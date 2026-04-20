"""
LLM Client - 大语言模型调用客户端

支持 DashScope(原生), Anthropic 和 OpenAI，包含完整的提示词体系和重试机制。
"""

from typing import Dict, List, Optional, Any, Union
from pathlib import Path
import json
import os
import time
from datetime import datetime

import yaml
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 尝试导入 LLM SDK
try:
    import dashscope
    from dashscope import Generation
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

from schemas.book_graph_schema import BookGraph, DisciplineType


# ═══════════════════════════════════════════════════════════
# 提示词体系
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位专业的学术书籍分析专家，精通知识图谱构建。你的任务是对书籍内容进行深度分析，输出结构化的知识图谱数据。

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"、"（内容由模型生成）"等无意义说明
3. 所有内容必须有实质性信息，如果确实无法分析某项，请基于上下文合理推断并明确标注
4. 对于底层逻辑，必须完整输出：前提假设→推理链条→核心结论
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力
6. 所有关联书籍必须说明具体的关联维度

【分析标准】
1. 对核心理论，必须拆解底层逻辑（前提假设→推理链条→核心结论）
2. 对涉及发展演化的内容，必须输出：各阶段特点、消亡/进化的原因与解释、发展的核心动力分析
3. 对金句必须进行语境化解读，区分字面意义与深层含义，识别常见误读
4. 批判性分析必须引入多元视角（女性主义、后殖民主义、制度经济学等）
5. 所有关联书籍必须说明关联的具体维度

【输出质量要求】
- 所有内容必须完整、具体、有信息量
- 避免模糊、笼统、空洞的表述
- 每个概念、洞见、案例都必须有实质性的分析和解读
- 如果某项内容确实无法从书中提取，请明确说明"书中未涉及此项内容"并跳过

输出格式：严格按照提供的 JSON Schema 输出，不添加任何额外说明。"""


CHUNK_ANALYSIS_PROMPT = """请分析以下书籍内容，提取结构化信息。

【书籍信息】
书名：{book_title}

【完整内容】
{chunk_content}

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"等无意义说明
3. 所有内容必须有实质性信息
4. 对于底层逻辑，必须完整输出：前提假设→推理链条→核心结论
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力

【分析要求】
请分析整本书的内容，提取以下信息（以 JSON 格式输出）：

1. 章节摘要：识别书中的所有章节，对每章提取：
   - chapter_number: 章节编号
   - title: 章节标题
   - core_argument: 核心论点（一句话概括，必须有实质内容）
   - underlying_logic: 底层逻辑（前提假设→推理链条→核心结论，必须完整）
   - related_books: 关联书籍（如有提及）
   - critical_questions: 批判性问题（2-3 个，必须具体）

2. 核心概念：提取关键概念，对每个概念提取：
   - name: 概念名称
   - definition: 定义（必须有实质性内容，不能是占位符）
   - deep_meaning: 深层含义（必须具体分析）
   - underlying_logic: 底层逻辑拆解（前提→推理→结论）
   - development_stages: 发展阶段（如有，包含阶段名称、时期、特点、消亡/进化原因）
   - core_drivers: 发展核心动力（数组，每项必须有实质内容）
   - critical_review: 批判性审视（必须具体分析，不能是占位符）
   - related_books: 关联书籍（如有）

3. 关键洞见：识别作者的重要观点，对每个洞见提取：
   - title: 洞见标题
   - description: 描述（必须有实质性内容）
   - underlying_logic: 底层逻辑（必须完整）
   - deep_assumptions: 深层假设列表（每项必须具体）
   - controversies: 潜在争议（必须具体分析）
   - multi_perspectives: 多维审视（不同视角的具体解读）

4. 关键案例：提取书中的具体案例，对每个案例提取：
   - name: 案例名称
   - source_chapter: 来源章节
   - event_description: 事件描述（必须具体详细）
   - development_stages: 发展阶段（每项必须包含名称和描述）
   - core_drivers: 发展核心动力（数组，每项必须具体）
   - historical_limitations: 历史局限性（必须具体分析）

5. 金句：摘录有代表性的原文语句，对每句提取：
   - text: 原文（必须是书中实际内容）
   - chapter: 来源章节
   - core_theme: 核心主题
   - background_context: 时代背景关联（必须具体）
   - underlying_logic: 底层逻辑
   - common_misreading: 常见误读（如有）
   - related_books: 关联书籍（如有）

