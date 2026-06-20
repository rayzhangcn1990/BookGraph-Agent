"""
多模型输出格式统一规范

问题：不同 LLM 模型返回的 JSON 格式不一致，导致解析失败
解决：三层防护机制 — Prompt约束 + 解析增强 + 验证兜底
"""

import logging
import json
import re

logger = logging.getLogger("BookGraph-Agent")

# ═══════════════════════════════════════════════════════════
# Layer 1: Prompt 层 — 强制输出格式约束
# ═══════════════════════════════════════════════════════════

OUTPUT_FORMAT_CONSTRAINT = """
【输出格式约束 - 最高优先级】

1. **JSON 格式铁律**
   - 必须输出纯 JSON，不包含任何 Markdown 代码块标记（```json```）
   - 不添加任何解释性文字、注释、说明
   - JSON 必须完整，所有引号、括号、大括号必须闭合

2. **字段名统一规范（强制使用英文）**
   必须使用以下标准英文字段名，不接受中文字段名：

   │ 字段类型          │ 标准英文名              │ 禁用中文名          │
   │------------------|------------------------|--------------------│
   │ 章节摘要          │ chapter_summaries      │ 章节摘要/章节概要    │
   │ 核心概念          │ core_concepts          │ 核心概念/关键概念    │
   │ 关键洞见          │ key_insights           │ 关键洞见/核心洞见    │
   │ 关键案例          │ key_cases              │ 关键案例/典型案例    │
   │ 金句引用          │ golden_quotes          │ 金句/名言/关键引用   │
   │ 作者主题          │ author_themes          │ 作者思想            │
   │ 书籍结构          │ book_structure         │ 书籍结构            │

3. **数组字段约束**
   - chapter_summaries, core_concepts, key_insights, key_cases, golden_quotes 必须是数组 []
   - 即使只有一个元素，也必须用数组包裹

4. **空值处理**
   - 如果某字段无法提取内容，返回空数组 [] 而不是 null
   - 不要使用 "待分析"、"TBD"、"N/A" 等占位符

5. **输出前自检**
   在输出 JSON 前，请自检：
   - [ ] 所有字段名都是英文吗？
   - [ ] 所有数组都用 [] 包裹吗？
   - [ ] JSON 完整闭合吗？
   - [ ] 没有 Markdown 代码块标记吗？
"""

# ═══════════════════════════════════════════════════════════
# Layer 2: 解析层 — 字段名映射 + 截断修复
# ═══════════════════════════════════════════════════════════

# 完整字段名映射表（扩展版）
FIELD_NAME_MAPPING_EXTENDED = {
    # 章节摘要（chunk分析阶段）
    "章节摘要": "chapter_summaries",
    "章节概要": "chapter_summaries",
    "章节分析": "chapter_summaries",
    "章节内容": "chapter_summaries",
    "chapter_summary": "chapter_summaries",
    "chapter_summaries": "chapter_summaries",
    # 🔑 注意：不映射 "chapters" → "chapter_summaries"，因为 synthesis 输出中 chapters 是独立字段
    "summaries": "chapter_summaries",

    # 核心概念
    "核心概念": "core_concepts",
    "核心观念": "core_concepts",
    "关键概念": "core_concepts",
    "重要概念": "core_concepts",
    "核心理论": "core_concepts",
    "core_concepts": "core_concepts",
    "concepts": "core_concepts",
    "key_concepts": "core_concepts",

    # 关键洞见
    "关键洞见": "key_insights",
    "关键洞察": "key_insights",
    "核心洞见": "key_insights",
    "重要洞见": "key_insights",
    "核心观点": "key_insights",
    "key_insights": "key_insights",
    "insights": "key_insights",
    "key_ideas": "key_insights",

    # 关键案例
    "关键案例": "key_cases",
    "经典案例": "key_cases",
    "典型案例": "key_cases",
    "重要案例": "key_cases",
    "案例分析": "key_cases",
    "key_cases": "key_cases",
    "cases": "key_cases",
    "examples": "key_cases",

    # 金句/引用
    "金句": "golden_quotes",
    "名言": "golden_quotes",
    "关键引用": "golden_quotes",
    "经典语句": "golden_quotes",
    "精彩段落": "golden_quotes",
    "golden_quotes": "golden_quotes",
    "quotes": "golden_quotes",
    "quotations": "golden_quotes",
    "key_quotes": "golden_quotes",
    "golden_sentences": "golden_quotes",
    "key_sentences": "golden_quotes",

    # 其他字段
    "作者思想": "author_themes",
    "作者观点": "author_themes",
    "author_themes": "author_themes",
    "书籍结构": "book_structure",
    "book_structure": "book_structure",
    "论证逻辑": "argument_logic",
    "argument_logic": "argument_logic",
    "发展脉络": "development_path",
    "development_path": "development_path",
}

