# backend/report_renderer.py
"""
模板化报告渲染：数字和表格由代码生成，LLM 只填解释段落
🌰 类比：填空题模板，AI 只能填指定空格，不能改题目
"""

from datetime import date
from backend.schemas import FundSnapshot, DataQualityReport, ScoreBreakdown


def _fmt(value, suffix="", default="数据缺失") -> str:
    if value is None:
        return default
    return f"{value}{suffix}"


def render_data_quality_section(q: DataQualityReport) -> str:
    level_text = {
        "real":    "✅ 核心指标均来自外部数据接口，未检测到模拟数据",
        "partial": f"⚠️ 部分数据缺失或为模拟：真实指标 {q.real_metric_count} 个，模拟指标 {q.mock_metric_count} 个",
        "mock":    "🔴 全部为模拟数据，报告仅供演示，不具参考价值",
        "failed":  "🔴 检测到数据矛盾，本报告不输出正式评级",
    }[q.level]

    lines = [level_text]

    if q.contradictions:
        lines.append("\n**⛔ 数据矛盾（已拦截评级）：**")
        for c in q.contradictions:
            lines.append(f"- {c}")

    if q.missing_fields:
        lines.append(f"\n**缺失字段：** {', '.join(q.missing_fields)}")

    if q.warnings:
        lines.append("\n**数据警告：**")
        for w in q.warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)


def render_metric_table(snapshot: FundSnapshot) -> str:
    """渲染核心指标溯源表"""
    rows = []

    def add_row(label, metric):
        if metric is None:
            rows.append(f"| {label} | 数据缺失 | — | — | — |")
            return
        val = f"{metric.value}" if metric.value is not None else "缺失"
        if metric.unit:
            val += f" {metric.unit}"
        mock_tag = "🔴模拟" if metric.is_mock else "✅真实"
        as_of    = str(metric.as_of) if metric.as_of else "未知"
        rows.append(f"| {label} | {val} | {mock_tag} | {as_of} | {metric.source} |")

    rows.append("| 指标 | 数值 | 数据性质 | 截止日期 | 来源 |")
    rows.append("|------|------|---------|---------|------|")
    add_row("最新净值",           snapshot.nav)
    add_row("累计净值",           snapshot.accumulated_nav)
    add_row("基金规模（亿元）",    snapshot.fund_size_bn)
    add_row("自成立以来收益",      snapshot.return_since_inception)
    add_row("近 1 年收益",        snapshot.return_1y)
    add_row("近 3 年收益",        snapshot.return_3y)
    add_row("最大回撤",           snapshot.max_drawdown)
    add_row("基准收益（同期）",    snapshot.benchmark_return_pct)
    add_row("超额收益（Alpha）",   snapshot.alpha_pct)

    return "\n".join(rows)


def render_score_table(score: ScoreBreakdown) -> str:
    rows = [
        "| 维度 | 得分（满分 10） | 权重 | 说明 |",
        "|------|--------------|------|------|",
        f"| 历史业绩 | {score.history_score} | 40% | |",
        f"| 市场情绪 | {score.sentiment_score} | 30% | |",
        f"| 风险控制 | {score.risk_score} | 30% | |",
    ]
    if score.alpha_bonus != 0:
        sign = "+" if score.alpha_bonus > 0 else ""
        rows.append(f"| Alpha 调整 | {sign}{score.alpha_bonus} | — | 超额收益奖惩 |")
    rows.append(f"| **综合得分** | **{score.total_score}** | 100% | 置信度：{score.confidence} |")
    return "\n".join(rows)


def render_report(
    snapshot:              FundSnapshot,
    quality:               DataQualityReport,
    score:                 ScoreBreakdown,
    market_commentary:     str,
    sentiment_commentary:  str,
    risk_commentary:       str,
) -> str:
    """
    最终报告模板：章节由代码控制，数字由代码填入，LLM 只提供 commentary
    """

    # 次新基金顶部警告
    new_fund_banner = ""
    if snapshot.run_days and snapshot.run_days < 365:
        new_fund_banner = (
            f"\n> ⚠️ **次新基金警告**：该基金运行仅 **{snapshot.run_days} 天**，"
            "所有历史业绩与风险指标统计意义有限，适配结论已受运行时长约束。\n"
        )

    # 数据矛盾顶部警告
    contradiction_banner = ""
    if quality.contradictions:
        contradiction_banner = (
            "\n> 🔴 **数据矛盾警告**：检测到数据一致性问题，本报告已停止生成正式评级。"
            "请以官方基金公告为准。\n"
        )

    managers_text = "数据缺失"
    if snapshot.managers:
        parts = []
        for m in snapshot.managers:
            mock_tag = "（模拟）" if m.is_mock else ""
            exp = f"从业 {m.experience_years} 年" if m.experience_years else "经验未知"
            parts.append(f"{m.name}{mock_tag}（{exp}）")
        managers_text = "、".join(parts)

    # 适配结论显示
    rating_section = f"**{score.rating}**"
    if score.rating_cap_reason:
        rating_section += f"\n\n> ⚠️ 评级限制原因：{score.rating_cap_reason}"

    return f"""# 📋 {snapshot.code} 基金分析报告
{new_fund_banner}{contradiction_banner}
**基金名称：** {snapshot.name or "数据缺失"}（代码：{snapshot.code}）
**报告日期：** {snapshot.report_date}
**基金运行时长：** {f"{snapshot.run_days} 天" if snapshot.run_days else "无法确认"}
**分析团队：** FundRAG Multi-Agent System V2.0

---

## 一、数据质量说明

{render_data_quality_section(quality)}

---

## 二、基金基本信息

| 项目 | 内容 |
|------|------|
| 基金类型 | {snapshot.fund_type or "数据缺失"} |
| 基金公司 | {snapshot.fund_company or "数据缺失"} |
| 成立日期 | {snapshot.inception_date or "数据缺失"} |
| 基金经理 | {managers_text} |
| 基准指数 | {snapshot.benchmark_name or "未配置"} |

---

## 三、核心指标溯源

{render_metric_table(snapshot)}

---

## 四、综合评分

{render_score_table(score)}

### 📌 适配结论

{rating_section}

**适合人群：** {score.suitability}

---

## 五、行情分析

{market_commentary}

---

## 六、舆情分析

{sentiment_commentary}

---

## 七、风险评估

{risk_commentary}

---

## 八、⚠️ 风险提示

本报告由 AI 系统自动生成，仅用于信息整理和学习演示，**不构成任何投资建议**。
基金投资有风险，过往业绩不代表未来表现。投资者应根据自身风险承受能力独立决策。

---

*本报告由 FundRAG Multi-Agent System V2.0 生成 | 数据来源：akshare / Tavily*
"""
