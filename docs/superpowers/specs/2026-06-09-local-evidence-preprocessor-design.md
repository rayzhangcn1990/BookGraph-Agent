# BookGraph-Agent 本地证据预处理与模型路由设计

## 背景

《善恶的彼岸》解析结果仍出现大量“待补充”和空洞内容。现有质量门主要依靠规则拦截最终 BookGraph，例如占位符检测、章节覆盖率、模板化内容检测和定向重试。这种方式可以阻止坏结果写入 Obsidian，但无法从生成源头保证模型有足够证据完成高质量哲学分析。

本次设计采用 evidence-first 思路：先从原文 chunk 中提取可追踪候选证据，再由云端模型完成深度解释、概念网络和最终 BookGraph 综合。

## 目标

1. 使用 NAS 上现有 `qwen2.5:3b` 作为本地短 JSON 预处理器。
2. 本地模型只做低风险候选信号提取，不参与最终哲学解释。
3. 将 BookGraph-Agent 模型池从平铺 fallback 改为任务型路由。
4. 保留现有解析、chunk、质量门和 Obsidian 输出能力。
5. 将运行成本控制在当前流程的 2-3 倍以内。

## 非目标

1. 不让 `qwen2.5:3b` 生成最终 BookGraph。
2. 不让本地模型补写“待补充”字段。
3. 不在本阶段引入完整 LightRAG 服务。
4. 不替换现有 `LLMClient` 的所有调用路径。
5. 不强制安装新 NAS 模型。

## 实测依据

当前 NAS Ollama 模型：

```text
qwen2.5:3b
参数：3.1B
量化：Q4_K_M
大小：约 1.8GB
```

实测输出速度：

```text
约 2.1 - 2.7 token/s
```

观察到的问题：

1. 普通知识问答会严重幻觉，例如将《善恶的彼岸》误判为易卜生作品。
2. Ollama `format: "json"` 对短 JSON 有效。
3. 较长 JSON 容易因输出截断导致无法解析。

因此 `qwen2.5:3b` 的定位是“候选信号粗筛员”，不是“哲学解释作者”。

## 推荐架构

```text
书籍解析
  ↓
语义分块
  ↓
LocalEvidencePreprocessor(qwen2.5:3b)
  ↓
LocalEvidenceHints / evidence_candidates cache
  ↓
云端 Evidence Pass
  ↓
Concept Network Pass
  ↓
Interpretation / BookGraph Synthesis
  ↓
质量门
  ↓
Obsidian 输出
```

## 新模块：LocalEvidencePreprocessor

新增文件：

```text
core/local_evidence_preprocessor.py
```

### 职责

1. 调用 NAS Ollama API。
2. 使用 `format: "json"`。
3. 限制输入长度，避免小模型长上下文退化。
4. 限制输出 token，避免长 JSON 截断。
5. 将所有异常视为软失败。
6. 输出候选证据，不输出解释性长文。

### 数据结构

```python
@dataclass
class LocalEvidenceHints:
    chunk_index: int
    chapter_ref: str
    has_argument: bool
    has_concept: bool
    has_quote: bool
    concept_candidates: list[str]
    quote_candidates: list[str]
    confidence: float
    error: str | None = None
```

### 最小方法

#### classify_chunk

判断 chunk 是否值得进入云端深度分析。

输出示例：

```json
{
  "chapter_ref": "第一章",
  "has_argument": true,
  "has_concept": true,
  "has_quote": false,
  "confidence": 0.78
}
```

#### extract_concept_candidates

只抽取短概念名，不写定义。

输出示例：

```json
{
  "concept_candidates": ["真理意志", "哲学家的偏见", "假象"]
}
```

#### extract_quote_candidates

只抽取短句，不解释。

输出示例：

```json
{
  "quote_candidates": ["为什么真理比假象更有价值？"]
}
```

## 配置设计