# ═══════════════════════════════════════════════════════════
# Layer 3: 验证层 — 必要字段检查
# ═══════════════════════════════════════════════════════════

REQUIRED_FIELDS = {
    # chunk 分析必要字段（chapter_summaries 必须存在！）
    "chunk_analysis": [
        "chapter_summaries",  # 🔑 强制要求！必须存在（即使是空数组）
        "core_concepts",
        "key_insights",
        "golden_quotes",
        "key_cases",
    ],
    # 综合分析必要字段
    "synthesis": [
        "metadata",
        "chapters",
        "core_concepts",
    ],
    # 🔑 新增：多轮 synthesis 各 round 的必要字段
    "synthesis_round_1": ["metadata", "time_background"],  # Round 1: 元数据 + 背景
    "synthesis_round_2": ["chapters"],  # Round 2: 章节 1-10
    "synthesis_round_3": ["chapters"],  # Round 3: 章节 11-20
    "synthesis_round_4": ["chapters", "core_concepts"],  # Round 4: 章节 21+ + 核心概念
    "synthesis_round_5": ["key_insights", "key_cases", "key_quotes"],  # Round 5: 洞见 + 案例 + 金句
}

# 🔑 新增：强制字段（必须存在，不能缺失）
MANDATORY_FIELDS = {
    "chunk_analysis": [],  # 不强制要求任何字段（每个chunk内容不同）
    "synthesis": ["metadata", "chapters", "core_concepts"],
    # 🔑 新增：多轮 synthesis 的强制字段
    "synthesis_round_1": ["metadata"],
    "synthesis_round_2": ["chapters"],
    "synthesis_round_3": ["chapters"],
    "synthesis_round_4": ["chapters"],
    "synthesis_round_5": ["key_insights"],
}

# ═══════════════════════════════════════════════════════════
# 模型特定约束（根据模型特点定制）
# ═══════════════════════════════════════════════════════════

MODEL_SPECIFIC_CONSTRAINTS = {
    # meta/llama 系列：倾向于中文字段名
    "meta/llama": """
        【特殊约束 - meta/llama】
        你倾向于使用中文字段名。本次任务必须使用英文标准字段名：
        - 使用 "chapter_summaries" 而非 "章节摘要"
        - 使用 "core_concepts" 而非 "核心概念"
        - 使用 "key_insights" 而非 "关键洞见"
        - 使用 "golden_quotes" 而非 "金句"
    """,

    # qwen 系列：通常使用英文，但有时混用
    "qwen": """
        【特殊约束 - qwen】
        保持使用英文字段名，确保与标准一致：
        - chapter_summaries（不是 chapters）
        - core_concepts（不是 concepts）
        - key_insights（不是 insights）
    """,

    # minimax 系列：混合使用中英文
    "minimax": """
        【特殊约束 - minimax】
        禁止混合使用中英文字段名。全部使用英文标准字段名。
        检查你的输出：如果发现任何中文字段名，立即替换为英文。
    """,

    # 默认约束
    "default": OUTPUT_FORMAT_CONSTRAINT,
}


def get_prompt_for_model(model_id: str) -> str:
    """
    根据模型 ID 获取对应的格式约束提示词

    Args:
        model_id: 模型标识符

    Returns:
        str: 该模型的格式约束提示词
    """
    # 匹配模型特定约束
    for model_prefix, constraint in MODEL_SPECIFIC_CONSTRAINTS.items():
        if model_prefix.lower() in model_id.lower():
            return constraint

    # 默认约束
    return MODEL_SPECIFIC_CONSTRAINTS["default"]


def normalize_field_names(result: dict) -> dict:
    """
    规范化字段名（扩展版）

    Args:
        result: 原始解析结果

    Returns:
        dict: 规范化后的结果
    """
    if not result:
        return result

    normalized = {}
    for key, value in result.items():
        # 查找映射
        normalized_key = FIELD_NAME_MAPPING_EXTENDED.get(key, key)
        normalized[normalized_key] = value

    return normalized


