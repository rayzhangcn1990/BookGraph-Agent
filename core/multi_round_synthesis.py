"""
拆分 synthesis 为多轮低复杂度任务

根因：minimax 处理完整 BookGraph（34章节）复杂度太高，输出偷懒
方案：拆成 5 轮，每轮输出 <2KB，降低单次任务复杂度
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("BookGraph-Agent")

# ═══════════════════════════════════════════════════════════════════════
# 多轮 Synthesis Prompt 模板
# ═══════════════════════════════════════════════════════════════════════

SYNTHESIS_ROUND_1_PROMPT = """请分析书籍内容，生成书籍元数据和时代背景。

【书籍信息】
书名：{book_title}
作者：{author}

【内容摘要】
{content_summary}

【输出要求】
输出 JSON 格式，包含以下字段（必须用英文字段名）：
{{
  "metadata": {{
    "title": "书名",
    "author": "作者",
    "author_intro": "作者简介（≥100字符）",
    "year_published": "出版年份或 null",
    "category": ["分类标签"],
    "discipline": "一级学科（政治学/经济学/心理学/历史学/哲学/管理学/社会学/文学/科学/技术）",
    "sub_discipline": "二级学科或 null",
    "tags": ["关键词"],
    "related_books": ["关联书籍"]
  }},
  "time_background": {{
    "macro_background": "宏观时代背景",
    "micro_background": "微观写作背景",
    "core_contradiction": "核心矛盾"
  }}
}}

【约束】
- 禁止 JSON 注释（//）
- 禁止占位符（"书中未涉及"、"N/A"、"待分析"）
- 必须输出纯 JSON，无 Markdown 代码块
"""

SYNTHESIS_ROUND_2_PROMPT = """请生成书籍章节摘要（第1-10章）。

【书籍信息】
书名：{book_title}

【章节列表（第1-10章）】
{chapters_list}

【输出要求】
输出 JSON 格式，包含以下字段：
{{
  "chapters": [
    {{
      "chapter_number": "1",
      "title": "章节标题",
      "core_argument": "核心论点（≥50字符）",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "related_books": ["关联书籍"],
      "critical_questions": ["批判性问题"]
    }},
    ...（第1-10章，每章必须独立输出）
  ]
}}

【约束】
- 禁止 JSON 注释（//）
- 禁止合并章节（"1-10"、"第1-10章"）
- 禁止占位符（"书中未涉及"、"N/A"）
- 必须输出纯 JSON
"""

SYNTHESIS_ROUND_3_PROMPT = """请生成书籍章节摘要（第11-20章）。

【书籍信息】
书名：{book_title}

【章节列表（第11-20章）】
{chapters_list}

【输出要求】
输出 JSON 格式，包含以下字段：
{{
  "chapters": [
    {{
      "chapter_number": "11",
      "title": "章节标题",
      "core_argument": "核心论点（≥50字符）",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "related_books": ["关联书籍"],
      "critical_questions": ["批判性问题"]
    }},
    ...（第11-20章，每章必须独立输出）
  ]
}}

【约束】
- 禁止 JSON 注释（//）
- 禁止合并章节
- 禁止占位符
- 必须输出纯 JSON
"""

SYNTHESIS_ROUND_4_PROMPT = """请生成书籍章节摘要（第21章之后）和核心概念。

【书籍信息】
书名：{book_title}

【章节列表（第21章之后）】
{chapters_list}

【输出要求】
输出 JSON 格式，包含以下字段：
{{
  "chapters": [
    {{
      "chapter_number": "21",
      "title": "章节标题",
      "core_argument": "核心论点",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "related_books": [],
      "critical_questions": []
    }},
    ...（第21章之后所有章节）
  ],
  "core_concepts": [
    {{
      "name": "概念名称",
      "definition": "定义（≥100字符）",
      "deep_meaning": "深层含义",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "development_stages": [{{"name": "阶段名", "period": "时期", "characteristics": "特点", "evolution_reason": "演化原因"}}],
      "core_drivers": ["驱动因素"],
      "critical_review": "批判性审视",
      "related_books": ["关联书籍"]
    }},
    ...（≥3个核心概念）
  ]
}}

