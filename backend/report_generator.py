# backend/report_generator.py
"""
报告导出模块
把 Agent 生成的 Markdown 报告导出为 Markdown 文件或 PDF

🌰 类比：把研究报告从「草稿本」打印成「正式文件」

补充决策：
- PDF 导出使用 fpdf2，中文支持通过系统字体实现
- 如果系统没有中文字体，自动降级为 Markdown 格式
- 支持的系统字体路径：macOS / Linux / Windows 常见路径
"""

import os
from datetime import datetime
from typing import Optional


def save_markdown_report(content: str, fund_code: str) -> str:
    """
    将报告保存为 Markdown 文件

    参数:
        content:   报告的 Markdown 文本内容
        fund_code: 基金代码，用于命名文件

    返回:
        保存的文件路径

    🌰 类比：把分析结果保存到「电子档案」，随时可以翻阅
    """
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/fund_{fund_code}_{timestamp}.md"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"💾 Markdown 报告已保存：{filename}")
        return filename
    except Exception as e:
        print(f"⚠️  Markdown 报告保存失败：{e}")
        return ""


def _find_chinese_font() -> Optional[str]:
    """
    在系统中查找支持中文的字体文件

    🌰 类比：去字体库找一本「支持中文的字典」

    优先顺序：macOS → Linux → Windows
    """
    candidate_paths = [
        # macOS 系统字体
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux 常见中文字体（需安装 fonts-wqy-zenhei 等）
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        # Windows 系统字体
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            return path
    return None


def generate_pdf_report(markdown_content: str, fund_code: str) -> str:
    """
    将 Markdown 报告导出为 PDF

    参数:
        markdown_content: Markdown 格式的报告文本
        fund_code:        基金代码，用于命名文件

    返回:
        PDF 文件路径（如果 PDF 生成失败，降级返回 Markdown 文件路径）

    🌰 类比：把电子文档「打印」成带封面的正式报告
    """
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_filename = f"reports/fund_{fund_code}_{timestamp}.pdf"

    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # 尝试加载中文字体
        font_path = _find_chinese_font()
        use_chinese_font = False

        if font_path:
            try:
                # fpdf2 支持 .ttc 文件，但部分版本需要指定 index
                pdf.add_font("ChineseFont", fname=font_path, uni=True)
                use_chinese_font = True
                print(f"✅ 已加载中文字体：{font_path}")
            except Exception as e:
                print(f"⚠️  中文字体加载失败：{e}，将使用英文字体")

        if use_chinese_font:
            # 渲染中文内容
            for line in markdown_content.split("\n"):
                # 简单清理 Markdown 符号
                clean_line = (
                    line.replace("**", "")
                    .replace("##", "")
                    .replace("#", "")
                    .replace("*", "")
                    .replace("|", " ")
                    .strip()
                )
                if not clean_line:
                    pdf.ln(3)
                    continue
                # 标题行字号大一点
                if line.startswith("#"):
                    pdf.set_font("ChineseFont", size=14)
                else:
                    pdf.set_font("ChineseFont", size=11)
                try:
                    pdf.multi_cell(0, 7, txt=clean_line[:120])
                except Exception:
                    pdf.multi_cell(0, 7, txt="[内容包含无法渲染的字符]")
        else:
            # 没有中文字体，写英文说明
            pdf.set_font("Helvetica", size=12)
            pdf.cell(0, 10, txt=f"FundRAG Analysis Report - Fund {fund_code}", ln=True)
            pdf.cell(0, 10, txt=f"Generated: {timestamp}", ln=True)
            pdf.ln(5)
            pdf.set_font("Helvetica", size=9)
            pdf.multi_cell(0, 6, txt=(
                "Note: Chinese fonts are not available on this system. "
                "Please download the Markdown report for full content. "
                "Install fonts-wqy-zenhei (Linux) or use macOS/Windows for Chinese PDF output."
            ))

        pdf.output(pdf_filename)
        print(f"📄 PDF 报告已生成：{pdf_filename}")
        return pdf_filename

    except ImportError:
        print("⚠️  fpdf2 未安装，降级为 Markdown 格式")
        return save_markdown_report(markdown_content, fund_code)
    except Exception as e:
        print(f"⚠️  PDF 生成失败（{e}），降级为 Markdown 格式")
        return save_markdown_report(markdown_content, fund_code)