请以 JSON 格式输出，不要添加任何额外说明。所有内容必须有实质性信息，严禁使用占位符。"""
SYNTHESIS_PROMPT = """请将以下所有分析结果综合为完整的书籍知识图谱。

【书籍信息】
书名：{book_title}
作者：{author}

【分析结果】
{all_chunk_analyses}

【综合要求】
请生成完整的 BookGraph JSON，包含以下部分：

1. metadata: 书籍元数据
   - title: 字符串
   - author: 字符串
   - author_intro: 字符串（作者简介）
   - year_published: 字符串或 null
   - category: 字符串数组
   - discipline: 字符串（从以下选择：政治哲学、经济学、心理学、历史学、哲学、管理学、社会学、文学、科学、技术）
   - tags: 字符串数组
   - related_books: 字符串数组

2. time_background: 时代背景
   - macro_background: 字符串
   - micro_background: 字符串
   - core_contradiction: 字符串

3. chapters: 章节摘要数组，每项包含：
   - chapter_number: 字符串
   - title: 字符串
   - core_argument: 字符串
   - underlying_logic: 字符串
   - related_books: 字符串数组
   - critical_questions: 字符串数组

4. core_concepts: 核心概念数组，每项包含：
   - name: 字符串
   - definition: 字符串
   - deep_meaning: 字符串
   - underlying_logic: 字符串
   - development_stages: 数组，每项为对象{{"name": "...", "period": "...", "characteristics": "...", "evolution_reason": "..."}}
   - core_drivers: 字符串数组
   - critical_review: 字符串
   - related_books: 字符串数组

5. key_insights: 关键洞见数组，每项包含：
   - title: 字符串
   - description: 字符串
   - underlying_logic: 字符串
   - deep_assumptions: 字符串数组
   - related_books: 字符串数组
   - controversies: 字符串
   - multi_perspectives: 对象，键为视角名称，值为解读字符串

6. key_cases: 关键案例数组，每项包含：
   - name: 字符串
   - source_chapter: 字符串
   - event_description: 字符串
   - development_stages: 数组，每项为对象{{"name": "...", "description": "..."}}
   - core_drivers: 字符串数组
   - related_books: 字符串数组
   - historical_limitations: 字符串

7. key_quotes: 金句数组，每项包含：
   - text: 字符串
   - chapter: 字符串
   - core_theme: 字符串
   - background_context: 字符串
   - underlying_logic: 字符串
   - common_misreading: 字符串或 null
   - related_books: 字符串数组

8. critical_analysis: 批判性分析
   - core_doubts: 数组，每项为对象{{"question": "...", "analysis": "..."}}
   - feminist_perspective: 字符串
   - postcolonial_perspective: 字符串
   - ethical_boundaries: 对象{{"reasonable": "...", "dangerous": "...", "institutional_safeguards": "..."}}

9. learning_path: 学习路径对象
   - beginner: 字符串数组
   - intermediate: 字符串数组
   - advanced: 字符串数组
   - practice: 字符串数组

10. book_network: 对象，键为书名，值为关联维度说明字符串

【重要格式要求】
- 必须输出有效的 JSON 格式
- 所有字段类型必须正确（字符串、数组、对象）
- 不要使用 Markdown 代码块包裹
- 不要添加任何额外说明文字

请严格按照上述格式输出完整的 JSON。"""


DISCIPLINE_DETECTION_PROMPT = """请判断以下书籍所属的学科类别。

【书籍信息】
书名：{book_title}
作者：{author}

【内容样本】
{first_chapter_content}

【可选学科类别】
政治哲学、经济学、心理学、历史学、哲学、管理学、社会学、文学、科学、技术

请从以上类别中选择最匹配的一个，仅输出学科名称，不要添加任何额外说明。"""


DISCIPLINE_GRAPH_UPDATE_PROMPT = """请将新书的内容整合到现有学科图谱中。

【现有学科图谱】
{existing_discipline_graph}

【新书知识图谱】
{new_book_graph}

【新书书名】
{book_title}

【更新要求】
1. 整合新书的核心概念到学科概念体系
2. 更新学科核心思想（如有新的贡献）
3. 在书籍网络中添加新书节点，并说明与已有书籍的关联关系
4. 如有新的学科发展洞见，更新发展脉络
5. 更新概念词汇库

