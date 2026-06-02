# frontend/app.py
"""
Streamlit 前端主界面
🌰 类比：整个投研系统的「驾驶舱」
         用户在这里输入基金代码，看到实时分析进度，
         最终拿到完整的投研报告

补充决策：
- Session State 全部在 main() 之前初始化，避免重渲染问题
- Agent 状态表格用 st.markdown 渲染，兼容性更好
- 历史记录最多保存 10 条（内存限制），展示最近 5 条
- 兼容本地 .env 和 Streamlit Cloud Secrets 的 API Key 读取
"""

import streamlit as st
import sys
import os
import time

from dotenv import load_dotenv
load_dotenv()

# 兼容 Streamlit Cloud Secrets 和本地 .env 两种方式
def _load_secrets():
    """同时支持本地.env和Streamlit Cloud部署"""
    try:
        import streamlit as st
        # Streamlit Cloud 环境：将 secrets 写入环境变量，供 backend 模块读取
        os.environ["DEEPSEEK_API_KEY"] = st.secrets.get(
            "DEEPSEEK_API_KEY",
            os.getenv("DEEPSEEK_API_KEY", "")
        )
        os.environ["DEEPSEEK_BASE_URL"] = st.secrets.get(
            "DEEPSEEK_BASE_URL",
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        )
        os.environ["TAVILY_API_KEY"] = st.secrets.get(
            "TAVILY_API_KEY",
            os.getenv("TAVILY_API_KEY", "")
        )
    except Exception:
        pass  # 本地运行时直接用 .env

_load_secrets()

