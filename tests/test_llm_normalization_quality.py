"""LLM 归一化质量测试。"""

from core.llm_client import LLMClient


PLACEHOLDER_MARKERS = ("待补充", "未命名", "[待补充]")


def _contains_placeholder(value):
    """递归检查结构中是否含有占位符。"""
    if isinstance(value, str):
        return any(marker in value for marker in PLACEHOLDER_MARKERS)
    if isinstance(value, dict):
        return any(_contains_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(v) for v in value)
    return False


def test_normalize_book_graph_data_does_not_invent_placeholder_content():
    """归一化只能修结构，不能制造会污染最终图谱的占位符内容。"""
    client = LLMClient({"provider": "openai", "model": "test-model", "api_key": "test-key"})
    data = {
        "core_concepts": [{}],
        "key_insights": [{}],
        "key_cases": [{}],
        "key_quotes": [{}],
    }

    normalized = client._normalize_book_graph_data(data, {"title": "善恶的彼岸", "author": "尼采"})

    assert not _contains_placeholder(normalized)
    assert normalized["metadata"]["title"] == "善恶的彼岸"
    assert normalized["metadata"]["author"] == "尼采"
