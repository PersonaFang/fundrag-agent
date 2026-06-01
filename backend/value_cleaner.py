# backend/value_cleaner.py
"""
值清洗器：在数据进入系统前统一清洗
🌰 类比：食材进厨房前先洗干净，不干净的直接丢弃
"""

from backend.constants import (
    ALLOWED_SOURCES, DIRTY_SOURCE_MAP,
    ALLOWED_RATINGS, AUTO_FIX_MAP, BANNED_WORDS
)
from typing import Optional

# 被认为是"缺失"的字符串值
MISSING_STRING_VALUES = frozenset({
    "", "N/A", "na", "null", "none", "None",
    "--", "—", "数据援助", "暂无", "未知",
    "-", "NaN", "nan",
})


def clean_value(value) -> Optional[float | int | str]:
    """
    清洗单个值，统一缺失值为 None
    """
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if v.lower() in {s.lower() for s in MISSING_STRING_VALUES}:
            return None
        return v
    if isinstance(value, float):
        import math
        if math.isnan(value) or math.isinf(value):
            return None
    return value


def normalize_source(source: str | None, allow_warning: bool = True) -> str:
    """
    标准化 source 字段
    脏值自动映射，未知值报错
    """
    if not source:
        return "missing"

    source = source.strip()

    # 自动修复脏值
    if source in DIRTY_SOURCE_MAP:
        clean = DIRTY_SOURCE_MAP[source]
        if allow_warning:
            print(f"⚠️ source 字段自动修复：'{source}' → '{clean}'")
        return clean

    if source not in ALLOWED_SOURCES:
        raise ValueError(
            f"非法 source 值：'{source}'，"
            f"允许的值：{sorted(ALLOWED_SOURCES)}"
        )
    return source


def normalize_rating(rating: str | None) -> str:
    """
    校验评级合法性，非法评级返回"无法评级"
    """
    if not rating:
        return "无法评级"

    rating = rating.strip()

    # 自动修复已知的非法评级
    illegal_to_valid = {
        "吞":   "无法评级",
        "缓解": "风险较高",
        "建议买入": "谨慎关注",
        "建议卖出": "风险较高",
        "强烈推荐": "谨慎关注",
        "中性持有": "谨慎关注",
    }
    if rating in illegal_to_valid:
        mapped = illegal_to_valid[rating]
        print(f"⚠️ 非法评级自动修复：'{rating}' → '{mapped}'")
        return mapped

    if rating not in ALLOWED_RATINGS:
        print(f"⚠️ 未知评级 '{rating}'，返回 '无法评级'")
        return "无法评级"

    return rating


def clean_manager_name(raw: str | None) -> list[str]:
    """
    清洗基金经理姓名字段
    修复「俞（瑶从业4.6年）」→「俞瑶」这类截断问题
    修复「刘单独杰」→「刘杰」这类LLM重组错误
    """
    if not raw:
        return []

    import re

    # Step1: 去除括号内容（括号里是职称/经验年限，不是姓名的一部分）
    cleaned = re.sub(r'（[^）]{0,20}）', '', raw)  # 全角括号
    cleaned = re.sub(r'\([^)]{0,20}\)', '', cleaned)  # 半角括号

    # Step2: 按分隔符分割
    parts = re.split(r'[\n，,、\s/／\\|]+', cleaned.strip())

    # Step3: 过滤无效项（长度<2 或 >5 的不像中文姓名）
    names = []
    for p in parts:
        p = p.strip()
        if 2 <= len(p) <= 5:
            # 检查是否全是中文字符
            if re.match(r'^[\u4e00-\u9fff]+$', p):
                names.append(p)

    return names


def auto_fix_text(text: str) -> tuple[str, list[str]]:
    """
    对报告文本执行自动修复
    返回 (修复后文本, 修复记录列表)
    """
    fixes = []
    for wrong, correct in AUTO_FIX_MAP.items():
        if wrong in text:
            text = text.replace(wrong, correct)
            fixes.append(f"'{wrong}' → '{correct}'")
    return text, fixes


def scan_banned_words(text: str) -> list[str]:
    """
    扫描文本中的禁用词
    返回找到的禁用词列表
    """
    found = []
    for word in BANNED_WORDS:
        if word in text:
            found.append(word)
    return found
