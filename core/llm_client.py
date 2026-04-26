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
import logging

import yaml
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 日志器
logger = logging.getLogger("BookGraph-Agent")

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
from core.multi_source_manager import MultiSourceAPIManager, create_client_from_source


# ═══════════════════════════════════════════════════════════
# 提示词体系
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位专业的学术书籍分析专家，精通知识图谱构建。你的任务是对书籍内容进行深度分析，输出结构化的知识图谱数据。

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"、"（内容由模型生成）"等无意义说明
3. 所有内容必须有实质性信息，如果确实无法分析某项，请基于上下文合理推断并明确标注
4. 对于底层逻辑，必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力
6. 所有关联书籍必须说明具体的关联维度

【分析标准】
1. 对核心理论，必须拆解底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
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
4. 对于底层逻辑，必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力

【分析要求】
请分析整本书的内容，提取以下信息（以 JSON 格式输出）：

1. 章节摘要：识别书中的所有章节，对每章提取：
   - chapter_number: 章节编号
   - title: 章节标题
   - core_argument: 核心论点（一句话概括，必须有实质内容）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - related_books: 关联书籍（如有提及）
   - critical_questions: 批判性问题（2-3 个，必须具体）

2. 核心概念：提取关键概念，对每个概念提取：
   - name: 概念名称
   - definition: 定义（必须有实质性内容，不能是占位符）
   - deep_meaning: 深层含义（必须具体分析）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - development_stages: 发展阶段（如有，包含阶段名称、时期、特点、消亡/进化原因）
   - core_drivers: 发展核心动力（数组，每项必须有实质内容）
   - critical_review: 批判性审视（必须具体分析，不能是占位符）
   - related_books: 关联书籍（如有）

3. 关键洞见：识别作者的重要观点，对每个洞见提取：
   - title: 洞见标题
   - description: 描述（必须有实质性内容）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
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
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - common_misreading: 常见误读（如有）
   - related_books: 关联书籍（如有）

请以 JSON 格式输出，不要添加任何额外说明。所有内容必须有实质性信息，严禁使用占位符。"""

# 🔑 优化：批量 Chunk 分析提示词（减少 API 调用次数）
BATCH_CHUNK_ANALYSIS_PROMPT = """请分析以下多个书籍内容块，提取结构化信息。

【书籍信息】
书名：{book_title}

【内容块列表】
以下内容按块分隔，每个块用 "--- CHUNK BREAK ---" 标记边界：

{batch_content}

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"等无意义说明
3. 所有内容必须有实质性信息
4. 对于底层逻辑，必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力

【分析要求】
请分析所有内容块，提取以下信息（以 JSON 格式输出）：

输出格式：
{{"chunks_analysis": [
    {{ "chunk_index": 0,
      "chapters": [...],
      "core_concepts": [...],
      "key_insights": [...],
      "key_cases": [...],
      "key_quotes": [...]
    }},
    {{ "chunk_index": 1,
      ...
    }}
  ]
}}

请以 JSON 格式输出，不要添加任何额外说明。所有内容必须有实质性信息，严禁使用占位符。"""

SYNTHESIS_PROMPT = """请将以下所有分析结果综合为完整的书籍知识图谱。

【书籍信息】
书名：{book_title}
作者：{author}

【章节列表（必须完整保留，不得过滤）】
以下是书籍的完整章节列表，你必须在输出中包含所有这些章节的摘要：
{chapters_list}

⚠️ 重要：你必须为上述每个章节都生成摘要，不得遗漏任何章节！

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
   - discipline: 字符串（一级学科，从以下选择：政治学、经济学、心理学、历史学、哲学、管理学、社会学、文学、科学、技术）
   - sub_discipline: 字符串或 null（二级子学科，如政治学下的：政治哲学、比较政治、国际关系等）
   - tags: 字符串数组
   - related_books: 字符串数组

2. time_background: 时代背景
   - macro_background: 字符串
   - micro_background: 字符串
   - core_contradiction: 字符串

3. chapters: 章节摘要数组（⚠️ 必须保留所有章节，不得选择性过滤）
   **重要**：根据分析结果中的章节信息，完整输出所有章节摘要，即使某些章节内容较少也要包含。
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

