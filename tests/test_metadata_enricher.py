"""
元数据增强器测试

测试覆盖：
1. Open Library ISBN 查询
2. Google Books 查询
3. Wikipedia 作者信息
4. 中英文切换
5. 缓存机制
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.metadata_enricher import (
    BookMetadataEnricher,
    MetadataCache,
    enrich_book_metadata,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def enricher():
    """创建元数据增强器实例"""
    return BookMetadataEnricher(cache_dir=".cache/test_metadata")


@pytest.fixture
def cache():
    """创建缓存实例"""
    return MetadataCache(cache_dir=".cache/test_metadata")


# ═══════════════════════════════════════════════════════════
# Open Library Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_openlibrary_isbn_success(enricher):
    """测试 Open Library ISBN 查询成功"""
    mock_response = {
        "ISBN:9780140449137": {
            "title": "The Prince",
            "authors": [{"name": "Niccolò Machiavelli"}],
            "publish_date": "1992",
            "publishers": [{"name": "Penguin Classics"}],
            "subjects": [{"name": "Political philosophy"}],
            "cover": {"medium": "https://example.com/cover.jpg"},
        }
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            return_value=mock_response
        )

        result = await enricher._fetch_openlibrary_isbn("9780140449137")

        assert result is not None
        assert result["title"] == "The Prince"
        assert result["author"] == "Niccolò Machiavelli"
        assert result["year_published"] == "1992"
        assert result["source"] == "openlibrary"


@pytest.mark.asyncio
async def test_fetch_openlibrary_isbn_not_found(enricher):
    """测试 Open Library ISBN 查询无结果"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(return_value={})

        result = await enricher._fetch_openlibrary_isbn("9999999999")
        assert result is None


@pytest.mark.asyncio
async def test_fetch_openlibrary_search(enricher):
    """测试 Open Library 书名作者搜索"""
    mock_response = {
        "docs": [
            {
                "title": "The Prince",
                "author_name": ["Niccolò Machiavelli"],
                "first_publish_year": 1532,
                "subject": ["Political philosophy", "Renaissance"],
            }
        ]
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            return_value=mock_response
        )

        result = await enricher._fetch_openlibrary_search("The Prince", "Machiavelli")

        assert result is not None
        assert result["title"] == "The Prince"
        assert result["author"] == "Niccolò Machiavelli"


# ═══════════════════════════════════════════════════════════
# Google Books Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_googlebooks_isbn_success(enricher):
    """测试 Google Books ISBN 查询成功"""
    mock_response = {
        "items": [
            {
                "volumeInfo": {
                    "title": "The Prince",
                    "authors": ["Niccolò Machiavelli"],
                    "publishedDate": "1992-01-01",
                    "publisher": "Penguin Classics",
                    "categories": ["Political Science"],
                    "averageRating": 4.2,
                    "ratingsCount": 1234,
                    "imageLinks": {"thumbnail": "https://example.com/thumb.jpg"},
                }
            }
        ]
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            return_value=mock_response
        )

        result = await enricher._fetch_googlebooks_isbn("9780140449137")

        assert result is not None
        assert result["title"] == "The Prince"
        assert result["rating"] == 4.2
        assert result["source"] == "googlebooks"


# ═══════════════════════════════════════════════════════════
# Wikipedia Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_wikipedia_author_zh(enricher):
    """测试中文 Wikipedia 作者信息获取"""
    mock_search_response = {
        "query": {
            "search": [{"pageid": 12345}]
        }
    }

    mock_content_response = {
        "query": {
            "pages": {
                "12345": {
                    "extract": "马基雅维利（1469年—1527年）是意大利文艺复兴时期的政治哲学家..."
                }
            }
        }
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        # 模拟两次请求：搜索 + 获取内容
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            side_effect=[mock_search_response, mock_content_response]
        )

        result = await enricher._fetch_wikipedia_author("马基雅维利", lang="zh")

        assert result != ""
        assert "马基雅维利" in result


@pytest.mark.asyncio
async def test_fetch_wikipedia_author_en_fallback(enricher):
    """测试英文 Wikipedia fallback"""
    enricher.author_mappings["测试作者"] = "Test Author"

    # 中文无结果
    mock_zh_response = {"query": {"search": []}}

    # 英文有结果
    mock_en_search = {
        "query": {
            "search": [{"pageid": 67890}]
        }
    }
    mock_en_content = {
        "query": {
            "pages": {
                "67890": {
                    "extract": "Test Author was a famous philosopher..."
                }
            }
        }
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            side_effect=[mock_zh_response, mock_en_search, mock_en_content]
        )

        result = await enricher.enrich_author_info("测试作者")

        # 应该调用英文 fallback
        assert result != ""


