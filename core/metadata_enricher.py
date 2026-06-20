"""
书籍元数据增强器

聚合多个 Books API，提供书籍元数据增强功能：
- Open Library: 主数据源（免费无需 Key）
- Google Books: 备选数据源（简介、评分）
- Wikipedia: 作者信息增强

核心功能：
1. ISBN 精确查询
2. 书名+作者模糊搜索
3. 中英文书名/作者名自动切换
4. 本地缓存机制（SQLite）
"""

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


class MetadataCache:
    """元数据本地缓存（SQLite）"""

    def __init__(self, cache_dir: str = ".cache/metadata"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "metadata_cache.db"
        self._init_db()

    def _init_db(self):
        """初始化缓存数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_key TEXT NOT NULL,
                query_type TEXT NOT NULL,
                source TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                UNIQUE(query_key, query_type, source)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_query ON metadata_cache(query_key, query_type)
        """)
        conn.commit()
        conn.close()

    def get(self, query_key: str, query_type: str, source: str) -> Optional[Dict]:
        """获取缓存数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT data, expires_at FROM metadata_cache
            WHERE query_key = ? AND query_type = ? AND source = ?
        """, (query_key, query_type, source))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        data_json, expires_at = row
        if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
            return None

        import json
        return json.loads(data_json)

    def set(self, query_key: str, query_type: str, source: str, data: Dict, ttl_days: int = 30):
        """设置缓存数据"""
        import json
        expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO metadata_cache (query_key, query_type, source, data, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (query_key, query_type, source, json.dumps(data, ensure_ascii=False), expires_at))
        conn.commit()
        conn.close()


