# backend/data_fetcher.py
"""
数据获取模块
🌰 类比：就像「数据采购员」
         从不同渠道（基金公司、新闻网站、行情平台）
         收集原材料，供后续 Agent 分析使用

补充决策：
- 缓存策略：基本信息 24h，业绩数据 1h，经理信息 6h
- 缓存文件命名：cache/fund_{code}_{type}.json
- akshare 不可用时全部返回 mock 数据，保证系统可用性
"""

import os
import re
import json
import time
import random
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# akshare：专门抓取中国金融数据的神器，完全免费！
# 🌰 类比：天猫超市，各种金融数据应有尽有，拿来即用
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("⚠️  akshare 未安装，使用模拟数据")


# ============ 缓存工具函数 ============

def _get_cache_path(fund_code: str, data_type: str) -> str:
    """
    生成缓存文件路径
    🌰 类比：给每份「食材」贴标签、放入专属格子
    """
    os.makedirs("cache", exist_ok=True)
    return f"cache/fund_{fund_code}_{data_type}.json"


def _load_cache(cache_path: str, max_age_seconds: int) -> Optional[Dict]:
    """
    读取缓存，如果文件不存在或已过期则返回 None
    🌰 类比：检查冰箱里的食材是否还在保质期内
    """
    if not os.path.exists(cache_path):
        return None
    file_age = time.time() - os.path.getmtime(cache_path)
    if file_age > max_age_seconds:
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(cache_path: str, data: Dict) -> None:
    """
    将数据写入缓存文件
    🌰 类比：把新鲜食材放进冰箱保存
    """
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  缓存写入失败：{e}")


# ============ 核心数据获取函数 ============

def get_fund_basic_info(fund_code: str) -> Dict:
    """
    获取基金基本信息

    参数:
        fund_code: 基金代码，例如 "000001"（华夏成长混合）

    返回:
        包含基金名称、类型、规模、基金经理、成立日期等信息的字典

    🌰 例子：
        输入: "110022"（易方达消费行业股票）
        输出: {
            "name": "易方达消费行业股票",
            "type": "股票型",
            "size": "45.32亿",
            "manager": "萧楠",
            "establish_date": "2010-08-20"
        }

    缓存策略：24 小时，基金基本信息变动极少
    """
    cache_path = _get_cache_path(fund_code, "basic")
    cached = _load_cache(cache_path, max_age_seconds=86400)  # 24h
    if cached:
        print(f"📂 使用缓存数据（基本信息）：{fund_code}")
        return cached

    if not AKSHARE_AVAILABLE:
        return _mock_fund_basic(fund_code)

    try:
        # akshare 获取基金基本信息
        # 返回的是 DataFrame，列为 ['item', 'value']，需先转为 dict
        # 🌰 就像去「基金公司官网」查基本资料
        fund_info_df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        fund_info = dict(zip(fund_info_df["item"], fund_info_df["value"]))

        # 基金类型原始值可能含 "-"（如「股票型-普通股票」），取 "-" 前半段
        raw_type = str(fund_info.get("基金类型", "混合型"))
        clean_type = raw_type.split("-")[0].strip()

        result = {
            "fund_code": fund_code,
            "name": str(fund_info.get("基金全称", fund_info.get("基金名称", f"基金{fund_code}"))),
            "type": clean_type,
            "size": str(fund_info.get("基金规模", fund_info.get("最新规模", "未知"))),
            "manager": str(fund_info.get("基金经理", "未知")),
            "establish_date": str(fund_info.get("成立时间", "未知")),
            "company": str(fund_info.get("基金公司", "未知")),
            "data_source": "akshare"
        }

        _save_cache(cache_path, result)
        print(f"✅ 基金基本信息获取成功：{result['name']}")
        return result

    except Exception as e:
        print(f"⚠️  akshare 获取基本信息失败，使用模拟数据：{e}")
        return _mock_fund_basic(fund_code)


