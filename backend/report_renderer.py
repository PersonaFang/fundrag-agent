# backend/report_renderer.py
"""
模板化报告渲染 V2.1：所有结构化字段由代码填充，LLM 只提供解释文字
核心修复：
- nature-aware 指标显示（real/mock/suspicious/missing）
- 截止日期列（修复「现有日期」→「截止日期」）
- total_score=None 时显示「不计算正式综合分」
- alpha_adjustment=None 时显示「不适用」
🌰 类比：填空题模板，AI 只能填指定空格，不能改题目
"""

from backend.constants import ALLOWED_RISK_LEVELS


def fmt_metric_value(metric, suffix: str = "", default: str = "数据缺失") -> str:
    """
    格式化单个指标值，按 nature 显示不同标注
    🌰 类比：
        真实数据 → 直接显示
        模拟数据 → 显示+「（模拟，不参与评分）」
        可疑数据 → 显示+「（口径存疑）」
        缺失数据 → 「数据缺失」
    """
    if metric is None or getattr(metric, 'value', None) is None:
        return default

    val = metric.value
    # 数值格式化
    if isinstance(val, float):
        val_str = f"{val:.4f}" if abs(val) < 10 else f"{val:.2f}"
    else:
        val_str = str(val)
    val_str += suffix

    # 按 nature 添加标注
    nature = getattr(metric, 'nature', None)
    is_mock = getattr(metric, 'is_mock', False)

    if nature:
        n = nature.value if hasattr(nature, 'value') else str(nature)
        if n == 'mock' or is_mock:
            return f"{val_str}（⚠️ 模拟，不参与评分）"
        if n == 'suspicious':
            return f"{val_str}（⚠️ 口径存疑，不参与评分）"
        if n == 'missing':
            return "数据缺失"
    elif is_mock:
        return f"{val_str}（⚠️ 模拟，不参与评分）"

    return val_str


def fmt_nature_badge(metric) -> str:
    """返回数据性质 badge"""
    if metric is None:
        return "—"

    nature = getattr(metric, 'nature', None)
    is_mock = getattr(metric, 'is_mock', False)

    if nature:
        n = nature.value if hasattr(nature, 'value') else str(nature)
        badges = {
            'real':       '✅ 真实',
            'calculated': '🔵 计算',
            'missing':    '⬜ 缺失',
            'mock':       '🔴 模拟',
            'suspicious': '🟡 存疑',
        }
        return badges.get(n, '⬜ 未知')
    return '🔴 模拟' if is_mock else '✅ 真实'


def fmt_source(metric) -> str:
    """返回数据来源，确保不出现脏值。本地兜底优先，不依赖外部函数抛异常"""
    if metric is None:
        return "—"

    src = getattr(metric, 'source', None) or 'missing'

    # 本地优先清洗脏值（不依赖 normalize_source 抛异常）
    _DIRTY_SOURCE_FIX = {
        "嘲笑": "mock",
        "计算": "calculated",
        "模拟": "mock",
        "真实": "akshare",
        "akShare": "akshare",
    }
    if src in _DIRTY_SOURCE_FIX:
        return _DIRTY_SOURCE_FIX[src]

    _ALLOWED = {"akshare", "tavily", "calculated", "official", "missing", "mock"}
    if src in _ALLOWED:
        return src

    # 最终兜底：调用 normalize_source
    try:
        from backend.value_cleaner import normalize_source
        return normalize_source(src, allow_warning=True)
    except ValueError:
        return "来源未知"


def add_row_fixed(label: str, metric, suffix: str = "") -> str:
    """
    构建单行指标表格行（可独立导入）
    ✅ metric=None 时返回「数据缺失」，不是「数据援助」
    ✅ 来源列通过 fmt_source 清洗（嘲笑→mock）
    """
    if metric is None or getattr(metric, 'value', None) is None:
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"

    val = metric.value
    if isinstance(val, float):
        val_str = f"{val:.4f}" if abs(val) < 10 else f"{val:.2f}"
    else:
        val_str = str(val)
    val_str += suffix

    nature  = getattr(metric, 'nature', None)
    is_mock = getattr(metric, 'is_mock', False)
    n_str   = (nature.value if hasattr(nature, 'value') else str(nature)) if nature else ""

    if n_str == 'missing':
        return f"| {label} | 数据缺失 | ⬜ 缺失 | — | — |"
    elif n_str == 'mock' or is_mock:
        val_str += "（⚠️ 模拟，不参与评分）"
        badge = "🔴 模拟"
    elif n_str == 'suspicious':
        val_str += "（⚠️ 口径存疑）"
        badge = "🟡 存疑"
    else:
        badge = "✅ 真实"

    as_of = str(metric.as_of) if getattr(metric, 'as_of', None) else "—"
    src   = fmt_source(metric)
    return f"| {label} | {val_str} | {badge} | {as_of} | {src} |"


