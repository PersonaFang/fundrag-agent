# tests/test_v21_fixes.py
"""
V2.1 修复验证测试
覆盖：constants/scoring/output_guard/benchmark_resolver/data_quality
"""

import pytest
from datetime import date, timedelta


# ============================================================
# 1. constants & value_cleaner
# ============================================================
class TestValueCleaner:
    def test_dirty_source_嘲笑_is_fixed(self):
        from backend.value_cleaner import normalize_source
        result = normalize_source("嘲笑")
        assert result == "mock"

    def test_unknown_source_raises(self):
        from backend.value_cleaner import normalize_source
        with pytest.raises(ValueError, match="非法 source"):
            normalize_source("随机来源", allow_warning=False)

    def test_missing_string_becomes_none(self):
        from backend.value_cleaner import clean_value
        assert clean_value("数据援助") is None
        assert clean_value("—") is None
        assert clean_value("N/A") is None
        assert clean_value("") is None

    def test_manager_name_bracket_cleaned(self):
        from backend.value_cleaner import clean_manager_name
        names = clean_manager_name("俞（瑶从业4.6年）\n要文强")
        # 清洗后姓名中不含括号
        for n in names:
            assert "（" not in n and "(" not in n
        # 「要文强」应被识别为合法姓名
        assert "要文强" in names

    def test_illegal_rating_fixed(self):
        from backend.value_cleaner import normalize_rating
        assert normalize_rating("吞") == "无法评级"
        assert normalize_rating("缓解") == "风险较高"
        assert normalize_rating("建议买入") == "谨慎关注"
        assert normalize_rating("适合配置") == "适合配置"  # 合法值不变

    def test_auto_fix_replaces_banned_words(self):
        from backend.value_cleaner import auto_fix_text
        text, fixes = auto_fix_text("需投资珍珠，力算产业链，显着增长。")
        assert "珍珠" not in text
        assert "算力产业链" in text
        assert "显著" in text
        assert len(fixes) > 0


# ============================================================
# 2. output_guard
# ============================================================
class TestOutputGuard:
    def make_valid_report(self) -> str:
        return (
            "## 一、数据质量说明\n✅ 真实\n"
            "## 二、基金基本信息\nXX\n"
            "## 三、核心指标溯源\n| 指标 |\n"
            "## 四、综合评分\n适配结论：谨慎关注\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议。"
        )

    def test_valid_report_passes(self):
        from backend.output_guard import validate_report
        ok, errors = validate_report(self.make_valid_report())
        assert ok, f"应通过：{errors}"

    def test_吞_blocked(self):
        from backend.output_guard import validate_report
        text = self.make_valid_report().replace("谨慎关注", "吞")
        ok, errors = validate_report(text)
        assert not ok

    def test_嘲笑_blocked(self):
        from backend.output_guard import validate_report
        text = self.make_valid_report() + " 来源：嘲笑"
        ok, errors = validate_report(text)
        assert not ok

    def test_mock_plus_high_confidence_blocked(self):
        from backend.output_guard import validate_report
        text = self.make_valid_report() + " 🔴 模拟 置信度：高 综合得分 | 7.1"
        ok, errors = validate_report(text)
        assert not ok
        assert any("模拟" in e and "置信度" in e for e in errors)

    def test_duplicate_section_blocked(self):
        from backend.output_guard import validate_report
        text = self.make_valid_report() + "\n## 四、综合评分\n重复出现"
        ok, errors = validate_report(text)
        assert not ok

    def test_illegal_rating_in_report_blocked(self):
        from backend.output_guard import validate_report
        text = self.make_valid_report().replace("适配结论：谨慎关注", "适配结论：建议买入")
        ok, errors = validate_report(text)
        assert not ok


