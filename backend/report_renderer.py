# backend/report_renderer.py
"""
模板化报告渲染 V2.2：所有结构化字段由代码填充，LLM 只提供解释文字
V2.2 修复：
- _safe_nature_display(): 任何未知 DataNature 值 → "⬜ 缺失"（不透传"阿富汗"等）
- add_row_fixed(): None/missing → "数据缺失"（不是"数据援助"）
- render_metric_table(): Alpha 行增加基准确认判断
- render_score_table(): 说明列全 hardcode，不依赖 auto_fix
- _clean_commentary(): 新增去重情绪评分逻辑
- render_quality_text(): 支持新 QualityResult.summary 属性
- render_report(): new_fund_banner 语序修正，基准缺失显示"数据缺失"
"""

import re
from typing import Optional, Any

from backend.constants import ALLOWED_RISK_LEVELS


# ============================================================
# 常量：DataNature → 显示文本（只在这里定义，统一使用）
# ============================================================
_NATURE_DISPLAY = {
    "real":        "✅ 真实",
    "calculated":  "✅ 计算",
    "mock":        "🔴 模拟",
    "suspicious":  "🟡 存疑",
    "missing":     "⬜ 缺失",
    # 防御：任何未知值映射到"⬜ 缺失"，绝不透传原始值
}

# 来源脏值本地清洗表（不依赖外部函数抛异常）
_DIRTY_SOURCE_FIX = {
    "嘲笑": "mock",
    "计算": "calculated",
    "模拟": "mock",
    "真实": "akshare",
    "akShare": "akshare",
    "官方": "official",
}

_ALLOWED_SOURCES = {
    "akshare", "tavily", "calculated",
    "official", "missing", "mock", "unknown",
}


# ============================================================
# 核心辅助函数
# ============================================================

def _safe_nature_display(metric) -> str:
    """
    安全将 MetricSource.nature 转换为显示文本。
    ✅ 三层防御：
      1. is_mock → 🔴 模拟
      2. safe_nature_key 在 _NATURE_DISPLAY 中 → 正常返回
      3. 任何其他值（含"阿富汗"/"真实"等历史脏值）→ "⬜ 缺失"
    """
    if metric is None:
        return "⬜ 缺失"
    is_mock = getattr(metric, 'is_mock', False)
    if is_mock:
        return "🔴 模拟"

    nature = getattr(metric, 'nature', None)
    if nature is None:
        return "⬜ 缺失"

    # 优先使用 safe_nature_key 属性（MetricSource V2.2 有此属性）
    if hasattr(metric, 'safe_nature_key'):
        key = metric.safe_nature_key
    else:
        key = nature.value if hasattr(nature, 'value') else str(nature)

    # 主查表
    result = _NATURE_DISPLAY.get(key)
    if result is not None:
        return result

    # 中文旧值兼容
    _LEGACY = {
        "真实": "✅ 真实", "计算": "✅ 计算",
        "模拟": "🔴 模拟", "缺失": "⬜ 缺失", "存疑": "🟡 存疑",
    }
    return _LEGACY.get(key, "⬜ 缺失")  # ✅ 终极兜底


def _safe_value_display(metric, suffix: str = "") -> str:
    """安全显示指标数值，含后缀。metric/value 为 None → '数据缺失'"""
    if metric is None:
        return "数据缺失"
    val = getattr(metric, 'value', None)
    if val is None:
        return "数据缺失"
    if isinstance(val, float):
        val_str = f"{val:.4f}" if abs(val) < 10 else f"{val:.2f}"
    else:
        val_str = str(val)
    return val_str + suffix


def fmt_source(metric) -> str:
    """返回来源字符串。本地清洗脏值，不依赖外部函数抛异常。"""
    if metric is None:
        return "—"
    src = getattr(metric, 'source', None) or 'unknown'
    src = _DIRTY_SOURCE_FIX.get(src, src)
    return src if src in _ALLOWED_SOURCES else "—"


def fmt_metric_value(metric, suffix: str = "", default: str = "数据缺失") -> str:
    """格式化单个指标值（向后兼容）"""
    return _safe_value_display(metric, suffix) if metric else default


def fmt_nature_badge(metric) -> str:
    """返回数据性质 badge（向后兼容）"""
    return _safe_nature_display(metric)


# ============================================================
# 指标表格行渲染
# ============================================================

