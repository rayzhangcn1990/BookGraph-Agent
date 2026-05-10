"""
Extraction Schema - LLM提取结果源文本对齐追踪

核心设计（借鉴 langextract）：
- 每条提取结果精确追溯到原文位置
- 支持模糊对齐（LLM输出可能和原文略有差异）
- AlignmentStatus 标记对齐质量

这是底层基础设施，所有 Skill 的提取结果都应该使用此结构。
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass


class AlignmentStatus(str, Enum):
    """对齐状态枚举"""
    MATCH_EXACT = "match_exact"      # 完全匹配（原文精确出现）
    MATCH_FUZZY = "match_fuzzy"      # 模糊匹配（相似度 >= 75%）
    MATCH_LESSER = "match_lesser"    # 匹配但内容更少
    MATCH_GREATER = "match_greater"  # 匹配但内容更多
    UNGROUNDED = "ungrounded"        # 无法在原文中定位（可能是LLM幻觉)


class CharInterval(BaseModel):
    """字符位置区间"""
    start_pos: int = Field(..., description="起始位置（包含）")
    end_pos: int = Field(..., description="结束位置（不包含）")

    def overlaps(self, other: "CharInterval") -> bool:
        """检查两个区间是否重叠"""
        return self.start_pos < other.end_pos and other.start_pos < self.end_pos

    def contains(self, pos: int) -> bool:
        """检查位置是否在区间内"""
        return self.start_pos <= pos < self.end_pos


class TokenInterval(BaseModel):
    """Token位置区间（用于分词后的精确定位）"""
    start_index: int = Field(..., description="起始Token索引（包含）")
    end_index: int = Field(..., description="结束Token索引（不包含）")


class Extraction(BaseModel):
    """
    单条提取结果 - 带源文本对齐

    核心价值：每条提取都能追溯到原文哪一行哪一字
    """
    # 提取内容
    extraction_class: str = Field(..., description="提取类型（concept/insight/case/quote/chapter等）")
    extraction_text: str = Field(..., description="提取的文本内容")

    # 位置信息（核心）
    char_interval: Optional[CharInterval] = Field(None, description="字符位置区间")
    token_interval: Optional[TokenInterval] = Field(None, description="Token位置区间")

    # 对齐质量
    alignment_status: AlignmentStatus = Field(
        default=AlignmentStatus.UNGROUNDED,
        description="对齐状态"
    )

    # 元数据
    extraction_index: Optional[int] = Field(None, description="提取顺序索引")
    chunk_id: Optional[str] = Field(None, description="来源chunk标识")
    attributes: Optional[Dict[str, Any]] = Field(None, description="额外属性")

    # 原文片段（用于验证）
    source_snippet: Optional[str] = Field(None, description="原文片段（用于对比验证）")

    def is_grounded(self) -> bool:
        """是否成功定位到原文"""
        return self.alignment_status != AlignmentStatus.UNGROUNDED and self.char_interval is not None

    def to_markdown_ref(self) -> str:
        """
        生成 Markdown 引用格式

        Returns:
            str: 格式如 "[概念名](#L123-145)" 可点击跳转到原文
        """
        if self.char_interval:
            return f"[{self.extraction_text}](#L{self.char_interval.start_pos}-{self.char_interval.end_pos})"
        return self.extraction_text


class ExtractionResult(BaseModel):
    """
    Skill 执行结果 - 包含多条 Extraction

    每个 Skill 返回这个统一结构
    """
    skill_name: str = Field(..., description="Skill名称")
    extractions: List[Extraction] = Field(default_factory=list, description="提取结果列表")
    success: bool = Field(default=True, description="是否成功")
    errors: List[str] = Field(default_factory=list, description="错误列表")

    # 统计
    total_count: int = Field(default=0, description="总提取数")
    grounded_count: int = Field(default=0, description="成功定位数")
    fuzzy_count: int = Field(default=0, description="模糊匹配数")
    ungrounded_count: int = Field(default=0, description="未定位数（可能是幻觉）")

    def compute_stats(self):
        """计算统计信息"""
        self.total_count = len(self.extractions)
        self.grounded_count = sum(1 for e in self.extractions if e.alignment_status == AlignmentStatus.MATCH_EXACT)
        self.fuzzy_count = sum(1 for e in self.extractions if e.alignment_status == AlignmentStatus.MATCH_FUZZY)
        self.ungrounded_count = sum(1 for e in self.extractions if e.alignment_status == AlignmentStatus.UNGROUNDED)

    def get_grounded_only(self) -> List[Extraction]:
        """只返回成功定位的提取（过滤幻觉）"""
        return [e for e in self.extractions if e.is_grounded()]


class ChunkInfo(BaseModel):
    """
    Chunk 信息 - 包含原文位置

    改造 book_parser 输出此结构
    """
    chunk_id: str = Field(..., description="Chunk唯一标识")
    chunk_index: int = Field(..., description="Chunk序号")
    content: str = Field(..., description="Chunk内容")
    label: str = Field(default="", description="Chunk标签")

    # 🆕 位置信息
    char_interval: CharInterval = Field(..., description="在原文中的字符位置")
    source_text: Optional[str] = Field(None, description="完整原文（用于对齐）")

    # 书籍信息
    book_title: str = Field(..., description="书名")