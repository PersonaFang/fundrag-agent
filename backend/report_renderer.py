# backend/report_renderer.py
"""
模板化报告渲染 V2.4：
- DataNature 四重防御（不透传任何未知值）
- 表头/来源/分数说明全部 hardcode
- 章节顺序固定（八在九之前）
- 适合人群/风险说明走本地白名单
- mock 来源不双重标注（"mock"而非"mock（模拟）"）
"""

import re
from typing import Optional

from backend.constants import ALLOWED_RISK_LEVELS


# ============================================================
# 常量：DataNature → 显示文本（唯一真理来源）
# ============================================================
_NATURE_DISPLAY = {
    "real":        "✅ 真实",
    "calculated":  "✅ 计算",
    "mock":        "🔴 模拟",
    "suspicious":  "🟡 存疑",
    "missing":     "⬜ 缺失",
}
_VALID_NATURE_KEYS = frozenset(_NATURE_DISPLAY.keys())

# 来源白名单 + 显示文本
_SOURCE_DISPLAY = {
    "akshare":    "akshare",
    "tavily":     "tavily",
    "calculated": "calculated",
    "official":   "official",
    "missing":    "—",
    "mock":       "mock",       # ✅ 不追加"（模拟）"，防止双重处理
    "unknown":    "—",
}
_ALLOWED_SOURCES = frozenset(_SOURCE_DISPLAY.keys())

# 来源脏值本地清洗（优先于白名单）
_DIRTY_SOURCE_FIX = {
    "嘲笑":         "mock",
    "计算":         "calculated",
    "模拟":         "mock",
    "真实":         "akshare",
    "akShare":      "akshare",
    "官方":         "official",
    "官网":         "official",
    "mock（模拟）": "mock",     # ✅ 修复双重处理产生的 "mock（模拟）"
}

# 适合人群白名单（完全 hardcode，禁止经过 AUTO_FIX）
_SUITABILITY_SAFE = {
    "适合配置": "适合高风险承受能力、资金期限 3 年以上、以组合卫星仓位配置的投资者",
    "谨慎关注": "可小比例配置，需能承受阶段性较大回撤，不适合保守型投资者",
    "持续观察": "基金数据不足，仅建议观察，不建议基于短期表现配置",
    "信息不足": "含模拟或缺失数据，无法形成有效配置结论，请以官方渠道数据为准",
    "风险较高": "历史回撤或波动性较高，仅适合能承受大幅亏损的积极投资者",
    "无法评级": "数据存在矛盾，需修复数据后重新分析",
}


# ============================================================
# 辅助函数
# ============================================================

def _safe_nature_display(metric) -> str:
    """
    四重防御：
    1. metric=None → "⬜ 缺失"
    2. is_mock=True → "🔴 模拟"（不看 nature）
    3. nature key 不在白名单 → "⬜ 缺失"（绝不透传）
    4. 捕获所有异常 → "⬜ 缺失"
    """
    try:
        if metric is None:
            return "⬜ 缺失"
        if getattr(metric, 'is_mock', False):
            return "🔴 模拟"
        nature = getattr(metric, 'nature', None)
        if nature is None:
            return "⬜ 缺失"
        key = nature.value if hasattr(nature, 'value') else str(nature)
        return _NATURE_DISPLAY.get(key, "⬜ 缺失")
    except Exception:
        return "⬜ 缺失"


def fmt_source(metric) -> str:
    """
    返回来源字符串。
    ✅ 本地清洗脏值 → 白名单校验 → 不在白名单显示 "—"
    ✅ 不追加括号注释（防止 "mock（模拟）" 双重问题）
    """
    if metric is None:
        return "—"
    src = str(getattr(metric, 'source', None) or 'unknown').strip()
    src = _DIRTY_SOURCE_FIX.get(src, src)
    if src not in _ALLOWED_SOURCES:
        return "—"
    return _SOURCE_DISPLAY.get(src, "—")


def _safe_value_display(metric, suffix: str = "") -> str:
    """安全显示指标数值。metric/value 为 None → '数据缺失'"""
    if metric is None:
        return "数据缺失"
    val = getattr(metric, 'value', None)
    if val is None:
        return "数据缺失"
    if isinstance(val, float):
        val_str = f"{val:.4f}" if 0 < abs(val) < 10 else f"{val:.2f}"
    else:
        val_str = str(val)
    return val_str + suffix


# ============================================================
# 指标表格行渲染
# ============================================================