def get_fund_performance(fund_code: str, years: int = 3) -> Dict:
    """
    获取基金历史业绩数据，自动检测实际运行时长并修正时间标签。

    参数:
        fund_code: 基金代码
        years: 期望查询年数（实际返回的 actual_period_label 以真实运行时长为准）

    新增返回字段：
        actual_days:         实际运行天数
        actual_period_label: 正确的时间区间描述（不再固定写「近3年」）
        data_warning:        数据不足时的警告文字
        is_new_fund:         是否为次新基金（运行 < 365 天）
        first_date / last_date: 净值首尾日期

    缓存策略：1 小时
    """
    cache_path = _get_cache_path(fund_code, f"perf_{years}y")
    cached = _load_cache(cache_path, max_age_seconds=3600)
    if cached:
        print(f"📂 使用缓存数据（业绩）：{fund_code}")
        return cached

    if not AKSHARE_AVAILABLE:
        return _mock_fund_performance(fund_code)

    try:
        # akshare 1.18.x 参数从 fund= 改为 symbol=
        nav_df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")

        if nav_df is None or nav_df.empty:
            return _mock_fund_performance(fund_code)

        # 兼容列名变化
        nav_col  = next((c for c in ["单位净值", "净值"] if c in nav_df.columns), nav_df.columns[1])
        date_col = next((c for c in ["净值日期", "日期"] if c in nav_df.columns), nav_df.columns[0])

        nav_df[date_col] = pd.to_datetime(nav_df[date_col])
        nav_df = nav_df.sort_values(date_col)
        nav_values = nav_df[nav_col].astype(float).tolist()

        # ✅ 计算基金实际运行天数，生成正确的时间标签（不再固定写「近3年」）
        first_date  = nav_df[date_col].iloc[0]
        last_date   = nav_df[date_col].iloc[-1]
        actual_days = (last_date - first_date).days

        if actual_days < 180:
            actual_period_label = f"自成立以来（约{actual_days // 30}个月，数据极短）"
            data_warning = "⚠️ 严重警告：基金运行不足6个月，所有统计指标不具备统计显著性"
        elif actual_days < 365:
            actual_period_label = f"自成立以来（约{actual_days // 30}个月）"
            data_warning = "⚠️ 警告：基金运行不足1年，历史数据参考价值有限"
        elif actual_days < 365 * 2:
            actual_period_label = f"近1年（实际{actual_days // 30}个月）"
            data_warning = "注意：数据周期不足2年"
        else:
            actual_period_label = f"近{min(years, actual_days // 365)}年"
            data_warning = ""

        total_return = (nav_values[-1] - nav_values[0]) / nav_values[0] * 100
        max_drawdown = _calculate_max_drawdown(nav_values)

        result = {
            "fund_code":           fund_code,
            "total_return_pct":    round(total_return, 2),
            "max_drawdown_pct":    round(max_drawdown, 2),
            "period_years":        years,
            "actual_days":         actual_days,
            "actual_period_label": actual_period_label,
            "data_warning":        data_warning,
            "is_new_fund":         actual_days < 365,
            "latest_nav":          round(nav_values[-1], 4),
            "first_nav":           round(nav_values[0], 4),
            "nav_history":         [round(v, 4) for v in nav_values[-60:]],
            "first_date":          str(first_date.date()),
            "last_date":           str(last_date.date()),
            "data_source":         "akshare"
        }

        _save_cache(cache_path, result)
        print(f"✅ 基金业绩数据获取成功：{fund_code}（实际运行 {actual_days} 天）")
        return result

    except Exception as e:
        print(f"⚠️  akshare 获取业绩失败，使用模拟数据：{e}")
        return _mock_fund_performance(fund_code)


