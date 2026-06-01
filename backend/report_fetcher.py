# backend/report_fetcher.py
"""
基金定期报告拉取模块
数据源：
  1. akshare fund_open_fund_report_em → 定期报告列表
  2. 天天基金报告 PDF 直链下载
  3. PDF 文本提取（pdfplumber）
  4. LLM 提炼经理观点（复用 DeepSeek）

🌰 类比：图书馆员——找到最新季报，把「经理报告书」那章复印出来
"""

from __future__ import annotations
import os
import re
import json
import hashlib
import tempfile
from dataclasses import dataclass
from datetime import date
from typing import Optional
from pathlib import Path

# 缓存目录
_CACHE_DIR = Path("cache/reports")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 报告全文过长，只取前 N 字符交给 LLM
_MAX_TEXT_LENGTH = 4000


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PeriodicReport:
    """基金定期报告摘要"""
    fund_code:        str
    report_type:      str
    report_date:      str
    manager_comment:  Optional[str]
    strategy_summary: Optional[str]
    benchmark_desc:   Optional[str]
    raw_text_snippet: Optional[str]
    source:           str  = "official"
    is_mock:          bool = False

    def to_json(self) -> str:
        import dataclasses
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "PeriodicReport":
        return cls(**json.loads(text))


# ============================================================
# PDF 工具
# ============================================================

def _extract_text_from_pdf_url(url: str, fund_code: str) -> Optional[str]:
    """下载 PDF → 提取文本（pdfplumber），结果缓存"""
    cache_key  = hashlib.md5(url.encode()).hexdigest()[:12]
    cache_path = _CACHE_DIR / f"{fund_code}_{cache_key}.txt"

    if cache_path.exists():
        print(f"   [report_fetcher] 使用缓存：{cache_path.name}")
        return cache_path.read_text(encoding="utf-8")

    try:
        import requests
        import pdfplumber

        print(f"   [report_fetcher] 下载报告 PDF：{url[:80]}...")
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FundRAG/2.2)"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        full_text = []
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages[:30]:
                text = page.extract_text()
                if text:
                    full_text.append(text)

        os.unlink(tmp_path)
        result = "\n".join(full_text)
        cache_path.write_text(result, encoding="utf-8")
        return result

    except ImportError:
        print("❌ [report_fetcher] 缺少依赖：pip install pdfplumber requests")
        return None
    except Exception as e:
        print(f"❌ [report_fetcher] PDF 提取失败：{e}")
        return None


# ============================================================
# 章节提取
# ============================================================

_MANAGER_SECTION_PATTERNS = [
    re.compile(
        r'(?:第[一二三四五六七八九十]+部分|[一二三四五六七八九十]+[、.．])\s*'
        r'(?:基金经理报告|管理人报告|投资管理人报告|基金管理人报告)'
        r'(.{200,3000}?)(?=第[一二三四五六七八九十]+部分|[一二三四五六七八九十]+[、.．]|$)',
        re.DOTALL
    ),
    re.compile(
        r'(?:基金经理报告|管理人投资报告)\s*\n(.{200,2000}?)(?=\n[一二三四五六七八九十]+[、.]|\Z)',
        re.DOTALL
    ),
]


def _extract_manager_section(full_text: str) -> Optional[str]:
    """从报告全文中提取「基金经理报告」章节"""
    for pattern in _MANAGER_SECTION_PATTERNS:
        m = pattern.search(full_text)
        if m:
            return m.group(1).strip()[:_MAX_TEXT_LENGTH]
    idx = full_text.find("业绩比较基准")
    if idx > 0:
        return full_text[max(0, idx - 200):idx + 1000]
    return full_text[:_MAX_TEXT_LENGTH]


# ============================================================
# akshare 报告列表
# ============================================================

