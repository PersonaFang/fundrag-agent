# tests/test_scoring.py
from datetime import date, timedelta
from backend.schemas import FundSnapshot, MetricSource, DataQualityReport, DataQualityLevel
from backend.scoring import score_fund, score_history, score_risk


def make_snapshot(run_days, mdd=20.0, ret=50.0, has_mock=False):
    report_date    = date.today()
    inception_date = report_date - timedelta(days=run_days)

    s = FundSnapshot(
        code="TEST",
        report_date=report_date,
        inception_date=inception_date,
        nav=MetricSource(value=1.5, source="test", is_mock=has_mock),
        max_drawdown=MetricSource(value=mdd, source="test", is_mock=False),
        return_since_inception=MetricSource(value=ret, source="test", is_mock=False),
    )
    s.run_days = run_days
    return s


def make_quality(level, mock_count=0, contradictions=None, missing=None):
    return DataQualityReport(
        level=DataQualityLevel(level),
        mock_metric_count=mock_count,
        contradictions=contradictions or [],
        missing_fields=missing or [],
        can_generate_rating=(level == "real" and not (contradictions or missing)),
        can_generate_report=True,
    )


def test_new_fund_rating_cap():
    """次新基金（< 180天）应得到「持续观察」评级"""
    s = make_snapshot(run_days=150)
    q = make_quality("real")
    score = score_fund(s, q)
    assert score.rating == "持续观察", f"次新基金（150天）应为持续观察，实际：{score.rating}"


def test_six_month_to_one_year_cap():
    """运行 200 天（180-365）应被限为「谨慎关注」"""
    s = make_snapshot(run_days=200)
    q = make_quality("real")
    score = score_fund(s, q)
    assert score.rating == "谨慎关注", f"200天基金应为谨慎关注，实际：{score.rating}"


def test_mock_data_blocks_rating():
    """含模拟数据应得到「信息不足」评级"""
    s = make_snapshot(run_days=800, has_mock=True)
    q = make_quality("partial", mock_count=1)
    score = score_fund(s, q)
    assert score.rating == "信息不足"


def test_contradiction_blocks_rating():
    """数据矛盾应得到「无法评级」"""
    s = make_snapshot(run_days=800)
    q = make_quality("failed", contradictions=["rank > total"])
    score = score_fund(s, q)
    assert score.rating == "无法评级"


def test_normal_fund_gets_valid_rating():
    """正常基金（运行 > 2 年）应得到合理评级"""
    s = make_snapshot(run_days=1200, mdd=15.0, ret=80.0)
    q = make_quality("real")
    score = score_fund(s, q, sentiment_score=7.0)
    assert score.rating in ["适合配置", "积极关注", "谨慎关注"]
    assert score.confidence == "高"
    assert score.total_score > 0


def test_score_history_new_fund_cap():
    """次新基金历史分起点低"""
    s = make_snapshot(run_days=100, ret=200.0)  # 极高收益，但运行时间短
    h = score_history(s)
    assert h <= 5.5, f"次新基金历史分应被压低，实际：{h}"


def test_score_risk_new_fund_penalty():
    """次新基金风险分应被惩罚"""
    s = make_snapshot(run_days=100, mdd=3.0)   # 很低回撤
    r = score_risk(s)
    # 即使回撤很低，次新基金风险分应因惩罚项降低
    assert r < 9.0, f"次新基金风险分应有惩罚，实际：{r}"


def test_missing_fields_block_rating():
    """缺失关键字段应得到「信息不足」"""
    s = make_snapshot(run_days=1000)
    q = make_quality("partial", missing=["inception_date", "nav"])
    score = score_fund(s, q)
    assert score.rating == "信息不足"
