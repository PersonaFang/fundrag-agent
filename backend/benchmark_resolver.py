# backend/benchmark_resolver.py
"""
基准指数解析器：根据基金名称和类型确定正确的基准
🌰 类比：白酒基金的竞争对手是白酒指数，不是沪深300
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class BenchmarkInfo:
    name:         Optional[str]  # 基准名称
    code:         Optional[str]  # 基准代码（用于行情查询）
    source:       str = "missing"
    is_matched:   bool = False
    match_method: str = ""       # 匹配方式说明
    mismatch_warning: Optional[str] = None


# 优先级从高到低的匹配规则
# 格式：(关键词列表, 基准名称, 基准代码)
BENCHMARK_RULES = [
    # QDII / 海外指数
    (["纳斯达克100", "NASDAQ100", "Nasdaq100", "纳指100"],
     "纳斯达克100指数", ".NDX"),
    (["纳斯达克", "NASDAQ", "Nasdaq", "纳指"],
     "纳斯达克综合指数", ".IXIC"),
    (["标普500", "S&P500", "SP500"],
     "标普500指数", ".SPX"),
    (["恒生科技", "恒科"],
     "恒生科技指数", "HSTECH"),
    (["恒生", "H股"],
     "恒生指数", "HSI"),

    # 主题指数
    (["中证白酒", "白酒"],
     "中证白酒指数", "399997"),
    (["中证消费", "消费"],
     "中证消费指数", "000932"),
    (["半导体", "芯片"],
     "中证半导体指数", "931127"),
    (["创业板人工智能", "创业板AI"],
     "创业板人工智能主题指数", "399673"),
    (["人工智能", "AI指数"],
     "中证人工智能指数", "930713"),
    (["新能源车", "新能源汽车"],
     "中证新能源汽车指数", "930955"),
    (["光伏", "太阳能"],
     "中证光伏产业指数", "931151"),
    (["医药", "生物医药"],
     "中证医药指数", "000933"),

    # 宽基指数
    (["沪深300", "300ETF"],
     "沪深300指数", "000300"),
    (["中证500", "500ETF"],
     "中证500指数", "000905"),
    (["中证1000"],
     "中证1000指数", "000852"),
    (["创业板"],
     "创业板指数", "399006"),
    (["科创板", "科创50"],
     "科创50指数", "000688"),
    (["上证50"],
     "上证50指数", "000016"),
]

# 基金类型 → 默认基准
TYPE_DEFAULT_BENCHMARK = {
    "QDII":  ("纳斯达克综合指数", ".IXIC"),    # QDII 默认纳指（仍需人工确认）
    "股票型": ("沪深300指数",     "000300"),
    "混合型": ("沪深300指数",     "000300"),
    "指数型": ("沪深300指数",     "000300"),
    "债券型": ("中债综合指数",    "H11001"),
    "货币型": (None, None),                   # 货币基金无基准
}


def resolve_benchmark(
    fund_name:           str,
    fund_type:           Optional[str] = None,
    declared_benchmark:  Optional[str] = None,
) -> BenchmarkInfo:
    """
    解析基金真实基准指数

    优先级：
    1. 基金名称关键词匹配（最准确）
    2. 声明基准（次之）
    3. 基金类型默认（最不准确，会标注警告）
    """
    fund_name = fund_name or ""

    # ---- Step 1: 基金名称关键词匹配 ----
    for keywords, bench_name, bench_code in BENCHMARK_RULES:
        for kw in keywords:
            if kw in fund_name:
                # 检查是否与声明基准冲突
                mismatch = None
                if declared_benchmark and bench_name not in declared_benchmark:
                    mismatch = (
                        f"基金名称匹配到「{bench_name}」，"
                        f"但声明基准为「{declared_benchmark}」，"
                        "请以官方文件为准"
                    )
                return BenchmarkInfo(
                    name=bench_name,
                    code=bench_code,
                    source="calculated",
                    is_matched=True,
                    match_method=f"基金名称含关键词「{kw}」",
                    mismatch_warning=mismatch,
                )

    # ---- Step 2: 使用声明基准 ----
    if declared_benchmark and declared_benchmark not in {"未知", "无", ""}:
        # 验证声明基准是否在规则里
        for keywords, bench_name, bench_code in BENCHMARK_RULES:
            if any(kw in declared_benchmark for kw in keywords):
                return BenchmarkInfo(
                    name=bench_name,
                    code=bench_code,
                    source="akshare",
                    is_matched=True,
                    match_method="使用数据源声明基准",
                )
        # 声明基准无法识别
        return BenchmarkInfo(
            name=declared_benchmark,
            code=None,
            source="akshare",
            is_matched=False,
            match_method="声明基准（无法识别具体指数代码）",
            mismatch_warning="声明基准无法匹配到已知指数，Alpha 计算可能不准确",
        )

    # ---- Step 3: 类型默认（最低优先级，需警告）----
    if fund_type and fund_type in TYPE_DEFAULT_BENCHMARK:
        default_name, default_code = TYPE_DEFAULT_BENCHMARK[fund_type]
        if default_name is None:
            return BenchmarkInfo(
                name=None, code=None, source="missing",
                is_matched=False,
                match_method="货币基金无基准",
            )
        return BenchmarkInfo(
            name=default_name,
            code=default_code,
            source="calculated",
            is_matched=False,
            match_method=f"基金类型「{fund_type}」默认基准",
            mismatch_warning=(
                f"使用类型默认基准「{default_name}」，"
                "可能与该基金实际基准不符，Alpha 仅供参考"
            ),
        )

    # ---- 无法确定 ----
    return BenchmarkInfo(
        name=None, code=None, source="missing",
        is_matched=False,
        match_method="无法识别基准",
        mismatch_warning="基准指数未知，不计算 Alpha",
    )
