# backend/data_adapters/adapter_factory.py
"""
数据源工厂：根据环境变量选择最优数据源，支持自动降级
🌰 类比：司机只管叫车，打车平台决定派哪辆车

优先级（可通过 DATA_SOURCE 环境变量覆盖）：
  wind    → WindAdapter
  choice  → ChoiceAdapter
  akshare → AkshareAdapter（默认，免费）
  auto    → wind → choice → akshare
"""

import os
from functools import lru_cache
from .base_adapter import FundDataAdapter


@lru_cache(maxsize=1)
def get_adapter() -> FundDataAdapter:
    """
    获取当前环境下最优数据适配器（单例）。
    ✅ lru_cache 确保全局只初始化一次
    """
    data_source = os.getenv("DATA_SOURCE", "auto").lower().strip()

    def try_wind():
        try:
            from .wind_adapter import WindAdapter
            adapter = WindAdapter()
            if adapter.is_available():
                print("✅ [AdapterFactory] 使用 Wind 数据源")
                return adapter
        except Exception as e:
            print(f"⚠️ [AdapterFactory] Wind 不可用：{e}")
        return None

    def try_choice():
        try:
            from .choice_adapter import ChoiceAdapter
            adapter = ChoiceAdapter()
            if adapter.is_available():
                print("✅ [AdapterFactory] 使用 Choice 数据源")
                return adapter
        except Exception as e:
            print(f"⚠️ [AdapterFactory] Choice 不可用：{e}")
        return None

    def use_akshare():
        from .akshare_adapter import AkshareAdapter
        print("✅ [AdapterFactory] 使用 akshare 数据源（免费）")
        return AkshareAdapter()

    if data_source == "wind":
        return try_wind() or use_akshare()
    elif data_source == "choice":
        return try_choice() or use_akshare()
    elif data_source == "auto":
        return try_wind() or try_choice() or use_akshare()
    else:
        return use_akshare()