def add_row_fixed(label: str, metric, suffix: str = "") -> str:
    """
    渲染指标溯源表一行（可独立导入）。
    ✅ metric=None 或 value=None → "数据缺失"（不是"数据援助"）
    ✅ DataNature 任何值安全转换（不透传"阿富汗"等）
    """
    if metric is None or getattr(metric, 'value', None) is None:
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"

    nature = getattr(metric, 'nature', None)
    nature_key = (nature.value if hasattr(nature, 'value') else str(nature)) if nature else ""

    # missing nature → "数据缺失"
    if nature_key == 'missing':
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"

    val_str    = _safe_value_display(metric, suffix)
    nature_str = _safe_nature_display(metric)
    is_mock    = getattr(metric, 'is_mock', False)

    # 在数值列追加来源质量标注
    if is_mock or nature_key == 'mock':
        val_str += "（⚠️ 模拟，不参与评分）"
    elif nature_key == 'suspicious':
        val_str += "（⚠️ 口径存疑）"

    as_of = str(metric.as_of) if getattr(metric, 'as_of', None) else "—"
    src   = fmt_source(metric)
    return f"| {label} | {val_str} | {nature_str} | {as_of} | {src} |"


def render_metric_table(snapshot) -> str:
    """
    渲染核心指标溯源表
    ✅ 列名：截止日期（不是现有日期）
    ✅ None/missing → 数据缺失（不是数据援助）
    ✅ Alpha：基准未确认或次新基金 → 不计算
    """
    rows = [
        "| 指标 | 数值 | 数据性质 | 截止日期 | 来源 |",
        "|------|------|---------|---------|------|",
    ]
    rows.append(add_row_fixed(
        "最新净值",
        getattr(snapshot, 'unit_nav', None) or getattr(snapshot, 'nav', None),
        " 元"
    ))
    rows.append(add_row_fixed("累计净值",
        getattr(snapshot, 'accumulated_nav', None), " 元"))
    rows.append(add_row_fixed("基金规模",
        getattr(snapshot, 'fund_size', None) or getattr(snapshot, 'fund_size_bn', None),
        " 亿元"))
    rows.append(add_row_fixed("自成立以来收益",
        getattr(snapshot, 'return_since_inception', None), "%"))
    rows.append(add_row_fixed("近 1 年收益",
        getattr(snapshot, 'return_1y', None), "%"))
    rows.append(add_row_fixed("近 3 年收益",
        getattr(snapshot, 'return_3y', None), "%"))
    rows.append(add_row_fixed("最大回撤",
        getattr(snapshot, 'max_drawdown', None) or getattr(snapshot, 'max_drawdown_pct', None),
        "%"))
    rows.append(add_row_fixed("基准收益（同期）",
        getattr(snapshot, 'benchmark_return', None) or getattr(snapshot, 'benchmark_return_pct', None),
        "%"))

    # ✅ Alpha：只在基准确认且运行满1年时才展示真实值
    benchmark      = getattr(snapshot, 'benchmark', None)
    bench_matched  = getattr(benchmark, 'is_matched', False) if benchmark else False
    run_days       = getattr(snapshot, 'run_days', None)
    alpha_metric   = getattr(snapshot, 'alpha', None) or getattr(snapshot, 'alpha_pct', None)

    if not bench_matched or (run_days is not None and run_days < 365):
        rows.append(
            "| 超额收益（Alpha） | 不计算（基准未确认或运行不足1年） | ⬜ 缺失 | — | — |"
        )
    else:
        rows.append(add_row_fixed("超额收益（Alpha）", alpha_metric, "%"))

    return "\n".join(rows)


# ============================================================
# 评分表渲染
# ============================================================

