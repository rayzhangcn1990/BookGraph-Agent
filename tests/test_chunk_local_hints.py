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