"""
Base Parser - 解析器抽象基类

定义所有书籍解析器的统一接口和通用方法。
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
import re


@dataclass
class ParseResult:
    """解析结果数据结构"""
    success: bool
    content: str = ""
    chapters: List[Dict] = None
    metadata: Dict = None
    error: Optional[str] = None
    is_image_based: bool = False  # 是否为图片型 PDF
    page_count: int = 0
    word_count: int = 0

    def __post_init__(self):
        if self.chapters is None:
            self.chapters = []
        if self.metadata is None:
            self.metadata = {}


class BaseParser(ABC):
    """
    书籍解析器抽象基类
    
    所有具体解析器（EPUB/PDF/MOBI）必须继承此类并实现 parse() 方法。
    """

    def __init__(self, file_path: str, config: Dict = None):
        """
        初始化解析器
        
        Args:
            file_path: 书籍文件路径
            config: 配置字典
        """
        self.file_path = Path(file_path)
        self.config = config or {}
        self.min_text_length = config.get('min_text_length', 100) if config else 100

    @abstractmethod
    def parse(self) -> ParseResult:
        """
        解析书籍文件
        
        Returns:
            ParseResult: 包含章节列表、元数据和错误信息的解析结果
            
        章节列表格式：
        [
            {
                "chapter_id": "1",
                "title": "第一章 标题",
                "content": "章节内容..."
            },
            ...
        ]
        """
        pass

    def detect_language(self, text: str) -> str:
        """
        检测文本语言
        
        Args:
            text: 待检测的文本
            
        Returns:
            str: 语言代码（zh/en/ja 等）
        """
        if not text or len(text.strip()) < 10:
            return "unknown"
        
        try:
            # 检测中文字符比例
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            if chinese_chars / len(text) > 0.3:
                return "zh"
            
            # 简单判断：如果有很多假名可能是日语
            japanese_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
            if japanese_chars / len(text) > 0.2:
                return "ja"
            
            # 默认返回英文
            return "en"
        except Exception:
            return "unknown"

    def clean_text(self, text: str) -> str:
        """
        清理乱码与无效字符
        
        Args:
            text: 原始文本
            
        Returns:
            str: 清理后的文本
        """
        if not text:
            return ""
        
        # 移除空字符
        text = text.replace('\x00', '')
        
        # 移除控制字符（保留换行和制表符）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        
        # 标准化换行符
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # 移除连续的空行（保留最多 2 个）
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 移除页眉页脚模式（常见于 PDF）
        # 例如："xxx 书 · 第 x 页" 或 "xxx 书 ·第x页"
        text = re.sub(r'.*·\s*第\s*\d+\s*页.*\n', '', text)
        text = re.sub(r'.*chapter\s+\d+.*\n', '', text, flags=re.IGNORECASE)
        
        # 移除 ISBN、版权信息等
        text = re.sub(r'ISBN[-\s]?\d[\d\sX-]{9,}', '', text)
        text = re.sub(r'Copyright © \d{4}.*', '', text, flags=re.IGNORECASE)
        
        # 移除 URL（保留必要的）
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
        
        return text.strip()

    def chunk_content(
        self, 
        content: str, 
        chunk_size: int = 50000, 
        overlap_size: int = 2000
    ) -> List[Dict]:
        """
        按照配置分块，保持章节完整性
        
        Args:
            content: 完整内容
            chunk_size: 每块最大字符数
            overlap_size: 块间重叠字符数
            
        Returns:
            List[Dict]: 分块列表，每块包含{chunk_index, content, start_chapter, end_chapter}
        """
        if not content:
            return []
        
        if len(content) <= chunk_size:
            return [{"chunk_index": 0, "content": content, "total_chunks": 1}]
        
        chunks = []
        current_pos = 0
        chunk_index = 0
        
        while current_pos < len(content):
            # 计算当前块的结束位置
            end_pos = min(current_pos + chunk_size, len(content))
            
            # 如果不是最后一块，尝试在章节边界处切断
            if end_pos < len(content):
                # 在重叠区域内寻找最近的章节标记
                search_start = max(current_pos, end_pos - overlap_size * 2)
                search_end = min(end_pos + overlap_size, len(content))
                search_region = content[search_start:search_end]
                
                # 寻找章节标记（### 或 第 X 章）
                chapter_patterns = [
                    r'\n#{1,3}\s+',
                    r'\n第 [一二三四五六七八九十\d]+[章节]',
                    r'\nChapter\s+\d+',
                    r'\nPART\s+[IVX\d]+',
                ]
                
                best_cut = None
                for pattern in chapter_patterns:
                    matches = list(re.finditer(pattern, search_region, re.IGNORECASE))
                    if matches:
                        # 选择最接近 end_pos 的章节标记
                        for match in reversed(matches):
                            cut_pos = search_start + match.start()
                            if cut_pos > current_pos + chunk_size // 2:
                                best_cut = cut_pos
                                break
                
                if best_cut:
                    end_pos = best_cut
            
            # 提取当前块
            chunk_content = content[current_pos:end_pos]
            
            # 如果不是第一块，添加重叠部分
            if chunk_index > 0 and overlap_size > 0:
                overlap_start = max(0, current_pos - overlap_size)
                overlap = content[overlap_start:current_pos]
                chunk_content = overlap + chunk_content
            
            chunks.append({
                "chunk_index": chunk_index,
                "content": chunk_content,
            })
            
            current_pos = end_pos
            chunk_index += 1
        
        # 更新总块数
        total = len(chunks)
        for chunk in chunks:
            chunk["total_chunks"] = total
        
        return chunks

    def is_image_heavy(self, content: str) -> bool:
        """
        判断内容是否主要是图片（文字覆盖率低）
        
        Args:
            content: 提取的文本内容
            
        Returns:
            bool: 是否为图片型内容
        """
        if not content:
            return True
        
        # 检查文字密度
        total_chars = len(content)
        if total_chars < self.min_text_length:
            return True
        
        # 检查重复内容（水印/页脚）
        lines = content.strip().split('\n')
        if len(lines) < 10:
            return True
        
        line_counts = {}
        for line in lines:
            if line.strip():
                line_counts[line] = line_counts.get(line, 0) + 1
        
        # 如果有行重复超过 50%，可能是水印
        repeated_lines = sum(1 for count in line_counts.values() if count > len(lines) * 0.1)
        if repeated_lines > len(line_counts) * 0.3:
            return True
        
        return False

    def extract_metadata_from_path(self) -> Dict:
        """
        从文件路径提取基本元数据
        
        Returns:
            Dict: 包含 title, author 等信息的字典
        """
        filename = self.file_path.stem
        
        # 尝试从文件名提取信息
        # 格式可能是："书名 - 作者.pdf" 或 "作者 - 书名.pdf"
        parts = re.split(r'[-_]', filename)
        
        metadata = {
            "title": filename,
            "author": "Unknown",
            "file_name": self.file_path.name,
            "file_path": str(self.file_path),
        }
        
        if len(parts) >= 2:
            # 假设第一个部分是书名
            metadata["title"] = parts[0].strip()
            metadata["author"] = parts[1].strip() if len(parts) > 1 else "Unknown"
        
        return metadata