def render_score_table(score) -> str:
    """
    渲染综合评分表。
    ✅ 说明列全部 hardcode，不经过 LLM，不依赖 auto_fix
    ✅ total_score=None → 不计算正式综合分
    ✅ alpha_adjustment=None → 不适用
    """
    def fmt_score(val):
        return "不计算" if val is None else str(val)

    # 兼容新旧 schema 字段名
    history_score      = getattr(score, 'history_score', None)
    sentiment_score    = getattr(score, 'sentiment_score', None)
    risk_control_score = (getattr(score, 'risk_control_score', None)
                          or getattr(score, 'risk_score', None))
    alpha_adj          = getattr(score, 'alpha_adjustment', None)
    if alpha_adj is None:
        alpha_adj = getattr(score, 'alpha_bonus', None)
    total_score        = getattr(score, 'total_score', None)
    confidence         = (getattr(score, 'confidence_label', None)
                          or getattr(score, 'confidence', "低"))

    alpha_display = (
        "不适用（基准未确认或次新基金）"
        if alpha_adj is None
        else fmt_score(alpha_adj)
    )
    total_display = (
        "不计算正式综合分"
        if total_score is None
        else f"**{total_score}**"
    )

    rows = [
        "| 维度 | 得分（满分 10） | 权重 | 说明 |",
        "|------|--------------|------|------|",
        f"| 历史业绩 | {fmt_score(history_score)} | 40% | 含运行时长惩罚 |",
        f"| 市场情绪 | {fmt_score(sentiment_score)} | 30% | 由舆情 Agent 输出 |",
        f"| 风险控制能力 | {fmt_score(risk_control_score)} | 30% | 越高=回撤控制越好 |",
        f"| Alpha 调整 | {alpha_display} | — | 超额收益奖惩 |",
        f"| **综合得分** | {total_display} | 100% | 置信度：{confidence} |",
    ]
    return "\n".join(rows)


# ============================================================
# 数据质量文本渲染
# ============================================================

def render_quality_text(quality) -> str:
    """
    渲染数据质量说明文本。
    ✅ 支持新 QualityResult.summary 属性（优先使用）
    ✅ 回退到旧 DataQualityReport 格式
    """
    if quality is None:
        return "⚠️ 数据质量信息未生成"

    # 新格式：QualityResult 有 summary 属性
    if hasattr(quality, 'summary') and quality.summary:
        return quality.summary

    # DataQualityReport (Pydantic) 或 JSON 字符串
    try:
        if isinstance(quality, str):
            import json
            q = json.loads(quality)
            # JSON 中有 summary 字段
            if q.get('summary'):
                return q['summary']
            level      = q.get('level', 'unknown')
            mock_count = q.get('mock_metric_count', 0)
            real_count = q.get('real_metric_count', 0)
            warnings   = q.get('warnings', [])
            contras    = q.get('contradictions', [])
        else:
            level      = getattr(quality, 'level', None)
            level      = level.value if hasattr(level, 'value') else str(level)
            mock_count = getattr(quality, 'mock_metric_count', 0)
            real_count = getattr(quality, 'real_metric_count', 0)
            warnings   = getattr(quality, 'warnings', [])
            contras    = getattr(quality, 'contradictions', [])

        level_text = {
            "real":     "✅ 核心指标均来自外部数据接口，未检测到模拟数据",
            "limited":  f"⚠️ 数据来源真实，但运行时间较短，统计意义有限",
            "partial":  f"⚠️ {mock_count} 项指标为模拟数据，适配结论为「信息不足」",
            "failed":   f"🔴 检测到 {len(contras)} 处数据矛盾，适配结论为「无法评级」",
            "mock":     "🔴 全部指标为模拟数据，报告仅供演示",
            "unavailable": "🔴 数据严重不足，无法生成有效分析",
        }.get(level, "数据质量未知")

        lines = [level_text]
        if contras:
            lines.append("\n**⛔ 数据矛盾：**")
            for c in contras:
                lines.append(f"- {c}")
        if warnings:
            lines.append("\n**数据警告：**")
            for w in warnings[:5]:
                lines.append(f"- {w}")
        return "\n".join(lines)
    except Exception:
        return "⚠️ 数据质量信息解析失败"


# ============================================================
# 经理信息渲染
# ============================================================

def _render_managers(snapshot) -> str:
    """渲染经理信息，格式：「俞瑶（从业4.6年、在管41.7亿元）」"""
    managers = getattr(snapshot, 'managers', [])
    if not managers:
        return "数据缺失"
    parts = []
    for m in managers:
        if isinstance(m, str):
            parts.append(m)
            continue
        name    = getattr(m, 'name', '未知')
        exp     = getattr(m, 'experience_years', None)
        aum     = getattr(m, 'total_aum_bn', None) or getattr(m, 'total_aum', None)
        is_mock = getattr(m, 'is_mock', False)
        details = []
        if exp is not None:
            details.append(f"从业 {exp} 年")
        if aum is not None:
            try:
                details.append(f"在管 {float(aum):.1f} 亿元")
            except (TypeError, ValueError):
                details.append(f"在管 {aum}")
        detail_str = f"（{'、'.join(details)}）" if details else ""
        mock_tag   = "（信息待核实）" if is_mock else ""
        parts.append(f"{name}{detail_str}{mock_tag}")
    return "、".join(parts)