class BookMetadataEnricher:
    """
    书籍元数据增强器

    支持中英文书名/作者名自动切换：
    - 输入中文书名 → 尝试英文原名查询
    - 输入作者中文名 → 尝试英文名/拼音查询
    - ISBN 查询 → 获取所有语言版本
    """

    def __init__(self, cache_dir: str = ".cache/metadata"):
        self.cache = MetadataCache(cache_dir)

        # API 端点
        self.openlibrary_base = "https://openlibrary.org"
        self.googlebooks_base = "https://www.googleapis.com/books/v1"
        self.wikipedia_zh_base = "https://zh.wikipedia.org/w/api.php"
        self.wikipedia_en_base = "https://en.wikipedia.org/w/api.php"

        # 常见中英文书名映射
        self.title_mappings = {
            "君主论": "The Prince",
            "利维坦": "Leviathan",
            "社会契约论": "The Social Contract",
            "政治学": "Politics",
            "理想国": "The Republic",
            "沉思录": "Meditations",
            "西方哲学史": "A History of Western Philosophy",
            "哲学的故事": "The Story of Philosophy",
            "善恶的彼岸": "Beyond Good and Evil",
        }

        # 常见中英文作者名映射
        self.author_mappings = {
            "马基雅维利": "Niccolò Machiavelli",
            "霍布斯": "Thomas Hobbes",
            "卢梭": "Jean-Jacques Rousseau",
            "亚里士多德": "Aristotle",
            "柏拉图": "Plato",
            "马克思": "Karl Marx",
            "尼采": "Friedrich Nietzsche",
            "康德": "Immanuel Kant",
            "黑格尔": "Georg Wilhelm Friedrich Hegel",
            "罗素": "Bertrand Russell",
            "奥勒留": "Marcus Aurelius",
        }

    async def enrich_by_isbn(self, isbn: str, llm_client=None) -> Dict[str, Any]:
        """
        通过 ISBN 增强元数据（最高优先级）

        Args:
            isbn: ISBN 编号（10 位或 13 位）
            llm_client: LLM 客户端（用于 API 无数据时的 fallback）

        Returns:
            Dict: 元数据字典
        """
        # 清理 ISBN（移除连字符）
        isbn = re.sub(r"[-\s]", "", isbn)

        # 检查缓存
        cached = self.cache.get(isbn, "isbn", "combined")
        if cached:
            logger.info(f"缓存命中: ISBN {isbn}")
            return cached

        # 尝试 Open Library
        metadata = await self._fetch_openlibrary_isbn(isbn)

        # Open Library 无数据 → 尝试 Google Books
        if not metadata:
            metadata = await self._fetch_googlebooks_isbn(isbn)

        # ponytail: API 都无数据 → 使用 LLM fallback
        if not metadata and llm_client:
            logger.info(f"API 无数据，使用 LLM 获取 ISBN {isbn} 的元数据")
            metadata = await self._fetch_llm_metadata(llm_client, isbn=isbn)

        # 增强作者信息
        if metadata and metadata.get("author"):
            author_info = await self.enrich_author_info(
                metadata["author"], llm_client=llm_client
            )
            metadata["author_intro"] = author_info

        # 缓存结果
        if metadata:
            self.cache.set(isbn, "isbn", "combined", metadata)

        return metadata or {}

    async def enrich_by_title_author(
        self, title: str, author: str = "", llm_client=None
    ) -> Dict[str, Any]:
        """
        通过书名和作者增强元数据（支持中英文切换）

        Args:
            title: 书名（中文或英文）
            author: 作者名（中文或英文，可选）
            llm_client: LLM 客户端（用于 API 无数据时的 fallback）

        Returns:
            Dict: 元数据字典
        """
        cache_key = f"{title}_{author}"
        cached = self.cache.get(cache_key, "title_author", "combined")
        if cached:
            logger.info(f"缓存命中: {title} - {author}")
            return cached

        metadata = None
        original_language = self._detect_language(title, author)  # 检测原始语言

        # ponytail: 中英文切换策略
        # 1. 尝试原始输入
        metadata = await self._search_by_title_author(title, author)

        # 2. 如果失败，尝试英文映射
        if not metadata:
            title_en = self.title_mappings.get(title, title)
            author_en = self.author_mappings.get(author, author)

            if title_en != title or author_en != author:
                logger.info(f"尝试英文映射: {title} → {title_en}")
                metadata = await self._search_by_title_author(title_en, author_en)

        # 3. 如果仍失败，尝试拼音（简化版）
        if not metadata and self._contains_chinese(title):
            title_pinyin = self._to_pinyin_simple(title)
            logger.info(f"尝试拼音搜索: {title} → {title_pinyin}")
            metadata = await self._search_by_title_author(title_pinyin, author)

        # ponytail: 🔑 关键修复 - API返回英文数据时，保留原始中文
        # 如果原始书籍是中文，但API返回了英文元数据，强制回退到LLM
        if metadata and metadata.get("source") == "openlibrary":
            # 检查API返回的元数据是否与原始语言不一致
            api_title_lang = self._detect_language(metadata.get("title", ""))
            if original_language == "zh" and api_title_lang != "zh":
                logger.info(f"⚠️ OpenLibrary返回英文数据，原始书籍为中文，回退到LLM")
                metadata = None  # 清除英文元数据，强制使用LLM

        # ponytail: API 都无数据 → 使用 LLM fallback
        if not metadata and llm_client:
            logger.info(f"API 无数据，使用 LLM 获取 {title} 的元数据")
            metadata = await self._fetch_llm_metadata(
                llm_client, title=title, author=author
            )

        # 增强作者信息
        if metadata and metadata.get("author"):
            author_info = await self.enrich_author_info(
                metadata["author"], llm_client=llm_client
            )
            metadata["author_intro"] = author_info

        # 缓存结果
        if metadata:
            self.cache.set(cache_key, "title_author", "combined", metadata)

        return metadata or {}

    async def enrich_author_info(self, author_name: str, llm_client=None) -> str:
        """
        从 Wikipedia 获取作者信息（优先中文，fallback 英文，最终 LLM）

        Args:
            author_name: 作者名（中文或英文）
            llm_client: LLM 客户端（用于 Wikipedia 无数据时的 fallback）

        Returns:
            str: 作者简介（200-500 字）
        """
        cache_key = f"author_{author_name}"
        cached = self.cache.get(cache_key, "author", "wikipedia")
        if cached:
            return cached.get("intro", "")

        # 尝试中文 Wikipedia
        intro = await self._fetch_wikipedia_author(author_name, lang="zh")

        # 中文无结果 → 尝试英文映射
        if not intro:
            author_en = self.author_mappings.get(author_name, author_name)
            if author_en != author_name:
                intro = await self._fetch_wikipedia_author(author_en, lang="en")

        # 仍无结果 → 尝试英文 Wikipedia
        if not intro:
            intro = await self._fetch_wikipedia_author(author_name, lang="en")

        # ponytail: Wikipedia 无数据 → 使用 LLM fallback
        if not intro and llm_client:
            logger.info(f"Wikipedia 无数据，使用 LLM 获取 {author_name} 的简介")
            intro = await self._fetch_llm_author_intro(llm_client, author_name)

        # 缓存结果
        if intro:
            self.cache.set(cache_key, "author", "wikipedia", {"intro": intro})

        return intro

    async def _search_by_title_author(
        self, title: str, author: str
    ) -> Optional[Dict]:
        """通过书名作者搜索（尝试多个 API）"""
        # 尝试 Open Library
        metadata = await self._fetch_openlibrary_search(title, author)

        # Open Library 无数据 → 尝试 Google Books
        if not metadata:
            metadata = await self._fetch_googlebooks_search(title, author)

        return metadata

    async def _fetch_openlibrary_isbn(self, isbn: str) -> Optional[Dict]:
        """从 Open Library 获取书籍信息（ISBN 查询）"""
        url = f"{self.openlibrary_base}/api/books"
        params = {
            "bibkeys": f"ISBN:{isbn}",
            "format": "json",
            "jscmd": "data",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if f"ISBN:{isbn}" in data:
                            return self._parse_openlibrary(data[f"ISBN:{isbn}"])
        except Exception as e:
            logger.warning(f"Open Library ISBN 查询失败: {e}")

        return None

    async def _fetch_openlibrary_search(
        self, title: str, author: str
    ) -> Optional[Dict]:
        """从 Open Library 搜索书籍（书名+作者）"""
        url = f"{self.openlibrary_base}/search.json"
        params = {"title": title, "limit": 5}

        if author:
            params["author"] = author

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("docs"):
                            # 选择最相关的结果
                            best_match = data["docs"][0]
                            return self._parse_openlibrary_search(best_match)
        except Exception as e:
            logger.warning(f"Open Library 搜索失败: {e}")

        return None

    async def _fetch_googlebooks_isbn(self, isbn: str) -> Optional[Dict]:
        """从 Google Books 获取书籍信息（ISBN 查询）"""
        url = f"{self.googlebooks_base}/volumes"
        params = {"q": f"isbn:{isbn}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("items"):
                            return self._parse_googlebooks(data["items"][0])
        except Exception as e:
            logger.warning(f"Google Books ISBN 查询失败: {e}")

        return None

    async def _fetch_googlebooks_search(
        self, title: str, author: str
    ) -> Optional[Dict]:
        """从 Google Books 搜索书籍（书名+作者）"""
        url = f"{self.googlebooks_base}/volumes"
        query = f"intitle:{title}"
        if author:
            query += f" inauthor:{author}"
        params = {"q": query, "maxResults": 5}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("items"):
                            return self._parse_googlebooks(data["items"][0])
        except Exception as e:
            logger.warning(f"Google Books 搜索失败: {e}")

        return None

    async def _fetch_wikipedia_author(
        self, author_name: str, lang: str = "zh"
    ) -> str:
        """从 Wikipedia 获取作者信息"""
        base_url = (
            self.wikipedia_zh_base if lang == "zh" else self.wikipedia_en_base
        )

        # 搜索作者页面
        search_url = f"{base_url}?action=query&list=search"
        params = {"srsearch": author_name, "format": "json"}

        try:
            async with aiohttp.ClientSession() as session:
                # 1. 搜索页面
                async with session.get(search_url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return ""

                    data = await resp.json()
                    if not data.get("query", {}).get("search"):
                        return ""

                    page_id = data["query"]["search"][0]["pageid"]

                # 2. 获取页面内容
                content_url = f"{base_url}?action=query&prop=extracts"
                params = {
                    "pageids": page_id,
                    "format": "json",
                    "exintro": True,
                    "explaintext": True,
                }

                async with session.get(content_url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return ""

                    data = await resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    if str(page_id) in pages:
                        extract = pages[str(page_id)].get("extract", "")
                        return self._clean_wikipedia_extract(extract)

        except Exception as e:
            logger.warning(f"Wikipedia 作者查询失败 ({lang}): {e}")

        return ""

    def _parse_openlibrary(self, data: Dict) -> Dict:
        """解析 Open Library 响应"""
        return {
            "title": data.get("title"),
            "author": data.get("authors", [{}])[0].get("name")
            if data.get("authors")
            else None,
            "year_published": data.get("publish_date", "")[:4]
            if data.get("publish_date")
            else None,
            "publisher": data.get("publishers", [{}])[0].get("name")
            if data.get("publishers")
            else None,
            "tags": [s.get("name", "") for s in data.get("subjects", [])],
            "cover_url": data.get("cover", {}).get("medium"),
            "source": "openlibrary",
        }

    def _parse_openlibrary_search(self, data: Dict) -> Dict:
        """解析 Open Library 搜索结果"""
        return {
            "title": data.get("title"),
            "author": data.get("author_name", [None])[0]
            if data.get("author_name")
            else None,
            "year_published": data.get("first_publish_year"),
            "tags": data.get("subject", []),
            "source": "openlibrary",
        }

    def _parse_googlebooks(self, data: Dict) -> Dict:
        """解析 Google Books 响应"""
        vol = data.get("volumeInfo", {})
        return {
            "title": vol.get("title"),
            "author": ", ".join(vol.get("authors", [])),
            "year_published": vol.get("publishedDate", "")[:4],
            "publisher": vol.get("publisher"),
            "tags": vol.get("categories", []),
            "cover_url": vol.get("imageLinks", {}).get("thumbnail"),
            "description": vol.get("description"),
            "rating": vol.get("averageRating"),
            "ratings_count": vol.get("ratingsCount"),
            "source": "googlebooks",
        }

    def _clean_wikipedia_extract(self, extract: str) -> str:
        """清理 Wikipedia 提取的文本"""
        # 移除多余空白
        clean = re.sub(r"\s+", " ", extract).strip()
        # 截取前 500 字符
        return clean[:500] + "..." if len(clean) > 500 else clean

    def _contains_chinese(self, text: str) -> bool:
        """检测文本是否包含中文"""
        return any("一" <= char <= "鿿" for char in text)

    def _detect_language(self, title: str, author: str = "") -> str:
        """
        检测书籍原始语言（中文或英文）

        Args:
            title: 书名
            author: 作者名（可选）

        Returns:
            str: "zh"（中文）或 "en"（英文）
        """
        combined = f"{title} {author}"

        # 如果标题或作者包含中文，判定为中文书籍
        if self._contains_chinese(combined):
            return "zh"

        # 否则判定为英文书籍
        return "en"

    def _to_pinyin_simple(self, text: str) -> str:
        """
        简单拼音转换（仅处理常见字）

        ponytail: 不引入 pypinyin 依赖，使用硬编码映射
        如需完整拼音支持，请安装 pypinyin
        """
        # 常见中文字符拼音映射（简化版）
        pinyin_map = {
            "沉": "chen",
            "思": "si",
            "录": "lu",
            "哲": "zhe",
            "学": "xue",
            "史": "shi",
            "西": "xi",
            "方": "fang",
            "君": "jun",
            "主": "zhu",
            "论": "lun",
            "政": "zheng",
            "治": "zhi",
        }

        result = []
        for char in text:
            if char in pinyin_map:
                result.append(pinyin_map[char])
            elif char.isalpha():
                result.append(char)
            else:
                result.append(" ")

        return "".join(result)


    # ═══════════════════════════════════════════════════════════
    # LLM Fallback 方法（API 无数据时的兜底方案）
    # ═══════════════════════════════════════════════════════════

    async def _fetch_llm_metadata(
        self, llm_client, isbn: str = None, title: str = None, author: str = None
    ) -> Optional[Dict]:
        """
        使用 LLM 获取书籍元数据（当 API 都无数据时）

        ponytail: 使用简单的 prompt 避免复杂推理，节省 token

        Args:
            llm_client: LLM 客户端
            isbn: ISBN 编号（可选）
            title: 书名（可选）
            author: 作者名（可选）

        Returns:
            Optional[Dict]: 元数据字典
        """
        if isbn:
            prompt = f"请提供 ISBN {isbn} 对应书籍的基本信息（书名、作者、出版年份、出版社），用 JSON 格式返回。"
        else:
            prompt = f"请提供《{title}》（作者：{author or '未知'}）的基本信息（作者、出版年份、出版社），用 JSON 格式返回。"

        try:
            # 使用 asyncio.to_thread 包装同步 LLM 调用
            response = await asyncio.to_thread(
                llm_client._call_llm,
                [{"role": "user", "content": prompt}],
                max_tokens=500,
            )

            if response:
                # 解析 JSON（简化版，不需要严格校验）
                import json
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    data = json.loads(response[json_start:json_end])
                    return {
                        "title": data.get("title") or title,
                        "author": data.get("author") or author,
                        "year_published": data.get("year_published"),
                        "publisher": data.get("publisher"),
                        "source": "llm",
                    }
        except Exception as e:
            logger.warning(f"LLM 元数据获取失败: {e}")

        return None

    async def _fetch_llm_author_intro(self, llm_client, author_name: str) -> str:
        """
        使用 LLM 获取作者简介（当 Wikipedia 无数据时）

        ponytail: 使用简单的 prompt，限制 200 字

        Args:
            llm_client: LLM 客户端
            author_name: 作者名

        Returns:
            str: 作者简介（200-300 字）
        """
        prompt = f"请用 200-300 字介绍 {author_name} 的生平和主要贡献，包括出生年份、国籍、主要作品、思想流派。"

        try:
            response = await asyncio.to_thread(
                llm_client._call_llm,
                [{"role": "user", "content": prompt}],
                max_tokens=400,
            )

            if response:
                # 清理并截断
                clean = re.sub(r"\s+", " ", response).strip()
                return clean[:500] + "..." if len(clean) > 500 else clean
        except Exception as e:
            logger.warning(f"LLM 作者简介获取失败: {e}")

        return ""


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_enricher: Optional[BookMetadataEnricher] = None


def get_metadata_enricher() -> BookMetadataEnricher:
    """获取全局元数据增强器单例"""
    global _enricher
    if _enricher is None:
        _enricher = BookMetadataEnricher()
    return _enricher


async def enrich_book_metadata(
    isbn: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    llm_client=None,
) -> Dict[str, Any]:
    """
    增强书籍元数据（便捷接口）

    优先级：ISBN > 书名+作者

    三层 fallback：
    1. Open Library / Google Books API
    2. Wikipedia（作者信息）
    3. LLM（当 API 都无数据时）

    Args:
        isbn: ISBN 编号（可选）
        title: 书名（可选）
        author: 作者名（可选）
        llm_client: LLM 客户端（用于 API 无数据时的 fallback）

    Returns:
        Dict: 元数据字典
    """
    enricher = get_metadata_enricher()

    if isbn:
        return await enricher.enrich_by_isbn(isbn, llm_client=llm_client)
    elif title:
        return await enricher.enrich_by_title_author(
            title, author or "", llm_client=llm_client
        )
    else:
        return {}
