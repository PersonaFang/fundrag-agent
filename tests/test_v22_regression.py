# tests/test_v22_regression.py
"""
V2.2 回归测试：验证本轮所有修复点不再复现
覆盖 026211 报告中的 14 类问题：
  #1  "数据援助" → "数据缺失"
  #2  "⬜ 阿富汗" → "⬜ 缺失"（DataNature 安全渲染）
  #3  "📌理念结论" → 被 _clean_commentary 清除
  #4  "📌建议结论" → output_guard 拦截
  #5  "基准指数：数据援助" → "基准指数：数据缺失"
  #6  "运行时间长处罚" → "运行时长惩罚"
  #7  "至少=恢复撤回控制" → "越高=回撤控制越好"
  #8  "修正结论受运行时长约束已" → banner 语序正确
  #9  output_guard 未生效 → 现在挂在 render_report 之后
  #10 "🟢数据完整" → 次新基金显示 "🟡样本受限"
  #11 风险等级"低" → 科技次新基金正确推高风险等级
  #12 Alpha 幻觉 → 次新基金/基准未确认时强制 None
  #13 "不统计显着性" → output_guard 检测并 auto_fix
  #14 情绪评分重复 → 只取最后一个
"""

import pytest


class TestDataNatureDisplay:
    """验证 DataNature 枚举渲染不透传原始值"""

    def test_unknown_nature_shows_缺失(self):
        """任何未知 nature 值不能透传，必须显示⬜缺失"""
        from backend.report_renderer import _safe_nature_display
        from types import SimpleNamespace
        m = SimpleNamespace()
        m.nature = SimpleNamespace(value="阿富汗")
        m.is_mock = False
        result = _safe_nature_display(m)
        assert "阿富汗" not in result
        assert result == "⬜ 缺失"

    def test_none_nature_shows_缺失(self):
        from backend.report_renderer import _safe_nature_display
        from types import SimpleNamespace
        m = SimpleNamespace(); m.nature = None; m.is_mock = False
        assert _safe_nature_display(m) == "⬜ 缺失"

    def test_real_nature_shows_真实(self):
        from backend.report_renderer import _safe_nature_display
        from types import SimpleNamespace
        m = SimpleNamespace()
        m.nature = SimpleNamespace(value="real"); m.is_mock = False
        assert _safe_nature_display(m) == "✅ 真实"

    def test_mock_nature_shows_模拟(self):
        from backend.report_renderer import _safe_nature_display
        from types import SimpleNamespace
        m = SimpleNamespace()
        m.nature = SimpleNamespace(value="mock"); m.is_mock = True
        assert _safe_nature_display(m) == "🔴 模拟"

    def test_none_metric_shows_缺失(self):
        from backend.report_renderer import _safe_nature_display
        assert _safe_nature_display(None) == "⬜ 缺失"


class TestAddRowFixed:
    """验证 add_row_fixed 不出现"数据援助"等脏词"""

    def test_none_metric_shows_数据缺失(self):
        from backend.report_renderer import add_row_fixed
        row = add_row_fixed("近1年收益", None, "%")
        assert "数据援助" not in row
        assert "数据缺失" in row

    def test_none_value_shows_数据缺失(self):
        from backend.report_renderer import add_row_fixed
        from types import SimpleNamespace
        m = SimpleNamespace(); m.value = None; m.is_mock = False
        m.nature = None; m.as_of = None; m.source = "akshare"
        row = add_row_fixed("净值", m, "元")
        assert "数据缺失" in row

    def test_unknown_nature_not_in_output(self):
        """非法 nature 值不应透传到输出"""
        from backend.report_renderer import add_row_fixed
        from types import SimpleNamespace
        m = SimpleNamespace()
        m.value = None; m.is_mock = False
        m.nature = SimpleNamespace(value="阿富汗")
        m.as_of = None; m.source = "akshare"
        row = add_row_fixed("测试指标", m, "")
        assert "阿富汗" not in row

    def test_嘲笑_not_in_source(self):
        """source='嘲笑' 应映射为 mock 相关值（嘲笑不出现在输出中）"""
        from backend.report_renderer import fmt_source
        from types import SimpleNamespace
        m = SimpleNamespace(); m.source = "嘲笑"
        result = fmt_source(m)
        assert "嘲笑" not in result
        assert "mock" in result   # 允许 "mock" 或 "mock（模拟）"