def render_metric_table(snapshot) -> str:
    """
    渲染核心指标溯源表
    ✅ 列名修复：现有日期 → 截止日期
    ✅ 空值修复：数据援助 → 数据缺失（通过 add_row_fixed）
    ✅ 来源修复：嘲笑 → mock（通过 fmt_source）
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
    rows.append(add_row_fixed("超额收益（Alpha）",
        getattr(snapshot, 'alpha', None) or getattr(snapshot, 'alpha_pct', None),
        "%"))

    return "\n".join(rows)


def render_score_table(score) -> str:
    """
    渲染综合评分表
    ✅ total_score=None 时显示「不计算正式综合分」
    ✅ alpha_adjustment=None 时显示「不适用」
    ✅ 风控得分标注说明（越高=风控越好）
    """
    def fmt_score(val, suffix=""):
        if val is None:
            return "不计算"
        return f"{val}{suffix}"

    # 兼容新旧 schema
    history_score  = getattr(score, 'history_score', None)
    sentiment_score = getattr(score, 'sentiment_score', None)
    # V2.1 字段：risk_control_score; V2.0 字段：risk_score
    risk_score     = (getattr(score, 'risk_control_score', None)
                      or getattr(score, 'risk_score', None))
    # V2.1 字段：alpha_adjustment; V2.0 字段：alpha_bonus
    alpha_adj      = getattr(score, 'alpha_adjustment', None)
    if alpha_adj is None:
        alpha_adj  = getattr(score, 'alpha_bonus', None)
    total_score    = getattr(score, 'total_score', None)
    # V2.1 字段：confidence_label; V2.0 字段：confidence
    confidence     = (getattr(score, 'confidence_label', None)
                      or getattr(score, 'confidence', "—"))

    alpha_display = "不适用（依赖数据为模拟）" if alpha_adj is None \
                    else fmt_score(alpha_adj)

    total_display = "不计算正式综合分" if total_score is None \
                    else f"**{total_score}**"

    rows = [
        "| 维度 | 得分（满分 10） | 权重 | 说明 |",
        "|------|--------------|------|------|",
        f"| 历史业绩 | {fmt_score(history_score)} | 40% | 含运行时长惩罚 |",
        f"| 市场情绪 | {fmt_score(sentiment_score)} | 30% | 由舆情 Agent 输出 |",
        f"| 风险控制能力 | {fmt_score(risk_score)} | 30% | 越高=回撤控制越好 |",
        f"| Alpha 调整 | {alpha_display} | — | 超额收益奖惩 |",
        f"| **综合得分** | {total_display} | 100% | 置信度：{confidence} |",
    ]

    return "\n".join(rows)


def render_quality_text(quality) -> str:
    """渲染数据质量说明"""
    level = getattr(quality, 'level', None)
    level_str = level.value if hasattr(level, 'value') else str(level)

    level_text = {
        "real":    "✅ 核心指标均来自外部数据接口，未检测到模拟数据",
        "partial": (
            f"⚠️ 部分数据缺失或为模拟："
            f"真实指标 {getattr(quality,'real_metric_count',0)} 个，"
            f"模拟指标 {getattr(quality,'mock_metric_count',0)} 个"
        ),
        "mock":    "🔴 全部指标为模拟数据，报告仅供演示，不具参考价值",
        "failed":  "🔴 检测到数据矛盾，本报告不输出正式评级",
    }.get(level_str, "数据质量未知")

    lines = [level_text]

    contradictions = getattr(quality, 'contradictions', [])
    if contradictions:
        lines.append("\n**⛔ 数据矛盾（已拦截评级）：**")
        for c in contradictions:
            lines.append(f"- {c}")

    warnings = getattr(quality, 'warnings', [])
    if warnings:
        lines.append("\n**数据警告：**")
        for w in warnings[:5]:  # 最多显示5条
            lines.append(f"- {w}")

    missing = getattr(quality, 'missing_fields', [])
    if missing:
        lines.append(f"\n**缺失关键字段：** {', '.join(missing)}")

    return "\n".join(lines)


def render_managers_text(snapshot) -> str:
    """渲染基金经理信息"""
    managers = getattr(snapshot, 'managers', [])
    if not managers:
        return "数据缺失"

    parts = []
    for m in managers:
        # 兼容 ManagerInfo 对象和字符串
        if isinstance(m, str):
            parts.append(m)
            continue

        name = getattr(m, 'name', '未知')
        exp  = getattr(m, 'experience_years', None)
        aum  = getattr(m, 'total_aum_bn', None) or getattr(m, 'total_aum', None)
        is_m = getattr(m, 'is_mock', False)

        detail_parts = []
        if exp is not None:
            detail_parts.append(f"从业 {exp} 年")
        if aum is not None:
            try:
                detail_parts.append(f"在管 {float(aum):.1f} 亿元")
            except (TypeError, ValueError):
                detail_parts.append(f"在管 {aum}")

        detail = f"（{'、'.join(detail_parts)}）" if detail_parts else ""
        mock_tag = "（信息待核实）" if is_m else ""
        parts.append(f"{name}{detail}{mock_tag}")

    return "、".join(parts)


def _clean_commentary(text: str) -> str:
    """
    清洗 LLM commentary 文本：
    1. 去除 LLM 可能生成的「📌方案/理念/概念/建议/丰田结论：...」段落（防止覆写模板标题）
    2. 去除 LLM 生成的 ## 综合评分 / ## 评级 章节（已由模板控制）
    3. 应用 AUTO_FIX_MAP 修复常见幻觉词
    """
    if not text:
        return "数据获取失败，请重试。"

    import re
    from backend.value_cleaner import auto_fix_text

    # 删除 LLM 生成的结论/评级段落（这些应由模板控制，LLM不得重复生成）
    _STRIP_PATTERNS = [
        re.compile(r'(?:📌|##\s*)(?:方案|理念|概念|建议|适配|综合|投资|丰田)\s*结论[：:][^\n]*\n?', re.M),
        re.compile(r'(?:##\s*)(?:综合评分|评级)[^\n]*\n?', re.M),
        re.compile(r'评级[：:]\s*(?:风险较高|适合配置|谨慎关注|持续观察|信息不足|无法评级)\s*\n?', re.M),
    ]
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub('', text)

    # 应用 AUTO_FIX_MAP 修复
    fixed, _ = auto_fix_text(text)
    return fixed.strip()


# Backward-compat alias
def render_data_quality_section(quality) -> str:
    """兼容旧接口"""
    return render_quality_text(quality)


def render_report(
    snapshot,
    quality,
    score,
    market_commentary:    str,
    sentiment_commentary: str,
    risk_commentary:      str,
) -> str:
    """
    最终报告模板 V2.1：所有结构化字段由代码填充
    LLM 只提供 *_commentary 三段解释文字
    """
    fund_code = getattr(snapshot, 'code', '未知')
    fund_name = getattr(snapshot, 'name', fund_code) or fund_code

    run_days      = getattr(snapshot, 'run_days', None)
    inception     = getattr(snapshot, 'inception_date', None)
    fund_type     = getattr(snapshot, 'fund_type', None)
    fund_company  = (getattr(snapshot, 'company', None)
                     or getattr(snapshot, 'fund_company', None))
    benchmark     = getattr(snapshot, 'benchmark', None)
    benchmark_name = (getattr(benchmark, 'name', None) if benchmark
                      else getattr(snapshot, 'benchmark_name', None))
    benchmark_mismatch = getattr(benchmark, 'mismatch_warning', None) if benchmark else None
    report_date   = getattr(snapshot, 'report_date', 'unknown')

    # 次新基金警告 banner
    new_fund_banner = ""
    if run_days and run_days < 365:
        new_fund_banner = (
            f"\n> ⚠️ **次新基金警告**：该基金运行仅 **{run_days} 天**，"
            "所有历史业绩与风险指标统计意义有限，适配结论已受运行时长约束。\n"
        )

    # 基准不匹配警告
    benchmark_warn = ""
    if benchmark_mismatch:
        benchmark_warn = f"\n> 🟡 **基准提示**：{benchmark_mismatch}\n"

    # 评级限制说明
    cap_reason = getattr(score, 'rating_cap_reason', None)
    cap_section = f"\n> ⚠️ **评级限制原因**：{cap_reason}" if cap_reason else ""

    # 运行时长显示
    run_days_display = f"{run_days} 天" if run_days else "无法确认"
    is_new = run_days and run_days < 365
    new_tag = "（次新基金）" if is_new else ""

    # 风险等级
    risk_level = getattr(score, 'risk_level', None) or "—"

    return f"""# 📋 {fund_code} 基金分析报告
{new_fund_banner}{benchmark_warn}
**基金名称：** {fund_name}（代码：{fund_code}）
**报告日期：** {report_date}
**基金运行时长：** {run_days_display}{new_tag}
**分析团队：** FundRAG Multi-Agent System V2.1

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
| 基金经理 | {render_managers_text(snapshot)} |
| 基准指数 | {benchmark_name or "数据缺失"} |

---

## 三、核心指标溯源

{render_metric_table(snapshot)}

---

## 四、综合评分

{render_score_table(score)}

### 📌 适配结论：{score.rating}
{cap_section}

**风险等级：{risk_level}**
（注：风险等级反映资产波动性，风险控制能力得分反映基金管控能力，二者含义不同）

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

---

## 八、⚠️ 风险提示

本报告由 AI 系统自动生成，仅用于信息整理和学习演示，**不构成任何投资建议**。
基金投资有风险，过往业绩不代表未来表现。投资者应根据自身情况独立决策。

---
*本报告由 FundRAG Multi-Agent System V2.1 生成 | 数据来源：akshare / Tavily*
"""
