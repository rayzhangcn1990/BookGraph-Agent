# Local Evidence Preprocessor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 NAS 上现有 `qwen2.5:3b` 为 BookGraph-Agent 增加本地短 JSON 证据预处理，并为后续任务型模型路由保留边界。

**Architecture:** 新增 `LocalEvidencePreprocessor`，它通过 Ollama `/api/generate` 的 `format: "json"` 输出短候选信号。主流程在语义分块之后、云端 chunk 分析之前运行本地预处理，并把候选信号注入 chunk prompt，但候选信号不能被视为最终事实。

**Tech Stack:** Python 3.11、asyncio、urllib 标准库、dataclass、pytest、现有 `utils.parse_cache.ParseCache`、现有 `core.optimized_chunk_processor.NativeAsyncChunkProcessor`。

---

## 文件结构

- Create: `core/local_evidence_preprocessor.py`
  - 负责 Ollama 调用、短 JSON prompt、解析、软失败、缓存 key 生成。
- Create: `tests/test_local_evidence_preprocessor.py`
  - 覆盖 JSON 成功、非法 JSON、超时、截断、缓存命中。
- Modify: `core/optimized_chunk_processor.py`
  - 为 `NativeAsyncChunkProcessor` 增加可选 `local_hints_by_chunk` 参数。
  - 在构造 chunk prompt 时注入本地候选信号。
- Modify: `main.py`
  - 在 `_semantic_chunking` 后读取 `improvements.local_evidence_preprocessor` 配置。
  - 启用时运行本地预处理，禁用或失败时继续原流程。
- Modify: `config.yaml`
  - 添加 `improvements.local_evidence_preprocessor` 默认配置。
- Test: `tests/test_local_evidence_preprocessor.py`
- Test: `tests/test_chunk_local_hints.py`
  - 覆盖 hints 注入 prompt 的行为。

---

### Task 1: 新增本地证据预处理器的失败优先测试

**Files:**
- Create: `tests/test_local_evidence_preprocessor.py`
- Create later: `core/local_evidence_preprocessor.py`

- [ ] **Step 1: 写失败测试文件**

Create `tests/test_local_evidence_preprocessor.py`:

