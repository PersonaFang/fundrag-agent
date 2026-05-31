# backend/output_guard.py
"""
输出质量守卫：拦截禁用词、重复章节、违规建议
🌰 类比：出版前的终审编辑，发现问题直接打回重写
"""

import re
from typing import Optional

# ============================================================
# 禁用词：出现即拦截
# ============================================================
BANNED_PHRASES = [
    # 投资建议类（已替换为适配结论）
    "建议买入", "建议卖出", "强烈推荐", "稳赚", "保本",
    "建议持有", "建议加仓", "值得买入",
    # 幻觉词（中文同音错误）
    "投资珍珠", "需投资珍珠", "中性偏珍珠",
    "死亡风险", "市场回购",
    "可轻松", "轻松的",
    # 无关事件
    "尼泊尔",
    # 非标准金融词汇
    "力算产业链", "加薪计划", "研发加薪",
    # 数据质量过度承诺
    "保证与市场公开信息一致", "数据完全可信", "经验证保证",
]

# 允许出现的近似词（避免误伤）
WHITELIST = ["投资建议", "不构成任何投资建议"]

# 章节编号模式（检测重复）
SECTION_NUM_PATTERN = re.compile(
    r"^#+\s*(一|二|三|四|五|六|七|八|九|十)、",
    re.MULTILINE
)

# 数字范围校验（简单启发式）
SUSPICIOUS_NUMBER_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d{1,2})?)%"
)


def check_banned_phrases(text: str) -> list[str]:
    found = []
    for phrase in BANNED_PHRASES:
        if phrase in text:
            # 检查是否在白名单语境里
            idx = text.index(phrase)
            context = text[max(0, idx - 10):idx + 30]
            is_whitelisted = any(wl in context for wl in WHITELIST)
            if not is_whitelisted:
                found.append(phrase)
    return found


def check_duplicate_sections(text: str) -> list[str]:
    sections   = SECTION_NUM_PATTERN.findall(text)
    seen       = set()
    duplicates = []
    for s in sections:
        if s in seen and s not in duplicates:
            duplicates.append(s)
        seen.add(s)
    return duplicates


def check_required_sections(text: str) -> list[str]:
    required = ["数据质量说明", "风险提示", "不构成任何投资建议"]
    return [r for r in required if r not in text]


def check_unreplaced_placeholders(text: str) -> list[str]:
    """检测未替换的占位符 {xxx}"""
    pattern = re.compile(r"\{[A-Z_a-z]+\}")
    return pattern.findall(text)


def validate_report(text: str) -> tuple[bool, list[str]]:
    """
    返回 (is_valid, error_list)
    is_valid=False 时应阻断报告导出
    """
    errors = []

    banned = check_banned_phrases(text)
    if banned:
        errors.append(f"禁用词：{', '.join(banned)}")

    duplicates = check_duplicate_sections(text)
    if duplicates:
        errors.append(f"重复章节编号：{'、'.join(duplicates)}")

    missing_sections = check_required_sections(text)
    if missing_sections:
        errors.append(f"缺少必要章节：{', '.join(missing_sections)}")

    placeholders = check_unreplaced_placeholders(text)
    if placeholders:
        errors.append(f"未替换占位符：{', '.join(placeholders)}")

    return len(errors) == 0, errors


def auto_fix_report(text: str) -> tuple[str, list[str]]:
    """
    对可以自动修复的问题执行替换
    返回 (修复后文本, 修复记录)
    """
    fixes = []

    # 自动修复同音幻觉词
    auto_fix_map = {
        "需投资珍珠":   "投资需谨慎",
        "投资珍珠":     "投资需谨慎",
        "中性偏珍珠":   "中性偏谨慎",
        "力算产业链":   "算力产业链",
        "研发费用加薪":  "研发费用加计扣除",
        "显着":         "显著",
        "尼泊尔疫情":   "",
        "投资机":       "投资机会",
    }

    for wrong, correct in auto_fix_map.items():
        if wrong in text:
            text = text.replace(wrong, correct)
            fixes.append(f"自动修复：'{wrong}' → '{correct}'")

    return text, fixes
