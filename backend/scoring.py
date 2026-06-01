# backend/scoring.py
"""
确定性评分：代码是唯一裁判
核心修复：
1. mock数据的Alpha不参与评分
2. 风险等级与风控得分分离
3. 含mock核心数据时不输出正式综合分
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from backend.constants import (
    ALLOWED_RATINGS, ALLOWED_CONFIDENCE, ALLOWED_RISK_LEVELS,
    DRAWDOWN_RISK_MAP, DRAWDOWN_SCORE_MAP,
    SCORING_ELIGIBLE_NATURES
)


@dataclass
class ScoreResult:
    """评分结果（所有字段由代码填充，LLM 不得修改）"""
    history_score:      Optional[float]   # None = 不计算
    sentiment_score:    Optional[float]
    risk_control_score: Optional[float]   # 越高表示风控能力越好
    alpha_adjustment:   Optional[float]   # None = 不适用
    total_score:        Optional[float]   # None = 不输出正式综合分

    rating:             str               # 必须在 ALLOWED_RATINGS 中
    confidence_label:   str               # 必须在 ALLOWED_CONFIDENCE 中
    risk_level:         str               # 必须在 ALLOWED_RISK_LEVELS 中
    rating_cap_reason:  Optional[str]
    suitability:        str
    run_days:           Optional[int] = None   # V2.2 新增：传递运行天数给渲染层

    def __post_init__(self):
        from backend.value_cleaner import normalize_rating
        self.rating = normalize_rating(self.rating)
        assert self.confidence_label in ALLOWED_CONFIDENCE, \
            f"非法 confidence_label: {self.confidence_label}"
        assert self.risk_level in ALLOWED_RISK_LEVELS, \
            f"非法 risk_level: {self.risk_level}"

    @property
    def confidence(self) -> str:
        """兼容旧接口：confidence == confidence_label"""
        return self.confidence_label

    def to_json(self) -> str:
        """序列化为 JSON 字符串（供 graph.py state 使用）"""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "ScoreResult":
        """从 JSON 字符串反序列化（使用 .get 安全处理旧格式缺少的字段）"""
        d = json.loads(text)
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


# ============================================================
# 工具函数
# ============================================================

def _metric_val(metric) -> Optional[float]:
    """安全取指标值，仅当数据性质可参与评分时返回"""
    if metric is None or getattr(metric, 'value', None) is None:
        return None
    nature = getattr(metric, 'nature', None)
    if nature is not None:
        # 兼容新旧两种 schema
        nature_str = nature.value if hasattr(nature, 'value') else str(nature)
        if nature_str not in SCORING_ELIGIBLE_NATURES:
            return None
    return float(metric.value)


def _is_mock_or_suspicious(metric) -> bool:
    if metric is None:
        return False
    nature = getattr(metric, 'nature', None)
    if nature is None:
        return getattr(metric, 'is_mock', False)
    nature_str = nature.value if hasattr(nature, 'value') else str(nature)
    return nature_str in {"mock", "suspicious"}


def risk_level_from_drawdown(mdd: Optional[float]) -> str:
    """
    最大回撤 → 风险等级
    🌰 类比：最大曾经亏多少，决定这只基金有多危险
    270042: 31.18% → 中高
    161725: 65.45% → 极高
    026211:  9.22% → 低
    """
    if mdd is None:
        return "中高"
    mdd = abs(float(mdd))
    for threshold, level in DRAWDOWN_RISK_MAP:
        if mdd < threshold:
            return level
    return "极高"


def risk_control_score_from_drawdown(
    mdd: Optional[float],
    run_days: Optional[int]
) -> float:
    """
    风控得分（越高=风控越好）
    注意：这是风控「能力」评分，不是风险等级
    """
    if mdd is None:
        return 4.0
    mdd = abs(float(mdd))
    score = 4.0
    for threshold, s in DRAWDOWN_SCORE_MAP:
        if mdd < threshold:
            score = s
            break

    # 次新基金数据不可信，压低风控得分上限
    if run_days and run_days < 365:
        score = min(score, 4.5)

    return round(score, 1)


def has_core_mock_data(snapshot) -> bool:
    """
    检查核心指标是否含 mock/suspicious 数据
    核心指标：净值、收益率、回撤、基准收益
    """
    core_fields = [
        'unit_nav', 'nav',
        'return_since_inception',
        'max_drawdown',
        'benchmark_return', 'benchmark_return_pct',
    ]
    for field_name in core_fields:
        m = getattr(snapshot, field_name, None)
        if _is_mock_or_suspicious(m):
            return True
    return False


def compute_alpha_adjustment(snapshot) -> tuple[float, Optional[str]]:
    """
    计算 Alpha 调整分
    ✅ 只有基准收益是真实数据时才计算
    ✅ alpha 指标本身也必须是 calculated（不是 mock）
    返回 (adjustment, reason)
    """
    # 获取 alpha 字段（兼容新旧 schema）
    alpha_metric = getattr(snapshot, 'alpha', None) or getattr(snapshot, 'alpha_pct', None)
    bench_metric = (getattr(snapshot, 'benchmark_return', None)
                    or getattr(snapshot, 'benchmark_return_pct', None))

    # 基准收益是 mock → 不计算 Alpha
    if _is_mock_or_suspicious(bench_metric):
        return 0.0, "基准收益为模拟数据，Alpha 不参与评分"

    # Alpha 本身是 mock → 不计算
    if alpha_metric is None or _is_mock_or_suspicious(alpha_metric):
        return 0.0, "Alpha 数据不可用"

    alpha_val = _metric_val(alpha_metric)
    if alpha_val is None:
        return 0.0, "Alpha 值缺失"

    # 依赖项检查（如果 alpha 是 calculated，检查 depends_on）
    depends_on = getattr(alpha_metric, 'depends_on', [])
    for dep_field in depends_on:
        dep = getattr(snapshot, dep_field, None)
        if _is_mock_or_suspicious(dep):
            return 0.0, f"Alpha 依赖的 {dep_field} 为模拟数据"

    # 计算调整分
    if   alpha_val >= 20:  adj = 0.5
    elif alpha_val >= 10:  adj = 0.3
    elif alpha_val >= 5:   adj = 0.1
    elif alpha_val < -20:  adj = -0.5
    elif alpha_val < -10:  adj = -0.3
    else:                  adj = 0.0

    return adj, None


def compute_history_score(snapshot, run_days: Optional[int]) -> float:
    """历史业绩得分（0-10）"""
    run_days = run_days or 0

    # 基础分（运行时长决定上限）
    if   run_days < 180:  base = 3.0
    elif run_days < 365:  base = 4.5
    elif run_days < 730:  base = 5.5
    else:                 base = 6.0

    # 取最优可用收益率
    ret = (
        _metric_val(getattr(snapshot, 'return_3y', None))
        or _metric_val(getattr(snapshot, 'return_1y', None))
        or _metric_val(getattr(snapshot, 'return_since_inception', None))
    )

    if ret is not None:
        if   ret >= 150: base += 2.5
        elif ret >= 100: base += 2.0
        elif ret >= 50:  base += 1.2
        elif ret >= 20:  base += 0.6
        elif ret < 0:    base -= 2.0

    return round(max(0.0, min(base, 10.0)), 1)


# Backward-compat wrappers for old tests
def score_history(snapshot) -> float:
    """兼容旧接口"""
    return compute_history_score(snapshot, getattr(snapshot, 'run_days', None))


def score_risk(snapshot) -> float:
    """兼容旧接口"""
    mdd_metric = (getattr(snapshot, 'max_drawdown', None)
                  or getattr(snapshot, 'max_drawdown_pct', None))
    mdd_val = None
    if mdd_metric:
        raw_val = getattr(mdd_metric, 'value', None)
        if raw_val is not None and not _is_mock_or_suspicious(mdd_metric):
            mdd_val = abs(float(raw_val))
    return risk_control_score_from_drawdown(mdd_val, getattr(snapshot, 'run_days', None))


SUITABILITY_MAP = {
    "适合配置": "适合高风险承受能力、资金期限 3 年以上、以组合卫星仓位配置的投资者",
    "谨慎关注": "可小比例配置，需能承受阶段性较大回撤，不适合保守型投资者",
    "持续观察": "基金数据不足，仅建议观察，不建议基于短期表现配置",
    "信息不足": "含模拟或缺失数据，无法形成有效配置结论，请以官方渠道数据为准",
    "风险较高": "历史回撤或波动性较高，仅适合能承受大幅亏损的积极投资者",
    "无法评级": "数据存在矛盾，需修复数据后重新分析",
}


def score_fund(
    snapshot,
    quality,
    sentiment_score: float = 5.0,
) -> ScoreResult:
    """
    确定性评分主入口

    评分决策树：
    1. 数据矛盾 → 无法评级，不计算任何分数
    2. 核心含 mock 或关键字段缺失 → 信息不足，不计算综合分
    3. 运行 < 365天 → 持续观察，不计算综合分
    4. 正常 → 计算完整分数
    """
    run_days = getattr(snapshot, 'run_days', None) or 0

    # 获取回撤值（用于风险计算）
    mdd_metric = (getattr(snapshot, 'max_drawdown', None)
                  or getattr(snapshot, 'max_drawdown_pct', None))
    mdd_val    = None
    if mdd_metric:
        raw_val = getattr(mdd_metric, 'value', None)
        if raw_val is not None and not _is_mock_or_suspicious(mdd_metric):
            mdd_val = abs(float(raw_val))

    risk_level         = risk_level_from_drawdown(mdd_val)
    risk_ctrl_score    = risk_control_score_from_drawdown(mdd_val, run_days)

    # 获取 quality 字段（兼容新旧）
    contradictions = getattr(quality, 'contradictions', [])
    mock_count     = getattr(quality, 'mock_metric_count', 0)
    missing_fields = getattr(quality, 'missing_fields', [])

    # ============ 路径1：数据矛盾 ============
    if contradictions:
        return ScoreResult(
            history_score=None, sentiment_score=None,
            risk_control_score=None, alpha_adjustment=None,
            total_score=None,
            rating="无法评级",
            confidence_label="低",
            risk_level=risk_level,
            rating_cap_reason=f"数据存在 {len(contradictions)} 处矛盾，已停止评级",
            suitability=SUITABILITY_MAP["无法评级"],
        )

    # ============ 路径2：核心含 mock 或关键字段缺失 ============
    core_has_mock = has_core_mock_data(snapshot)
    if core_has_mock or mock_count > 0 or missing_fields:
        return ScoreResult(
            history_score=None,
            sentiment_score=round(max(0, min(sentiment_score, 10)), 1),
            risk_control_score=risk_ctrl_score,
            alpha_adjustment=None,   # ✅ mock 基准不计算 Alpha
            total_score=None,        # ✅ 不输出正式综合分
            rating="信息不足",
            confidence_label="低",   # ✅ 含 mock 时置信度强制为低
            risk_level=risk_level,
            rating_cap_reason=(
                f"含 {mock_count} 项模拟数据，不输出正式评级"
                if mock_count > 0 else
                f"缺失关键字段 {missing_fields}，不输出正式评级"
            ),
            suitability=SUITABILITY_MAP["信息不足"],
        )

    # ============ 路径3：次新基金 ============
    if run_days < 365:
        # ✅ V1.7 修复：次新基金风险等级用 compute_risk_level()，不能只看短期回撤
        fund_name_v = getattr(snapshot, 'name', '') or ''
        fund_type_v = getattr(snapshot, 'fund_type', '') or ''
        risk_level_final = compute_risk_level(
            max_drawdown_pct=mdd_val,
            fund_name=fund_name_v,
            fund_type=fund_type_v,
            run_days=run_days,
        )
        return ScoreResult(
            history_score=compute_history_score(snapshot, run_days),
            sentiment_score=round(max(0, min(sentiment_score, 10)), 1),
            risk_control_score=risk_ctrl_score,
            alpha_adjustment=None,   # ✅ V1.7 修复：次新基金 Alpha 强制 None
            total_score=None,        # ✅ 次新基金不输出综合分
            rating="持续观察",
            confidence_label="低",
            risk_level=risk_level_final,   # ✅ 使用综合风险等级
            rating_cap_reason=f"运行仅 {run_days} 天（< 1年），评级上限为持续观察",
            suitability=SUITABILITY_MAP["持续观察"],
            run_days=run_days,
        )

    # ============ 路径4：正常计算 ============
    history  = compute_history_score(snapshot, run_days)
    sentiment = round(max(0, min(float(sentiment_score), 10)), 1)

    alpha_adj, alpha_reason = compute_alpha_adjustment(snapshot)

    total = round(
        history   * 0.40
        + sentiment * 0.30
        + risk_ctrl_score * 0.30
        + alpha_adj,
        1
    )
    total = round(max(0.0, min(total, 10.0)), 1)

    # 确定置信度
    if run_days >= 1095:   confidence = "高"   # 3年以上
    elif run_days >= 730:  confidence = "中"
    else:                  confidence = "低"

    # 确定评级（高风险覆盖高得分）
    if   risk_level in {"高", "极高"} and total < 7.0:
        raw_rating = "风险较高"
    elif total >= 7.5:   raw_rating = "适合配置"
    elif total >= 5.5:   raw_rating = "谨慎关注"
    else:                raw_rating = "风险较高"

    return ScoreResult(
        history_score=history,
        sentiment_score=sentiment,
        risk_control_score=risk_ctrl_score,
        alpha_adjustment=alpha_adj,
        total_score=total,
        rating=raw_rating,
        confidence_label=confidence,
        risk_level=risk_level,
        rating_cap_reason=alpha_reason if alpha_reason else None,
        suitability=SUITABILITY_MAP.get(raw_rating, "请咨询专业投资顾问"),
    )


# ============================================================
# V2.2 新增：综合风险等级计算
# ============================================================

# 最大回撤 → 基础风险等级映射
_DRAWDOWN_TO_RISK_LEVEL = [
    (0.05,  "低"),
    (0.10,  "中低"),
    (0.20,  "中"),
    (0.30,  "中高"),
    (0.40,  "高"),
    (float('inf'), "极高"),
]

# 基金类型/名称关键词 → 最低风险等级
_FUND_TYPE_MIN_RISK = {
    "科技":    "中高",
    "QDII":    "中高",
    "纳斯达克": "高",
    "新能源":  "中高",
    "半导体":  "高",
    "机器人":  "高",
    "AI":      "中高",
    "消费":    "中",
    "债券":    "低",
    "货币":    "低",
    "货币型":  "低",
}

_RISK_LEVEL_ORDER = ["低", "中低", "中", "中高", "高", "极高"]


def _risk_level_max(a: str, b: str) -> str:
    """返回两个风险等级中较高的那个"""
    ia = _RISK_LEVEL_ORDER.index(a) if a in _RISK_LEVEL_ORDER else 2
    ib = _RISK_LEVEL_ORDER.index(b) if b in _RISK_LEVEL_ORDER else 2
    return _RISK_LEVEL_ORDER[max(ia, ib)]


def compute_risk_level(
    max_drawdown_pct: Optional[float],
    fund_name:        str = "",
    fund_type:        str = "",
    run_days:         Optional[int] = None,
) -> str:
    """
    V2.2 修复：综合考虑 最大回撤 + 基金名称/类型关键词 + 运行时长
    次新基金(<180天)：回撤样本不足，强制至少中风险
    科技/QDII类：有最低风险等级下限
    """
    # Step1: 按回撤判断基础等级
    if max_drawdown_pct is None:
        base_level = "中"
    else:
        dd_abs = abs(max_drawdown_pct) / 100 if abs(max_drawdown_pct) > 1 else abs(max_drawdown_pct)
        base_level = "极高"
        for threshold, level in _DRAWDOWN_TO_RISK_LEVEL:
            if dd_abs <= threshold:
                base_level = level
                break

    # Step2: 次新基金（<180天）回撤样本不足，至少中风险
    if run_days is not None and run_days < 180:
        base_level = _risk_level_max(base_level, "中")

    # Step3: 基金名称/类型关键词推高下限
    combined = (fund_name or "") + (fund_type or "")
    for keyword, min_level in _FUND_TYPE_MIN_RISK.items():
        if keyword in combined:
            base_level = _risk_level_max(base_level, min_level)

    return base_level


# ============================================================
# V2.2 新增：新版评分主函数（graph.py 可选切换）
# ============================================================

def _calc_history_score(
    ret_since_inception: Optional[float],
    ret_1y: Optional[float],
    ret_3y: Optional[float],
    run_days: Optional[int],
) -> Optional[float]:
    if ret_since_inception is None:
        return None
    base = min(max(ret_since_inception / 10, 0), 8)
    if ret_1y:
        base = base * 0.5 + min(max(ret_1y / 10, 0), 8) * 0.5
    if ret_3y:
        base = base * 0.4 + min(max(ret_3y / 15, 0), 8) * 0.6
    if run_days:
        if run_days < 180:   base = max(base - 3, 0)
        elif run_days < 365: base = max(base - 2, 0)
        elif run_days < 730: base = max(base - 1, 0)
    return round(base, 1)


def _calc_risk_control_score(max_drawdown_pct: Optional[float], run_days: Optional[int]) -> Optional[float]:
    if max_drawdown_pct is None:
        return None
    dd = abs(max_drawdown_pct) / 100 if abs(max_drawdown_pct) > 1 else abs(max_drawdown_pct)
    if dd <= 0.05:   base = 9.0
    elif dd <= 0.10: base = 7.5
    elif dd <= 0.20: base = 6.0
    elif dd <= 0.30: base = 4.0
    elif dd <= 0.40: base = 2.5
    else:            base = 1.0
    if run_days and run_days < 365:
        base = max(base - 1.5, 1.0)
    return round(base, 1)


def _score_to_rating_v2(total: float, run_days: Optional[int]):
    if run_days and run_days < 365:
        return "持续观察", "低"
    if total >= 8.0:  return "适合配置", "高"
    if total >= 6.5:  return "谨慎关注", "中"
    if total >= 5.0:  return "持续观察", "中"
    return "风险较高", "低"


_SUITABILITY_V2 = {
    "适合配置": "适合风险承受能力匹配的长期投资者",
    "谨慎关注": "适合有一定风险承受能力的投资者，建议小仓位观察",
    "持续观察": "次新基金，建议持续观察，暂不作为配置依据",
    "风险较高": "风险较高，不建议配置",
    "信息不足": "数据不足，无法给出配置建议",
    "无法评级": "数据存在矛盾，无法评级",
}


def calculate_score(
    snapshot,
    sentiment_score: Optional[float],
    benchmark_return: Optional[float] = None,
) -> ScoreResult:
    """
    V2.2 新版评分主函数。
    ✅ Alpha：基准未确认或次新基金(<365天) → 强制 None
    ✅ 风险等级：使用 compute_risk_level()（综合回撤+类型+运行时长）
    """
    run_days  = getattr(snapshot, 'run_days', None)
    fund_name = getattr(snapshot, 'name', '') or ''
    fund_type = getattr(snapshot, 'fund_type', '') or ''
    benchmark = getattr(snapshot, 'benchmark', None)
    bench_is_matched = getattr(benchmark, 'is_matched', False) if benchmark else False

    # 取回撤值
    mdd_metric = (getattr(snapshot, 'max_drawdown', None)
                  or getattr(snapshot, 'max_drawdown_pct', None))
    drawdown_v = getattr(mdd_metric, 'value', mdd_metric) if mdd_metric else None
    if drawdown_v is not None:
        drawdown_v = float(drawdown_v)

    # 历史业绩分
    ret_since = getattr(snapshot, 'return_since_inception', None)
    ret_1y    = getattr(snapshot, 'return_1y', None)
    ret_3y    = getattr(snapshot, 'return_3y', None)
    history_score = _calc_history_score(
        ret_since_inception=getattr(ret_since, 'value', ret_since) if ret_since else None,
        ret_1y=getattr(ret_1y, 'value', ret_1y) if ret_1y else None,
        ret_3y=getattr(ret_3y, 'value', ret_3y) if ret_3y else None,
        run_days=run_days,
    )

    # 风险控制分
    risk_control_score = _calc_risk_control_score(drawdown_v, run_days)

    # Alpha 调整：次新基金或基准未确认 → None
    alpha_adjustment = None
    if bench_is_matched and run_days and run_days >= 365:
        ret_since_v = getattr(ret_since, 'value', None) if ret_since else None
        if ret_since_v is not None and benchmark_return is not None:
            alpha_val = float(ret_since_v) - float(benchmark_return)
            alpha_adjustment = round(min(max(alpha_val / 10, -1.0), 1.0), 2)

    # 综合评分
    cap_reason = None
    if run_days is not None and run_days < 365:
        total_score = None
        cap_reason  = f"运行仅 {run_days} 天（< 1年），评级上限为持续观察"
        rating      = "持续观察"
        confidence  = "低"
    elif history_score is None or sentiment_score is None or risk_control_score is None:
        total_score = None
        cap_reason  = "核心指标数据不足"
        rating      = "信息不足"
        confidence  = "低"
    else:
        raw = (
            history_score     * 0.40
            + sentiment_score * 0.30
            + risk_control_score * 0.30
            + (alpha_adjustment or 0)
        )
        total_score = round(min(max(raw, 0), 10), 1)
        rating, confidence = _score_to_rating_v2(total_score, run_days)

    # 风险等级（综合判断）
    risk_level = compute_risk_level(
        max_drawdown_pct=drawdown_v,
        fund_name=fund_name,
        fund_type=fund_type,
        run_days=run_days,
    )

    suitability = _SUITABILITY_V2.get(rating, "暂无建议")
    if run_days and run_days < 365 and rating == "持续观察":
        suitability = "次新基金，建议持续观察，暂不作为配置依据"

    return ScoreResult(
        history_score=history_score,
        sentiment_score=sentiment_score,
        risk_control_score=risk_control_score,
        alpha_adjustment=alpha_adjustment,
        total_score=total_score,
        rating=rating,
        confidence_label=confidence,
        risk_level=risk_level,
        rating_cap_reason=cap_reason,
        suitability=suitability,
        run_days=run_days,
    )
