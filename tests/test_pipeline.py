# tests/test_pipeline.py
"""
端到端测试脚本
不需要启动前端，直接在命令行验证整个流程

🌰 就像「试运营」，确保系统上线前没有问题
     测试1：数据层（不调用任何 API）
     测试2：工具层（不调用 LLM API）
     测试3：完整 Multi-Agent 流程（会调用 OpenAI，询问确认）

运行方式：
    python tests/test_pipeline.py
    # 输入 n 跳过完整流程测试（节省 API 费用）
"""

import os
import sys
import json

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


# ============ 测试1：数据获取模块 ============

def test_data_fetcher():
    """
    测试数据获取模块
    🌰 类比：验证「采购员」能否正常拿到食材（不管真的还是mock的）
    """
    print("\n🧪 测试1：数据获取模块")
    print("-" * 50)

    from backend.data_fetcher import (
        get_fund_basic_info,
        get_fund_performance,
        get_fund_manager_info,
        get_fund_ranking,
    )

    # 测试基金基本信息（会优先使用真实数据，失败则 mock）
    print("  1.1 测试基金基本信息获取...")
    info = get_fund_basic_info("110022")
    assert "fund_code" in info, "❌ 基金信息格式错误：缺少 fund_code"
    assert "name" in info, "❌ 基金信息格式错误：缺少 name"
    assert "type" in info, "❌ 基金信息格式错误：缺少 type"
    assert "manager" in info, "❌ 基金信息格式错误：缺少 manager"
    print(f"  ✅ 基金基本信息：{info['name']}（{info['data_source']}）")

    # 测试业绩数据获取
    print("  1.2 测试基金业绩数据获取...")
    perf = get_fund_performance("110022", years=3)
    assert "total_return_pct" in perf, "❌ 业绩数据缺少 total_return_pct"
    assert "max_drawdown_pct" in perf, "❌ 业绩数据缺少 max_drawdown_pct"
    assert "latest_nav" in perf, "❌ 业绩数据缺少 latest_nav"
    assert isinstance(perf["nav_history"], list), "❌ nav_history 应为列表"
    print(f"  ✅ 业绩数据：收益率 {perf['total_return_pct']}%，最大回撤 {perf['max_drawdown_pct']}%（{perf['data_source']}）")

    # 测试基金经理信息
    print("  1.3 测试基金经理信息获取...")
    mgr = get_fund_manager_info("萧楠")
    assert "name" in mgr, "❌ 经理信息缺少 name"
    assert "experience_years" in mgr, "❌ 经理信息缺少 experience_years"
    print(f"  ✅ 基金经理：{mgr['name']}，从业 {mgr['experience_years']}（{mgr['data_source']}）")

    # 测试排名数据
    print("  1.4 测试同类排名获取...")
    rank = get_fund_ranking("110022", "股票型")
    assert "rank_percentile" in rank, "❌ 排名数据缺少 rank_percentile"
    print(f"  ✅ 同类排名：{rank['rank_percentile']}（{rank['data_source']}）")

    # 测试缓存机制（第二次调用应更快）
    print("  1.5 测试缓存机制...")
    import time
    t1 = time.time()
    get_fund_basic_info("110022")
    t2 = time.time()
    print(f"  ✅ 第二次调用耗时：{(t2-t1)*1000:.1f}ms（有缓存应 < 10ms）")

    print("\n✅ 测试1 全部通过！")


# ============ 测试2：工具层 ============

def test_tools():
    """
    测试 LangChain 工具函数
    🌰 类比：验证「工具箱里的每件工具」能否正常使用
    """
    print("\n🧪 测试2：工具模块")
    print("-" * 50)

    from backend.tools import (
        tool_get_fund_info,
        tool_get_fund_performance,
        tool_get_manager_info,
        tool_calculate_risk_score,
        tool_compare_fund_ranking,
        ALL_TOOLS,
    )

    # 测试工具数量（V2.0 新增 tool_search_fund_news_balanced，共 7 个）
    print(f"  2.0 工具总数：{len(ALL_TOOLS)} 个（预期 7 个）")
    assert len(ALL_TOOLS) == 7, f"❌ 工具数量错误：{len(ALL_TOOLS)}"
    print(f"  ✅ 工具数量正确：{[t.name for t in ALL_TOOLS]}")

    # 测试基金信息工具
    print("  2.1 测试 tool_get_fund_info...")
    result = tool_get_fund_info.invoke({"fund_code": "110022"})
    assert len(result) > 10, "❌ 返回内容太短"
    data = json.loads(result)
    assert "name" in data, "❌ 工具返回缺少 name 字段"
    print(f"  ✅ tool_get_fund_info：{data['name']}")

    # 测试业绩工具
    print("  2.2 测试 tool_get_fund_performance...")
    result = tool_get_fund_performance.invoke({"fund_code": "110022"})
    data = json.loads(result)
    assert "total_return_pct" in data, "❌ 工具返回缺少 total_return_pct"
    print(f"  ✅ tool_get_fund_performance：收益率 {data['total_return_pct']}%")

    # 测试风险评分工具（纯计算，无外部依赖）
    print("  2.3 测试 tool_calculate_risk_score...")
    result = tool_calculate_risk_score.invoke({
        "max_drawdown": 25.0,
        "return_rate": 45.0,
        "fund_type": "股票型"
    })
    data = json.loads(result)
    assert "risk_score" in data, "❌ 风险评分工具缺少 risk_score"
    assert "risk_level" in data, "❌ 风险评分工具缺少 risk_level"
    assert 1 <= data["risk_score"] <= 10, f"❌ 风险评分超出范围：{data['risk_score']}"
    print(f"  ✅ tool_calculate_risk_score：{data['risk_score']}/10 ({data['risk_level']})")

    # 测试排名工具
    print("  2.4 测试 tool_compare_fund_ranking...")
    result = tool_compare_fund_ranking.invoke({"fund_code": "110022", "fund_type": "股票型"})
    data = json.loads(result)
    assert "rank_percentile" in data, "❌ 排名工具缺少 rank_percentile"
    print(f"  ✅ tool_compare_fund_ranking：{data['rank_percentile']}")

    # 测试风险评分边界情况
    print("  2.5 测试风险评分边界情况...")
    # 极低风险
    r1 = json.loads(tool_calculate_risk_score.invoke({"max_drawdown": 1.0, "return_rate": 5.0, "fund_type": "货币型"}))
    assert r1["risk_score"] <= 3, f"❌ 货币型基金风险应 <= 3，实际 {r1['risk_score']}"
    # 极高风险
    r2 = json.loads(tool_calculate_risk_score.invoke({"max_drawdown": 50.0, "return_rate": 10.0, "fund_type": "QDII"}))
    assert r2["risk_score"] >= 8, f"❌ 高回撤 QDII 风险应 >= 8，实际 {r2['risk_score']}"
    print(f"  ✅ 边界情况：货币型={r1['risk_score']}分，高回撤QDII={r2['risk_score']}分")

    print("\n✅ 测试2 全部通过！")


