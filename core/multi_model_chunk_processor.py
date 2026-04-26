"""
单书多模型分块并行处理器

架构：
- 一本书，多个 chunk
- 每个 chunk 分配给不同模型并行处理
- 自动模型轮换和故障切换
- 质量检查：结果质量差时切换模型重新生成

流程：
1. 解析书籍 → 分块
2. 获取可用模型池（N个模型）
3. Chunk[i] 分配给 Model[i % N]
4. 并行调用所有模型
5. 质量检查每个结果
6. 质量差的 chunk：切换模型重新生成（最多2次重试）
7. 合并结果 → 综合输出
"""

import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import json
import yaml

import httpx

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class ChunkTask:
    """分块任务"""
    chunk_index: int
    chunk_content: str
    chunk_label: str
    assigned_model: str
    status: str  # pending, running, completed, failed
    result: Optional[Dict] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class MultiModelChunkProcessor:
    """单书多模型分块并行处理器"""

    # 🔑 更新：基于完整测试的52个可用模型（高性能模型池）
    MODEL_POOL = [
        # TOP级推理模型
        "qwen/qwen3-coder-480b-a35b-instruct",
        "meta/llama-3.1-405b-instruct",
        "mistralai/mistral-large-3-675b-instruct-2512",
        "qwen/qwen3.5-397b-a17b",
        "moonshotai/kimi-k2-instruct",

        # 强推理模型
        "openai/gpt-oss-120b",
        "meta/llama-3.1-70b-instruct",
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.3-nemotron-super-49b-v1",
        "deepseek-ai/deepseek-v4-pro",

        # 备选模型
        "meta/llama-3.2-90b-vision-instruct",
        "qwen/qwen3-next-80b-a3b-instruct",
        "moonshotai/kimi-k2-thinking",
        "nvidia/nemotron-3-super-120b-a12b",
        "gpt-4o-mini",
    ]

    def __init__(self, config: Dict, max_parallel_models: int = 4):
        """
        Args:
            config: 完整配置
            max_parallel_models: 最大并行模型数
        """
        self.config = config
        self.llm_config = config.get("llm", {})
        self.max_parallel_models = max_parallel_models
        self.available_models: List[str] = []
        self.api_sources = self.llm_config.get("api_sources", [])

        # 模型质量追踪（用于剔除差模型）
        self.model_quality_tracker: Dict[str, Dict] = {}  # {model_id: {success: int, quality_fail: int, total: int}}
        self.model_blacklist: List[str] = []  # 被剔除的模型
        self.max_quality_failures = 3  # 最大质量失败次数（超过则剔除）

    async def fetch_available_models(self) -> List[str]:
        """从所有 API 源获取可用模型"""
        all_models = set()

        # 🔑 优先从本地 API 获取（无区域限制）
        for source in self.api_sources:
            api_base = source.get("api_base", "")
            api_key = source.get("api_key", "unused")

            if not api_base:
                continue

            # 优先使用本地 API
            if "localhost" not in api_base and "18765" not in api_base:
                continue  # 跳过非本地 API（有区域限制）

            headers = {"Authorization": f"Bearer {api_key}"}

            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(
                        f"{api_base.rstrip('/')}/models",
                        headers=headers
                    )

                    if response.status_code == 200:
                        data = response.json()
                        models = [m["id"] for m in data.get("data", [])]

                        # 过滤推荐模型
                        for model in models:
                            for pool_model in self.MODEL_POOL:
                                if pool_model.lower() in model.lower():
                                    all_models.add(model)
                                    break

                        logger.info(f"✅ {source['name']}: {len(models)} 个模型")
                        break  # 本地 API 成功后退出

            except Exception as e:
                logger.warning(f"⚠️ {source['name']}: {str(e)[:50]}")

        # 如果本地 API 没有模型，尝试其他源
        if not all_models:
            for source in self.api_sources:
                if "localhost" in source.get("api_base", "") or "18765" in source.get("api_base", ""):
                    continue  # 已尝试过

                api_base = source.get("api_base", "")
                api_key = source.get("api_key", "unused")

                if not api_base:
                    continue

                headers = {"Authorization": f"Bearer {api_key}"}

                if "openrouter" in source.get("name", "").lower():
                    headers["HTTP-Referer"] = "https://bookgraph.app"
                    headers["X-Title"] = "BookGraph-Agent"

                try:
                    async with httpx.AsyncClient(timeout=15) as client:
                        response = await client.get(
                            f"{api_base.rstrip('/')}/models",
                            headers=headers
                        )

                        if response.status_code == 200:
                            data = response.json()
                            models = [m["id"] for m in data.get("data", [])]

                            for model in models:
                                for pool_model in self.MODEL_POOL:
                                    if pool_model.lower() in model.lower():
                                        all_models.add(model)
                                        break

                            logger.info(f"✅ {source['name']}: {len(models)} 个模型")

                except Exception as e:
                    logger.warning(f"⚠️ {source['name']}: {str(e)[:50]}")

        self.available_models = list(all_models)
        logger.info(f"🧠 可用模型池: {len(self.available_models)} 个")

        return self.available_models

    def select_model_for_chunk(self, chunk_index: int) -> str:
        """为 chunk 选择模型（轮换分配）"""
        if not self.available_models:
            raise Exception("没有可用模型")

        # 按优先级排序模型
        priority_models = []
        for pool_model in self.MODEL_POOL:
            for available in self.available_models:
                if pool_model.lower() in available.lower():
                    priority_models.append(available)
                    break

        if not priority_models:
            priority_models = self.available_models

        # 轮换分配
        return priority_models[chunk_index % len(priority_models)]

    async def call_llm_for_chunk(
        self,
        chunk: ChunkTask,
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str
    ) -> ChunkTask:
        """使用指定模型调用 LLM 处理 chunk"""

        chunk.status = "running"
        chunk.start_time = datetime.now()

        # 构建请求
        prompt = chunk_prompt_template.format(
            book_title=book_title,
            chunk_content=chunk.chunk_content
        )

        # 找到该模型的 API 源
        api_source = self._find_source_for_model(chunk.assigned_model)

        if not api_source:
            chunk.status = "failed"
            chunk.error = f"找不到模型 {chunk.assigned_model} 的 API 源"
            chunk.end_time = datetime.now()
            return chunk

        api_base = api_source["api_base"]
        api_key = api_source["api_key"]

        # 🔑 使用 OpenAI 客户端（与 LLMClient 一致）
        from openai import OpenAI

        headers = {}
        if "openrouter" in api_source.get("name", "").lower():
            headers = {
                "HTTP-Referer": "https://bookgraph.app",
                "X-Title": "BookGraph-Agent"
            }

        try:
            client = OpenAI(
                api_key=api_key,
                base_url=api_base.rstrip('/'),
                default_headers=headers if headers else None
            )

            # 同步调用（在 async 函数中需要包装）
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=chunk.assigned_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=16384,
                temperature=0.7
            )

            content = response.choices[0].message.content

            # 解析 JSON
            try:
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = content[json_start:json_end]
                else:
                    json_str = content

                chunk.result = json.loads(json_str)
                chunk.status = "completed"
                logger.info(f"✅ [{chunk.assigned_model}] Chunk {chunk.chunk_index} 完成")

            except json.JSONDecodeError as e:
                chunk.status = "failed"
                chunk.error = f"JSON 解析失败: {str(e)[:100]}"
                logger.warning(f"⚠️ [{chunk.assigned_model}] Chunk {chunk.chunk_index}: JSON 解析失败")

        except Exception as e:
            chunk.status = "failed"
            chunk.error = str(e)[:200]
            logger.error(f"❌ [{chunk.assigned_model}] Chunk {chunk.chunk_index}: {str(e)[:100]}")

        chunk.end_time = datetime.now()
        return chunk

    def check_result_quality(self, result: Dict) -> Tuple[bool, str]:
        """
        检查结果质量

        Returns:
            Tuple[bool, str]: (是否合格, 原因)
        """
        if not result:
            return False, "结果为空"

        # 检查核心字段
        required_fields = ["chapters", "core_concepts", "key_insights"]
        missing_fields = [f for f in required_fields if f not in result]

        if missing_fields:
            return False, f"缺少必要字段: {missing_fields}"

        # 检查章节分析质量
        chapters = result.get("chapters", [])
        if not chapters:
            return False, "章节分析为空"

        # 检查是否有模板化输出（通用性描述）
        template_phrases = [
            "本章探讨了书中的核心议题",
            "作者通过逻辑推理展开论述",
            "本章分析了",
        ]

        for chapter in chapters:
            if isinstance(chapter, dict):
                core_point = chapter.get("core_point", "")
                bottom_logic = chapter.get("bottom_logic", "")

                for phrase in template_phrases:
                    if phrase in core_point or phrase in bottom_logic:
                        return False, f"章节分析过于模板化: '{phrase}'"

        # 检查核心概念质量
        concepts = result.get("core_concepts", [])
        if len(concepts) < 3:
            return False, f"核心概念太少: {len(concepts)} < 3"

        # 检查洞察质量
        insights = result.get("key_insights", [])
        if len(insights) < 2:
            return False, f"关键洞察太少: {len(insights)} < 2"

        # 检查洞察是否包含推理链
        for insight in insights:
            if isinstance(insight, str):
                if "→" not in insight and "推理" not in insight:
                    # 洞察缺少推理链，可能是模板化输出
                    pass  # 不强制要求，只是警告

        return True, "质量合格"

    async def retry_with_different_model(
        self,
        chunk: ChunkTask,
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str,
        max_retries: int = 2
    ) -> ChunkTask:
        """
        质量差时切换模型重新生成

        Args:
            chunk: 失败/质量差的 chunk
            max_retries: 最大重试次数
        """
        retries = 0
        best_result = None
        best_quality = False

        # 获取备用模型列表（排除已失败的模型）
        fallback_models = [
            m for m in self.available_models
            if m != chunk.assigned_model
        ]

        while retries < max_retries and not best_quality:
            # 选择备用模型
            if fallback_models:
                new_model = fallback_models[retries % len(fallback_models)]
            else:
                new_model = self.available_models[retries % len(self.available_models)]

            logger.info(f"🔄 Chunk {chunk.chunk_index} 重试 ({retries+1}/{max_retries}): {chunk.assigned_model} → {new_model}")

            # 创建新任务
            new_chunk = ChunkTask(
                chunk_index=chunk.chunk_index,
                chunk_content=chunk.chunk_content,
                chunk_label=chunk.chunk_label,
                assigned_model=new_model,
                status="pending"
            )

            # 调用 LLM
            result_chunk = await self.call_llm_for_chunk(
                new_chunk, book_title, system_prompt, chunk_prompt_template
            )

            if result_chunk.status == "completed" and result_chunk.result:
                # 质量检查
                quality_ok, reason = self.check_result_quality(result_chunk.result)

                if quality_ok:
                    logger.info(f"✅ Chunk {chunk.chunk_index} 重试成功: {new_model}")
                    return result_chunk
                else:
                    logger.warning(f"⚠️ Chunk {chunk.chunk_index} 重试质量仍差: {reason}")
                    if best_result is None or len(str(result_chunk.result)) > len(str(best_result)):
                        best_result = result_chunk

            retries += 1

        # 返回最佳结果（即使质量不完美）
        if best_result:
            logger.warning(f"⚠️ Chunk {chunk.chunk_index} 重试后仍不完美，使用最佳结果")
            return best_result

        # 所有重试都失败
        chunk.status = "failed"
        chunk.error = f"重试 {max_retries} 次后仍失败"
        return chunk

    def track_model_quality(self, model_id: str, is_quality_ok: bool):
        """追踪模型质量"""
        if model_id not in self.model_quality_tracker:
            self.model_quality_tracker[model_id] = {
                "success": 0,
                "quality_fail": 0,
                "total": 0
            }

        self.model_quality_tracker[model_id]["total"] += 1

        if is_quality_ok:
            self.model_quality_tracker[model_id]["success"] += 1
        else:
            self.model_quality_tracker[model_id]["quality_fail"] += 1

            # 检查是否需要剔除
            if self.model_quality_tracker[model_id]["quality_fail"] >= self.max_quality_failures:
                self.blacklist_model(model_id)

    def blacklist_model(self, model_id: str):
        """剔除质量差的模型"""
        if model_id not in self.model_blacklist:
            self.model_blacklist.append(model_id)

            # 从可用模型池移除
            if model_id in self.available_models:
                self.available_models.remove(model_id)

            logger.warning(f"🚫 模型已剔除: {model_id} (质量失败次数: {self.model_quality_tracker[model_id]['quality_fail']})")

    def get_model_quality_report(self) -> Dict:
        """获取模型质量报告"""
        return {
            "tracker": self.model_quality_tracker,
            "blacklist": self.model_blacklist,
            "summary": {
                model: {
                    "success_rate": data["success"] / data["total"] if data["total"] > 0 else 0,
                    "quality_fail_rate": data["quality_fail"] / data["total"] if data["total"] > 0 else 0,
                }
                for model, data in self.model_quality_tracker.items()
            }
        }

    def _find_source_for_model(self, model_id: str) -> Optional[Dict]:
        """找到支持指定模型的 API 源"""
        # 🔑 优先使用本地 API（localhost:18765）- 无区域限制
        for source in self.api_sources:
            if "localhost" in source.get("api_base", "") or "18765" in source.get("api_base", ""):
                return source

        # OpenRouter 支持所有模型
        for source in self.api_sources:
            name = source.get("name", "").lower()
            if "openrouter" in name and "main" in name:
                return source

        # 其他源按模型类型匹配
        model_lower = model_id.lower()

        if "gemini" in model_lower:
            for source in self.api_sources:
                if "gemini" in source.get("name", "").lower():
                    return source

        if "deepseek" in model_lower:
            for source in self.api_sources:
                if "dashscope" in source.get("name", "").lower():
                    return source

        if "nvidia" in model_lower:
            for source in self.api_sources:
                if "nvidia" in source.get("name", "").lower():
                    return source

        # 默认使用 OpenRouter
        for source in self.api_sources:
            if "openrouter" in source.get("name", "").lower():
                return source

        return self.api_sources[0] if self.api_sources else None

    async def process_book_chunks_parallel(
        self,
        chunks: List[Tuple[int, str, str]],  # (index, content, label)
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str
    ) -> List[ChunkTask]:
        """
        并行处理一本书的所有 chunks

        Args:
            chunks: 分块列表 [(index, content, label)]
            book_title: 书名
            system_prompt: 系统提示词
            chunk_prompt_template: chunk 提示词模板

        Returns:
            List[ChunkTask]: 处理结果
        """
        # 获取可用模型
        await self.fetch_available_models()

        if not self.available_models:
            raise Exception("没有可用模型")

        # 创建任务
        tasks = []
        for idx, content, label in chunks:
            model = self.select_model_for_chunk(idx)
            task = ChunkTask(
                chunk_index=idx,
                chunk_content=content,
                chunk_label=label,
                assigned_model=model,
                status="pending"
            )
            tasks.append(task)
            logger.info(f"   Chunk {idx} → {model}")

        # 并行执行（使用 semaphore 控制并发）
        semaphore = asyncio.Semaphore(self.max_parallel_models)

        async def run_task_with_semaphore(task: ChunkTask):
            async with semaphore:
                return await self.call_llm_for_chunk(
                    task, book_title, system_prompt, chunk_prompt_template
                )

        # 启动所有任务
        results = await asyncio.gather(
            *[run_task_with_semaphore(t) for t in tasks],
            return_exceptions=True
        )

        # 处理结果 + 质量检查
        final_tasks = []
        quality_failed_tasks = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tasks[i].status = "failed"
                tasks[i].error = str(result)
                quality_failed_tasks.append(tasks[i])
            elif result.status == "completed" and result.result:
                # 质量检查
                quality_ok, reason = self.check_result_quality(result.result)

                # 追踪模型质量
                self.track_model_quality(result.assigned_model, quality_ok)

                if quality_ok:
                    final_tasks.append(result)
                    logger.info(f"✅ Chunk {result.chunk_index} 质量合格 [{result.assigned_model}]")
                else:
                    logger.warning(f"⚠️ Chunk {result.chunk_index} 质量差: {reason} [{result.assigned_model}]")
                    result.status = "quality_failed"
                    result.error = reason
                    quality_failed_tasks.append(result)
            else:
                quality_failed_tasks.append(result)

        # 对质量差的 chunk 进行重试
        if quality_failed_tasks:
            logger.info(f"\n🔄 开始质量修复（{len(quality_failed_tasks)} 个 chunk）...")

            retry_results = await asyncio.gather(
                *[self.retry_with_different_model(
                    t, book_title, system_prompt, chunk_prompt_template, max_retries=2
                ) for t in quality_failed_tasks],
                return_exceptions=True
            )

            for i, retry_result in enumerate(retry_results):
                if isinstance(retry_result, Exception):
                    quality_failed_tasks[i].status = "failed"
                    quality_failed_tasks[i].error = f"重试失败: {str(retry_result)}"
                    final_tasks.append(quality_failed_tasks[i])
                else:
                    final_tasks.append(retry_result)

        return final_tasks

    def print_summary(self, tasks: List[ChunkTask]):
        """打印处理摘要"""
        completed = [t for t in tasks if t.status == "completed"]
        failed = [t for t in tasks if t.status == "failed"]

        print("\n" + "=" * 60)
        print("📊 分块并行处理摘要")
        print("=" * 60)
        print(f"✅ 完成: {len(completed)} 块")
        print(f"❌ 失败: {len(failed)} 块")

        # 模型使用统计
        model_stats = {}
        for t in tasks:
            model = t.assigned_model
            if model not in model_stats:
                model_stats[model] = {"completed": 0, "failed": 0}
            if t.status == "completed":
                model_stats[model]["completed"] += 1
            else:
                model_stats[model]["failed"] += 1

        print("\n模型使用统计:")
        for model, stats in model_stats.items():
            print(f"  {model}: 完成 {stats['completed']}, 失败 {stats['failed']}")

        # 模型质量报告
        if self.model_quality_tracker:
            print("\n模型质量报告:")
            quality_report = self.get_model_quality_report()
            for model, summary in quality_report["summary"].items():
                success_rate = summary["success_rate"]
                quality_fail_rate = summary["quality_fail_rate"]
                status = "✅" if success_rate >= 0.8 else "⚠️" if success_rate >= 0.5 else "🚫"
                print(f"  {status} {model}: 成功率 {success_rate:.0%}, 质量差率 {quality_fail_rate:.0%}")

            if self.model_blacklist:
                print(f"\n🚫 已剔除模型: {', '.join(self.model_blacklist)}")

        if failed:
            print("\n失败的 chunk:")
            for t in failed:
                print(f"  Chunk {t.chunk_index}: {t.error[:50]}")

        print("=" * 60)


