"""失败 Chunk 原始响应落盘测试。"""

import pytest

from core.optimized_chunk_processor import NativeAsyncChunkProcessor


class FakeAsyncClient:
    """返回非 JSON 响应的假异步客户端。"""

    async def _call_llm_async(self, messages, max_tokens=None):
        return "这不是 JSON 响应"


@pytest.mark.asyncio
async def test_failed_chunk_raw_response_is_saved(tmp_path, monkeypatch):
    """Chunk JSON 解析失败时应保存 raw_response，便于诊断模型输出。"""
    monkeypatch.chdir(tmp_path)
    processor = NativeAsyncChunkProcessor(FakeAsyncClient(), max_parallel=1)
    processor.retry_delays = [0, 0, 0]
    processor.max_retries = 1

    result = await processor.process_single_chunk(
        chunk_index=3,
        chunk_content="测试内容",
        book_title="测试书籍",
        system_prompt="系统提示",
        chunk_prompt_template="内容：{chunk_content}",
        use_cache=False,
    )

    failed_path = tmp_path / "logs" / "failed_chunks" / "测试书籍_chunk_3_retry_1.txt"
    assert not result.success
    assert failed_path.read_text(encoding="utf-8") == "这不是 JSON 响应"