在 `config.yaml` 的 `improvements` 下新增：

```yaml
local_evidence_preprocessor:
  enabled: true
  provider: "ollama"
  api_base: "http://10.108.1.143:11434"
  model: "qwen2.5:3b"
  timeout: 180
  max_chars: 1200
  num_predict: 128
  temperature: 0.0
  cache_results: true
```

## 数据流接入点

接入位置：`main.py` 中语义分块之后、云端 chunk 分析之前。

当前流程：

```text
Step 2: _semantic_chunking
Step 3: process_book_chunks_native_async
```

目标流程：

```text
Step 2: _semantic_chunking
Step 2.5: preprocess_local_evidence
Step 3: process_book_chunks_native_async
```

本地 hints 会作为附加上下文传入云端 chunk prompt，但不能被视为事实来源。云端模型必须以原文为准。

## Prompt 注入方式

短期采用低侵入方式，在每个 chunk prompt 前附加：

```text
【本地预处理候选信号】
可能章节：第一章
候选概念：真理意志、哲学家的偏见、假象
候选金句：为什么真理比假象更有价值？
注意：这些只是本地小模型候选信号，必须以原文为准，不可盲信。
```

## 缓存策略

本地预处理速度慢，必须缓存。

缓存 key：

```text
book_title + chunk_index + sha256(chunk_content) + model + prompt_version
```

缓存内容：

```json
{
  "chunk_index": 1,
  "chapter_ref": "第一章",
  "has_argument": true,
  "has_concept": true,
  "has_quote": false,
  "concept_candidates": ["真理意志"],
  "quote_candidates": [],
  "confidence": 0.78,
  "error": null
}
```

缓存实现优先复用 `utils/parse_cache.py`，避免新增独立缓存系统。

## 失败策略

本地预处理是软依赖，任何失败都不能中断主流程。

| 失败类型 | 行为 |
|---|---|
| Ollama 不可达 | 记录 warning，返回空 hints |
| 超时 | 记录 warning，返回空 hints |
| JSON 解析失败 | 记录 warning，返回空 hints |
| 输出字段缺失 | 填默认值，降低 confidence |
| 模型幻觉 | 不直接进入最终输出，只作为候选信号 |

## BookGraph-Agent 推荐模型组合

### 本地层

用途：低风险预处理。

推荐：

```text
qwen2.5:3b
```

后续可选测试：

```text
qwen3:4b
gemma3:4b
gemma3n:e2b
```

### Evidence Pass

用途：从原文和本地 hints 中抽取 claim、concept、quote、evidence。

推荐：

```text
deepseek/deepseek-chat
qwen/qwen3-32b
google/gemini-2.5-flash
```

### Concept Network Pass

用途：概念归并、关系抽取、章节间概念演化。

推荐：

```text
deepseek/deepseek-reasoner
qwen/qwen3-32b
google/gemini-2.5-pro
```

### Final Synthesis

用途：最终 BookGraph 生成、哲学解释、批判分析。

推荐：

```text
anthropic/claude-sonnet-4.5 或 claude-sonnet-4.6
deepseek/deepseek-reasoner
google/gemini-2.5-pro
```

### Quality Review / Repair

用途：检查证据覆盖、空洞内容、误读和 schema 缺失。

推荐：

```text
anthropic/claude-haiku-4.5
anthropic/claude-sonnet-4.5 或 claude-sonnet-4.6
deepseek/deepseek-chat
```

## 任务型路由设计

长期应将 `config.yaml` 中平铺的 `model_pool.models` 改为任务型路由：

```yaml
llm:
  routing:
    local_fast:
      provider: ollama
      models:
        - qwen2.5:3b

    extraction:
      provider: openai
      models:
        - deepseek/deepseek-chat
        - qwen/qwen3-32b
        - google/gemini-2.5-flash

    reasoning:
      provider: openai
      models:
        - anthropic/claude-sonnet-4.6
        - deepseek/deepseek-reasoner
        - google/gemini-2.5-pro

    review:
      provider: openai
      models:
        - anthropic/claude-haiku-4.5
        - deepseek/deepseek-chat
```

