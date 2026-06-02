# 📈 FundRAG Multi-Agent V2.5 — 基金智能投研助手

> 基于 LangGraph + Multi-Agent 架构的 A 股公募基金智能分析系统

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.2-green)](https://github.com/langchain-ai/langgraph)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.45-red)](https://streamlit.io)
[![Tests](https://img.shields.io/badge/Tests-104%20passed-brightgreen)](#测试)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🎯 核心原则

**数据、评分、评级由代码决定；LLM 只负责解释文字。**

- 所有结构化字段（评级/来源/置信度/风险等级）由代码枚举决定
- 所有数字和结论由代码计算，LLM 不得修改
- 最终报告通过 7 层质量守卫检测，自动修复脏词后输出

---

## 🏗️ V2.5 系统架构

### 11 节点流水线

```
输入基金代码
     │
     ▼
┌─────────────────┐
│ fetch_snapshot  │ ← akshare 拉取数据 + 持仓分析（holdings）
└────────┬────────┘
         │
         ▼
┌─────────────────┐     数据矛盾时
│ validate_quality│ ──────────────→ data_issue_report → END
└────────┬────────┘
         │ 数据正常
         ▼
┌─────────────────┐
│  scoring_node   │ ← 确定性评分（代码裁判，LLM 不介入）
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ periodic_report  │ ← 定期报告 PDF 拉取 + LLM 提炼经理观点
└────────┬─────────┘
         │
         ▼
┌─────────────────┐
│  market_agent   │ ← LLM 解释行情数据
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ sentiment_agent  │ ← Tavily 搜索 + LLM 多空舆情分析
└────────┬─────────┘
         │
         ▼
┌─────────────────┐
│   risk_agent    │ ← LLM 解释风险评分
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  cross_check    │ ← 一致性校验（时间窗口/排名/禁用词）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  render_report  │ ← 模板渲染（代码填数字，LLM 只填解释段落）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  output_guard   │ ← 7 层质量守卫 + 自动修复
└────────┬────────┘
         │
         ▼
   最终投研报告（Markdown / PDF）
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 数据拉取 | `data_fetcher.py` | akshare 实时数据 + 缓存 + 降级 mock + V2.5 多接口补全 |
| 数据契约 | `schemas.py` | FundSnapshot / DataQualityReport / ScoreResult |
| 数据质量 | `data_quality.py` | 矛盾检测 / limited 等级 / run_days 计算 |
| 评分引擎 | `scoring.py` | 确定性评分 4 路径决策树 + compute_risk_level |
| 基准解析 | `benchmark_resolver.py` | 20 关键词规则 + 不匹配警告 |
| 报告渲染 | `report_renderer.py` | 模板填充，DataNature 四重防御 |
| 质量守卫 | `output_guard.py` | 禁用词 / 非法标题 / 脏值 4 步自动修复 |
| 常量定义 | `constants.py` | 全局合法值白名单（评级/来源/风险等级） |
| 值清洗 | `value_cleaner.py` | normalize_rating / auto_fix_text |
| 持仓分析 | `holdings.py` | 前十大重仓股拉取 + 集中度 + 行业分布 |
| 定期报告 | `report_fetcher.py` | 季报/半年报 PDF 下载 + LLM 提炼经理观点 |
| PDF 导出 | `pdf_exporter.py` | Markdown → WeasyPrint/xhtml2pdf |
| 数据适配器 | `data_adapters/` | Wind / Choice / akshare 统一接口层 |

---

## ✨ 功能特性

### P0：确定性评分与报告渲染

- **4 路径评分决策树**：矛盾数据 → 无法评级 / 含 mock → 信息不足 / 次新基金 → 持续观察 / 正常 → 综合评分
- **评级白名单校验**：所有评级必须在 `ALLOWED_RATINGS` 中，LLM 非法输出自动映射 `无法评级`
- **适合人群白名单**：`_SUITABILITY_SAFE` 字典直接映射，不经过 AUTO_FIX 防止乱码
- **DataNature 四重防御**：`_missing_()` 枚举兜底 + `_VALID_NATURE_KEYS` 白名单 + 中文旧值兼容 + try/except 包裹

### P1：数据质量体系

- **5 级数据质量**：`real` / `limited`（次新基金）/ `partial`（含 mock）/ `failed`（矛盾）/ `unavailable`
- **数据性质溯源**：每个指标标注 `real` / `calculated` / `mock` / `suspicious` / `missing`
- **指标表格**：列名「截止日期」hardcoded，来源「嘲笑」→「mock」本地清洗，`None` → 「数据缺失」
- **基准解析**：白酒/纳斯达克100等20条关键词规则，声明基准不符时自动警告

### P2：7 层质量守卫

output_guard 按顺序执行：

1. BANNED_WORDS 集合扫描（60+ 禁用词）
2. 额外正则检测（DataNature 透传 / 字段名泄漏 / 来源脏值等 17 类）
3. 非法结论标题检测（📌方案/理念/概念/推断/修正结论等）
4. 模拟数据 + 高置信度矛盾检测
5. 必要章节检查
6. 重复章节检测
7. 未替换占位符检测

**自动修复 4 步流水线**：本地优先规则 → AUTO_FIX_MAP（按长度降序）→ 正则修复 → 字段名清除

### P4：V2.5 多接口交叉补全

`data_fetcher.py` 中新增 `enrich_snapshot_with_multi_source()`，在主快照构建完成后自动补全缺失字段：

| 字段 | 补全接口 | 说明 |
|------|---------|------|
| `return_1y` / `return_3y` | `fund_open_fund_rank_em(全部)` | 东方财富基金排行，含近1/3/5年收益 |
| `benchmark_return_pct` | `fund_open_fund_info_em(累计收益率走势)` | 取第二列最新值作为同期基准收益 |
| `volatility` | `fund_open_fund_info_em(单位净值走势)` | 日收益率 std × √250，年化波动率 |
| `sharpe` | 同上（计算得出） | (年化收益 - 1.5%) / 年化波动率 |

- 只填充 `value=None` 的字段，**不覆盖已有真实数据**
- `nature` 字段标注为 `REAL`（排行/基准）或 `CALCULATED`（波动率/Sharpe）
- 接口间自动 sleep 0.3 s，避免 akshare 频率限制
- 任意接口失败均静默降级，不影响主流程

### P3：五大扩展模块

| 模块 | 功能 |
|------|------|
| 持仓分析 | 前十大重仓股 / 集中度 / 行业分布，报告新增第九章节 |
| 数据适配器 | Wind / Choice / akshare 统一接口，`DATA_SOURCE=auto` 自动降级 |
| 定期报告 | 季报/半年报 PDF 拉取，LLM 提炼经理观点，报告新增第十章节 |
| 用户认证 | Streamlit 登录页，SHA-256/bcrypt 双格式，5 次失败锁定 |
| PDF 导出 | 封面页 + 完整样式，WeasyPrint/xhtml2pdf 双引擎 |

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
# 编辑 .env，填入以下密钥：
# DEEPSEEK_API_KEY=sk-...
# DEEPSEEK_BASE_URL=https://api.deepseek.com
# TAVILY_API_KEY=tvly-...
# DATA_SOURCE=auto           # 数据源：auto / wind / choice / akshare
```

### 3. 运行测试

```bash
# 单元测试（不调用 API，约 2 秒）
venv/bin/python -m pytest tests/ --ignore=tests/test_pipeline.py -q
# 预期：104 passed

# 集成测试（会调用 DeepSeek API，约 ¥0.03-0.08）
python tests/test_pipeline.py
# 输入 n 跳过完整流程测试
```

### 4. 启动前端

```bash
streamlit run frontend/app.py
# 浏览器打开 http://localhost:8501
```

---

## 🔑 需要配置的 API

| API | 申请地址 | 用途 | 费用 |
|-----|----------|------|------|
| DeepSeek API Key | https://platform.deepseek.com | 行情/舆情/风险解释（v4-flash）| 按量计费，每次约 ¥0.1-0.3 |
| Tavily API Key | https://tavily.com | 实时新闻搜索 | 每月 1000 次免费 |
| akshare | 无需申请 | A 股 / 基金数据 | 完全免费 |
| Wind（可选）| Wind 终端授权 | 商业数据源（精确度更高）| 商业授权 |
| Choice（可选）| 东方财富企业账号 | 商业数据源 | 商业授权 |

---

## 📁 项目结构

```
fundrag-agent/
├── README.md
├── requirements.txt
├── .env.example
├── .streamlit/
│   └── secrets.toml             # 认证配置（可选）
├── backend/
│   ├── schemas.py               # 数据契约（FundSnapshot / DataNature 枚举）
│   ├── constants.py             # 全局合法值白名单
│   ├── value_cleaner.py         # 值清洗（normalize_rating / auto_fix_text）
│   ├── data_fetcher.py          # akshare 数据拉取 + 缓存 + 降级 + V2.5 多接口补全
│   ├── data_quality.py          # 数据质量校验（5 级 / run_days 计算）
│   ├── scoring.py               # 确定性评分（4 路径 + compute_risk_level）
│   ├── benchmark_resolver.py    # 基准指数解析（20 关键词规则）
│   ├── report_renderer.py       # 模板渲染 V2.4（DataNature 四重防御）
│   ├── output_guard.py          # 7 层质量守卫 + 4 步自动修复
│   ├── agents.py                # 三个 Agent Prompt（市场/舆情/风险）
│   ├── graph.py                 # LangGraph 11 节点状态机（核心）
│   ├── tools.py                 # LangChain 工具（7 个）
│   ├── holdings.py              # 前十大重仓股分析（Module 1）
│   ├── report_fetcher.py        # 定期报告 PDF 拉取（Module 3）
│   ├── pdf_exporter.py          # Markdown→PDF 导出（Module 5）
│   ├── cache_cleaner.py         # 脏缓存自动清理
│   ├── benchmark.py             # 基准收益率计算
│   ├── data_adapters/           # 数据源适配器（Module 2）
│   │   ├── base_adapter.py      # 抽象基类
│   │   ├── akshare_adapter.py   # akshare 实现
│   │   ├── wind_adapter.py      # Wind 实现（需授权）
│   │   ├── choice_adapter.py    # Choice 实现（需授权）
│   │   └── adapter_factory.py   # 工厂（DATA_SOURCE 环境变量选择）
│   └── report_generator.py      # 旧版报告生成器（向后兼容）
├── frontend/
│   ├── app.py                   # Streamlit 主界面（含 Module 4 认证）
│   └── auth.py                  # 用户认证（Module 4）
├── tests/
│   ├── test_pipeline.py         # 端到端集成测试（含 API 调用）
│   ├── test_scoring.py          # 评分引擎单元测试
│   ├── test_output_guard.py     # 质量守卫单元测试
│   ├── test_data_quality.py     # 数据质量单元测试
│   ├── test_v21_fixes.py        # V2.1 修复验证（25 tests）
│   ├── test_v21_regression.py   # V2.1 回归测试（24 tests）
│   └── test_v22_regression.py   # V2.2 回归测试（32 tests）
├── cache/                       # 数据缓存（自动生成）
└── reports/                     # 生成的报告
```

---

## 🧪 测试

```bash
# 全量单元测试（104 个，不消耗 API）
venv/bin/python -m pytest tests/ --ignore=tests/test_pipeline.py -v

# 按模块运行
venv/bin/python -m pytest tests/test_scoring.py -v        # 评分引擎
venv/bin/python -m pytest tests/test_output_guard.py -v   # 质量守卫
venv/bin/python -m pytest tests/test_v22_regression.py -v # V2.2 回归

# 端到端流程（需 DEEPSEEK_API_KEY）
python tests/test_pipeline.py
```

---

## 📊 报告示例

每份报告包含以下章节：

| 章节 | 内容 | 数据来源 |
|------|------|---------|
| 一、数据质量说明 | 真实/模拟/矛盾 Badge + 警告列表 | 代码生成 |
| 二、基金基本信息 | 类型/公司/经理/基准指数 | akshare |
| 三、核心指标溯源 | 净值/收益/回撤，每项标注性质和来源 | akshare |
| 四、综合评分 | 4 维度评分表 + 适配结论 + 适合人群 | 代码评分 |
| 五、行情分析 | LLM 解释数据快照 | DeepSeek |
| 六、舆情分析 | 多空平衡新闻情绪 + 情绪评分 | Tavily + DeepSeek |
| 七、风险评估 | 4 维度风险解释（市场/流动性/管理人/数据）| DeepSeek |
| 八、风险提示 | 免责声明（hardcoded）| 代码生成 |
| 九、持仓分析 | 前十大重仓股 + 集中度 + 行业分布（可选）| akshare |
| 十、经理观点 | 最新季报提炼（可选，需 pdfplumber）| 官方 PDF |

---

## ⚙️ 可选功能配置

### 启用 PDF 导出

```bash
pip install markdown2 weasyprint
# Ubuntu 系统依赖：
# apt-get install libpango-1.0-0 fonts-noto-cjk
```

### 启用定期报告拉取

```bash
pip install pdfplumber requests
```

### 启用用户认证

在 `.streamlit/secrets.toml` 中配置：

```toml
[auth]
mode = "simple"
session_timeout_hours = 8

[auth.users.admin]
# python -c "import hashlib; print(hashlib.sha256(b'yourpwd').hexdigest())"
password_hash = "<sha256_of_your_password>"
role = "admin"
display_name = "管理员"
```

### 接入商业数据源（Wind / Choice）

```bash
# .env 文件
DATA_SOURCE=wind        # 或 choice / auto
WIND_USERNAME=your_username
WIND_PASSWORD=your_password
```

---

## 🔄 版本历史

| 版本 | 主要改动 |
|------|---------|
| V1.0 | 初版 5 节点流水线，基础 akshare + Tavily 集成 |
| V2.0 | LangGraph 重构，FundSnapshot 数据契约，确定性评分 |
| V2.1 | 质量加固：constants 枚举 / value_cleaner / benchmark_resolver / output_guard |
| V2.2 | 次新基金 limited 等级 / output_guard 挂入 graph / 情绪分去重 |
| V2.3 | 五大扩展模块（持仓/数据适配器/定期报告/认证/PDF 导出） |
| V2.4 | DataNature._missing_ 防御 / report_renderer 四重防御 / 三轮样本全面修复 |
| V2.5 | akshare 多接口交叉补全：return_1y/return_3y/benchmark_return_pct/volatility/sharpe 缺失自动填充 |

---

## ⚠️ 免责声明

本系统仅供学习演示，不构成任何投资建议。基金有风险，投资需谨慎。过往业绩不代表未来表现。

---

*FundRAG Multi-Agent System V2.5 | 数据来源：akshare / Tavily / 基金官方公告*