def add_row_fixed(label: str, metric, suffix: str = "") -> str:
    """
    渲染指标溯源表一行。
    ✅ None/missing → "数据缺失"（不是"数据援助"）
    ✅ DataNature 经四重防御安全转换
    ✅ source 脏值本地清洗
    """
    if metric is None:
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"

    val = getattr(metric, 'value', None)
    if val is None:
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"

    nature     = getattr(metric, 'nature', None)
    nature_key = ""
    if nature is not None:
        nature_key = nature.value if hasattr(nature, 'value') else str(nature)

    if nature_key == 'missing':
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"

    if isinstance(val, float):
        val_str = f"{val:.4f}" if 0 < abs(val) < 10 else f"{val:.2f}"
    else:
        val_str = str(val)
    val_str = val_str + suffix

    is_mock       = getattr(metric, 'is_mock', False) or nature_key == 'mock'
    is_suspicious = (nature_key == 'suspicious')

    if is_mock:
        val_str += "（⚠️ 模拟，不参与评分）"
    elif is_suspicious:
        val_str += "（⚠️ 口径存疑）"

    nature_str = _safe_nature_display(metric)
    as_of      = str(metric.as_of) if getattr(metric, 'as_of', None) else "—"
    src        = fmt_source(metric)

    return f"| {label} | {val_str} | {nature_str} | {as_of} | {src} |"