# ============================================================
# 3. benchmark_resolver
# ============================================================
class TestBenchmarkResolver:
    def test_白酒_matched_with_mismatch_warning(self):
        """白酒基金通过名称匹配到白酒指数（is_matched=True），但与声明的沪深300不符"""
        from backend.benchmark_resolver import resolve_benchmark
        b = resolve_benchmark("招商中证白酒指数证券投资基金", fund_type="股票型",
                               declared_benchmark="沪深300")
        assert b.name == "中证白酒指数"
        assert b.is_matched           # ✅ 从基金名称匹配到，is_matched=True
        assert b.mismatch_warning is not None  # ✅ 与声明基准不符，有警告

    def test_纳斯达克100_resolved(self):
        from backend.benchmark_resolver import resolve_benchmark
        b = resolve_benchmark(
            "广发纳斯达克100交易型开放式指数证券投资基金联接基金(QDII)",
            fund_type="QDII"
        )
        assert "纳斯达克100" in b.name
        assert b.is_matched

    def test_unknown_fund_returns_missing(self):
        from backend.benchmark_resolver import resolve_benchmark
        b = resolve_benchmark("未知主题增强基金", fund_type=None)
        assert not b.is_matched or b.name is None


# ============================================================
# 4. scoring
# ============================================================
class TestScoring:
    def _make_snapshot(self, run_days=1200, mdd=20.0, ret=50.0,
                        bench_mock=False, alpha_mock=False):
        """构造测试用 snapshot（简化版，兼容新旧 schema）"""
        from types import SimpleNamespace

        def make_m(val, is_mock=False, nature_str='real'):
            m = SimpleNamespace()
            m.value   = val
            m.is_mock = is_mock
            # 创建 nature 枚举兼容对象
            nature = SimpleNamespace()
            nature.value = 'mock' if is_mock else nature_str
            m.nature = nature
            m.depends_on = []
            return m

        snap = SimpleNamespace()
        snap.run_days               = run_days
        snap.unit_nav               = make_m(1.5)
        snap.nav                    = make_m(1.5)
        snap.max_drawdown           = make_m(mdd)
        snap.max_drawdown_pct       = make_m(mdd)
        snap.return_since_inception = make_m(ret)
        snap.return_1y              = None
        snap.return_3y              = None
        snap.benchmark_return       = make_m(20.0, is_mock=bench_mock)
        snap.benchmark_return_pct   = make_m(20.0, is_mock=bench_mock)
        alpha_val = ret - 20.0
        snap.alpha     = make_m(alpha_val, is_mock=alpha_mock, nature_str='calculated')
        snap.alpha_pct = snap.alpha
        snap.accumulated_nav = make_m(2.0)
        snap.fund_size     = None
        snap.fund_size_bn  = None
        return snap

    def _make_quality(self, contradictions=None, mock_count=0, level="real"):
        from types import SimpleNamespace
        q = SimpleNamespace()
        q.contradictions    = contradictions or []
        q.mock_metric_count = mock_count
        q.level             = SimpleNamespace()
        q.level.value       = level
        q.warnings          = []
        q.missing_fields    = []
        return q

    def test_mock_benchmark_no_alpha_bonus(self):
        """270042场景：基准是mock，Alpha不应加分"""
        from backend.scoring import score_fund, compute_alpha_adjustment
        snap = self._make_snapshot(run_days=5037, mdd=31.18,
                                    ret=747.73, bench_mock=True)
        adj, reason = compute_alpha_adjustment(snap)
        assert adj == 0.0, f"mock基准不应产生Alpha调整，实际={adj}"
        assert reason is not None

    def test_mock_core_data_forces_info_insufficient(self):
        """核心数据含mock → 信息不足，不输出综合分"""
        from backend.scoring import score_fund
        snap = self._make_snapshot(run_days=5037, bench_mock=True)
        q    = self._make_quality(mock_count=2, level="partial")
        result = score_fund(snap, q, sentiment_score=6.0)
        assert result.rating == "信息不足"
        assert result.total_score is None
        assert result.confidence_label == "低"
        assert result.alpha_adjustment is None

    def test_new_fund_no_total_score(self):
        """026211场景：次新基金（170天）→ 持续观察，不输出综合分"""
        from backend.scoring import score_fund
        snap = self._make_snapshot(run_days=170)
        q    = self._make_quality(level="real")
        result = score_fund(snap, q, sentiment_score=7.5)
        assert result.rating == "持续观察"
        assert result.total_score is None
        assert result.confidence_label == "低"

    def test_drawdown_31_is_high_risk(self):
        """270042场景：最大回撤31.18% → 风险等级「中高」"""
        from backend.scoring import risk_level_from_drawdown
        level = risk_level_from_drawdown(31.18)
        assert level in {"中高", "高"}, f"31.18%回撤应为中高/高风险，实际={level}"

    def test_drawdown_65_is_extreme_risk(self):
        """161725场景：最大回撤65.45% → 风险等级「极高」"""
        from backend.scoring import risk_level_from_drawdown
        level = risk_level_from_drawdown(65.45)
        assert level == "极高"

    def test_contradictions_block_rating(self):
        """数据矛盾 → 无法评级"""
        from backend.scoring import score_fund
        snap = self._make_snapshot(run_days=1200)
        q    = self._make_quality(contradictions=["rank > total"], level="failed")
        result = score_fund(snap, q)
        assert result.rating == "无法评级"
        assert result.total_score is None

    def test_score_result_json_roundtrip(self):
        """ScoreResult 序列化/反序列化往返测试"""
        from backend.scoring import score_fund, ScoreResult
        snap = self._make_snapshot(run_days=1200, mdd=15.0, ret=80.0)
        q    = self._make_quality(level="real")
        result = score_fund(snap, q, sentiment_score=7.0)

        json_str = result.to_json()
        restored = ScoreResult.from_json(json_str)
        assert restored.rating == result.rating
        assert restored.total_score == result.total_score
        assert restored.confidence_label == result.confidence_label