def get_fund_manager_info(manager_name: str) -> Dict:
    """
    获取基金经理信息，支持多经理（逗号/换行符分隔的多个姓名）。

    修复：
        - 用 re.split 清洗姓名，避免换行符导致解析错误（如「俞、瑶要文强」→「俞瑶、要文强」）
        - 累计从业时间为天数，自动转换为年
        - 兼容 akshare 1.18.x 列名

    缓存策略：6 小时
    """
    safe_name = manager_name.replace("/", "_").replace(" ", "_")
    cache_path = _get_cache_path(safe_name, "manager")
    cached = _load_cache(cache_path, max_age_seconds=21600)
    if cached:
        print(f"📂 使用缓存数据（经理）：{manager_name}")
        return cached

    if not AKSHARE_AVAILABLE:
        return _mock_manager_info(manager_name)

    try:
        # ✅ 修复1：用 re.split 解析多经理姓名
        # akshare 有时返回 "俞瑶\n要文强" 或 "俞瑶，要文强"，直接拼接会乱码
        raw_names = re.split(r'[\n，,、\s]+', manager_name.strip())
        clean_names = [n.strip() for n in raw_names if n.strip()]
        print(f"DEBUG 解析经理姓名：原始={repr(manager_name)} → 解析={clean_names}")

        manager_df = ak.fund_manager_em()
        print(f"DEBUG 经理表列名: {manager_df.columns.tolist()}")

        # ✅ 修复2：兼容列名变化（akshare 1.18.x 实际列名为「姓名」）
        name_col = next(
            (c for c in ["姓名", "基金经理", "name"] if c in manager_df.columns),
            manager_df.columns[0]
        )

        results = []
        for name in clean_names:
            matched = manager_df[manager_df[name_col].astype(str).str.contains(name, na=False)]
            if not matched.empty:
                row = matched.iloc[0]

                # ✅ 修复3：累计从业时间是天数，转换为年
                exp_raw = row.get("累计从业时间", row.get("从业时间", "0"))
                try:
                    exp_days  = int(str(exp_raw).replace("天", "").strip())
                    exp_years = round(exp_days / 365, 1)
                    exp_str   = f"{exp_years}年"
                except (ValueError, TypeError):
                    exp_str   = str(exp_raw)

                results.append({
                    "name":             name,
                    "experience_years": exp_str,
                    # 兼容新旧列名，优先读具体数量列
                    "managed_funds":    str(row.get("现任基金数量", row.get("管理基金数量", row.get("现任基金", "未知")))),
                    "total_aum":        str(row.get("现任基金总规模(亿元)", row.get("现任基金资产总规模", row.get("管理总规模", "未知")))) + "亿元",
                    "best_return":      str(row.get("最佳基金回报", row.get("现任基金最佳回报", "未知"))),
                    "data_source":      "akshare"
                })
            else:
                print(f"⚠️  未找到经理 {name} 的数据，使用模拟数据")
                results.append(_mock_manager_info(name))

        # ✅ 支持多经理：单经理直接返回，多经理返回 is_multi_manager 结构
        if len(results) == 1:
            result = results[0]
        else:
            result = {
                "is_multi_manager": True,
                "managers":         results,
                "manager_count":    len(results),
                "data_source":      "akshare"
            }

        _save_cache(cache_path, result)
        print(f"✅ 基金经理信息获取成功：{manager_name}")
        return result

    except Exception as e:
        print(f"⚠️  akshare 获取经理信息失败，使用模拟数据：{e}")
        return _mock_manager_info(manager_name)


def get_fund_ranking(fund_code: str, fund_type: str) -> Dict:
    """
    获取基金在同类中的排名

    参数:
        fund_code: 基金代码
        fund_type: 基金类型，如「股票型」「混合型」

    🌰 类比：不光看自己考了多少分，还要看在全班排第几名
         排名前 10% 比分数高更有说服力

    缓存策略：1 小时
    """
    cache_path = _get_cache_path(fund_code, "rank")
    cached = _load_cache(cache_path, max_age_seconds=3600)
    if cached:
        return cached

    if not AKSHARE_AVAILABLE:
        return _mock_fund_ranking(fund_code)

    try:
        # akshare 1.18.x 中 fund_rank_em 已被移除
        # 尝试备用函数名，均失败则降级至 mock
        # 🌰 类比：主入口关了，找侧门进
        ak_type = fund_type if fund_type else "混合型"
        rank_df = None
        for func_name in ("fund_open_fund_rank_em", "fund_rank_em", "fund_performance_em"):
            func = getattr(ak, func_name, None)
            if func is None:
                continue
            try:
                rank_df = func(symbol=ak_type)
                break
            except Exception:
                try:
                    rank_df = func()
                    break
                except Exception:
                    continue

        if rank_df is None:
            return _mock_fund_ranking(fund_code)

        if rank_df is not None and not rank_df.empty:
            total_funds = len(rank_df)
            # 查找基金代码列（不同版本 akshare 列名可能有差异）
            code_col = None
            for col in rank_df.columns:
                if "代码" in col or "code" in col.lower():
                    code_col = col
                    break

            if code_col and fund_code in rank_df[code_col].values:
                matched_row = rank_df[rank_df[code_col] == fund_code].iloc[0]
                # 优先使用「序号」列（akshare 返回的真实排名序号）
                if "序号" in rank_df.columns:
                    rank_position = int(matched_row["序号"])
                else:
                    # 兜底：用 DataFrame 中的行位置
                    rank_position = rank_df[rank_df[code_col] == fund_code].index.get_loc(
                        rank_df[rank_df[code_col] == fund_code].index[0]
                    ) + 1
                percentile = round(rank_position / total_funds * 100, 1)
                result = {
                    "fund_code": fund_code,
                    "rank_position": rank_position,
                    "total_funds_in_category": total_funds,
                    "rank_percentile": f"前{percentile}%",
                    "data_source": "akshare"
                }
                _save_cache(cache_path, result)
                return result

        return _mock_fund_ranking(fund_code)

    except Exception as e:
        print(f"⚠️  akshare 获取排名失败，使用模拟数据：{e}")
        return _mock_fund_ranking(fund_code)


