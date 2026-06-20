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

# 🔑 异步客户端（Phase 3: LLM 异步化）
try:
    from openai import AsyncOpenAI
    ASYNC_OPENAI_AVAILABLE = True
except ImportError:
    ASYNC_OPENAI_AVAILABLE = False

try:
    from anthropic import AsyncAnthropic
    ASYNC_ANTHROPIC_AVAILABLE = True
except ImportError:
    ASYNC_ANTHROPIC_AVAILABLE = False

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

from schemas.book_graph_schema import BookGraph, DisciplineType
from core.multi_source_manager import MultiSourceAPIManager, create_client_from_source
from core.model_pool_manager import ModelPoolManager
import re


def resolve_env_vars(value: str) -> str:
    """
    解析环境变量引用（${VAR_NAME} 格式）

    Args:
        value: 可能包含环境变量引用的字符串

    Returns:
        str: 解析后的字符串（环境变量已替换）
    """
    if not isinstance(value, str):
        return value

    # 匹配 ${VAR_NAME} 格式
    pattern = r'\$\{([^}]+)\}'

    def replace_env_var(match):
        var_name = match.group(1)
        env_value = os.environ.get(var_name, '')
        if not env_value:
            logger.warning(f"⚠️ 环境变量 {var_name} 未设置，使用空值")
        return env_value

    return re.sub(pattern, replace_env_var, value)


def resolve_config_env_vars(config: Dict) -> Dict:
    """
    递归解析配置中的所有环境变量引用

    Args:
        config: 配置字典

    Returns:
        Dict: 解析后的配置字典
    """
    if not isinstance(config, dict):
        return config

    resolved = {}
    for key, value in config.items():
        if isinstance(value, dict):
            resolved[key] = resolve_config_env_vars(value)
        elif isinstance(value, list):
            resolved[key] = [
                resolve_config_env_vars(item) if isinstance(item, dict)
                else resolve_env_vars(item) if isinstance(item, str)
                else item
                for item in value
            ]
        elif isinstance(value, str):
            resolved[key] = resolve_env_vars(value)
        else:
            resolved[key] = value

    return resolved