class TestRiskLevel:
    """验证 compute_risk_level 综合判断逻辑"""

    def test_科技次新基金_不能是低风险(self):
        """026211场景：科技主题171天，不能因为回撤低就给低风险"""
        from backend.scoring import compute_risk_level
        level = compute_risk_level(
            max_drawdown_pct=9.22,
            fund_name="平安科技精选混合",
            fund_type="混合型",
            run_days=171,
        )
        assert level not in ("低", "中低"), f"科技次新基金不应为{level}"
        assert level in ("中", "中高", "高", "极高")

    def test_货币基金_是低风险(self):
        from backend.scoring import compute_risk_level
        # 货币型基金，回撤 2%（用百分比表示 > 1，代码会除以100得到0.02 ≤ 0.05阈值 → 低）
        level = compute_risk_level(
            max_drawdown_pct=2.0,
            fund_name="天弘余额宝货币",
            fund_type="货币型",
            run_days=3000,
        )
        assert level == "低"

    def test_QDII_最低中高风险(self):
        from backend.scoring import compute_risk_level
        level = compute_risk_level(
            max_drawdown_pct=5.0,
            fund_name="广发纳斯达克100",
            fund_type="QDII",
            run_days=2000,
        )
        assert level in ("中高", "高", "极高")

    def test_高回撤_极高风险(self):
        from backend.scoring import compute_risk_level
        level = compute_risk_level(
            max_drawdown_pct=65.0,
            fund_name="普通基金",
            fund_type="股票型",
            run_days=2000,
        )
        assert level == "极高"


class TestAlphaForNewFund:
    """验证次新基金和基准未确认时 Alpha 强制置 None"""

    def _make_snapshot(self, run_days, bench_matched=False):
        from types import SimpleNamespace
        s = SimpleNamespace()
        s.run_days  = run_days
        s.name      = "测试基金"
        s.fund_type = "混合型"
        s.return_since_inception = SimpleNamespace(value=20.0, is_mock=False)
        s.return_1y  = None
        s.return_3y  = None
        s.max_drawdown = SimpleNamespace(value=5.0, is_mock=False)
        s.max_drawdown_pct = s.max_drawdown
        s.benchmark = SimpleNamespace(is_matched=bench_matched, name="沪深300") if bench_matched else None
        return s

    def test_次新基金_alpha_is_none(self):
        from backend.scoring import calculate_score
        snap = self._make_snapshot(run_days=171, bench_matched=True)
        result = calculate_score(snap, sentiment_score=6.0, benchmark_return=5.0)
        assert result.alpha_adjustment is None, f"次新基金alpha应为None，实际={result.alpha_adjustment}"

    def test_基准未确认_alpha_is_none(self):
        from backend.scoring import calculate_score
        snap = self._make_snapshot(run_days=800, bench_matched=False)
        result = calculate_score(snap, sentiment_score=6.0, benchmark_return=5.0)
        assert result.alpha_adjustment is None, f"基准未确认时alpha应为None，实际={result.alpha_adjustment}"

    def test_正常基金_alpha_calculated(self):
        """成熟基金+基准确认 → alpha 正常计算"""
        from backend.scoring import calculate_score
        snap = self._make_snapshot(run_days=800, bench_matched=True)
        result = calculate_score(snap, sentiment_score=6.0, benchmark_return=5.0)
        # alpha = (20.0 - 5.0) / 10 = 1.5 → clamped to 1.0
        assert result.alpha_adjustment is not None