def _get_latest_report_url(fund_code: str) -> Optional[tuple]:
    """返回 (报告类型, PDF_URL)，优先级：季报 > 半年报 > 年报"""
    try:
        import akshare as ak
        df = ak.fund_open_fund_report_em(fund=fund_code)
        if df is None or df.empty:
            return None
        for report_type_kw in ["季报", "半年报", "年报"]:
            subset = df[df["报告类型"].str.contains(report_type_kw, na=False)]
            if not subset.empty:
                latest = subset.sort_values("报告日期", ascending=False).iloc[0]
                url = latest.get("报告链接") or latest.get("下载链接")
                if url:
                    return report_type_kw, str(url)
        return None
    except Exception as e:
        print(f"⚠️ [report_fetcher] 报告列表获取失败：{e}")
        return None


# ============================================================
# LLM 提炼经理观点
# ============================================================

def _llm_extract_manager_comment(raw_text: str, fund_code: str) -> tuple:
    """用 LLM 从原始文本中提炼：经理观点（≤200字）+ 投资策略摘要（≤100字）"""
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            temperature=0,
            max_tokens=600,
        )
        prompt = f"""以下是基金 {fund_code} 定期报告中「基金经理报告」章节的原文节选：

---
{raw_text[:3000]}
---

请提炼：
1. 基金经理对市场和持仓的核心观点（≤200字，客观引述，不加评论）
2. 基金投资策略摘要（≤100字）

输出格式（严格遵守）：
经理观点：[内容]
策略摘要：[内容]

⚠️ 只能引用原文已有内容，不得推断或编造任何数字、股票名称或业绩数据。"""

        response = llm.invoke(prompt)
        content  = response.content
        comment_m  = re.search(r'经理观点[：:]\s*(.+?)(?=策略摘要|$)', content, re.DOTALL)
        strategy_m = re.search(r'策略摘要[：:]\s*(.+?)$', content, re.DOTALL)
        comment  = comment_m.group(1).strip()[:300]  if comment_m  else "提炼失败"
        strategy = strategy_m.group(1).strip()[:150] if strategy_m else "提炼失败"
        return comment, strategy
    except Exception as e:
        print(f"❌ [report_fetcher] LLM 提炼失败：{e}")
        return "基金经理观点获取失败", "投资策略获取失败"


# ============================================================
# Mock 降级
# ============================================================

def _mock_report(fund_code: str) -> PeriodicReport:
    return PeriodicReport(
        fund_code=fund_code,
        report_type="季报（模拟）",
        report_date=str(date.today()),
        manager_comment="⚠️ 此为模拟数据，真实经理观点待接口恢复后更新。",
        strategy_summary="⚠️ 模拟：投资于高成长潜力行业龙头。",
        benchmark_desc=None,
        raw_text_snippet=None,
        is_mock=True,
    )


# ============================================================
# 主入口
# ============================================================

def fetch_periodic_report(fund_code: str) -> PeriodicReport:
    """
    拉取最新定期报告，提炼经理观点。
    失败时自动降级为 mock。
    """
    print(f"\n📄 [report_fetcher] 开始拉取 {fund_code} 定期报告...")

    result = _get_latest_report_url(fund_code)
    if not result:
        print("   报告列表为空，降级 mock")
        return _mock_report(fund_code)

    report_type, url = result
    print(f"   最新报告类型：{report_type}")

    full_text = _extract_text_from_pdf_url(url, fund_code)
    if not full_text:
        print("   PDF 提取失败，降级 mock")
        return _mock_report(fund_code)

    section_text = _extract_manager_section(full_text)
    comment, strategy = _llm_extract_manager_comment(section_text or full_text, fund_code)

    bench_match = re.search(r'业绩比较基准[：:]\s*([^\n]{10,150})', full_text)
    bench_desc  = bench_match.group(1).strip() if bench_match else None

    return PeriodicReport(
        fund_code=fund_code,
        report_type=report_type,
        report_date=str(date.today()),
        manager_comment=comment,
        strategy_summary=strategy,
        benchmark_desc=bench_desc,
        raw_text_snippet=section_text[:500] if section_text else None,
        source="official",
        is_mock=False,
    )
