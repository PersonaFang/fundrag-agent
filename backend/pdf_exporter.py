# backend/pdf_exporter.py
"""
Markdown → PDF 导出模块
技术栈：markdown2（MD→HTML）+ WeasyPrint（HTML→PDF）
备用方案：xhtml2pdf

安装：
  pip install markdown2 weasyprint
  # Ubuntu 系统依赖：
  # apt-get install libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk

🌰 类比：把报告打印成 PDF——格式固定，方便存档和分发
"""

from __future__ import annotations
import io
import re
from datetime import date
from typing import Optional


# ============================================================
# CSS 样式（内嵌，确保 PDF 字体/布局正确）
# ============================================================

_REPORT_DATE = str(date.today())

_PDF_CSS = f"""
@page {{
    size: A4;
    margin: 2cm 2.5cm 2cm 2.5cm;
    @top-center {{
        content: "FundRAG 基金投研报告";
        font-size: 9pt;
        color: #888;
    }}
    @bottom-right {{
        content: "第 " counter(page) " 页 / 共 " counter(pages) " 页";
        font-size: 9pt;
        color: #888;
    }}
    @bottom-left {{
        content: "生成日期：{_REPORT_DATE}";
        font-size: 9pt;
        color: #888;
    }}
}}

body {{
    font-family: "Source Han Sans CN", "Noto Sans CJK SC",
                 "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
    font-size: 10.5pt;
    line-height: 1.7;
    color: #222;
}}

.cover-page {{
    text-align: center;
    padding-top: 8cm;
    page-break-after: always;
}}
.cover-title {{ font-size: 24pt; font-weight: bold; color: #1a3a5c; margin-bottom: 0.5cm; }}
.cover-subtitle {{ font-size: 14pt; color: #555; margin-bottom: 2cm; }}
.cover-meta {{ font-size: 11pt; color: #777; line-height: 2; }}
.cover-disclaimer {{
    margin-top: 3cm; font-size: 9pt; color: #aaa;
    border-top: 1px solid #ddd; padding-top: 0.5cm;
}}

h1 {{ font-size: 18pt; color: #1a3a5c; border-bottom: 2px solid #1a3a5c;
      padding-bottom: 4px; margin-top: 1cm; }}
h2 {{ font-size: 14pt; color: #2c5f8a; margin-top: 0.8cm;
      page-break-before: auto; page-break-after: avoid; }}
h3 {{ font-size: 12pt; color: #3a7ab8; }}

table {{ width: 100%; border-collapse: collapse; margin: 0.5cm 0; font-size: 9.5pt; }}
th {{ background-color: #1a3a5c; color: white; padding: 6px 10px;
      text-align: left; font-weight: 600; }}
td {{ padding: 5px 10px; border-bottom: 1px solid #e0e0e0; vertical-align: top; }}
tr:nth-child(even) td {{ background-color: #f8f9fa; }}

blockquote {{
    border-left: 4px solid #f0ad4e; background: #fffbf0;
    margin: 0.4cm 0; padding: 0.3cm 0.5cm;
    font-size: 9.5pt; color: #555;
}}

code {{
    background: #f4f4f4; padding: 2px 5px; border-radius: 3px;
    font-size: 9pt; font-family: "Courier New", monospace;
}}

.disclaimer-section {{
    background: #fff8e1; border: 1px solid #ffcc02; border-radius: 5px;
    padding: 0.4cm 0.6cm; margin-top: 0.5cm; font-size: 9pt;
}}

table {{ page-break-inside: avoid; }}
"""


# ============================================================
# Markdown → HTML
# ============================================================

def _markdown_to_html(md_text: str) -> str:
    """MD → HTML，优先 markdown2，降级 markdown，最终降级基础转换"""
    try:
        import markdown2
        extras = ["tables", "fenced-code-blocks", "strike", "header-ids", "break-on-newline"]
        return markdown2.markdown(md_text, extras=extras)
    except ImportError:
        pass
    try:
        import markdown
        return markdown.markdown(md_text, extensions=["tables", "fenced_code", "toc"])
    except ImportError:
        pass
    paragraphs = md_text.split("\n\n")
    return "\n".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())


# ============================================================
# 封面页
# ============================================================