# ═══════════════════════════════════════════════════════════
# 中英文切换 Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_chinese_to_english_title_mapping(enricher):
    """测试中文书名映射到英文"""
    # 模拟英文查询成功
    mock_response = {
        "docs": [
            {
                "title": "The Prince",
                "author_name": ["Niccolò Machiavelli"],
                "first_publish_year": 1532,
            }
        ]
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        # 第一次中文查询失败，第二次英文查询成功
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            side_effect=[{"docs": []}, mock_response]
        )

        result = await enricher.enrich_by_title_author("君主论", "马基雅维利")

        assert result is not None
        assert result["title"] == "The Prince"


def test_contains_chinese(enricher):
    """测试中文检测"""
    assert enricher._contains_chinese("沉思录") is True
    assert enricher._contains_chinese("Meditations") is False
    assert enricher._contains_chinese("沉思录 Meditations") is True


def test_to_pinyin_simple(enricher):
    """测试简单拼音转换"""
    assert enricher._to_pinyin_simple("沉思录") == "chensilu"
    assert enricher._to_pinyin_simple("哲学") == "zhexue"


# ═══════════════════════════════════════════════════════════
# 缓存机制 Tests
# ═══════════════════════════════════════════════════════════


def test_cache_set_and_get(cache):
    """测试缓存设置和获取"""
    test_data = {"title": "Test Book", "author": "Test Author"}
    cache.set("test_key", "isbn", "openlibrary", test_data)

    result = cache.get("test_key", "isbn", "openlibrary")
    assert result is not None
    assert result["title"] == "Test Book"


def test_cache_miss(cache):
    """测试缓存未命中"""
    result = cache.get("nonexistent_key", "isbn", "openlibrary")
    assert result is None


def test_cache_expiration(cache):
    """测试缓存过期"""
    test_data = {"title": "Test Book"}

    # 设置已过期的缓存
    from datetime import datetime, timedelta

    import sqlite3
    conn = sqlite3.connect(cache.db_path)
    cursor = conn.cursor()
    expires_at = (datetime.now() - timedelta(days=1)).isoformat()
    cursor.execute(
        "INSERT INTO metadata_cache (query_key, query_type, source, data, expires_at) VALUES (?, ?, ?, ?, ?)",
        ("expired_key", "isbn", "openlibrary", '{"title": "Expired"}', expires_at),
    )
    conn.commit()
    conn.close()

    result = cache.get("expired_key", "isbn", "openlibrary")
    assert result is None


# ═══════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_enrich_by_isbn_full_flow(enricher):
    """测试完整 ISBN 查询流程"""
    mock_ol_response = {
        "ISBN:9780140449137": {
            "title": "The Prince",
            "authors": [{"name": "Niccolò Machiavelli"}],
            "publish_date": "1992",
            "publishers": [{"name": "Penguin Classics"}],
        }
    }

    mock_wiki_search = {"query": {"search": [{"pageid": 12345}]}}
    mock_wiki_content = {
        "query": {
            "pages": {
                "12345": {
                    "extract": "Niccolò Machiavelli was an Italian diplomat..."
                }
            }
        }
    }

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(
            side_effect=[mock_ol_response, mock_wiki_search, mock_wiki_content]
        )

        result = await enricher.enrich_by_isbn("9780140449137")

        assert result["title"] == "The Prince"
        assert result["author"] == "Niccolò Machiavelli"
        assert "author_intro" in result
        assert result["author_intro"] != ""


@pytest.mark.asyncio
async def test_enrich_book_metadata_convenience_function():
    """测试便捷接口"""
    with patch(
        "core.metadata_enricher.BookMetadataEnricher.enrich_by_isbn"
    ) as mock_enrich:
        mock_enrich.return_value = {
            "title": "Test Book",
            "author": "Test Author",
        }

        result = await enrich_book_metadata(isbn="1234567890")

        assert result["title"] == "Test Book"
        mock_enrich.assert_called_once_with("1234567890")


# ═══════════════════════════════════════════════════════════
# 错误处理 Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_api_timeout_handling(enricher):
    """测试 API 超时处理"""
    import asyncio

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.side_effect = asyncio.TimeoutError()

        result = await enricher._fetch_openlibrary_isbn("9780140449137")
        assert result is None


@pytest.mark.asyncio
async def test_api_error_handling(enricher):
    """测试 API 错误处理"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 500

        result = await enricher._fetch_openlibrary_isbn("9780140449137")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
