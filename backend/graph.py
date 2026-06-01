# backend/graph.py
"""
LangGraph Multi-Agent V2.0 状态机

核心原则：数据、评分、评级由代码决定；LLM只负责解释。

改进：
- P0：每次分析生成唯一 run_id，彻底消除跨基金状态污染
- 9节点流水线：fetch_snapshot → validate_quality → [data_issue_report | scoring_node]
                → market_agent → sentiment_agent → risk_agent → render_report → END
- FundRAGState：新增 run_id、snapshot_json、data_quality_json、score_json
- LLM Agent 只负责解释（commentary），不再生成数字/表格
- 舆情 Agent 输出 SENTIMENT_SCORE，由 graph 层提取并更新总分

🌰 类比：
    代码 = 财务部（算数字）
    LLM  = 分析师（写解释）
    两者职责严格分离
"""

import os
import re
import uuid
import time
from datetime import datetime
from typing import TypedDict, List

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from backend.tools import (
    tool_search_fund_news_balanced,
)
from backend.agents import (
    MARKET_ANALYST_PROMPT,
    SENTIMENT_ANALYST_PROMPT,
    RISK_ANALYST_PROMPT,
)

load_dotenv()

try:
    import streamlit as st
    DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    DEEPSEEK_BASE_URL = st.secrets.get("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
except Exception:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


# ============================================================
# ============================================================
# V2.2 模块级工具函数（可被测试直接 import）
# ============================================================

def _extract_sentiment_score(text: str) -> float:
    """
    从舆情 Agent 输出中提取情绪评分。
    ✅ V2.2 修复：只取最后一个匹配，防止重复追加
    """
    if not text:
        return 5.0
    all_matches = []
    for pat in [
        r'情绪评分[：:\s]+(\d+(?:\.\d+)?)',
        r'情感得分[：:\s]+(\d+(?:\.\d+)?)',
        r'SENTIMENT_SCORE[：:\s]+(\d+(?:\.\d+)?)',
    ]:
        all_matches.extend(re.findall(pat, text, re.IGNORECASE))
    if not all_matches:
        return 5.0
    try:
        val = float(all_matches[-1])   # ✅ 只取最后一个
        return round(min(max(val, 0.0), 10.0), 1)
    except (ValueError, TypeError):
        return 5.0


# V2.0 状态定义
# ============================================================
class FundRAGState(TypedDict, total=False):
    # 输入
    fund_code:      str
    user_question:  str
    run_id:         str          # ✅ 每次唯一，彻底隔离

    # 数据层（P1 新增，存序列化 JSON）
    snapshot_json:     str       # FundSnapshot.model_dump_json()
    data_quality_json: str       # DataQualityReport.model_dump_json()
    score_json:        str       # ScoreBreakdown.model_dump_json()

    # Agent 解释层（LLM 只填这三段）
    market_commentary:    str
    sentiment_commentary: str
    risk_commentary:      str

    # 输出
    final_report:  str
    errors:        List[str]
    warnings:      List[str]
    current_step:  str

    # Module 3: 定期报告（PeriodicReport.to_json()）
    periodic_report_json: str

    # 向后兼容旧版前端字段
    fund_name:          str
    fund_type:          str
    actual_days:        int
    is_new_fund:        bool
    market_analysis:    str
    sentiment_analysis: str
    risk_analysis:      str
    data_quality:       str
    error_messages:     List[str]


def _get_today() -> str:
    return datetime.now().strftime("%Y年%m月%d日")


def _create_llm(
    model_name: str = "deepseek-v4-flash",
    temperature: float = 0,
    streaming: bool = True,
    enable_thinking: bool = False,
) -> ChatOpenAI:
    """创建 DeepSeek LLM 实例"""
    kwargs = dict(
        model=model_name,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        streaming=streaming,
        max_tokens=8192,
    )
    if enable_thinking and model_name == "deepseek-v4-pro":
        kwargs["reasoning_effort"] = "high"
    return ChatOpenAI(**kwargs)


def create_fund_rag_graph():
    """
    构建 V2.0 Multi-Agent 分析图（9 节点）
    """
    today = _get_today()
    year  = today[:4]

    llm_fast = _create_llm("deepseek-v4-flash", temperature=0)
    memory   = MemorySaver()

    # Sub-Agents（只做解释，不做计算）
    market_agent = create_react_agent(
        model=llm_fast,
        tools=[],   # V2.0：不再查询工具，只解释 snapshot_json
        prompt=MARKET_ANALYST_PROMPT,
    )
    sentiment_agent = create_react_agent(
        model=llm_fast,
        tools=[tool_search_fund_news_balanced],
        prompt=SENTIMENT_ANALYST_PROMPT.format(today=today, year=year),
    )
    risk_agent = create_react_agent(
        model=llm_fast,
        tools=[],   # V2.0：不再调用工具，只解释 score_json
        prompt=RISK_ANALYST_PROMPT,
    )

    # ============================================================
    # 节点函数
    # ============================================================

    def node_fetch_and_build_snapshot(state: FundRAGState) -> dict:
        """
        拉取数据 → 构建 FundSnapshot → 序列化存入 state
        🌰 类比：采购员把所有食材买齐、整理好，放进共享冰箱
        """
        fund_code = state["fund_code"]
        run_id    = state.get("run_id", "")
        print(f"\n📡 [fetch_snapshot] 数据拉取：{fund_code} (run_id={run_id})")

        from datetime import date
        try:
            from backend.data_fetcher import fetch_fund_snapshot
            snapshot = fetch_fund_snapshot(code=fund_code, report_date=date.today())

            # Module 1: 拉取持仓（独立 try，失败不阻断主流程）
            try:
                from backend.holdings import fetch_holdings
                holdings = fetch_holdings(fund_code)
                snapshot.holdings_json = holdings.to_json()
                print(f"   持仓拉取：前{len(holdings.stocks)}大，集中度={holdings.concentration_level}")
            except Exception as e_h:
                print(f"⚠️ [fetch_snapshot] 持仓拉取跳过：{e_h}")

            return {
                "snapshot_json": snapshot.model_dump_json(),
                # 向后兼容：填充旧版字段
                "fund_name": snapshot.name or fund_code,
                "fund_type": snapshot.fund_type or "混合型",
                "current_step": "数据拉取完成 ✅",
            }
        except Exception as e:
            err = f"数据拉取失败：{e}"
            print(f"❌ [fetch_snapshot] {err}")
            return {
                "errors": state.get("errors", []) + [err],
                "error_messages": state.get("error_messages", []) + [err],
                "current_step": "数据拉取失败 ❌",
            }

    def node_validate_data_quality(state: FundRAGState) -> dict:
        """数据质量校验 + 写入 run_days"""
        print("\n🔍 [validate_quality] 数据质量校验...")

        if not state.get("snapshot_json"):
            err = "snapshot_json 为空，跳过质量校验"
            print(f"⚠️  {err}")
            return {
                "errors": state.get("errors", []) + [err],
                "current_step": "数据校验跳过（无快照）",
            }

        try:
            from backend.data_quality import validate_snapshot
            from backend.schemas import FundSnapshot

            snapshot = FundSnapshot.model_validate_json(state["snapshot_json"])
            quality  = validate_snapshot(snapshot)   # 会写入 snapshot.run_days

            # 向后兼容字段
            actual_days = snapshot.run_days or 0
            is_new_fund = actual_days < 365 if actual_days > 0 else False

            print(f"   质量等级：{quality.level}，矛盾数：{len(quality.contradictions)}")
            return {
                "snapshot_json":     snapshot.model_dump_json(),   # 含 run_days
                "data_quality_json": quality.model_dump_json(),
                "warnings":          state.get("warnings", []) + quality.warnings,
                "actual_days":       actual_days,
                "is_new_fund":       is_new_fund,
                "current_step":      "数据校验完成 ✅",
            }
        except Exception as e:
            err = f"数据质量校验失败：{e}"
            print(f"❌ [validate_quality] {err}")
            return {
                "errors": state.get("errors", []) + [err],
                "current_step": "数据校验失败 ❌",
            }

    def node_data_issue_report(state: FundRAGState) -> dict:
        """数据矛盾时直接生成问题报告，不走正式评级"""
        print("\n🔴 [data_issue_report] 数据矛盾，生成问题报告...")

        try:
            from backend.schemas import DataQualityReport, FundSnapshot
            quality  = DataQualityReport.model_validate_json(state["data_quality_json"])
            snapshot = FundSnapshot.model_validate_json(state["snapshot_json"])

            report = f"""# ⛔ {state['fund_code']} 数据一致性问题报告

**报告日期：** {snapshot.report_date}
**基金名称：** {snapshot.name or "未知"}

## 检测到的数据矛盾

以下矛盾导致本次分析无法输出正式评级：

{chr(10).join(f"- {c}" for c in quality.contradictions)}

## 建议

1. 请等待 akshare 数据接口更新后重新分析
2. 或前往基金公司官方网站核实数据
3. 如为缓存问题，请清空 cache/ 目录后重试

---
*本报告由 FundRAG Multi-Agent System V2.0 生成*
"""
            return {
                "final_report": report,
                # 向后兼容
                "market_analysis": "数据存在矛盾，已停止分析",
                "sentiment_analysis": "数据存在矛盾，已停止分析",
                "risk_analysis": "数据存在矛盾，已停止分析",
                "current_step": "数据问题报告已生成",
            }
        except Exception as e:
            err = f"数据问题报告生成失败：{e}"
            return {
                "final_report": f"数据质量存在矛盾，无法生成报告。错误：{err}",
                "current_step": "数据问题报告生成失败",
            }

    def node_compute_scores(state: FundRAGState) -> dict:
        """确定性评分（代码计算，不依赖 LLM）"""
        print("\n📊 [scoring_node] 确定性评分计算...")

        if not state.get("snapshot_json") or not state.get("data_quality_json"):
            # 降级：无数据时给默认分
            from backend.schemas import (
                DataQualityReport, DataQualityLevel, FundSnapshot
            )
            from datetime import date
            dummy_snapshot = FundSnapshot(code=state["fund_code"], report_date=date.today())
            dummy_quality = DataQualityReport(
                level=DataQualityLevel.PARTIAL,
                missing_fields=["nav", "max_drawdown", "return_since_inception", "inception_date"],
            )
            from backend.scoring import score_fund
            score = score_fund(dummy_snapshot, dummy_quality)
            return {"score_json": score.to_json(), "current_step": "评分计算完成（降级）"}

        try:
            from backend.schemas import FundSnapshot, DataQualityReport
            from backend.scoring import score_fund

            snapshot = FundSnapshot.model_validate_json(state["snapshot_json"])
            quality  = DataQualityReport.model_validate_json(state["data_quality_json"])
            score    = score_fund(snapshot, quality, sentiment_score=5.0)

            print(f"   评分：{score.total_score}/10，评级：{score.rating}，置信度：{score.confidence}")
            return {
                "score_json":   score.to_json(),
                "current_step": "评分计算完成 ✅",
            }
        except Exception as e:
            err = f"评分计算失败：{e}"
            print(f"❌ [scoring_node] {err}")
            return {
                "errors":       state.get("errors", []) + [err],
                "current_step": "评分计算失败 ❌",
            }

    def node_market_agent(state: FundRAGState) -> dict:
        """行情 Agent：只做解释，数字全部引用 snapshot_json"""
        print("\n📊 [market_agent] 行情分析（解释层）...")
        fund_code = state["fund_code"]
        run_id    = state.get("run_id", "")

        snapshot_json = state.get("snapshot_json", "{}")

        query = f"""
以下是基金 {fund_code} 的完整数据 JSON，请基于此写行情分析解释：

```json
{snapshot_json}
```

⚠️ 严格规则：
1. 只能引用 JSON 中已有的数字，禁止自行计算或编造数字
2. 禁止使用「近3年」，使用 return_since_inception 时注明「自成立以来」
3. 若字段 is_mock=true，引用时必须加「（模拟数据）」
4. 若 run_days < 365，首句必须加粗说明「⚠️ 次新基金，数据参考价值有限」
5. managers 字段若有多个，逐一介绍，名字来自 name 字段
6. 用户问题（如有）：{state.get('user_question', '请进行全面分析')}

输出：400字以内的行情分析解释文字，不含表格（表格由系统模板生成）
"""

        try:
            config = {"configurable": {"thread_id": f"market_{fund_code}_{run_id}"}}
            result = market_agent.invoke({"messages": [("human", query)]}, config=config)
            content = result["messages"][-1].content
            print(f"✅ [market_agent] 完成，字数：{len(content)}")
            return {
                "market_commentary": content,
                "market_analysis":   content,   # 向后兼容
                "current_step":      "行情分析完成 ✅",
            }
        except Exception as e:
            err = f"行情分析失败：{e}"
            print(f"❌ [market_agent] {err}")
            return {
                "market_commentary": f"行情分析失败：{err}",
                "market_analysis":   f"行情分析失败：{err}",
                "errors":            state.get("errors", []) + [err],
                "error_messages":    state.get("error_messages", []) + [err],
                "current_step":      "行情分析失败 ❌",
            }

    def node_sentiment_agent(state: FundRAGState) -> dict:
        """舆情 Agent：多空平衡分析 + 输出 SENTIMENT_SCORE"""
        print("\n📰 [sentiment_agent] 舆情分析...")
        fund_code = state["fund_code"]
        run_id    = state.get("run_id", "")

        # 从 snapshot 获取基金名称和类型
        fund_name = state.get("fund_name", fund_code)
        fund_type = state.get("fund_type", "混合型")
        if state.get("snapshot_json"):
            try:
                from backend.schemas import FundSnapshot
                snap = FundSnapshot.model_validate_json(state["snapshot_json"])
                fund_name = snap.name or fund_name
                fund_type = snap.fund_type or fund_type
            except Exception:
                pass

        query = f"""
请对基金「{fund_name}」（{fund_code}）进行多空平衡的舆情分析。

⚠️ 只能分析 {fund_code}，禁止引用其他基金的数据。

请调用 tool_search_fund_news_balanced：
- fund_name: "{fund_name}"
- fund_industry: "{fund_type}"

根据搜索结果，输出：
1. 情绪评分（0-10 的数字，10 最乐观）
2. 情绪分析文字（多空平衡，必须包含「反面观点」小节）

格式：
SENTIMENT_SCORE: [0-10 的数字]
---
[分析文字]
"""

        try:
            config = {"configurable": {"thread_id": f"sentiment_{fund_code}_{run_id}"}}
            result = sentiment_agent.invoke({"messages": [("human", query)]}, config=config)
            content = result["messages"][-1].content

            # ✅ V2.2：使用模块级函数提取，只取最后一个匹配，防止重复
            sentiment_score = _extract_sentiment_score(content)

            # 去掉评分行和分隔符，只保留解释文字
            commentary = re.sub(r"(情绪评分|SENTIMENT_SCORE)[：:].*\n?---?\n?", "", content).strip()

            print(f"✅ [sentiment_agent] 完成，情绪评分={sentiment_score}")

            # 用实际情绪分重新计算总分（如果有 snapshot 和 quality）
            new_score_json = state.get("score_json", "")
            if state.get("snapshot_json") and state.get("data_quality_json"):
                try:
                    from backend.schemas import FundSnapshot, DataQualityReport
                    from backend.scoring import score_fund
                    snapshot = FundSnapshot.model_validate_json(state["snapshot_json"])
                    quality  = DataQualityReport.model_validate_json(state["data_quality_json"])
                    new_score = score_fund(snapshot, quality, sentiment_score=sentiment_score)
                    new_score_json = new_score.to_json()
                    print(f"   更新总分：{new_score.total_score}/10，评级：{new_score.rating}")
                except Exception as e:
                    print(f"⚠️ 情绪分更新总分失败（保留原分）：{e}")

            return {
                "sentiment_commentary": commentary,
                "sentiment_analysis":   commentary,   # 向后兼容
                "score_json":           new_score_json,
                "current_step":         "舆情分析完成 ✅",
            }
        except Exception as e:
            err = f"舆情分析失败：{e}"
            print(f"❌ [sentiment_agent] {err}")
            return {
                "sentiment_commentary": f"舆情分析失败：{err}",
                "sentiment_analysis":   f"舆情分析失败：{err}",
                "errors":               state.get("errors", []) + [err],
                "error_messages":       state.get("error_messages", []) + [err],
                "current_step":         "舆情分析失败 ❌",
            }

    def node_risk_agent(state: FundRAGState) -> dict:
        """风控 Agent：解释后端计算出的风险分，不重新计算"""
        print("\n⚠️  [risk_agent] 风险解释...")
        fund_code = state["fund_code"]
        run_id    = state.get("run_id", "")

        query = f"""
以下是基金 {fund_code} 的评分 JSON，请解释风险来源：

评分结果：
```json
{state.get("score_json", "{}")}
```

快照数据（仅用于引用）：
```json
{state.get("snapshot_json", "{}")}
```

⚠️ 严格规则：
1. 禁止修改评分数字
2. 禁止忽略 data_penalty（数据不足惩罚）
3. 若 run_days < 365，「数据充分性风险」必须列为首要风险
4. 禁止出现「建议买入/卖出/持有」
5. 只解释，不重新计算

输出：300字以内的风险解释文字，不含表格
"""

        try:
            config = {"configurable": {"thread_id": f"risk_{fund_code}_{run_id}"}}
            result = risk_agent.invoke({"messages": [("human", query)]}, config=config)
            content = result["messages"][-1].content
            print(f"✅ [risk_agent] 完成，字数：{len(content)}")
            return {
                "risk_commentary": content,
                "risk_analysis":   content,   # 向后兼容
                "current_step":    "风险分析完成 ✅",
            }
        except Exception as e:
            err = f"风险分析失败：{e}"
            print(f"❌ [risk_agent] {err}")
            return {
                "risk_commentary":  f"风险分析失败：{err}",
                "risk_analysis":    f"风险分析失败：{err}",
                "errors":           state.get("errors", []) + [err],
                "error_messages":   state.get("error_messages", []) + [err],
                "current_step":     "风险评估失败 ❌",
            }

    def node_cross_check(state: FundRAGState) -> dict:
        """
        跨 Agent 一致性校验节点（V2.1 新增）
        检测舆情分析里是否出现了与 snapshot 矛盾的数字
        🌰 类比：校对员，确保不同来源的说法不打架
        """
        print("\n🔍 [cross_check] 跨Agent一致性校验...")

        sentiment = state.get("sentiment_commentary", "")
        snapshot_json = state.get("snapshot_json", "{}")
        errors = list(state.get("errors", []))
        warnings = list(state.get("warnings", []))

        try:
            import json as _json
            snap = _json.loads(snapshot_json)
            run_days = snap.get("run_days", 0) or 0

            # ---- 规则1：次新基金不应出现"近1年涨幅"作为结论 ----
            if run_days < 365:
                year_patterns = [
                    re.compile(r'近一年涨幅[^，。\n]{0,30}%'),
                    re.compile(r'近1年[收益涨幅]{0,4}[^，。\n]{0,20}%'),
                    re.compile(r'过去一年[^，。\n]{0,30}%'),
                ]
                for pattern in year_patterns:
                    m = pattern.search(sentiment)
                    if m:
                        matched_text = m.group(0)
                        if "口径存疑" not in sentiment[max(0, m.start()-20):m.end()+50]:
                            replacement = (
                                f"[⚠️ 口径存疑：以下数据的时间窗口可能超过基金实际运行期（{run_days}天）]"
                                f" {matched_text}"
                            )
                            sentiment = sentiment.replace(matched_text, replacement)
                            warnings.append(
                                f"舆情修正：次新基金（{run_days}天）出现「近1年」口径数据，已标注存疑"
                            )

            # ---- 规则2：排名数字一致性检查 ----
            peer_rank = snap.get("peer_rank", {}) or {}
            rank_pos   = peer_rank.get("rank", None)
            rank_total = peer_rank.get("total", None)

            if rank_pos and rank_total and rank_pos > rank_total * 0.8:
                top_rank_patterns = [
                    re.compile(r'排名第[123456789][0-9]?位'),
                    re.compile(r'同类第[123456789][0-9]?'),
                ]
                for pattern in top_rank_patterns:
                    if pattern.search(sentiment):
                        warnings.append(
                            "舆情警告：系统排名数据显示倒数，但舆情出现靠前排名描述，"
                            "可能为新闻口径不同，已记录供参考"
                        )

            # ---- 规则3：禁用词扫描 ----
            from backend.value_cleaner import scan_banned_words, auto_fix_text
            banned = scan_banned_words(sentiment)
            if banned:
                fixed, fixes = auto_fix_text(sentiment)
                sentiment = fixed
                if fixes:
                    warnings.append(f"舆情自动修复：{'; '.join(fixes[:3])}")

        except Exception as e:
            warnings.append(f"跨Agent校验异常（不影响报告）：{e}")

        return {
            **state,
            "sentiment_commentary": sentiment,
            "sentiment_analysis":   sentiment,
            "errors":       errors,
            "warnings":     warnings,
            "current_step": "跨Agent校验完成 ✅",
        }

    def node_render_report(state: FundRAGState) -> dict:
        """用模板渲染最终报告，不依赖 LLM 生成结构"""
        print("\n📝 [render_report] 渲染最终报告...")

        try:
            from backend.schemas import FundSnapshot, DataQualityReport
            from backend.scoring import ScoreResult
            from backend.report_renderer import render_report
            from backend.output_guard import validate_report, auto_fix_report
            from datetime import date

            # 获取或构建所需对象
            snapshot = (FundSnapshot.model_validate_json(state["snapshot_json"])
                        if state.get("snapshot_json")
                        else FundSnapshot(code=state["fund_code"], report_date=date.today()))

            quality = (DataQualityReport.model_validate_json(state["data_quality_json"])
                       if state.get("data_quality_json")
                       else None)

            score = (ScoreResult.from_json(state["score_json"])
                     if state.get("score_json")
                     else None)

            if quality is None or score is None:
                # 降级到文本汇总模式
                raise ValueError("缺少 quality 或 score，降级处理")

            raw_report = render_report(
                snapshot=snapshot,
                quality=quality,
                score=score,
                market_commentary=state.get("market_commentary", "数据获取失败"),
                sentiment_commentary=state.get("sentiment_commentary", "数据获取失败"),
                risk_commentary=state.get("risk_commentary", "数据获取失败"),
                periodic_report_json=state.get("periodic_report_json", ""),  # Module 3
            )

            # 自动修复幻觉词
            fixed_report, fix_log = auto_fix_report(raw_report)
            if fix_log:
                print(f"  自动修复：{fix_log}")

            # 质量校验
            is_valid, guard_errors = validate_report(fixed_report)
            if not is_valid:
                print(f"  ⚠️ 质量守卫警告：{guard_errors}")
                fixed_report += f"\n\n---\n> ⚠️ 系统质量校验警告：{'; '.join(guard_errors)}"

            print(f"✅ [render_report] 完成，字数：{len(fixed_report)}")
            print(f"\n🎉 全部节点执行完毕！")

            return {
                "final_report":   fixed_report,
                "warnings":       state.get("warnings", []) + (fix_log if fix_log else []),
                "data_quality":   state.get("data_quality_json", ""),
                "current_step":   "报告生成完成 🎉",
            }
        except Exception as e:
            err = f"报告渲染失败：{e}"
            print(f"❌ [render_report] {err}")

            # 降级报告
            fallback_report = (
                f"# 📋 基金分析报告（降级版）\n\n"
                f"> 模板渲染失败，以下为各子模块原始输出\n\n"
                f"## 行情分析\n{state.get('market_commentary', state.get('market_analysis', '无数据'))}\n\n"
                f"## 舆情分析\n{state.get('sentiment_commentary', state.get('sentiment_analysis', '无数据'))}\n\n"
                f"## 风险评估\n{state.get('risk_commentary', state.get('risk_analysis', '无数据'))}\n\n"
                f"## ⚠️ 风险提示\n本报告由AI系统自动生成，不构成任何投资建议。\n"
            )
            return {
                "final_report":  fallback_report,
                "errors":        state.get("errors", []) + [err],
                "error_messages": state.get("error_messages", []) + [err],
                "current_step":  "报告生成失败（已降级）❌",
            }

    # ============================================================
    # Module 3: 定期报告节点
    # ============================================================
    def node_fetch_periodic_report(state: FundRAGState) -> dict:
        """拉取基金最新定期报告（季报/半年报），失败不阻断主流程"""
        fund_code = state["fund_code"]
        print(f"\n📄 [periodic_report] 拉取定期报告：{fund_code}")
        try:
            from backend.report_fetcher import fetch_periodic_report
            report = fetch_periodic_report(fund_code)
            return {
                "periodic_report_json": report.to_json(),
                "current_step": "定期报告拉取完成 ✅",
            }
        except Exception as e:
            print(f"⚠️ [periodic_report] 跳过：{e}")
            return {
                "periodic_report_json": "",
                "current_step": "定期报告拉取跳过",
            }

    # ============================================================
    # output_guard 节点（V2.2 新增：挂在 render_report 之后）
    # ============================================================
    def node_output_guard(state: FundRAGState) -> dict:
        """
        ✅ V2.2 修复：output_guard 挂在 final_report 写入节点之后
        对 final_report 执行完整检测，自动修复后仍有问题则追加警告头
        """
        from backend.output_guard import validate_report, auto_fix_report

        final_report = state.get("final_report", "")
        if not final_report:
            return {}

        # 先尝试自动修复
        fixed_report, fix_log = auto_fix_report(final_report)
        if fix_log:
            print(f"  🔧 [output_guard] 自动修复 {len(fix_log)} 处：{fix_log[:3]}")

        ok, errors = validate_report(fixed_report)
        if not ok:
            print(f"  ⚠️ [output_guard] 仍有 {len(errors)} 项质量问题（已降级处理）")
            warning_header = (
                "\n> ⚠️ **系统质量检测**：本报告经质量守卫检测发现若干文本问题，"
                "已尽量自动修复，请以数据为准。\n\n"
            )
            return {
                "final_report": warning_header + fixed_report,
                "errors": state.get("errors", []) + errors,
            }

        return {"final_report": fixed_report}

    # ============================================================
    # 路由函数：数据矛盾 → 问题报告；否则 → 正常流程
    # ============================================================
    def route_after_quality(state: FundRAGState) -> str:
        if not state.get("data_quality_json"):
            return "scoring_node"   # 无质量报告时继续（降级）
        try:
            from backend.schemas import DataQualityReport
            quality = DataQualityReport.model_validate_json(state["data_quality_json"])
            if quality.contradictions:
                return "data_issue_report"
        except Exception:
            pass
        return "scoring_node"

    # ============================================================
    # 构建图
    # ============================================================
    workflow = StateGraph(FundRAGState)

    workflow.add_node("fetch_snapshot",    node_fetch_and_build_snapshot)
    workflow.add_node("validate_quality",  node_validate_data_quality)
    workflow.add_node("data_issue_report", node_data_issue_report)
    workflow.add_node("scoring_node",      node_compute_scores)
    workflow.add_node("market_agent",      node_market_agent)
    workflow.add_node("sentiment_agent",   node_sentiment_agent)
    workflow.add_node("risk_agent",        node_risk_agent)
    workflow.add_node("cross_check",        node_cross_check)        # V2.1 新增
    workflow.add_node("render_report",     node_render_report)
    workflow.add_node("output_guard",      node_output_guard)       # V2.2 新增
    workflow.add_node("periodic_report",   node_fetch_periodic_report)  # Module 3 新增

    workflow.set_entry_point("fetch_snapshot")
    workflow.add_edge("fetch_snapshot", "validate_quality")

    # ✅ 关键分支：数据矛盾时走问题报告
    workflow.add_conditional_edges(
        "validate_quality",
        route_after_quality,
        {
            "data_issue_report": "data_issue_report",
            "scoring_node":      "scoring_node",
        }
    )

    workflow.add_edge("data_issue_report", END)
    workflow.add_edge("scoring_node",      "periodic_report")   # Module 3: 先拉季报
    workflow.add_edge("periodic_report",   "market_agent")
    workflow.add_edge("market_agent",      "sentiment_agent")
    workflow.add_edge("sentiment_agent",   "risk_agent")
    workflow.add_edge("risk_agent",        "cross_check")         # V2.1：risk → cross_check → render
    workflow.add_edge("cross_check",       "render_report")
    workflow.add_edge("render_report",     "output_guard")         # ✅ V2.2：render → guard → END
    workflow.add_edge("output_guard",      END)

    print("✅ FundRAG V2.1 Multi-Agent 图构建完成")
    print("   节点数量：9 个")
    print("   执行顺序：fetch_snapshot → validate_quality → scoring_node → market_agent → sentiment_agent → risk_agent → cross_check → render_report")

    return workflow.compile(checkpointer=memory)


def run_fund_analysis(fund_code: str, user_question: str = "", session_id: str = "default", user_query: str = "") -> dict:
    """
    执行完整的基金分析流程（对外统一入口）

    ✅ P0 修复：每次调用生成唯一 run_id，彻底隔离不同分析
    向后兼容：接受 user_query 参数（旧版 app.py 使用）

    🌰 类比：每次开一张全新白板，扔掉旧白板
    """
    # 兼容旧版 user_query 参数
    if not user_question and user_query:
        user_question = user_query

    # ✅ P0 核心修复：唯一 run_id
    run_id = f"{fund_code}_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    initial_state: FundRAGState = {
        "fund_code":           fund_code.strip(),
        "user_question":       user_question or "请进行全面分析",
        "run_id":              run_id,
        # ✅ 显式初始化所有字段，防止读取任何历史残留
        "snapshot_json":       "",
        "data_quality_json":   "",
        "score_json":          "",
        "market_commentary":   "",
        "sentiment_commentary": "",
        "risk_commentary":     "",
        "final_report":        "",
        "errors":              [],
        "warnings":            [],
        "current_step":        "初始化...",
        # 向后兼容字段
        "fund_name":           fund_code.strip(),
        "fund_type":           "混合型",
        "actual_days":         0,
        "is_new_fund":         False,
        "market_analysis":     "",
        "sentiment_analysis":  "",
        "risk_analysis":       "",
        "data_quality":        "",
        "error_messages":      [],
    }

    print(f"\n{'#'*50}")
    print(f"🚀 V2.1 开始分析基金：{fund_code}")
    print(f"   用户问题：{user_question}")
    print(f"   run_id：{run_id}")
    print(f"{'#'*50}")

    graph = create_fund_rag_graph()
    # ✅ config 使用唯一 run_id
    config = {"configurable": {"thread_id": run_id}}
    final_state = graph.invoke(initial_state, config=config)

    error_count = len(final_state.get("errors", final_state.get("error_messages", [])))
    print(f"\n{'#'*50}")
    print(f"🏁 V2.1 分析完成！错误数量：{error_count}")
    print(f"{'#'*50}\n")

    return final_state