def render_metric_table(snapshot) -> str:
    """
    渲染核心指标溯源表。
    ✅ 表头列名：「截止日期」（硬编码，不经任何替换）
    ✅ 缺失值：「数据缺失」（不是「数据援助」）
    ✅ Alpha 行完全 hardcode
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

    # ✅ Alpha 行：完全 hardcode，不走 add_row_fixed
    benchmark     = getattr(snapshot, 'benchmark', None)
    bench_matched = getattr(benchmark, 'is_matched', False) if benchmark else False
    run_days      = getattr(snapshot, 'run_days', None)

    if not bench_matched or (run_days is not None and run_days < 365):
        rows.append(
            "| 超额收益（Alpha） | 不计算（基准未确认或运行不足 1 年） | ⬜ 缺失 | — | — |"
        )
    else:
        alpha_metric = getattr(snapshot, 'alpha', None) or getattr(snapshot, 'alpha_pct', None)
        if alpha_metric is None:
            rows.append("| 超额收益（Alpha） | 数据缺失 | ⬜ 缺失 | — | — |")
        else:
            rows.append(add_row_fixed("超额收益（Alpha）", alpha_metric, "%"))

    return "\n".join(rows)


# ============================================================
# 评分表渲染
# ============================================================

def render_score_table(score) -> str:
    """
    渲染综合评分表。
    ✅ 说明列全部 hardcode 中文，不经过任何 LLM 或 AUTO_FIX
    ✅ total_score=None → "不计算正式综合分"
    ✅ alpha=None → "不适用（基准未确认或次新基金）"
    """
    def fmt_score(val) -> str:
        return "不计算" if val is None else str(val)

    history_score      = getattr(score, 'history_score', None)
    sentiment_score    = getattr(score, 'sentiment_score', None)
    risk_control_score = (getattr(score, 'risk_control_score', None)
                          or getattr(score, 'risk_score', None))
    alpha_adj  = getattr(score, 'alpha_adjustment', None)
    if alpha_adj is None:
        alpha_adj = getattr(score, 'alpha_bonus', None)
    total_score = getattr(score, 'total_score', None)
    confidence  = (getattr(score, 'confidence_label', None)
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

    # ✅ 说明列：全部中文硬编码，禁止任何变量插入
    return "\n".join([
        "| 维度 | 得分（满分 10） | 权重 | 说明 |",
        "|------|--------------|------|------|",
        f"| 历史业绩 | {fmt_score(history_score)} | 40% | 含运行时长惩罚 |",
        f"| 市场情绪 | {fmt_score(sentiment_score)} | 30% | 由舆情 Agent 输出 |",
        f"| 风险控制能力 | {fmt_score(risk_control_score)} | 30% | 越高表示回撤控制越好 |",
        f"| Alpha 调整 | {alpha_display} | — | 超额收益奖惩项 |",
        f"| **综合得分** | {total_display} | 100% | 置信度：{confidence} |",
    ])


# ============================================================
# 数据质量文本渲染
# ============================================================

def render_quality_text(quality) -> str:
    """
    渲染数据质量说明文本。
    ✅ level 文案完全 hardcode
    ✅ 支持新 QualityResult.summary 属性
    """
    if quality is None:
        return "⚠️ 数据质量信息未生成"

    if hasattr(quality, 'summary') and quality.summary:
        return quality.summary

    try:
        if isinstance(quality, str):
            import json
            q = json.loads(quality)
            level      = q.get('level', 'unknown')
            mock_count = q.get('mock_metric_count', 0)
            warnings   = q.get('warnings', [])
            contras    = q.get('contradictions', [])
        else:
            level_raw  = getattr(quality, 'level', None)
            level      = level_raw.value if hasattr(level_raw, 'value') else str(level_raw)
            mock_count = getattr(quality, 'mock_metric_count', 0)
            warnings   = getattr(quality, 'warnings', [])
            contras    = getattr(quality, 'contradictions', [])

        level_text = {
            "real":        "✅ 核心指标均来自外部数据接口，未检测到模拟数据",
            "limited":     "⚠️ 数据来源真实，但运行时间较短，统计意义有限",
            "partial":     f"⚠️ {mock_count} 项指标为模拟数据，适配结论为「信息不足」",
            "failed":      f"🔴 检测到 {len(contras)} 处数据矛盾，适配结论为「无法评级」",
            "mock":        "🔴 全部指标为模拟数据，报告仅供演示",
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


# ============================================================
# Commentary 清洗
# ============================================================

def _clean_commentary(text: str) -> str:
    """
    清洗 LLM commentary：
    1. 删除非法结论/评级 heading
    2. 情绪评分去重（只保留最后一个）
    3. 删除内部字段名泄漏
    4. 应用 AUTO_FIX_MAP
    """
    if not text:
        return "数据获取失败，请重试。"

    _STRIP_PATTERNS = [
        re.compile(r'(?:📌|##\s*)(?:方案|理念|概念|建议|综合|投资|丰田|修正|推理|推断)\s*结论[：:][^\n]*\n?', re.M),
        re.compile(r'(?:##\s*)(?:综合评分|评级)[^\n]*\n?', re.M),
        re.compile(r'^评级[：:]\s*\S+\s*$', re.M),
    ]
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub('', text)

    # 情绪评分去重
    _SENTIMENT_PAT = re.compile(
        r'(?:情绪评分|SENTIMENT_SCORE|情感得分)[：:\s]*\d+(?:\.\d+)?',
        re.IGNORECASE
    )
    matches = list(_SENTIMENT_PAT.finditer(text))
    if len(matches) > 1:
        for m in reversed(matches[:-1]):
            text = text[:m.start()] + text[m.end():]
        text = re.sub(r'\n{3,}', '\n\n', text)

    # ✅ 删除内部字段名泄漏
    _FIELD_NAME_PATTERN = re.compile(
        r'\b(run_days|history_score|sentiment_score|risk_control_score|'
        r'alpha_adjustment|confidence_label|total_score|is_mock|'
        r'fund_code|score_json|snapshot_json|data_quality_json)\b'
        r'[^，。；\n]{0,30}',
    )
    text = _FIELD_NAME_PATTERN.sub('[数据项]', text)

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
    return (
        f"\n> ⚠️ **次新基金警告**：该基金运行仅 **{run_days} 天**，"
        "所有历史业绩与风险指标统计意义有限，"
        "**适配结论**已受运行时长约束。\n"
    )


def render_report(
    snapshot,
    quality,
    score,
    market_commentary:    str,
    sentiment_commentary: str,
    risk_commentary:      str,
    periodic_report_json: str = "",
    holdings_section:     str = "",
) -> str:
    """
    最终报告模板 V2.4。
    ✅ 章节顺序固定：一~八（主体）→ 九持仓（可选）→ 十经理观点（可选）
    ✅ 「📌 适配结论：」完全 hardcode
    ✅ 适合人群走本地白名单（_SUITABILITY_SAFE）
    ✅ 风险等级说明完全 hardcode
    ✅ new_fund_banner 语序正确
    """
    from datetime import date as date_type
    from backend.constants import ALLOWED_RATINGS

    fund_code    = getattr(snapshot, 'code', '未知')
    fund_name    = getattr(snapshot, 'name', fund_code) or fund_code
    run_days     = getattr(snapshot, 'run_days', None)
    inception    = getattr(snapshot, 'inception_date', None)
    fund_type    = getattr(snapshot, 'fund_type', None)
    fund_company = (getattr(snapshot, 'company', None)
                    or getattr(snapshot, 'fund_company', None))
    benchmark    = getattr(snapshot, 'benchmark', None)
    bench_name   = getattr(benchmark, 'name', None) if benchmark else None
    if not bench_name:
        bench_name = getattr(snapshot, 'benchmark_name', None)
    report_date  = getattr(snapshot, 'report_date', str(date_type.today()))

    new_fund_banner = ""
    if run_days and run_days < 365:
        new_fund_banner = _build_new_fund_banner(run_days)

    bench_warn = ""
    bench_mismatch = getattr(benchmark, 'mismatch_warning', None) if benchmark else None
    if bench_mismatch:
        bench_warn = f"\n> 🟡 **基准提示**：{bench_mismatch}\n"

    run_display = f"{run_days} 天" if run_days else "无法确认"
    is_new      = run_days and run_days < 365
    new_tag     = "（次新基金）" if is_new else ""
    bench_display = bench_name if bench_name else "数据缺失"
    managers_text = _render_managers(snapshot)

    # ✅ 评级白名单校验
    raw_rating  = getattr(score, 'rating', '无法评级')
    safe_rating = raw_rating if raw_rating in ALLOWED_RATINGS else '无法评级'

    cap_reason  = getattr(score, 'rating_cap_reason', None)
    cap_section = f"\n> ⚠️ **评级限制原因**：{cap_reason}" if cap_reason else ""

    # ✅ 风险等级白名单校验
    raw_risk_level  = getattr(score, 'risk_level', '中')
    safe_risk_level = raw_risk_level if raw_risk_level in ALLOWED_RISK_LEVELS else '中'

    # ✅ 适合人群从本地白名单取
    suitability = _SUITABILITY_SAFE.get(safe_rating, "请咨询专业投资顾问")

    # ✅ 风险等级说明完全 hardcode
    risk_level_note = (
        "风险等级反映资产波动性；"
        "风险控制能力分反映基金回撤管控能力，二者含义不同"
    )

    # ✅ 可选章节（九、十）拼接——必须在八之后
    optional_sections = ""
    if holdings_section:
        optional_sections += f"\n---\n\n## 九、前十大重仓股持仓分析\n\n{holdings_section}\n"
    if periodic_report_json:
        try:
            from backend.report_fetcher import PeriodicReport
            pr = PeriodicReport.from_json(periodic_report_json)
            mock_tag = "（⚠️ 模拟，仅供参考）" if pr.is_mock else ""
            optional_sections += f"""
