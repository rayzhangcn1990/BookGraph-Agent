"""
EPUB Parser - EPUB 格式书籍解析器

使用 ebooklib 解析 EPUB 结构，提取章节内容和元数据。
"""

import logging
from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub

from .base_parser import BaseParser, ParseResult

logger = logging.getLogger("BookGraph-Agent")


class EpubParser(BaseParser):
    """
    EPUB 书籍解析器
    
    功能：
    - 使用 ebooklib 解析 EPUB 结构
    - 提取书脊顺序（spine order）确保章节顺序正确
    - 使用 BeautifulSoup 清理 HTML 标签
    - 保留标题层级结构（h1/h2/h3）
    - 处理图片章节（跳过或标记）
    - 提取书籍元数据（title, author, publisher, date）
    """

    def __init__(self, file_path: str, config: Dict = None):
        super().__init__(file_path, config)
        self.book: Optional[ebooklib.EpubBook] = None

    def parse(self) -> ParseResult:
        """
        解析 EPUB 文件
        
        Returns:
            ParseResult: 包含章节列表和元数据的解析结果
        """
        try:
            # 读取 EPUB 文件
            self.book = epub.read_epub(self.file_path)
            
            # 提取元数据
            metadata = self._extract_metadata()
            
            # 提取章节内容（按照书脊顺序）
            chapters = self._extract_chapters()
            
            # 合并所有内容
            full_content = "\n\n".join([ch["content"] for ch in chapters])
            
            # 清理文本
            full_content = self.clean_text(full_content)
            
            # 检测语言
            language = self.detect_language(full_content)
            
            # 检查是否为图片型 EPUB
            is_image_based = self.is_image_heavy(full_content)
            
            return ParseResult(
                success=True,
                content=full_content,
                chapters=chapters,
                metadata=metadata,
                is_image_based=is_image_based,
                page_count=len(chapters),
                word_count=len(full_content),
            )
            
        except Exception as e:
            return ParseResult(
                success=False,
                error=f"EPUB 解析失败：{str(e)}",
                metadata={"file_path": str(self.file_path)},
            )

    def _extract_metadata(self) -> Dict:
        """
        提取 EPUB 元数据
        
        Returns:
            Dict: 包含 title, author, publisher, language 等信息
        """
        metadata = {
            "title": "",
            "author": "",
            "publisher": "",
            "language": "",
            "date": "",
            "identifier": "",
            "description": "",
            "subjects": [],
        }
        
        if not self.book:
            return metadata
        
        # 提取基础元数据
        title_meta = self.book.get_metadata("DC", "title")
        creator_meta = self.book.get_metadata("DC", "creator")
        
        # 处理元数据（可能是 tuple 列表）
        if title_meta and isinstance(title_meta, list) and len(title_meta) > 0:
            if isinstance(title_meta[0], tuple):
                metadata["title"] = str(title_meta[0][0])
            else:
                metadata["title"] = str(title_meta[0])
        
        if creator_meta and isinstance(creator_meta, list) and len(creator_meta) > 0:
            if isinstance(creator_meta[0], tuple):
                metadata["author"] = str(creator_meta[0][0])
            else:
                metadata["author"] = str(creator_meta[0])
        
        metadata["publisher"] = str(self.book.get_metadata("DC", "publisher") or "")
        metadata["language"] = str(self.book.get_metadata("DC", "language") or "")
        metadata["date"] = str(self.book.get_metadata("DC", "date") or "")
        metadata["identifier"] = str(self.book.get_metadata("DC", "identifier") or "")
        metadata["description"] = str(self.book.get_metadata("DC", "description") or "")
        
        # 提取主题/分类
        subjects = self.book.get_metadata("DC", "subject")
        if subjects:
            metadata["subjects"] = [str(s[0]) if isinstance(s, tuple) else str(s) for s in subjects if s]
        
        # 如果元数据中没有作者，尝试从文件名提取
        if not metadata["author"]:
            path_metadata = self.extract_metadata_from_path()
            metadata["author"] = path_metadata.get("author", "Unknown")
        
        if not metadata["title"]:
            path_metadata = self.extract_metadata_from_path()
            metadata["title"] = path_metadata.get("title", self.file_path.stem)
        
        return metadata

    def _extract_chapters(self) -> List[Dict]:
        """
        提取章节内容（按照书脊顺序）

        P2优化：增强 OPF Spine 解析，确保章节顺序正确

        Returns:
            List[Dict]: 章节列表（包含 title, content, chapter_number）
        """
        chapters = []

        if not self.book:
            return chapters

        # 🗝️ P2优化：优先使用 OPF Spine 顺序
        # 参考 ai-book-summarizer 项目的 Spine 解析模式
        spine_order = self._get_spine_order()

        if spine_order:
            # 按照 Spine 顺序提取章节
            for index, item_id in enumerate(spine_order):
                item = self.book.get_item_with_id(item_id)
                if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                    chapter = self._parse_chapter_item(item, index + 1)
                    if chapter:
                        chapters.append(chapter)
        else:
            # 回退：使用原有逻辑（遍历所有 item）
            logger.warning("未找到 Spine 顺序，使用默认遍历逻辑")
            chapter_number = 0
            for item in self.book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    chapter_number += 1
                    chapter = self._parse_chapter_item(item, chapter_number)
                    if chapter:
                        chapters.append(chapter)

        return chapters

    def _get_spine_order(self) -> List[str]:
        """
        获取 OPF Spine 顺序（确保章节顺序正确）

        Returns:
            List[str]: Spine item ID 列表（按顺序）
        """
        try:
            # 尝试从 EPUB Spine 获取顺序
            spine = self.book.spine
            if spine:
                # spine 格式: [(idref, linear), ...]
                return [item[0] if isinstance(item, tuple) else item for item in spine]
        except Exception as e:
            logger.warning(f"获取 Spine 顺序失败: {e}")

        return []

    def _parse_chapter_item(self, item, chapter_number: int) -> Optional[Dict]:
        """
        解析单个章节 item

        Args:
            item: EPUB item
            chapter_number: 章节编号

        Returns:
            Optional[Dict]: 章节数据（如果有效）
        """
        try:
            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')

            # 提取标题
            title = self._extract_chapter_title(soup)

            # 提取文本内容
            text_content = self._extract_text_content(soup)

            # 跳过空章节或过短章节
            if len(text_content) < 100:
                return None

            return {
                "title": title,
                "content": text_content,
                "chapter_number": chapter_number
            }
        except Exception as e:
            logger.warning(f"解析章节 {chapter_number} 失败: {e}")
            return None

    def _extract_chapter_title(self, soup: BeautifulSoup) -> str:
        """提取章节标题"""
        # 尝试从 h1/h2/h3 标签提取
        for tag in ['h1', 'h2', 'h3']:
            heading = soup.find(tag)
            if heading:
                text = heading.get_text(strip=True)
                if text and len(text) > 2:
                    return text
        return ""

    def _extract_text_content(self, soup: BeautifulSoup) -> str:
        """提取文本内容"""
        # 移除 script 和 style 标签
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()

        # 提取文本
        text = soup.get_text(separator='\n', strip=True)
        return text

    def _process_document(self, doc_item, chapter_id: int) -> Optional[Dict]:
        """
        处理单个文档项
        
        Args:
            doc_item: EPUB 文档项
            chapter_id: 章节编号
            
        Returns:
            Optional[Dict]: 章节数据或 None
        """
        try:
            content = doc_item.get_content().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(content, 'lxml')
            
            # 提取标题
            title = self._extract_title(soup, doc_item)
            
            # 提取正文内容，保留标题层级
            body_content = self._extract_body_content(soup)
            
            if not body_content.strip():
                return None
            
            return {
                "chapter_id": str(chapter_id),
                "title": title or f"第{chapter_id}章",
                "content": body_content,
            }
            
        except Exception as e:
            return None

    def _extract_title(self, soup: BeautifulSoup, doc_item) -> str:
        """
        从文档中提取标题

        Args:
            soup: BeautifulSoup 对象
            doc_item: EPUB 文档项

        Returns:
            str: 标题文本
        """
        # 尝试从 h1/h2/h3 标签提取（优先 h1）
        for tag in ['h1', 'h2', 'h3']:
            heading = soup.find(tag)
            if heading:
                text = heading.get_text(strip=True)
                # 检查是否是有效标题（包含中文或有效内容）
                if text and len(text) > 2 and len(text) <= 50:
                    # 必须包含中文字符或有意义的英文单词
                    has_chinese = any('一' <= c <= '鿿' for c in text)
                    has_valid_word = any(word.len() >= 3 for word in text.split()) if not has_chinese else True
                    if has_chinese or has_valid_word:
                        # 排除常见的占位符
                        placeholders = ['chapter', 'section', 'content', 'index', 'toc', 'nav', 'part', 'text', 'split', 'ch']
                        if not any(text.lower().startswith(p) for p in placeholders):
                            return text

        # 尝试从第一个包含"章"、"节"、"第"的段落提取
        body = soup.find('body') or soup
        for element in body.find_all(['p', 'div', 'span']):
            text = element.get_text(strip=True)
            # 匹配章节标题格式：如 "第一章 xxx", "第1章 xxx", "第1节 xxx"
            if text and ('章' in text[:10] or '节' in text[:10] or (text.startswith('第') and len(text) > 3)):
                # 必须以"第"开头或包含明确的章节标记
                if text.startswith('第') or '第' in text[:5]:
                    # 截取合理的标题长度（通常不超过30字）
                    if len(text) <= 30:
                        return text
                    # 如果太长，可能包含正文，截取前20字
                    return text[:20].strip()

        # 尝试从 title 标签提取
        title_tag = soup.find('title')
        if title_tag:
            text = title_tag.get_text(strip=True)
            # 排除占位符
            placeholders = ['untitled', 'no title', '', 'part', 'text', 'split', 'ch', 'index', 'nav']
            if text and not any(text.lower().startswith(p) for p in placeholders):
                if len(text) <= 30 and (any('一' <= c <= '鿿' for c in text) or text[0].isalpha()):
                    return text

        # 尝试从文件名提取（但排除占位符）
        if hasattr(doc_item, 'file_name'):
            name = Path(doc_item.file_name).stem
            # 排除常见的占位符文件名（增强版）
            placeholder_patterns = [
                'chapter', 'ch', 'index', 'split', 'section', 'content',
                'page', 'nav', 'toc', 'part', 'text', '000', '001',
                'nav', 'ncx', 'opf', 'cover', 'titlepage'
            ]
            # 如果文件名全是数字或数字+字母组合，跳过
            if name and not any(name.lower().startswith(p) for p in placeholder_patterns):
                # 检查是否是 part0000、text00001 这种格式
                import re
                if re.match(r'^(part|text|ch|split)\d+$', name.lower()):
                    return ""
                # 检查是否包含有效内容
                if any('一' <= c <= '鿿' for c in name) or (name[0].isalpha() and len(name) > 3 and not name.isdigit()):
                    return name

        return ""

    def _extract_body_content(self, soup: BeautifulSoup) -> str:
        """
        提取正文内容，保留标题层级结构
        
        Args:
            soup: BeautifulSoup 对象
            
        Returns:
            str: 清理后的正文内容
        """
        # 找到 body 标签
        body = soup.find('body')
        if not body:
            body = soup
        
        lines = []
        
        # 遍历所有元素，保留标题层级
        for element in body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'span']):
            text = element.get_text(separator=' ', strip=True)
            
            if not text:
                continue
            
            # 根据标签类型添加标记
            tag_name = element.name.lower()
            if tag_name.startswith('h'):
                level = int(tag_name[1])
                prefix = "#" * level
                lines.append(f"\n{prefix} {text}\n")
            elif tag_name == 'p':
                lines.append(text)
        
        # 如果没有找到结构化内容，尝试提取所有文本
        if not lines:
            text = body.get_text(separator='\n', strip=True)
            if text:
                return text
        
        return "\n".join(lines)

    def _is_image_chapter(self, doc_item) -> bool:
        """
        判断章节是否主要是图片
        
        Args:
            doc_item: EPUB 文档项
            
        Returns:
            bool: 是否为图片章节
        """
        # 检查文档中的图片数量
        images = doc_item.media or []
        if len(images) > 5:
            # 检查文字内容
            content = doc_item.get_content().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(content, 'lxml')
            text = soup.get_text(strip=True)
            
            # 如果文字很少，可能是图片章节
            if len(text) < 100:
                return True
        
        return False
