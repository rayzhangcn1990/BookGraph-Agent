# BookGraph KDNA Assets

KDNA（Knowledge DNA）判断资产格式标准集成，用于BookGraph-Agent质量检查和生成流程管理。

## 目录结构

```
kdna-assets/
└── @bookgraph/
    ├── quality-checks/          # 质量检查规则集
    │   ├── truth_charter.json   # 判断边界定义
    │   └── manifest.json        # 公理、边界、自检规则
    ├── generation/              # 知识图谱生成流程
    │   └── truth_charter.json   # 生成边界定义
    └── metadata-enrichment/     # 元数据增强LoadPlan
        └── loadplan.json        # 三层fallback链路
```

## 已集成的KDNA资产

### 1. 质量检查规则集 (@bookgraph/quality-checks)

**用途**：将`book_graph_quality_checker.py`的10项检查规则标准化为KDNA判断资产

**核心内容**：
- **Truth Charter**：定义判断边界（in_scope/out_of_scope）
- **Axioms（公理）**：10项质量检查规则
  - `no-placeholder-pollution`：占位符污染检测
  - `no-chapter-merge`：章节合并检测
  - `no-empty-chapters`：空洞章节检测
  - `no-template-content`：模板化内容检测（语义相似度>0.85）
  - `concept-definition-depth`：概念定义深度检查
  - `quote-source-attribution`：金句来源标注检查
  - `critical-analysis-coverage`：批判性分析覆盖检查
  - `underlying-logic-format`：底层逻辑格式检查
  - `required-fields-completeness`：必填字段完整性检查
  - `chapter-coverage-rate`：章节覆盖率检查

**使用方式**：
```python
from kdna_assets.@bookgraph.quality_checks import manifest

# 加载axioms
for axiom in manifest['axioms']:
    print(f"{axiom['id']}: {axiom['statement']}")
```

---

### 2. 知识图谱生成流程 (@bookgraph/generation)

**用途**：定义BookGraph生成流程的判断边界

**核心内容**：
- **Highest Question**：如何从书籍内容生成高质量知识图谱？
- **Core Insight**：知识图谱应忠实反映原文结构、提取核心论点、避免LLM偷懒
- **Forbidden Simplifications**：10种禁止的简化行为
  - 章节编号合并
  - 关键内容占位符
  - 概念定义过短
  - 金句缺少来源标注
  - 模板化表述
  - 空洞章节
  - 批判性分析视角缺失
  - 底层逻辑格式不规范
  - 虚构内容
  - 过度抽象

**使用方式**：
```python
from kdna_assets.@bookgraph.generation import truth_charter

# 检查生成结果是否符合边界
if "章节编号合并" in truth_charter['forbidden_simplifications']:
    # 触发重试机制
    pass
```

---

### 3. 元数据增强LoadPlan (@bookgraph/metadata-enrichment)

**用途**：管理元数据增强的三层fallback链路

**核心内容**：
- **Stage 1**：OpenLibrary API查询（免费无需Key）
- **Stage 2**：Google Books API查询（备选数据源）
- **Stage 3**：LLM fallback生成（API无数据时的兜底）
- **Stage 4**：Wikipedia作者信息增强
- **Stage 5**：LLM生成作者简介（Wikipedia无数据时）

**验证规则**：
- 必填字段：title, author
- 作者简介长度：≥200字
- 数据源追踪：openlibrary, googlebooks, llm, wikipedia
- 缓存策略：SQLite + 30天TTL + SHA256校验

**使用方式**：
```python
from kdna_assets.@bookgraph.metadata_enrichment import loadplan

# 执行LoadPlan
for stage in loadplan['stages']:
    if execute_stage(stage):
        break  # 成功即停止
```

---

## KDNA集成收益

### 1. 质量检查标准化

| 维度 | 集成前 | 集成后 |
|------|-------|--------|
| **规则表达** | 硬编码在代码中 | KDNA标准格式 |
| **跨项目复用** | 需复制代码 | 导入.kdna文件 |
| **版本管理** | Git提交 | KDNA版本链 |
| **验证机制** | 单元测试 | KDNA Schema验证 |

### 2. 判断边界明确化

**集成前**：判断边界隐含在prompt中，难以追踪和审计

**集成后**：
- Truth Charter明确定义in_scope/out_of_scope
- Forbidden simplifications列出禁止行为
- Anti-drift rules防止判断漂移

### 3. Fallback链路可视化

**集成前**：元数据增强的fallback逻辑散落在多个函数中

**集成后**：
- LoadPlan清晰展示5个stage
- 验证规则集中定义
- 缓存策略统一管理

---

## 下一步集成建议

### 立即可做

1. **安装KDNA CLI**：
   ```bash
   npm install -g @aikdna/kdna-cli
   ```

2. **验证KDNA资产**：
   ```bash
   kdna validate kdna-assets/@bookgraph/quality-checks/
   kdna validate kdna-assets/@bookgraph/generation/
   kdna validate kdna-assets/@bookgraph/metadata-enrichment/
   ```

3. **打包为.kdna文件**：
   ```bash
   kdna pack kdna-assets/@bookgraph/quality-checks/ quality-checks.kdna
   ```

### 中期规划

1. **构建BookGraph判断资产市场**：
   - 发布@bookgraph/quality-checks到KDNA Registry
   - 支持第三方贡献质量检查规则

2. **集成KDNA Loader**：
   - 在`book_graph_quality_checker.py`中加载.kdna文件
   - 动态更新质量检查规则（无需修改代码）

3. **使用KDNA SDK**：
   - 集成`@aikdna/kdna-core`到BookGraph-Agent
   - 实现运行时加载判断资产

---

## 参考链接

- [KDNA Core Spec](https://github.com/aikdna/kdna)
- [KDNA CLI](https://www.npmjs.com/package/@aikdna/kdna-cli)
- [KDNA Truth Charter Schema](https://aikdna.com/schema/truth_charter.json)
- [KDNA LoadPlan Schema](https://aikdna.com/schema/kdna_loadplan.json)
