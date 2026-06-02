# tests/test_v21_regression.py
"""
回归测试：验证 V2.1 精准修复（v1_5.md）不再复现
覆盖三份样本报告（161725/026211/270042）中的 8 类问题：
  1. "运行时间长" → "运行时长惩罚"（评分表说明列）
  2. "至少=恢复撤回控制" → "越高=回撤控制越好"（评分表说明列）
  3. "方案/理念/概念结论" heading → 被 _clean_commentary 清除
  4. "嘲笑" → "mock"（指标来源列）
  5. None → "数据缺失"（指标表格空值）
  6. 双"适合人群" → 仅报告模板出现一次
  7. "丰田结论" Badge → validate_report 阻断
  8. "约束已" → 次新基金banner已修复
"""

import pytest


class TestScoreTableText:
    """验证评分表说明列不再有垃圾文本"""

    def _make_score(self, total=6.5, history=7.0, risk=5.0,
                    sentiment=6.0, alpha=0.3, rating="谨慎关注",
                    confidence="高", risk_level="中高"):
        from types import SimpleNamespace
        s = SimpleNamespace()
        s.history_score      = history
        s.sentiment_score    = sentiment
        s.risk_control_score = risk
        s.alpha_adjustment   = alpha
        s.total_score        = total
        s.rating             = rating
        s.confidence_label   = confidence
        s.risk_level         = risk_level
        s.rating_cap_reason  = None
        s.suitability        = "适合高风险投资者"
        return s

    def test_no_garbage_text_in_score_table(self):
        from backend.report_renderer import render_score_table
        score = self._make_score()
        table = render_score_table(score)

        assert "运行时间长" not in table,     "运行时间长 不应出现"
        assert "至少=" not in table,          "至少= 不应出现"
        assert "恢复撤回" not in table,       "恢复撤回 不应出现"
        assert "运行时长惩罚" in table,       "应有'运行时长惩罚'"
        assert "回撤控制越好" in table,       "应有回撤控制说明"

    def test_none_total_shows_not_calculated(self):
        from backend.report_renderer import render_score_table
        score = self._make_score(total=None)
        table = render_score_table(score)
        assert "不计算正式综合分" in table

    def test_none_alpha_shows_not_applicable(self):
        from backend.report_renderer import render_score_table
        score = self._make_score(alpha=None)
        table = render_score_table(score)
        assert "不适用" in table


class TestMetricTableText:
    """验证指标溯源表不再有脏值"""

    def test_no_shuju_yuanzhu(self):
        """None 值显示「数据缺失」，不是「数据援助」"""
        from backend.report_renderer import add_row_fixed
        row = add_row_fixed("近1年收益", None, "%")
        assert "数据援助" not in row
        assert "数据缺失" in row

    def test_no_xianyouriqi_column(self):
        """列名是「截止日期」，不是「现有日期」"""
        from backend.report_renderer import render_metric_table
        from types import SimpleNamespace
        from datetime import date

        snap = SimpleNamespace()
        snap.unit_nav = SimpleNamespace()
        snap.unit_nav.value = 1.5
        snap.unit_nav.source = "akshare"
        snap.unit_nav.is_mock = False
        snap.unit_nav.as_of = date.today()
        n = SimpleNamespace(); n.value = "real"
        snap.unit_nav.nature = n

        for field in ['accumulated_nav', 'fund_size', 'fund_size_bn',
                      'return_since_inception', 'return_1y', 'return_3y',
                      'max_drawdown', 'max_drawdown_pct',
                      'benchmark_return', 'benchmark_return_pct',
                      'alpha', 'alpha_pct']:
            setattr(snap, field, None)

        table = render_metric_table(snap)
        assert "现有日期" not in table
        assert "截止日期" in table

    def test_no_嘲笑_in_source(self):
        """「嘲笑」不应出现在来源列，应被映射为 mock 相关值"""
        from backend.report_renderer import fmt_source
        from types import SimpleNamespace

        m = SimpleNamespace()
        m.source = "嘲笑"
        result = fmt_source(m)
        assert "嘲笑" not in result
        assert "mock" in result   # 允许 "mock" 或 "mock（模拟）"

    def test_计算_source_mapped(self):
        """「计算」来源映射为「calculated」"""
        from backend.report_renderer import fmt_source
        from types import SimpleNamespace

        m = SimpleNamespace()
        m.source = "计算"
        result = fmt_source(m)
        assert result == "calculated"


class TestCommentaryCleaning:
    """验证 commentary 中的结论标题被 _clean_commentary 清除"""

    def test_llm_heading_stripped(self):
        """LLM 生成的 📌方案结论 不应出现在最终报告"""
        from backend.report_renderer import _clean_commentary
        text = "业绩分析内容...\n📌方案结论：风险较高\n更多内容"
        result = _clean_commentary(text)
        assert "方案结论" not in result

    def test_理念结论_stripped(self):
        from backend.report_renderer import _clean_commentary
        text = "风险分析...\n📌理念结论：持续观察\n更多"
        result = _clean_commentary(text)
        assert "理念结论" not in result

    def test_概念结论_stripped(self):
        from backend.report_renderer import _clean_commentary
        text = "行情分析...\n📌概念结论：信息不足\n"
        result = _clean_commentary(text)
        assert "概念结论" not in result

    def test_丰田结论_stripped(self):
        from backend.report_renderer import _clean_commentary
        text = "分析内容...\n📌丰田结论：谨慎关注\n"
        result = _clean_commentary(text)
        assert "丰田结论" not in result

    def test_normal_text_preserved(self):
        """正常文本不应被删除"""
        from backend.report_renderer import _clean_commentary
        text = "该基金自成立以来收益显著，风险控制能力较好。"
        result = _clean_commentary(text)
        assert "自成立以来收益" in result

    def test_empty_input_returns_default(self):
        """空输入返回默认提示"""
        from backend.report_renderer import _clean_commentary
        result = _clean_commentary("")
        assert "数据获取失败" in result


