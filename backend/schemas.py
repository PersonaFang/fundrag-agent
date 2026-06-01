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
    REAL    = "real"      # 全部真实数据
    PARTIAL = "partial"   # 部分模拟或缺失
    MOCK    = "mock"      # 全部模拟
    FAILED  = "failed"    # 数据存在硬性矛盾


class DataNature(str, Enum):
    """单个指标的数据性质（V2.1 新增）"""
    REAL        = "real"        # 来自可信外部接口的真实数据
    CALCULATED  = "calculated"  # 由 real 数据计算得出
    MISSING     = "missing"     # 缺失，无法获取
    MOCK        = "mock"        # 模拟/降级数据
    SUSPICIOUS  = "suspicious"  # 数据存在疑问


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
