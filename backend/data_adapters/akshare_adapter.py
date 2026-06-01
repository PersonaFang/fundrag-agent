# backend/data_adapters/akshare_adapter.py
"""
akshare 适配器：将 akshare 调用封装为标准接口
作为默认/降级数据源（免费，无需授权）
"""

from __future__ import annotations
from datetime import date
from typing import Optional

from .base_adapter import FundDataAdapter


class AkshareAdapter(FundDataAdapter):

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    def get_nav(self, fund_code: str) -> Optional[dict]:
        try:
            import akshare as ak
            import pandas as pd
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            date_col = next((c for c in ["净值日期", "日期"] if c in df.columns), df.columns[0])
            nav_col  = next((c for c in ["单位净值", "净值"] if c in df.columns), df.columns[1])
            df[date_col] = pd.to_datetime(df[date_col])
            latest = df.sort_values(date_col).iloc[-1]
            return {
                "unit_nav":        float(latest[nav_col]),
                "accumulated_nav": float(latest.get("累计净值", latest[nav_col])),
                "as_of":           latest[date_col].date(),
                "source":          "akshare",
            }
        except Exception as e:
            print(f"❌ [AkshareAdapter.get_nav] {e}")
            return None

    def get_returns(self, fund_code: str) -> Optional[dict]:
        try:
            import akshare as ak
            import pandas as pd
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            date_col = next((c for c in ["净值日期", "日期"] if c in df.columns), df.columns[0])
            nav_col  = next((c for c in ["单位净值", "净值"] if c in df.columns), df.columns[1])
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.sort_values(date_col)
            nav_vals = df[nav_col].astype(float).tolist()
            if len(nav_vals) < 2:
                return None
            total_return = round((nav_vals[-1] - nav_vals[0]) / nav_vals[0] * 100, 2)
            return {
                "return_since_inception": total_return,
                "return_1y":              None,
                "return_3y":              None,
                "as_of":                  date.today(),
                "source":                 "akshare",
            }
        except Exception as e:
            print(f"❌ [AkshareAdapter.get_returns] {e}")
            return None

    def get_drawdown(self, fund_code: str) -> Optional[dict]:
        try:
            import akshare as ak
            import pandas as pd
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            nav_col = next((c for c in ["单位净值", "净值"] if c in df.columns), df.columns[1])
            navs = df[nav_col].astype(float).tolist()
            peak = navs[0]
            max_dd = 0.0
            for v in navs:
                peak = max(peak, v)
                if peak > 0:
                    dd = (peak - v) / peak * 100
                    max_dd = max(max_dd, dd)
            return {
                "max_drawdown": round(max_dd, 2),
                "as_of":        date.today(),
                "source":       "akshare",
            }
        except Exception as e:
            print(f"❌ [AkshareAdapter.get_drawdown] {e}")
            return None

    def get_fund_info(self, fund_code: str) -> Optional[dict]:
        try:
            import akshare as ak
            df = ak.fund_individual_basic_info_xq(symbol=fund_code)
            info = dict(zip(df["item"], df["value"]))
            return {
                "name":           str(info.get("基金全称", info.get("基金名称", ""))),
                "fund_type":      str(info.get("基金类型", "混合型")).split("-")[0].strip(),
                "company":        str(info.get("基金公司", "")),
                "inception_date": None,
                "benchmark_name": str(info.get("业绩比较基准", "")) or None,
                "managers":       [],
                "source":         "akshare",
            }
        except Exception as e:
            print(f"❌ [AkshareAdapter.get_fund_info] {e}")
            return None
