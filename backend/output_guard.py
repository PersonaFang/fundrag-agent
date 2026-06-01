# backend/output_guard.py
"""
输出质量守卫：报告发布前的最后防线
V2.2 修复：
- check_banned_words(): 新增「显着」错别字检测
- check_heading_variants(): 覆盖「建议结论」「修正」等更多变体
- auto_fix_report(): 真正应用 AUTO_FIX_MAP + 修复「显着」 + 修复非法结论标题
- validate_report(): 调用 check_heading_variants()
"""

import re
from typing import Tuple, List
from backend.constants import (
    BANNED_WORDS, ALLOWED_RATINGS, ALLOWED_SOURCES,
    ALLOWED_CONFIDENCE, AUTO_FIX_MAP
)
from backend.value_cleaner import auto_fix_text, scan_banned_words


# ============================================================
# 必要章节清单（V2.2 更新：用编号前缀，匹配模板实际输出）
# ============================================================
REQUIRED_SECTIONS = [
    "一、数据质量说明",
    "三、核心指标溯源",
    "四、综合评分",
    "八、⚠️ 风险提示",
    "不构成任何投资建议",   # 免责声明文字必须出现
]


# ============================================================
# 1. 禁用词检测
# ============================================================
def check_banned_words(text: str) -> list[str]:
    """
    检测禁用词 + 错别字。
    ✅ V2.2：新增「显着」错别字检测
    """
    errors = []
    # BANNED_WORDS 集合检测
    found = scan_banned_words(text)
    if found:
        errors.append(f"禁用词：{'、'.join(found)}")

    # ✅ 额外检测「显着」错别字
    if re.search(r'显着(?!重)', text):
        errors.append("错别字：「显着」应为「显著」")

    return errors


# 旧接口别名（兼容）
def check_banned_phrases(text: str) -> list[str]:
    return check_banned_words(text)


# ============================================================
# 2. 评级枚举校验
# ============================================================
RATING_PATTERNS = [
    re.compile(r'适配结论[：:]\s*\**([^\n*]{1,10})\**'),
    re.compile(r'建议结论[：:]\s*\**([^\n*]{1,10})\**'),
    re.compile(r'评级[：:]\s*\**([^\n*]{1,10})\**'),
]


def check_illegal_ratings(text: str) -> list[str]:
    errors = []
    for pattern in RATING_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(1).strip().strip('*').strip('"').strip('“').strip('”').strip()
            first_word = value.split()[0] if value.split() else value
            if first_word and first_word not in ALLOWED_RATINGS:
                if not any(r in value for r in ALLOWED_RATINGS):
                    errors.append(f"非法评级文本：'{value}'")
    return errors


# ============================================================
# 3. 模拟数据 + 高置信度 矛盾检测
# ============================================================
def check_mock_score_conflict(text: str) -> list[str]:
    errors = []
    has_mock = "🔴 模拟" in text or "mock" in text.lower()
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


# ============================================================
# 4. 残缺句式检测
# ============================================================
BROKEN_PATTERNS = [
    (re.compile(r'市场风\s*\n'),           "「市场风」后句子残缺"),
    (re.compile(r'\bdat\b'),               "变量名「dat」泄露到报告"),
    (re.compile(r'基金运行时间长'),         "「基金运行时间长」字段名错字"),
    (re.compile(r'不投资输出评级'),         "「不投资输出评级」语序错误"),
    (re.compile(r'表面\s+上并不'),          "「表面 上并不」断句污染"),
    (re.compile(r'另一——'),                "「另一——」断句残缺"),
    (re.compile(r'根据JSON数据'),           "「根据JSON数据」技术术语外漏"),
    (re.compile(r'is_mock|is_new_fund|fund_code|score_json'), "内部字段名外漏"),
]


def check_broken_phrases(text: str) -> list[str]:
    errors = []
    for pattern, desc in BROKEN_PATTERNS:
        if pattern.search(text):
            errors.append(f"疑似残缺/污染文本：{desc}")
    return errors