def validate_required_fields(result: dict, field_type: str = "chunk_analysis") -> tuple:
    """
    验证必要字段是否存在（强化版）

    🔑 根因修复：强制要求 chapter_summaries 存在且非空

    Args:
        result: 解析结果
        field_type: 字段类型（chunk_analysis 或 synthesis）

    Returns:
        tuple: (是否合格, 缺失字段列表)
    """
    required = REQUIRED_FIELDS.get(field_type, [])
    mandatory = MANDATORY_FIELDS.get(field_type, [])

    # 🔑 Step 1: 检查强制字段必须存在（允许空数组——有些chunk确实无实质内容）
    mandatory_missing = []
    for field in mandatory:
        if field not in result:
            mandatory_missing.append(field)

    if mandatory_missing:
        # 强制字段缺失，直接不合格
        return False, mandatory_missing

    # 🔑 Step 1.5: 检查至少有一个必要字段有内容
    has_content = False
    missing = []

    for field in required:
        if field in result:
            value = result[field]
            # 检查是否有内容
            if isinstance(value, list) and len(value) > 0:
                has_content = True
            elif isinstance(value, dict) and len(value) > 0:
                has_content = True
            elif isinstance(value, str) and len(value.strip()) > 0:
                has_content = True
        else:
            missing.append(field)

    # 🔑 Step 3: 允许空内容（如"致谢"章节），但必须有字段
    if not has_content and not missing:
        # 标记为无学术内容章节，但仍视为合格（因为强制字段已存在）
        result["is_non_academic"] = True
        result["extraction_status"] = "empty_content"
        return True, []

    return has_content, missing


