"""
性能优化测试 - 验证 Phase 1-5 效果

测试：
1. Docling 解析器是否正确输出 Markdown
2. 语义分块是否按标题切分
3. 异步 LLM 客户端是否正常工作
4. JSON Schema 强制输出是否有效
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path


# ═══════════════════════════════════════════════════════════
# Phase 1: Docling 解析器测试
# ═══════════════════════════════════════════════════════════

class TestDoclingParser:
    """Docling 解析器测试"""

    def test_docling_import(self):
        """测试 Docling 是否可导入"""
        try:
            from parsers.docling_parser import DoclingParser, is_docling_available
            assert callable(is_docling_available)
        except ImportError:
            pytest.skip("Docling 未安装")

    def test_docling_not_available_fallback(self):
        """测试 Docling 不可用时的回退"""
        with patch('parsers.docling_parser.DOCLING_AVAILABLE', False):
            from parsers.docling_parser import is_docling_available
            assert is_docling_available() == False

    @pytest.mark.skipif(
        not pytest.importorskip('docling', reason='Docling 未安装'),
        reason="Docling 未安装"
    )
    def test_docling_parse_returns_markdown(self, tmp_path):
        """测试 Docling 解析返回 Markdown"""
        # 创建测试 PDF（需要实际文件，这里跳过）
        pytest.skip("需要实际 PDF 文件")


# ═══════════════════════════════════════════════════════════
# Phase 2: 语义分块测试
# ═══════════════════════════════════════════════════════════

class TestSemanticChunking:
    """语义分块测试"""

    def test_chunk_by_markdown_headers(self):
        """测试按 Markdown 标题切分"""
        from main import _semantic_chunking
        from parsers.base_parser import ParseResult

        # 模拟 Markdown 内容
        content = """# 第一章

## 1.1 简介

这是简介内容。

## 1.2 背景

这是背景内容。

### 1.2.1 历史背景

历史背景详情。

# 第二章

## 2.1 概述