async def process_book_with_multi_model_chunks(
    book_path: str,
    discipline: str,
    config: Dict,
    max_parallel_models: int = 4
) -> Dict:
    """
    使用多模型并行处理一本书的所有 chunks

    Args:
        book_path: 书籍路径
        discipline: 学科
        config: 配置
        max_parallel_models: 最大并行模型数

    Returns:
        Dict: 处理结果
    """
    from main import BookParser, SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT

    # 1. 解析书籍
    book_parser = BookParser(book_path, config.get("parsing", {}))
    parse_result = book_parser.parse()

    if not parse_result.success:
        raise Exception(f"书籍解析失败: {parse_result.error}")

    # 2. 分块
    chunks = []
    max_chunk_size = config.get("llm", {}).get("chunk_size", 30000)

    full_content = "\n\n".join([ch["content"] for ch in parse_result.chapters])

    if len(full_content) <= max_chunk_size:
        # 短书，不分块
        chunks = [(0, full_content, "完整内容")]
    else:
        # 按章节分块
        for i, chapter in enumerate(parse_result.chapters):
            content = chapter.get("content", "")
            title = chapter.get("title", f"第{i+1}章")

            if len(content) <= max_chunk_size:
                chunks.append((i, content, title))
            else:
                # 大章节分割
                for j in range(0, len(content), max_chunk_size):
                    sub_content = content[j:j+max_chunk_size]
                    chunks.append((len(chunks), sub_content, f"{title} - 部分{j//max_chunk_size+1}"))

    logger.info(f"🧩 分块完成: {len(chunks)} 块")

    # 3. 多模型并行处理
    processor = MultiModelChunkProcessor(config, max_parallel_models)

    tasks = await processor.process_book_chunks_parallel(
        chunks,
        parse_result.metadata.get("title", Path(book_path).stem),
        SYSTEM_PROMPT,
        CHUNK_ANALYSIS_PROMPT
    )

    processor.print_summary(tasks)

    # 4. 合并结果
    all_analyses = [t.result for t in tasks if t.status == "completed" and t.result]

    return {
        "book_path": book_path,
        "book_title": parse_result.metadata.get("title", Path(book_path).stem),
        "chunks_processed": len([t for t in tasks if t.status == "completed"]),
        "chunks_failed": len([t for t in tasks if t.status == "failed"]),
        "analyses": all_analyses,
        "metadata": parse_result.metadata,
    }


if __name__ == "__main__":
    # 测试
    import sys

    book = sys.argv[1] if len(sys.argv) > 1 else None
    if book:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)

        result = asyncio.run(process_book_with_multi_model_chunks(
            book, "政治学", config, max_parallel_models=4
        ))

        print(f"\n✅ 处理完成: {result['book_title']}")
        print(f"   成功: {result['chunks_processed']} 块")
        print(f"   失败: {result['chunks_failed']} 块")