# backend/data_quality.py
"""
数据质量校验：统一计算 run_days，检查矛盾、缺失、mock
🌰 类比：质检员，任何数字打架都会被发现
"""

from datetime import date
from backend.schemas import FundSnapshot, DataQualityReport, DataQualityLevel

REQUIRED_FOR_RATING = [
    "inception_date",
    "nav",
    "max_drawdown",
    "return_since_inception",
]

METRIC_FIELDS = [
    "nav", "accumulated_nav", "fund_size_bn",
    "return_since_inception", "return_1m", "return_3m",
    "return_6m", "return_1y", "return_3y",
    "max_drawdown", "volatility", "sharpe",
    "benchmark_return_pct", "alpha_pct",
]


def compute_run_days(inception_date: date | None, report_date: date) -> int | None:
    if not inception_date:
        return None
    return max((report_date - inception_date).days, 0)


def validate_snapshot(snapshot: FundSnapshot) -> DataQualityReport:
    missing        = []
    contradictions = []
    warnings       = []
    real_count     = 0
    mock_count     = 0

    # ✅ 统一计算并写入 run_days（唯一数据源）
    snapshot.run_days = compute_run_days(snapshot.inception_date, snapshot.report_date)

    # 检查必填字段
    for field in REQUIRED_FOR_RATING:
        if getattr(snapshot, field, None) is None:
            missing.append(field)

    # 检查每个指标
    for field in METRIC_FIELDS:
        metric = getattr(snapshot, field, None)
        if metric is None:
            continue
        if metric.is_mock:
            mock_count += 1
        else:
            real_count += 1
        # 检查数据日期是否晚于报告日期
        if metric.as_of and metric.as_of > snapshot.report_date:
            contradictions.append(
                f"{field}.as_of ({metric.as_of}) 晚于 report_date ({snapshot.report_date})"
            )

    # ✅ 关键：校验 peer_rank 内部一致性
    if snapshot.peer_rank:
        r = snapshot.peer_rank
        if r.rank and r.total:
            if r.rank > r.total:
                contradictions.append(
                    f"排名 {r.rank} 大于总数 {r.total}，数据矛盾"
                )
            if r.percentile is not None:
                expected = round(r.rank / r.total * 100, 2)
                if abs(r.percentile - expected) > 2.0:
                    contradictions.append(
                        f"percentile={r.percentile} 与 rank/total 计算值 {expected} 不符"
                    )

    # ✅ 关键：Alpha 一致性（P3）
    if (snapshot.return_since_inception and snapshot.benchmark_return_pct
            and snapshot.alpha_pct):
        fund_ret = snapshot.return_since_inception.value
        bench    = snapshot.benchmark_return_pct.value
        alpha    = snapshot.alpha_pct.value
        if (fund_ret is not None and bench is not None and alpha is not None):
            expected_alpha = round(float(fund_ret) - float(bench), 2)
            if abs(float(alpha) - expected_alpha) > 1.0:
                contradictions.append(
                    f"alpha={alpha} 与 fund_return-benchmark={expected_alpha} 不符"
                )

    # 运行时长警告
    if snapshot.run_days is None:
        warnings.append("无法确认基金运行天数，无法评级")
    elif snapshot.run_days < 180:
        warnings.append(f"基金运行仅 {snapshot.run_days} 天（< 6 个月），所有指标不具统计显著性")
    elif snapshot.run_days < 365:
        warnings.append(f"基金运行仅 {snapshot.run_days} 天（< 1 年），历史数据参考价值有限")
    elif snapshot.run_days < 730:
        warnings.append(f"基金运行 {snapshot.run_days} 天（< 2 年），未经历完整市场周期")

    # 判断总体质量等级
    if contradictions:
        level = DataQualityLevel.FAILED
    elif mock_count > 0 or missing:
        level = DataQualityLevel.PARTIAL
    else:
        level = DataQualityLevel.REAL

    can_generate_rating = (
        level in [DataQualityLevel.REAL, DataQualityLevel.PARTIAL]
        and not contradictions
        and "inception_date" not in missing
    )

    return DataQualityReport(
        level=level,
        real_metric_count=real_count,
        mock_metric_count=mock_count,
        missing_fields=missing,
        contradictions=contradictions,
        warnings=warnings,
        can_generate_rating=can_generate_rating,
        can_generate_report=(level != DataQualityLevel.FAILED),
    )