# ============ 测试3：完整 Multi-Agent 流程 ============

def test_full_pipeline():
    """
    测试完整的 Multi-Agent 分析流程
    ⚠️  此测试会调用 OpenAI API，预计花费约 $0.03-0.08
    🌰 类比：真正「试营业」，所有系统联动测试
    """
    print("\n🧪 测试3：完整 Multi-Agent 流程")
    print("-" * 50)
    print("⚠️  此测试会调用 OpenAI API，预计花费约 $0.03-0.08")
    print("   包含：4 个 Agent 调用 + 多次工具调用")

    confirm = input("  确认继续？(y/n): ").strip().lower()
    if confirm != 'y':
        print("  ⏭️  跳过完整流程测试（节省 API 费用）")
        return

    # 检查 API Key
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxx"):
        print("  ❌ DEEPSEEK_API_KEY 未配置，请先在 .env 文件中设置真实的 API Key")
        return

    from backend.graph import run_fund_analysis

    print("\n  🚀 开始完整分析（基金代码：110022）...")
    print("  预计耗时：30-90 秒\n")

    result = run_fund_analysis(
        fund_code="110022",
        user_query="这只基金适合长期持有吗？风险如何？近期是否有利好或利空？",
        session_id="test_full_001"
    )

    # 验证输出
    assert result.get("final_report"), "❌ 最终报告为空！"
    assert len(result["final_report"]) > 100, "❌ 最终报告内容过短"
    assert result.get("market_analysis"), "❌ 行情分析为空！"
    assert result.get("risk_analysis"), "❌ 风险分析为空！"

    print("\n✅ 完整流程测试通过！")
    print(f"\n📋 报告预览（前 600 字）：")
    print("-" * 50)
    print(result["final_report"][:600])
    print("...\n")

    # 错误统计
    errors = result.get("error_messages", [])
    if errors:
        print(f"⚠️  流程中有 {len(errors)} 个可接受的错误（不影响整体分析）：")
        for e in errors:
            print(f"   - {e}")
    else:
        print("✅ 无错误，所有 Agent 正常完成")

    # 测试缓存：第二次调用同一基金应更快（数据层命中缓存）
    print("\n  测试缓存加速效果...")
    import time
    t1 = time.time()
    from backend.data_fetcher import get_fund_basic_info
    get_fund_basic_info("110022")
    t2 = time.time()
    print(f"  缓存命中耗时：{(t2-t1)*1000:.1f}ms")

    print("\n✅ 测试3 全部通过！")


# ============ 主入口 ============

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 FundRAG Multi-Agent 系统测试")
    print("=" * 60)

    all_passed = True

    try:
        test_data_fetcher()
    except AssertionError as e:
        print(f"\n❌ 测试1 失败：{e}")
        all_passed = False
    except Exception as e:
        print(f"\n❌ 测试1 异常：{e}")
        all_passed = False

    try:
        test_tools()
    except AssertionError as e:
        print(f"\n❌ 测试2 失败：{e}")
        all_passed = False
    except Exception as e:
        print(f"\n❌ 测试2 异常：{e}")
        all_passed = False

    try:
        test_full_pipeline()
    except AssertionError as e:
        print(f"\n❌ 测试3 失败：{e}")
        all_passed = False
    except Exception as e:
        print(f"\n❌ 测试3 异常：{e}")
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试完成！系统准备就绪，可以启动前端。")
        print("   运行命令：streamlit run frontend/app.py")
    else:
        print("⚠️  部分测试失败，请检查上方错误信息。")
    print("=" * 60)
