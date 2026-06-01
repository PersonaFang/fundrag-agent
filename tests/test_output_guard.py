# tests/test_output_guard.py
from backend.output_guard import validate_report, auto_fix_report


def _make_valid_report(body: str = "") -> str:
    """生成一个包含所有必要章节的基础报告（V2.1 兼容）"""
    return f"""## 一、数据质量说明
✅ 数据真实
{body}
## 三、核心指标溯源
| 指标 | 数值 | 数据性质 |
|------|------|---------|
| 净值 | 1.5 | ✅ 真实 |
## 四、综合评分
适配结论：谨慎关注
## 八、⚠️ 风险提示
本报告不构成任何投资建议。基金有风险，投资需谨慎。
数据质量说明：已验证。"""


def test_banned_phrase_blocked():
    """「建议买入」应被拦截"""
    text = _make_valid_report("综合来看，建议买入该基金。")
    ok, errors = validate_report(text)
    assert not ok
    assert any("建议买入" in e for e in errors)


def test_investment_advice_not_blocked_when_in_disclaimer():
    """「不构成任何投资建议」中的「投资建议」不应被误拦截"""
    text = _make_valid_report("本结论不构成任何投资建议，请谨慎。")
    ok, errors = validate_report(text)
    assert ok, f"白名单词汇被误拦截：{errors}"


def test_hallucination_blocked():
    """幻觉词「需投资珍珠」应被拦截"""
    text = _make_valid_report("需投资珍珠，市场风险较高。")
    ok, errors = validate_report(text)
    assert not ok


def test_duplicate_section_blocked():
    """重复章节编号应被拦截"""
    text = "## 四、风险评估\n内容\n## 四、风险评估\n内容\n数据质量说明：OK\n不构成任何投资建议"
    ok, errors = validate_report(text)
    assert not ok
    assert any("重复章节" in e for e in errors)


def test_missing_required_section():
    """缺少「不构成任何投资建议」应被拦截"""
    text = "## 一、数据质量说明\n✅ 数据真实\n## 七、风险提示\n基金有风险。"
    ok, errors = validate_report(text)
    assert not ok
    assert any("不构成任何投资建议" in e for e in errors)


def test_auto_fix_hallucination():
    """auto_fix_report 应自动修复常见幻觉词"""
    text = "需投资珍珠，力算产业链，显着增长。"
    fixed, fixes = auto_fix_report(text)
    assert "珍珠" not in fixed
    assert "算力产业链" in fixed
    assert len(fixes) > 0


def test_auto_fix_traditional_chinese():
    """「显着」应修复为「显著」"""
    text = "该基金表现显着优于同类。"
    fixed, fixes = auto_fix_report(text)
    assert "显著" in fixed


def test_valid_report_passes():
    """合规报告应通过验证"""
    text = _make_valid_report()
    ok, errors = validate_report(text)
    assert ok, f"应通过，实际错误：{errors}"


def test_unreplaced_placeholder_blocked():
    """未替换的占位符应被拦截"""
    text = _make_valid_report("评级：{RATING_PLACEHOLDER}")
    ok, errors = validate_report(text)
    assert not ok
    assert any("占位符" in e for e in errors)
