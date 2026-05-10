# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BookGraph-Agent 是一个智能化的书籍分析系统，自动解析书籍（PDF/EPUB/MOBI）并生成结构化的 Obsidian 知识图谱。

**核心能力：**
- 书籍解析（支持文字版和扫描版 PDF）
- LLM 分析（通过 OpenRouter API 调用 DeepSeek V4 Pro）
- 知识图谱生成（8 层书籍图谱 + 10 层学科图谱）
- Obsidian 输出（Markdown 格式，支持双向链接）

## Development Commands

### 运行主程序

```bash
# 处理单本书
python main.py --input "/path/to/book.pdf"

# 指定学科
python main.py --input "/path/to/book.pdf" --discipline 哲学

# 批量处理
python main.py --input "/path/to/books/" --workers 3
```

### 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_book_parser.py

# 带覆盖率
pytest --cov=core --cov=parsers
```

### 依赖管理

```bash
# 安装依赖
pip install -r requirements.txt

# 更新依赖
pip freeze > requirements.txt
```

## Architecture

### 核心处理流程

```
书籍输入 → 解析器 → 分块 → LLM 分析 → 综合 → Obsidian 输出
```

**1. 解析层（parsers/）**
- `base_parser.py`: 解析器基类
- `epub_parser.py`: EPUB 解析
- `pdf_parser.py`: PDF 解析（文字版 + OCR）
- `mobi_parser.py`: MOBI 解析

**2. 核心层（core/）**
- `book_parser.py`: 书籍解析入口，自动选择解析器
- `llm_client.py`: LLM 客户端，支持多 API 源轮换和模型池管理
- `optimized_chunk_processor.py`: 并行 chunk 处理（asyncio）
- `multi_round_synthesis.py`: 多轮综合分析（拆分复杂任务）
- `graph_generator.py`: 知识图谱生成
- `obsidian_writer.py`: Obsidian 文件写入

**3. Skill 系统（core/skills/）**
- `skill_orchestrator.py`: Skill 编排器
- `chapter_skill.py`: 章节分析
- `concept_skill.py`: 概念提取
- `insight_skill.py`: 洞见提取
- `case_skill.py`: 案例分析
- `quote_skill.py`: 金句萃取
- `critical_skill.py`: 批判性解读

**4. Schema 层（schemas/）**
- `book_graph_schema.py`: BookGraph 数据模型（Pydantic）
- `extraction_schema.py`: 提取结果模型

### 关键设计决策

**多轮综合分析（multi_round_synthesis.py）**
- **问题**：单次 synthesis 任务复杂度高，LLM 容易偷懒（合并章节、输出占位符）
- **方案**：拆分为 5 轮低复杂度任务，每轮输出 <2KB
- **效果**：提升输出质量，减少占位符和章节合并

**模型池管理（model_pool_manager.py）**
- **问题**：单一模型可能额度耗尽或不稳定
- **方案**：维护多个模型池，自动验证可用性，动态切换
- **配置**：`config.yaml` 中的 `model_pool` 和 `api_sources`

**进度持久化（utils/parse_cache.py）**
- **问题**：批量处理中断后需要重新开始
- **方案**：缓存解析结果到 `~/.bookgraph/cache/`
- **效果**：支持断点续传，跳过已处理书籍

**占位符清理（book_graph_quality_checker.py）**
- **问题**：LLM 输出"待分析"、"待补充"等占位符
- **方案**：质量检查器自动检测并拒绝低质量输出
- **触发**：synthesis 失败时自动重试

## Configuration

### 环境变量（.env）

```bash
# Obsidian 配置
OBSIDIAN_VAULT_PATH=/path/to/obsidian/vault

# OpenRouter API Key
OPENROUTER_API_KEY=sk-or-v1-xxx
```

### 配置文件（config.yaml）

**LLM 配置**
```yaml
llm:
  provider: "openrouter"
  model: "deepseek/deepseek-chat"
  api_base: "https://openrouter.ai/api/v1"
  api_key: "${OPENROUTER_API_KEY}"
  max_tokens: 16384
  temperature: 0.3
  chunk_size: 25000
```

**模型池配置**
```yaml
llm:
  model_pool:
    enabled: true
    auto_verify: true
    min_stability: 0.7
    max_response_time: 30
```

**学科路径映射**
```yaml
obsidian:
  discipline_paths:
    政治学: "📚 知识图谱/政治学"
    经济学: "📚 知识图谱/经济学"
    # ...
```

## Common Issues

### OCR 支持

扫描版 PDF 需要安装 OCR 引擎：

```bash
# PaddleOCR（推荐）
pip install paddlepaddle paddleocr

# Tesseract
brew install tesseract
pip install pytesseract pillow
```

### LLM 调用失败

检查配置：
1. 确认 `OPENROUTER_API_KEY` 已设置
2. 检查 `config.yaml` 中的 `api_sources` 配置
3. 查看日志：`logs/bookgraph.log`

### 输出质量问题

如果生成的知识图谱包含占位符或章节合并：
1. 检查 `book_graph_quality_checker.py` 是否启用
2. 调整 `multi_round_synthesis.py` 中的提示词
3. 增加 `max_retries` 配置

## Code Conventions

- 使用 Pydantic 进行数据验证
- 异步处理使用 `asyncio`
- 日志使用 `loguru`
- 配置使用 YAML + 环境变量
- 文件路径使用 `pathlib.Path`

## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore the codebase.**

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |

### Workflow

1. Use `detect_changes` for code review
2. Use `get_affected_flows` to understand impact
3. Use `query_graph` pattern="tests_for" to check coverage
