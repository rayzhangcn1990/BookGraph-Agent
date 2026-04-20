"""
PDF Parser - PDF 格式书籍解析器

使用 PyMuPDF (fitz) 解析 PDF，支持文字版和扫描版（OCR）检测。
"""

from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None

from .base_parser import BaseParser, ParseResult


class PdfParser(BaseParser):
    """
    PDF 书籍解析器
    
    功能：
    - 使用 PyMuPDF (fitz) 解析 PDF
    - 自动检测图片型 PDF（扫描版）
    - 对图片型 PDF 标记，供 OCR 引擎处理
    - 基于字体大小和样式识别章节标题
    - 保持页面顺序与章节对应关系
    - 处理双栏布局的文字提取顺序
    """

    def __init__(self, file_path: str, config: Dict = None):
        super().__init__(file_path, config)
        self.config = config or {}
        self.image_pdf_threshold = self.config.get('image_pdf_threshold', 0.8)
        self.doc: Optional[fitz.Document] = None

    def parse(self) -> ParseResult:
        """
        解析 PDF 文件
        
        Returns:
            ParseResult: 包含章节列表和元数据的解析结果
        """
        if fitz is None:
            return ParseResult(
                success=False,
                error="PyMuPDF 未安装：pip install pymupdf",
            )
        
        try:
            # 打开 PDF 文档
            self.doc = fitz.open(self.file_path)
            
            # 检测是否为图片型 PDF
            is_image_based = self.is_image_pdf()
            
            # 提取元数据
            metadata = self._extract_metadata()
            
            if is_image_based:
                # 图片型 PDF，返回标记供 OCR 处理
                return ParseResult(
                    success=True,
                    content="",
                    chapters=[],
                    metadata=metadata,
                    is_image_based=True,
                    page_count=len(self.doc),
                    word_count=0,
                    error="图片型 PDF，需要 OCR 处理",
                )
            
            # 文字型 PDF，提取内容
            chapters = self._extract_chapters()
            full_content = "\n\n".join([ch["content"] for ch in chapters])
            
            # 如果内容为空，尝试使用 pymupdf4llm
            if not full_content.strip() and pymupdf4llm:
                try:
                    md_content = pymupdf4llm.to_markdown(str(self.file_path))
                    if md_content.strip():
                        full_content = md_content
                        chapters = [{
                            "chapter_id": "1",
                            "title": "完整内容",
                            "content": md_content,
                        }]
                except Exception:
                    pass
            
            # 清理文本
            full_content = self.clean_text(full_content)
            
            # 再次检查内容质量
            if self.is_image_heavy(full_content):
                return ParseResult(
                    success=True,
                    content=full_content,
                    chapters=chapters,
                    metadata=metadata,
                    is_image_based=True,
                    page_count=len(self.doc),
                    word_count=len(full_content),
                    error="内容质量低，可能是扫描版或加密 PDF",
                )
            
            return ParseResult(
                success=True,
                content=full_content,
                chapters=chapters,
                metadata=metadata,
                is_image_based=False,
                page_count=len(self.doc),
                word_count=len(full_content),
            )
            
        except Exception as e:
            return ParseResult(
                success=False,
                error=f"PDF 解析失败：{str(e)}",
                metadata={"file_path": str(self.file_path)},
            )
        finally:
            if self.doc:
                self.doc.close()

    def is_image_pdf(self) -> bool:
        """
        检测 PDF 是否为图片型（扫描版）
        
        抽样检测前 10 页的文字覆盖率，若覆盖率低于阈值则判定为图片型。
        
        Returns:
            bool: 是否为图片型 PDF
        """
        if not self.doc or len(self.doc) == 0:
            return True
        
        # 抽样检测前 10 页
        sample_pages = min(10, len(self.doc))
        total_text_ratio = 0
        total_image_count = 0
        
        for page_num in range(sample_pages):
            page = self.doc[page_num]
            
            # 获取页面文本
            text = page.get_text("text")
            text_len = len(text.strip())
            
            # 获取页面图片数量
            images = page.get_images(full=True)
            image_count = len(images)
            
            # 获取页面面积
            page_area = page.rect.width * page.rect.height
            
            # 估算文字覆盖面积（粗略估计）
            text_blocks = page.get_text("blocks")
            text_area = sum((b[3] - b[1]) * (b[2] - b[0]) for b in text_blocks if b[-1] == 0)
            
            # 计算文字覆盖率
            if page_area > 0:
                text_ratio = text_area / page_area
                total_text_ratio += text_ratio
            
            total_image_count += image_count
        
        # 平均文字覆盖率
        avg_text_ratio = total_text_ratio / sample_pages if sample_pages > 0 else 0
        
        # 平均每页图片数
        avg_images = total_image_count / sample_pages if sample_pages > 0 else 0
        
        # 判定逻辑：
        # 1. 文字覆盖率低于阈值
        # 2. 或者每页图片数很多（>5）且文字很少
        if avg_text_ratio < self.image_pdf_threshold:
            return True
        
        if avg_images > 5 and avg_text_ratio < 0.5:
            return True
        
        return False

    def _extract_metadata(self) -> Dict:
        """
        提取 PDF 元数据
        
        Returns:
            Dict: 包含 title, author, subject 等信息
        """
        metadata = {
            "title": "",
            "author": "",
            "subject": "",
            "publisher": "",
            "creation_date": "",
            "modification_date": "",
        }
        
        if not self.doc:
            return metadata
        
        # 从 PDF 元数据提取
        pdf_meta = self.doc.metadata
        
        metadata["title"] = pdf_meta.get("title", "")
        metadata["author"] = pdf_meta.get("author", "")
        metadata["subject"] = pdf_meta.get("subject", "")
        metadata["publisher"] = pdf_meta.get("producer", "")
        metadata["creation_date"] = pdf_meta.get("creationDate", "")
        metadata["modification_date"] = pdf_meta.get("modDate", "")
        
        # 如果元数据中没有标题，使用文件名
        if not metadata["title"]:
            path_metadata = self.extract_metadata_from_path()
            metadata["title"] = path_metadata.get("title", self.file_path.stem)
        
        if not metadata["author"]:
            path_metadata = self.extract_metadata_from_path()
            metadata["author"] = path_metadata.get("author", "Unknown")
        
        return metadata

    def _extract_chapters(self) -> List[Dict]:
        """
        提取章节内容
        
        基于字体大小和样式识别章节标题，保持页面顺序。
        
        Returns:
            List[Dict]: 章节列表
        """
        if not self.doc:
            return []
        
        chapters = []
        current_chapter = None
        current_content = []
        
        # 字体大小阈值，用于识别标题
        title_font_threshold = 14  # 大于此值可能是标题
        subtitle_font_threshold = 12  # 大于此值可能是副标题
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            
            # 获取详细的文本块信息（包含字体信息）
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            
            for block in blocks:
                if block.get("type") != 0:  # 跳过非文本块
                    continue
                
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        font_size = span.get("size", 10)
                        font_flags = span.get("flags", 0)
                        is_bold = bool(font_flags & 2**4)  # 粗体标志
                        
                        if not text:
                            continue
                        
                        # 检测是否为章节标题
                        is_chapter_title = self._is_chapter_title(text, font_size, is_bold)
                        
                        if is_chapter_title:
                            # 保存前一章
                            if current_chapter:
                                chapters.append({
                                    "chapter_id": current_chapter["id"],
                                    "title": current_chapter["title"],
                                    "content": "\n".join(current_content),
                                })
                            
                            # 开始新章节
                            current_chapter = {
                                "id": str(len(chapters) + 1),
                                "title": self._clean_chapter_title(text),
                            }
                            current_content = []
                        elif current_chapter:
                            current_content.append(text)
        
        # 保存最后一章
        if current_chapter:
            chapters.append({
                "chapter_id": current_chapter["id"],
                "title": current_chapter["title"],
                "content": "\n".join(current_content),
            })
        
        # 如果没有检测到章节，将整个文档作为一章
        if not chapters:
            full_text = []
            for page_num in range(len(self.doc)):
                page = self.doc[page_num]
                text = page.get_text("text")
                full_text.append(f"\n--- 第{page_num + 1}页 ---\n")
                full_text.append(text)
            
            chapters.append({
                "chapter_id": "1",
                "title": "完整内容",
                "content": "\n".join(full_text),
            })
        
        return chapters

    def _is_chapter_title(self, text: str, font_size: float, is_bold: bool) -> bool:
        """
        判断文本是否为章节标题
        
        Args:
            text: 文本内容
            font_size: 字体大小
            is_bold: 是否粗体
            
        Returns:
            bool: 是否为章节标题
        """
        # 检查是否包含章节标记
        chapter_patterns = [
            r'^第 [一二三四五六七八九十\d]+[章节]',
            r'^Chapter\s+\d+',
            r'^CHAPTER\s+\d+',
            r'^Part\s+[IVX\d]+',
            r'^PART\s+[IVX\d]+',
            r'^\d+\.\s+',  # 数字编号
            r'^Section\s+\d+',
        ]
        
        for pattern in chapter_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True
        
        # 检查字体特征
        if font_size >= 16 and is_bold:
            return True
        
        if font_size >= 14 and is_bold and len(text) < 50:
            return True
        
        return False

    def _clean_chapter_title(self, text: str) -> str:
        """
        清理章节标题
        
        Args:
            text: 原始标题
            
        Returns:
            str: 清理后的标题
        """
        # 移除页眉页脚
        text = re.sub(r'\s*·\s*第\d+页\s*', '', text)
        text = re.sub(r'\s*\d+\s*$', '', text)  # 移除末尾页码
        
        return text.strip()

    def render_page_to_image(self, page_num: int, dpi: int = 300) -> bytes:
        """
        将 PDF 页面渲染为图片
        
        Args:
            page_num: 页码（从 0 开始）
            dpi: 分辨率
            
        Returns:
            bytes: PNG 图片数据
        """
        if not self.doc or page_num >= len(self.doc):
            return b""
        
        page = self.doc[page_num]
        
        # 计算缩放比例
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # 渲染为图片
        pix = page.get_pixmap(matrix=mat)
        
        return pix.tobytes("png")