def render_managers_text(snapshot) -> str:
    """向后兼容别名"""
    return _render_managers(snapshot)


# ============================================================
# Commentary 清洗
# ============================================================

def _clean_commentary(text: str) -> str:
    """
    清洗 LLM commentary 文本：
    1. 删除非法结论标题行（📌方案/理念/概念/建议/丰田结论：...）
    2. 去重情绪评分行（只保留最后一个）
    3. 应用 AUTO_FIX_MAP 修复常见幻觉词
    """
    if not text:
        return "数据获取失败，请重试。"

    # 删除 LLM 生成的结论/评级段落
    _STRIP_PATTERNS = [
        re.compile(r'(?:📌|##\s*)(?:方案|理念|概念|建议|综合|投资|丰田|修正)\s*结论[：:][^\n]*\n?', re.M),
        re.compile(r'(?:##\s*)(?:综合评分|评级)[^\n]*\n?', re.M),
        re.compile(r'^评级[：:]\s*\S+\s*$', re.M),
    ]
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub('', text)

    # 情绪评分去重：找所有匹配，只保留最后一个
    _SENTIMENT_PAT = re.compile(
        r'(?:情绪评分|SENTIMENT_SCORE|情感得分)[：:\s]*\d+(?:\.\d+)?',
        re.IGNORECASE
    )
    matches = list(_SENTIMENT_PAT.finditer(text))
    if len(matches) > 1:
        for m in reversed(matches[:-1]):
            text = text[:m.start()] + text[m.end():]
            # Trim any leftover blank lines
            text = re.sub(r'\n{3,}', '\n\n', text)

    # 应用 AUTO_FIX_MAP 修复
    try:
        from backend.value_cleaner import auto_fix_text
        fixed, _ = auto_fix_text(text)
        return fixed.strip()
    except Exception:
        return text.strip()


# ============================================================
# 最终报告渲染
# ============================================================

def _build_new_fund_banner(run_days: int) -> str:
    """
    次新基金警告 Banner，语序硬编码，不经过 LLM。
    ✅ 正确：「适配结论已受运行时长约束」
    ✅ 不出现「约束已」「修正结论」等历史污染词
    """
    return (
        f"\n> ⚠️ **次新基金警告**：该基金运行仅 **{run_days} 天**，"
        "所有历史业绩与风险指标统计意义有限，"
        "适配结论已受运行时长约束。\n"
    )