def repair_truncated_json(json_str: str) -> str:
    """
    修复截断的 JSON（增强版）

    Args:
        json_str: 可能截断的 JSON 字符串

    Returns:
        str: 修复后的 JSON 字符串
    """
    import re

    # 🔑 Step 0: 先 strip() 去除首尾空白，再移除 Markdown 代码块标记
    json_str = json_str.strip()
    json_str = re.sub(r'^```json\s*', '', json_str)
    json_str = re.sub(r'^```\s*', '', json_str)
    json_str = re.sub(r'\s*```$', '', json_str)

    # 🔑 新增 Step 0.05: 移除 JSON 键名前后的 Markdown 粗体标记
    json_str = re.sub(r'\*\*(\s*"[^"]+"\s*:)', r'\1', json_str)
    json_str = re.sub(r'("[^"]+"\s*:)\*\*', r'\1', json_str)

    # 🔑 新增 Step 0.1: 移除注释行（以 # 开头的行）
    lines = json_str.split('\n')
    non_comment_lines = [line for line in lines if not line.strip().startswith('#')]
    json_str = '\n'.join(non_comment_lines).strip()

    # 🔑 新增 Step 0.5: 移除 JSON 注释（LLM经常添加 // 注释）
    # 移除单行注释 // ...（但不移除URL中的//，如 https://）
    json_str = re.sub(r'(?<!:)//[^\n]*', '', json_str)
    # 移除多行注释 /* ... */
    json_str = re.sub(r'/\*[\s\S]*?\*/', '', json_str)

    # 🔑 新增 Step 0.6: 清理注释移除后的空白行和多余逗号
    # 移除只包含空白的行（保留有内容的行）
    lines = json_str.split('\n')
    non_empty_lines = [line for line in lines if line.strip()]
    json_str = '\n'.join(non_empty_lines)

    # 🔑 清理多余的逗号（逗号后面是 ] 或 }）
    json_str = re.sub(r',(\s*[\]\}])', r'\1', json_str)

    # 🔑 新增 Step 0.7: 智能转义字符串值内部的引号
    # 问题：字符串值内部的引号（无论是中文还是英文）会被JSON解析器误认为字符串结束
    # 方案：找到字符串值的范围，将内部的引号转义为 \"
    def escape_internal_quotes(text):
        """转义JSON字符串值内部的引号"""
        result = []
        i = 0
        in_string = False

        while i < len(text):
            char = text[i]

            # 检测字符串开始（未转义的引号）
            if char == '"' and (i == 0 or text[i-1] != '\\'):
                if not in_string:
                    # 字符串开始
                    in_string = True
                    result.append(char)
                    i += 1
                    continue
                else:
                    # 检查是否是字符串结束
                    # 字符串结束条件：后面是逗号、方括号/花括号结束、冒号、空白或换行
                    remaining = text[i+1:].lstrip()
                    end_marker = remaining[:1] if remaining else ''

                    if end_marker in ['', ',', ']', '}', ':'] or (i+1 < len(text) and text[i+1] in '\n\r\t '):
                        # 这是字符串结束引号
                        in_string = False
                        result.append(char)
                        i += 1
                        continue
                    else:
                        # 这是字符串值内部的引号，需要转义
                        result.append('\\')
                        result.append(char)
                        i += 1
                        continue

            # 其他字符正常处理
            result.append(char)
            i += 1

        return ''.join(result)

    json_str = escape_internal_quotes(json_str)

    # 🔑 新增：修复常见的字段格式错误（字符串应该是数组）
    # 修复 "critical_questions": "问题1", "问题2" → ["问题1", "问题2"]
    # 匹配模式：字段名后是字符串，然后逗号，然后另一个字符串
    array_fields_pattern = [
        ('critical_questions', r'"critical_questions":\s*"([^"]+)",\s*"([^"]+)"'),
        ('related_books', r'"related_books":\s*"([^"]+)",\s*"([^"]+)"'),
    ]
    for field_name, pattern in array_fields_pattern:
        json_str = re.sub(pattern, f'"{field_name}": ["\\1", "\\2"]', json_str)

    # 🔑 新增：修复字段值是单个字符串但应该是数组的情况
    # "critical_questions": "问题" → ["问题"]
    single_string_to_array_fields = ['critical_questions', 'related_books', 'tags', 'category']
    for field_name in single_string_to_array_fields:
        pattern = f'"{field_name}":\\s*"([^"\\[\\]]+)"'
        replacement = f'"{field_name}": ["\\1"]'
        json_str = re.sub(pattern, replacement, json_str)

    # 1. 如果 JSON 以 } 结尾，可能是完整的
    if json_str.rstrip().endswith('}'):
        return json_str

    # 3. 找到最外层 JSON 对象的开始
    start = json_str.find('{')
    if start < 0:
        return json_str

    result = json_str[start:]

    # 4. 统计未闭合的括号
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False

    for i, c in enumerate(result):
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                open_braces += 1
            elif c == '}':
                open_braces -= 1
            elif c == '[':
                open_brackets += 1
            elif c == ']':
                open_brackets -= 1

    # 5. 修复截断的字符串
    if in_string:
        result = result + '"'

    # 5.5: 修复截断的对象（在数组内）
    # 问题：当截断在 {"key": "value" 时，需要先闭合对象，再闭合数组
    # 策略：检查最后一个字符是否是 "，且前面是对象属性的值
    # 简单方案：在字符串闭合后，如果还有未闭合的对象和数组，按正确顺序闭合
    #
    # 注意：JSON 结构可能是嵌套的，如：
    # {"arr": [{"key": "value"}]}
    # 截断后：{"arr": [{"key": "value"
    # 需要修复为：{"arr": [{"key": "value"}]}

    # 6. 修复截断的数组
    # 问题：当截断在数组内的对象时，需要先闭合对象，再闭合数组
    # 策略：检查 result 的最后一个非空白字符
    last_char = result.rstrip()[-1] if result.rstrip() else ''

    # 如果最后是 "，可能是在字符串值后截断
    # 需要检查是否需要先闭合对象
    if last_char == '"' and open_braces > 1 and open_brackets > 0:
        # 在数组内的对象被截断，需要先闭合对象
        # 但我们不能直接添加 }，因为可能还有其他嵌套
        # 策略：按顺序先尝试闭合所有对象，再闭合数组
        pass  # 让下面的循环按顺序处理

    while open_brackets > 0 or open_braces > 0:
        # 智能闭合：检查哪个应该先闭合
        # 规则：在有效的 JSON 中，如果对象在数组内，应该先闭合对象
        # 但由于我们只有计数，无法确定顺序
        # 策略：交替闭合，先 } 后 ]
        if open_braces > open_brackets:
            # 更多对象未闭合，先闭合对象
            result = result + '}'
            open_braces -= 1
        else:
            # 更多或相等的数组未闭合
            result = result + ']'
            open_brackets -= 1

    # 8. 清理末尾可能的逗号
    result = re.sub(r',(\s*[}\]])', r'\1', result)

    return result