# ============================================================
# 5. 必要章节检测
# ============================================================
def check_required_sections(text: str) -> list[str]:
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    if missing:
        return [f"缺少必要章节：{'、'.join(missing)}"]
    return []


# ============================================================
# 6. 重复章节检测
# ============================================================
SECTION_PATTERN = re.compile(
    r'^#{1,3}\s*(一|二|三|四|五|六|七|八|九|十)[、.]',
    re.MULTILINE
)


def check_duplicate_sections(text: str) -> list[str]:
    nums  = SECTION_PATTERN.findall(text)
    seen  = set()
    dups  = []
    for n in nums:
        if n in seen and n not in dups:
            dups.append(f"重复章节编号「{n}」")
        seen.add(n)
    return dups


# ============================================================
# 7. 未替换占位符检测
# ============================================================
PLACEHOLDER_PATTERN = re.compile(r'\{[A-Z_]{3,}\}')


def check_unreplaced_placeholders(text: str) -> list[str]:
    found = PLACEHOLDER_PATTERN.findall(text)
    return [f"未替换占位符：{p}" for p in found]


# ============================================================
# 8. 非法结论标题检测（V2.1 新增，V2.2 扩展）
# ============================================================
def check_heading_variants(text: str) -> list[str]:
    """
    检测「📌适配结论」heading 被替换为非法变体。
    ✅ V2.2：覆盖「建议结论」「修正结论」「改进结论」等更多变体
    """
    errors = []
    bad_heading_pattern = re.compile(
        r'📌\s*(方案|理念|概念|建议|综合|投资|丰田|修正|改进)\s*结论'
    )
    for m in bad_heading_pattern.finditer(text):
        errors.append(f"非法结论标题：「{m.group(0).strip()}」，应为「📌 适配结论」")
    return errors


# ============================================================
# 主校验函数
# ============================================================
def validate_report(text: str) -> tuple[bool, list[str]]:
    """
    全量校验报告文本
    返回 (is_valid, error_list)
    """
    errors = []

    banned = check_banned_words(text)
    errors.extend(banned)

    errors.extend(check_illegal_ratings(text))
    errors.extend(check_mock_score_conflict(text))
    errors.extend(check_broken_phrases(text))
    errors.extend(check_duplicate_sections(text))
    errors.extend(check_heading_variants(text))

    placeholders = check_unreplaced_placeholders(text)
    errors.extend(placeholders)

    errors.extend(check_required_sections(text))

    return len(errors) == 0, errors


# ============================================================
# 自动修复函数
# ============================================================
def auto_fix_report(text: str) -> Tuple[str, List[str]]:
    """
    自动修复报告文本：
    1. 应用 AUTO_FIX_MAP
    2. 修复「显着」→「显著」
    3. 修复非法结论标题 → 「📌 适配结论」
    返回 (修复后文本, 修复记录列表)
    """
    fixed = text
    logs  = []

    # 应用 AUTO_FIX_MAP
    for bad, good in AUTO_FIX_MAP.items():
        if bad in fixed:
            fixed = fixed.replace(bad, good)
            logs.append(f"auto_fix: 「{bad}」→「{good}」")

    # ✅ 修复「显着」→「显著」（正则，避免误替换「显着重」）
    new_fixed = re.sub(r'显着(?!重)', '显著', fixed)
    if new_fixed != fixed:
        logs.append("auto_fix: 「显着」→「显著」")
        fixed = new_fixed

    # 修复非法结论标题
    new_fixed = re.sub(
        r'📌\s*(方案|理念|概念|建议|综合|投资|丰田|修正|改进)\s*结论',
        '📌 适配结论',
        fixed
    )
    if new_fixed != fixed:
        logs.append("auto_fix: 非法结论标题 → 「📌 适配结论」")
        fixed = new_fixed

    return fixed, logs


def fix_and_validate(text: str) -> tuple[str, bool, list[str]]:
    """先自动修复，再校验"""
    fixed_text, fix_log = auto_fix_report(text)
    if fix_log:
        print(f"  🔧 output_guard 自动修复 {len(fix_log)} 处")
    is_valid, errors = validate_report(fixed_text)
    return fixed_text, is_valid, errors
