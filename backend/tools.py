# backend/tools.py
"""
工具模块：定义所有 Agent 可以调用的工具
🌰 类比：给每个「专家员工」配备专属工具箱
         行情分析师 → 有净值查询工具
         新闻分析师 → 有新闻搜索工具
         风险评估师 → 有风险计算工具

补充决策：
- Tavily API Key 同时兼容 .env 和 Streamlit Cloud Secrets
- tool_compare_fund_ranking 将排名逻辑内联，不重复调用 akshare
- 工具描述（docstring 第一行）用中文写，Agent 据此判断何时调用
"""

import os
import json
from typing import Optional
from dotenv import load_dotenv
from langchain.tools import tool

# 兼容本地 .env 和 Streamlit Cloud Secrets
# 🌰 类比：先看钱包里有没有现金（.env），没有再刷卡（secrets）
load_dotenv()

try:
    import streamlit as st
    TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY", os.getenv("TAVILY_API_KEY", ""))
except Exception:
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

from backend.data_fetcher import (
    get_fund_basic_info,
    get_fund_performance,
    get_fund_manager_info,
    get_fund_ranking,
)

# ============ 初始化 Tavily 客户端 ============
# 🌰 类比：提前开好「新闻检索终端」，需要时直接查
_tavily_client = None

def _get_tavily_client():
    """懒加载 Tavily 客户端，避免导入时 Key 还未设置"""
    global _tavily_client
    if _tavily_client is None:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily_client


