# BookGraph Agent

**Obsidian 知识图谱生成系统** — 自动解析书籍，生成结构化知识图谱，构建学科知识体系。

---

## 📖 简介

BookGraph Agent 是一个智能化的书籍分析系统，能够：

- 📚 **自动解析** PDF/EPUB/MOBI 格式书籍
- 🔍 **OCR 识别** 扫描版 PDF（支持 PaddleOCR/Tesseract/Marker）
- 🧠 **LLM 分析** 通过 Hermes/Claude Code 工具调用（无需配置 API Key）
- 📝 **Obsidian 输出** 生成标准 Markdown 笔记和知识图谱
- 🗂️ **学科管理** 自动分类并更新学科知识体系

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd BookGraph-Agent
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```bash
# Obsidian 配置
OBSIDIAN_VAULT_PATH=/Users/your_name/Documents/Obsidian Vault
```

**注意**: LLM 通过 Hermes/Claude Code 工具调用，无需配置外部 API Key。

### 3. 运行

```bash
# 处理单本书
python main.py --input "/path/to/book.pdf"

# 指定学科
python main.py --input "/path/to/book.pdf" --discipline 哲学

# 批量处理目录
python main.py --input "/path/to/books/"

# 批量处理（自定义并发数）
python main.py --input "/path/to/books/" --workers 3
```

---

## 🔧 配置说明

**配置文件：** `config.yaml`

```yaml
llm:
  # LLM 通过 Hermes/Claude Code 工具调用，无需在此配置
  max_tokens: 16384
  temperature: 0.3
  chunk_size: 30000        # 每块字符数

batch:
  max_workers: 3           # 并发数

obsidian:
  vault_path: "${OBSIDIAN_VAULT_PATH}"
  graph_root: "📚 知识图谱"
```

---

## 📋 功能特性

### 书籍解析

| 格式 | 解析器 | 速度 | 适用场景 |
|------|--------|------|----------|
| EPUB | ebooklib | ⚡⚡⚡ | 电子书 |
| PDF | PyMuPDF | ⚡⚡⚡ | 文字版 PDF |
| PDF | OCR | ⚡ | 扫描版 PDF |
| MOBI | mobi | ⚡⚡ | Kindle 电子书 |

### 知识图谱输出

**书籍图谱**包含 8 层框架：
1. 书籍基础信息（含反向链接）
2. 章节结构与核心内容
3. 核心概念（含批判性审视）
4. 关键洞见（含多维审视）
5. 关键案例（含历史局限性）
6. 金句萃取（含语境化解读）
7. 学习路径（初学者→实践）
8. 批判性解读（多元视角）

**学科图谱**包含 10 大板块：
1. 学科概述与核心问题
2. 学科整体知识结构
3. 学科发展脉络
4. 学科核心思想及底层逻辑
5. 核心概念词汇库
6. 代表书籍与阅读网络
7. 初学者入门指南
8. 学科内部流派与争论
9. 与其他学科的交叉关联
10. 学科前沿与开放问题

### ✨ 新增功能

**1. 进度持久化**
- 批量处理中断后可继续
- 自动跳过已处理的书籍
- 进度保存在 `~/.bookgraph/progress.json`

**2. 文件名截断**
- 自动截断过长文件名（>100 字符）
- 使用哈希保持唯一性
- 避免文件系统兼容问题

**3. 占位符清理**
- 自动过滤"待分析"、"待补充"等占位符
- 确保输出内容有意义
- 提升知识图谱质量

**4. 基本信息去重**
- YAML Front Matter 保留书名
- 表格中不再重复书名
- 输出更简洁清晰

---

## ⚠️ 注意事项

### LLM 调用

BookGraph-Agent 所有 LLM 调用通过 Hermes/Claude Code 工具实现：

1. 运行时会输出 LLM 调用提示词
2. 需要 Hermes/Claude Code 通过工具调用获取响应
3. 无需在 Agent 内部配置外部 API Key

### OCR 支持

扫描版 PDF 需要安装 OCR 引擎：

**PaddleOCR（推荐）：**
```bash
pip install paddlepaddle paddleocr
```

**Tesseract：**
```bash
brew install tesseract  # macOS
pip install pytesseract pillow
```

**Marker（高质量）：**
```bash
pip install marker-pdf
```

---

## 🐛 故障排除

### 解析结果为空或只有水印

**问题**：PDF 是扫描版（图片型），PyMuPDF 无法提取文字

**解决**：
```bash
# 安装 OCR 支持
pip install paddlepaddle paddleocr
```

### 学科分类错误

检查书籍所在目录是否正确（如 `1.哲学/`）

### 批量处理中断

进度已保存，重新运行会自动跳过已处理的书籍：
```bash
python main.py --input "/path/to/books/"
```

---

## 📄 License

MIT License