# ============ 辅助计算函数 ============

def _calculate_max_drawdown(nav_list: List[float]) -> float:
    """
    计算最大回撤

    🌰 类比：找出价格从「最高点」到「最低点」跌幅最大的那一段
         比如净值从 2.0 跌到 1.4，回撤就是 30%
    """
    if len(nav_list) < 2:
        return 0.0

    max_drawdown = 0.0
    peak = nav_list[0]

    for nav in nav_list:
        if nav > peak:
            peak = nav  # 更新最高点
        if peak > 0:
            drawdown = (peak - nav) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown  # 记录最大回撤

    return max_drawdown


# ============ 模拟数据（akshare 不可用时的备用）============

def _mock_fund_basic(fund_code: str) -> Dict:
    """
    模拟基金基本信息（测试用）
    🌰 类比：当真实食材缺货时，用「仿真食品」代替演示
    """
    # 预设几个常用基金的数据，让演示更真实
    preset = {
        "110022": {"name": "易方达消费行业股票", "type": "股票型", "manager": "萧楠", "company": "易方达基金"},
        "000001": {"name": "华夏成长混合", "type": "混合型", "manager": "周克平", "company": "华夏基金"},
        "161725": {"name": "招商中证白酒指数A", "type": "指数型", "manager": "侯昊", "company": "招商基金"},
        "270042": {"name": "广发纳斯达克100ETF联接A", "type": "QDII", "manager": "龙煜", "company": "广发基金"},
    }
    info = preset.get(fund_code, {})
    return {
        "fund_code": fund_code,
        "name": info.get("name", f"示例基金{fund_code}"),
        "type": info.get("type", "混合型"),
        "size": f"{random.uniform(20, 200):.2f}亿元",
        "manager": info.get("manager", "张伟"),
        "establish_date": "2015-06-01",
        "company": info.get("company", "示例基金公司"),
        "data_source": "mock"
    }


def _mock_fund_performance(fund_code: str) -> Dict:
    """模拟基金业绩数据（测试用）"""
    random.seed(int(fund_code) if fund_code.isdigit() else hash(fund_code))
    base_return   = random.uniform(-10, 80)
    base_drawdown = random.uniform(5, 35)
    base_nav      = random.uniform(0.8, 3.0)
    nav_history   = []
    nav = base_nav * 0.7
    for i in range(30):
        nav = nav * (1 + random.uniform(-0.03, 0.04))
        nav_history.append(round(nav, 4))
    return {
        "fund_code":           fund_code,
        "total_return_pct":    round(base_return, 2),
        "max_drawdown_pct":    round(base_drawdown, 2),
        "period_years":        3,
        "actual_days":         1095,
        "actual_period_label": "近3年（模拟数据）",
        "data_warning":        "※模拟数据，仅供参考",
        "is_new_fund":         False,
        "latest_nav":          round(base_nav, 4),
        "first_nav":           round(base_nav * 0.7, 4),
        "nav_history":         nav_history,
        "first_date":          "2022-01-01",
        "last_date":           "2025-01-01",
        "data_source":         "mock"
    }


def _mock_manager_info(manager_name: str) -> Dict:
    """模拟基金经理信息（测试用）"""
    return {
        "name": manager_name,
        "experience_years": f"{random.randint(3, 15)}年",
        "managed_funds": f"{random.randint(1, 5)}只",
        "total_aum": f"{random.uniform(30, 300):.1f}亿元",
        "best_return": f"{random.uniform(50, 200):.1f}%",
        "data_source": "mock"
    }


def _mock_fund_ranking(fund_code: str) -> Dict:
    """模拟基金排名数据（测试用）"""
    random.seed(int(fund_code) if fund_code.isdigit() else hash(fund_code))
    percentile = random.randint(10, 60)
    return {
        "fund_code": fund_code,
        "rank_position": percentile * 3,
        "total_funds_in_category": percentile * 3 * 100 // percentile,
        "rank_percentile": f"前{percentile}%",
        "rank_description": "同类基金中表现良好" if percentile <= 30 else "同类基金中表现中等",
        "data_source": "mock"
    }


# ============================================================
# V2.5 新增：多接口交叉补全策略
# 目标：用 akshare 其余接口填充 return_1y / return_3y /
#        benchmark_return_pct / volatility / sharpe
# ============================================================