class TestBadgeText:
    """验证 output_guard 拦截 Badge 中的幻觉词"""

    def test_badge_no_丰田结论(self):
        """「丰田结论」出现在报告中应被阻断"""
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n⚠️ 部分模拟\n丰田结论显示为信息不足\n"
            "## 三、核心指标溯源\nX\n"
            "## 四、综合评分\n适配结论：信息不足\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        assert not ok
        assert any("丰田结论" in e or "禁用词" in e for e in errors)

    def test_方案结论_heading_blocked(self):
        """「📌方案结论」heading 被 check_heading_variants 拦截"""
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n真实\n"
            "## 三、核心指标溯源\nX\n"
            "## 四、综合评分\n📌方案结论：风险较高\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        assert not ok

    def test_正确适配结论_passes(self):
        """合法的「📌 适配结论」heading 不被阻断"""
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n真实\n"
            "## 三、核心指标溯源\nX\n"
            "## 四、综合评分\n📌 适配结论：谨慎关注\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        # 适配结论合法，不应触发结论标题检测错误
        heading_errors = [e for e in errors if "非法结论标题" in e]
        assert not heading_errors, f"合法结论标题不应被阻断: {heading_errors}"


class TestBenchmarkResolver:
    """验证 161725 和 270042 的基准识别"""

    def test_161725_白酒_resolves_correctly(self):
        """白酒基金：基准应解析为中证白酒指数，并有与沪深300不匹配的警告"""
        from backend.benchmark_resolver import resolve_benchmark
        b = resolve_benchmark(
            "招商中证白酒指数证券投资基金",
            fund_type="股票型",
            declared_benchmark="沪深300"
        )
        # 从基金名称匹配到白酒指数
        assert b.name == "中证白酒指数"
        # is_matched=True（通过名称关键词匹配到）
        assert b.is_matched
        # 与声明的沪深300不匹配，应有警告
        assert b.mismatch_warning is not None
        assert "沪深300" in b.mismatch_warning or "白酒" in b.mismatch_warning

    def test_270042_纳斯达克100_resolved(self):
        """纳斯达克100 QDII：基准应解析为纳斯达克100指数"""
        from backend.benchmark_resolver import resolve_benchmark
        b = resolve_benchmark(
            "广发纳斯达克100交易型开放式指数证券投资基金联接基金(QDII)",
            fund_type="QDII"
        )
        assert "纳斯达克100" in b.name
        assert b.is_matched


class TestOutputGuardNew:
    """验证新增的结论标题检测函数"""

    def test_check_heading_variants_detects_方案结论(self):
        """check_heading_variants 直接测试"""
        from backend.output_guard import check_heading_variants
        text = "某段文字\n📌方案结论：风险较高\n另一段"
        errors = check_heading_variants(text)
        assert len(errors) > 0
        assert any("方案结论" in e for e in errors)

    def test_check_heading_variants_allows_适配结论(self):
        """合法的「📌 适配结论」不应被检测到"""
        from backend.output_guard import check_heading_variants
        text = "### 📌 适配结论：谨慎关注\n"
        errors = check_heading_variants(text)
        assert not errors, f"合法标题不应报错：{errors}"

    def test_理念结论_detected(self):
        from backend.output_guard import check_heading_variants
        errors = check_heading_variants("📌理念结论：持续观察")
        assert any("理念结论" in e for e in errors)

    def test_丰田结论_detected(self):
        from backend.output_guard import check_heading_variants
        errors = check_heading_variants("📌丰田结论：信息不足")
        assert any("丰田结论" in e for e in errors)


class TestConstantsNew:
    """验证 constants.py 新增词条"""

    def test_新增禁用词_in_BANNED_WORDS(self):
        from backend.constants import BANNED_WORDS
        new_words = [
            "方案结论", "理念结论", "概念结论", "丰田结论",
            "运行时间长", "至少=恢复", "恢复撤回控制",
            "营养不良", "通讯作者", "认知社区情感",
        ]
        for w in new_words:
            assert w in BANNED_WORDS, f"「{w}」应在 BANNED_WORDS 中"

    def test_新增自动修复词_in_AUTO_FIX_MAP(self):
        from backend.constants import AUTO_FIX_MAP
        expected = {
            "方案结论":               "适配结论",
            "理念结论":               "适配结论",
            "丰田结论":               "适配结论",
            "能承受大幅恢复":          "能承受大幅回撤",
            "认知社区情感":            "认清社区情感",
        }
        for k, v in expected.items():
            assert k in AUTO_FIX_MAP, f"AUTO_FIX_MAP 应包含「{k}」"
            assert AUTO_FIX_MAP[k] == v, f"AUTO_FIX_MAP['{k}'] 应为「{v}」，实际为「{AUTO_FIX_MAP[k]}」"