【约束】
- 禁止 JSON 注释
- 禁止合并章节
- 禁止占位符
- 必须输出纯 JSON
"""

SYNTHESIS_ROUND_5_PROMPT = """请生成书籍关键洞见、案例、金句和批判性分析。

【书籍信息】
书名：{book_title}

【内容摘要】
{content_summary}

【输出要求】
输出 JSON 格式，包含以下字段：
{{
  "key_insights": [
    {{
      "title": "洞见标题",
      "description": "描述（≥100字符）",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "deep_assumptions": ["假设"],
      "related_books": [],
      "controversies": "争议",
      "multi_perspectives": {{\"视角名\": \"解读\"}}
    }},
    ...（≥2个洞见）
  ],
  "key_cases": [
    {{
      "name": "案例名称",
      "source_chapter": "来源章节",
      "event_description": "事件描述",
      "development_stages": [{{"name": "阶段", "description": "描述"}}],
      "core_drivers": ["驱动因素"],
      "related_books": [],
      "historical_limitations": "历史局限"
    }},
    ...（≥2个案例）
  ],
  "key_quotes": [
    {{
      "text": "原文金句",
      "chapter": "来源章节",
      "core_theme": "核心主题",
      "background_context": "时代背景",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "common_misreading": "常见误读或 null",
      "related_books": []
    }},
    ...（≥3个金句）
  ],
  "critical_analysis": {{
    "core_doubts": [{{"question": "问题", "analysis": "分析"}}],
    "feminist_perspective": "女性主义视角",
    "postcolonial_perspective": "后殖民视角",
    "ethical_boundaries": {{\"reasonable\": \"合理边界\", \"dangerous\": \"危险边界\", \"institutional_safeguards\": \"制度保障\"}}
  }},
  "learning_path": {{
    "beginner": ["入门建议"],
    "intermediate": ["进阶建议"],
    "advanced": ["高阶建议"],
    "practice": ["实践建议"]
  }},
  "book_network": {{\"书名\": \"关联维度\"}}
}}

【约束】
- 禁止 JSON 注释
- 禁止占位符
- 必须输出纯 JSON
"""


# ═══════════════════════════════════════════════════════════════════════
# 多轮 Synthesis 执行器
# ═══════════════════════════════════════════════════════════════════════

def _format_quality_feedback(retry_feedback: str) -> str:
    """将质量门报告压缩为可注入提示词的定向修复要求。"""
    if not retry_feedback:
        return ""

    issue_lines = [
        line.strip("- ❌⚠️ ")
        for line in retry_feedback.splitlines()
        if line.strip().startswith(("- ❌", "- ⚠️"))
    ]
    if not issue_lines:
        return ""

    return "\n".join([
        "【上一次质量门失败，请定向修复以下问题】",
        *[f"- {line}" for line in issue_lines[:12]],
        "【修复要求】",
        "- 只输出真实、具体、有证据的内容，禁止空字段、占位符和模板句。",
        "- 若问题指向学习路径、关联书籍网络、伦理边界、案例、金句或洞见，必须优先补齐这些部分。",
        "- 章节必须逐章独立输出，禁止合并编号或省略中间章节。",
    ])


async def synthesize_multi_round(
    llm_client,
    chunk_results: List[Dict],
    book_title: str,
    author: str,
    discipline: str,
    expected_chapters: int = 0,
    retry_feedback: str = ""
) -> Dict:
    """
    多轮综合分析

    拆分 synthesis 为 5 轮低复杂度任务，避免 LLM 输出偷懒
    """

    # 提取章节列表
    chapters_json = []
    for chunk in chunk_results:
        if "chapter_summaries" in chunk:
            for ch in chunk["chapter_summaries"]:
                chapters_json.append(ch)

    chapter_count = len(chapters_json)
    logger.info(f"   📖 提取章节: {chapter_count} 个")

    # 内容摘要（用于 Round 1, 5）
    content_summary = json.dumps(chunk_results[:5], ensure_ascii=False)[:3000]  # 只取前5个chunk
    quality_feedback = _format_quality_feedback(retry_feedback)
    if quality_feedback:
        content_summary = f"{content_summary}\n\n{quality_feedback}"

    # ═════════════════════════════════════════════════════════════════
    # Round 1: metadata + time_background
    # ═════════════════════════════════════════════════════════════════
    logger.info("   🔄 Round 1: metadata + time_background")

    prompt_1 = SYNTHESIS_ROUND_1_PROMPT.format(
        book_title=book_title,
        author=author,
        content_summary=content_summary
    )

    # 🔑 修复：使用正确的 field_type
    result_1 = await _call_llm_round(llm_client, prompt_1, "round_1", field_type="synthesis_round_1")

    if not result_1:
        logger.error("   ❌ Round 1 失败")
        return None

    # 🔑 新增：Round 1 成功后等待（避免速率限制）
    await asyncio.sleep(60)  # 等待 60 秒

    # ═════════════════════════════════════════════════════════════════
    # Round 2: chapters[:10]
    # ═════════════════════════════════════════════════════════════════
    logger.info("   🔄 Round 2: chapters[:10]")

    chapters_1_10 = json.dumps(chapters_json[:10], ensure_ascii=False)[:2000]
    if quality_feedback:
        chapters_1_10 = f"{chapters_1_10}\n\n{quality_feedback}"

    prompt_2 = SYNTHESIS_ROUND_2_PROMPT.format(
        book_title=book_title,
        chapters_list=chapters_1_10
    )

    # 🔑 修复：使用正确的 field_type
    result_2 = await _call_llm_round(llm_client, prompt_2, "round_2", field_type="synthesis_round_2")

    if not result_2:
        logger.error("   ❌ Round 2 失败")
        return None

    # 🔑 新增：Round 2 成功后等待
    await asyncio.sleep(60)

    # ═════════════════════════════════════════════════════════════════
    # Round 3: chapters[10:20]
    # ═════════════════════════════════════════════════════════════════
    logger.info("   🔄 Round 3: chapters[10:20]")

    chapters_11_20 = json.dumps(chapters_json[10:20], ensure_ascii=False)[:2000] if len(chapters_json) > 10 else "[]"
    if quality_feedback:
        chapters_11_20 = f"{chapters_11_20}\n\n{quality_feedback}"

    prompt_3 = SYNTHESIS_ROUND_3_PROMPT.format(
        book_title=book_title,
        chapters_list=chapters_11_20
    )

    # 🔑 修复：使用正确的 field_type（Round 3 只在章节数>10时执行）
    result_3 = await _call_llm_round(llm_client, prompt_3, "round_3", field_type="synthesis_round_3") if len(chapters_json) > 10 else {"chapters": []}

    # 🔑 新增：Round 3 成功后等待
    if result_3:
        await asyncio.sleep(60)

    # ═════════════════════════════════════════════════════════════════
    # Round 4: chapters[20:] + core_concepts
    # ═════════════════════════════════════════════════════════════════
    logger.info("   🔄 Round 4: chapters[20:] + core_concepts")

    chapters_20_plus = json.dumps(chapters_json[20:], ensure_ascii=False)[:2000] if len(chapters_json) > 20 else "[]"
    if quality_feedback:
        chapters_20_plus = f"{chapters_20_plus}\n\n{quality_feedback}"

    prompt_4 = SYNTHESIS_ROUND_4_PROMPT.format(
        book_title=book_title,
        chapters_list=chapters_20_plus
    )

    # Round 4 始终执行：即使少于 21 章，也需要生成核心概念
    result_4 = await _call_llm_round(llm_client, prompt_4, "round_4", field_type="synthesis_round_4")

    # 🔑 新增：Round 4 成功后等待
    if result_4:
        await asyncio.sleep(60)

    # ═════════════════════════════════════════════════════════════════
    # Round 5: key_insights + key_cases + key_quotes + critical_analysis
    # ═════════════════════════════════════════════════════════════════
    logger.info("   🔄 Round 5: insights + cases + quotes + critical")

    prompt_5 = SYNTHESIS_ROUND_5_PROMPT.format(
        book_title=book_title,
        content_summary=content_summary
    )

    # 🔑 修复：使用正确的 field_type
    result_5 = await _call_llm_round(llm_client, prompt_5, "round_5", field_type="synthesis_round_5")

    if not result_5:
        logger.error("   ❌ Round 5 失败")
        return None

    # ═════════════════════════════════════════════════════════════════
    # 合并结果
    # ═════════════════════════════════════════════════════════════════
    logger.info("   🔄 合并多轮结果")

    final_result = {}

    # Round 1
    if "metadata" in result_1:
        final_result["metadata"] = result_1["metadata"]
    if "time_background" in result_1:
        final_result["time_background"] = result_1["time_background"]

    # Round 2-4: 合并 chapters
    all_chapters = []
    if "chapters" in result_2:
        all_chapters.extend(result_2["chapters"])
    if result_3 and "chapters" in result_3:
        all_chapters.extend(result_3["chapters"])
    if len(chapters_json) > 20 and result_4 and "chapters" in result_4:
        all_chapters.extend(result_4["chapters"])

    final_result["chapters"] = all_chapters

    # Round 4: core_concepts
    if result_4 and "core_concepts" in result_4:
        final_result["core_concepts"] = result_4["core_concepts"]

    # Round 5
    if result_5:
        for field in ["key_insights", "key_cases", "key_quotes", "critical_analysis", "learning_path", "book_network"]:
            if field in result_5:
                final_result[field] = result_5[field]

    # 统计
    logger.info(f"   ✅ 合并完成:")
    logger.info(f"      chapters: {len(final_result.get('chapters', []))}")
    logger.info(f"      core_concepts: {len(final_result.get('core_concepts', []))}")
    logger.info(f"      key_insights: {len(final_result.get('key_insights', []))}")
    logger.info(f"      key_quotes: {len(final_result.get('key_quotes', []))}")

    return final_result


async def _call_llm_round(llm_client, prompt: str, round_name: str, field_type: str = "synthesis", max_retries: int = 3) -> Optional[Dict]:
    """
    执行单轮 LLM 调用（增强版：支持重试和长等待）

    Args:
        llm_client: LLM 客户端
        prompt: 提示词
        round_name: 轮次名称（用于日志）
        field_type: 字段类型（用于验证，默认 synthesis）
        max_retries: 最大重试次数（默认 3）
    """
    from core.model_output_format_spec import parse_model_output

    messages = [{"role": "user", "content": prompt}]

    for retry in range(max_retries):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    llm_client._call_llm,
                    messages,
                    max_tokens=4096
                ),
                timeout=300
            )

            if response:
                result, success, error_msg = parse_model_output(response, field_type=field_type)

                if not success:
                    logger.warning(f"      ⚠️ {round_name} 解析失败: {error_msg}")
                    debug_path = Path(f"/tmp/{round_name}_failed.txt")
                    with open(debug_path, 'w') as f:
                        f.write(f"# {round_name}\n# Error: {error_msg}\n\n{response}")
                    logger.warning(f"      ⚠️ 响应已保存: {debug_path}")

                    # 🔑 解析失败也重试
                    if retry < max_retries - 1:
                        wait_time = 60 * (retry + 1)  # 60秒, 120秒, 180秒
                        logger.warning(f"      ⚠️ 等待 {wait_time}秒后重试...")
                        await asyncio.sleep(wait_time)
                        continue
                    return None

                logger.info(f"      ✅ {round_name} 成功")
                return result

        except asyncio.TimeoutError:
            logger.warning(f"      ⚠️ {round_name} 超时 (retry {retry+1}/{max_retries})")
            if retry < max_retries - 1:
                wait_time = 60 * (retry + 1)
                logger.warning(f"      ⚠️ 等待 {wait_time}秒后重试...")
                await asyncio.sleep(wait_time)
                continue

        except Exception as e:
            error_str = str(e)
            logger.warning(f"      ⚠️ {round_name} 异常: {error_str[:100]}")

            # 🔑 检测速率限制错误（429）
            if '429' in error_str or 'rate-limited' in error_str:
                wait_time = 120 * (retry + 1)  # 速率限制等待更长：120秒, 240秒
                logger.warning(f"      ⚠️ 速率限制，等待 {wait_time}秒后重试...")
                await asyncio.sleep(wait_time)
                continue

            if retry < max_retries - 1:
                wait_time = 30 * (retry + 1)
                await asyncio.sleep(wait_time)
                continue

    return None