class TestDataQualityLevel:
    """验证数据质量 level 分级（含 limited）"""

    def test_次新基金_level_is_limited(self):
        from backend.data_quality import assess_quality
        from types import SimpleNamespace
        s = SimpleNamespace()
        s.run_days  = 171
        s.benchmark = None
        s.peer_rank = None
        for attr in ['unit_nav','nav','accumulated_nav','fund_size','fund_size_bn',
                     'return_since_inception','return_1y','return_3y',
                     'max_drawdown','max_drawdown_pct','benchmark_return',
                     'benchmark_return_pct','alpha','alpha_pct']:
            setattr(s, attr, None)
        s.unit_nav = SimpleNamespace(value=1.8, is_mock=False)
        s.return_since_inception = SimpleNamespace(value=80.0, is_mock=False)
        s.max_drawdown = SimpleNamespace(value=9.22, is_mock=False)

        result = assess_quality(s)
        assert result.level == "limited", f"次新基金应为limited，得到{result.level}"

    def test_成熟基金_level_is_real(self):
        from backend.data_quality import assess_quality
        from types import SimpleNamespace
        s = SimpleNamespace()
        s.run_days  = 1500
        s.benchmark = SimpleNamespace(is_matched=True, name="沪深300")
        s.peer_rank = None
        for attr in ['nav','accumulated_nav','fund_size','fund_size_bn',
                     'return_since_inception','return_1y','return_3y',
                     'max_drawdown','max_drawdown_pct','benchmark_return',
                     'benchmark_return_pct','alpha','alpha_pct']:
            setattr(s, attr, None)
        s.unit_nav = SimpleNamespace(value=2.0, is_mock=False)
        result = assess_quality(s)
        assert result.level == "real"

    def test_limited_has_summary(self):
        """limited 等级有专属 summary 文案"""
        from backend.data_quality import assess_quality
        from types import SimpleNamespace
        s = SimpleNamespace()
        s.run_days  = 100
        s.benchmark = None
        s.peer_rank = None
        for attr in ['unit_nav','nav','accumulated_nav','fund_size','fund_size_bn',
                     'return_since_inception','return_1y','return_3y',
                     'max_drawdown','max_drawdown_pct','benchmark_return',
                     'benchmark_return_pct','alpha','alpha_pct']:
            setattr(s, attr, None)
        s.unit_nav = SimpleNamespace(value=1.5, is_mock=False)
        result = assess_quality(s)
        assert result.level == "limited"
        assert result.summary
        assert "样本量不足" in result.summary or "统计意义" in result.summary


class TestSentimentDedup:
    """验证情绪评分只取最后一个，不重复"""

    def test_module_level_extract_last_match(self):
        """_extract_sentiment_score 只取最后一个匹配"""
        from backend.graph import _extract_sentiment_score
        text = "分析...\n情绪评分：6\n更多内容\n情绪评分：7"
        score = _extract_sentiment_score(text)
        assert score == 7.0, f"应取最后一个7，得到{score}"

    def test_module_level_single_match(self):
        from backend.graph import _extract_sentiment_score
        text = "舆情分析\n情绪评分：5"
        assert _extract_sentiment_score(text) == 5.0

    def test_module_level_no_match_default(self):
        from backend.graph import _extract_sentiment_score
        assert _extract_sentiment_score("无评分文本") == 5.0

    def test_clean_commentary_dedup(self):
        """_clean_commentary 去重，多个情绪评分只保留一个"""
        from backend.report_renderer import _clean_commentary
        text = "舆情分析内容\n情绪评分：6\n\n情绪评分：6"
        result = _clean_commentary(text)
        count = result.count("情绪评分")
        assert count <= 1, f"情绪评分出现{count}次，应最多1次"