def fetch_returns_from_rank(fund_code: str) -> dict:
    """
    从东方财富基金排行接口获取分期收益率。
    接口：fund_open_fund_rank_em(symbol="全部")
    包含：近1年、近3年、近5年、成立以来等多个时间窗口。
    """
    result = {
        "return_1y": None,
        "return_3y": None,
        "return_5y": None,
        "as_of":     None,
    }
    if not AKSHARE_AVAILABLE:
        return result
    try:
        from datetime import date as date_type
        df = ak.fund_open_fund_rank_em(symbol="全部")
        if df is None or df.empty:
            return result

        code_col = next((c for c in df.columns if "代码" in c), None)
        if not code_col:
            return result

        row = df[df[code_col].astype(str) == fund_code]
        if row.empty:
            return result

        row = row.iloc[0]
        result["as_of"] = date_type.today()

        col_map = {
            "近1年": "return_1y",
            "1年":   "return_1y",
            "近3年": "return_3y",
            "3年":   "return_3y",
            "近5年": "return_5y",
            "5年":   "return_5y",
        }
        for col_keyword, field in col_map.items():
            matched_col = next((c for c in df.columns if col_keyword in c), None)
            if matched_col and pd.notna(row.get(matched_col)):
                try:
                    val = float(str(row[matched_col]).replace('%', '').strip())
                    result[field] = round(val, 2)
                except (ValueError, TypeError):
                    pass

        return result
    except Exception as e:
        print(f"⚠️ [fetch_returns_from_rank] {fund_code}: {e}")
        return result


def fetch_benchmark_return_from_info(fund_code: str) -> Optional[float]:
    """
    从「累计收益率走势」接口提取同期基准收益率（最新值）。
    """
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = ak.fund_open_fund_info_em(
            symbol=fund_code,
            indicator="累计收益率走势"
        )
        if df is None or df.empty:
            return None

        bench_col = next(
            (c for c in df.columns if "基准" in c or "benchmark" in c.lower()),
            None
        )
        if bench_col is None and len(df.columns) >= 2:
            bench_col = df.columns[1]

        if bench_col:
            latest_bench = df[bench_col].dropna()
            if not latest_bench.empty:
                return round(float(latest_bench.iloc[-1]), 2)
        return None
    except Exception as e:
        print(f"⚠️ [fetch_benchmark_return_from_info] {fund_code}: {e}")
        return None


def compute_volatility_and_sharpe(
    fund_code: str,
    risk_free_rate: float = 0.015,
) -> dict:
    """
    从历史净值走势自行计算年化波动率和 Sharpe Ratio。
    risk_free_rate: 1年期存款利率（默认 1.5%）
    """
    result = {
        "volatility_annual": None,
        "sharpe_ratio":      None,
    }
    if not AKSHARE_AVAILABLE:
        return result
    try:
        import numpy as np

        df = ak.fund_open_fund_info_em(
            symbol=fund_code,
            indicator="单位净值走势"
        )
        if df is None or df.empty or len(df) < 20:
            return result

        date_col = df.columns[0]
        nav_col  = df.columns[1]
        df = df.sort_values(date_col)

        nav_series = pd.to_numeric(df[nav_col], errors='coerce').dropna()
        if len(nav_series) < 20:
            return result

        daily_returns = nav_series.pct_change().dropna()
        vol_annual    = float(daily_returns.std() * np.sqrt(250) * 100)

        total_return = float(nav_series.iloc[-1] / nav_series.iloc[0] - 1)
        n_years      = max(len(daily_returns) / 250, 0.1)
        annual_return = (1 + total_return) ** (1 / n_years) - 1

        excess_return = annual_return - risk_free_rate
        sharpe = round(excess_return / (vol_annual / 100), 2) if vol_annual > 0 else None

        result["volatility_annual"] = round(vol_annual, 2)
        result["sharpe_ratio"]      = sharpe
        return result
    except Exception as e:
        print(f"⚠️ [compute_volatility_and_sharpe] {fund_code}: {e}")
        return result


