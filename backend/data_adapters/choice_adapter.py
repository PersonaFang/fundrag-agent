# backend/data_adapters/choice_adapter.py
"""
Choice（东方财富 Choice）数据源适配器
前提：已安装 ChoiceSDK（EmQuantAPI），有效企业账号授权
安装：pip install dfchoice（或从东方财富获取离线包）
"""

from __future__ import annotations
from datetime import date
from typing import Optional
import os

from .base_adapter import FundDataAdapter


class ChoiceAdapter(FundDataAdapter):
    """
    Choice 数据适配器
    环境变量：CHOICE_ACCOUNT, CHOICE_PASSWORD
    """

    def __init__(self):
        self._api = None
        self._connected = False

    def _connect(self) -> bool:
        if self._connected:
            return True
        try:
            from EmQuantAPI import c as choice_api
            account  = os.getenv("CHOICE_ACCOUNT", "")
            password = os.getenv("CHOICE_PASSWORD", "")
            if not account:
                print("❌ [ChoiceAdapter] 未配置 CHOICE_ACCOUNT")
                return False
            ret = choice_api.start(account, password)
            if ret.ErrorCode == 0:
                self._api = choice_api
                self._connected = True
                print("✅ [ChoiceAdapter] Choice 连接成功")
                return True
            print(f"❌ [ChoiceAdapter] 连接失败：{ret.ErrorMsg}")
            return False
        except ImportError:
            print("❌ [ChoiceAdapter] EmQuantAPI 未安装")
            return False
        except Exception as e:
            print(f"❌ [ChoiceAdapter] 连接异常：{e}")
            return False

    def is_available(self) -> bool:
        return self._connect()

    @staticmethod
    def _to_choice_code(fund_code: str) -> str:
        return f"{fund_code}.OF" if "." not in fund_code else fund_code

    def get_nav(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            code   = self._to_choice_code(fund_code)
            today  = date.today().strftime("%Y-%m-%d")
            result = self._api.css(code, "EMS_NAV,EMS_ACCUMUNAV", f"TradeDate={today}")
            if result.ErrorCode != 0:
                return None
            data = result.Data
            unit_nav = data.get("EMS_NAV", {}).get(code)
            acc_nav  = data.get("EMS_ACCUMUNAV", {}).get(code)
            if unit_nav is None:
                return None
            return {
                "unit_nav":        float(unit_nav),
                "accumulated_nav": float(acc_nav) if acc_nav else float(unit_nav),
                "as_of":           date.today(),
                "source":          "choice",
            }
        except Exception as e:
            print(f"❌ [ChoiceAdapter.get_nav] {e}")
            return None

    def get_returns(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            code   = self._to_choice_code(fund_code)
            today  = date.today().strftime("%Y-%m-%d")
            fields = "EMS_CHANGEPCTNEWINCEPTION,EMS_1YRETURN,EMS_3YRETURN"
            result = self._api.css(code, fields, f"TradeDate={today}")
            if result.ErrorCode != 0:
                return None
            data = result.Data

            def get_pct(field):
                v = data.get(field, {}).get(code)
                return round(float(v), 2) if v is not None else None

            return {
                "return_since_inception": get_pct("EMS_CHANGEPCTNEWINCEPTION"),
                "return_1y":              get_pct("EMS_1YRETURN"),
                "return_3y":              get_pct("EMS_3YRETURN"),
                "as_of":                  date.today(),
                "source":                 "choice",
            }
        except Exception as e:
            print(f"❌ [ChoiceAdapter.get_returns] {e}")
            return None

    def get_drawdown(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            code   = self._to_choice_code(fund_code)
            today  = date.today().strftime("%Y-%m-%d")
            result = self._api.css(code, "EMS_MAXRETRACEMENT", f"TradeDate={today}")
            if result.ErrorCode != 0:
                return None
            mdd = result.Data.get("EMS_MAXRETRACEMENT", {}).get(code)
            if mdd is None:
                return None
            return {
                "max_drawdown": round(abs(float(mdd)) * 100, 2),
                "as_of":        date.today(),
                "source":       "choice",
            }
        except Exception as e:
            print(f"❌ [ChoiceAdapter.get_drawdown] {e}")
            return None

    def get_fund_info(self, fund_code: str) -> Optional[dict]:
        if not self._connect():
            return None
        try:
            code   = self._to_choice_code(fund_code)
            fields = "EMS_FUNDNAME,EMS_FUNDTYPE,EMS_FUNDCOMP,EMS_SETUPDATE,EMS_BENCHMARK"
            result = self._api.css(code, fields)
            if result.ErrorCode != 0:
                return None
            data = result.Data

            def get_val(field):
                return data.get(field, {}).get(code)

            setup_date = get_val("EMS_SETUPDATE")
            inception = None
            if setup_date:
                try:
                    from datetime import datetime
                    inception = datetime.strptime(str(setup_date)[:10], "%Y-%m-%d").date()
                except Exception:
                    pass

            return {
                "name":           get_val("EMS_FUNDNAME"),
                "fund_type":      get_val("EMS_FUNDTYPE"),
                "company":        get_val("EMS_FUNDCOMP"),
                "inception_date": inception,
                "benchmark_name": get_val("EMS_BENCHMARK"),
                "managers":       [],
                "source":         "choice",
            }
        except Exception as e:
            print(f"❌ [ChoiceAdapter.get_fund_info] {e}")
            return None