class TestOutputGuardV22:
    """验证 output_guard V2.2 更新"""

    def test_显着_blocked(self):
        """「显着」应被 check_banned_words 检测"""
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n不统计显着性\n"
            "## 三、核心指标溯源\nX\n"
            "## 四、综合评分\n📌 适配结论：持续观察\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        assert not ok
        assert any("显着" in e for e in errors)

    def test_auto_fix_repairs_显着(self):
        """auto_fix_report 修复「显着」→「显著」"""
        from backend.output_guard import auto_fix_report
        text = "基金表现显着优于同类。"
        fixed, logs = auto_fix_report(text)
        assert "显着" not in fixed
        assert "显著" in fixed

    def test_建议结论_blocked(self):
        """「📌建议结论」应被 check_heading_variants 检测"""
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n真实\n"
            "## 三、核心指标溯源\nX\n"
            "## 四、综合评分\n📌建议结论：持续观察\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        assert not ok
        heading_errors = [e for e in errors if "非法结论标题" in e]
        assert heading_errors, f"未检测到非法结论标题，errors={errors}"

    def test_auto_fix_repairs_建议结论(self):
        """auto_fix_report 修复「📌建议结论」→「📌 适配结论」"""
        from backend.output_guard import auto_fix_report
        text = "某段文字\n📌建议结论：持续观察\n结尾"
        fixed, logs = auto_fix_report(text)
        assert "建议结论" not in fixed
        assert "适配结论" in fixed

    def test_合法报告_passes_blocking_check(self):
        """合法报告不应触发阻断性错误"""
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n✅ 真实\n"
            "## 三、核心指标溯源\n表格\n"
            "## 四、综合评分\n📌 适配结论：持续观察\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        blocking = [e for e in errors
                    if "非法结论标题" in e or "禁用词" in e
                    or "非法评级" in e or "未替换占位符" in e]
        assert not blocking, f"合法报告不应被阻断: {blocking}"

    def test_丰田结论_blocked(self):
        from backend.output_guard import validate_report
        text = (
            "## 一、数据质量说明\n⚠️ 部分模拟\n"
            "## 三、核心指标溯源\nX\n"
            "## 四、综合评分\n📌 适配结论：信息不足\n丰田结论\n"
            "## 八、⚠️ 风险提示\n不构成任何投资建议"
        )
        ok, errors = validate_report(text)
        assert not ok
        assert any("丰田结论" in e or "禁用词" in e for e in errors)


class TestScoreResultRunDays:
    """验证 ScoreResult 新增 run_days 字段"""

    def test_run_days_default_none(self):
        from backend.scoring import ScoreResult
        r = ScoreResult(
            history_score=5.0, sentiment_score=5.0, risk_control_score=5.0,
            alpha_adjustment=None, total_score=5.0,
            rating="谨慎关注", confidence_label="中", risk_level="中",
            rating_cap_reason=None, suitability="适合配置"
        )
        assert r.run_days is None

    def test_run_days_json_roundtrip(self):
        """run_days 字段序列化/反序列化"""
        from backend.scoring import ScoreResult
        r = ScoreResult(
            history_score=5.0, sentiment_score=6.0, risk_control_score=5.0,
            alpha_adjustment=None, total_score=5.5,
            rating="谨慎关注", confidence_label="中", risk_level="中",
            rating_cap_reason=None, suitability="适合小仓位配置",
            run_days=171
        )
        restored = ScoreResult.from_json(r.to_json())
        assert restored.run_days == 171

    def test_from_json_old_format(self):
        """旧格式 JSON（无 run_days）不崩溃"""
        from backend.scoring import ScoreResult
        import json
        old_json = json.dumps({
            "history_score": 5.0, "sentiment_score": 5.0, "risk_control_score": 5.0,
            "alpha_adjustment": None, "total_score": 5.0,
            "rating": "谨慎关注", "confidence_label": "中", "risk_level": "中",
            "rating_cap_reason": None, "suitability": "适合配置"
            # 没有 run_days
        }, ensure_ascii=False)
        r = ScoreResult.from_json(old_json)
        assert r.run_days is None
