#!/usr/bin/env python3
"""
Wikipedia 信息补充模块

通过 Wikipedia-API 自动获取：
- 作者简介
- 历史事件背景
- 核心概念补充

减少 LLM 调用次数，降低 token 消耗。
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass, field

import wikipediaapi

logger = logging.getLogger(__name__)


@dataclass
class WikipediaInfo:
    """Wikipedia 补充信息"""
    author_intro: Optional[str] = None
    historical_events: Dict[str, str] = field(default_factory=dict)  # 事件名 -> 描述
    concepts: Dict[str, str] = field(default_factory=dict)  # 概念名 -> 定义
    related_books: List[str] = field(default_factory=list)


class WikipediaEnricher:
    """Wikipedia 信息补充器"""

    def __init__(self, user_agent: str = "BookGraph-Agent/1.0", language: str = "zh"):
        self.wiki = wikipediaapi.Wikipedia(
            user_agent=user_agent,
            language=language
        )
        self.en_wiki = wikipediaapi.Wikipedia(
            user_agent=user_agent,
            language='en'
        )
        self._cache: Dict[str, WikipediaInfo] = {}

    def search_author(self, author_name: str) -> Optional[str]:
        """
        搜索作者信息

        Args:
            author_name: 作者名称

        Returns:
            作者简介（约 500-1000 字）
        """
        cache_key = f"author:{author_name}"
        if cache_key in self._cache and self._cache[cache_key].author_intro:
            return self._cache[cache_key].author_intro

        # 尝试中文页面
        page = self.wiki.page(author_name)
        if not page.exists():
            # 尝试英文页面
            page = self.en_wiki.page(author_name)

        if not page.exists():
            logger.warning(f"Wikipedia 未找到作者: {author_name}")
            return None

        # 提取摘要（前 800 字）
        summary = page.summary[:800] if len(page.summary) > 800 else page.summary

        logger.info(f"✅ Wikipedia 获取作者信息: {author_name} ({len(summary)}字符)")

        # 缓存
        if cache_key not in self._cache:
            self._cache[cache_key] = WikipediaInfo()
        self._cache[cache_key].author_intro = summary

        return summary

    def search_event(self, event_name: str) -> Optional[str]:
        """
        搜索历史事件

        Args:
            event_name: 事件名称

        Returns:
            事件描述
        """
        cache_key = f"event:{event_name}"
        if cache_key in self._cache and event_name in self._cache.get(cache_key, WikipediaInfo()).historical_events:
            return self._cache[cache_key].historical_events[event_name]

        # 尝试中文页面
        page = self.wiki.page(event_name)
        if not page.exists():
            # 尝试英文页面
            page = self.en_wiki.page(event_name)

        if not page.exists():
            logger.warning(f"Wikipedia 未找到事件: {event_name}")
            return None

        # 提取摘要（前 500 字）
        summary = page.summary[:500] if len(page.summary) > 500 else page.summary

        logger.info(f"✅ Wikipedia 获取事件信息: {event_name} ({len(summary)}字符)")

        # 缓存
        if cache_key not in self._cache:
            self._cache[cache_key] = WikipediaInfo()
        self._cache[cache_key].historical_events[event_name] = summary

        return summary

    def search_concept(self, concept_name: str) -> Optional[str]:
        """
        搜索概念定义

        Args:
            concept_name: 概念名称

        Returns:
            概念定义
        """
        cache_key = f"concept:{concept_name}"

        # 尝试中文页面
        page = self.wiki.page(concept_name)
        if not page.exists():
            # 尝试英文页面
            page = self.en_wiki.page(concept_name)

        if not page.exists():
            logger.warning(f"Wikipedia 未找到概念: {concept_name}")
            return None

        # 提取首段（前 300 字）
        definition = page.summary[:300] if len(page.summary) > 300 else page.summary

        logger.info(f"✅ Wikipedia 获取概念: {concept_name} ({len(definition)}字符)")

        return definition

    def enrich_book_metadata(
        self,
        book_title: str,
        author: str,
        concepts: List[str] = None,
        events: List[str] = None
    ) -> WikipediaInfo:
        """
        补充书籍元数据

        Args:
            book_title: 书名
            author: 作者
            concepts: 核心概念列表
            events: 关键事件列表

        Returns:
            补充信息
        """
        info = WikipediaInfo()

        # 1. 获取作者信息
        if author:
            info.author_intro = self.search_author(author)

        # 2. 获取概念定义
        if concepts:
            for concept in concepts[:5]:  # 最多 5 个概念
                definition = self.search_concept(concept)
                if definition:
                    info.concepts[concept] = definition

        # 3. 获取事件背景
        if events:
            for event in events[:5]:  # 最多 5 个事件
                description = self.search_event(event)
                if description:
                    info.historical_events[event] = description

        logger.info(f"📊 Wikipedia 补充完成: 作者={bool(info.author_intro)}, "
                   f"概念={len(info.concepts)}, 事件={len(info.historical_events)}")

        return info

    def get_token_savings(self) -> int:
        """
        估算节省的 token 数

        Returns:
            估算节省的 token 数（每 4 字符约 1 token）
        """
        total_chars = 0

        for cache_key, info in self._cache.items():
            if info.author_intro:
                total_chars += len(info.author_intro)
            for event_desc in info.historical_events.values():
                total_chars += len(event_desc)
            for concept_def in info.concepts.values():
                total_chars += len(concept_def)

        # 中文字符约 1.5 tokens/字，英文约 4 字符/token
        # 综合估算：每字符约 0.5 token
        tokens_saved = int(total_chars * 0.5)

        logger.info(f"💰 估算节省 token: {tokens_saved} (基于 {total_chars} 字符)")

        return tokens_saved


# 便捷函数
def enrich_author(author_name: str) -> Optional[str]:
    """便捷函数：获取作者简介"""
    enricher = WikipediaEnricher()
    return enricher.search_author(author_name)


def enrich_event(event_name: str) -> Optional[str]:
    """便捷函数：获取事件描述"""
    enricher = WikipediaEnricher()
    return enricher.search_event(event_name)


def enrich_concept(concept_name: str) -> Optional[str]:
    """便捷函数：获取概念定义"""
    enricher = WikipediaEnricher()
    return enricher.search_concept(concept_name)