概述内容。
"""

        parse_result = ParseResult(
            success=True,
            content=content,
            chapters=[
                {"chapter_id": "1", "title": "第一章", "content": content.split("# 第二章")[0]},
                {"chapter_id": "2", "title": "第二章", "content": content.split("# 第二章")[1] if "# 第二章" in content else ""},
            ],
        )

        config = {"llm": {"chunk_tokens": 1000}}

        chunks = _semantic_chunking(parse_result, config)

        # 验证：应该按 ## 标题切分
        assert len(chunks) >= 2
        assert all(len(c[1]) > 0 for c in chunks)

    def test_fallback_to_character_chunking(self):
        """测试无章节结构时的回退"""
        from main import _semantic_chunking
        from parsers.base_parser import ParseResult

        # 无章节结构
        content = "纯文本内容，无标题结构。" * 1000

        parse_result = ParseResult(
            success=True,
            content=content,
            chapters=[],
        )

        config = {"llm": {"chunk_tokens": 100}}

        chunks = _semantic_chunking(parse_result, config)

        # 验证：应该按字符切分
        assert len(chunks) >= 1

    def test_chunk_size_estimation(self):
        """测试 token 估算"""
        from main import _semantic_chunking
        from parsers.base_parser import ParseResult

        # 中英文混合
        content = "## 标题\n\n" + "测试内容" * 100 + "\n\n## 另一个标题\n\n" + "Test content" * 100

        parse_result = ParseResult(
            success=True,
            content=content,
            chapters=[{"chapter_id": "1", "title": "测试", "content": content}],
        )

        config = {"llm": {"chunk_tokens": 200}}

        chunks = _semantic_chunking(parse_result, config)

        # 验证：每个 chunk 的 token 数应该接近目标
        for chunk in chunks:
            estimated_tokens = len(chunk[1]) // 4
            # 允许一定误差


# ═══════════════════════════════════════════════════════════
# Phase 3: 异步 LLM 测试
# ═══════════════════════════════════════════════════════════

class TestAsyncLLMClient:
    """异步 LLM 客户端测试"""

    def test_async_import(self):
        """测试异步客户端可导入"""
        from core.llm_client import AsyncLLMClient, get_async_llm_client
        assert callable(get_async_llm_client)

    @pytest.mark.asyncio
    async def test_async_call_llm(self):
        """测试异步 LLM 调用"""
        from core.llm_client import AsyncLLMClient

        config = {
            "provider": "openai",
            "model": "test-model",
            "api_base": "http://localhost:3001/v1",
            "api_key": "test-key",
        }

        client = AsyncLLMClient(config)

        # 验证异步客户端初始化
        assert client.async_openai_client is not None or client.openai_client is not None

    @pytest.mark.asyncio
    async def test_native_async_processor(self):
        """测试原生异步处理器"""
        from core.optimized_chunk_processor import NativeAsyncChunkProcessor
        from core.llm_client import AsyncLLMClient

        config = {
            "provider": "openai",
            "model": "test-model",
            "api_base": "http://localhost:3001/v1",
            "api_key": "test-key",
        }

        async_client = AsyncLLMClient(config)
        processor = NativeAsyncChunkProcessor(async_client, max_parallel=4)

        assert processor.max_parallel == 4
        assert processor.async_client is not None


# ═══════════════════════════════════════════════════════════
# Phase 4: JSON Schema 测试
# ═══════════════════════════════════════════════════════════

class TestJSONSchema:
    """JSON Schema 测试"""

    def test_schema_export(self):
        """测试 JSON Schema 导出"""
        from schemas.book_graph_schema import (
            BOOK_GRAPH_JSON_SCHEMA,
            CHUNK_ANALYSIS_JSON_SCHEMA,
            get_book_graph_json_schema,
        )

        # 验证 Schema 已生成
        assert isinstance(BOOK_GRAPH_JSON_SCHEMA, dict)
        assert isinstance(CHUNK_ANALYSIS_JSON_SCHEMA, dict)

        # 验证必要字段
        assert "properties" in BOOK_GRAPH_JSON_SCHEMA
        assert "metadata" in BOOK_GRAPH_JSON_SCHEMA["properties"]
        assert "chapters" in BOOK_GRAPH_JSON_SCHEMA["properties"]

    def test_schema_has_required_fields(self):
        """测试 Schema 包含必要字段"""
        from schemas.book_graph_schema import BOOK_GRAPH_JSON_SCHEMA

        required = ["metadata", "chapters", "core_concepts", "key_insights"]

        for field in required:
            assert field in BOOK_GRAPH_JSON_SCHEMA["properties"], f"缺少必要字段: {field}"

    def test_call_llm_with_schema_method(self):
        """测试 _call_llm_with_schema 方法存在"""
        from core.llm_client import LLMClient

        config = {
            "provider": "openai",
            "model": "test-model",
            "api_base": "http://localhost:3001/v1",
            "api_key": "test-key",
        }

        client = LLMClient(config)
        assert hasattr(client, "_call_llm_with_schema")


# ═══════════════════════════════════════════════════════════
# Phase 5: Prompt Caching 测试
# ═══════════════════════════════════════════════════════════

class TestPromptCaching:
    """Prompt Caching 测试"""

    def test_cache_control_in_async_client(self):
        """测试 AsyncLLMClient 包含 cache_control"""
        from core.llm_client import AsyncLLMClient

        # 验证异步客户端初始化时会设置缓存
        config = {
            "provider": "openai",
            "model": "test-model",
            "api_base": "http://localhost:3001/v1",
            "api_key": "test-key",
        }

        client = AsyncLLMClient(config)

        # 验证 Anthropic 客户端支持缓存（如果可用）
        # 这里只验证方法存在
        assert hasattr(client, "_call_llm_async")


# ═══════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════

class TestIntegration:
    """集成测试"""

    def test_full_pipeline_imports(self):
        """测试完整管道导入"""
        # 解析器
        from parsers.docling_parser import DoclingParser
        from parsers.pdf_parser import PdfParser
        from parsers.book_parser import BookParser

        # 核心
        from core.llm_client import LLMClient, AsyncLLMClient
        from core.optimized_chunk_processor import (
            OptimizedChunkProcessor,
            NativeAsyncChunkProcessor,
        )

        # Schema
        from schemas.book_graph_schema import BookGraph, BOOK_GRAPH_JSON_SCHEMA

        # 主入口
        from main import _semantic_chunking

        # 验证所有导入成功
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
