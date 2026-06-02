# backend/output_guard.py
"""
输出质量守卫 V2.4：报告发布前的最后防线
"""

import re
from typing import Tuple, List
from backend.constants import BANNED_WORDS, ALLOWED_RATINGS, AUTO_FIX_MAP
from backend.value_cleaner import auto_fix_text, scan_banned_words


# ============================================================
# 必要章节清单
# ============================================================
REQUIRED_SECTIONS = [
    "一、数据质量说明",
    "三、核心指标溯源",
    "四、综合评分",
    "八、⚠️ 风险提示",
    "不构成任何投资建议",
    "适配结论：",     # 确保 heading 是「适配结论」而非变体
]


# ============================================================
# 1. 禁用词检测（扩充版，覆盖三轮样本）
# ============================================================

def check_banned_words(text: str) -> list[str]:
    errors = []

    # BANNED_WORDS 集合检测
    found = scan_banned_words(text)
    if found:
        errors.append(f"禁用词：{'、'.join(found)}")

    # ✅ 额外正则检测（三轮样本新发现，不全在 BANNED_WORDS 集合里）
    _EXTRA_PATTERNS = [
        (re.compile(r'现有日期'),                               "「现有日期」应为「截止日期」"),
        (re.compile(r'数据援助'),                               "「数据援助」应为「数据缺失」"),
        (re.compile(r'嘲笑'),                                   "「嘲笑」脏值泄露"),
        (re.compile(r'⬜\s+(?!缺失)\S+'),                       "DataNature 未知值透传"),
        (re.compile(r'显着(?!重)'),                             "「显着」应为「显著」"),
        (re.compile(r'(?:推理|概念|建议|修正|方案|理念|丰田|推断)\s*结论'),
                                                               "非法结论变体"),
        (re.compile(r'运行时间长'),                             "「运行时间长」应为「运行时长」"),
        (re.compile(r'数据相[似同近]'),                         "适合人群文案乱码"),
        (re.compile(r'至少[=＝]恢复'),                          "说明列垃圾文本"),
        (re.compile(r'恢复取消控制'),                           "「恢复取消控制」垃圾文本"),
        (re.compile(r'持仓现场'),                               "「持仓现场」应为「持仓占比」"),
        (re.compile(r'数据比重'),                               "「数据比重」应为「数据截止」"),
        (re.compile(r'模拟（模拟）'),                           "来源列双重 mock 标注"),
        (re.compile(r'\b(?:run_days|history_score|sentiment_score|'
                    r'risk_control_score|alpha_adjustment|confidence_label|'
                    r'total_score|is_mock|fund_code|score_json)\b'),
                                                               "内部字段名泄漏"),
        (re.compile(r'受运行时长约束已'),                       "「受运行时长约束已」语序错误"),
        (re.compile(r'样本模型'),                               "「样本模型」应为「样本受限」"),
        (re.compile(r'推断结论'),                               "「推断结论」应为「适配结论」"),
    ]
    for pattern, desc in _EXTRA_PATTERNS:
        if pattern.search(text):
            errors.append(f"检测到问题：{desc}")

    return errors


def check_banned_phrases(text: str) -> list[str]:
    """旧接口别名"""
    return check_banned_words(text)


# ============================================================
# 2. 非法 heading 检测（扩充，覆盖"推断"）
# ============================================================

def check_heading_variants(text: str) -> list[str]:
    errors = []
    bad_heading_pattern = re.compile(
        r'📌\s*(方案|理念|概念|建议|综合|投资|丰田|修正|改进|推理|推断)\s*结论'
    )
    for m in bad_heading_pattern.finditer(text):
        errors.append(f"非法结论标题：「{m.group(0).strip()}」")
    return errors


# ============================================================
# 3. auto_fix_report（V2.4 完整版）
# ============================================================

