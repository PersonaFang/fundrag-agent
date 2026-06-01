# backend/holdings.py
"""
持仓分析模块：前十大重仓股拉取、集中度计算、行业分布
🌰 类比：查看基金"购物清单"——买了什么、买多少、押注哪些行业
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import date


# ============================================================
# 数据结构
# ============================================================

@dataclass
class HoldingStock:
    """单只重仓股"""
    rank:       int
    code:       str
    name:       str
    weight_pct: float
    industry:   Optional[str]
    is_mock:    bool = False


@dataclass
class HoldingsAnalysis:
    """前十大重仓股分析结果"""
    stocks:               list
    top10_weight_pct:     float
    top3_weight_pct:      float
    industry_dist:        dict
    concentration_level:  str
    as_of:                Optional[date]
    is_mock:              bool = False
    source:               str  = "akshare"

    def to_dict(self) -> dict:
        return {
            "stocks":               [asdict(s) for s in self.stocks],
            "top10_weight_pct":     self.top10_weight_pct,
            "top3_weight_pct":      self.top3_weight_pct,
            "industry_dist":        self.industry_dist,
            "concentration_level":  self.concentration_level,
            "as_of":                str(self.as_of) if self.as_of else None,
            "is_mock":              self.is_mock,
            "source":               self.source,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "HoldingsAnalysis":
        d = json.loads(text)
        stocks = [HoldingStock(**s) for s in d.get("stocks", [])]
        as_of_str = d.get("as_of")
        return cls(
            stocks=stocks,
            top10_weight_pct=d["top10_weight_pct"],
            top3_weight_pct=d["top3_weight_pct"],
            industry_dist=d["industry_dist"],
            concentration_level=d["concentration_level"],
            as_of=date.fromisoformat(as_of_str) if as_of_str else None,
            is_mock=d.get("is_mock", False),
            source=d.get("source", "akshare"),
        )


# ============================================================
# 集中度分级
# ============================================================

def _classify_concentration(top10_pct: float) -> str:
    """
    前十大合计持仓 → 集中度等级
    > 70% 高度集中（主题基金典型）
    40-70% 适度集中（均衡配置）
    < 40%  分散配置
    """
    if top10_pct >= 70:
        return "高"
    elif top10_pct >= 40:
        return "中"
    else:
        return "低"


# ============================================================
# Mock 数据（akshare 拉取失败时降级）
# ============================================================

def _mock_holdings(fund_code: str) -> HoldingsAnalysis:
    stocks = [
        HoldingStock(rank=i + 1, code=f"00000{i}", name=f"模拟股票{i + 1}",
                     weight_pct=round(10 - i * 0.5, 1), industry="模拟行业", is_mock=True)
        for i in range(10)
    ]
    top10 = sum(s.weight_pct for s in stocks)
    top3  = sum(s.weight_pct for s in stocks[:3])
    return HoldingsAnalysis(
        stocks=stocks,
        top10_weight_pct=round(top10, 2),
        top3_weight_pct=round(top3, 2),
        industry_dist={"模拟行业": 100.0},
        concentration_level=_classify_concentration(top10),
        as_of=None,
        is_mock=True,
        source="mock",
    )


# ============================================================
# 核心拉取函数
# ============================================================

def fetch_holdings(fund_code: str) -> HoldingsAnalysis:
    """
    拉取基金前十大重仓股（akshare）。
    失败时自动降级为 mock 数据并标记。
    akshare 接口：fund_portfolio_hold_em(symbol, date)
    """
    try:
        import akshare as ak
        import pandas as pd

        # 获取最新季度报告持仓（尝试当年）
        from datetime import datetime
        year = str(datetime.now().year)
        df: pd.DataFrame = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)

        if df is None or df.empty:
            print(f"⚠️ [holdings] {fund_code} 持仓数据为空，降级 mock")
            return _mock_holdings(fund_code)

        # 标准化列名
        col_map = {
            "股票代码": "code",
            "股票名称": "name",
            "占净值比例": "weight",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        required = {"code", "name", "weight"}
        if not required.issubset(set(df.columns)):
            missing = required - set(df.columns)
            print(f"⚠️ [holdings] 缺少列 {missing}，降级 mock")
            return _mock_holdings(fund_code)

        top10_df = df.head(10).copy()
        top10_df["weight"] = pd.to_numeric(top10_df["weight"], errors="coerce").fillna(0.0)

        stocks = []
        for _, row in top10_df.iterrows():
            industry = str(row.get("所在行业", row.get("industry", "未知")))
            stocks.append(HoldingStock(
                rank=len(stocks) + 1,
                code=str(row["code"]),
                name=str(row["name"]),
                weight_pct=round(float(row["weight"]), 2),
                industry=industry if industry not in ("nan", "未知", "") else None,
            ))

        top10_pct = round(sum(s.weight_pct for s in stocks), 2)
        top3_pct  = round(sum(s.weight_pct for s in stocks[:3]), 2)

        industry_dist: dict = {}
        for s in stocks:
            ind = s.industry or "其他"
            industry_dist[ind] = round(industry_dist.get(ind, 0.0) + s.weight_pct, 2)

        return HoldingsAnalysis(
            stocks=stocks,
            top10_weight_pct=top10_pct,
            top3_weight_pct=top3_pct,
            industry_dist=industry_dist,
            concentration_level=_classify_concentration(top10_pct),
            as_of=date.today(),
            is_mock=False,
            source="akshare",
        )

    except Exception as e:
        print(f"❌ [holdings] 持仓拉取异常：{e}，降级 mock")
        return _mock_holdings(fund_code)


# ============================================================
# 持仓表格渲染（供 report_renderer 调用）
# ============================================================

def render_holdings_table(holdings: HoldingsAnalysis) -> str:
    """
    渲染前十大重仓股 Markdown 表格。
    ✅ is_mock=True 时在标题行加警告
    """
    mock_tag  = "（⚠️ 模拟数据，仅供演示）" if holdings.is_mock else ""
    as_of_str = str(holdings.as_of) if holdings.as_of else "未知"

    lines = [
        f"**数据截止：** {as_of_str}　"
        f"**前十大合计：** {holdings.top10_weight_pct}%　"
        f"**前三大合计：** {holdings.top3_weight_pct}%　"
        f"**集中度：** {holdings.concentration_level}{mock_tag}",
        "",
        "| 排名 | 股票代码 | 股票名称 | 持仓占比 | 行业 |",
        "|:----:|:--------:|:--------:|:-------:|:----:|",
    ]
    for s in holdings.stocks:
        industry_display = s.industry or "—"
        lines.append(
            f"| {s.rank} | {s.code} | {s.name} | {s.weight_pct}% | {industry_display} |"
        )

    # 行业分布小结（仅真实数据）
    if holdings.industry_dist and not holdings.is_mock:
        lines.append("")
        lines.append("**行业分布：**")
        sorted_ind = sorted(holdings.industry_dist.items(), key=lambda x: -x[1])
        dist_str = "　".join([f"{ind}({pct}%)" for ind, pct in sorted_ind[:5]])
        lines.append(f"> {dist_str}")

    return "\n".join(lines)