```python
"""本地证据预处理器测试。"""

import json
import urllib.error

import pytest

from core.local_evidence_preprocessor import (
    LocalEvidenceHints,
    LocalEvidencePreprocessor,
)


class FakeCache:
    """测试用内存缓存。"""

    def __init__(self):
        self.values = {}
        self.get_calls = []
        self.set_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self.values.get(key)

    def set(self, key, result):
        self.set_calls.append((key, result))
        self.values[key] = result


class FakeOllamaTransport:
    """替代真实 Ollama HTTP 请求。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def generate(self, api_base, payload, timeout):
        self.payloads.append((api_base, payload, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_preprocessor(responses, cache=None, **overrides):
    config = {
        "enabled": True,
        "api_base": "http://nas:11434",
        "model": "qwen2.5:3b",
        "timeout": 10,
        "max_chars": 20,
        "num_predict": 64,
        "temperature": 0.0,
        "cache_results": True,
    }
    config.update(overrides)
    transport = FakeOllamaTransport(responses)
    processor = LocalEvidencePreprocessor(config, cache=cache or FakeCache(), transport=transport)
    return processor, transport


@pytest.mark.asyncio
async def test_classify_chunk_parses_valid_json():
    processor, transport = make_preprocessor([
        {"response": json.dumps({
            "chapter_ref": "第一章",
            "has_argument": True,
            "has_concept": True,
            "has_quote": False,
            "confidence": 0.8,
        }, ensure_ascii=False)}
    ])

    hints = await processor.preprocess_chunk("测试书", 1, "尼采追问真理的价值。")

    assert isinstance(hints, LocalEvidenceHints)
    assert hints.chunk_index == 1
    assert hints.chapter_ref == "第一章"
    assert hints.has_argument is True
    assert hints.has_concept is True
    assert hints.has_quote is False
    assert hints.confidence == 0.8
    assert hints.error is None
    assert transport.payloads[0][1]["format"] == "json"
    assert transport.payloads[0][1]["model"] == "qwen2.5:3b"


@pytest.mark.asyncio
async def test_preprocess_chunk_returns_empty_hints_on_invalid_json():
    processor, _ = make_preprocessor([{"response": "不是 JSON"}])

    hints = await processor.preprocess_chunk("测试书", 2, "文本")

    assert hints.chunk_index == 2
    assert hints.chapter_ref == ""
    assert hints.has_argument is False
    assert hints.has_concept is False
    assert hints.has_quote is False
    assert hints.concept_candidates == []
    assert hints.quote_candidates == []
    assert hints.confidence == 0.0
    assert "JSON" in hints.error


@pytest.mark.asyncio
async def test_preprocess_chunk_returns_empty_hints_on_transport_error():
    processor, _ = make_preprocessor([urllib.error.URLError("连接失败")])

    hints = await processor.preprocess_chunk("测试书", 3, "文本")

    assert hints.chunk_index == 3
    assert hints.error is not None
    assert hints.confidence == 0.0


@pytest.mark.asyncio
async def test_preprocess_chunk_truncates_input_to_max_chars():
    processor, transport = make_preprocessor([
        {"response": json.dumps({"concept_candidates": ["真理意志"]}, ensure_ascii=False)}
    ], max_chars=5)

    hints = await processor.preprocess_chunk("测试书", 4, "1234567890")

    sent_prompt = transport.payloads[0][1]["prompt"]
    assert "12345" in sent_prompt
    assert "67890" not in sent_prompt
    assert hints.concept_candidates == ["真理意志"]


@pytest.mark.asyncio
async def test_preprocess_chunk_uses_cache_when_available():
    cache = FakeCache()
    cache.values["local_evidence:qwen2.5:3b:v1:测试书:5:098f6bcd4621d373cade4e832627b4f6"] = {
        "chunk_index": 5,
        "chapter_ref": "第二章",
        "has_argument": True,
        "has_concept": False,
        "has_quote": False,
        "concept_candidates": [],
        "quote_candidates": [],
        "confidence": 0.7,
        "error": None,
    }
    processor, transport = make_preprocessor([], cache=cache)

    hints = await processor.preprocess_chunk("测试书", 5, "test")

    assert hints.chapter_ref == "第二章"
    assert transport.payloads == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run:

```bash
pytest tests/test_local_evidence_preprocessor.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'core.local_evidence_preprocessor'
```

- [ ] **Step 3: 提交失败测试**

```bash
git add tests/test_local_evidence_preprocessor.py
git commit -m "test: add local evidence preprocessor tests"
```

---

### Task 2: 实现 LocalEvidencePreprocessor 最小功能

**Files:**
- Create: `core/local_evidence_preprocessor.py`
- Test: `tests/test_local_evidence_preprocessor.py`

- [ ] **Step 1: 创建实现文件**

Create `core/local_evidence_preprocessor.py`:

```python
"""本地证据预处理器。

使用 NAS Ollama 小模型做短 JSON 候选信号提取。
本模块只产生候选 hints，不产生最终分析内容。
"""

import asyncio
import hashlib
import json
import logging
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Protocol

from utils.parse_cache import get_cache

logger = logging.getLogger("BookGraph-Agent")

PROMPT_VERSION = "v1"


