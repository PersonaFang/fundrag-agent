# backend/benchmark.py
"""
基准指数获取：计算超额收益（Alpha）
🌰 类比：不只看考了多少分，还要看班级平均分，算出「超额分数」
"""

import akshare as ak
import pandas as pd
from datetime import date
from typing import Optional
from backend.schemas import MetricSource

# 基金类型 → 基准指数映射
BENCHMARK_MAP = {
    "股票型":   ("沪深300",   "000300"),
    "混合型":   ("沪深300",   "000300"),
    "指数型":   ("沪深300",   "000300"),
    "QDII":    ("纳斯达克",   "IXIC"),
    "债券型":   ("中债综合",   "H11001"),
    "货币型":   ("余额宝",     None),      # 无基准
    "科技主题": ("创业板指",   "399006"),
    "消费主题": ("消费指数",   "000932"),
    "半导体":   ("半导体指数", "931127"),
}


def get_benchmark_return(
    fund_type:      str,
    inception_date: date,
    report_date:    date,
    fund_code:      str = "",
) -> tuple[Optional[MetricSource], str]:
    """
    获取同期基准收益率
    返回 (MetricSource, 基准名称)
    """
    # 根据基金类型选择基准
    bench_info = None
    for key, val in BENCHMARK_MAP.items():
        if key in (fund_type or ""):
            bench_info = val
            break

    if bench_info is None:
        bench_info = ("沪深300", "000300")   # 默认

    bench_name, bench_code = bench_info

    if bench_code is None:
        return None, bench_name

    try:
        # 尝试获取 A 股指数数据
        if bench_code.startswith(("0", "3", "9")):
            prefix = "sh" if bench_code.startswith("0") else "sz"
            df = ak.stock_zh_index_daily(symbol=f"{prefix}{bench_code}")
        else:
            # 海外指数（QDII）降级处理
            df = None

        if df is None or df.empty:
            return _mock_benchmark(bench_name, fund_type), bench_name

        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= pd.Timestamp(inception_date)) &
                (df["date"] <= pd.Timestamp(report_date))]

        if len(df) < 5:
            return _mock_benchmark(bench_name, fund_type), bench_name

        close_col = next((c for c in ["close", "收盘"] if c in df.columns), df.columns[-1])
        start_val = df[close_col].iloc[0]
        end_val   = df[close_col].iloc[-1]
        ret_pct   = round((end_val - start_val) / start_val * 100, 2)

        return MetricSource(
            value=ret_pct,
            unit="%",
            source="akshare",
            endpoint="stock_zh_index_daily",
            as_of=report_date,
            is_mock=False,
            note=f"基准：{bench_name}（{bench_code}），区间：{inception_date}~{report_date}"
        ), bench_name

    except Exception as e:
        print(f"⚠️ 基准数据获取失败：{e}")
        return _mock_benchmark(bench_name, fund_type), bench_name


def _mock_benchmark(bench_name: str, fund_type: str) -> MetricSource:
    """模拟基准数据"""
    mock_returns = {
        "沪深300": 25.0, "创业板指": 45.0, "纳斯达克": 80.0,
        "消费指数": 15.0, "半导体指数": 60.0, "中债综合": 5.0,
    }
    val = mock_returns.get(bench_name, 20.0)
    return MetricSource(
        value=val, unit="%", source="mock",
        is_mock=True, note="模拟基准收益，仅供演示"
    )