def enrich_snapshot_with_multi_source(snapshot, fund_code: str) -> None:
    """
    对已有 snapshot 做多接口补全。
    只填充 value=None 的字段，不覆盖已有真实数据。
    在 fetch_fund_snapshot() 末尾调用。
    """
    from backend.schemas import MetricSource, DataNature
    from datetime import date as date_type

    print(f"   [enrich] 开始多接口补全：{fund_code}")

    # ---- 补全分期收益率 ----
    needs_returns = (
        getattr(getattr(snapshot, 'return_1y', None), 'value', None) is None
        or getattr(getattr(snapshot, 'return_3y', None), 'value', None) is None
    )
    if needs_returns:
        returns_data = fetch_returns_from_rank(fund_code)
        time.sleep(0.3)

        if returns_data.get("return_1y") is not None and \
                getattr(getattr(snapshot, 'return_1y', None), 'value', None) is None:
            snapshot.return_1y = MetricSource(
                value=returns_data["return_1y"],
                unit="%",
                as_of=returns_data["as_of"],
                nature=DataNature.REAL,
                source="akshare",
                is_mock=False,
                endpoint="fund_open_fund_rank_em",
            )
            print(f"   [enrich] return_1y 补全：{returns_data['return_1y']}%")

        if returns_data.get("return_3y") is not None and \
                getattr(getattr(snapshot, 'return_3y', None), 'value', None) is None:
            snapshot.return_3y = MetricSource(
                value=returns_data["return_3y"],
                unit="%",
                as_of=returns_data["as_of"],
                nature=DataNature.REAL,
                source="akshare",
                is_mock=False,
                endpoint="fund_open_fund_rank_em",
            )
            print(f"   [enrich] return_3y 补全：{returns_data['return_3y']}%")

    # ---- 补全基准收益 ----
    if getattr(getattr(snapshot, 'benchmark_return_pct', None), 'value', None) is None:
        bench_val = fetch_benchmark_return_from_info(fund_code)
        time.sleep(0.3)
        if bench_val is not None:
            snapshot.benchmark_return_pct = MetricSource(
                value=bench_val,
                unit="%",
                as_of=date_type.today(),
                nature=DataNature.REAL,
                source="akshare",
                is_mock=False,
                endpoint="fund_open_fund_info_em(累计收益率走势)",
            )
            print(f"   [enrich] benchmark_return_pct 补全：{bench_val}%")

    # ---- 补全波动率和 Sharpe ----
    needs_vol = getattr(getattr(snapshot, 'volatility', None), 'value', None) is None
    if needs_vol:
        vol_data = compute_volatility_and_sharpe(fund_code)
        time.sleep(0.3)
        if vol_data.get("volatility_annual") is not None:
            snapshot.volatility = MetricSource(
                value=vol_data["volatility_annual"],
                unit="%",
                as_of=date_type.today(),
                nature=DataNature.CALCULATED,
                source="calculated",
                is_mock=False,
                note="由历史日净值走势计算，250个交易日年化",
            )
        if vol_data.get("sharpe_ratio") is not None:
            snapshot.sharpe = MetricSource(
                value=vol_data["sharpe_ratio"],
                unit="",
                as_of=date_type.today(),
                nature=DataNature.CALCULATED,
                source="calculated",
                is_mock=False,
                note="(年化收益率 - 1.5%无风险利率) / 年化波动率",
            )
        if vol_data.get("volatility_annual"):
            print(f"   [enrich] volatility={vol_data['volatility_annual']}%, "
                  f"sharpe={vol_data.get('sharpe_ratio')}")

    print(f"   [enrich] 补全完成")


# ============================================================
# V2.0 新增：构建 FundSnapshot 的统一入口
# ============================================================

