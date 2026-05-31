# backend/graph.py
"""
LangGraph Multi-Agent 状态机（系统核心）

🌰 整体类比：
    就像一家「基金研究所」的工作流程：

    老板（Orchestrator）收到分析任务
        ↓ 顺序派出三个专家组
    📊行情组 → 📰舆情组 → ⚠️风控组  顺序工作
        ↓ 三组结果汇总
    📝报告员 综合三份报告，输出最终结论

补充决策：
- LangGraph 0.4.x 的 create_react_agent 通过 state_modifier 参数注入 prompt
- MemorySaver 用于多轮对话记忆（同一 session_id 可追问）
- 顺序执行（非并行）原因：舆情分析需要行情分析提供的基金名称，保证信息传递准确
- 每个节点失败时写入 error_messages 并继续，不中断整体流程
"""

import os
import json
from datetime import datetime
from typing import TypedDict, List, Annotated
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent

from backend.tools import (
    tool_get_fund_info,
    tool_get_fund_performance,
    tool_get_manager_info,
    tool_search_fund_news,
    tool_calculate_risk_score,
    tool_compare_fund_ranking,
)
from backend.agents import (
    MARKET_ANALYST_PROMPT,
    SENTIMENT_ANALYST_PROMPT,
    RISK_ANALYST_PROMPT,
    REPORT_WRITER_PROMPT,
)

# 兼容本地 .env 和 Streamlit Cloud Secrets
load_dotenv()

