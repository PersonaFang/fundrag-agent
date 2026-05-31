# 📈 FundRAG Multi-Agent — 基金智能投研助手

> 基于 LangGraph + Multi-Agent 架构的 A 股公募基金智能分析系统

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.x-green)](https://github.com/langchain-ai/langgraph)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.45-red)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🏗️ 系统架构

```
用户输入基金代码
        │
        ▼
┌──────────────────┐
│  📊 行情分析师   │  akshare 实时数据
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  🔍 数据质量验证  │  检查真实/模拟数据，生成质量摘要
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  📰 舆情研究员   │  Tavily 实时新闻
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  ⚠️ 风险控制官   │  内置风险评分模型
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────┐
│  📝 报告撰写员（DeepSeek v4-pro）│  含数据质量说明章节
└────────┬─────────────────────────┘
         ▼
   综合投研报告  →  Streamlit 展示 / Markdown 导出
```

### 核心组件

| 组件 | 职责 | 使用工具 / 模型 |
|------|------|----------------|
| 📊 行情分析师 | 量化数据分析（净值/回撤/排名/经理） | akshare 数据接口 · DeepSeek v4-flash |
| 🔍 数据质量验证 | 检测真实 vs 模拟数据，生成质量摘要 | 无外部调用（纯逻辑） |
| 📰 舆情研究员 | 新闻情绪分析（基金/行业/政策） | Tavily 实时搜索 · DeepSeek v4-flash |
| ⚠️ 风险控制官 | 风险量化评估（评分/等级/维度） | 内置风险模型 · DeepSeek v4-flash |
| 📝 报告撰写员 | 综合研判总结（含数据质量章节） | DeepSeek v4-pro（思考模式开启） |

---

## ✨ 技术亮点

1. **Multi-Agent 协作**：5 节点流水线（行情→数据验证→舆情→风控→报告），LangGraph 1.2 状态机统一调度
2. **真实金融数据**：集成 akshare 1.18.x（A 股数据）+ Tavily（实时新闻），接口参数已与最新版对齐
3. **数据质量可见**：`validate_data` 节点检测真实/模拟数据，最终报告包含「数据质量说明」章节，不混淆真假数据
4. **容错设计**：任一 Agent 失败不中断流程，自动降级至模拟数据并明确标注，错误统一收集
5. **DeepSeek 双模型**：工具调用 Agent 用 v4-flash（快速），报告撰写 Agent 用 v4-pro + 思考模式（深度推理）
6. **缓存优化**：基金数据本地 JSON 缓存（基本信息 24h / 业绩数据 1h），减少重复 API 调用
7. **完整产品**：Streamlit 前端 + 实时进度 + Tab 分组 + 历史记录 + Markdown 导出

---

## 🚀 快速开始

### 1. 克隆 & 安装依赖

```bash
git clone https://github.com/your-username/fundrag-agent.git
cd fundrag-agent
python -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入真实密钥
```

### 3. 运行测试（不消耗 API）

```bash
python tests/test_pipeline.py
# 输入 n 跳过完整流程测试
```

### 4. 启动前端

```bash
streamlit run frontend/app.py
# 浏览器打开 http://localhost:8501
```

---

## 🔑 需要申请的 API

| API | 申请地址 | 用途 | 费用 |
|-----|----------|------|------|
| DeepSeek API Key | https://platform.deepseek.com | v4-flash（工具调用）+ v4-pro（报告生成） | 按量计费，每次分析约 ¥0.1-0.3 |
| Tavily API Key | https://tavily.com | 实时新闻搜索 | 每月 1000 次免费 |
| akshare | 无需申请 | A 股 / 基金数据 | 完全免费 |

---

## 📁 项目结构

```
fundrag-agent/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── .streamlit/
│   └── secrets.toml.example
├── backend/
│   ├── __init__.py
│   ├── data_fetcher.py      # 数据获取（akshare + 缓存 + mock）
│   ├── tools.py             # 6 个 LangChain 工具
│   ├── agents.py            # 4 个 Agent 的 Prompt
│   ├── graph.py             # LangGraph 状态机（核心）
│   └── report_generator.py  # Markdown/PDF 导出
├── frontend/
│   └── app.py               # Streamlit 主界面
├── tests/
│   └── test_pipeline.py     # 三层测试
├── cache/                   # 数据缓存（自动生成，不上传）
└── reports/                 # 生成的报告（不上传）
```

---

## ⚠️ 免责声明

本系统仅供学习演示，不构成任何投资建议。基金有风险，投资需谨慎。过往业绩不代表未来表现。
