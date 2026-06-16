#!/usr/bin/env python3
"""
JSON知识库持久化测试

验证 P0 优化：JSON知识库持久化功能
"""

import pytest
import tempfile
from pathlib import Path
from utils.json_knowledge_persistence import (
    JSONKnowledgeBase,
    enable_test_mode,
    disable_test_mode
)


@pytest.fixture(autouse=True)
def test_mode():
    """每个测试前后启用/禁用测试模式"""
    enable_test_mode()
    yield
    disable_test_mode()


def test_json_knowledge_base_init():
    """测试知识库初始化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_kb.json"
        kb = JSONKnowledgeBase(db_path=str(db_path))

        assert kb.db_path == db_path
        assert kb.index_path.suffix == ".db"


def test_save_and_get_chunk_result():
    """测试保存和查询 chunk 结果"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_kb.json"
        kb = JSONKnowledgeBase(db_path=str(db_path))

        # 保存 chunk 结果
        chunk_result = {
            "chapter_summaries": ["第一章摘要"],
            "core_concepts": ["概念1", "概念2"]
        }
        success = kb.save_chunk_result(
            book_title="君主论",
            chunk_index=0,
            result=chunk_result,
            content_hash="abc123"
        )

        assert success

        # 查询 chunk 结果
        cached = kb.get_chunk_result(
            book_title="君主论",
            content_hash="abc123"
        )

        assert cached is not None
        assert cached == chunk_result


def test_save_and_get_author_info():
    """测试保存和查询作者信息（跨书籍复用）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_kb.json"
        kb = JSONKnowledgeBase(db_path=str(db_path))

        # 保存作者信息
        author_info = {
            "name": "马基雅维利",
            "intro": "意大利政治思想家",
            "birth_year": 1469
        }
        success = kb.save_author_info(
            author_name="马基雅维利",
            author_info=author_info,
            source="wikipedia"
        )

        assert success

        # 查询作者信息
        cached_info = kb.get_author_info("马基雅维利")

        assert cached_info is not None
        assert cached_info == author_info


def test_get_stats():
    """测试统计信息"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_kb.json"
        kb = JSONKnowledgeBase(db_path=str(db_path))

        # 保存一些数据
        kb.save_chunk_result("书1", 0, {}, "hash1")
        kb.save_chunk_result("书2", 0, {}, "hash2")
        kb.save_author_info("作者1", {}, "wikipedia")

        stats = kb.get_stats()

        assert stats["total"] >= 3
        assert "by_type" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
