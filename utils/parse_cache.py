"""
解析结果缓存系统

功能：
- 缓存 chunk 分析结果，避免重复调用 LLM
- 支持断点续传，失败后从缓存恢复
- 自动清理过期缓存
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
import logging

logger = logging.getLogger("BookGraph-Agent")


class ParseCache:
    """解析结果缓存管理器"""

    def __init__(self, cache_dir: str = ".cache/parse_results"):
        """
        初始化缓存管理器

        Args:
            cache_dir: 缓存目录路径
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = 7  # 缓存最大保留天数

    def _get_cache_key(self, book_title: str, chunk_index: int, chunk_content: str) -> str:
        """
        生成缓存键（基于内容的哈希）

        Args:
            book_title: 书名
            chunk_index: chunk 索引
            chunk_content: chunk 内容

        Returns:
            str: 缓存键
        """
        # 使用内容哈希确保唯一性
        content_hash = hashlib.md5(chunk_content.encode()).hexdigest()[:12]
        return f"{book_title}_{chunk_index}_{content_hash}"

    def get_cached_result(self, book_title: str, chunk_index: int, chunk_content: str) -> Optional[Dict]:
        """
        获取缓存的解析结果

        Args:
            book_title: 书名
            chunk_index: chunk 索引
            chunk_content: chunk 内容

        Returns:
            Optional[Dict]: 缓存结果，不存在则返回 None
        """
        cache_key = self._get_cache_key(book_title, chunk_index, chunk_content)
        cache_file = self.cache_dir / f"{cache_key}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)

            # 检查缓存是否过期
            cached_time = datetime.fromisoformat(cached.get('timestamp', '2000-01-01'))
            if datetime.now() - cached_time > timedelta(days=self.max_age_days):
                logger.info(f"   🗑️ 缓存过期: {cache_key}")
                cache_file.unlink()
                return None

            logger.info(f"   ✅ 使用缓存: {cache_key}")
            return cached.get('result')

        except Exception as e:
            logger.warning(f"   ⚠️ 缓存读取失败: {e}")
            return None

    def save_result(self, book_title: str, chunk_index: int, chunk_content: str, result: Dict):
        """
        保存解析结果到缓存

        Args:
            book_title: 书名
            chunk_index: chunk 索引
            chunk_content: chunk 内容
            result: 解析结果
        """
        cache_key = self._get_cache_key(book_title, chunk_index, chunk_content)
        cache_file = self.cache_dir / f"{cache_key}.json"

        try:
            cached = {
                'timestamp': datetime.now().isoformat(),
                'book_title': book_title,
                'chunk_index': chunk_index,
                'content_hash': hashlib.md5(chunk_content.encode()).hexdigest(),
                'result': result,
            }

            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cached, f, ensure_ascii=False, indent=2)

            logger.info(f"   💾 缓存保存: {cache_key}")

        except Exception as e:
            logger.warning(f"   ⚠️ 缓存保存失败: {e}")

    def get_book_progress(self, book_title: str) -> Dict:
        """
        获取书籍的处理进度

        Args:
            book_title: 书名

        Returns:
            Dict: 进度信息 {completed_chunks, total_cached, cache_files}
        """
        cache_files = list(self.cache_dir.glob(f"{book_title}_*.json"))

        completed_chunks = []
        for cf in cache_files:
            try:
                with open(cf, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                completed_chunks.append(cached.get('chunk_index'))
            except:
                pass

        return {
            'completed_chunks': sorted(completed_chunks),
            'total_cached': len(cache_files),
            'cache_files': [str(cf) for cf in cache_files],
        }

    def clear_book_cache(self, book_title: str):
        """
        清除指定书籍的所有缓存

        Args:
            book_title: 书名
        """
        cache_files = list(self.cache_dir.glob(f"{book_title}_*.json"))
        for cf in cache_files:
            cf.unlink()
        logger.info(f"   🗑️ 清除缓存: {book_title} ({len(cache_files)} 个文件)")

    def clear_expired_cache(self):
        """
        清除所有过期缓存
        """
        cleared = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                cached_time = datetime.fromisoformat(cached.get('timestamp', '2000-01-01'))
                if datetime.now() - cached_time > timedelta(days=self.max_age_days):
                    cache_file.unlink()
                    cleared += 1
            except:
                # 无法读取的缓存文件直接删除
                cache_file.unlink()
                cleared += 1

        logger.info(f"   🗑️ 清理过期缓存: {cleared} 个文件")

    # ═══════════════════════════════════════════════════════════
    # Skill 专用接口（简单 key-value）
    # ═══════════════════════════════════════════════════════════

    def get(self, cache_key: str) -> Optional[Dict]:
        """
        简单 key-value 获取（用于 Skill 缓存）

        Args:
            cache_key: 缓存键

        Returns:
            Optional[Dict]: 缓存结果
        """
        cache_file = self.cache_dir / f"{cache_key}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)

            # 检查过期
            cached_time = datetime.fromisoformat(cached.get('timestamp', '2000-01-01'))
            if datetime.now() - cached_time > timedelta(days=self.max_age_days):
                cache_file.unlink()
                return None

            return cached.get('result')

        except Exception as e:
            logger.warning(f"   ⚠️ 缓存读取失败: {e}")
            return None

    def set(self, cache_key: str, result: Dict):
        """
        简单 key-value 设置（用于 Skill 缓存）

        Args:
            cache_key: 缓存键
            result: 结果
        """
        cache_file = self.cache_dir / f"{cache_key}.json"

        try:
            cached = {
                'timestamp': datetime.now().isoformat(),
                'result': result,
            }

            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cached, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"   ⚠️ 缓存保存失败: {e}")


# 全局缓存实例
_cache_instance: Optional[ParseCache] = None


def get_cache() -> ParseCache:
    """获取全局缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ParseCache()
    return _cache_instance