from core.prompts import (
    SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT, SYNTHESIS_PROMPT, BATCH_CHUNK_ANALYSIS_PROMPT,

    DISCIPLINE_DETECTION_PROMPT, DISCIPLINE_GRAPH_UPDATE_PROMPT
)

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
        # 🔑 解析环境变量引用（${VAR_NAME} 格式）
        resolved_config = resolve_config_env_vars(config) if config else {}
        if 'llm' in resolved_config and 'provider' not in resolved_config:
            resolved_config = resolved_config.get('llm', {}) or {}
        self.config = resolved_config
        self.provider = self.config.get('provider', 'anthropic')
        self.model = self.config.get('model', 'claude-3-5-sonnet-20241022')
        self.max_tokens = self.config.get('max_tokens', 32768)
        self.temperature = self.config.get('temperature', 0.3)
        self.chunk_size = self.config.get('chunk_size', 50000)
        self.max_retries = self.config.get('max_retries', 3)
        self.api_base = self.config.get('api_base', '')

        # 🔑 模型轮换系统
        self.model_rotation_list: List[str] = []  # 可用模型列表
        self.current_model_index: int = 0  # 当前模型索引
        self.exhausted_models: set = set()  # 额度耗尽的模型
        self.failed_models: set = set()  # 失败的模型

        # 🔑 多API源管理器
        self.multi_source_manager: Optional[MultiSourceAPIManager] = None

        # 🔑 模型池管理器（新增）
        self.model_pool_manager: Optional[ModelPoolManager] = None

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

            # 🔑 初始化模型池管理器（新增）
            self.model_pool_manager = ModelPoolManager(self.config)

            source = self.multi_source_manager.get_current_source()
            if source:
                self.api_base = source.api_base
                api_key = source.api_key

                if OPENAI_AVAILABLE:
                    # 使用 create_client_from_source 自动处理特殊头
                    self.openai_client = create_client_from_source(source)
                    if self.openai_client:
                        self.provider = 'anthropic'

                        logger.info(f"✅ 多源API初始化成功（源：{source.name}）")
                        logger.info(f"   API Base: {source.api_base}")

                        # 🔑 使用模型池管理器选择模型（替换旧逻辑）
                        self._select_model_from_pool()
                        return

        # 🔑 优先尝试 Anthropic 兼容端点（当 provider 为 anthropic 时）
        if self.provider == 'anthropic' and ANTHROPIC_AVAILABLE:
            api_key_env = os.environ.get('ANTHROPIC_AUTH_TOKEN') or os.environ.get('ANTHROPIC_API_KEY', '')
            base_url_env = os.environ.get('ANTHROPIC_BASE_URL', '')

            # 从 Claude Code settings.json 读取（总是读取 model，因为配置可能滞后）
            settings_path = Path.home() / '.claude' / 'settings.json'
            if settings_path.exists():
                try:
                    with open(settings_path) as f:
                        env = json.load(f).get('env', {})
                    api_key_env = api_key_env or env.get('ANTHROPIC_AUTH_TOKEN', '')
                    base_url_env = base_url_env or env.get('ANTHROPIC_BASE_URL', '')
                    if env.get('ANTHROPIC_MODEL'):
                        self.model = env.get('ANTHROPIC_MODEL', self.model)
                except Exception:
                    pass

            if api_key_env and base_url_env:
                # 创建 Anthropic 原生客户端（备用）
                self.anthropic_client = anthropic.Anthropic(
                    api_key=api_key_env,
                    base_url=base_url_env,
                    timeout=180,
                )
                # 🔑 同时创建 OpenAI 客户端 — 需要 /v1 前缀
                if OPENAI_AVAILABLE:
                    self.openai_client = openai.OpenAI(
                        api_key=api_key_env,
                        base_url=base_url_env.rstrip("/") + "/v1",
                        timeout=180,
                    )
                self.provider = 'anthropic'
                logger.info(f"✅ 客户端初始化成功（模型：{self.model}）")
                logger.info(f"   API Base: {base_url_env}")
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
                logger.info(f"✅ DashScope 客户端初始化成功（模型：{self.model}）")
                logger.info(f"   API Base: {api_base_env}")
                return

        # 从 config 直接创建 OpenAI 客户端（provider: openai + api_base + api_key）
        if OPENAI_AVAILABLE and not self.openai_client and not self.anthropic_client:
            config_api_base = self.config.get('api_base', '')
            config_api_key = self.config.get('api_key', '')
            if config_api_base and config_api_key and config_api_key not in ['', 'unused']:
                # 🔑 增强超时控制：分离连接/读取/写入超时
                import httpx
                timeout_config = httpx.Timeout(
                    connect=30.0,  # 连接超时30秒
                    read=self.config.get('timeout', 240),  # 读取超时（可配置）
                    write=30.0,  # 写入超时30秒
                    pool=30.0   # 连接池超时30秒
                )
                self.openai_client = openai.OpenAI(
                    api_key=config_api_key,
                    base_url=config_api_base,
                    timeout=timeout_config,
                )
                self.provider = 'openai'
                logger.info(f"✅ OpenAI 客户端初始化成功（模型: {self.model}）")
                logger.info(f"   API Base: {config_api_base}")
                logger.info(f"   超时配置: 连接={timeout_config.connect}s, 读取={timeout_config.read}s")
                return

        # 后备：使用 Hermes 内置 LLM
        if not self.openai_client and not self.anthropic_client:
            logger.warning(f"⚠️  未配置有效 API，使用 Hermes 内置 LLM")
            self.use_hermes_llm = True
            self.model = 'qwen3.5-plus'
            logger.info(f"   模型：{self.model}")

    def _auto_select_model(self):
        """自动选择最佳可用模型"""
        import asyncio

        # 🔑 优先使用配置指定的模型（已验证可用）
        config_model = self.config.get('model', '')
        available_models = self.config.get('available_models', [])

        # 🧪 调试：打印配置读取
        logger.debug(f"[DEBUG] config_model: {config_model}")
        logger.debug(f"[DEBUG] available_models: {len(available_models)} items")

        # 如果配置有验证可用模型池，优先使用
        if available_models:
            # 使用验证可用的第一个模型
            first_available = available_models[0]
            self.model = first_available.get('model', config_model)
            logger.info(f"🎯 使用验证可用模型: {self.model}")
            return

        # 如果配置明确指定了模型，直接使用
        if config_model and 'nemotron' in config_model or 'nvidia' in config_model:
            self.model = config_model
            logger.info(f"🎯 使用配置模型: {self.model}")
            return

        # 自动模型选择逻辑（仅在未配置时使用）
        preferred_models = [
            # 🔑 验证可用模型优先
            "nvidia/llama-3.3-nemotron-super-49b-v1",  # 验证可用（0.68s）
            "tencent/hy3-preview:free",                # 验证可用（2.66s）

            # ⭐ TOP级推理模型
            "qwen/qwen3-coder-480b-a35b-instruct",
            "meta/llama-3.1-405b-instruct",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "qwen/qwen3.5-397b-a17b",
            "moonshotai/kimi-k2-instruct",

            # ⭐ 强推理模型
            "openai/gpt-oss-120b",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.3-70b-instruct",
            "deepseek-ai/deepseek-v4-pro",
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

        # 最终后备
        self.model = config_model or "nvidia/llama-3.3-nemotron-super-49b-v1"

    def _select_model_from_pool(self):
        """
        从模型池选择模型（使用 ModelPoolManager）

        替换旧的 _auto_select_model 和 _setup_model_rotation
        """
        # 🔑 检查模型池是否启用
        model_pool_enabled = self.config.get('model_pool', {}).get('enabled', True)

        if not model_pool_enabled or not self.model_pool_manager:
            # 模型池禁用：直接使用配置的模型
            logger.info(f"🎯 模型池已禁用，使用配置的模型: {self.model}")
            return

        # 🔑 从池管理器获取可用模型配置
        pool_models_config = self.model_pool_manager.get_available_models_config()

        if pool_models_config:
            # 使用池中第一个模型
            best_model = pool_models_config[0]
            self.model = best_model['model']
            self.api_base = best_model['api_base']

            # 🔑 设置轮换列表（从池配置）
            self.model_rotation_list = [m['model'] for m in pool_models_config]
            self.current_model_index = 0

            logger.info(f"🎯 从模型池选择: {self.model}")
            logger.info(f"   稳定性: {best_model.get('stability', 0):.2f}")
            logger.info(f"   响应时间: {best_model.get('response_time', 0):.2f}s")
            logger.info(f"   轮换列表: {len(self.model_rotation_list)} 个模型")

            # 🔑 更新配置中的 available_models（持久化）
            self.config['available_models'] = pool_models_config

        else:
            # 池为空，使用旧逻辑
            logger.warning("⚠️ 模型池为空，使用传统模型选择")
            self._auto_select_model()
            self._setup_model_rotation()

    def _setup_model_rotation(self):
        """设置模型轮换列表，确保总有可用模型"""
        # 🔑 保留已选择的模型（不覆盖）
        selected_model = self.model

        # 🔑 验证可用模型优先（从配置读取）
        available_models_config = self.config.get('available_models', [])
        config_priority = [m.get('model') for m in available_models_config if m.get('model')]

        # 其他模型优先级
        model_priority = config_priority + [
            # ⭐ TOP级推理模型
            "qwen/qwen3-coder-480b-a35b-instruct",
            "meta/llama-3.1-405b-instruct",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "qwen/qwen3.5-397b-a17b",
            "moonshotai/kimi-k2-instruct",

            # ⭐ 强推理模型
            "openai/gpt-oss-120b",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.3-70b-instruct",
            "deepseek-ai/deepseek-v4-pro",

            # ⭐ 备选模型
            "meta/llama-3.2-90b-vision-instruct",
            "qwen/qwen3-next-80b-a3b-instruct",
            "moonshotai/kimi-k2-thinking",
            "nvidia/nemotron-3-super-120b-a12b",
            "gpt-4o-mini",

            # ⭐ 免费模型
            "openai/gpt-oss-120b:free",
            "tencent/hy3-preview:free",
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

                # 🔑 只有当模型未设置时才使用轮换列表第一个
                if self.model_rotation_list and not selected_model:
                    self.current_model_index = 0
                    self.model = self.model_rotation_list[0]
                elif selected_model:
                    # 保留已选择的模型，确保它在轮换列表中
                    if selected_model not in self.model_rotation_list:
                        self.model_rotation_list.insert(0, selected_model)
                    self.current_model_index = self.model_rotation_list.index(selected_model)
                    logger.info(f"🎯 保留已选择模型: {self.model}")

        except Exception as e:
            logger.warning(f"获取模型列表失败，使用默认列表: {e}")
            self.model_rotation_list = model_priority

        # 至少保留当前配置模型，避免空轮换列表把状态推入伪后备模式
        if not self.model_rotation_list and self.model:
            self.model_rotation_list = [self.model]

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

        logger.warning("⚠️ 所有远程模型不可用")
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
            logger.warning("⚠️  未找到响应文件，请先创建 response_*.json 文件")
            return None

        # 使用第一个响应文件
        response_file = response_files[0]
        logger.info(f"\n{'='*60}")
        logger.info(f"📝 [从文件读取 LLM 响应: {response_file}]")
        logger.info(f"{'='*60}")
        
        try:
            with open(response_file, 'r', encoding='utf-8') as f:
                response = f.read()
            
            # 删除已使用的文件
            response_file.unlink()
            logger.info(f"✅ 读取响应成功，长度：{len(response)} 字符")
            logger.info(f"   已删除文件：{response_file}")
            return response
        except Exception as e:
            logger.error(f"❌ 读取响应文件失败: {e}")
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
                        import time
                        call_start = time.time()

                        response = self.openai_client.chat.completions.create(
                            model=current_model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=self.temperature
                        )

                        # 🔑 计算响应时间
                        elapsed = time.time() - call_start

                        # 🔑 反馈给模型池管理器（成功）
                        if self.model_pool_manager:
                            self.model_pool_manager.record_request_result(
                                current_model, success=True, response_time=elapsed
                            )

                        return response.choices[0].message.content

                    except Exception as e:
                        error_str = str(e)
                        error_type = type(e).__name__

                        # 🔑 反馈给模型池管理器（失败）
                        if self.model_pool_manager:
                            self.model_pool_manager.record_request_result(
                                current_model, success=False
                            )

                        # 🔑 新增：超时异常处理
                        if 'timeout' in error_type.lower() or 'timeout' in error_str.lower():
                            logger.error(f"❌ API调用超时（模型：{current_model}）")
                            if self.switch_to_next_model(f"超时: {current_model}"):
                                continue  # 使用下一个模型重试
                            else:
                                return None

                        # 🔑 检测额度耗尽
                        if self._is_quota_exhausted(error_str):
                            # 模型池关闭时，不要切换模型，直接抛出异常让调用方重试
                            if not self.model_pool_manager:
                                raise
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
                            if not self.model_pool_manager:
                                raise
                            self.failed_models.add(current_model)
                            current_model_switches += 1
                            logger.warning(f"⚠️ 模型 {current_model} 调用失败: {error_str[:50]}")
                            if self.switch_to_next_model(f"调用失败"):
                                continue
                            else:
                                break

                        # 🔑 新增：限流智能等待（解析Retry-After）
                        elif '429' in error_str or 'rate limit' in error_str.lower() or 'throttling' in error_str.lower():
                            import re
                            import time

                            # 尝试从错误消息中提取等待时间
                            wait_seconds = 5  # 默认等待5秒

                            # 策略1: 解析 Retry-After 响应头
                            retry_after_match = re.search(r'retry.?after[:\s]+(\d+)', error_str, re.IGNORECASE)
                            if retry_after_match:
                                wait_seconds = int(retry_after_match.group(1))
                                logger.info(f"   🕐 解析到Retry-After: {wait_seconds}秒")
                            else:
                                # 策略2: 从错误消息中提取秒数
                                seconds_match = re.search(r'wait[:\s]+(\d+)', error_str, re.IGNORECASE)
                                if seconds_match:
                                    wait_seconds = int(seconds_match.group(1))
                                    logger.info(f"   🕐 从错误消息提取等待时间: {wait_seconds}秒")

                            # 策略3: 指数退避（基于连续限流次数）
                            if not hasattr(self, '_rate_limit_count'):
                                self._rate_limit_count = 0
                            self._rate_limit_count += 1
                            if self._rate_limit_count > 1:
                                wait_seconds = min(wait_seconds * (2 ** (self._rate_limit_count - 1)), 300)  # 最多等待5分钟
                                logger.info(f"   📈 指数退避（第{self._rate_limit_count}次限流）: {wait_seconds}秒")

                            logger.warning(f"   ⏸️  限流等待 {wait_seconds}秒...")
                            time.sleep(wait_seconds)

                            # 重置限流计数（如果成功等待）
                            self._rate_limit_count = 0

                            if self.switch_to_next_model(f"限流"):
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

                # 无可用客户端时直接失败，不再回退到文件型本地模式
                else:
                    logger.error("❌ 未配置可用的远程 LLM 客户端")
                    return None

            # 检查是否成功切换到新源
            if self.multi_source_manager and self.multi_source_manager.current_source:
                current_source = self.multi_source_manager.get_current_source()
                if current_source and not current_source.is_exhausted:
                    continue  # 使用新源继续
            else:
                break  # 无可用源，退出

        logger.error("❌ 所有远程资源不可用，终止本次调用")
        return None

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

    def _call_llm_with_schema(
        self,
        messages: List[Dict],
        schema: Dict,
        max_tokens: int = None
    ) -> Dict:
        """
        强制 JSON Schema 输出（Phase 4）

        使用 OpenAI response_format 强制 LLM 输出符合 schema 的 JSON。
        消除解析错误和重试循环。

        Args:
            messages: 消息列表
            schema: JSON Schema 字典
            max_tokens: 最大输出 token 数

        Returns:
            Dict: 解析后的 JSON 对象
        """
        max_tokens = max_tokens or self.max_tokens

        if not self.openai_client:
            raise ValueError("OpenAI 客户端未初始化，无法使用 JSON Schema 模式")

        try:
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=self.temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "BookGraph",
                        "schema": schema,
                        "strict": True
                    }
                }
            )

            # 直接解析 JSON
            import json
            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            logger.error(f"❌ JSON Schema 模式失败: {str(e)[:100]}")
            # 回退到普通模式
            logger.warning("⚠️ 回退到普通模式，使用 parse_model_output 解析")
            response = self._call_llm(messages, max_tokens)
            if response:
                result, success, error = parse_model_output(response)
                if success:
                    return result
            raise

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
            logger.warning(f"⚠️ JSON 解析失败：{e}")
            return {"raw_response": response}

    def _normalize_book_graph_data(self, data: Dict, metadata: Dict) -> Dict:
        """
        规范化 BookGraph 数据，处理 LLM 返回的不规范格式

        🔑 核心修复：补齐结构字段，但不制造占位符内容

        Args:
            data: LLM 返回的原始数据
            metadata: 书籍元数据

        Returns:
            Dict: 规范化后的数据
        """
        # ═══════════════════════════════════════════════════════════
        # 🔑 Step 0: 占位符检测与清理
        # ═══════════════════════════════════════════════════════════

        PLACEHOLDER_PATTERNS = [
            "待补充", "待分析", "待填写", "待完善", "待完成",
            "TBD", "TODO", "FIXME", "N/A", "暂无",
            "需要补充", "需要分析", "略", "无",
            "（待补充）", "（待分析）", "（略）"
        ]

        def is_placeholder(text: str) -> bool:
            """检测文本是否为占位符"""
            if not isinstance(text, str):
                return False
            text_stripped = text.strip()
            # 精确匹配占位符模式
            for pattern in PLACEHOLDER_PATTERNS:
                if text_stripped == pattern or text_stripped == f"（{pattern}）":
                    return True
            # 检测以占位符开头的文本
            for pattern in PLACEHOLDER_PATTERNS:
                if text_stripped.startswith(pattern) and len(text_stripped) < len(pattern) + 10:
                    return True
            return False

        def clean_placeholder(obj):
            """递归清理占位符（替换为空字符串或空数组）"""
            if isinstance(obj, dict):
                return {k: clean_placeholder(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                # 过滤掉纯占位符元素
                return [clean_placeholder(item) for item in obj if not is_placeholder(item)]
            elif isinstance(obj, str):
                return "" if is_placeholder(obj) else obj
            else:
                return obj

        # 清理占位符
        data = clean_placeholder(data)

        # ═══════════════════════════════════════════════════════════
        # 🔑 Step 1: 确保顶层结构存在
        # ═══════════════════════════════════════════════════════════

        if not data:
            data = {}

        # 确保 metadata 存在且填充必填字段
        if 'metadata' not in data:
            data['metadata'] = {}

        meta = data['metadata']

        # 🔑 必填字段默认值填充：只补结构，不制造“待补充”内容
        meta.setdefault('title', metadata.get('title', 'Unknown'))
        meta.setdefault('author', metadata.get('author', 'Unknown'))
        meta.setdefault('author_intro', metadata.get('author_intro', ''))
        meta.setdefault('discipline', metadata.get('discipline', '哲学'))

        # 处理 metadata 中的 tuple
        if isinstance(meta.get('title'), (tuple, list)):
            meta['title'] = str(meta['title'][0]) if meta['title'] else 'Unknown'
        if isinstance(meta.get('author'), (tuple, list)):
            meta['author'] = str(meta['author'][0]) if meta['author'] else 'Unknown'

        # 确保 time_background 存在且填充必填字段
        if 'time_background' not in data:
            data['time_background'] = {}

        tb = data['time_background']
        tb.setdefault('macro_background', '')
        tb.setdefault('micro_background', '')
        tb.setdefault('core_contradiction', '')

        # 确保 critical_analysis 存在且填充必填字段
        if 'critical_analysis' not in data:
            data['critical_analysis'] = {}

        ca = data['critical_analysis']
        ca.setdefault('feminist_perspective', '')
        ca.setdefault('postcolonial_perspective', '')
        ca.setdefault('core_doubts', [])
        ca.setdefault('ethical_boundaries', {})

        # ═══════════════════════════════════════════════════════════
        # 🔑 Step 2: 处理数组字段（确保都是数组）
        # ═══════════════════════════════════════════════════════════

        array_fields = ['chapters', 'core_concepts', 'key_insights', 'key_cases', 'key_quotes']

        for field in array_fields:
            if field not in data:
                data[field] = []
            elif not isinstance(data[field], list):
                data[field] = []

        # ═══════════════════════════════════════════════════════════
        # 🔑 Step 3: 处理嵌套结构中的不规范格式
        # ═══════════════════════════════════════════════════════════

        # 处理 core_drivers（应该是数组，LLM 可能返回字符串）
        for section in ['core_concepts', 'key_cases']:
            if section in data and isinstance(data[section], list):
                for item in data[section]:
                    if isinstance(item, dict):
                        if 'core_drivers' in item and isinstance(item['core_drivers'], str):
                            # 将逗号分隔的字符串转为数组
                            item['core_drivers'] = [s.strip() for s in item['core_drivers'].replace(',', ',').split('、') if s.strip()]
                        # 确保其他必填字段存在，但不填入伪内容
                        item.setdefault('name', item.get('name', ''))
                        item.setdefault('definition', item.get('definition', ''))

        # 处理 multi_perspectives（应该是对象，LLM 可能返回字符串）
        if 'key_insights' in data and isinstance(data['key_insights'], list):
            for item in data['key_insights']:
                if isinstance(item, dict):
                    if 'multi_perspectives' in item and isinstance(item['multi_perspectives'], str):
                        # 将字符串转为对象
                        item['multi_perspectives'] = {"其他视角": item['multi_perspectives']}
                    item.setdefault('multi_perspectives', {})
                    # 确保其他必填字段存在，但不填入伪内容
                    item.setdefault('title', item.get('title', ''))
                    item.setdefault('description', item.get('description', ''))
                    item.setdefault('underlying_logic', item.get('underlying_logic', ''))
                    item.setdefault('controversies', item.get('controversies', ''))

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
                    if isinstance(item, dict) and 'development_stages' in item:
                        if isinstance(item['development_stages'], list):
                            for i, stage in enumerate(item['development_stages']):
                                if isinstance(stage, str):
                                    item['development_stages'][i] = {"name": stage, "description": ""}
                        elif isinstance(item['development_stages'], str):
                            item['development_stages'] = [{"name": item['development_stages'], "description": ""}]

        # 🔑 Step 4: 补齐嵌套模型必填字段（LLM 经常遗漏），但不制造伪内容
        nested_defaults = {
            'core_concepts': {
                'name': '', 'definition': '', 'deep_meaning': '',
                'underlying_logic': '', 'critical_review': '',
            },
            'key_insights': {
                'title': '', 'description': '', 'underlying_logic': '',
                'controversies': '',
            },
            'key_cases': {
                'name': '', 'source_chapter': '', 'event_description': '',
                'historical_limitations': '',
            },
            'key_quotes': {
                'text': '', 'chapter': '', 'core_theme': '',
                'background_context': '', 'underlying_logic': '',
            },
        }
        for section, defaults in nested_defaults.items():
            if section in data and isinstance(data[section], list):
                for i, item in enumerate(data[section]):
                    if isinstance(item, str):
                        # 字符串 → dict 转换（使用字符串作为标题/名称）
                        data[section][i] = {**defaults, 'title': item, 'name': item, 'text': item}
                    elif isinstance(item, dict):
                        for field, default in defaults.items():
                            item.setdefault(field, default)

        # 确保 critical_analysis 子字段存在
        if 'critical_analysis' in data and isinstance(data['critical_analysis'], dict):
            ca = data['critical_analysis']
            ca.setdefault('feminist_perspective', '')
            ca.setdefault('postcolonial_perspective', '')

        # 处理 learning_path（应该是对象，各字段为数组，LLM 可能返回字符串）
        if 'learning_path' not in data:
            data['learning_path'] = {}

        lp = data['learning_path']
        for key in ['beginner', 'intermediate', 'advanced', 'practice']:
            if key not in lp:
                lp[key] = []
            elif isinstance(lp[key], str):
                lp[key] = [lp[key]]

        # 确保 book_network 存在
        if 'book_network' not in data:
            data['book_network'] = {}

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
            logger.warning(f"⚠️ BookGraph 合成失败：{e}")

            # 🔑 新增：部分构造策略 - 保留有效数据而非返回空BookGraph
            from schemas.book_graph_schema import (
                BookMetadata, TimeBackground, CriticalAnalysis
            )

            # 尝试提取并构造metadata
            try:
                meta_data = data.get('metadata', {}) if 'data' in locals() else {}
                metadata_obj = BookMetadata(
                    title=meta_data.get('title', metadata.get('title', 'Unknown')),
                    author=meta_data.get('author', metadata.get('author', 'Unknown')),
                    author_intro=meta_data.get('author_intro', metadata.get('author_intro', '')),
                    discipline=meta_data.get('discipline', metadata.get('discipline', DisciplineType.哲学)),
                )
            except Exception as meta_error:
                logger.warning(f"   ⚠️ metadata构造失败: {meta_error}")
                metadata_obj = BookMetadata(
                    title=metadata.get('title', 'Unknown'),
                    author=metadata.get('author', 'Unknown'),
                    author_intro=metadata.get('author_intro', ''),
                    discipline=metadata.get('discipline', DisciplineType.哲学),
                )

            # 尝试提取并构造time_background
            try:
                tb_data = data.get('time_background', {}) if 'data' in locals() else {}
                time_background_obj = TimeBackground(
                    macro_background=tb_data.get('macro_background', ''),
                    micro_background=tb_data.get('micro_background', ''),
                    core_contradiction=tb_data.get('core_contradiction', ''),
                )
            except Exception as tb_error:
                logger.warning(f"   ⚠️ time_background构造失败: {tb_error}")
                time_background_obj = TimeBackground(
                    macro_background="",
                    micro_background="",
                    core_contradiction="",
                )

            # 尝试提取并构造critical_analysis
            try:
                ca_data = data.get('critical_analysis', {}) if 'data' in locals() else {}
                critical_analysis_obj = CriticalAnalysis(
                    feminist_perspective=ca_data.get('feminist_perspective', ''),
                    postcolonial_perspective=ca_data.get('postcolonial_perspective', ''),
                    ethical_boundaries=ca_data.get('ethical_boundaries', {}),
                    core_doubts=ca_data.get('core_doubts', []),
                )
            except Exception as ca_error:
                logger.warning(f"   ⚠️ critical_analysis构造失败: {ca_error}")
                critical_analysis_obj = CriticalAnalysis(
                    feminist_perspective="",
                    postcolonial_perspective="",
                    ethical_boundaries={},
                )

            # 🔑 关键：保留所有数组数据（即使不完整）
            logger.info("   📦 部分构造BookGraph，保留有效数据")
            return BookGraph(
                metadata=metadata_obj,
                time_background=time_background_obj,
                critical_analysis=critical_analysis_obj,
                chapters=data.get('chapters', []) if 'data' in locals() else [],
                core_concepts=data.get('core_concepts', []) if 'data' in locals() else [],
                key_insights=data.get('key_insights', []) if 'data' in locals() else [],
                key_cases=data.get('key_cases', []) if 'data' in locals() else [],
                key_quotes=data.get('key_quotes', []) if 'data' in locals() else [],
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
            logger.warning(f"⚠️ 无法识别学科 '{discipline_name}'，使用默认值：哲学")
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


# ═══════════════════════════════════════════════════════════
# Phase 3: 异步 LLM 客户端
# ═══════════════════════════════════════════════════════════

class AsyncLLMClient(LLMClient):
    """
    异步 LLM 客户端

    使用原生 AsyncOpenAI/AsyncAnthropic，消除 asyncio.to_thread 包装开销。
    配合 AsyncChunkProcessor 实现真正的并发处理。

    用法：
        async_client = AsyncLLMClient(config)
        response = await async_client._call_llm_async(messages)
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)

        # 异步客户端
        self.async_openai_client = None
        self.async_anthropic_client = None

        self._init_async_client()

    def _init_async_client(self):
        """初始化异步客户端"""
        # 初始化父类同步客户端（保留回退）
        # super() 已经调用了 _init_client()

        # 初始化异步客户端
        if ASYNC_OPENAI_AVAILABLE and self.openai_client:
            try:
                self.async_openai_client = AsyncOpenAI(
                    api_key=self.config.get('api_key', 'unused'),
                    base_url=self.config.get('api_base', 'https://api.openai.com/v1'),
                    timeout=self.config.get('timeout', 240),
                )
                logger.info("✅ AsyncOpenAI 客户端初始化成功")
            except Exception as e:
                logger.warning(f"⚠️ AsyncOpenAI 初始化失败: {e}")

        if ASYNC_ANTHROPIC_AVAILABLE and self.anthropic_client:
            try:
                self.async_anthropic_client = AsyncAnthropic(
                    api_key=os.environ.get('ANTHROPIC_API_KEY', ''),
                    base_url=os.environ.get('ANTHROPIC_BASE_URL', ''),
                )
                logger.info("✅ AsyncAnthropic 客户端初始化成功")
            except Exception as e:
                logger.warning(f"⚠️ AsyncAnthropic 初始化失败: {e}")

    async def _call_llm_async(self, messages: List[Dict], max_tokens: int = None) -> str:
        """
        异步调用 LLM（增强错误处理和断路器）

        Args:
            messages: 消息列表
            max_tokens: 最大输出 token 数

        Returns:
            str: LLM 响应文本
        """
        max_tokens = max_tokens or self.max_tokens

        # 🔑 成功后重置失败计数器
        if hasattr(self, '_consecutive_failures') and self._consecutive_failures > 0:
            self._consecutive_failures = 0

        # 优先使用 AsyncOpenAI
        if self.async_openai_client:
            try:
                import time
                call_start = time.time()

                response = await self.async_openai_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self.temperature
                )

                elapsed = time.time() - call_start

                # 反馈给模型池管理器
                if self.model_pool_manager:
                    self.model_pool_manager.record_request_result(
                        self.model, success=True, response_time=elapsed
                    )

                return response.choices[0].message.content

            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__

                # 🔑 增强错误日志
                logger.error(f"❌ AsyncOpenAI 调用失败")
                logger.error(f"   错误类型: {error_type}")
                logger.error(f"   错误信息: {error_str[:200]}")
                logger.error(f"   模型: {self.model}")
                logger.error(f"   API Base: {self.api_base}")

                # 反馈给模型池管理器
                if self.model_pool_manager:
                    self.model_pool_manager.record_request_result(
                        self.model, success=False
                    )

                # 🔑 断路器：连续失败检查
                if not hasattr(self, '_consecutive_failures'):
                    self._consecutive_failures = 0

                self._consecutive_failures += 1

                if self._consecutive_failures >= 3:
                    logger.warning(f"⚠️  连续失败 {self._consecutive_failures} 次，暂停 60 秒...")
                    time.sleep(60)
                    self._consecutive_failures = 0  # 重置计数器

                # 额度耗尽：切换模型
                if self._is_quota_exhausted(error_str):
                    if self.switch_to_next_model(f"额度耗尽: {self.model}"):
                        logger.info(f"🔄 切换到备选模型: {self.model}")
                        # 递归重试（已切换模型）
                        return await self._call_llm_async(messages, max_tokens)

                # 回退到同步调用
                logger.info("⬇️  回退到同步调用")
                return self._call_llm(messages, max_tokens)

        # 回退到 AsyncAnthropic
        elif self.async_anthropic_client:
            try:
                system_content = ""
                user_messages = []

                for msg in messages:
                    if msg['role'] == 'system':
                        system_content = msg['content']
                    else:
                        user_messages.append(msg)

                # 🔑 Prompt Caching（Phase 5）
                system_blocks = [
                    {
                        "type": "text",
                        "text": system_content,
                        "cache_control": {"type": "ephemeral"}
                    }
                ] if system_content else None

                response = await self.async_anthropic_client.messages.create(
                    model=self.model,
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
                logger.error(f"❌ AsyncAnthropic 调用失败: {str(e)[:100]}")
                # 回退到同步调用
                return self._call_llm(messages, max_tokens)

        # 无异步客户端：回退到同步
        else:
            return self._call_llm(messages, max_tokens)


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_async_llm_client: Optional[AsyncLLMClient] = None


def get_async_llm_client(config: Dict) -> AsyncLLMClient:
    """获取全局异步 LLM 客户端单例"""
    global _async_llm_client
    if _async_llm_client is None:
        _async_llm_client = AsyncLLMClient(config)
    return _async_llm_client