def auto_fix_report(text: str) -> Tuple[str, List[str]]:
    """
    自动修复报告文本 V2.4。
    ✅ 规则按长度降序应用，防止短词污染长词
    ✅ 覆盖三轮样本中所有发现的脏词
    """
    fixed = text
    logs  = []

    # ---- Step1：本地优先修复规则（长到短排序）----
    _LOCAL_FIXES = [
        # 表头
        ("| 指标 | 数值 | 数据性质 | 现有日期 | 来源 |",
         "| 指标 | 数值 | 数据性质 | 截止日期 | 来源 |"),
        # 结论 heading 变体（长→短）
        ("📌 推断结论：",           "📌 适配结论："),
        ("📌 推理结论：",           "📌 适配结论："),
        ("📌 概念结论：",           "📌 适配结论："),
        ("📌 建议结论：",           "📌 适配结论："),
        ("📌 修正结论：",           "📌 适配结论："),
        ("📌 方案结论：",           "📌 适配结论："),
        ("📌 理念结论：",           "📌 适配结论："),
        ("📌 丰田结论：",           "📌 适配结论："),
        # Banner 文案
        ("修正结论受运行时长约束已", "适配结论已受运行时长约束"),
        ("受运行时长约束已",         "已受运行时长约束"),
        # 说明列脏值
        ("含运行时间长处罚",         "含运行时长惩罚"),
        ("至少=恢复撤回控制比较好",  "越高表示回撤控制越好"),
        ("至少表示恢复取消控制更好", "越高表示回撤控制越好"),
        ("恢复取消控制更好",         "回撤控制越好"),
        ("恢复撤回控制比较好",       "回撤控制越好"),
        # 来源脏值
        ("嘲笑",                    "mock"),
        ("模拟（模拟）",             "mock"),
        # 数据字段文案
        ("数据援助",                "数据缺失"),
        ("数据比重",                "数据截止"),
        ("数据总量",                "数据截止"),
        ("前十大总量",              "前十大合计"),
        ("前三大总量",              "前三大合计"),
        ("持仓现场",                "持仓占比"),
        ("演示文稿",                "仅供演示"),
        # Badge 文案
        ("推断结论",                "适配结论"),
        ("修正结论",                "适配结论"),
        ("样本模型",                "样本受限"),
        ("未输出正式评级",          "不输出正式评级"),
        # 适合人群乱码
        ("请以官方渠道数据相似",    "请以官方渠道数据为准"),
        ("请以官方渠道数据相同",    "请以官方渠道数据为准"),
        ("基金数据建议不足，仅建议观察，不基于短期表现配置",
         "基金数据不足，仅建议观察，不建议基于短期表现配置"),
    ]

    for bad, good in _LOCAL_FIXES:
        if bad in fixed:
            fixed = fixed.replace(bad, good)
            logs.append(f"local_fix: 「{bad[:20]}」→「{good[:20]}」")

    # ---- Step2：AUTO_FIX_MAP（长度降序）----
    for bad, good in sorted(AUTO_FIX_MAP.items(), key=lambda x: -len(x[0])):
        if bad in fixed:
            fixed = fixed.replace(bad, good)
            logs.append(f"auto_fix: 「{bad}」→「{good}」")

    # ---- Step3：正则修复 ----
    new_fixed = re.sub(r'显着(?!重)', '显著', fixed)
    if new_fixed != fixed:
        logs.append("auto_fix: 「显着」→「显著」")
        fixed = new_fixed

    new_fixed = re.sub(
        r'📌\s*(方案|理念|概念|建议|综合|投资|丰田|修正|改进|推理|推断)\s*结论',
        '📌 适配结论',
        fixed
    )
    if new_fixed != fixed:
        logs.append("auto_fix: 非法结论标题 → 「📌 适配结论」")
        fixed = new_fixed

    # DataNature 透传脏值（"⬜ X" 其中 X 不是"缺失"）
    new_fixed = re.sub(r'⬜\s+(?!缺失)(\S+)', '⬜ 缺失', fixed)
    if new_fixed != fixed:
        logs.append("auto_fix: DataNature 未知值 → 「⬜ 缺失」")
        fixed = new_fixed

    # ---- Step4：内部字段名清除 ----
    field_pattern = re.compile(
        r'\b(run_days|history_score|sentiment_score|risk_control_score|'
        r'alpha_adjustment|confidence_label|total_score|is_mock|'
        r'fund_code|score_json|snapshot_json)\b'
        r'[为是=：:\s]*[\d\w\.None]*'
    )
    new_fixed = field_pattern.sub('[数据项]', fixed)
    if new_fixed != fixed:
        logs.append("auto_fix: 内部字段名 → 「[数据项]」")
        fixed = new_fixed

    return fixed, logs


# ============================================================
# 4. validate_report
# ============================================================

def check_mock_score_conflict(text: str) -> list[str]:
    """检测：含模拟数据时不得显示高置信度或正式综合得分"""
    errors = []
    has_mock     = "🔴 模拟" in text or ("mock" in text.lower() and "模拟" in text)
    has_high_conf = "置信度：高" in text or "置信度:高" in text
    has_formal_score = bool(re.search(
        r'综合得分\s*[|｜]\s*\d+(?:\.\d+)?(?!\s*不计算)',
        text
    ))
    if has_mock and has_high_conf:
        errors.append("含模拟数据时不得显示「置信度：高」")
    if has_mock and has_formal_score:
        errors.append("含核心模拟数据时不得显示正式综合得分数字")
    return errors


def validate_report(text: str) -> tuple[bool, list[str]]:
    errors = []
    errors.extend(check_banned_words(text))
    errors.extend(check_heading_variants(text))
    errors.extend(check_mock_score_conflict(text))

    # 必要章节检查
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    if missing:
        errors.append(f"缺少必要章节：{'、'.join(missing)}")

    # 重复章节
    section_nums = re.findall(r'^#{1,3}\s*(一|二|三|四|五|六|七|八|九|十)[、.]', text, re.M)
    seen, dups = set(), []
    for n in section_nums:
        if n in seen and n not in dups:
            dups.append(f"重复章节「{n}」")
        seen.add(n)
    errors.extend(dups)

    # 未替换占位符
    placeholders = re.findall(r'\{[A-Z_]{3,}\}', text)
    errors.extend([f"未替换占位符：{p}" for p in placeholders])

    return len(errors) == 0, errors


def fix_and_validate(text: str) -> tuple[str, bool, list[str]]:
    fixed_text, fix_log = auto_fix_report(text)
    if fix_log:
        print(f"  🔧 output_guard 自动修复 {len(fix_log)} 处")
    is_valid, errors = validate_report(fixed_text)
    return fixed_text, is_valid, errors