def _build_cover_html(fund_code: str, fund_name: str, report_date: str) -> str:
    return f"""
<div class="cover-page">
    <div class="cover-title">📈 基金投研分析报告</div>
    <div class="cover-subtitle">{fund_name}（{fund_code}）</div>
    <div class="cover-meta">
        报告生成日期：{report_date}<br>
        数据来源：akshare / Tavily / 官方公告<br>
        分析系统：FundRAG Multi-Agent V2.2
    </div>
    <div class="cover-disclaimer">
        ⚠️ 本报告由 AI 系统自动生成，仅供信息整理和学习演示，<br>
        <strong>不构成任何投资建议</strong>。基金投资有风险，过往业绩不代表未来表现。
    </div>
</div>
"""


# ============================================================
# 完整 HTML 组装
# ============================================================

def _build_full_html(report_md: str, fund_code: str, fund_name: str, report_date: str) -> str:
    cover = _build_cover_html(fund_code, fund_name, report_date)
    body  = _markdown_to_html(report_md)
    # 标记免责声明区
    body = re.sub(
        r'(<h2[^>]*>.*?风险提示.*?</h2>)',
        r'<div class="disclaimer-section">\1',
        body,
        flags=re.IGNORECASE | re.DOTALL
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>FundRAG 基金报告 - {fund_name}（{fund_code}）</title>
<style>{_PDF_CSS}</style>
</head>
<body>
{cover}
{body}
</body>
</html>"""


# ============================================================
# HTML → PDF
# ============================================================

def _html_to_pdf_weasyprint(html: str) -> Optional[bytes]:
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except ImportError:
        print("❌ [pdf_exporter] WeasyPrint 未安装：pip install weasyprint")
        return None
    except Exception as e:
        print(f"❌ [pdf_exporter] WeasyPrint 失败：{e}")
        return None


def _html_to_pdf_xhtml2pdf(html: str) -> Optional[bytes]:
    try:
        from xhtml2pdf import pisa
        buffer = io.BytesIO()
        status = pisa.CreatePDF(html.encode("utf-8"), dest=buffer, encoding="utf-8")
        return None if status.err else buffer.getvalue()
    except ImportError:
        print("❌ [pdf_exporter] xhtml2pdf 未安装：pip install xhtml2pdf")
        return None
    except Exception as e:
        print(f"❌ [pdf_exporter] xhtml2pdf 失败：{e}")
        return None


# ============================================================
# 主导出函数
# ============================================================

def export_to_pdf(
    report_md:   str,
    fund_code:   str = "未知",
    fund_name:   str = "基金报告",
    report_date: str = "",
) -> Optional[bytes]:
    """
    将 Markdown 报告导出为 PDF 字节流。
    优先 WeasyPrint，失败则 xhtml2pdf。
    返回 bytes 供 st.download_button 使用，失败返回 None。
    """
    if not report_date:
        report_date = str(date.today())

    print(f"📄 [pdf_exporter] 开始生成 PDF：{fund_code} {fund_name}")
    html = _build_full_html(report_md, fund_code, fund_name, report_date)

    pdf_bytes = _html_to_pdf_weasyprint(html)
    if pdf_bytes:
        print(f"✅ [pdf_exporter] WeasyPrint 成功，{len(pdf_bytes)/1024:.1f} KB")
        return pdf_bytes

    pdf_bytes = _html_to_pdf_xhtml2pdf(html)
    if pdf_bytes:
        print(f"✅ [pdf_exporter] xhtml2pdf 成功，{len(pdf_bytes)/1024:.1f} KB")
        return pdf_bytes

    print("❌ [pdf_exporter] 所有 PDF 引擎均不可用")
    return None


# ============================================================
# 快速测试入口
# ============================================================

if __name__ == "__main__":
    test_md = """# 📋 110022 基金分析报告

## 一、数据质量说明
✅ 核心指标均来自外部数据接口

## 二、基金基本信息
| 项目 | 内容 |
|------|------|
| 基金类型 | 混合型 |

## 八、⚠️ 风险提示
本报告不构成任何投资建议。
"""
    pdf = export_to_pdf(test_md, "110022", "易方达消费行业", str(date.today()))
    if pdf:
        with open("/tmp/test_report.pdf", "wb") as f:
            f.write(pdf)
        print("✅ 测试 PDF 已保存到 /tmp/test_report.pdf")
    else:
        print("❌ PDF 生成失败（请安装 weasyprint 或 xhtml2pdf）")
