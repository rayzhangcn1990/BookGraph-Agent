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