try:
    import streamlit as st
    DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    DEEPSEEK_BASE_URL = st.secrets.get("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
except Exception:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


# ============ 定义状态结构 ============
class FundAnalysisState(TypedDict):
    """
    整个分析流程的「共享白板」
    所有 Agent 都从这里读取信息，也把结果写回这里

    🌰 类比：研究所里的「公告栏」
         每个专家组把分析结果贴在上面
         最后报告员综合公告栏上的所有内容

    补充决策：TypedDict 不支持默认值，所有字段必须在 initial_state 中赋值
    """
    fund_code: str               # 要分析的基金代码
    fund_name: str               # 基金名称（行情分析完成后填入）
    fund_type: str               # 基金类型（行情分析完成后填入）
    user_query: str              # 用户的原始问题
    actual_days: int             # 基金实际运行天数（行情节点提取后填入）
    is_new_fund: bool            # 是否为次新基金（运行 < 365 天）
    market_analysis: str         # 行情分析师的分析结果
    sentiment_analysis: str      # 舆情研究员的分析结果
    risk_analysis: str           # 风险控制官的分析结果
    final_report: str            # 最终综合报告
    data_quality: str            # 数据质量摘要（验证节点填入，供报告节点引用）
    error_messages: List[str]    # 错误信息收集（不中断流程，只记录）
    current_step: str            # 当前执行步骤（供前端显示进度）


def _get_today() -> str:
    """获取今天的日期字符串，注入 Prompt"""
    return datetime.now().strftime("%Y年%m月%d日")


def _create_llm(
    model_name: str = "deepseek-v4-flash",
    temperature: float = 0,
    streaming: bool = True,
    enable_thinking: bool = False,
) -> ChatOpenAI:
    """
    创建 DeepSeek LLM 实例

    可用模型：
        deepseek-v4-flash  → 快速便宜，适合工具调用型 Agent
        deepseek-v4-pro    → 更强推理，适合写最终报告

    🌰 类比：
        flash = 普通快递（够用、便宜、快）
        pro   = 顺丰次日达（贵一点，但质量更好）

    enable_thinking=True 时开启 deepseek-v4-pro 的思考模式，
    会在内部先「打草稿」再输出，回答更深入但稍慢。
    """
    kwargs = dict(
        model=model_name,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        streaming=streaming,
        max_tokens=8192,
    )

    # 思考模式仅 deepseek-v4-pro 支持
    # langchain-openai 1.x 支持直接传 reasoning_effort 参数
    if enable_thinking and model_name == "deepseek-v4-pro":
        kwargs["reasoning_effort"] = "high"   # 可选: "low" / "medium" / "high"

    return ChatOpenAI(**kwargs)


def create_fund_analysis_graph():
    """
    构建完整的 Multi-Agent 分析图

    节点（Node）= 每一步要做的事
    边（Edge）= 步骤之间的跳转关系

    🌰 就像工厂的「流水线设计图」
         原材料 → 车间A → 车间B → 车间C → 成品检验 → 出库
    """

    # ---- 初始化 LLM（DeepSeek v4）----
    # 三个工具调用 Agent：flash，速度优先，不需要深度推理
    llm_fast = _create_llm(
        model_name="deepseek-v4-flash",
        temperature=0,
        enable_thinking=False,
    )
    # 报告撰写 Agent：pro + 思考模式，质量优先
    llm_strong = _create_llm(
        model_name="deepseek-v4-pro",
        temperature=0.1,
        enable_thinking=True,
    )
    today = _get_today()

    # ---- 创建四个专职 Sub-Agent ----

    # Sub-Agent 1：行情分析师
    # 🌰 配备数据查询类工具，就像给「数据分析师」配备 Excel 和数据库权限
    # LangGraph 1.x 中 create_react_agent 的 prompt 参数替代了 state_modifier
    market_agent = create_react_agent(
        model=llm_fast,
        tools=[
            tool_get_fund_info,
            tool_get_fund_performance,
            tool_get_manager_info,
            tool_compare_fund_ranking,
        ],
        prompt=MARKET_ANALYST_PROMPT.format(today=today),
    )

    # Sub-Agent 2：舆情研究员
    # 🌰 只配备新闻搜索工具，就像给「记者」只配备搜索引擎
    sentiment_agent = create_react_agent(
        model=llm_fast,
        tools=[tool_search_fund_news],
        prompt=SENTIMENT_ANALYST_PROMPT.format(today=today),
    )

    # Sub-Agent 3：风险控制官
    # 🌰 配备业绩数据和风险计算工具，就像给「风控官」配备风险模型
    risk_agent = create_react_agent(
        model=llm_fast,
        tools=[
            tool_get_fund_performance,
            tool_calculate_risk_score,
        ],
        prompt=RISK_ANALYST_PROMPT.format(today=today),
    )

    # Sub-Agent 4：报告撰写员
    # 🌰 不需要工具，纯靠语言能力综合信息写报告
    report_agent = create_react_agent(
        model=llm_strong,
        tools=[],
        prompt=REPORT_WRITER_PROMPT,
    )

    # ---- 定义节点函数 ----

    def run_market_analysis(state: FundAnalysisState) -> dict:
        """
        节点1：运行行情分析
        🌰 就像「行情部门」开始工作，查数据、算指标
        """
        print(f"\n{'='*50}")
        print(f"📊 [节点1] 行情分析师开始工作...")
        print(f"   基金代码：{state['fund_code']}")

        query = (
            f"请对基金代码 {state['fund_code']} 进行完整的行情分析。\n\n"
            f"用户问题：{state['user_query']}\n\n"
            f"必须按顺序调用：\n"
            f"1. tool_get_fund_info 获取基本信息\n"
            f"2. tool_get_fund_performance 获取业绩数据（注意读取返回的 actual_period_label 和 actual_days 字段）\n"
            f"3. tool_get_manager_info（用步骤1返回的经理姓名，传入完整字符串）\n"
            f"4. tool_compare_fund_ranking 获取同类排名\n\n"
            f"输出报告时必须使用 actual_period_label 作为时间区间描述，禁止写「近3年」。"
        )

        try:
            config = {"configurable": {"thread_id": f"market_{state['fund_code']}"}}
            result = market_agent.invoke(
                {"messages": [("human", query)]},
                config=config,
            )
            analysis = result["messages"][-1].content
            print(f"✅ [节点1] 行情分析完成，字数：{len(analysis)}")

            # ✅ 从工具调用消息中提取 actual_days（解析 ToolMessage 的 JSON 内容）
            actual_days = 0
            is_new_fund = False
            for msg in result.get("messages", []):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    try:
                        data = json.loads(msg.content)
                        if isinstance(data, dict) and "actual_days" in data:
                            actual_days = int(data["actual_days"])
                            is_new_fund = bool(data.get("is_new_fund", actual_days < 365))
                            print(f"   [节点1] 提取到 actual_days={actual_days}, is_new_fund={is_new_fund}")
                            break
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

            return {
                "market_analysis": analysis,
                "actual_days":     actual_days,
                "is_new_fund":     is_new_fund,
                "current_step":    "行情分析完成 ✅",
            }
        except Exception as e:
            error_msg = f"行情分析失败：{str(e)}"
            print(f"❌ [节点1] {error_msg}")
            return {
                "market_analysis": f"行情分析暂时不可用：{error_msg}",
                "actual_days":     0,
                "is_new_fund":     False,
                "error_messages":  state.get("error_messages", []) + [error_msg],
                "current_step":    "行情分析失败 ❌",
            }

    def run_sentiment_analysis(state: FundAnalysisState) -> dict:
        """
        节点2：运行舆情分析
        🌰 就像「舆情部门」开始刷新闻、看政策
        """
        print(f"\n{'='*50}")
        print(f"📰 [节点2] 舆情研究员开始工作...")

        # 从行情分析结果中提取基金名称，让舆情搜索更精准
        # 🌰 类比：知道了「餐厅名字」再去搜评价，比搜「某餐厅」准确得多
        fund_name = state.get("fund_name") or state["fund_code"]

        # 尝试从行情分析文本中提取基金名称
        market_text = state.get("market_analysis", "")
        if "基金名称：" in market_text:
            try:
                start = market_text.index("基金名称：") + len("基金名称：")
                end = market_text.index("\n", start)
                fund_name = market_text[start:end].strip().split("（")[0].strip()
            except Exception:
                pass

        query = (
            f"请对基金「{fund_name}」（代码：{state['fund_code']}）进行舆情分析。\n\n"
            f"搜索策略（请至少搜索3次）：\n"
            f"1. 搜索「{fund_name} 最新消息 2026」\n"
            f"2. 搜索「{fund_name} 所属行业 政策 2026」（先判断该基金主投什么行业）\n"
            f"3. 搜索「{fund_name} 基金公司 动态」\n\n"
            f"综合输出舆情分析报告。"
        )

        try:
            config = {"configurable": {"thread_id": f"sentiment_{state['fund_code']}"}}
            result = sentiment_agent.invoke(
                {"messages": [("human", query)]},
                config=config,
            )
            analysis = result["messages"][-1].content
            print(f"✅ [节点2] 舆情分析完成，字数：{len(analysis)}")
            return {
                "sentiment_analysis": analysis,
                "fund_name": fund_name,  # 回写基金名称供后续节点使用
                "current_step": "舆情分析完成 ✅",
            }
        except Exception as e:
            error_msg = f"舆情分析失败：{str(e)}"
            print(f"❌ [节点2] {error_msg}")
            return {
                "sentiment_analysis": f"舆情分析暂时不可用：{error_msg}",
                "error_messages": state.get("error_messages", []) + [error_msg],
                "current_step": "舆情分析失败 ❌",
            }

    def run_risk_analysis(state: FundAnalysisState) -> dict:
        """
        节点3：运行风险分析
        🌰 就像「风控部门」给基金做体检，量血压、测心率
        """
        print(f"\n{'='*50}")
        print(f"⚠️  [节点3] 风险控制官开始工作...")

        actual_days = state.get("actual_days", 0)

        query = (
            f"请对基金代码 {state['fund_code']} 进行风险评估。\n\n"
            f"已知该基金实际运行天数为 {actual_days} 天。\n\n"
            f"步骤（严格按顺序）：\n"
            f"1. 调用 tool_get_fund_performance 获取 max_drawdown_pct 和 total_return_pct\n"
            f"2. 调用 tool_calculate_risk_score，参数：\n"
            f"   - max_drawdown = 从步骤1获取的最大回撤数值（浮点数，如 25.3）\n"
            f"   - return_rate  = 从步骤1获取的总收益率数值（浮点数，如 45.2）\n"
            f"   - fund_type    = 基金类型（如「股票型」「混合型」）\n"
            f"   - actual_days  = {actual_days}    ← 必须传入此值，不得省略\n"
            f"3. 综合输出多维度风险评估报告\n\n"
            f"参考行情分析结论：\n{state.get('market_analysis', '暂无')[:500]}"
        )

        try:
            config = {"configurable": {"thread_id": f"risk_{state['fund_code']}"}}
            result = risk_agent.invoke(
                {"messages": [("human", query)]},
                config=config,
            )
            analysis = result["messages"][-1].content
            print(f"✅ [节点3] 风险评估完成，字数：{len(analysis)}")
            return {
                "risk_analysis": analysis,
                "current_step": "风险评估完成 ✅",
            }
        except Exception as e:
            error_msg = f"风险分析失败：{str(e)}"
            print(f"❌ [节点3] {error_msg}")
            return {
                "risk_analysis": f"风险分析暂时不可用：{error_msg}",
                "error_messages": state.get("error_messages", []) + [error_msg],
                "current_step": "风险评估失败 ❌",
            }

    def validate_data_quality(state: FundAnalysisState) -> dict:
        """
        节点3.5：数据质量验证（行情分析后、舆情分析前插入）
        检查哪些数据是真实 akshare 数据，哪些是 mock 数据，
        生成 data_quality 摘要供后续报告节点引用。
        🌰 类比：「质检员」在流水线上检查食材来源，贴上「真实/模拟」标签
        """
        print(f"\n{'='*50}")
        print(f"🔍 [验证节点] 数据质量检查...")

        market = state.get("market_analysis", "")

        has_real_data = "akshare实时数据" in market or (
            "akshare" in market and "mock" not in market.lower() and "模拟" not in market
        )
        has_mock_data = (
            "mock" in market.lower()
            or "模拟数据" in market
            or "数据获取失败" in market
        )

        issues = []
        if "业绩获取失败" in market or "模拟数据" in market:
            issues.append("业绩数据含模拟值")
        if "经理" in market and ("未知" in market or "模拟" in market):
            issues.append("基金经理信息不完整")
        if "排名" in market and "模拟" in market:
            issues.append("同类排名为估算值")

        if not issues:
            completeness = "完整（akshare实时数据）"
            quality_notice = "✅ 本报告所有量化数据均来自 akshare 实时接口，数据可信。"
        else:
            completeness = f"部分缺失（含模拟数据：{', '.join(issues)}）"
            quality_notice = (
                f"⚠️ 以下数据项使用了估算/模拟值（※标注处仅供参考）：\n"
                + "\n".join(f"- {i}" for i in issues)
                + "\n\n建议：如需精确数据，请稍后重试或直接查询基金公司官网。"
            )

        print(f"   数据完整性：{completeness}")
        return {
            "data_quality": quality_notice,
            "current_step": "数据质量验证完成 ✅",
        }

    def run_report_generation(state: FundAnalysisState) -> dict:
        """
        节点4：汇总生成最终报告
        🌰 就像「报告员」把三份分析综合成一份完整报告，交给老板
        """
        print(f"\n{'='*50}")
        print(f"📝 [节点4] 报告撰写员开始汇总...")

        # ✅ 根据具体状态字段构建数据质量说明（比文本分析更准确）
        actual_days = state.get("actual_days", 0)
        is_new_fund = state.get("is_new_fund", False)
        errors      = state.get("error_messages", [])

        if is_new_fund:
            data_quality_notice = (
                f"⚠️ **次新基金警告**：该基金仅运行 {actual_days} 天，"
                f"所有历史业绩、排名及风险指标均不具备统计显著性，"
                f"请以官方基金公告为准，本报告分析结论参考价值有限。"
            )
        elif errors:
            data_quality_notice = (
                f"部分数据获取失败（{len(errors)}项），已使用模拟数据填充，"
                f"相关指标仅供参考，请以官方渠道数据为准。"
            )
        else:
            data_quality_notice = "✅ 本报告所有量化数据均来自 akshare 实时接口，数据可信。"

        synthesis_query = (
            f"请综合以下三份分析报告，生成最终的基金投研报告：\n\n"
            f"{'='*40}\n"
            f"【行情分析报告】\n{state.get('market_analysis', '数据获取失败')}\n\n"
            f"{'='*40}\n"
            f"【舆情分析报告】\n{state.get('sentiment_analysis', '数据获取失败')}\n\n"
            f"{'='*40}\n"
            f"【风险评估报告】\n{state.get('risk_analysis', '数据获取失败')}\n\n"
            f"{'='*40}\n"
            f"基金代码：{state['fund_code']}\n"
            f"基金实际运行天数：{actual_days}天（{'次新基金，禁止给出买入评级' if is_new_fund else '数据有效'}）\n"
            f"用户原始问题：{state['user_query']}\n\n"
            f"请将以下内容填入报告「七、数据质量说明」章节（直接替换 {{DATA_QUALITY_NOTICE}}）：\n"
            f"{data_quality_notice}"
        )

        try:
            config = {"configurable": {"thread_id": f"report_{state['fund_code']}"}}
            result = report_agent.invoke(
                {"messages": [("human", synthesis_query)]},
                config=config,
            )
            final_report = result["messages"][-1].content

            # ✅ 兜底替换：防止 LLM 未替换占位符
            final_report = final_report.replace("{DATA_QUALITY_NOTICE}", data_quality_notice)

            print(f"✅ [节点4] 报告生成完成，字数：{len(final_report)}")
            print(f"\n🎉 全部节点执行完毕！")
            return {
                "final_report":  final_report,
                "data_quality":  data_quality_notice,
                "current_step":  "报告生成完成 🎉",
            }
        except Exception as e:
            error_msg = f"报告生成失败：{str(e)}"
            print(f"❌ [节点4] {error_msg}")
            fallback_report = (
                f"# 📋 基金分析报告（自动降级版）\n\n"
                f"> 报告生成失败，以下为各子模块原始输出\n\n"
                f"## 行情分析\n{state.get('market_analysis', '无数据')}\n\n"
                f"## 舆情分析\n{state.get('sentiment_analysis', '无数据')}\n\n"
                f"## 风险评估\n{state.get('risk_analysis', '无数据')}\n"
            )
            return {
                "final_report":   fallback_report,
                "error_messages": state.get("error_messages", []) + [error_msg],
                "current_step":   "报告生成失败（已降级）❌",
            }

    # ---- 构建状态图 ----
    # 🌰 类比：画出「工厂流水线图」，标注每道工序的顺序
    workflow = StateGraph(FundAnalysisState)

    # 添加节点
    workflow.add_node("market_analysis", run_market_analysis)
    workflow.add_node("validate_data", validate_data_quality)   # 新增：数据质量验证
    workflow.add_node("sentiment_analysis", run_sentiment_analysis)
    workflow.add_node("risk_analysis", run_risk_analysis)
    workflow.add_node("report_generation", run_report_generation)

    # 设置入口：从行情分析开始
    workflow.set_entry_point("market_analysis")

    # 定义执行顺序（流水线）
    # 🌰 行情 → 数据验证 → 舆情 → 风控 → 报告
    workflow.add_edge("market_analysis", "validate_data")        # 验证节点插入行情之后
    workflow.add_edge("validate_data", "sentiment_analysis")
    workflow.add_edge("sentiment_analysis", "risk_analysis")
    workflow.add_edge("risk_analysis", "report_generation")
    workflow.add_edge("report_generation", END)

    # 编译成可执行的图（不用 checkpointer，用外部 session_id 管理）
    app = workflow.compile()

    print("✅ FundRAG Multi-Agent 图构建完成")
    print("   节点数量：5 个")
    print("   执行顺序：行情分析 → 数据验证 → 舆情分析 → 风险评估 → 报告生成")

    return app


def run_fund_analysis(fund_code: str, user_query: str, session_id: str = "default") -> dict:
    """
    执行完整的基金分析流程（对外统一入口）

    参数:
        fund_code:  基金代码，如 "110022"
        user_query: 用户问题，如 "这只基金值得投资吗？"
        session_id: 会话 ID（保留参数，当前版本不做跨次记忆）

    返回:
        FundAnalysisState 字典，包含完整分析结果

    🌰 使用示例：
        result = run_fund_analysis("110022", "帮我分析这只基金")
        print(result["final_report"])
    """

    # 初始化状态，所有字段必须赋值（TypedDict 要求）
    initial_state: FundAnalysisState = {
        "fund_code":         fund_code.strip(),
        "fund_name":         fund_code.strip(),   # 分析过程中会自动更新为真实名称
        "fund_type":         "混合型",             # 分析过程中会自动更新
        "user_query":        user_query,
        "actual_days":       0,                   # 行情节点执行后填入
        "is_new_fund":       False,               # 行情节点执行后填入
        "market_analysis":   "",
        "sentiment_analysis": "",
        "risk_analysis":     "",
        "final_report":      "",
        "data_quality":      "",
        "error_messages":    [],
        "current_step":      "开始分析...",
    }

    print(f"\n{'#'*50}")
    print(f"🚀 开始分析基金：{fund_code}")
    print(f"   用户问题：{user_query}")
    print(f"   会话 ID：{session_id}")
    print(f"{'#'*50}")

    graph = create_fund_analysis_graph()
    final_state = graph.invoke(initial_state)

    error_count = len(final_state.get("error_messages", []))
    print(f"\n{'#'*50}")
    print(f"🏁 分析完成！错误数量：{error_count}")
    if error_count > 0:
        print(f"   错误详情：{final_state['error_messages']}")
    print(f"{'#'*50}\n")

    return final_state