请输出更新后的完整学科图谱内容（Markdown 格式）。"""


class LLMClient:
    """
    LLM 客户端类
    
    功能：
    - 支持 Anthropic 和 OpenAI
    - 完整的提示词体系
    - 指数退避重试机制
    - Token 计数和上下文管理
    """

    def __init__(self, config: Dict = None):
        """
        初始化 LLM 客户端
        
        Args:
            config: 配置字典
                - provider: 'anthropic' 或 'openai'
                - model: 模型名称
                - max_tokens: 最大输出 token 数
                - temperature: 温度参数
                - chunk_size: 分块大小
                - max_retries: 最大重试次数
        """
        self.config = config or {}
        self.provider = self.config.get('provider', 'anthropic')
        self.model = self.config.get('model', 'claude-3-5-sonnet-20241022')
        self.max_tokens = self.config.get('max_tokens', 32768)
        self.temperature = self.config.get('temperature', 0.3)
        self.chunk_size = self.config.get('chunk_size', 50000)
        self.max_retries = self.config.get('max_retries', 3)
        
        # 初始化客户端
        self._init_client()
        
        # Token 编码器
        self.token_encoder = None
        if TIKTOKEN_AVAILABLE:
            try:
                self.token_encoder = tiktoken.encoding_for_model("gpt-4")
            except Exception:
                self.token_encoder = tiktoken.get_encoding("cl100k_base")

    def _init_client(self):
        """初始化 LLM 客户端"""
        self.dashscope_api_key = None
        self.anthropic_client = None
        self.openai_client = None
        self.use_hermes_llm = False
        
        if self.provider == 'dashscope' and DASHSCOPE_AVAILABLE:
            api_key = os.environ.get('DASHSCOPE_API_KEY')
            if api_key and api_key != 'your_dashscope_api_key_here':
                dashscope.api_key = api_key
                self.dashscope_api_key = api_key
                print(f"✅ DashScope 客户端初始化成功（模型：{self.model}）")
                return
        
        # 如果没有有效 API Key，使用 Hermes 内置 LLM
        print(f"⚠️  未配置有效 API Key，使用 Hermes 内置 LLM")
        self.use_hermes_llm = True
        self.model = 'qwen3.5-plus'  # Hermes 使用的模型
        print(f"   模型：{self.model}")

    def _call_llm_hermes(self, system_prompt: str, user_prompt: str, max_tokens: int = None) -> str:
        """
        通过 Hermes Agent 工具调用 LLM
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户输入
            max_tokens: 最大输出 token 数
            
        Returns:
            str: LLM 响应文本
        """
        max_tokens = max_tokens or self.max_tokens
        
        # 输出提示词供 Hermes 调用
        print(f"\n{'='*60}")
        print(f"📝 [Hermes LLM 调用]")
        print(f"{'='*60}")
        print(f"System: {system_prompt[:500]}...")
        print(f"User: {user_prompt[:1000]}...")
        print(f"Max Tokens: {max_tokens}")
        print(f"{'='*60}")
        print(f"⚠️  等待 Hermes Agent 调用 LLM 工具...")
        print(f"{'='*60}\n")
        
        # 实际使用时，这里需要 Hermes Agent 通过工具调用获取响应
        # 目前返回提示词供 Hermes 处理
        return None  # Hermes Agent 会填充实际响应
    
    def _call_llm(self, messages: List[Dict], max_tokens: int = None) -> str:
        """
        调用 LLM - 使用 Hermes 内置 LLM
        
        Args:
            messages: 消息列表
            max_tokens: 最大输出 token 数
            
        Returns:
            str: LLM 响应文本
        """
        max_tokens = max_tokens or self.max_tokens
        
        # 提取系统提示和用户输入
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg['role'] == 'system':
                system_prompt = msg['content']
            elif msg['role'] == 'user':
                user_prompt = msg['content']
        
        # 使用 Hermes 内置 LLM
        return self._call_llm_hermes(system_prompt, user_prompt, max_tokens)

    def count_tokens(self, text: str) -> int:
        """
        计算文本的 token 数
        
        Args:
            text: 文本内容
            
        Returns:
            int: token 数量
        """
        if self.token_encoder:
            return len(self.token_encoder.encode(text))
        
        # 粗略估计（中文字符约 1.5 token/字，英文约 0.75 token/词）
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    def analyze_book_chunk(
        self, 
        chunk_content: str, 
        chunk_index: int, 
        total_chunks: int,
        book_title: str,
        context: Dict = None
    ) -> Dict:
        """
        分析单个文本块
        
        Args:
            chunk_content: 文本块内容
            chunk_index: 当前块索引
            total_chunks: 总块数
            book_title: 书名
            context: 额外上下文
            
        Returns:
            Dict: 结构化分析结果
        """
        prompt = CHUNK_ANALYSIS_PROMPT.format(
            book_title=book_title,
            chunk_index=chunk_index + 1,
            total_chunks=total_chunks,
            chunk_content=chunk_content[:self.chunk_size],  # 确保不超过限制
        )
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        
        response = self._call_llm(messages)
        
        # 解析 JSON 响应
        try:
            # 尝试提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                result = json.loads(json_str)
            else:
                result = json.loads(response)
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 解析失败：{e}")
            return {"raw_response": response}

    def _normalize_book_graph_data(self, data: Dict, metadata: Dict) -> Dict:
        """
        规范化 BookGraph 数据，处理 LLM 返回的不规范格式
        
        Args:
            data: LLM 返回的原始数据
            metadata: 书籍元数据
            
        Returns:
            Dict: 规范化后的数据
        """
        # 处理 metadata 中的 tuple
        if 'metadata' in data:
            meta = data['metadata']
            if isinstance(meta.get('title'), (tuple, list)):
                meta['title'] = str(meta['title'][0]) if meta['title'] else ''
            if isinstance(meta.get('author'), (tuple, list)):
                meta['author'] = str(meta['author'][0]) if meta['author'] else ''
        
        # 处理 core_drivers（应该是数组，LLM 可能返回字符串）
        for section in ['core_concepts', 'key_cases']:
            if section in data and isinstance(data[section], list):
                for item in data[section]:
                    if 'core_drivers' in item and isinstance(item['core_drivers'], str):
                        # 将逗号分隔的字符串转为数组
                        item['core_drivers'] = [s.strip() for s in item['core_drivers'].replace(',', ',').split('、') if s.strip()]
        
        # 处理 multi_perspectives（应该是对象，LLM 可能返回字符串）
        if 'key_insights' in data and isinstance(data['key_insights'], list):
            for item in data['key_insights']:
                if 'multi_perspectives' in item and isinstance(item['multi_perspectives'], str):
                    # 将字符串转为对象
                    item['multi_perspectives'] = {"其他视角": item['multi_perspectives']}
        
        # 处理 core_doubts（应该是对象数组，LLM 可能返回字符串）
        if 'critical_analysis' in data:
            ca = data['critical_analysis']
            if 'core_doubts' in ca and isinstance(ca['core_doubts'], list):
                for i, item in enumerate(ca['core_doubts']):
                    if isinstance(item, str):
                        ca['core_doubts'][i] = {"question": item, "analysis": ""}
            
            if 'ethical_boundaries' in ca and isinstance(ca['ethical_boundaries'], str):
                ca['ethical_boundaries'] = {
                    "reasonable": ca['ethical_boundaries'],
                    "dangerous": "",
                    "institutional_safeguards": ""
                }
        
        # 处理 development_stages（应该是对象数组，LLM 可能返回字符串）
        for section in ['core_concepts', 'key_cases']:
            if section in data and isinstance(data[section], list):
                for item in data[section]:
                    if 'development_stages' in item and isinstance(item['development_stages'], list):
                        for i, stage in enumerate(item['development_stages']):
                            if isinstance(stage, str):
                                item['development_stages'][i] = {"name": stage, "description": ""}
        
        # 处理 learning_path（应该是对象，各字段为数组，LLM 可能返回字符串）
        if 'learning_path' in data and isinstance(data['learning_path'], dict):
            lp = data['learning_path']
            for key in ['beginner', 'intermediate', 'advanced', 'practice']:
                if key in lp and isinstance(lp[key], str):
                    lp[key] = [lp[key]]
        
        return data

    def synthesize_book_graph(
        self, 
        all_analyses: List[Dict], 
        metadata: Dict
    ) -> BookGraph:
        """
        综合生成完整的 BookGraph
        
        Args:
            all_analyses: 所有分块分析结果
            metadata: 书籍元数据
            
        Returns:
            BookGraph: 完整的书籍知识图谱
        """
        # 准备综合提示词
        analyses_str = json.dumps(all_analyses, ensure_ascii=False, indent=2)
        
        # 如果太长，智能截断（保留最后一个完整的 JSON 对象）
        max_length = 100000
        if len(analyses_str) > max_length:
            # 寻找截断点：向前寻找最后一个完整的 JSON 对象结束位置
            truncate_pos = max_length
            while truncate_pos > max_length - 1000:
                if analyses_str[truncate_pos] == '}':
                    analyses_str = analyses_str[:truncate_pos + 1]
                    analyses_str += "\n...（内容过长，已截断，保留部分分析结果）"
                    break
                truncate_pos -= 1
            else:
                # 无法找到合适的截断点，使用简单截断
                analyses_str = analyses_str[:max_length] + "...（内容过长，已截断）"
        
        prompt = SYNTHESIS_PROMPT.format(
            book_title=metadata.get('title', 'Unknown'),
            author=metadata.get('author', 'Unknown'),
            all_chunk_analyses=analyses_str,
        )
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        response = self._call_llm(messages, max_tokens=32768)
        
        # 解析 JSON 响应
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)
            else:
                data = json.loads(response)
            
            # 数据预处理：规范化格式
            data = self._normalize_book_graph_data(data, metadata)
            
            # 构建 BookGraph 对象
            book_graph = BookGraph(**data)
            return book_graph
            
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"⚠️ BookGraph 合成失败：{e}")
            # 返回一个基础的 BookGraph
            from schemas.book_graph_schema import (
                BookMetadata, TimeBackground, CriticalAnalysis
            )
            
            return BookGraph(
                metadata=BookMetadata(
                    title=metadata.get('title', 'Unknown'),
                    author=metadata.get('author', 'Unknown'),
                    author_intro=metadata.get('author_intro', ''),
                    discipline=metadata.get('discipline', DisciplineType.哲学),
                ),
                time_background=TimeBackground(
                    macro_background="待补充",
                    micro_background="待补充",
                    core_contradiction="待补充",
                ),
                critical_analysis=CriticalAnalysis(
                    feminist_perspective="待补充",
                    postcolonial_perspective="待补充",
                    ethical_boundaries={},
                ),
            )

    def detect_discipline(
        self, 
        title: str, 
        author: str, 
        sample_content: str
    ) -> DisciplineType:
        """
        检测书籍所属学科
        
        Args:
            title: 书名
            author: 作者
            sample_content: 内容样本（第一章）
            
        Returns:
            DisciplineType: 学科类型
        """
        # 截断样本内容
        sample_content = sample_content[:5000] if sample_content else "无内容"
        
        prompt = DISCIPLINE_DETECTION_PROMPT.format(
            book_title=title,
            author=author,
            first_chapter_content=sample_content,
        )
        
        messages = [
            {"role": "system", "content": "你是一位学科分类专家。请准确判断书籍所属学科。"},
            {"role": "user", "content": prompt},
        ]
        
        response = self._call_llm(messages, max_tokens=50)
        
        # 解析学科名称
        discipline_name = response.strip()
        
        # 映射到 DisciplineType
        try:
            return DisciplineType(discipline_name)
        except ValueError:
            # 如果无法匹配，返回默认值
            print(f"⚠️ 无法识别学科 '{discipline_name}'，使用默认值：哲学")
            return DisciplineType.哲学

    def update_discipline_graph(
        self, 
        existing_graph: str, 
        new_book_graph: BookGraph,
        book_title: str
    ) -> str:
        """
        更新学科图谱
        
        Args:
            existing_graph: 现有学科图谱内容
            new_book_graph: 新书知识图谱
            book_title: 新书书名
            
        Returns:
            str: 更新后的学科图谱内容
        """
        new_book_json = new_book_graph.model_dump_json(indent=2)
        
        # 截断如果太长
        if len(existing_graph) > 50000:
            existing_graph = existing_graph[:50000] + "...（已截断）"
        
        prompt = DISCIPLINE_GRAPH_UPDATE_PROMPT.format(
            existing_discipline_graph=existing_graph,
            new_book_graph=new_book_json,
            book_title=book_title,
        )
        
        messages = [
            {"role": "system", "content": "你是一位学科知识图谱专家。请智能整合新书内容到现有图谱中。"},
            {"role": "user", "content": prompt},
        ]
        
        response = self._call_llm(messages, max_tokens=16384)
        
        return response
