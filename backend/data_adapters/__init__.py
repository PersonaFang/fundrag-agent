# backend/data_adapters/__init__.py
"""数据源适配器包：统一接口，支持 akshare / Wind / Choice 自动降级"""
from .adapter_factory import get_adapter
from .base_adapter import FundDataAdapter

__all__ = ["get_adapter", "FundDataAdapter"]
