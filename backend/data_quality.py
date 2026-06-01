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


# ============================================================
# V2.1 新增：一致性校验函数
# ============================================================

def validate_nav_consistency(snapshot) -> list[str]:
    """
    校验单位净值与累计净值的一致性
    🌰 类比：一个人现在的身高不可能低于出生时的身高
    """
    warnings = []

    unit_metric = getattr(snapshot, 'unit_nav', None) or getattr(snapshot, 'nav', None)
    acc_metric  = getattr(snapshot, 'accumulated_nav', None)

    if unit_metric is None or acc_metric is None:
        return warnings

    unit_val = getattr(unit_metric, 'value', None)
    acc_val  = getattr(acc_metric,  'value', None)

    if unit_val is None or acc_val is None:
        return warnings

    try:
        unit_f = float(unit_val)
        acc_f  = float(acc_val)

        # 累计净值 < 单位净值：通常说明数据有问题
        # 注意：有分红的基金累计净值 > 单位净值，没分红时两者相等
        if acc_f < unit_f and acc_f > 0:
            # 如果累计净值是 1.0 且单位净值远大于 1，很可能是写死了
            if abs(acc_f - 1.0) < 0.001 and unit_f > 1.5:
                warnings.append(
                    f"累计净值疑似写死为 1.0（单位净值={unit_f:.4f}），"
                    "请检查 data_fetcher 是否正确获取累计净值走势"
                )
                # 标记为 suspicious
                try:
                    from backend.schemas import DataNature
                    acc_metric.nature = DataNature.SUSPICIOUS
                    acc_metric.confidence = 0.1
                except Exception:
                    pass
            else:
                warnings.append(
                    f"累计净值({acc_f:.4f}) < 单位净值({unit_f:.4f})，"
                    "可能存在数据口径问题"
                )
    except (TypeError, ValueError):
        pass

    return warnings


def validate_time_window_consistency(snapshot) -> list[str]:
    """
    校验收益率时间窗口与运行天数是否匹配
    🌰 类比：不能说一个刚出生3个月的孩子的"近1年成绩"
    """
    warnings = []
    run_days = getattr(snapshot, 'run_days', None)

    if run_days is None:
        return warnings

    checks = [
        ('return_1y',  365, "近1年收益"),
        ('return_3y',  730, "近3年收益（至少2年数据）"),
    ]

    for field_name, min_days, label in checks:
        metric = getattr(snapshot, field_name, None)
        if metric is None:
            continue
        val = getattr(metric, 'value', None)
        if val is None:
            continue
        if run_days < min_days:
            warnings.append(
                f"基金运行仅 {run_days} 天，但存在「{label}」数据，"
                "该数据可能为系统标签错误（实际为成立以来收益）"
            )
            # 标记为可疑
            try:
                from backend.schemas import DataNature
                metric.nature = DataNature.SUSPICIOUS
                metric.confidence = 0.2
                metric.note = f"实际运行仅 {run_days} 天，「{label}」标签可能不准确"
            except Exception:
                pass

    return warnings


def validate_benchmark_consistency(snapshot) -> list[str]:
    """
    校验基准指数识别是否与基金名称一致
    """
    warnings = []
    benchmark = getattr(snapshot, 'benchmark', None)
    if benchmark is None:
        return warnings

    mismatch = getattr(benchmark, 'mismatch_warning', None)
    if mismatch:
        warnings.append(f"基准匹配警告：{mismatch}")

    if not getattr(benchmark, 'is_matched', True):
        warnings.append(
            f"基准指数「{getattr(benchmark, 'name', '未知')}」"
            "未能从基金名称确认，Alpha 计算结果可信度较低"
        )

    return warnings


def validate_mock_count_consistency(snapshot, quality) -> list[str]:
    """
    校验 mock_count 的数量是否前后一致
    （防止报告说"2项模拟"，风险分析说"3个模拟"）
    """
    warnings = []

    # 重新计算 mock 数量
    metric_fields = [
        'unit_nav', 'nav', 'accumulated_nav', 'fund_size', 'fund_size_bn',
        'return_since_inception', 'return_1y', 'return_3y',
        'max_drawdown', 'benchmark_return', 'benchmark_return_pct',
        'alpha', 'alpha_pct',
    ]
    actual_mock = 0
    for f in metric_fields:
        m = getattr(snapshot, f, None)
        if m is None:
            continue
        nature_str = ""
        nature = getattr(m, 'nature', None)
        if nature:
            nature_str = nature.value if hasattr(nature, 'value') else str(nature)
        is_mock_flag = getattr(m, 'is_mock', False)
        if nature_str == 'mock' or is_mock_flag:
            actual_mock += 1

    reported_mock = getattr(quality, 'mock_metric_count', -1)
    if reported_mock >= 0 and abs(reported_mock - actual_mock) > 0:
        warnings.append(
            f"mock 数量不一致：quality 报告 {reported_mock} 项，"
            f"重新计算为 {actual_mock} 项，请检查 validate_snapshot 逻辑"
        )

    return warnings
