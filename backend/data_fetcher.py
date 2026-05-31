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
