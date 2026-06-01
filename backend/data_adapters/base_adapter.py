# backend/data_adapters/base_adapter.py
"""
数据源适配器抽象基类
🌰 类比：不同品牌的充电器，只要接口形状一样，都能给手机充电
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional


class FundDataAdapter(ABC):
    """
    所有数据源必须实现此接口。
    上层代码（data_fetcher.py）只依赖这个接口，不感知底层数据源。
    """

    @abstractmethod
    def get_nav(self, fund_code: str) -> Optional[dict]:
        """
        获取最新净值
        返回格式：
        {
          "unit_nav": float,
          "accumulated_nav": float,
          "as_of": date,
          "source": str,
        }
        失败返回 None。
        """
        ...

    @abstractmethod
    def get_returns(self, fund_code: str) -> Optional[dict]:
        """
        获取各期收益率
        返回格式：
        {
          "return_since_inception": float,
          "return_1y": float or None,
          "return_3y": float or None,
          "as_of": date,
          "source": str,
        }
        """
        ...

    @abstractmethod
    def get_drawdown(self, fund_code: str) -> Optional[dict]:
        """
        获取最大回撤
        返回格式：
        {
          "max_drawdown": float,   # 正数，如 31.18 表示 31.18%
          "as_of": date,
          "source": str,
        }
        """
        ...

    @abstractmethod
    def get_fund_info(self, fund_code: str) -> Optional[dict]:
        """
        获取基金基本信息
        返回格式：
        {
          "name": str,
          "fund_type": str,
          "company": str,
          "inception_date": date,
          "benchmark_name": str or None,
          "managers": list[dict],
          "source": str,
        }
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        ...
