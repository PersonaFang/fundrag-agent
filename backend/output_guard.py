# backend/output_guard.py
"""
输出质量守卫：报告发布前的最后防线
🌰 类比：出版审查员，任何不合格内容直接打回
"""

import re
from backend.constants import (
    BANNED_WORDS, ALLOWED_RATINGS, ALLOWED_SOURCES,
    ALLOWED_CONFIDENCE
)
from backend.value_cleaner import auto_fix_text, scan_banned_words


# ============================================================
# 1. 禁用词检测
# ============================================================
def check_banned_words(text: str) -> list[str]:
    return scan_banned_words(text)


# 旧接口别名（兼容现有测试）
def check_banned_phrases(text: str) -> list[str]:
    return check_banned_words(text)


# ============================================================
# 2. 评级枚举校验（检测报告中的评级文本是否合法）
# ============================================================
RATING_PATTERNS = [
    re.compile(r'适配结论[：:]\s*\**([^\n*]{1,10})\**'),
    re.compile(r'建议结论[：:]\s*\**([^\n*]{1,10})\**'),
    re.compile(r'评级[：:]\s*\**([^\n*]{1,10})\**'),
    re.compile(r'📌\s*([^\n]{1,10})'),
]


def check_illegal_ratings(text: str) -> list[str]:
    errors = []
    for pattern in RATING_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(1).strip().strip('*').strip('"').strip('\u201c').strip('\u201d').strip()
            # 只取第一个词（防止匹配到说明文字）
            first_word = value.split()[0] if value.split() else value
            if first_word and first_word not in ALLOWED_RATINGS:
                # 排除已知合法前缀
                if not any(r in value for r in ALLOWED_RATINGS):
                    errors.append(f"非法评级文本：'{value}'（来自：{pattern.pattern[:20]}...）")
    return errors


# ============================================================
# 3. 模拟数据 + 高置信度/正式评分 矛盾检测
# ============================================================
def check_mock_score_conflict(text: str) -> list[str]:
    errors = []
    has_mock = "🔴 模拟" in text or "mock" in text.lower()
    has_high_conf = "置信度：高" in text or "置信度:高" in text
    # 检测是否出现了像 "综合得分 | 7.1" 这样的正式评分行
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
    (re.compile(r'市场风\s*\n'),          "「市场风」后句子残缺"),
    (re.compile(r'\bdat\b'),              "变量名「dat」泄露到报告"),
    (re.compile(r'基金运行时间长'),        "「基金运行时间长」字段名错字"),
    (re.compile(r'不投资输出评级'),        "「不投资输出评级」语序错误"),
    (re.compile(r'表面\s+上并不'),         "「表面 上并不」断句污染"),
    (re.compile(r'另一——'),               "「另一——」断句残缺"),
    (re.compile(r'根据JSON数据'),          "「根据JSON数据」技术术语外漏"),
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
REQUIRED_SECTIONS = [
    "数据质量说明",
    "核心指标溯源",
    "综合评分",
    "风险提示",
    "不构成任何投资建议",
]


def check_required_sections(text: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s not in text]


# ============================================================
# 6. 重复章节检测
# ============================================================
SECTION_PATTERN = re.compile(
    r'^#{1,3}\s*(一|二|三|四|五|六|七|八|九|十)[、.]',
    re.MULTILINE
)


def check_duplicate_sections(text: str) -> list[str]:
    nums   = SECTION_PATTERN.findall(text)
    seen   = set()
    dups   = []
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
# 8. 结论标题变体检测（V2.1 新增）
# ============================================================
def check_heading_variants(text: str) -> list[str]:
    """
    检测「📌适配结论」heading 被 LLM 替换为其他词的情况
    合法：「📌 适配结论：...」
    非法：「📌方案结论」「📌理念结论」「📌概念结论」「📌建议结论」「📌丰田结论」
    """
    errors = []
    bad_heading_pattern = re.compile(
        r'📌\s*(方案|理念|概念|建议|综合|投资|丰田)\s*结论'
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
    is_valid=False 时应阻断报告导出
    """
    errors = []

    banned = check_banned_words(text)
    if banned:
        errors.append(f"禁用词：{'、'.join(banned)}")

    errors.extend(check_illegal_ratings(text))
    errors.extend(check_mock_score_conflict(text))
    errors.extend(check_broken_phrases(text))
    errors.extend(check_duplicate_sections(text))
    errors.extend(check_heading_variants(text))

    placeholders = check_unreplaced_placeholders(text)
    if placeholders:
        errors.extend(placeholders)

    missing = check_required_sections(text)
    if missing:
        errors.append(f"缺少必要章节：{'、'.join(missing)}")

    return len(errors) == 0, errors


def auto_fix_report(text: str) -> tuple[str, list[str]]:
    """
    自动修复报告（兼容旧接口名）
    返回 (修复后文本, 修复记录列表)
    """
    return auto_fix_text(text)


def fix_and_validate(text: str) -> tuple[str, bool, list[str]]:
    """
    先自动修复，再校验
    返回 (修复后文本, is_valid, remaining_errors)
    """
    fixed_text, fix_log = auto_fix_text(text)
    if fix_log:
        print(f"  🔧 output_guard 自动修复 {len(fix_log)} 处：{fix_log[:3]}...")

    is_valid, errors = validate_report(fixed_text)
    return fixed_text, is_valid, errors
