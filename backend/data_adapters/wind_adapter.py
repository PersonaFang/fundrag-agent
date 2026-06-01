# backend/data_adapters/wind_adapter.py
"""
Wind 数据源适配器
前提：服务器已安装 WindPy，且有有效的 Wind 量化终端授权
安装：pip install WindPy（需在有 Wind 终端的机器上）
"""

from __future__ import annotations
from datetime import date
from typing import Optional
import os

from .base_adapter import FundDataAdapter


class WindAdapter(FundDataAdapter):
    """
    Wind 量化数据适配器
    环境变量：WIND_USERNAME, WIND_PASSWORD（部分部署方式需要）
    """

    def __init__(self):
        self._w = None
        self._connected = False

    def _connect(self) -> bool:
        if self._connected:
            return True
        try:
            from WindPy import w
            ret = w.start(waitTime=10)
            if ret.ErrorCode == 0:
                self._w = w
                self._connected = True
                print("✅ [WindAdapter] Wind 连接成功")
                return True
            print(f"❌ [WindAdapter] Wind 连接失败，ErrorCode={ret.ErrorCode}")
            return False
        except ImportError:
            print("❌ [WindAdapter] WindPy 未安装")
            return False
        except Exception as e:
            print(f"❌ [WindAdapter] 连接异常：{e}")
            return False

    def is_available(self) -> bool:
        return self._connect()

    @staticmethod
    def _to_wind_code(fund_code: str) -> str:
        return f"{fund_code}.OF" if "." not in fund_code else fund_code

    def get_nav(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            wcode  = self._to_wind_code(fund_code)
            today  = date.today().strftime("%Y-%m-%d")
            result = self._w.wss(wcode, "NAV,NAV_ACC", f"tradeDate={today};")
            if result.ErrorCode != 0 or not result.Data:
                return None
            unit_nav = result.Data[0][0]
            acc_nav  = result.Data[1][0]
            if unit_nav is None:
                return None
            return {
                "unit_nav":        float(unit_nav),
                "accumulated_nav": float(acc_nav) if acc_nav else float(unit_nav),
                "as_of":           date.today(),
                "source":          "wind",
            }
        except Exception as e:
            print(f"❌ [WindAdapter.get_nav] {e}")
            return None

    def get_returns(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            wcode  = self._to_wind_code(fund_code)
            today  = date.today().strftime("%Y-%m-%d")
            result = self._w.wss(
                wcode,
                "FUND_RETURN_SINCE_INCEPTION,FUND_RETURN_1Y,FUND_RETURN_3Y",
                f"tradeDate={today};"
            )
            if result.ErrorCode != 0 or not result.Data:
                return None

            def pct(v):
                return round(float(v) * 100, 2) if v is not None else None

            return {
                "return_since_inception": pct(result.Data[0][0]),
                "return_1y":              pct(result.Data[1][0]),
                "return_3y":              pct(result.Data[2][0]),
                "as_of":                  date.today(),
                "source":                 "wind",
            }
        except Exception as e:
            print(f"❌ [WindAdapter.get_returns] {e}")
            return None

    def get_drawdown(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            wcode  = self._to_wind_code(fund_code)
            today  = date.today().strftime("%Y-%m-%d")
            result = self._w.wss(wcode, "FUND_MAX_DRAWDOWN_INCEPTION", f"tradeDate={today};")
            if result.ErrorCode != 0 or not result.Data or result.Data[0][0] is None:
                return None
            return {
                "max_drawdown": round(abs(float(result.Data[0][0])) * 100, 2),
                "as_of":        date.today(),
                "source":       "wind",
            }
        except Exception as e:
            print(f"❌ [WindAdapter.get_drawdown] {e}")
            return None

    def get_fund_info(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            wcode  = self._to_wind_code(fund_code)
            result = self._w.wss(
                wcode,
                "SEC_NAME,FUND_FUNDTYPE,FUND_CORP_FUNDMANAGEMENTCOMP,"
                "FUND_SETUPDATE,FUND_BENCHMARK",
            )
            if result.ErrorCode != 0 or not result.Data:
                return None
            name, ftype, company, setup_date, benchmark = [d[0] for d in result.Data]
            inception = None
            if setup_date:
                try:
                    from datetime import datetime
                    inception = datetime.strptime(str(setup_date)[:10], "%Y-%m-%d").date()
                except Exception:
                    pass
            return {
                "name":           str(name) if name else None,
                "fund_type":      str(ftype) if ftype else None,
                "company":        str(company) if company else None,
                "inception_date": inception,
                "benchmark_name": str(benchmark) if benchmark else None,
                "managers":       [],
                "source":         "wind",
            }
        except Exception as e:
            print(f"❌ [WindAdapter.get_fund_info] {e}")
            return None