# ============================================================
# 5. data_quality 一致性校验
# ============================================================
class TestDataQuality:
    def test_accumulated_nav_1_flagged_suspicious(self):
        """累计净值写死为1.0时应标记为 suspicious"""
        from backend.data_quality import validate_nav_consistency
        from types import SimpleNamespace

        snap = SimpleNamespace()
        unit = SimpleNamespace(); unit.value = 8.4773
        acc  = SimpleNamespace(); acc.value  = 1.0
        acc.nature = SimpleNamespace(); acc.nature.value = 'real'
        acc.confidence = 1.0

        snap.unit_nav        = unit
        snap.nav             = unit
        snap.accumulated_nav = acc

        warnings = validate_nav_consistency(snap)
        assert warnings, "累计净值=1.0,单位净值=8.47,应产生警告"
        assert acc.nature.value == 'suspicious' or acc.confidence < 0.5

    def test_new_fund_1y_return_flagged(self):
        """次新基金（170天）出现近1年收益 → 标记suspicious"""
        from backend.data_quality import validate_time_window_consistency
        from types import SimpleNamespace

        snap = SimpleNamespace()
        snap.run_days = 170
        r1y = SimpleNamespace(); r1y.value = 73.13
        r1y.nature = SimpleNamespace(); r1y.nature.value = 'real'
        r1y.confidence = 1.0; r1y.note = None

        snap.return_1y = r1y
        snap.return_3y = None

        warnings = validate_time_window_consistency(snap)
        assert warnings
        assert r1y.nature.value == 'suspicious'

    def test_benchmark_mismatch_warns(self):
        """白酒基金声明沪深300基准 → 产生不匹配警告"""
        from backend.benchmark_resolver import resolve_benchmark
        b = resolve_benchmark("招商中证白酒指数证券投资基金",
                               declared_benchmark="沪深300")
        assert b.mismatch_warning is not None
        assert "沪深300" in b.mismatch_warning or "白酒" in b.mismatch_warning