# ============ 工具1：基金基本信息查询 ============
@tool
def tool_get_fund_info(fund_code: str) -> str:
    """
    查询基金基本信息，包括基金名称、类型、规模、基金经理、成立日期、基金公司。
    输入 6 位基金代码（如：110022、000001），返回 JSON 格式的基本信息。
    当需要了解一只基金「是什么」时使用此工具。

    🌰 类比：去「工商局」查公司的营业执照信息
    """
    try:
        info = get_fund_basic_info(fund_code.strip())
        return json.dumps(info, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取基金信息失败：{str(e)}"


# ============ 工具2：基金历史业绩查询 ============
@tool
def tool_get_fund_performance(fund_code: str) -> str:
    """
    查询基金历史业绩表现，包括近 3 年收益率、最大回撤、最新净值、净值走势。
    输入 6 位基金代码，返回关键量化指标。
    当需要评估基金「历史表现好不好」时使用此工具。

    🌰 类比：查学生的「历年成绩单」，看是否稳定优秀
    """
    try:
        perf = get_fund_performance(fund_code.strip(), years=3)
        return json.dumps(perf, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取业绩数据失败：{str(e)}"


# ============ 工具3：基金经理信息查询 ============
@tool
def tool_get_manager_info(manager_name: str) -> str:
    """
    查询基金经理的从业经历和历史管理业绩，包括从业年限、管理基金数量、总管理规模、历史最佳业绩。
    输入基金经理姓名（如：萧楠、张坤），返回经理画像。
    当需要评估「基金经理靠不靠谱」时使用此工具。

    🌰 类比：查「厨师的履历」，看他在哪干过、做得好不好
    """
    try:
        info = get_fund_manager_info(manager_name.strip())
        return json.dumps(info, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取基金经理信息失败：{str(e)}"


# ============ 工具4：实时新闻舆情搜索 ============
@tool
def tool_search_fund_news(query: str) -> str:
    """
    搜索基金、市场相关的最新新闻和舆情，返回最新财经资讯摘要和来源链接。
    输入搜索关键词（如「易方达消费基金 最新」「A股消费行业 政策 2026」），优先返回财经网站结果。
    当需要了解市场动态、政策变化、基金公司近况时使用此工具。

    🌰 类比：请「新闻助理」帮你刷最新的财经资讯
    """
    try:
        client = _get_tavily_client()
        results = client.search(
            query=f"{query} 基金 投资",
            search_depth="basic",
            max_results=5,
            include_domains=[
                "eastmoney.com", "xueqiu.com", "fund.people.com.cn",
                "sina.com.cn", "163.com", "10jqka.com.cn", "caixin.com"
            ]
        )

        formatted_results = []
        for r in results.get("results", []):
            formatted_results.append({
                "title": r.get("title", ""),
                "content": r.get("content", "")[:300],  # 只取前 300 字，节省 token
                "url": r.get("url", ""),
                "published_date": r.get("published_date", "未知")
            })

        if not formatted_results:
            return "未找到相关新闻，请尝试其他关键词"

        return json.dumps(formatted_results, ensure_ascii=False, indent=2)

    except Exception as e:
        # 🌰 Tavily 失败时返回友好提示，不让流程崩溃
        return json.dumps([{
            "title": "新闻搜索暂时不可用",
            "content": f"搜索失败原因：{str(e)}。建议检查 TAVILY_API_KEY 是否配置正确。",
            "url": "",
            "published_date": "未知"
        }], ensure_ascii=False)


# ============ 工具5：风险评分计算 ============
@tool
def tool_calculate_risk_score(
    max_drawdown: float,
    return_rate: float,
    fund_type: str
) -> str:
    """
    根据基金的最大回撤、收益率和类型，计算综合风险评分（1-10分，10分最高风险）。
    参数：max_drawdown（最大回撤%，如 25.3），return_rate（近3年总收益率%，如 45.2），fund_type（基金类型，如「股票型」）。
    当需要给基金「打风险分」时使用此工具。

    🌰 类比：给基金做「体检报告」
         最大回撤高 → 容易心脏病发作（高风险）
         收益率低 → 身体素质差（性价比低）
    """
    try:
        # 1. 回撤评分（最大回撤越大，风险越高）
        # 🌰 回撤5%以下=轻微感冒，30%以上=重病住院
        if max_drawdown < 5:
            drawdown_score = 1
        elif max_drawdown < 10:
            drawdown_score = 2
        elif max_drawdown < 20:
            drawdown_score = 4
        elif max_drawdown < 30:
            drawdown_score = 6
        elif max_drawdown < 40:
            drawdown_score = 8
        else:
            drawdown_score = 10

        # 2. 基金类型风险基准分
        type_risk_map = {
            "货币型": 1, "债券型": 2, "混合型": 5,
            "股票型": 7, "指数型": 6, "QDII": 8
        }
        type_score = type_risk_map.get(fund_type, 5)

        # 3. 性价比分析（高风险低回报更危险）
        # 🌰 冒了大风险却只赚了一点点 → 性价比极差
        risk_return_ratio = return_rate / (max_drawdown + 1)
        if risk_return_ratio < 0.5:
            performance_warning = "⚠️  风险收益比偏低，建议谨慎"
        elif risk_return_ratio < 1.5:
            performance_warning = "📊 风险收益比一般"
        else:
            performance_warning = "✅ 风险收益比较好"

        # 综合评分（加权平均：回撤 60% + 类型 40%）
        risk_score = round(drawdown_score * 0.6 + type_score * 0.4, 1)

        # 风险等级描述
        if risk_score <= 3:
            level = "低风险"
            advice = "适合保守型投资者，资金安全性较高"
        elif risk_score <= 6:
            level = "中等风险"
            advice = "适合稳健型投资者，需要一定的风险承受能力"
        elif risk_score <= 8:
            level = "高风险"
            advice = "适合积极型投资者，可能面临较大亏损"
        else:
            level = "极高风险"
            advice = "仅适合激进型投资者，亏损概率极高"

        result = {
            "risk_score": risk_score,
            "risk_level": level,
            "drawdown_impact": f"最大回撤{max_drawdown}%，回撤风险评分{drawdown_score}/10",
            "type_impact": f"基金类型[{fund_type}]类型风险评分{type_score}/10",
            "performance_analysis": performance_warning,
            "investment_advice": advice
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"风险评估计算失败：{str(e)}"


# ============ 工具6：同类基金排名比较 ============
@tool
def tool_compare_fund_ranking(fund_code: str, fund_type: str) -> str:
    """
    查询基金在同类基金中的排名百分位。
    输入基金代码和类型（如「股票型」「混合型」），返回该基金在同类中排名前多少百分比。
    当需要「横向比较」这只基金好不好时使用此工具。

    🌰 类比：不光看自己考了多少分，还要看在全班排第几名
         排名前10%比分数高更有说服力
    """
    try:
        result = get_fund_ranking(fund_code.strip(), fund_type.strip())
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"排名查询失败：{str(e)}"


# ============ 导出所有工具（供 Agent 使用）============
ALL_TOOLS = [
    tool_get_fund_info,
    tool_get_fund_performance,
    tool_get_manager_info,
    tool_search_fund_news,
    tool_calculate_risk_score,
    tool_compare_fund_ranking,
]
