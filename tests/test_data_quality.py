# tests/test_data_quality.py
from datetime import date
from backend.schemas import FundSnapshot, MetricSource, PeerRank
from backend.data_quality import validate_snapshot


def make_metric(value, is_mock=False, as_of=None):
    return MetricSource(
        value=value, source="test", is_mock=is_mock,
        as_of=as_of or date.today()
    )


def test_run_days_computed_correctly():
    s = FundSnapshot(
        code="000001",
        report_date=date(2026, 5, 31),
        inception_date=date(2025, 12, 12),
        nav=make_metric(1.5)
    )
    q = validate_snapshot(s)
    assert s.run_days == 170, f"期望 170，实际 {s.run_days}"


def test_short_run_warns():
    s = FundSnapshot(
        code="026211",
        report_date=date(2026, 5, 31),
        inception_date=date(2025, 12, 12),
        nav=make_metric(1.9),
        max_drawdown=make_metric(9.2),
        return_since_inception=make_metric(93.0),
    )
    q = validate_snapshot(s)
    assert any("180" in w or "6" in w for w in q.warnings), "应有次新基金警告"


def test_peer_rank_contradiction_detected():
    """rank > total 应被检测为矛盾"""
    s = FundSnapshot(
        code="025493",
        report_date=date(2026, 5, 31),
        inception_date=date(2025, 11, 1),
        nav=make_metric(1.5),
        peer_rank=PeerRank(rank=8210, total=8000, percentile=98.2),  # rank > total
    )
    q = validate_snapshot(s)
    assert q.contradictions, "应检测到排名矛盾"
    assert q.level.value == "failed"


def test_mock_data_partial_level():
    s = FundSnapshot(
        code="000001",
        report_date=date.today(),
        inception_date=date(2020, 1, 1),
        nav=make_metric(1.5, is_mock=True),
        max_drawdown=make_metric(20.0),
        return_since_inception=make_metric(50.0),
    )
    q = validate_snapshot(s)
    assert q.level.value == "partial"
    assert q.mock_metric_count >= 1


def test_clean_data_real_level():
    """真实数据应得到 real 质量等级"""
    s = FundSnapshot(
        code="110022",
        report_date=date.today(),
        inception_date=date(2020, 1, 1),
        nav=make_metric(2.1),
        max_drawdown=make_metric(25.0),
        return_since_inception=make_metric(110.0),
    )
    q = validate_snapshot(s)
    assert q.level.value == "real"
    assert not q.contradictions


def test_percentile_contradiction_detected():
    """percentile 与 rank/total 不符应被检测"""
    s = FundSnapshot(
        code="999999",
        report_date=date.today(),
        inception_date=date(2020, 1, 1),
        peer_rank=PeerRank(rank=100, total=1000, percentile=50.0),  # 100/1000=10%, but given 50%
    )
    q = validate_snapshot(s)
    assert q.contradictions, "应检测到 percentile 矛盾"