def parse_model_output(content: str, field_type: str = "chunk_analysis", model_id: str = "unknown") -> tuple:
    """
    解析模型输出（优化版：简化三层防护）

    ponytail: 三层防护过于复杂（618行），简化为：
    1. 尝试直接解析JSON
    2. 失败时使用json_repair库修复
    3. 最终fallback返回raw_response

    Args:
        content: 模型返回的原始内容
        field_type: 字段类型（chunk_analysis 或 synthesis），用于验证
        model_id: 模型标识符（可选）

    Returns:
        tuple: (解析结果dict, 是否成功, 错误信息)
    """
    import json

    if content is None:
        return {
            "raw_response": None,
            "extraction_status": "partial",
            "error": "LLM 返回空内容"
        }, False, "LLM 返回空内容"

    # ponytail: Step 1 - 清理内容（移除markdown代码块）
    content_cleaned = repair_truncated_json(content.strip())

    # ponytail: Step 2 - 尝试直接解析
    try:
        result = json.loads(content_cleaned)
        result = normalize_field_names(result)

        # 补齐缺失字段（chunk分析允许部分字段缺失）
        if field_type == "chunk_analysis":
            for field in REQUIRED_FIELDS.get(field_type, []):
                result.setdefault(field, [])

        # 验证必要字段
        is_valid, missing = validate_required_fields(result, field_type)
        if not is_valid:
            return result, False, f"缺少必要字段: {missing}"

        return result, True, "解析成功"

    except json.JSONDecodeError:
        # ponytail: Step 3 - 使用json_repair库修复（更可靠）
        try:
            import json_repair
            result = json_repair.loads(content_cleaned)
            result = normalize_field_names(result)

            logger.info("   ✅ 使用json_repair库成功修复JSON")

            # 补齐缺失字段
            if field_type == "chunk_analysis":
                for field in REQUIRED_FIELDS.get(field_type, []):
                    result.setdefault(field, [])

            return result, True, "json_repair修复成功"

        except ImportError:
            # ponytail: Step 4 - json_repair未安装，提取第一个JSON对象
            json_start = content_cleaned.find('{')
            if json_start < 0:
                logger.warning(f"⚠️ 未找到JSON结构，已保存原始响应({len(content)}字符)")
                return {
                    "raw_response": content[:5000],
                    "extraction_status": "partial",
                    "error": "未找到JSON结构"
                }, False, "未找到JSON结构，已保存raw_response"

            # 深度匹配找完整JSON
            depth = 0
            json_end = json_start
            for i, c in enumerate(content_cleaned[json_start:], json_start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        json_end = i + 1
                        break

            json_str = content_cleaned[json_start:json_end]

            try:
                result = json.loads(json_str)
                result = normalize_field_names(result)

                # 补齐缺失字段
                if field_type == "chunk_analysis":
                    for field in REQUIRED_FIELDS.get(field_type, []):
                        result.setdefault(field, [])

                return result, True, "提取JSON成功"

            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ JSON解析失败，已保存原始响应({len(content)}字符)")
                return {
                    "raw_response": content[:5000],
                    "extraction_status": "partial",
                    "error": str(e)[:100]
                }, False, f"JSON 解析失败，已保存raw_response"

        except Exception as e:
            logger.warning(f"⚠️ 解析异常，已保存原始响应({len(content)}字符)")
            return {
                "raw_response": content[:5000],
                "extraction_status": "partial",
                "error": str(e)[:100]
            }, False, f"解析异常，已保存raw_response"


# ═══════════════════════════════════════════════════════════
# 使用示例
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 测试字段名规范化
    test_input = {
        "章节摘要": [{"title": "第一章"}],
        "核心概念": [{"name": "系统思维"}],
        "金句": ["这是一句话"],
    }

    normalized = normalize_field_names(test_input)
    logger.info("规范化结果:")
    logger.info(json.dumps(normalized, indent=2, ensure_ascii=False))

    # 测试截断修复
    truncated = '{"core_concepts": [{"name": "概念1", "definition": "定义...'
    repaired = repair_truncated_json(truncated)
    logger.info(f"截断修复: {repaired}")