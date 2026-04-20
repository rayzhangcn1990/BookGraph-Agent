"""
EPUB Parser - EPUB 格式书籍解析器

使用 ebooklib 解析 EPUB 结构，提取章节内容和元数据。
"""

from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub

from .base_parser import BaseParser, ParseResult


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
        按照书脊顺序提取章节内容
        
        Returns:
            List[Dict]: 章节列表，每章包含{chapter_id, title, content}
        """
        chapters = []
        
        if not self.book:
            return chapters
        
        # 按照书脊顺序遍历文档
        chapter_id = 1
        for item in self.book.spine:
            if isinstance(item, tuple):
                item = item[0]
            
            # 获取实际的项目
            doc_item = self.book.get_item_with_id(item) if isinstance(item, str) else item
            
            if doc_item and doc_item.get_type() == ebooklib.ITEM_DOCUMENT:
                chapter_data = self._process_document(doc_item, chapter_id)
                if chapter_data:
                    chapters.append(chapter_data)
                    chapter_id += 1
        
        return chapters

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
        # 尝试从 h1 标签提取
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)
        
        # 尝试从 title 标签提取
        title = soup.find('title')
        if title and title.get_text(strip=True):
            return title.get_text(strip=True)
        
        # 尝试从文件名提取
        if hasattr(doc_item, 'file_name'):
            name = Path(doc_item.file_name).stem
            if name and name.lower() not in ['chapter', 'section', 'content']:
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