@dataclass
class LocalEvidenceHints:
    """单个 chunk 的本地候选证据信号。"""

    chunk_index: int
    chapter_ref: str = ""
    has_argument: bool = False
    has_concept: bool = False
    has_quote: bool = False
    concept_candidates: List[str] = None
    quote_candidates: List[str] = None
    confidence: float = 0.0
    error: Optional[str] = None

    def __post_init__(self):
        if self.concept_candidates is None:
            self.concept_candidates = []
        if self.quote_candidates is None:
            self.quote_candidates = []

    @classmethod
    def empty(cls, chunk_index: int, error: Optional[str] = None) -> "LocalEvidenceHints":
        return cls(chunk_index=chunk_index, error=error)

    @classmethod
    def from_dict(cls, chunk_index: int, data: Dict[str, Any]) -> "LocalEvidenceHints":
        return cls(
            chunk_index=chunk_index,
            chapter_ref=str(data.get("chapter_ref") or ""),
            has_argument=bool(data.get("has_argument", False)),
            has_concept=bool(data.get("has_concept", False)),
            has_quote=bool(data.get("has_quote", False)),
            concept_candidates=_clean_string_list(data.get("concept_candidates", []), limit=8),
            quote_candidates=_clean_string_list(data.get("quote_candidates", []), limit=5),
            confidence=_clamp_float(data.get("confidence", 0.0)),
            error=data.get("error"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OllamaTransport(Protocol):
    """Ollama 调用传输接口，便于测试替换。"""

    def generate(self, api_base: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        ...


class UrllibOllamaTransport:
    """基于 urllib 的 Ollama HTTP 传输。"""

    def generate(self, api_base: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        endpoint = api_base.rstrip("/") + "/api/generate"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


class LocalEvidencePreprocessor:
    """使用本地 Ollama 小模型抽取短候选证据信号。"""

    def __init__(self, config: Dict[str, Any], cache=None, transport: Optional[OllamaTransport] = None):
        self.enabled = bool(config.get("enabled", False))
        self.api_base = str(config.get("api_base", "http://10.108.1.143:11434"))
        self.model = str(config.get("model", "qwen2.5:3b"))
        self.timeout = int(config.get("timeout", 180))
        self.max_chars = int(config.get("max_chars", 1200))
        self.num_predict = int(config.get("num_predict", 128))
        self.temperature = float(config.get("temperature", 0.0))
        self.cache_results = bool(config.get("cache_results", True))
        self.cache = cache if cache is not None else get_cache()
        self.transport = transport if transport is not None else UrllibOllamaTransport()

    async def preprocess_chunk(self, book_title: str, chunk_index: int, chunk_content: str) -> LocalEvidenceHints:
        """预处理单个 chunk，失败时返回空 hints。"""
        if not self.enabled:
            return LocalEvidenceHints.empty(chunk_index)

        cache_key = self._cache_key(book_title, chunk_index, chunk_content)
        if self.cache_results:
            cached = self.cache.get(cache_key)
            if cached:
                return LocalEvidenceHints.from_dict(chunk_index, cached)

        try:
            prompt = self._build_prompt(chunk_content)
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "num_predict": self.num_predict,
                    "temperature": self.temperature,
                },
            }
            response = await asyncio.to_thread(self.transport.generate, self.api_base, payload, self.timeout)
            raw_text = str(response.get("response") or "")
            parsed = json.loads(raw_text)
            hints = LocalEvidenceHints.from_dict(chunk_index, parsed)
            if self.cache_results:
                self.cache.set(cache_key, hints.to_dict())
            return hints
        except Exception as exc:
            logger.warning(f"   ⚠️ 本地 evidence 预处理失败 chunk={chunk_index}: {str(exc)[:120]}")
            return LocalEvidenceHints.empty(chunk_index, error=f"JSON/OLLAMA_ERROR: {str(exc)[:120]}")

    async def preprocess_chunks(self, book_title: str, chunks: List[tuple], max_parallel: int = 1) -> Dict[int, LocalEvidenceHints]:
        """预处理多个 chunks，返回 chunk_index 到 hints 的映射。"""
        if not self.enabled:
            return {}

        semaphore = asyncio.Semaphore(max(1, max_parallel))

        async def run_one(chunk):
            async with semaphore:
                index, content, _label = chunk
                return index, await self.preprocess_chunk(book_title, index, content)

        results = await asyncio.gather(*(run_one(chunk) for chunk in chunks), return_exceptions=True)
        hints_by_chunk: Dict[int, LocalEvidenceHints] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"   ⚠️ 本地 evidence 批处理异常: {str(result)[:120]}")
                continue
            index, hints = result
            hints_by_chunk[index] = hints
        self._log_summary(hints_by_chunk)
        return hints_by_chunk

    def _cache_key(self, book_title: str, chunk_index: int, chunk_content: str) -> str:
        content_hash = hashlib.md5(chunk_content.encode("utf-8")).hexdigest()
        return f"local_evidence:{self.model}:{PROMPT_VERSION}:{book_title}:{chunk_index}:{content_hash}"

    def _build_prompt(self, chunk_content: str) -> str:
        clipped = chunk_content[: self.max_chars]
        return f"""只从【文本】抽取候选信号，不要使用外部知识，不要解释作者背景。
输出严格 JSON，不要 Markdown，不要代码块。

【文本】
{clipped}

JSON 字段必须为：
{{
  "chapter_ref": "章节名或空字符串",
  "has_argument": true,
  "has_concept": true,
  "has_quote": false,
  "concept_candidates": ["短概念名，最多8个"],
  "quote_candidates": ["原文短句，最多5个"],
  "confidence": 0.0
}}
"""

    def _log_summary(self, hints_by_chunk: Dict[int, LocalEvidenceHints]) -> None:
        if not hints_by_chunk:
            logger.info("   📍 本地 evidence 预处理: 未启用或无结果")
            return
        total = len(hints_by_chunk)
        failed = sum(1 for hints in hints_by_chunk.values() if hints.error)
        concept_count = sum(len(hints.concept_candidates) for hints in hints_by_chunk.values())
        quote_count = sum(len(hints.quote_candidates) for hints in hints_by_chunk.values())
        logger.info(f"   📍 本地 evidence 预处理: {total} chunks")
        logger.info(f"   ✅ 成功: {total - failed}，⚠️ 失败: {failed}")
        logger.info(f"   🏷️ 候选概念: {concept_count}，💬 候选金句: {quote_count}")


def _clean_string_list(value: Any, limit: int) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        cleaned.append(text[:80])
        seen.add(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
```

- [ ] **Step 2: 运行本地预处理器测试**

Run:

```bash
pytest tests/test_local_evidence_preprocessor.py -v
```

Expected:

```text
5 passed
```

- [ ] **Step 3: 修复测试中的缓存 key 若失败**

If `test_preprocess_chunk_uses_cache_when_available` fails because the cache key hash differs, run:

```bash
python3 - <<'PY'
import hashlib
print(hashlib.md5('test'.encode('utf-8')).hexdigest())
PY
```

Expected:

```text
098f6bcd4621d373cade4e832627b4f6
```

Then keep the test key exactly:

```python
"local_evidence:qwen2.5:3b:v1:测试书:5:098f6bcd4621d373cade4e832627b4f6"
```

- [ ] **Step 4: 提交实现**

```bash
git add core/local_evidence_preprocessor.py tests/test_local_evidence_preprocessor.py
git commit -m "feat: add local evidence preprocessor"
```

---

### Task 3: 为云端 chunk prompt 注入本地 hints

**Files:**
- Modify: `core/optimized_chunk_processor.py`
- Create: `tests/test_chunk_local_hints.py`

- [ ] **Step 1: 写 prompt 注入失败测试**

Create `tests/test_chunk_local_hints.py`:

```python
"""Chunk prompt 本地候选信号注入测试。"""

import pytest

from core.local_evidence_preprocessor import LocalEvidenceHints
from core.optimized_chunk_processor import NativeAsyncChunkProcessor


class CapturingAsyncClient:
    """捕获发送给云端模型的 messages。"""

    def __init__(self):
        self.messages = []

    async def _call_llm_async(self, messages, max_tokens=None):
        self.messages.append(messages)
        return '{"chapters": [], "core_concepts": [], "key_insights": [], "key_cases": [], "key_quotes": []}'


@pytest.mark.asyncio
async def test_native_processor_injects_local_hints_into_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = CapturingAsyncClient()
    processor = NativeAsyncChunkProcessor(client, max_parallel=1)
    hints = {
        1: LocalEvidenceHints(
            chunk_index=1,
            chapter_ref="第一章",
            has_argument=True,
            has_concept=True,
            has_quote=True,
            concept_candidates=["真理意志", "哲学家的偏见"],
            quote_candidates=["为什么真理比假象更有价值？"],
            confidence=0.8,
        )
    }

    result = await processor.process_single_chunk(
        chunk_index=1,
        chunk_content="原文内容",
        book_title="测试书",
        system_prompt="系统提示",
        chunk_prompt_template="内容：{chunk_content}",
        use_cache=False,
        local_hints_by_chunk=hints,
    )

    assert result.success is True
    sent_prompt = client.messages[0][1]["content"]
    assert "【本地预处理候选信号】" in sent_prompt
    assert "可能章节：第一章" in sent_prompt
    assert "真理意志、哲学家的偏见" in sent_prompt
    assert "为什么真理比假象更有价值？" in sent_prompt
    assert "必须以原文为准" in sent_prompt


@pytest.mark.asyncio
async def test_native_processor_omits_empty_local_hints(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = CapturingAsyncClient()
    processor = NativeAsyncChunkProcessor(client, max_parallel=1)

    await processor.process_single_chunk(
        chunk_index=1,
        chunk_content="原文内容",
        book_title="测试书",
        system_prompt="系统提示",
        chunk_prompt_template="内容：{chunk_content}",
        use_cache=False,
        local_hints_by_chunk={},
    )

    sent_prompt = client.messages[0][1]["content"]
    assert "【本地预处理候选信号】" not in sent_prompt
```

- [ ] **Step 2: 运行测试，确认失败**

Run:

```bash
pytest tests/test_chunk_local_hints.py -v
```

Expected:

```text
TypeError: NativeAsyncChunkProcessor.process_single_chunk() got an unexpected keyword argument 'local_hints_by_chunk'
```

- [ ] **Step 3: 修改 `NativeAsyncChunkProcessor.process_single_chunk` 签名和 prompt 构造**

Modify `core/optimized_chunk_processor.py` inside `NativeAsyncChunkProcessor.process_single_chunk`.

Change signature from:

```python
async def process_single_chunk(
    self,
    chunk_index: int,
    chunk_content: str,
    book_title: str,
    system_prompt: str,
    chunk_prompt_template: str,
    use_cache: bool = True
) -> ChunkResult:
```

to:

```python
async def process_single_chunk(
    self,
    chunk_index: int,
    chunk_content: str,
    book_title: str,
    system_prompt: str,
    chunk_prompt_template: str,
    use_cache: bool = True,
    local_hints_by_chunk: Optional[Dict[int, object]] = None,
) -> ChunkResult:
```

Replace prompt construction:

```python
prompt = chunk_prompt_template.format(
    book_title=book_title,
    chunk_content=chunk_content
)
```

with:

```python
prompt = chunk_prompt_template.format(
    book_title=book_title,
    chunk_content=chunk_content
)
local_hint_text = _format_local_hint_for_prompt(
    (local_hints_by_chunk or {}).get(chunk_index)
)
if local_hint_text:
    prompt = f"{local_hint_text}\n\n{prompt}"
```

Add helper near module-level functions in `core/optimized_chunk_processor.py`:

```python
def _format_local_hint_for_prompt(hint) -> str:
    """将本地预处理候选信号格式化为 prompt 片段。"""
    if not hint:
        return ""

    chapter_ref = getattr(hint, "chapter_ref", "") or "未知"
    concepts = getattr(hint, "concept_candidates", []) or []
    quotes = getattr(hint, "quote_candidates", []) or []

    if not concepts and not quotes and chapter_ref == "未知":
        return ""

    lines = [
        "【本地预处理候选信号】",
        f"可能章节：{chapter_ref}",
    ]
    if concepts:
        lines.append(f"候选概念：{'、'.join(concepts[:8])}")
    if quotes:
        lines.append(f"候选金句：{'；'.join(quotes[:5])}")
    lines.append("注意：这些只是本地小模型候选信号，必须以原文为准，不可盲信。")
    return "\n".join(lines)
```

- [ ] **Step 4: 将 `process_all` / `process_book_chunks_native_async` 参数向下传递**

In `core/optimized_chunk_processor.py`, find `NativeAsyncChunkProcessor.process_all` and add optional parameter:

```python
local_hints_by_chunk: Optional[Dict[int, object]] = None,
```

When it calls `process_single_chunk`, pass:

```python
local_hints_by_chunk=local_hints_by_chunk,
```

Find `process_book_chunks_native_async` and add optional parameter:

```python
local_hints_by_chunk: Optional[Dict[int, object]] = None,
```

When it calls `processor.process_all`, pass:

```python
local_hints_by_chunk=local_hints_by_chunk,
```

- [ ] **Step 5: 运行注入测试**

Run:

```bash
pytest tests/test_chunk_local_hints.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 6: 运行相关回归测试**

Run:

```bash
pytest tests/test_failed_chunk_logging.py tests/test_chunk_local_hints.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 7: 提交 prompt 注入改造**

```bash
git add core/optimized_chunk_processor.py tests/test_chunk_local_hints.py
git commit -m "feat: inject local evidence hints into chunk prompts"
```

---

### Task 4: 在 main.py 接入本地 evidence 预处理

**Files:**
- Modify: `main.py`
- Test: `tests/test_main_import.py`

- [ ] **Step 1: 在 `main.py` 导入预处理器**

At the imports near existing core imports, add:

```python
from core.local_evidence_preprocessor import LocalEvidencePreprocessor
```

- [ ] **Step 2: 在分块后增加预处理逻辑**

In `process_single_book_optimized`, after:

```python
chunks = _semantic_chunking(parse_result, config)
logger.info(f"   🧩 分块: {len(chunks)} 块")
```

insert:

```python
local_hints_by_chunk = {}
local_preprocessor_config = config.get('improvements', {}).get('local_evidence_preprocessor', {})
if local_preprocessor_config.get('enabled', False):
    logger.info("   📍 启用本地 evidence 预处理")
    local_preprocessor = LocalEvidencePreprocessor(local_preprocessor_config)
    local_hints_by_chunk = await local_preprocessor.preprocess_chunks(
        book_title=parse_result.metadata.get('title', book_path.stem),
        chunks=chunks,
        max_parallel=int(local_preprocessor_config.get('max_parallel', 1)),
    )
```

- [ ] **Step 3: 将 hints 传给云端 chunk processor**

Find call to `process_book_chunks_native_async` in `main.py` and add:

```python
local_hints_by_chunk=local_hints_by_chunk
```

Final call should look like:

```python
chunk_results = await process_book_chunks_native_async(
    async_llm_client,
    chunks,
    book_title,
    SYSTEM_PROMPT,
    CHUNK_ANALYSIS_PROMPT,
    max_parallel,
    local_hints_by_chunk=local_hints_by_chunk,
)
```

- [ ] **Step 4: 运行 import 回归测试**

Run:

```bash
pytest tests/test_main_import.py -v
```

Expected:

```text
1 passed
```

- [ ] **Step 5: 运行本地 evidence 与 chunk 注入测试**

Run:

```bash
pytest tests/test_local_evidence_preprocessor.py tests/test_chunk_local_hints.py tests/test_main_import.py -v
```

Expected:

```text
8 passed
```

- [ ] **Step 6: 提交 main 接入**

```bash
git add main.py
git commit -m "feat: run local evidence preprocessing before chunk analysis"
```

---

### Task 5: 添加配置默认值和文档化注释

**Files:**
- Modify: `config.yaml`
- Test: `tests/test_main_import.py`

- [ ] **Step 1: 在 `config.yaml` 添加开关**

Under `improvements:` after `two_stage_ingest`, add:

```yaml
  # 本地证据预处理：使用 NAS Ollama 小模型做短 JSON 候选信号抽取
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
    max_parallel: 1
```

- [ ] **Step 2: 运行配置加载 smoke test**

Run:

```bash
python3 - <<'PY'
from main import load_config
config = load_config('config.yaml')
local = config['improvements']['local_evidence_preprocessor']
assert local['enabled'] is True
assert local['model'] == 'qwen2.5:3b'
assert local['api_base'] == 'http://10.108.1.143:11434'
print('config ok')
PY
```

Expected:

```text
config ok
```

- [ ] **Step 3: 提交配置**

```bash
git add config.yaml
git commit -m "chore: enable local evidence preprocessing config"
```

---

### Task 6: 增加真实 NAS Ollama 手动验证脚本片段

**Files:**
- Modify: `docs/superpowers/specs/2026-06-09-local-evidence-preprocessor-design.md`
- No production code change.

- [ ] **Step 1: 在设计文档追加手动验证命令**

Append to `docs/superpowers/specs/2026-06-09-local-evidence-preprocessor-design.md`:

```markdown
## 手动验证命令

验证 NAS Ollama 是否可达：

```bash
curl -s http://10.108.1.143:11434/api/tags | python3 -m json.tool
```

验证 `qwen2.5:3b` 短 JSON 输出：

```bash
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
```

- [ ] **Step 2: 提交文档更新**

```bash
git add docs/superpowers/specs/2026-06-09-local-evidence-preprocessor-design.md
git commit -m "docs: add local evidence preprocessor verification steps"
```

---

### Task 7: 全量回归和小范围真实验证

**Files:**
- No new files.

- [ ] **Step 1: 运行目标测试集**

Run:

```bash
pytest tests/test_local_evidence_preprocessor.py tests/test_chunk_local_hints.py tests/test_main_import.py tests/test_failed_chunk_logging.py -v
```

Expected:

```text
9 passed
```

- [ ] **Step 2: 运行完整测试套件**

Run:

```bash
pytest -q
```

Expected:

```text
所有测试通过
```

If unrelated tests fail, record exact failure and do not hide it.

- [ ] **Step 3: 验证 Python 编译**

Run:

```bash
python3 -m py_compile core/local_evidence_preprocessor.py core/optimized_chunk_processor.py main.py
```

Expected: command exits with code 0.

- [ ] **Step 4: 验证 NAS Ollama 可达**

Run:

```bash
curl -s http://10.108.1.143:11434/api/tags | python3 -m json.tool
```

Expected: output contains:

```text
"name": "qwen2.5:3b"
```

- [ ] **Step 5: 小范围运行《善恶的彼岸》前置流程**

Run a limited smoke by importing the preprocessor directly:

```bash
python3 - <<'PY'
import asyncio
from core.local_evidence_preprocessor import LocalEvidencePreprocessor

async def main():
    processor = LocalEvidencePreprocessor({
        "enabled": True,
        "api_base": "http://10.108.1.143:11434",
        "model": "qwen2.5:3b",
        "timeout": 180,
        "max_chars": 300,
        "num_predict": 96,
        "temperature": 0.0,
        "cache_results": False,
    })
    hints = await processor.preprocess_chunk(
        "善恶的彼岸",
        1,
        "尼采追问哲学家为什么偏爱真理而不是非真理。所谓真理意志本身也需要被追问。",
    )
    print(hints.to_dict())
    assert hints.chunk_index == 1

asyncio.run(main())
PY
```

Expected:

```text
字典输出包含 chunk_index、concept_candidates 或 confidence 字段
```

- [ ] **Step 6: 提交最终验证记录或修复**

If only code/config/docs changed and tests passed:

```bash
git status --short
```

Expected: no unexpected untracked files except intended logs/cache. Do not commit generated cache or logs.

---

## Self-Review

### Spec coverage

- 本地 `qwen2.5:3b` 短 JSON 预处理：Task 1, Task 2, Task 5, Task 7。
- 软失败策略：Task 1 invalid JSON / transport error tests, Task 2 implementation。
- 缓存策略：Task 1 cache test, Task 2 cache key and get/set。
- Prompt 注入：Task 3。
- `main.py` 数据流接入：Task 4。
- 推荐模型组合和任务型路由边界：设计文档已记录，第一阶段不实现完整路由，Task 5 保留独立配置边界。
- 验证策略：Task 7。

### Placeholder scan

本计划没有 `TBD`、`TODO`、`implement later`、未定义函数引用或“类似上一任务”的省略步骤。

### Type consistency

- `LocalEvidenceHints` 字段在测试、实现、prompt 注入中一致。
- `local_hints_by_chunk` 类型在 `process_single_chunk`、`process_all`、`process_book_chunks_native_async` 中一致。
- 缓存接口使用现有 `ParseCache.get` / `ParseCache.set`。