# 将项目根目录加入 sys.path，确保 backend 模块可以导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============ 页面配置（必须第一个 st 调用）============
st.set_page_config(
    page_title="FundRAG - 基金智能投研助手",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============ Module 4: 认证检查 ============
try:
    import sys
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from auth import is_authenticated, render_login_page, render_user_sidebar
    if not is_authenticated():
        render_login_page()
        st.stop()
    with st.sidebar:
        render_user_sidebar()
except ImportError:
    pass   # auth.py 不存在时跳过认证（开发模式）

# ============ 自定义 CSS 样式 ============
st.markdown("""
<style>
    .main-title {
        font-size: 2.0rem;
        font-weight: bold;
        background: linear-gradient(90deg, #11998e 0%, #38ef7d 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .subtitle {
        color: #888;
        font-size: 0.95rem;
        margin-top: 0;
    }
    .agent-card {
        background: #1a1a2e;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        font-family: monospace;
        font-size: 0.88rem;
        margin: 0.3rem 0;
        border-left: 3px solid #38ef7d;
    }
    .disclaimer {
        background: #fff8e1;
        border: 1px solid #ffcc02;
        border-radius: 8px;
        padding: 0.7rem 1rem;
        font-size: 0.85rem;
        color: #555;
    }
</style>
""", unsafe_allow_html=True)

# ============ 在 main() 之前初始化 Session State ============
# 🌰 类比：开店前先把收银台、货架、台账都准备好
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "analysis_history" not in st.session_state:
    st.session_state.analysis_history = []   # 最多保留 10 条
if "is_analyzing" not in st.session_state:
    st.session_state.is_analyzing = False
if "agent_statuses" not in st.session_state:
    st.session_state.agent_statuses = {
        "market": "⏳ 等待中",
        "sentiment": "⏳ 等待中",
        "risk": "⏳ 等待中",
        "report": "⏳ 等待中",
    }
if "quick_fund" not in st.session_state:
    st.session_state.quick_fund = ""


def render_agent_status_table(statuses: dict) -> None:
    """
    渲染四个 Agent 的状态表格
    🌰 类比：「项目进度看板」，实时显示每个部门的工作状态
    """
    st.markdown(f"""
| Agent | 状态 |
|:------|:-----|
| 📊 行情分析师 | {statuses['market']} |
| 📰 舆情研究员 | {statuses['sentiment']} |
| ⚠️ 风险控制官 | {statuses['risk']} |
| 📝 报告撰写员 | {statuses['report']} |
""")


def render_data_quality_badge(result: dict) -> None:
    """
    V2.3：数据质量 Badge。
    ✅ 所有文案完全硬编码
    ✅ 「适配结论」文案统一（不出现「修正结论」/「建议结论」）
    ✅ limited 等级处理（次新基金）
    """
    quality_json = result.get("data_quality_json", "")
    if not quality_json:
        st.warning("⬜ 数据质量信息未生成")
        return

    try:
        import json
        q          = json.loads(quality_json)
        level      = q.get("level", "unknown")
        mock_count = int(q.get("mock_metric_count", 0))
        run_days   = q.get("run_days", None)
        contras    = q.get("contradictions", [])
        warnings   = q.get("warnings", [])

        # ✅ 全部硬编码，每个字都经过人工校对
        if level == "real":
            st.success("🟢 数据完整｜核心指标均来自真实接口，**适配结论**可信")
        elif level == "limited":
            day_str = f"{run_days} 天" if run_days else "不足 1 年"
            st.warning(
                f"🟡 样本受限｜基金运行仅 {day_str}，"        # ✅ "样本受限"（不是"样本模型"）
                "数据来源真实但统计意义有限，**适配结论**为「持续观察」"  # ✅ "适配结论"
            )
        elif level == "partial":
            st.warning(
                f"🟡 部分模拟｜{mock_count} 项指标为模拟数据，"
                "**适配结论**为「信息不足」，不输出正式评级"    # ✅ "不输出"（不是"未输出"）
            )
        elif level == "failed":
            st.error(
                f"🔴 数据矛盾｜检测到 {len(contras)} 处不一致，"
                "**适配结论**为「无法评级」"
            )
            for c in contras[:3]:
                st.caption(f"  ⛔ {c}")
        else:
            st.error("🔴 数据不可用｜无法生成有效分析")

        if warnings:
            with st.expander(f"⚠️ {len(warnings)} 条数据说明"):
                for w in warnings:
                    st.caption(f"• {w}")

    except Exception as e:
        st.warning(f"⬜ 数据质量 Badge 加载失败：{e}")


def render_score_section(result: dict) -> None:
    """
    V2.3：独立评分区。
    ✅ 评级使用 normalize_rating + ALLOWED_RATINGS 双重校验
    ✅ total=None 时显示「不计算」
    ✅ 「📌 适配结论」label 完全 hardcode
    """
    score_json = result.get("score_json", "")
    if not score_json:
        return

    try:
        import json
        from backend.value_cleaner import normalize_rating
        from backend.constants import ALLOWED_RATINGS

        score = json.loads(score_json)

        # ✅ 双重校验：normalize_rating + ALLOWED_RATINGS 白名单
        raw_rating  = score.get("rating", "无法评级")
        norm_rating = normalize_rating(raw_rating)
        safe_rating = norm_rating if norm_rating in ALLOWED_RATINGS else "无法评级"

        total  = score.get("total_score", None)
        conf   = score.get("confidence_label", score.get("confidence", "低"))
        rlevel = score.get("risk_level", "未知")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if total is None:
                st.metric("综合得分", "不计算",
                          help="含模拟数据或次新基金时不输出正式综合分")
            else:
                st.metric("综合得分", f"{total}/10")
        with col2:
            st.metric("置信度", conf)
        with col3:
            st.metric("风险等级", rlevel)
        with col4:
            st.metric("📌 适配结论", safe_rating)

        cap_reason = score.get("rating_cap_reason", "")
        if cap_reason:
            st.warning(f"⚠️ 评级限制：{cap_reason}")

    except Exception as e:
        st.caption(f"评分展示异常：{e}")


def render_raw_metrics_expander(result: dict) -> None:
    """
    V2.0：原始指标溯源展开区
    """
    snapshot_json = result.get("snapshot_json", "")
    if not snapshot_json:
        return

    try:
        from backend.schemas import FundSnapshot
        import pandas as pd
        snapshot = FundSnapshot.model_validate_json(snapshot_json)
        with st.expander("🔬 原始指标溯源（点击展开）"):
            st.caption("每项指标均注明来源、截止日期、是否模拟")
            metric_fields = [
                ("最新净值",       snapshot.nav),
                ("基金规模(亿元)", snapshot.fund_size_bn),
                ("自成立收益",     snapshot.return_since_inception),
                ("近1年收益",      snapshot.return_1y),
                ("近3年收益",      snapshot.return_3y),
                ("最大回撤",       snapshot.max_drawdown),
                ("基准收益",       snapshot.benchmark_return_pct),
                ("超额收益Alpha",  snapshot.alpha_pct),
            ]
            rows = []
            for label, metric in metric_fields:
                if metric is None:
                    rows.append({"指标": label, "数值": "缺失", "性质": "—",
                                 "截止日期": "—", "来源": "—"})
                else:
                    rows.append({
                        "指标":     label,
                        "数值":     f"{metric.value}{metric.unit or ''}",
                        "性质":     "🔴模拟" if metric.is_mock else "✅真实",
                        "截止日期": str(metric.as_of) if metric.as_of else "未知",
                        "来源":     metric.source,
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
    except Exception as e:
        st.caption(f"指标溯源加载失败：{e}")


def main():

    # ---- 标题区 ----
    st.markdown('<div class="main-title">📈 FundRAG Multi-Agent</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">基金智能投研助手 | 行情分析 × 舆情研究 × 风险评估 × 综合报告</div>', unsafe_allow_html=True)
    st.divider()

    # ---- 布局：左侧输入面板，右侧结果展示 ----
    col_left, col_right = st.columns([1, 2.2])

    # ===== 左侧：输入区 =====
    with col_left:
        st.subheader("🔍 基金分析输入")

        # ---- 基金代码输入 ----
        # 支持快捷按钮设置的值
        default_code = st.session_state.quick_fund if st.session_state.quick_fund else ""
        fund_code = st.text_input(
            "基金代码",
            value=default_code,
            placeholder="例如：110022（易方达消费）",
            help="6 位基金代码，可在天天基金网或支付宝基金页面查询",
            key="fund_code_input",
        )
        # 使用后清空 quick_fund，避免重渲染时覆盖用户输入
        if st.session_state.quick_fund:
            st.session_state.quick_fund = ""

        # ---- 常用基金快捷按钮 ----
        st.caption("📌 常用基金快捷选择：")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("110022\n易方达消费", use_container_width=True, key="btn_110022"):
                st.session_state.quick_fund = "110022"
                st.rerun()
            if st.button("000001\n华夏成长", use_container_width=True, key="btn_000001"):
                st.session_state.quick_fund = "000001"
                st.rerun()
        with col_b:
            if st.button("161725\n招商中证白酒", use_container_width=True, key="btn_161725"):
                st.session_state.quick_fund = "161725"
                st.rerun()
            if st.button("270042\n广发纳斯达克", use_container_width=True, key="btn_270042"):
                st.session_state.quick_fund = "270042"
                st.rerun()

        # ---- 分析问题输入 ----
        user_query = st.text_area(
            "你想了解什么？",
            value="请对这只基金进行信息整理、风险分析和适配性观察。",
            height=90,
            help="可以具体描述你的关注点，例如：适合保守型投资者吗？近期有没有风险？",
        )

        st.divider()

        # ---- 开始分析按钮 ----
        can_analyze = bool(fund_code) and not st.session_state.is_analyzing
        analyze_btn = st.button(
            "🚀 开始 Multi-Agent 分析",
            disabled=not can_analyze,
            use_container_width=True,
            type="primary",
        )

        if not fund_code:
            st.caption("请先输入基金代码")

        # ---- Agent 状态面板 ----
        st.subheader("🤖 Agent 工作状态")
        render_agent_status_table(st.session_state.agent_statuses)

        # ---- 历史分析记录 ----
        if st.session_state.analysis_history:
            st.subheader("📚 历史分析")
            # 倒序展示（最新在上），最多显示 5 条
            recent = list(reversed(st.session_state.analysis_history))[:5]
            for i, hist in enumerate(recent):
                label = f"📋 {hist['fund_code']} · {hist['time']}"
                if st.button(label, use_container_width=True, key=f"hist_{i}"):
                    st.session_state.analysis_result = hist["result"]
                    st.rerun()

        # ---- 免责声明 ----
        st.markdown("""
<div class="disclaimer">
⚠️ <b>免责声明：</b>本系统仅供学习演示，不构成任何投资建议。基金有风险，投资需谨慎。
</div>
""", unsafe_allow_html=True)

    # ===== 右侧：分析结果区 =====
    with col_right:

        # ---- 处理分析请求 ----
        if analyze_btn and fund_code:
            st.session_state.is_analyzing = True
            st.session_state.analysis_result = None

            # 重置 Agent 状态
            st.session_state.agent_statuses = {
                "market": "🔄 分析中...",
                "sentiment": "⏳ 等待中",
                "risk": "⏳ 等待中",
                "report": "⏳ 等待中",
            }

            with st.spinner("🤖 Multi-Agent 团队正在协作分析（约需 30-90 秒）..."):
                progress_bar = st.progress(0, text="准备中...")

                try:
                    # 导入放在函数内，确保 API Key 已从 secrets 加载
                    from backend.graph import run_fund_analysis

                    progress_bar.progress(10, text="📊 行情分析师：正在查询基金数据...")
                    st.session_state.agent_statuses["market"] = "🔄 分析中..."

                    result = run_fund_analysis(
                        fund_code=fund_code.strip(),
                        user_query=user_query,
                        session_id=f"fund_{fund_code}_{int(time.time())}",
                    )

                    progress_bar.progress(100, text="✅ 分析完成！")

                    # 更新所有 Agent 状态（兼容 V1/V2 字段名）
                    error_count = len(result.get("errors", result.get("error_messages", [])))
                    market_ok   = result.get("market_commentary") or result.get("market_analysis")
                    sentiment_ok = result.get("sentiment_commentary") or result.get("sentiment_analysis")
                    risk_ok     = result.get("risk_commentary") or result.get("risk_analysis")
                    st.session_state.agent_statuses = {
                        "market":    "✅ 完成" if market_ok else "❌ 失败",
                        "sentiment": "✅ 完成" if sentiment_ok else "❌ 失败",
                        "risk":      "✅ 完成" if risk_ok else "❌ 失败",
                        "report":    "✅ 完成" if result.get("final_report") else "❌ 失败",
                    }

                    st.session_state.analysis_result = result

                    # 保存到历史（最多 10 条）
                    st.session_state.analysis_history.append({
                        "fund_code": fund_code.strip(),
                        "time": time.strftime("%H:%M"),
                        "result": result,
                    })
                    if len(st.session_state.analysis_history) > 10:
                        st.session_state.analysis_history.pop(0)

                    if error_count > 0:
                        st.warning(f"分析完成，但有 {error_count} 个子任务遇到问题（不影响整体结果）")

                    time.sleep(0.3)
                    progress_bar.empty()

                except Exception as e:
                    st.error(f"❌ 分析失败：{str(e)}\n\n请检查 API Key 配置是否正确。")
                    progress_bar.empty()
                    st.session_state.agent_statuses = {
                        "market": "❌ 失败", "sentiment": "❌ 失败",
                        "risk": "❌ 失败", "report": "❌ 失败",
                    }
                finally:
                    st.session_state.is_analyzing = False

            st.rerun()

        # ---- 显示分析结果 ----
        if st.session_state.analysis_result:
            result = st.session_state.analysis_result
            fund_code_display = result.get("fund_code", "")

            # 顶部操作栏
            col_title, col_export = st.columns([3, 1])
            with col_title:
                fund_display_name = result.get("fund_name", fund_code_display)
                st.subheader(f"📋 {fund_display_name} 投研报告")
            with col_export:
                report_content = result.get("final_report", "")
                if report_content:
                    # Markdown 下载（原有）
                    st.download_button(
                        label="📥 导出 Markdown",
                        data=report_content.encode("utf-8"),
                        file_name=f"fund_{fund_code_display}_report.md",
                        mime="text/markdown",
                        use_container_width=True,
                    )

                    # Module 5: PDF 下载（懒生成，避免每次渲染重复生成）
                    pdf_cache_key = f"pdf_{fund_code_display}_{hash(report_content)}"
                    if pdf_cache_key not in st.session_state:
                        st.session_state[pdf_cache_key] = None

                    if st.button("🖨️ 生成 PDF", use_container_width=True, key="gen_pdf_btn"):
                        with st.spinner("正在生成 PDF，约需 5-15 秒..."):
                            try:
                                from backend.pdf_exporter import export_to_pdf
                                pdf_bytes = export_to_pdf(
                                    report_md=report_content,
                                    fund_code=fund_code_display,
                                    fund_name=result.get("fund_name", fund_code_display),
                                    report_date=str(time.strftime("%Y-%m-%d")),
                                )
                                st.session_state[pdf_cache_key] = pdf_bytes
                                if not pdf_bytes:
                                    st.warning("PDF 生成失败：请安装 weasyprint 或 xhtml2pdf")
                            except Exception as e:
                                st.error(f"PDF 生成失败：{e}")

                    cached_pdf = st.session_state.get(pdf_cache_key)
                    if cached_pdf:
                        st.download_button(
                            label="📄 下载 PDF",
                            data=cached_pdf,
                            file_name=f"fund_{fund_code_display}_report.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                        )

            # ---- Tab 分组展示 ----
            tab_final, tab_market, tab_sentiment, tab_risk = st.tabs([
                "📋 综合报告", "📊 行情分析", "📰 舆情分析", "⚠️ 风险评估"
            ])

            with tab_final:
                # V2.1：数据质量 Badge
                render_data_quality_badge(result)
                st.divider()

                # V2.1：独立评分区（修复截断问题）
                render_score_section(result)
                st.divider()

                # V2.1：原始指标溯源
                render_raw_metrics_expander(result)
                st.divider()

                final_report = result.get("final_report", "报告生成中...")
                st.markdown(final_report)

                # 显示错误详情（如有）
                errors = result.get("errors", result.get("error_messages", []))
                if errors:
                    with st.expander(f"⚠️ {len(errors)} 项数据问题（已降级处理）"):
                        for err in errors:
                            st.warning(err)

            with tab_market:
                st.markdown("### 📊 行情分析")
                # V2.1 字段：market_commentary；V2.0 字段：market_analysis
                market_report = result.get("market_commentary") or result.get("market_analysis", "")
                if market_report:
                    st.markdown(market_report)
                else:
                    st.warning("行情分析数据不可用")

            with tab_sentiment:
                st.markdown("### 📰 舆情分析")
                sentiment_report = (result.get("sentiment_commentary")
                                    or result.get("sentiment_analysis", ""))
                if sentiment_report:
                    st.markdown(sentiment_report)
                else:
                    st.warning("舆情分析数据不可用")

            with tab_risk:
                st.markdown("### ⚠️ 风险评估")
                risk_report = result.get("risk_commentary") or result.get("risk_analysis", "")
                if risk_report:
                    st.markdown(risk_report)
                else:
                    st.warning("风险评估数据不可用")

        else:
            # ---- 未开始分析时的引导界面 ----
            st.info("👈 在左侧输入基金代码，点击「开始 Multi-Agent 分析」")

            st.markdown("""
### 🤖 V2.0 系统架构

本系统采用 **LangGraph Multi-Agent V2.0 协作架构**：
> 核心原则：**数据、评分、评级由代码决定；LLM只负责解释**

| 节点 | 职责 | 技术 |
|:-----|:-----|:-----|
| 📡 数据拉取 | 构建 FundSnapshot（含 is_mock 标记） | akshare 实时接口 |
| 🔍 质量校验 | 检测矛盾/缺失/模拟，写入 run_days | 确定性逻辑 |
| 📊 确定性评分 | 代码计算所有分数，LLM 不可修改 | Python 评分模型 |
| 📊 行情解释 | 解释 snapshot_json，禁止编造数字 | DeepSeek v4-flash |
| 📰 舆情分析 | 多空平衡搜索 + SENTIMENT_SCORE | Tavily + DeepSeek |
| ⚠️ 风险解释 | 解释 score_json，不重新计算 | DeepSeek v4-flash |
| 📝 模板渲染 | 代码填表格，LLM 只填解释段落 | report_renderer.py |
| 🛡️ 质量守卫 | 拦截禁用词/重复章节/违规建议 | output_guard.py |

### 🔄 V2.0 工作流程

```
输入基金代码
    ↓
📡 数据拉取（FundSnapshot + is_mock 标记）
    ↓
🔍 数据质量校验（矛盾检测 → 拦截 or 继续）
    ↓
📊 确定性评分（代码裁判，不依赖 LLM）
    ↓
📊 行情解释（LLM 解释数据）
    ↓
📰 舆情分析（多空平衡 + SENTIMENT_SCORE）
    ↓
⚠️ 风险解释（LLM 解释评分）
    ↓
📝 模板渲染（代码填数字，LLM 填解释）
    ↓
🛡️ 质量守卫（禁用词/章节/占位符）
    ↓
完整投研报告（含指标溯源）
```

> ⚠️ **免责声明**：本系统仅供学习演示，不构成任何投资建议。基金有风险，投资需谨慎。过往业绩不代表未来表现。
""")


if __name__ == "__main__":
    main()
