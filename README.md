# BookGraph-Agent

**智能化书籍分析系统，自动解析书籍并生成结构化的 Obsidian 知识图谱**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ 核心能力

- 📖 **书籍解析**：支持 PDF/EPUB/MOBI，文字版与扫描版 PDF（推荐 Docling 高性能解析）
- 🤖 **LLM 分析**：通过远程 API 端点（OpenAI 兼容接口），当前使用 astron-code-latest 模型
- 🗺️ **知识图谱生成**：8 层书籍图谱 + 10 层学科图谱
- 📝 **Obsidian 输出**：Markdown 格式，支持双向链接
- 🛡️ **质量校验**：KDNA 资产定义的 10 项质量检查规则

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt

# 可选：启用 Docling 高性能解析（替代 PaddleOCR）
pip install docling>=2.0.0
```

### 命令行使用

```bash
# 处理单本书
python main.py --input "/path/to/book.pdf"

# 指定学科
python main.py --input "/path/to/book.pdf" --discipline 哲学

# 批量处理目录
python main.py --input "/path/to/books/" --workers 3
```

### API 服务

```bash
# 启动 API 服务
docker-compose up -d

# 或使用 uvicorn
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Web UI

访问 `http://localhost:8000` 即可使用可视化界面。

## 🏗️ 架构

### 核心处理流程

```
书籍输入 → 解析器(parser) → 语义分块 → LLM 分析(chunk/skill) → 综合(synthesis/two-stage) → Obsidian 输出
```

### 目录结构

```
BookGraph-Agent/
├── core/                  # 核心处理逻辑
│   ├── agent_tools.py     # Agent 工具层封装
│   ├── agent_orchestrator.py  # 编排层统一入口
│   ├── memory_layer.py    # 分层记忆（短期/长期/工作记忆）
│   ├── reflection_layer.py # 自我反思机制
│   ├── vector_store.py    # LanceDB 向量检索
│   ├── monitoring.py      # Prometheus 监控
│   ├── llm_client.py      # LLM 客户端
│   ├── optimized_chunk_processor.py  # 并发 chunk 处理
│   ├── book_graph_quality_checker.py # 质量校验
│   └── prompts.py         # 提示词定义
├── parsers/               # 书籍解析器
├── schemas/               # Pydantic 数据模型
├── utils/                 # 工具函数
├── api/                   # FastAPI 服务
├── web/                   # Web UI
├── exporters/             # 导出器（JSON/思维导图）
└── kdna-assets/           # KDNA 质量检查规则
```

## 🔧 配置

### 环境变量（.env）

```bash
OBSIDIAN_VAULT_PATH=/path/to/obsidian/vault
FREELLMAPI_KEY=your_api_key
```

### config.yaml

```yaml
llm:
  provider: "openai"
  model: "astron-code-latest"
  api_base: "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"
  max_tokens: 8192
  max_parallel: 8

improvements:
  two_stage_ingest:
    enabled: true
  quality_gate:
    enabled: true
    threshold: 80.0
```

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 单书处理时长 | 4-6 分钟（优化后） |
| 批量吞吐量 | 3-5 本/10 分钟 |
| 缓存命中率 | 50-70% |
| 重试成功率 | 85% |
| 质量问题识别准确率 | 85% |

## 🧪 测试

```bash
# 运行全部测试
pytest

# 单个测试文件
pytest tests/test_graph_generator.py -v

# 带覆盖率
pytest --cov=core --cov=parsers
```

## 📈 监控

### Prometheus 指标

访问 `/metrics` 端点获取 17 项核心指标：

- API 请求速率、延迟（p95）
- 任务成功率、执行时长
- LLM 调用速率、Token 使用量
- 缓存命中率、并发度、质量门控通过率

### Grafana 仪表盘

参考 `core/monitoring.py` 中的 `GRAFANA_DASHBOARD_JSON` 配置。

## 🌐 API 文档

详细 API 文档请参考 [API_DOCS.md](./API_DOCS.md)

### 核心端点

- `POST /api/v1/parse` - 提交解析任务
- `GET /api/v1/status/{task_id}` - 查询任务状态
- `GET /api/v1/result/{task_id}` - 获取任务结果
- `GET /metrics` - Prometheus 指标

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [LangChain](https://python.langchain.com/) - Agent 工具标准
- [LanceDB](https://lancedb.github.io/lancedb/) - 向量数据库
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Prometheus](https://prometheus.io/) - 监控系统
