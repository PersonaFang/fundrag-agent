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
    对报告文本执行自动修复。
    Step1: 应用 AUTO_FIX_MAP
    Step2: 独立正则修复（不依赖 AUTO_FIX_MAP 完整性）
    返回 (修复后文本, 修复记录列表)
    """
    import re
    fixes = []

    # Step1: 应用 AUTO_FIX_MAP
    for wrong, correct in AUTO_FIX_MAP.items():
        if wrong in text:
            text = text.replace(wrong, correct)
            fixes.append(f"'{wrong}' → '{correct}'")

    # Step2: 独立正则修复
    # 修复"显着"→"显著"（避免误替换"显着重"）
    new = re.sub(r'显着(?!重)', '显著', text)
    if new != text:
        fixes.append("'显着' → '显著'")
        text = new

    # 修复"阿尔法"→"Alpha"
    new = text.replace("阿尔法调整", "Alpha 调整").replace("阿尔法", "Alpha")
    if new != text:
        fixes.append("'阿尔法' → 'Alpha'")
        text = new

    # 修复非法结论标题
    new = re.sub(
        r'📌\s*(方案|理念|概念|建议|综合|投资|丰田|修正|改进)\s*结论',
        '📌 适配结论',
        text
    )
    if new != text:
        fixes.append("非法结论标题 → '📌 适配结论'")
        text = new

    # 修复 Banner 语序
    new = text.replace("约束已。", "约束。").replace(
        "修正结论受运行时长约束已", "适配结论已受运行时长约束"
    )
    if new != text:
        fixes.append("Banner 语序修正")
        text = new

    return text, fixes


def normalize_rating(rating: str | None) -> str:
    """
    校验评级合法性，非法评级返回"无法评级"
    ✅ V1.7 扩展：覆盖"建议结论"/"修正结论"等变体
    """
    if not rating:
        return "无法评级"

    rating = rating.strip().strip('*「」【】"\'')

    if rating in ALLOWED_RATINGS:
        return rating

    # 扩展变体映射
    _VARIANTS = {
        "吞":          "无法评级",
        "缓解":        "风险较高",
        "建议买入":    "谨慎关注",
        "建议卖出":    "风险较高",
        "强烈推荐":    "谨慎关注",
        "中性持有":    "谨慎关注",
        # 常见近义词
        "建议配置":    "适合配置",
        "可以配置":    "适合配置",
        "谨慎":        "谨慎关注",
        "观察":        "持续观察",
        "数据不足":    "信息不足",
        "高风险":      "风险较高",
        # 非法标题变体（出现在评级字段里）
        "建议结论":    "无法评级",
        "修正结论":    "无法评级",
        "理念结论":    "无法评级",
        "概念结论":    "无法评级",
        "丰田结论":    "无法评级",
    }

    for key, val in _VARIANTS.items():
        if key in rating:
            print(f"⚠️ 非法评级自动修复：'{rating}' → '{val}'")
            return val

    print(f"⚠️ 未知评级 '{rating}'，返回 '无法评级'")
    return "无法评级"


def scan_banned_words(text: str) -> list[str]:
    """
    扫描文本中的禁用词。
    ✅ V1.7：新增「显着」错别字检测
    返回找到的禁用词列表
    """
    import re
    found = []
    for word in BANNED_WORDS:
        if word in text:
            found.append(word)
    # 额外检测「显着」错别字
    if re.search(r'显着(?!重)', text):
        found.append("显着（错别字）")
    return found