---

## 十、基金经理观点（来源：{pr.report_type}{mock_tag}）

**基金经理观点：**
> {pr.manager_comment or "暂无"}

**投资策略摘要：**
{pr.strategy_summary or "暂无"}
"""
            if pr.benchmark_desc:
                optional_sections += f"\n**报告中的业绩基准描述：** {pr.benchmark_desc}\n"
        except Exception:
            pass

    return f"""# 📋 {fund_code} 基金分析报告
{new_fund_banner}{bench_warn}
**基金名称：** {fund_name}（代码：{fund_code}）
**报告日期：** {report_date}
**基金运行时长：** {run_display}{new_tag}
**分析团队：** FundRAG Multi-Agent System V2.4

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

### 📌 适配结论：{safe_rating}
{cap_section}

**风险等级：{safe_risk_level}**
（{risk_level_note}）

**适合人群：** {suitability}

---

## 五、行情分析

{_clean_commentary(market_commentary)}

---

## 六、舆情分析

{_clean_commentary(sentiment_commentary)}

---

## 七、风险评估

{_clean_commentary(risk_commentary)}

---

## 八、⚠️ 风险提示

本报告由 AI 系统自动生成，仅用于信息整理和学习演示，**不构成任何投资建议**。
基金投资有风险，过往业绩不代表未来表现。投资者应根据自身情况独立决策。
{optional_sections}
---
*本报告由 FundRAG Multi-Agent System V2.4 生成 | 数据来源：akshare / Tavily*
"""


# ============================================================
# 向后兼容别名
# ============================================================

def render_data_quality_section(quality) -> str:
    return render_quality_text(quality)

def fmt_metric_value(metric, suffix: str = "", default: str = "数据缺失") -> str:
    return _safe_value_display(metric, suffix) if metric else default

def fmt_nature_badge(metric) -> str:
    return _safe_nature_display(metric)

def render_managers_text(snapshot) -> str:
    return _render_managers(snapshot)
