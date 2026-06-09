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