"""语义分块合并测试。"""

from main import _merge_small_chunks


def test_merge_small_chunks_respects_target_size():
    """小块合并应接近目标大小，不能把所有小块吞成一个巨块。"""
    chunks = [(i, "测试内容" * 40, f"章节{i}") for i in range(20)]

    merged = _merge_small_chunks(chunks, target_tokens=200, min_tokens=50)

    assert len(merged) > 1
    assert max(len(content) // 4 for _, content, _ in merged) <= 260
    assert merged[0][0] == 0
    assert merged[1][0] != merged[0][0]
