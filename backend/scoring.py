# backend/scoring.py
"""
确定性评分：代码是唯一裁判，LLM 不能修改评分
🌰 类比：考试分数由机器阅卷，不允许 AI 猜分
"""

from backend.schemas import (
    FundSnapshot, DataQualityReport, ScoreBreakdown,
    DataQualityLevel
)


def _val(metric, default=None):
    """安全取 MetricSource.value"""
    return float(metric.value) if (metric and metric.value is not None) else default


def score_history(snapshot: FundSnapshot) -> float:
    """
    历史业绩评分（0-10）
    次新基金起评分压低，防止短期暴涨误导
    """
    run_days = snapshot.run_days or 0

    # 基础分（由运行时长决定上限）
    if run_days < 180:
        base = 3.0
    elif run_days < 365:
        base = 4.5
    elif run_days < 730:
        base = 5.5
    else:
        base = 6.0

    # 取最优可用收益率
    ret = (_val(snapshot.return_3y)
           or _val(snapshot.return_1y)
           or _val(snapshot.return_since_inception))

    if ret is None:
        return round(min(base, 5.0), 1)

    # 收益加分
    if   ret >= 150: base += 2.5
    elif ret >= 100: base += 2.0
    elif ret >= 50:  base += 1.2
    elif ret >= 20:  base += 0.6
    elif ret >= 0:   base += 0.0
    else:            base -= 2.0   # 负收益减分

    # P3：Alpha 奖励
    alpha = _val(snapshot.alpha_pct)
    if alpha is not None:
        if   alpha >= 20:  base += 1.0
        elif alpha >= 5:   base += 0.5
        elif alpha < -10:  base -= 1.0  # 跑输基准减分

    return round(max(0, min(base, 10)), 1)


def score_risk(snapshot: FundSnapshot) -> float:
    """
    风险控制评分（0-10，越高越好）
    """
    mdd = _val(snapshot.max_drawdown)

    if mdd is None:
        base = 5.0
    else:
        mdd = abs(mdd)
        if   mdd < 5:  base = 9.0
        elif mdd < 10: base = 8.0
        elif mdd < 20: base = 6.5
        elif mdd < 30: base = 5.0
        elif mdd < 40: base = 3.5
        else:          base = 2.0

    # 次新基金：回撤数据不可靠，降低置信度
    run_days = snapshot.run_days or 0
    if   run_days < 180: base -= 2.0
    elif run_days < 365: base -= 1.5
    elif run_days < 730: base -= 0.5

    return round(max(0, min(base, 10)), 1)


def _determine_confidence(run_days: int | None) -> str:
    if run_days is None or run_days < 365:
        return "低"
    elif run_days < 730:
        return "中"
    else:
        return "高"


def apply_rating_cap(
    raw_rating: str,
    snapshot:   FundSnapshot,
    quality:    DataQualityReport,
) -> tuple[str, str | None]:
    """
    评级上限规则（硬性，不可绕过）
    返回：(最终评级, 降级原因)
    """
    # 数据矛盾：无法评级
    if quality.level == DataQualityLevel.FAILED:
        return "无法评级", "数据存在硬性矛盾，已停止评级"

    # 存在 mock 数据：信息不足
    if quality.mock_metric_count > 0:
        return "信息不足", f"含 {quality.mock_metric_count} 项模拟数据，不输出投资评级"

    # 关键字段缺失
    if quality.missing_fields:
        return "信息不足", f"缺失关键字段：{', '.join(quality.missing_fields)}"

    # 无法确认运行天数
    if snapshot.run_days is None:
        return "信息不足", "无法确认基金运行天数"

    # 次新基金上限
    if snapshot.run_days < 180:
        return "持续观察", f"运行仅 {snapshot.run_days} 天（< 6 个月），评级上限为持续观察"

    if snapshot.run_days < 365:
        return "谨慎关注", f"运行 {snapshot.run_days} 天（< 1 年），评级上限为谨慎关注"

    if snapshot.run_days < 730 and raw_rating in ["适合配置"]:
        return "积极关注", "运行不足 2 年，评级上限为积极关注"

    return raw_rating, None


SUITABILITY_MAP = {
    "适合配置": "适合高风险承受能力、资金期限 3 年以上、组合卫星仓位投资者",
    "积极关注": "可纳入观察池，适合高风险承受能力投资者分批小比例配置",
    "谨慎关注": "建议继续观察，等待更多历史数据或更好估值区间",
    "持续观察": "数据不足，仅建议观察，不建议基于短期表现配置",
    "信息不足": "数据不足，无法形成有效配置结论，请以官方渠道数据为准",
    "无法评级": "数据存在矛盾，需修复数据后重新生成报告",
    "回避":     "风险收益特征不佳或与普通投资者风险承受能力不匹配",
}


def score_fund(
    snapshot:        FundSnapshot,
    quality:         DataQualityReport,
    sentiment_score: float = 5.0,
) -> ScoreBreakdown:
    """
    确定性评分主入口
    sentiment_score 由舆情 Agent 输出后，graph 层面注入
    """
    history   = score_history(snapshot)
    risk      = score_risk(snapshot)
    sentiment = round(max(0, min(float(sentiment_score), 10)), 1)

    # P3：Alpha 奖励分（单独计算，不与 history_score 重复）
    alpha_bonus = 0.0
    alpha = _val(snapshot.alpha_pct)
    if alpha is not None:
        if   alpha >= 20: alpha_bonus = 0.5
        elif alpha >= 10: alpha_bonus = 0.3
        elif alpha < -10: alpha_bonus = -0.3

    total = round(
        history   * 0.40
        + sentiment * 0.30
        + risk      * 0.30
        + alpha_bonus,
        1
    )
    total = round(max(0, min(total, 10)), 1)

    # 原始评级
    if   total >= 8.0: raw_rating = "适合配置"
    elif total >= 6.5: raw_rating = "积极关注"
    elif total >= 5.0: raw_rating = "谨慎关注"
    else:              raw_rating = "回避"

    # 应用硬性上限
    rating, cap_reason = apply_rating_cap(raw_rating, snapshot, quality)

    return ScoreBreakdown(
        history_score=history,
        sentiment_score=sentiment,
        risk_score=risk,
        alpha_bonus=alpha_bonus,
        total_score=total,
        confidence=_determine_confidence(snapshot.run_days),
        rating=rating,
        rating_cap_reason=cap_reason,
        suitability=SUITABILITY_MAP.get(rating, "请咨询专业投资顾问"),
    )
