"""
MOBI Parser - MOBI 格式书籍解析器

使用 mobi 库解析 MOBI 格式，转换为 HTML 后复用 EpubParser 的处理逻辑。
"""

from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup
import tempfile
import os

try:
    import mobi
except ImportError:
    mobi = None

from .base_parser import BaseParser, ParseResult
from .epub_parser import EpubParser


class MobiParser(BaseParser):
    """
    MOBI 书籍解析器
    
    功能：
    - 使用 mobi 库解析 MOBI 格式
    - 转换为中间 HTML 格式
    - 复用 EpubParser 的 HTML 处理逻辑
    - 处理 MOBI 特有的元数据格式
    """

    def __init__(self, file_path: str, config: Dict = None):
        super().__init__(file_path, config)
        self.temp_dir: Optional[str] = None
        self.extracted_html: Optional[str] = None

    def parse(self) -> ParseResult:
        """
        解析 MOBI 文件
        
        Returns:
            ParseResult: 包含章节列表和元数据的解析结果
        """
        if mobi is None:
            return ParseResult(
                success=False,
                error="mobi 库未安装：pip install mobi",
            )
        
        try:
            # 创建临时目录提取文件
            self.temp_dir = tempfile.mkdtemp(prefix="mobi_extract_")
            
            # 提取 MOBI 文件
            extract_path, container = mobi.extract(self.file_path)
            
            # 获取元数据
            metadata = self._extract_metadata(container)
            
            # 提取 HTML 内容
            html_content = self._extract_html_content(extract_path)
            
            if not html_content:
                return ParseResult(
                    success=False,
                    error="未能提取到 HTML 内容",
                    metadata=metadata,
                )
            
            # 使用 BeautifulSoup 处理 HTML
            chapters = self._process_html(html_content)
            
            # 合并内容
            full_content = "\n\n".join([ch["content"] for ch in chapters])
            
            # 清理文本
            full_content = self.clean_text(full_content)
            
            # 检测语言
            language = self.detect_language(full_content)
            
            # 检查内容质量
            is_image_based = self.is_image_heavy(full_content)
            
            # 清理临时文件
            self._cleanup()
            
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
            self._cleanup()
            return ParseResult(
                success=False,
                error=f"MOBI 解析失败：{str(e)}",
                metadata={"file_path": str(self.file_path)},
            )

    def _extract_metadata(self, container) -> Dict:
        """
        从 MOBI 容器提取元数据
        
        Args:
            container: mobi 容器对象
            
        Returns:
            Dict: 包含 title, author 等信息
        """
        metadata = {
            "title": "",
            "author": "",
            "publisher": "",
            "language": "",
            "date": "",
            "identifier": "",
        }
        
        try:
            # 尝试从 container 提取元数据
            if hasattr(container, 'metadata'):
                meta = container.metadata
                
                # 不同版本的 mobi 库元数据访问方式不同
                if isinstance(meta, dict):
                    metadata["title"] = meta.get("title", "")
                    metadata["author"] = meta.get("creator", meta.get("author", ""))
                    metadata["publisher"] = meta.get("publisher", "")
                    metadata["language"] = meta.get("language", "")
                elif hasattr(meta, '__dict__'):
                    metadata["title"] = getattr(meta, 'title', "")
                    metadata["author"] = getattr(meta, 'creator', getattr(meta, 'author', ""))
                    metadata["publisher"] = getattr(meta, 'publisher', "")
                    metadata["language"] = getattr(meta, 'language', "")
            
            # 如果元数据中没有标题，使用文件名
            if not metadata["title"]:
                path_metadata = self.extract_metadata_from_path()
                metadata["title"] = path_metadata.get("title", self.file_path.stem)
            
            if not metadata["author"]:
                path_metadata = self.extract_metadata_from_path()
                metadata["author"] = path_metadata.get("author", "Unknown")
                
        except Exception:
            # 元数据提取失败，使用文件名
            path_metadata = self.extract_metadata_from_path()
            metadata["title"] = path_metadata.get("title", self.file_path.stem)
            metadata["author"] = path_metadata.get("author", "Unknown")
        
        return metadata

    def _extract_html_content(self, extract_path: str) -> Optional[str]:
        """
        从提取的目录中获取 HTML 内容
        
        Args:
            extract_path: 提取目录路径
            
        Returns:
            Optional[str]: HTML 内容或 None
        """
        try:
            # 查找 HTML 文件
            html_files = []
            for root, dirs, files in os.walk(extract_path):
                for file in files:
                    if file.endswith(('.html', '.xhtml', '.htm')):
                        html_files.append(os.path.join(root, file))
            
            if not html_files:
                # 尝试查找其他文本文件
                for root, dirs, files in os.walk(extract_path):
                    for file in files:
                        if file.endswith(('.txt', '.text')):
                            with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                return f.read()
                return None
            
            # 合并所有 HTML 文件
            html_contents = []
            for html_file in sorted(html_files):
                try:
                    with open(html_file, 'r', encoding='utf-8') as f:
                        html_contents.append(f.read())
                except UnicodeDecodeError:
                    # 尝试其他编码
                    try:
                        with open(html_file, 'r', encoding='gbk') as f:
                            html_contents.append(f.read())
                    except Exception:
                        continue
            
            return "\n".join(html_contents)
            
        except Exception:
            return None

    def _process_html(self, html_content: str) -> List[Dict]:
        """
        处理 HTML 内容，提取章节
        
        复用 EpubParser 的 HTML 处理逻辑。
        
        Args:
            html_content: HTML 内容
            
        Returns:
            List[Dict]: 章节列表
        """
        soup = BeautifulSoup(html_content, 'lxml')
        chapters = []
        
        # 找到所有标题
        headings = soup.find_all(['h1', 'h2', 'h3'])
        
        if not headings:
            # 没有标题，将整个内容作为一章
            body = soup.find('body') or soup
            content = body.get_text(separator='\n', strip=True)
            
            if content:
                chapters.append({
                    "chapter_id": "1",
                    "title": "完整内容",
                    "content": content,
                })
            
            return chapters
        
        # 按标题分章节
        chapter_id = 1
        for i, heading in enumerate(headings):
            title = heading.get_text(strip=True)
            
            # 获取章节内容（从当前标题到下一个标题）
            content_elements = []
            current = heading.next_sibling
            
            while current and (i == len(headings) - 1 or current != headings[i + 1]):
                if hasattr(current, 'get_text'):
                    text = current.get_text(separator=' ', strip=True)
                    if text:
                        content_elements.append(text)
                elif isinstance(current, str) and current.strip():
                    content_elements.append(current.strip())
                
                current = current.next_sibling
            
            content = "\n".join(content_elements)
            
            if content:
                chapters.append({
                    "chapter_id": str(chapter_id),
                    "title": title or f"第{chapter_id}章",
                    "content": content,
                })
                chapter_id += 1
        
        return chapters

    def _cleanup(self):
        """清理临时文件"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                import shutil
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
            self.temp_dir = None
