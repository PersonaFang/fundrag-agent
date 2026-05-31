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
            value="请对这只基金进行全面分析，给出投资建议。",
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

                    # 更新所有 Agent 状态
                    final_step = result.get("current_step", "")
                    error_count = len(result.get("error_messages", []))
                    st.session_state.agent_statuses = {
                        "market": "✅ 完成" if result.get("market_analysis") else "❌ 失败",
                        "sentiment": "✅ 完成" if result.get("sentiment_analysis") else "❌ 失败",
                        "risk": "✅ 完成" if result.get("risk_analysis") else "❌ 失败",
                        "report": "✅ 完成" if result.get("final_report") else "❌ 失败",
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
                    st.download_button(
                        label="📥 导出 Markdown",
                        data=report_content.encode("utf-8"),
                        file_name=f"fund_{fund_code_display}_report.md",
                        mime="text/markdown",
                        use_container_width=True,
                    )

            # ---- Tab 分组展示 ----
            tab_final, tab_market, tab_sentiment, tab_risk = st.tabs([
                "📋 综合报告", "📊 行情分析", "📰 舆情分析", "⚠️ 风险评估"
            ])

            with tab_final:
                # 次新基金额外提示
                if result.get("is_new_fund"):
                    st.warning(
                        f"⚠️ **次新基金提示**：该基金运行仅 {result.get('actual_days', 0)} 天，"
                        "报告中所有历史业绩指标参考价值有限，请谨慎参考。"
                    )
                final_report = result.get("final_report", "报告生成中...")
                st.markdown(final_report)

                # 显示错误详情（如有）
                errors = result.get("error_messages", [])
                if errors:
                    with st.expander(f"⚠️ {len(errors)} 个子任务遇到问题（点击查看详情）"):
                        for err in errors:
                            st.warning(err)

            with tab_market:
                st.markdown("### 📊 行情分析师完整报告")
                market_report = result.get("market_analysis", "数据获取失败")
                if market_report:
                    st.markdown(market_report)
                else:
                    st.warning("行情分析数据不可用")

            with tab_sentiment:
                st.markdown("### 📰 舆情研究员完整报告")
                sentiment_report = result.get("sentiment_analysis", "数据获取失败")
                if sentiment_report:
                    st.markdown(sentiment_report)
                else:
                    st.warning("舆情分析数据不可用")

            with tab_risk:
                st.markdown("### ⚠️ 风险控制官完整报告")
                risk_report = result.get("risk_analysis", "数据获取失败")
                if risk_report:
                    st.markdown(risk_report)
                else:
                    st.warning("风险评估数据不可用")

        else:
            # ---- 未开始分析时的引导界面 ----
            st.info("👈 在左侧输入基金代码，点击「开始 Multi-Agent 分析」")

            st.markdown("""
### 🤖 系统架构

本系统采用 **LangGraph Multi-Agent 协作架构**，由 4 个专职 AI 组成：

| Agent | 职责 | 使用工具 |
|:------|:-----|:---------|
| 📊 行情分析师 | 量化数据分析（净值/回撤/排名） | akshare 金融数据接口 |
| 📰 舆情研究员 | 新闻情绪分析（基金/行业/政策） | Tavily 实时搜索引擎 |
| ⚠️ 风险控制官 | 风险量化评估（评分/等级/维度） | 内置风险评分模型 |
| 📝 报告撰写员 | 综合研判，生成完整投研报告 | DeepSeek v4-pro |

### 🔄 工作流程

```
输入基金代码
    ↓
📊 行情分析（akshare数据）
    ↓
🔍 数据质量验证
    ↓
📰 舆情分析（Tavily新闻）
    ↓
⚠️ 风险评估（量化模型）
    ↓
📝 综合报告（DeepSeek v4-pro）
    ↓
完整投研报告
```

> ⚠️ **免责声明**：本系统仅供学习演示，不构成任何投资建议。基金有风险，投资需谨慎。过往业绩不代表未来表现。
""")


if __name__ == "__main__":
    main()