【可选一级学科类别】
政治学、经济学、心理学、历史学、哲学、管理学、社会学、文学、科学、技术

【政治学的子学科示例】
政治哲学、比较政治、国际关系、政治经济学、公共行政、政治理论

请从一级学科类别中选择最匹配的一个，如能确定子学科也可一并输出。
输出格式：一级学科名称 或 一级学科名称/子学科名称（如：政治学/政治哲学）
仅输出学科名称，不要添加任何额外说明。"""


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
    - 智能模型切换（额度耗尽自动切换）
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

        # 🔑 模型轮换系统
        self.model_rotation_list: List[str] = []  # 可用模型列表
        self.current_model_index: int = 0  # 当前模型索引
        self.exhausted_models: set = set()  # 额度耗尽的模型
        self.failed_models: set = set()  # 失败的模型

        # 🔑 多API源管理器
        self.multi_source_manager: Optional[MultiSourceAPIManager] = None

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

        # 🔑 初始化多API源管理器
        if self.config.get('api_sources'):
            self.multi_source_manager = MultiSourceAPIManager(self.config)
            source = self.multi_source_manager.get_current_source()
            if source:
                self.api_base = source.api_base
                api_key = source.api_key

                if OPENAI_AVAILABLE:
                    # 使用 create_client_from_source 自动处理特殊头
                    self.openai_client = create_client_from_source(source)
                    if self.openai_client:
                        self.provider = 'anthropic'

                        print(f"✅ 多源API初始化成功（源：{source.name}）")
                        print(f"   API Base: {source.api_base}")

                        self._setup_model_rotation()
                        return

        # 从配置读取 API 信息（单源模式）
        api_key = self.config.get('api_key', 'unused')
        base_url = self.config.get('api_base', '')

        # 优先使用配置文件中的设置
        if base_url:
            self.api_base = base_url

            # 使用 OpenAI 客户端连接本地 OpenRelay 服务
            if OPENAI_AVAILABLE:
                try:
                    self.openai_client = openai.OpenAI(
                        api_key=api_key,
                        base_url=base_url,
                        timeout=self.config.get('timeout', 600),
                    )
                    self.provider = 'anthropic'  # OpenRelay 使用 Anthropic 格式

                    print(f"✅ OpenRelay 客户端初始化成功（模型：{self.model}）")
                    print(f"   API Base: {base_url}")

                    # 🔑 设置模型轮换列表
                    self._setup_model_rotation()
                    return
                except Exception as e:
                    print(f"⚠️ OpenRelay 客户端初始化失败: {e}")

        # 尝试 Anthropic（从 Claude Code 设置读取）
        if ANTHROPIC_AVAILABLE and not self.openai_client:
            api_key_env = os.environ.get('ANTHROPIC_AUTH_TOKEN') or os.environ.get('ANTHROPIC_API_KEY', '')
            base_url_env = os.environ.get('ANTHROPIC_BASE_URL', '')

            # 从 Claude Code settings.json 读取
            if not api_key_env or not base_url_env:
                settings_path = Path.home() / '.claude' / 'settings.json'
                if settings_path.exists():
                    try:
                        with open(settings_path) as f:
                            env = json.load(f).get('env', {})
                        api_key_env = api_key_env or env.get('ANTHROPIC_AUTH_TOKEN', '')
                        base_url_env = base_url_env or env.get('ANTHROPIC_BASE_URL', '')
                        self.model = env.get('ANTHROPIC_MODEL', self.model)
                    except Exception:
                        pass

            if api_key_env and base_url_env:
                self.anthropic_client = anthropic.Anthropic(
                    api_key=api_key_env,
                    base_url=base_url_env,
                    timeout=600,
                )
                self.provider = 'anthropic'
                print(f"✅ Anthropic 客户端初始化成功（模型：{self.model}）")
                print(f"   API Base: {base_url_env}")
                return

        # 尝试 DashScope
        if OPENAI_AVAILABLE and not self.openai_client and not self.anthropic_client:
            api_key_env = os.environ.get('DASHSCOPE_API_KEY', '')
            api_base_env = os.environ.get('DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')

            if api_key_env and api_key_env not in ['your_dashscope_api_key_here', '***']:
                self.openai_client = openai.OpenAI(
                    api_key=api_key_env,
                    base_url=api_base_env
                )
                self.dashscope_api_key = api_key_env
                self.provider = 'dashscope'
                print(f"✅ DashScope 客户端初始化成功（模型：{self.model}）")
                print(f"   API Base: {api_base_env}")
                return

        # 后备：使用 Hermes 内置 LLM
        if not self.openai_client and not self.anthropic_client:
            print(f"⚠️  未配置有效 API，使用 Hermes 内置 LLM")
            self.use_hermes_llm = True
            self.model = 'qwen3.5-plus'
            print(f"   模型：{self.model}")

    def _auto_select_model(self):
        """自动选择最佳可用模型"""
        import asyncio

        # 如果配置指定了模型，先尝试使用
        config_model = self.config.get('model', '')

        # 自动模型选择逻辑（优先推理能力强）
        # 🔑 更新：基于完整测试的52个可用模型，优先最强推理模型
        preferred_models = [
            # ⭐ TOP级推理模型（知识图谱首选）
            "qwen/qwen3-coder-480b-a35b-instruct",   # 480B参数，最强推理
            "meta/llama-3.1-405b-instruct",          # Llama最大405B
            "mistralai/mistral-large-3-675b-instruct-2512", # Mistral最强675B
            "qwen/qwen3.5-397b-a17b",                # Qwen 3.5 397B
            "moonshotai/kimi-k2-instruct",           # Moonshot Kimi K2

            # ⭐ 强推理模型（70B+级别）
            "openai/gpt-oss-120b",                   # OpenAI OSS 120B
            "meta/llama-3.1-70b-instruct",           # Llama 3.1 70B
            "meta/llama-3.3-70b-instruct",           # Llama 3.3 70B
            "nvidia/llama-3.3-nemotron-super-49b-v1",# Nemotron Super 49B
            "deepseek-ai/deepseek-v4-pro",           # DeepSeek V4 Pro

            # ⭐ 备选模型
            "meta/llama-3.2-90b-vision-instruct",
            "qwen/qwen3-next-80b-a3b-instruct",
            "moonshotai/kimi-k2-thinking",
            "nvidia/nemotron-3-super-120b-a12b",

            # 原有模型（可能受限）
            "claude-opus-4.7",
            "claude-sonnet-4.6",
            "claude-sonnet-4-6",
            "gpt-4o-mini",
        ]

        # 检查配置的模型是否在首选列表中
        if config_model and config_model in preferred_models:
            self.model = config_model
            return

        # 尝试获取可用模型列表
        try:
            import httpx
            response = httpx.get(
                f"{self.api_base}/v1/models",
                headers={"x-api-key": self.config.get('api_key', 'unused')},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                available_ids = [m['id'] for m in data.get('data', [])]

                # 从首选列表中找第一个可用的
                for model in preferred_models:
                    if model in available_ids:
                        self.model = model
                        logger.info(f"🧠 自动选择模型: {model}")
                        return

                # 如果首选都不可用，使用配置的模型
                if config_model:
                    self.model = config_model
                    return

                # 默认使用第一个可用模型
                if available_ids:
                    self.model = available_ids[0]
                    return
        except Exception as e:
            logger.warning(f"获取模型列表失败: {e}")

        # 最终后备（使用验证可用的模型）
        self.model = config_model or "qwen/qwen3-coder-480b-a35b-instruct"

        # 🔑 初始化模型轮换列表（确保总有可用模型）
        self._setup_model_rotation()

    def _setup_model_rotation(self):
        """设置模型轮换列表，确保总有可用模型"""
        # 🔑 更新：基于完整测试的52个可用模型优先级排序
        model_priority = [
            # ⭐ TOP级推理模型（首选）
            "qwen/qwen3-coder-480b-a35b-instruct",
            "meta/llama-3.1-405b-instruct",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "qwen/qwen3.5-397b-a17b",
            "moonshotai/kimi-k2-instruct",

            # ⭐ 强推理模型
            "openai/gpt-oss-120b",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.3-70b-instruct",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "deepseek-ai/deepseek-v4-pro",

            # ⭐ 备选模型
            "meta/llama-3.2-90b-vision-instruct",
            "qwen/qwen3-next-80b-a3b-instruct",
            "moonshotai/kimi-k2-thinking",
            "nvidia/nemotron-3-super-120b-a12b",
            "gpt-4o-mini",

            # ⭐ 免费模型
            "openai/gpt-oss-120b:free",
            "openrouter/free",
            "minimax/minimax-m2.5:free",
        ]

        # 从API获取可用模型
        try:
            import httpx
            response = httpx.get(
                f"{self.api_base}/v1/models",
                headers={"x-api-key": self.config.get('api_key', 'unused')},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                available_ids = [m['id'] for m in data.get('data', [])]

                # 按优先级排序可用模型
                self.model_rotation_list = [
                    m for m in model_priority
                    if m in available_ids
                ]

                # 补充其他可用模型（不在优先列表中的）
                other_models = [
                    m for m in available_ids
                    if m not in self.model_rotation_list
                    and ':free' in m or 'free' in m  # 优先选择免费模型
                ]
                self.model_rotation_list.extend(other_models)

                # 再补充剩余模型
                remaining = [
                    m for m in available_ids
                    if m not in self.model_rotation_list
                ]
                self.model_rotation_list.extend(remaining)

                logger.info(f"📋 模型轮换列表: {len(self.model_rotation_list)} 个模型")
                if self.model_rotation_list:
                    logger.info(f"   首选: {self.model_rotation_list[:5]}")

                # 设置当前模型
                if self.model_rotation_list:
                    self.current_model_index = 0
                    self.model = self.model_rotation_list[0]

        except Exception as e:
            logger.warning(f"获取模型列表失败，使用默认列表: {e}")
            self.model_rotation_list = model_priority

        # 🔑 确保至少有一个模型（本地后备）
        if not self.model_rotation_list:
            self.model_rotation_list = ["hermes-local"]
            self.use_hermes_llm = True

    def switch_to_next_model(self, reason: str = ""):
        """切换到下一个可用模型"""
        # 标记当前模型为耗尽
        self.exhausted_models.add(self.model)
        logger.warning(f"⚠️ 模型 {self.model} 额度耗尽: {reason}")

        # 🔑 找下一个未耗尽的模型
        for i in range(len(self.model_rotation_list)):
            next_index = (self.current_model_index + 1 + i) % len(self.model_rotation_list)
            next_model = self.model_rotation_list[next_index]

            # 检查是否可用（未耗尽且未失败）
            if next_model not in self.exhausted_models and next_model not in self.failed_models:
                self.current_model_index = next_index
                self.model = next_model
                logger.info(f"🔄 切换到模型: {self.model}")
                return True

        # 🔑 所有主要模型都耗尽，尝试免费模型（重置耗尽记录）
        free_models = [m for m in self.model_rotation_list if ':free' in m or 'free' in m.lower()]
        if free_models:
            # 清空耗尽记录，从免费模型开始
            self.exhausted_models.clear()
            self.model = free_models[0]
            self.current_model_index = self.model_rotation_list.index(free_models[0])
            logger.info(f"🔄 使用免费模型: {self.model}")
            return True

        # 🔑 最终后备：本地模型
        logger.warning("⚠️ 所有远程模型不可用，启用本地处理模式")
        self.use_hermes_llm = True
        self.model = "hermes-local"
        return False

    def _call_llm_hermes(self, system_prompt: str, user_prompt: str, max_tokens: int = None) -> str:
        """
        从文件读取 LLM 响应（供 Hermes Agent 使用）
        """
        import json
        from pathlib import Path
        
        max_tokens = max_tokens or self.max_tokens
        
        # 查找响应文件
        response_files = sorted(Path('.').glob('response_*.json'))
        if not response_files:
            print("⚠️  未找到响应文件，请先创建 response_*.json 文件")
            return None
        
        # 使用第一个响应文件
        response_file = response_files[0]
        print(f"\n{'='*60}")
        print(f"📝 [从文件读取 LLM 响应: {response_file}]")
        print(f"{'='*60}")
        
        try:
            with open(response_file, 'r', encoding='utf-8') as f:
                response = f.read()
            
            # 删除已使用的文件
            response_file.unlink()
            print(f"✅ 读取响应成功，长度：{len(response)} 字符")
            print(f"   已删除文件：{response_file}")
            return response
        except Exception as e:
            print(f"❌ 读取响应文件失败: {e}")
            return None
    
    def _call_llm(self, messages: List[Dict], max_tokens: int = None) -> str:
        """
        调用 LLM - 支持自动模型切换和API源切换

        Args:
            messages: 消息列表
            max_tokens: 最大输出 token 数

        Returns:
            str: LLM 响应文本
        """
        max_tokens = max_tokens or self.max_tokens
        max_source_switches = 6  # 最大API源切换次数（我们有6个源）
        max_model_switches_per_source = 5  # 每个源最多尝试5个模型

        for source_attempt in range(max_source_switches):
            current_model_switches = 0

            for model_attempt in range(max_model_switches_per_source):
                current_model = self.model

                # 🔑 使用 OpenAI 客户端
                if self.openai_client and current_model != "hermes-local":
                    try:
                        response = self.openai_client.chat.completions.create(
                            model=current_model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=self.temperature
                        )
                        return response.choices[0].message.content

                    except Exception as e:
                        error_str = str(e)

                        # 🔑 检测额度耗尽
                        if self._is_quota_exhausted(error_str):
                            logger.warning(f"⚠️ 模型 {current_model} 额度耗尽")

                            # 🔑 关键优化：如果是共享额度源（OpenRelay），直接切换API源
                            current_source = self.multi_source_manager.get_current_source() if self.multi_source_manager else None
                            if current_source and current_source.quota_type == "shared":
                                logger.warning(f"⚠️ 共享额度源耗尽，立即切换API源")
                                if self._switch_api_source():
                                    # 切换成功，重新设置模型轮换
                                    self._setup_model_rotation()
                                    break  # 跳出模型循环，进入下一个源的循环
                                else:
                                    # 所有源都耗尽
                                    logger.error("❌ 所有API源额度耗尽")
                                    break
                            else:
                                # 独立额度源，尝试切换模型
                                current_model_switches += 1
                                if self.switch_to_next_model(f"额度耗尽: {current_model}"):
                                    continue
                                else:
                                    # 当前源的所有模型耗尽，切换源
                                    if self._switch_api_source():
                                        self._setup_model_rotation()
                                        break
                                    else:
                                        break

                        # 🔑 其他错误
                        elif 'error' in error_str.lower() or 'failed' in error_str.lower():
                            self.failed_models.add(current_model)
                            current_model_switches += 1
                            logger.warning(f"⚠️ 模型 {current_model} 调用失败: {error_str[:50]}")
                            if self.switch_to_next_model(f"调用失败"):
                                continue
                            else:
                                break

                        # 其他异常
                        logger.error(f"❌ API调用异常: {e}")
                        return None

                # 🔑 Anthropic 客户端（备用）
                elif self.anthropic_client and current_model != "hermes-local":
                    try:
                        system_content = ""
                        user_messages = []

                        for msg in messages:
                            if msg['role'] == 'system':
                                system_content = msg['content']
                            else:
                                user_messages.append(msg)

                        system_blocks = [
                            {
                                "type": "text",
                                "text": system_content,
                                "cache_control": {"type": "ephemeral"}
                            }
                        ] if system_content else None

                        response = self.anthropic_client.messages.create(
                            model=current_model,
                            max_tokens=max_tokens,
                            temperature=self.temperature,
                            system=system_blocks,
                            messages=user_messages,
                        )

                        text = ""
                        for block in response.content:
                            if hasattr(block, "text"):
                                text += block.text

                        return text if text else None

                    except Exception as e:
                        error_str = str(e)

                        if self._is_quota_exhausted(error_str):
                            current_model_switches += 1
                            if self.switch_to_next_model(f"额度耗尽: {current_model}"):
                                continue
                            else:
                                break

                        elif '429' in error_str or 'throttling' in error_str.lower():
                            time.sleep(5)
                            current_model_switches += 1
                            if self.switch_to_next_model(f"限流"):
                                continue
                            else:
                                break

                        self.failed_models.add(current_model)
                        return None

                # 🔑 本地后备
                else:
                    system_prompt = ""
                    user_prompt = ""
                    for msg in messages:
                        if msg['role'] == 'system':
                            system_prompt = msg['content']
                        elif msg['role'] == 'user':
                            user_prompt = msg['content']

                    return self._call_llm_hermes(system_prompt, user_prompt, max_tokens)

            # 检查是否成功切换到新源
            if self.multi_source_manager and self.multi_source_manager.current_source:
                current_source = self.multi_source_manager.get_current_source()
                if current_source and not current_source.is_exhausted:
                    continue  # 使用新源继续
            else:
                break  # 无可用源，退出

        # 所有源和模型都耗尽，使用本地处理
        logger.warning("⚠️ 所有远程资源耗尽，使用本地处理")
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg['role'] == 'system':
                system_prompt = msg['content']
            elif msg['role'] == 'user':
                user_prompt = msg['content']

        return self._call_llm_hermes(system_prompt, user_prompt, max_tokens)

    def _is_quota_exhausted(self, error_str: str) -> bool:
        """检测额度耗尽错误"""
        quota_keywords = [
            'daily_limit_exceeded',
            'rate limit',
            'quota',
            'limit exceeded',
            'too many requests',
            'usage limit',
            'credit',
            'billing',
            'insufficient_quota',
            '免费额度',
            '额度耗尽',
        ]
        error_lower = error_str.lower()
        return any(kw in error_lower for kw in quota_keywords)

    def _switch_api_source(self):
        """切换到下一个API源"""
        if self.multi_source_manager:
            success = self.multi_source_manager.switch_to_next_source("额度耗尽")
            if success:
                source = self.multi_source_manager.get_current_source()
                if source:
                    # 更新客户端
                    self.api_base = source.api_base
                    if OPENAI_AVAILABLE:
                        # 构建默认头（OpenRouter 需要特殊头）
                        default_headers = {}
                        if source.extra_headers:
                            default_headers.update(source.extra_headers)

                        if "openrouter" in source.name.lower():
                            default_headers.setdefault("HTTP-Referer", "https://bookgraph.app")
                            default_headers.setdefault("X-Title", "BookGraph-Agent")

                        self.openai_client = openai.OpenAI(
                            api_key=source.api_key or "unused",
                            base_url=source.api_base,
                            timeout=self.config.get('timeout', 600),
                            default_headers=default_headers if default_headers else None,
                        )
                    # 清空模型耗尽记录（新源有新额度）
                    self.exhausted_models.clear()
                    self.failed_models.clear()
                    logger.info(f"✅ 切换到API源: {source.name}")
                    return True
        return False

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
        metadata: Dict,
        chapters_list: str = ""  # 🔑 新增：完整章节列表（强制保留）
    ) -> BookGraph:
        """
        综合生成完整的 BookGraph

        Args:
            all_analyses: 所有分块分析结果
            metadata: 书籍元数据
            chapters_list: 完整章节列表（强制保留，防止LLM过滤）

        Returns:
            BookGraph: 完整的书籍知识图谱
        """
        # 🔑 移除截断，发送完整分析结果（避免章节丢失）
        analyses_str = json.dumps(all_analyses, ensure_ascii=False, indent=2)
        logger.info(f"综合生成输入长度: {len(analyses_str)} 字符")

        # 如果内容过长，发出警告但不截断
        if len(analyses_str) > 100000:
            logger.warning(f"⚠️ 分析结果较长({len(analyses_str)}字符)，可能导致API响应时间增加")

        prompt = SYNTHESIS_PROMPT.format(
            book_title=metadata.get('title', 'Unknown'),
            author=metadata.get('author', 'Unknown'),
            chapters_list=chapters_list,  # 🔑 传入章节列表
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
