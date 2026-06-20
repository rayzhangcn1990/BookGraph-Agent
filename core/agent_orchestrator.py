"""
BookGraph-Agent 编排层

统一管理 Agent 工具调用、状态管理、记忆层
"""

import logging
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
import json

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class AgentState:
    """Agent 状态管理"""
    book_path: str
    current_phase: str = "init"  # init/parse/chunk/process/synthesis/write/done
    metadata: Dict = field(default_factory=dict)
    chunk_results: List[Dict] = field(default_factory=list)
    book_graph_data: Optional[Dict] = None
    output_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """转换为字典（用于持久化）"""
        return {
            'book_path': self.book_path,
            'current_phase': self.current_phase,
            'metadata': self.metadata,
            'chunk_results': self.chunk_results,
            'book_graph_data': self.book_graph_data,
            'output_path': self.output_path,
            'errors': self.errors,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'AgentState':
        """从字典恢复状态"""
        return cls(
            book_path=data['book_path'],
            current_phase=data['current_phase'],
            metadata=data['metadata'],
            chunk_results=data['chunk_results'],
            book_graph_data=data['book_graph_data'],
            output_path=data['output_path'],
            errors=data['errors'],
            start_time=datetime.fromisoformat(data['start_time']),
            end_time=datetime.fromisoformat(data['end_time']) if data['end_time'] else None
        )


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
    metadata: Dict = field(default_factory=dict)


class AgentMemoryManager:
    """Agent 记忆层管理"""

    def __init__(self, db_path: str = ".cache/agent_memory.db"):
        """
        初始化记忆管理器

        Args:
            db_path: 数据库路径（SQLite）
        """
        self.db_path = db_path
        self.short_term = {}  # 短期记忆（当前会话）
        self.long_term = []  # 长期记忆（历史任务）

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 数据库"""
        import sqlite3
        from pathlib import Path

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_path TEXT NOT NULL,
                state_json TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def save_state(self, state: AgentState):
        """保存当前状态"""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO agent_states (book_path, state_json) VALUES (?, ?)",
            (state.book_path, json.dumps(state.to_dict()))
        )

        conn.commit()
        conn.close()

        # 同时保存到短期记忆
        self.short_term[state.book_path] = state

    def recall_state(self, book_path: str) -> Optional[AgentState]:
        """召回历史状态"""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT state_json FROM agent_states WHERE book_path = ? ORDER BY timestamp DESC LIMIT 1",
            (book_path,)
        )

        result = cursor.fetchone()
        conn.close()

        if result:
            return AgentState.from_dict(json.loads(result[0]))

        return None


class BookGraphAgentOrchestrator:
    """BookGraph-Agent 统一编排层"""

    def __init__(self, config: Dict):
        """
        初始化编排器

        Args:
            config: 配置字典
        """
        self.config = config
        self.tools = self._init_tools()
        self.memory = AgentMemoryManager()

    def _init_tools(self) -> Dict[str, Any]:
        """初始化工具集合"""
        from core.agent_tools import get_default_tools
        return get_default_tools(self.config)

    async def run(self, book_path: str) -> AgentResult:
        """
        统一编排入口

        Args:
            book_path: 书籍路径

        Returns:
            AgentResult: 执行结果
        """
        start_time = datetime.now()
        state = AgentState(book_path=book_path)

        try:
            # Phase 1: 解析书籍
            logger.info(f"📖 Phase 1: 解析书籍 - {book_path}")
            state.current_phase = "parse"

            parse_result = await self.tools['parse'].arun(book_path)

            if not parse_result.success:
                raise Exception(f"书籍解析失败: {parse_result.error}")

            state.metadata = parse_result.metadata
            logger.info(f"   ✅ 解析完成: {parse_result.title} ({len(parse_result.content)}字符)")

            # Phase 2: 分块
            logger.info("🧩 Phase 2: 分块处理")
            state.current_phase = "chunk"

            from main import _semantic_chunking
            chunks = _semantic_chunking(parse_result, self.config)

            logger.info(f"   ✅ 分块完成: {len(chunks)} 块")

            # Phase 3: Chunk 处理
            logger.info("⚡ Phase 3: Chunk 分析")
            state.current_phase = "process"

            process_result = await self.tools['process'].arun(
                chunks=chunks,
                book_title=parse_result.title,
                discipline=state.metadata.get('discipline', '哲学')
            )

            if not process_result.success:
                raise Exception(f"Chunk 处理失败: {process_result.error}")

            state.chunk_results = process_result.results
            logger.info(f"   ✅ Chunk 处理完成: {len(process_result.results)} 成功")

            # Phase 4: 综合
            logger.info("🔄 Phase 4: 综合分析")
            state.current_phase = "synthesis"

            # 调用主流程的综合逻辑
            from main import run_synthesis
            synthesis_result = await run_synthesis(
                chunk_results=state.chunk_results,
                book_title=parse_result.title,
                author=parse_result.author,
                discipline=state.metadata.get('discipline', '哲学'),
                llm_client=self._get_llm_client()
            )

            if not synthesis_result:
                raise Exception("综合分析失败")

            # 构建 BookGraph
            from main import build_book_graph
            book_graph, schema_error = build_book_graph(synthesis_result)

            if schema_error:
                raise Exception(f"Schema 校验失败: {schema_error}")

            state.book_graph_data = book_graph.model_dump()

            # Phase 5: 图谱生成
            logger.info("📝 Phase 5: 图谱生成")
            state.current_phase = "generate"

            generate_result = await self.tools['generate'].arun(state.book_graph_data)

            if not generate_result.success:
                raise Exception(f"图谱生成失败: {generate_result.error}")

            logger.info("   ✅ Markdown 生成完成")

            # Phase 6: 写入 Obsidian
            logger.info("💾 Phase 6: 写入 Obsidian")
            state.current_phase = "write"

            write_result = await self.tools['write'].arun(
                book_graph_data=state.book_graph_data,
                markdown_content=generate_result.markdown,
                source_book_path=book_path
            )

            if not write_result.success:
                raise Exception(f"Obsidian 写入失败: {write_result.error}")

            state.output_path = write_result.output_path
            state.current_phase = "done"
            state.end_time = datetime.now()

            elapsed = (state.end_time - start_time).total_seconds()
            logger.info(f"✅ 完成: {state.output_path} ({elapsed:.1f}秒)")

            # 保存状态到记忆层
            self.memory.save_state(state)

            return AgentResult(
                success=True,
                output_path=state.output_path,
                elapsed_seconds=elapsed,
                metadata=state.metadata
            )

        except Exception as e:
            logger.error(f"❌ 执行失败: {e}")
            state.errors.append(str(e))
            state.end_time = datetime.now()

            # 保存失败状态
            self.memory.save_state(state)

            elapsed = (state.end_time - start_time).total_seconds()
            return AgentResult(
                success=False,
                error=str(e),
                elapsed_seconds=elapsed,
                metadata=state.metadata
            )

    def _get_llm_client(self):
        """获取 LLM 客户端"""
        from core.llm_client import get_llm_client
        return get_llm_client(self.config)

    def recall_previous_state(self, book_path: str) -> Optional[AgentState]:
        """召回历史执行状态（用于断点续传）"""
        return self.memory.recall_state(book_path)

    def resume_from_state(self, state: AgentState) -> AgentResult:
        """从历史状态恢复执行（用于断点续传）"""
        logger.info(f"🔄 从断点恢复: {state.book_path} (Phase: {state.current_phase})")

        # 根据当前阶段决定恢复点
        if state.current_phase == "process":
            # 从 Chunk 处理恢复
            # ...
            pass

        # 完整恢复逻辑需要根据具体断点实现
        return self.run(state.book_path)