def fetch_fund_snapshot(code: str, report_date=None) -> "FundSnapshot":
    """
    拉取所有数据并构建 FundSnapshot 对象
    这是 V2.0 graph 的唯一数据入口

    V2.1 修复：
    - 累计净值从「累计净值走势」接口单独获取，不写死1.0
    - 调用 benchmark_resolver 解析基准指数
    - MetricSource source 字段统一用英文

    🌰 类比：「采购员」把所有食材买齐、整理好放进冰箱，
             后续所有厨师从同一个冰箱取材
    """
    from datetime import date as date_type
    from backend.schemas import (
        FundSnapshot, MetricSource, ManagerInfo, PeerRank
    )

    if report_date is None:
        report_date = date_type.today()

    # ---- 安全构建 MetricSource 的辅助函数（统一清洗 source 字段）----
    def safe_metric_source(value, unit, source, **kwargs):
        """构建 MetricSource 时强制清洗 source 字段为合法英文值"""
        from backend.value_cleaner import normalize_source
        try:
            clean_src = normalize_source(source, allow_warning=True)
        except ValueError:
            clean_src = "mock"
        return MetricSource(value=value, unit=unit, source=clean_src, **kwargs)

    # 1. 基本信息
    basic = get_fund_basic_info(code)
    is_mock_basic = basic.get("data_source", "mock") == "mock"

    # 解析成立日期
    inception_date = None
    establish_str = basic.get("establish_date", "")
    if establish_str and establish_str != "未知":
        try:
            from datetime import datetime as dt_type
            # 支持多种日期格式
            for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
                try:
                    inception_date = dt_type.strptime(establish_str, fmt).date()
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    # 解析基金规模
    size_str = basic.get("size", "")
    fund_size_val = None
    try:
        size_num_str = re.sub(r'[^\d.]', '', str(size_str))
        if size_num_str:
            fund_size_val = float(size_num_str)
    except (ValueError, TypeError):
        pass

    # 2. 业绩数据
    perf = get_fund_performance(code, years=3)
    is_mock_perf = perf.get("data_source", "mock") == "mock"

    # 解析净值
    nav_val = perf.get("latest_nav")
    first_nav_val = perf.get("first_nav")
    total_return = perf.get("total_return_pct")
    max_drawdown = perf.get("max_drawdown_pct")
    actual_days = perf.get("actual_days", 0)
    last_date_str = perf.get("last_date")

    last_nav_date = None
    if last_date_str:
        try:
            from datetime import datetime as dt_type
            last_nav_date = dt_type.strptime(last_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    # 3. 基金经理
    manager_name = basic.get("manager", "")
    managers: list[ManagerInfo] = []
    if manager_name and manager_name != "未知":
        mgr_data = get_fund_manager_info(manager_name)
        is_mock_mgr = mgr_data.get("data_source", "mock") == "mock"

        if mgr_data.get("is_multi_manager"):
            for m in mgr_data.get("managers", []):
                exp_raw = m.get("experience_years", "0年")
                try:
                    exp_years = float(str(exp_raw).replace("年", "").strip())
                except (ValueError, TypeError):
                    exp_years = None
                aum_raw = m.get("total_aum", "")
                try:
                    aum_bn = float(re.sub(r'[^\d.]', '', str(aum_raw))) if aum_raw else None
                except (ValueError, TypeError):
                    aum_bn = None
                managers.append(ManagerInfo(
                    name=m.get("name", "未知"),
                    experience_years=exp_years,
                    is_mock=is_mock_mgr,
                    total_aum_bn=aum_bn,
                ))
        else:
            exp_raw = mgr_data.get("experience_years", "0年")
            try:
                exp_years = float(str(exp_raw).replace("年", "").strip())
            except (ValueError, TypeError):
                exp_years = None
            aum_raw = mgr_data.get("total_aum", "")
            try:
                aum_bn = float(re.sub(r'[^\d.]', '', str(aum_raw))) if aum_raw else None
            except (ValueError, TypeError):
                aum_bn = None
            managers.append(ManagerInfo(
                name=mgr_data.get("name", manager_name),
                experience_years=exp_years,
                is_mock=is_mock_mgr,
                total_aum_bn=aum_bn,
            ))

    # 4. 同类排名
    fund_type = basic.get("type", "混合型")
    ranking = get_fund_ranking(code, fund_type)
    is_mock_rank = ranking.get("data_source", "mock") == "mock"
    peer_rank = None
    rank_pos = ranking.get("rank_position")
    total_funds = ranking.get("total_funds_in_category")
    if rank_pos and total_funds:
        peer_rank = PeerRank(
            rank=int(rank_pos),
            total=int(total_funds),
            percentile=round(int(rank_pos) / int(total_funds) * 100, 2),
        )

    # 5. 累计净值（V2.1修复：独立接口获取，不写死1.0）
    accumulated_nav_metric = None
    if AKSHARE_AVAILABLE:
        try:
            acc_df = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
            if acc_df is not None and not acc_df.empty:
                acc_col  = next(
                    (c for c in ["累计净值", "净值"] if c in acc_df.columns),
                    acc_df.columns[1]
                )
                date_col = next(
                    (c for c in ["净值日期", "日期"] if c in acc_df.columns),
                    acc_df.columns[0]
                )
                acc_df[date_col] = pd.to_datetime(acc_df[date_col])
                acc_df = acc_df.sort_values(date_col)
                latest_acc      = float(acc_df[acc_col].iloc[-1])
                latest_acc_date = acc_df[date_col].iloc[-1].date()
                from backend.schemas import DataNature
                accumulated_nav_metric = MetricSource(
                    value=latest_acc,
                    unit="元",
                    source="akshare",
                    endpoint="fund_open_fund_info_em(累计净值走势)",
                    as_of=latest_acc_date,
                    is_mock=False,
                    confidence=1.0,
                    nature=DataNature.REAL,
                )
                print(f"✅ 累计净值获取成功：{code} = {latest_acc}")
        except Exception as e:
            print(f"⚠️ 累计净值获取失败，不写死1.0，显示为数据缺失：{e}")
            # 不写死 accumulated_nav_metric = None（保持 None，避免写入错误值）

    # 6. 基准对比（P3）
    benchmark_return_metric = None
    alpha_metric = None
    benchmark_name = None
    if inception_date:
        try:
            from backend.benchmark import get_benchmark_return
            benchmark_return_metric, benchmark_name = get_benchmark_return(
                fund_type=fund_type,
                inception_date=inception_date,
                report_date=report_date,
                fund_code=code,
            )
            if (benchmark_return_metric is not None
                    and benchmark_return_metric.value is not None
                    and total_return is not None):
                alpha_val = round(float(total_return) - float(benchmark_return_metric.value), 2)
                from backend.schemas import DataNature as _DN
                alpha_metric = MetricSource(
                    value=alpha_val,
                    unit="%",
                    source="calculated",
                    is_mock=benchmark_return_metric.is_mock,
                    nature=_DN.CALCULATED,
                    note=f"超额收益 = 基金收益({total_return}%) - 基准收益({benchmark_return_metric.value}%)",
                )
        except Exception as e:
            print(f"⚠️ 基准数据计算失败（不影响主流程）：{e}")

    # 7. 基准指数解析（V2.1新增：benchmark_resolver）
    fund_name_for_bench = basic.get("name", code)
    declared_benchmark  = basic.get("业绩比较基准") or basic.get("跟踪标的") or None
    try:
        from backend.benchmark_resolver import resolve_benchmark
        benchmark_info = resolve_benchmark(
            fund_name=fund_name_for_bench,
            fund_type=fund_type,
            declared_benchmark=declared_benchmark,
        )
        # 如果 benchmark_resolver 解析到了名称，优先用它覆盖旧的 benchmark_name
        if benchmark_info and benchmark_info.name:
            benchmark_name = benchmark_info.name
        print(f"✅ benchmark_resolver: {getattr(benchmark_info, 'name', None)} "
              f"matched={getattr(benchmark_info, 'is_matched', False)}")
    except Exception as e:
        print(f"⚠️ benchmark_resolver 失败（不影响主流程）：{e}")
        benchmark_info = None

    # 8. 构建 FundSnapshot
    from backend.schemas import DataNature
    _nat_perf  = DataNature.MOCK if is_mock_perf  else DataNature.REAL
    _nat_basic = DataNature.MOCK if is_mock_basic else DataNature.REAL

    snapshot = FundSnapshot(
        code=code,
        report_date=report_date,
        name=basic.get("name"),
        fund_type=fund_type,
        fund_company=basic.get("company"),
        inception_date=inception_date,
        nav=MetricSource(
            value=nav_val, unit="元", source="akshare" if not is_mock_perf else "mock",
            as_of=last_nav_date, is_mock=is_mock_perf,
            endpoint="fund_open_fund_info_em",
            nature=_nat_perf,
        ) if nav_val is not None else None,
        # ✅ V2.1修复：使用真实接口的累计净值（非first_nav，非写死1.0）
        accumulated_nav=accumulated_nav_metric,
        fund_size_bn=MetricSource(
            value=fund_size_val, unit="亿元",
            source="akshare" if not is_mock_basic else "mock",
            is_mock=is_mock_basic,
            nature=_nat_basic,
        ) if fund_size_val is not None else None,
        return_since_inception=MetricSource(
            value=total_return, unit="%",
            source="akshare" if not is_mock_perf else "mock",
            as_of=last_nav_date, is_mock=is_mock_perf,
            note=perf.get("actual_period_label", ""),
            nature=_nat_perf,
        ) if total_return is not None else None,
        max_drawdown=MetricSource(
            value=abs(max_drawdown) if max_drawdown is not None else None, unit="%",
            source="akshare" if not is_mock_perf else "mock",
            as_of=last_nav_date, is_mock=is_mock_perf,
            nature=DataNature.CALCULATED,   # 由净值历史计算
        ) if max_drawdown is not None else None,
        peer_rank=peer_rank,
        managers=managers,
        benchmark_name=benchmark_name,          # 保留字符串字段兼容旧代码
        benchmark=benchmark_info,               # ✅ V2.1新增：BenchmarkInfo对象
        benchmark_return_pct=benchmark_return_metric,
        alpha_pct=alpha_metric,
        raw={
            "basic": basic,
            "perf": {k: v for k, v in perf.items() if k != "nav_history"},
            "ranking": ranking,
        }
    )

    # 9. V2.5 多接口补全：填充 return_1y / return_3y / benchmark_return_pct / volatility / sharpe
    enrich_snapshot_with_multi_source(snapshot, code)

    return snapshot
