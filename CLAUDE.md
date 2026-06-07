# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BookGraph-Agent 是一个智能化的书籍分析系统，自动解析书籍（PDF/EPUB/MOBI）并生成结构化的 Obsidian 知识图谱。

**核心能力：**
- 书籍解析（支持文字版和扫描版 PDF）
- LLM 分析（通过 localhost:3001 代理端点，后端路由到 OpenRouter/DeepSeek 等模型池）
- 知识图谱生成（8 层书籍图谱 + 10 层学科图谱）
- Obsidian 输出（Markdown 格式，支持双向链接）
- 质量校验（占位符检测、章节完整性、模板化内容检测）

## Development Commands

```bash
# 处理单本书
python main.py --input "/path/to/book.pdf"

# 指定学科
python main.py --input "/path/to/book.pdf" --discipline 哲学

# 批量处理目录
python main.py --input "/path/to/books/" --workers 3

# 指定模型（使用本地 Ollama）
python main.py --input "/path/to/book.pdf" --model ollama/qwen2.5:3b

# 运行测试
pytest

# 单个测试文件
pytest tests/test_graph_generator.py -v

# 带覆盖率
pytest --cov=core --cov=parsers

# 安装依赖
pip install -r requirements.txt
```

## Architecture

### 核心处理流程

```
书籍输入 → 解析器(parser) → 语义分块 → LLM 分析(chunk/skill) → 综合(synthesis/two-stage) → Obsidian 输出
```

### 1. 解析层 (parsers/)
- `base_parser.py`: 解析器基类，定义 `ParseResult` 标准接口
- `epub_parser.py`: EPUB 解析 (ebooklib)
- `pdf_parser.py`: PDF 解析（PyMuPDF 文字版 + PaddleOCR/Tesseract 扫描版）
- `mobi_parser.py`: MOBI/AZW 解析

### 2. 核心层 (core/)
- **LLM 客户端体系**
  - `llm_client.py`: 统一 LLM 调用入口，支持 Anthropic/OpenAI/DashScope/Ollama 多 provider，自动轮换和模型池路由
  - `model_pool_manager.py`: 三层模型池管理（验证层→评估层→池管理层），自动测试可用性、追踪稳定性、动态淘汰
  - `multi_source_manager.py`: 多 API 源管理，独立额度追踪，自动切换（OpenRouter 多 Key 轮换）
  - `model_output_format_spec.py`: 三层 JSON 解析防护（Prompt约束 + 字段名映射 + 截断修复）
- **分析管线**
  - `book_parser.py`: 解析入口，按扩展名自动选择解析器
  - `optimized_chunk_processor.py`: asyncio 并行 chunk 处理（Semaphore 限流，指数退避重试，动态降低并发应对限流）
  - `multi_round_synthesis.py`: 5 轮低复杂度合成（拆分 BookGraph 生成，防止 LLM 偷懒合并章节）
  - `two_stage_ingest.py`: 两阶段 CoT 摄取（分析→生成），支持增量缓存（替代多轮合成）
- **图谱生成**
  - `graph_generator.py`: 书籍/学科知识图谱 Markdown 生成（Obsidian Callout 语法）
  - `obsidian_writer.py`: 写入 Obsidian Vault，管理目录结构和文件备份
  - `graph_insights.py`: 图洞察（Louvain 社区检测、孤立/桥节点、稀疏社区检测）
  - `graph_relevance.py`: 4 信号知识图相关性模型（直接链接×3.0 + 来源重叠×4.0 + Adamic-Adar×1.5 + 类型亲和×1.0）
  - `hybrid_search.py`: 混合搜索（词元搜索 + 图扩展 + 可选 LanceDB 向量搜索）
  - `entity_resolution.py`: 实体消歧（sentence-transformers 向量聚类合并相似概念）
  - `summary_index.py`: 摘要层索引（生成 _chapter_summary.md 和 _book_summary.md）
  - `structured_output.py`: 结构化输出保证（instructor 库或 Pydantic JSON schema）
- **质量保障**
  - `book_graph_quality_checker.py`: 10 项质量检查（占位符污染、章节完整性、模板化内容、底层逻辑格式、必填字段等）
  - `prompts.py`: 提示词定义（SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT, SYNTHESIS_PROMPT 等）

### 3. Skill 系统 (core/skills/)
- `skill_orchestrator.py`: 并发协调器，Semaphore 控制多 Skill 并行执行，增量写入，Per-Skill 质量检查
- `base_skill.py`: Skill 基类，定义 execute → validate → generate_markdown → run_and_write 标准流程，支持 Extraction 源文本对齐追踪
- `chapter_skill.py` / `concept_skill.py` / `insight_skill.py` / `case_skill.py` / `quote_skill.py` / `background_skill.py` / `critical_skill.py`: 各维度分析 Skill
- `model_pool_skill.py`: 模型池管理 Skill