第一阶段不要求完成全部路由改造，只需要为 local evidence preprocessing 提供独立配置，并为后续路由保留接口边界。

## 测试计划

### 单元测试

1. Ollama 返回合法 JSON 时，正确解析为 `LocalEvidenceHints`。
2. Ollama 返回非法 JSON 时，返回空 hints，不抛异常。
3. Ollama 超时时，返回空 hints。
4. 输入超过 `max_chars` 时被截断。
5. 缓存命中时不重复调用 Ollama。

### 集成测试

1. 使用固定 chunk 文本测试 `qwen2.5:3b` 的 JSON 输出。
2. 跑《善恶的彼岸》前 2-3 个 chunk，检查日志中是否出现本地预处理统计。
3. 确认 Ollama 不可达时主流程仍可继续。

### 成功标准

运行《善恶的彼岸》时看到：

```text
📍 本地 evidence 预处理: 16 chunks
✅ 成功: 13
⚠️ 失败: 3
🏷️ 候选概念: 真理意志, 哲学家的偏见, 自由精神...
💬 候选金句: ...
```

最终目标不是让本地模型直接消除所有“待补充”，而是为云端 Evidence Pass 和 Final Synthesis 提供更清晰的证据入口。

## 风险与缓解

### 风险 1：本地模型速度慢

缓解：

1. 每个任务输出短 JSON。
2. 限制 `max_chars` 和 `num_predict`。
3. 启用缓存。
4. 后续允许只对高价值 chunk 运行。

### 风险 2：本地模型幻觉

缓解：

1. 明确标记为候选信号。
2. 不直接进入最终 BookGraph。
3. 云端模型必须回看原文。
4. 质量门检查 evidence coverage。

### 风险 3：JSON 截断

缓解：

1. 一个调用只做一种抽取。
2. 控制输出数组长度。
3. 非法 JSON 返回空 hints。
4. 不做长解释。

### 风险 4：模型路由复杂度上升

缓解：

1. 第一阶段只实现 local evidence preprocessing。
2. 后续再引入任务型路由。
3. 保留现有 `model_pool` 作为 fallback。

## 实施顺序

1. 新增 `core/local_evidence_preprocessor.py`。
2. 增加配置读取和默认值。
3. 为本地预处理写单元测试。
4. 在 `main.py` 分块后接入预处理。
5. 将 hints 注入 chunk prompt。
6. 运行《善恶的彼岸》小范围验证。
7. 后续设计任务型模型路由。

## 已确认约束

1. 第一阶段仅使用 `qwen2.5:3b`，不拉取新 NAS 模型。
2. 本地预处理失败不阻断主流程。
3. 本地模型输出只作为候选，不作为最终事实。
4. 最终 synthesis 后续仍建议使用云端强模型。
5. 继续推进 BookGraph-Agent 推荐模型组合，但第一阶段只落地本地证据预处理和路由边界。

## 手动验证命令

验证 NAS Ollama 是否可达：

```bash
curl -s http://10.108.1.143:11434/api/tags | python3 -m json.tool
```

验证 `qwen2.5:3b` 短 JSON 输出：

```python
python3 - <<'PY'
import json
import urllib.request

payload = {
    "model": "qwen2.5:3b",
    "prompt": "输出严格 JSON：{\"concept_candidates\":[\"真理意志\"]}",
    "stream": False,
    "format": "json",
    "options": {"num_predict": 64, "temperature": 0.0},
}
request = urllib.request.Request(
    "http://10.108.1.143:11434/api/generate",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=180) as response:
    data = json.loads(response.read().decode("utf-8"))
print(data["response"])
json.loads(data["response"])
print("json ok")
PY
```