def render_report(
    snapshot,
    quality,
    score,
    market_commentary:    str,
    sentiment_commentary: str,
    risk_commentary:      str,
    periodic_report_json: str = "",   # Module 3: 定期报告经理观点
) -> str:
    """
    最终报告模板 V2.2。
    ✅ new_fund_banner 语序正确："适配结论已受运行时长约束"
    ✅ 基准指数缺失时显示"数据缺失"（不是"数据援助"）
    ✅ commentary 通过 _clean_commentary 清洗
    ✅ 适合人群只在此处出现一次
    """
    from datetime import date as date_type

    fund_code    = getattr(snapshot, 'code', '未知')
    fund_name    = getattr(snapshot, 'name', fund_code) or fund_code
    run_days     = getattr(snapshot, 'run_days', None)
    inception    = getattr(snapshot, 'inception_date', None)
    fund_type    = getattr(snapshot, 'fund_type', None)
    fund_company = (getattr(snapshot, 'company', None)
                    or getattr(snapshot, 'fund_company', None))
    benchmark    = getattr(snapshot, 'benchmark', None)
    bench_name   = getattr(benchmark, 'name', None) if benchmark else None
    # 兼容旧的 benchmark_name 字段
    if not bench_name:
        bench_name = getattr(snapshot, 'benchmark_name', None)
    report_date  = getattr(snapshot, 'report_date', str(date_type.today()))

    # ✅ 使用硬编码函数生成 Banner，语序安全
    new_fund_banner = ""
    if run_days and run_days < 365:
        new_fund_banner = _build_new_fund_banner(run_days)

    bench_warn = ""
    bench_mismatch = getattr(benchmark, 'mismatch_warning', None) if benchmark else None
    if bench_mismatch:
        bench_warn = f"\n> 🟡 **基准提示**：{bench_mismatch}\n"

    run_display  = f"{run_days} 天" if run_days else "无法确认"
    is_new       = run_days and run_days < 365
    new_tag      = "（次新基金）" if is_new else ""
    cap_reason   = getattr(score, 'rating_cap_reason', None)
    cap_section  = f"\n> ⚠️ **评级限制原因**：{cap_reason}" if cap_reason else ""

    # ✅ 基准指数缺失时显示"数据缺失"
    bench_display = bench_name if bench_name else "数据缺失"

    managers_text = _render_managers(snapshot)

    # Module 1: 持仓分析章节
    holdings_section = ""
    holdings_json_str = getattr(snapshot, 'holdings_json', None)
    if holdings_json_str:
        try:
            from backend.holdings import HoldingsAnalysis, render_holdings_table
            holdings = HoldingsAnalysis.from_json(holdings_json_str)
            holdings_section = (
                "\n---\n\n## 九、前十大重仓股持仓分析\n\n"
                + render_holdings_table(holdings)
                + "\n"
            )
        except Exception:
            holdings_section = "\n---\n\n## 九、前十大重仓股持仓分析\n\n持仓数据获取失败\n"

    # Module 3: 定期报告/经理观点章节
    periodic_section = ""
    if periodic_report_json:
        try:
            from backend.report_fetcher import PeriodicReport
            pr = PeriodicReport.from_json(periodic_report_json)
            mock_tag = "（⚠️ 模拟，仅供参考）" if pr.is_mock else ""
            bench_in_report = (
                f"\n\n**报告中的业绩基准描述：** {pr.benchmark_desc}"
                if pr.benchmark_desc else ""
            )
            periodic_section = (
                f"\n---\n\n## 十、基金经理观点（来源：{pr.report_type}{mock_tag}）\n\n"
                f"**基金经理观点：**\n> {pr.manager_comment or '暂无'}\n\n"
                f"**投资策略摘要：**\n{pr.strategy_summary or '暂无'}{bench_in_report}\n"
            )
        except Exception:
            periodic_section = "\n---\n\n## 十、基金经理观点\n\n获取失败\n"

    return f"""# 📋 {fund_code} 基金分析报告
{new_fund_banner}{bench_warn}
**基金名称：** {fund_name}（代码：{fund_code}）
**报告日期：** {report_date}
**基金运行时长：** {run_display}{new_tag}
**分析团队：** FundRAG Multi-Agent System V2.2

---

## 一、数据质量说明

{render_quality_text(quality)}

---

## 二、基金基本信息

| 项目 | 内容 |
|------|------|
| 基金类型 | {fund_type or "数据缺失"} |
| 基金公司 | {fund_company or "数据缺失"} |
| 成立日期 | {inception or "数据缺失"} |
| 基金经理 | {managers_text} |
| 基准指数 | {bench_display} |

---

## 三、核心指标溯源

{render_metric_table(snapshot)}

---

## 四、综合评分

{render_score_table(score)}

### 📌 适配结论：{score.rating}
{cap_section}

**风险等级：{score.risk_level}**
（风险等级反映资产波动性；风险控制能力分反映基金回撤管控能力，二者含义不同）

**适合人群：** {score.suitability}

---

## 五、行情分析

{_clean_commentary(market_commentary)}

---

## 六、舆情分析

{_clean_commentary(sentiment_commentary)}

---

## 七、风险评估

{_clean_commentary(risk_commentary)}

{holdings_section}{periodic_section}
---

## 八、⚠️ 风险提示

本报告由 AI 系统自动生成，仅用于信息整理和学习演示，**不构成任何投资建议**。
基金投资有风险，过往业绩不代表未来表现。投资者应根据自身情况独立决策。

---
*本报告由 FundRAG Multi-Agent System V2.2 生成 | 数据来源：akshare / Tavily*
"""


# ============================================================
# 向后兼容别名
# ============================================================

def render_data_quality_section(quality) -> str:
    """兼容旧接口"""
    return render_quality_text(quality)