### 4. Schema 层 (schemas/)
- `book_graph_schema.py`: BookGraph Pydantic 模型（8 层框架：metadata → time_background → chapters → core_concepts → key_insights → key_cases → key_quotes → critical_analysis → learning_path → book_network）
- `extraction_schema.py`: 提取结果模型（Extraction, AlignmentStatus, CharInterval）
- `discipline_schema.py`: 学科图谱 Pydantic 模型（10 板块：概述 → 知识结构 → 发展脉络 → 核心思想 → 概念词汇库 → 代表书籍 → 入门指南 → 流派争论 → 交叉关联 → 前沿问题）
- `validate_book_graphs.py`: 独立验证工具（检查已生成的图谱文件完整性）

### 5. 工具层 (utils/)
- `cache.py` / `parse_cache.py`: 缓存机制（断点续传），支持内容哈希缓存
- `file_handler.py`: 文件处理工具
- `hardware_config.py`: 硬件配置检测
- `logger.py`: 日志配置（loguru）
- `path_manager.py`: 路径管理
- `progress.py`: 进度追踪
- `wikipedia_enricher.py`: Wikipedia 概念丰富

## Key Design Decisions

**两阶段 CoT 摄取 (two_stage_ingest.py)**
- 问题：多轮合成仍有占位符和章节合并问题
- 方案：分析→生成两阶段，阶段 1 只做结构化分析（实体、概念、论点），阶段 2 基于分析结果生成图谱
- 效果：分析结果可缓存复用，生成阶段有更丰富的上下文

**模型池管理 (model_pool_manager.py)**
- 三层架构：验证层（测试可用性）→评估层（追踪稳定性评分）→池管理层（动态入池/淘汰 + 持久化）
- Musk The Algorithm 方法论：Question → Delete → Simplify → Accelerate → Automate

**Per-Skill 质量检查**
- 每个 Skill 完成即校验（不是等到全部完成再检查）
- 发现问题立即重试，避免下游模块基于低质量数据继续工作

**三层 JSON 解析防护 (model_output_format_spec.py)**
- Layer 1: Prompt 约束（强制英文 field name、数组包裹、无代码块）
- Layer 2: 字段名映射 + 截断修复（兼容不同模型的输出差异）
- Layer 3: 验证兜底（JSON schema 校验 + 缺失字段填充）

## Configuration

### 环境变量 (.env)
```
OBSIDIAN_VAULT_PATH=/path/to/obsidian/vault
OPENROUTER_API_KEY=sk-or-v1-xxx
```

### 当前 LLM 配置 (config.yaml)
```yaml
llm:
  provider: "openai"          # 使用 OpenAI 兼容接口
  model: "auto"               # 由模型池自动选择
  api_base: "http://localhost:3001/v1"  # 本地代理端点
  api_key: "freellmapi-..."   # 代理端点认证密钥

  # 模型池（从 OpenRouter 自动发现模型）
  model_pool:
    enabled: true
    models:
      - model: "deepseek/deepseek-chat"      # 主模型
      - model: "nvidia/llama-3.3-nemotron..." # 备选
      - model: "tencent/hy3-preview:free"     # 免费备用
```

### 功能开关 (config.yaml -> improvements)
```yaml
improvements:
  two_stage_ingest:    # 两阶段 CoT 摄取（替代多轮合成）
    enabled: true
  graph_insights:      # 图洞察（孤立节点、桥节点检测）
    enabled: true
  summary_index:       # 摘要层索引
    enabled: true
  hybrid_search:       # 混合搜索（需 LanceDB）
    enabled: false
  entity_resolution:   # 实体消歧（需 sentence-transformers）
    enabled: false
  structured_output:   # 结构化输出（需 instructor 库）
    enabled: false
```

## Code Conventions

- Pydantic v2 数据验证（`BaseModel` + `Field`）
- asyncio 异步处理（`asyncio.to_thread` 包装同步 LLM 调用）
- 日志使用标准 `logging` 模块（非 loguru，已迁移）
- 配置 YAML + 环境变量（`${VAR_NAME}` 自动解析）
- 文件路径使用 `pathlib.Path`
- 提示词模板使用 `str.format()` 占位符
- 全局 LLM 客户端单例模式（`get_llm_client()`）

## MCP Tools: codegraph

This project has a CodeGraph index. Use `codegraph_*` tools for structural code queries before resorting to grep/read.

| Tool | When to use |
|------|-------------|
| `codegraph_context` | Primary — understanding a task/feature area |
| `codegraph_trace` | Flow tracing — how X reaches Y |
| `codegraph_search` | Find a symbol by name |
| `codegraph_explore` | See several related symbols' source at once |
| `codegraph_callers/callees` | What calls / is called by a symbol |
| `codegraph_impact` | Blast radius of a change |

For the full workflow, see `.cursorrules` or `AGENTS.md`.
