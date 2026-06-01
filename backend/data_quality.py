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
    elif snapshot.run_days is not None and snapshot.run_days < 365:
        # ✅ V2.2/V1.7 修复：次新基金数据来源真实但样本不足 → LIMITED
        level = DataQualityLevel.LIMITED
    else:
        level = DataQualityLevel.REAL

    can_generate_rating = (
        level in [DataQualityLevel.REAL, DataQualityLevel.LIMITED, DataQualityLevel.PARTIAL]
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
        run_days=snapshot.run_days,   # ✅ V2.2 新增：传递给渲染层
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


# ============================================================
# V2.2 新增：QualityResult 和 assess_quality（含 limited 等级）
# ============================================================

from dataclasses import dataclass, field as dc_field
from typing import List
import json as _json


@dataclass
class QualityResult:
    """V2.2 新增：更丰富的数据质量结果，含 limited 等级和 summary 文本"""
    level:               str              # real / limited / partial / failed / unavailable
    mock_metric_count:   int = 0
    real_metric_count:   int = 0
    contradictions:      List[str] = dc_field(default_factory=list)
    warnings:            List[str] = dc_field(default_factory=list)
    run_days:            int = None
    summary:             str = ""

    def to_json(self) -> str:
        return _json.dumps({
            "level":               self.level,
            "mock_metric_count":   self.mock_metric_count,
            "real_metric_count":   self.real_metric_count,
            "contradictions":      self.contradictions,
            "warnings":            self.warnings,
            "run_days":            self.run_days,
            "summary":             self.summary,
        }, ensure_ascii=False)


_METRIC_ATTRS = [
    'unit_nav', 'nav', 'accumulated_nav', 'fund_size', 'fund_size_bn',
    'return_since_inception', 'return_1y', 'return_3y',
    'max_drawdown', 'max_drawdown_pct',
    'benchmark_return', 'benchmark_return_pct',
    'alpha', 'alpha_pct',
]


def assess_quality(snapshot) -> QualityResult:
    """
    V2.2 综合评估数据质量。
    ✅ 新增 limited 等级：次新基金（run_days<365），数据来源真实但样本不足
    """
    run_days       = getattr(snapshot, 'run_days', None)
    warnings       = []
    contradictions = []
    mock_count     = 0
    real_count     = 0

    # 统计 mock / real 指标数量
    for attr in _METRIC_ATTRS:
        m = getattr(snapshot, attr, None)
        if m is None:
            continue
        if getattr(m, 'is_mock', False):
            mock_count += 1
        elif getattr(m, 'value', None) is not None:
            real_count += 1

    # 排名 mock 检查
    ranking = getattr(snapshot, 'ranking', None) or getattr(snapshot, 'peer_rank', None)
    if ranking and getattr(ranking, 'is_mock', False):
        mock_count += 1

    # 一致性检验
    contradictions.extend(_aq_check_rank_overflow(snapshot))
    contradictions.extend(_aq_check_nav_consistency(snapshot))
    contradictions.extend(_aq_check_alpha_validity(snapshot))

    # 次新基金警告
    if run_days is not None:
        if run_days < 180:
            warnings.append(f"基金运行仅 {run_days} 天（< 6个月），所有指标不具统计显著性")
        elif run_days < 365:
            warnings.append(f"基金运行仅 {run_days} 天（< 1年），历史业绩参考意义有限")

    # 基准缺失警告
    benchmark = getattr(snapshot, 'benchmark', None)
    if benchmark is None or not getattr(benchmark, 'is_matched', False):
        warnings.append("基准指数未确认，Alpha 不计算")

    # 判断 level
    if len(contradictions) > 0:
        level = "failed"
    elif mock_count > real_count and real_count < 3:
        level = "unavailable"
    elif mock_count > 0:
        level = "partial"
    elif run_days is not None and run_days < 365:
        # ✅ 次新基金：数据来源真实但样本不足 → limited
        level = "limited"
    else:
        level = "real"

    summary = _aq_build_summary(level, mock_count, real_count, warnings, contradictions, run_days)

    return QualityResult(
        level=level,
        mock_metric_count=mock_count,
        real_metric_count=real_count,
        contradictions=contradictions,
        warnings=warnings,
        run_days=run_days,
        summary=summary,
    )


def _aq_build_summary(level, mock_count, real_count, warnings, contradictions, run_days) -> str:
    lines = []
    if level == "real":
        lines.append("✅ 核心指标均来自外部数据接口，未检测到模拟数据")
    elif level == "limited":
        lines.append(f"⚠️ 数据来源真实，但运行仅 {run_days} 天，样本量不足，统计意义有限")
    elif level == "partial":
        lines.append(f"⚠️ {mock_count} 项指标为模拟数据，适配结论为「信息不足」")
    elif level == "failed":
        lines.append(f"🔴 检测到 {len(contradictions)} 处数据矛盾，适配结论为「无法评级」")
    else:
        lines.append("🔴 数据严重不足，无法生成有效分析")

    if warnings:
        lines.append("\n**数据警告：**")
        for w in warnings:
            lines.append(f"- {w}")
    if contradictions:
        lines.append("\n**数据矛盾：**")
        for c in contradictions:
            lines.append(f"- ⛔ {c}")
    return "\n".join(lines)


def _aq_check_rank_overflow(snapshot) -> list:
    errors = []
    pr = getattr(snapshot, 'peer_rank', None)
    if pr is None:
        return errors
    rank  = getattr(pr, 'rank', None)
    total = getattr(pr, 'total', None)
    if rank and total:
        try:
            if int(rank) > int(total):
                errors.append(f"排名溢出：rank={rank} > total={total}")
        except (TypeError, ValueError):
            pass
    return errors


def _aq_check_nav_consistency(snapshot) -> list:
    errors = []
    unit_nav = getattr(snapshot, 'unit_nav', None) or getattr(snapshot, 'nav', None)
    acc_nav  = getattr(snapshot, 'accumulated_nav', None)
    if unit_nav and acc_nav:
        uv = getattr(unit_nav, 'value', unit_nav)
        av = getattr(acc_nav, 'value', acc_nav)
        try:
            if float(av) < float(uv) * 0.9:
                errors.append(f"累计净值({av})异常低于单位净值({uv})")
        except (TypeError, ValueError):
            pass
    return errors


def _aq_check_alpha_validity(snapshot) -> list:
    errors = []
    benchmark = getattr(snapshot, 'benchmark', None)
    if benchmark is None:
        return errors
    is_matched = getattr(benchmark, 'is_matched', False)
    alpha = getattr(snapshot, 'alpha', None) or getattr(snapshot, 'alpha_pct', None)
    if alpha and not is_matched:
        av = getattr(alpha, 'value', alpha)
        if av is not None and not getattr(alpha, 'is_mock', False):
            errors.append(f"Alpha={av} 但基准指数未确认，存在口径矛盾")
    return errors
