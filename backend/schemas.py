# backend/schemas.py
"""
统一数据契约：所有指标必须带 source/as_of/is_mock/confidence
🌰 类比：每一个数字都贴着「出生证明」，注明来自哪里、什么时候、是否真实
"""

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


class DataQualityLevel(str, Enum):
    REAL        = "real"        # 全部真实数据
    LIMITED     = "limited"     # V2.2 新增：次新基金，数据真实但样本不足
    PARTIAL     = "partial"     # 部分模拟或缺失
    MOCK        = "mock"        # 全部模拟
    FAILED      = "failed"      # 数据存在硬性矛盾
    UNAVAILABLE = "unavailable" # 数据严重不足


class DataNature(str, Enum):
    """单个指标的数据性质（V2.1+）"""
    REAL        = "real"        # 来自可信外部接口的真实数据
    CALCULATED  = "calculated"  # 由 real 数据计算得出
    MISSING     = "missing"     # 缺失，无法获取
    MOCK        = "mock"        # 模拟/降级数据
    SUSPICIOUS  = "suspicious"  # 数据存在疑问

    @classmethod
    def from_any(cls, val) -> "DataNature":
        """
        安全转换：支持英文值、中文旧值、枚举实例。
        ✅ 任何未知值（含"阿富汗"）→ MISSING，绝不抛异常
        """
        if val is None:
            return cls.MISSING
        if isinstance(val, cls):
            return val
        _LEGACY = {
            "真实": cls.REAL, "计算": cls.CALCULATED,
            "缺失": cls.MISSING, "模拟": cls.MOCK, "存疑": cls.SUSPICIOUS,
        }
        _BY_VALUE = {v.value: v for v in cls}
        key = str(val).strip()
        if key in _BY_VALUE:
            return _BY_VALUE[key]
        if key in _LEGACY:
            return _LEGACY[key]
        return cls.MISSING   # 兜底


class MetricSource(BaseModel):
    """单个指标的完整溯源信息"""
    value:      Optional[Union[float, int, str]] = None
    unit:       Optional[str] = None
    source:     str = "unknown"           # akshare / mock / tavily
    endpoint:   Optional[str] = None      # 具体接口名
    as_of:      Optional[date] = None     # 数据截止日期
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    is_mock:    bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    note:       Optional[str] = None
    nature:     Optional[DataNature] = None   # V2.1：数据性质
    depends_on: list[str] = Field(default_factory=list)  # V2.1：依赖字段名

    @field_validator('nature', mode='before')
    @classmethod
    def _validate_nature(cls, v):
        """✅ 任何脏值（含"阿富汗"）→ DataNature.MISSING"""
        if v is None:
            return None
        return DataNature.from_any(v)

    @field_validator('source', mode='before')
    @classmethod
    def _validate_source(cls, v):
        """清洗脏 source 值"""
        if v is None:
            return "missing"
        _FIX = {"嘲笑": "mock", "计算": "calculated", "模拟": "mock", "真实": "akshare"}
        _OK  = {"akshare","tavily","calculated","official","missing","mock","unknown"}
        s = str(v).strip()
        return _FIX.get(s, s if s in _OK else "unknown")

    @property
    def safe_nature_key(self) -> str:
        """返回安全的 nature key，可直接用于 _NATURE_DISPLAY 查找"""
        if self.nature is None:
            return "missing"
        return self.nature.value if hasattr(self.nature, 'value') else "missing"


class PeerRank(BaseModel):
    rank:       Optional[int] = None
    total:      Optional[int] = None
    percentile: Optional[float] = None   # 0-100，越小越好

    @field_validator("percentile")
    @classmethod
    def check_percentile(cls, v):
        if v is not None and not (0.0 <= v <= 100.0):
            raise ValueError(f"percentile={v} 不在 0-100 范围内")
        return v


class ManagerInfo(BaseModel):
    name:             str
    experience_years: Optional[float] = None
    managed_funds:    Optional[int] = None
    total_aum_bn:     Optional[float] = None   # 单位：亿元
    best_return_pct:  Optional[float] = None
    is_mock:          bool = False


class FundSnapshot(BaseModel):
    """一只基金在某一报告日期的完整快照"""
    code:           str
    report_date:    date
    name:           Optional[str] = None
    fund_type:      Optional[str] = None
    fund_company:   Optional[str] = None
    inception_date: Optional[date] = None
    run_days:       Optional[int] = None      # 由 data_quality 计算填入

    nav:               Optional[MetricSource] = None
    accumulated_nav:   Optional[MetricSource] = None
    fund_size_bn:      Optional[MetricSource] = None  # 亿元

    # 收益率（value 为百分比，如 45.2 代表 45.2%）
    return_since_inception: Optional[MetricSource] = None
    return_1m:   Optional[MetricSource] = None
    return_3m:   Optional[MetricSource] = None
    return_6m:   Optional[MetricSource] = None
    return_1y:   Optional[MetricSource] = None
    return_3y:   Optional[MetricSource] = None

    # 风险指标
    max_drawdown:  Optional[MetricSource] = None   # 正数，如 25.3
    volatility:    Optional[MetricSource] = None
    sharpe:        Optional[MetricSource] = None

    peer_rank:  Optional[PeerRank] = None
    managers:   list[ManagerInfo] = []

    # Benchmark（P3 新增）
    benchmark_name:          Optional[str] = None
    benchmark:               Optional[Any] = None    # V2.1新增：BenchmarkInfo 对象（benchmark_resolver）
    benchmark_return_pct:    Optional[MetricSource] = None
    alpha_pct:               Optional[MetricSource] = None  # 超额收益

    raw: dict[str, Any] = Field(default_factory=dict)

    # 持仓分析（Module 1：前十大重仓股）
    holdings_json: Optional[str] = None    # HoldingsAnalysis.to_json()


class DataQualityReport(BaseModel):
    level:               DataQualityLevel
    real_metric_count:   int = 0
    mock_metric_count:   int = 0
    missing_fields:      list[str] = []
    stale_fields:        list[str] = []
    contradictions:      list[str] = []
    warnings:            list[str] = []
    can_generate_rating: bool = False
    can_generate_report: bool = True
    run_days:            Optional[int] = None   # V2.2 新增：传递给渲染层


class ScoreBreakdown(BaseModel):
    history_score:   float
    sentiment_score: float
    risk_score:      float
    alpha_bonus:     float = 0.0    # P3：Alpha 加分
    total_score:     float
    confidence:      Literal["低", "中", "高"] = "低"
    rating:          str            # 适合配置/积极关注/谨慎关注/观察/信息不足/无法评级/回避
    rating_cap_reason: Optional[str] = None
    suitability:     str
