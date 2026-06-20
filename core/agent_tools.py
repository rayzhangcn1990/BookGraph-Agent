"""
BookGraph-Agent 工具层封装

遵循 LangChain Tool 标准，将现有能力封装为可独立调用的 Agent 工具
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger("BookGraph-Agent")


# ═══════════════════════════════════════════════════════════
# 数据模型定义
# ═══════════════════════════════════════════════════════════

class ParseBookInput(BaseModel):
    """书籍解析工具输入"""
    book_path: str = Field(..., description="书籍文件路径（PDF/EPUB/MOBI）")


class ParseBookOutput(BaseModel):
    """书籍解析工具输出"""
    success: bool = Field(..., description="是否成功")
    title: Optional[str] = Field(None, description="书名")
    author: Optional[str] = Field(None, description="作者")
    content: Optional[str] = Field(None, description="解析后的文本内容")
    metadata: Optional[Dict] = Field(None, description="元数据")
    error: Optional[str] = Field(None, description="错误信息")


class ProcessChunksInput(BaseModel):
    """Chunk 处理工具输入"""
    chunks: List[str] = Field(..., description="书籍分块列表")
    book_title: str = Field(..., description="书名")
    discipline: str = Field(default="哲学", description="学科")


class ProcessChunksOutput(BaseModel):
    """Chunk 处理工具输出"""
    success: bool = Field(..., description="是否成功")
    results: Optional[List[Dict]] = Field(None, description="Chunk 分析结果列表")
    failed_indices: Optional[List[int]] = Field(None, description="失败的 chunk 索引")
    error: Optional[str] = Field(None, description="错误信息")


class GenerateGraphInput(BaseModel):
    """图谱生成工具输入"""
    book_graph_data: Dict = Field(..., description="书籍图谱数据（JSON）")


class GenerateGraphOutput(BaseModel):
    """图谱生成工具输出"""
    success: bool = Field(..., description="是否成功")
    markdown: Optional[str] = Field(None, description="生成的 Markdown 内容")
    error: Optional[str] = Field(None, description="错误信息")


class WriteObsidianInput(BaseModel):
    """Obsidian 写入工具输入"""
    book_graph_data: Dict = Field(..., description="书籍图谱数据")
    markdown_content: str = Field(..., description="Markdown 内容")
    source_book_path: Optional[str] = Field(None, description="源书籍路径")


class WriteObsidianOutput(BaseModel):
    """Obsidian 写入工具输出"""
    success: bool = Field(..., description="是否成功")
    output_path: Optional[str] = Field(None, description="输出文件路径")
    error: Optional[str] = Field(None, description="错误信息")


# ═══════════════════════════════════════════════════════════
# 工具实现
# ═══════════════════════════════════════════════════════════

class BookParserTool:
    """书籍解析工具"""

    name = "parse_book"
    description = "解析书籍文件（PDF/EPUB/MOBI），提取文本内容和元数据"

    def __init__(self, config: Dict = None):
        """
        初始化工具

        Args:
            config: 配置字典
        """
        self.config = config or {}

    def _run(self, book_path: str) -> ParseBookOutput:
        """
        同步执行工具

        Args:
            book_path: 书籍文件路径

        Returns:
            ParseBookOutput: 解析结果
        """
        try:
            from core.book_parser import BookParser

            parser = BookParser(book_path, self.config.get('parsing', {}))
            result = parser.parse()

            if not result.success:
                return ParseBookOutput(
                    success=False,
                    error=result.error
                )

            return ParseBookOutput(
                success=True,
                title=result.metadata.get('title'),
                author=result.metadata.get('author'),
                content=result.content,
                metadata=result.metadata
            )

        except Exception as e:
            logger.error(f"书籍解析失败: {e}")
            return ParseBookOutput(
                success=False,
                error=str(e)
            )

    async def arun(self, book_path: str) -> ParseBookOutput:
        """
        异步执行工具

        Args:
            book_path: 书籍文件路径

        Returns:
            ParseBookOutput: 解析结果
        """
        import asyncio
        return await asyncio.to_thread(self._run, book_path)


class ChunkProcessorTool:
    """Chunk 处理工具"""

    name = "process_chunks"
    description = "并行处理书籍分块，调用 LLM 分析每个 chunk"

    def __init__(self, config: Dict = None):
        """
        初始化工具

        Args:
            config: 配置字典
        """
        self.config = config or {}

    async def arun(
        self,
        chunks: List[str],
        book_title: str,
        discipline: str = "哲学"
    ) -> ProcessChunksOutput:
        """
        异步执行工具

        Args:
            chunks: 书籍分块列表
            book_title: 书名
            discipline: 学科

        Returns:
            ProcessChunksOutput: 处理结果
        """
        try:
            from core.optimized_chunk_processor import OptimizedChunkProcessor
            from core.llm_client import get_llm_client, SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT

            llm_client = get_llm_client(self.config)
            processor = OptimizedChunkProcessor(
                llm_client,
                max_parallel=self.config.get('llm', {}).get('max_parallel', 4)
            )

            # 并行处理所有 chunks
            results = []
            failed_indices = []

            for i, chunk in enumerate(chunks):
                result = await processor.process_single_chunk(
                    chunk_index=i,
                    chunk_content=chunk,
                    book_title=book_title,
                    system_prompt=SYSTEM_PROMPT,
                    chunk_prompt_template=CHUNK_ANALYSIS_PROMPT
                )

                if result.success:
                    results.append(result.result)
                else:
                    failed_indices.append(i)
                    logger.warning(f"Chunk {i} 处理失败: {result.error}")

            return ProcessChunksOutput(
                success=len(failed_indices) < len(chunks) * 0.5,  # 失败率 < 50% 视为成功
                results=results,
                failed_indices=failed_indices if failed_indices else None
            )

        except Exception as e:
            logger.error(f"Chunk 处理失败: {e}")
            return ProcessChunksOutput(
                success=False,
                error=str(e)
            )


class GraphGeneratorTool:
    """图谱生成工具"""

    name = "generate_graph"
    description = "生成书籍知识图谱 Markdown 内容"

    def __init__(self, config: Dict = None):
        """
        初始化工具

        Args:
            config: 配置字典
        """
        self.config = config or {}

    def _run(self, book_graph_data: Dict) -> GenerateGraphOutput:
        """
        同步执行工具

        Args:
            book_graph_data: 书籍图谱数据

        Returns:
            GenerateGraphOutput: 生成结果
        """
        try:
            from core.graph_generator import GraphGenerator
            from schemas.book_graph_schema import BookGraph

            # 构造 BookGraph 对象
            book_graph = BookGraph(**book_graph_data)

            generator = GraphGenerator(self.config)
            markdown = generator.generate_book_graph_markdown(book_graph)

            return GenerateGraphOutput(
                success=True,
                markdown=markdown
            )

        except Exception as e:
            logger.error(f"图谱生成失败: {e}")
            return GenerateGraphOutput(
                success=False,
                error=str(e)
            )

    async def arun(self, book_graph_data: Dict) -> GenerateGraphOutput:
        """
        异步执行工具

        Args:
            book_graph_data: 书籍图谱数据

        Returns:
            GenerateGraphOutput: 生成结果
        """
        import asyncio
        return await asyncio.to_thread(self._run, book_graph_data)


class ObsidianWriterTool:
    """Obsidian 写入工具"""

    name = "write_obsidian"
    description = "将书籍图谱写入 Obsidian Vault"

    def __init__(self, config: Dict = None):
        """
        初始化工具

        Args:
            config: 配置字典
        """
        self.config = config or {}

    def _run(
        self,
        book_graph_data: Dict,
        markdown_content: str,
        source_book_path: Optional[str] = None
    ) -> WriteObsidianOutput:
        """
        同步执行工具

        Args:
            book_graph_data: 书籍图谱数据
            markdown_content: Markdown 内容
            source_book_path: 源书籍路径

        Returns:
            WriteObsidianOutput: 写入结果
        """
        try:
            from core.obsidian_writer import ObsidianWriter
            from schemas.book_graph_schema import BookGraph

            # 构造 BookGraph 对象
            book_graph = BookGraph(**book_graph_data)

            writer = ObsidianWriter(self.config.get('obsidian', {}))

            # 写入文件
            output_path = writer.write_book_graph(
                book_graph,
                markdown_content,
                source_book_path=Path(source_book_path) if source_book_path else None
            )

            return WriteObsidianOutput(
                success=True,
                output_path=str(output_path)
            )

        except Exception as e:
            logger.error(f"Obsidian 写入失败: {e}")
            return WriteObsidianOutput(
                success=False,
                error=str(e)
            )

    async def arun(
        self,
        book_graph_data: Dict,
        markdown_content: str,
        source_book_path: Optional[str] = None
    ) -> WriteObsidianOutput:
        """
        异步执行工具

        Args:
            book_graph_data: 书籍图谱数据
            markdown_content: Markdown 内容
            source_book_path: 源书籍路径

        Returns:
            WriteObsidianOutput: 写入结果
        """
        import asyncio
        return await asyncio.to_thread(
            self._run,
            book_graph_data,
            markdown_content,
            source_book_path
        )


# ═══════════════════════════════════════════════════════════
# 工具注册表
# ═══════════════════════════════════════════════════════════

def get_default_tools(config: Dict = None) -> Dict[str, Any]:
    """
    获取默认工具集合

    Args:
        config: 配置字典

    Returns:
        Dict[str, Any]: 工具名称到工具实例的映射
    """
    return {
        'parse': BookParserTool(config),
        'process': ChunkProcessorTool(config),
        'generate': GraphGeneratorTool(config),
        'write': ObsidianWriterTool(config)
    }
