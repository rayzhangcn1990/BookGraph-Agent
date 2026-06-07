"""
测试 P0-1: LLM JSON 输出解析增强

问题：模型返回带前缀的 JSON 或非结构化文本，导致解析失败
方案：使用 instructor 库强制结构化输出
"""
import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from pydantic import BaseModel, Field
from typing import List, Optional


# ═══════════════════════════════════════════════════════════
# 测试用的 Pydantic 模型
# ═══════════════════════════════════════════════════════════

class ChapterSummary(BaseModel):
    """章节摘要"""
    chapter_number: str = Field(description="章节编号")
    title: str = Field(description="章节标题")
    core_argument: str = Field(description="核心论点")


class CoreConcept(BaseModel):
    """核心概念"""
    name: str = Field(description="概念名称")
    definition: str = Field(description="概念定义")
    deep_meaning: str = Field(default="", description="深层含义")


class ChunkAnalysisResult(BaseModel):
    """Chunk 分析结果"""
    chapter_summaries: List[ChapterSummary] = Field(default_factory=list, description="章节摘要列表")
    core_concepts: List[CoreConcept] = Field(default_factory=list, description="核心概念列表")
    key_insights: List[str] = Field(default_factory=list, description="关键洞见")
    key_cases: List[str] = Field(default_factory=list, description="关键案例")
    golden_quotes: List[str] = Field(default_factory=list, description="金句")


# ═══════════════════════════════════════════════════════════
# Test 1: 带前缀的 JSON 解析
# ═══════════════════════════════════════════════════════════

class TestPrefixedJSONParsing:
    """测试带前缀的 JSON 解析"""

    def test_parse_json_with_chinese_prefix(self):
        """
        RED: 测试解析带中文前缀的 JSON

        场景：Gemini 模型返回：
        "首先，让我分析一下书籍内容...
        {"chapter_summaries": [...]}"

        期望：正确提取 JSON 部分
        """
        from core.model_output_format_spec import parse_model_output

        raw_response = """首先，用户要求分析书籍内容，提取结构化数据。让我来分析一下...

{"chapter_summaries": [{"chapter_number": "1", "title": "第一卷", "core_argument": "测试论点"}], "core_concepts": [], "key_insights": [], "key_cases": [], "golden_quotes": []}"""

        result, success, error = parse_model_output(raw_response, "chunk_analysis")

        assert result is not None, "解析结果不应为 None"
        assert success, f"解析应成功，但失败: {error}"
        assert "chapter_summaries" in result, "应包含 chapter_summaries 字段"
        assert len(result["chapter_summaries"]) == 1, "应有 1 个章节摘要"

    def test_parse_json_with_markdown_block(self):
        """
        RED: 测试解析 Markdown 代码块包裹的 JSON

        场景：模型返回：
        ```json
        {"chapter_summaries": [...]}
        ```

        期望：正确提取 JSON 部分
        """
        from core.model_output_format_spec import parse_model_output

        raw_response = """根据书籍内容，我提取了以下信息：

```json
{
  "chapter_summaries": [
    {"chapter_number": "1", "title": "引言", "core_argument": "引言论点"}
  ],
  "core_concepts": [{"name": "概念1", "definition": "定义1"}],
  "key_insights": [],
  "key_cases": [],
  "golden_quotes": []
}
```"""

        result, success, error = parse_model_output(raw_response, "chunk_analysis")

        assert result is not None, "解析结果不应为 None"
        assert success, f"解析应成功，但失败: {error}"
        assert "core_concepts" in result, "应包含 core_concepts 字段"
        assert result["core_concepts"][0]["name"] == "概念1"

    def test_parse_json_with_thinking_prefix(self):
        """
        RED: 测试解析带思维链前缀的 JSON

        场景：Llama 模型返回：
        <thinking>
        用户想要分析这本书...
        </thinking>
        {"chapter_summaries": [...]}
        """
        from core.model_output_format_spec import parse_model_output

        raw_response = """<thinking>
用户要求提取书籍的结构化数据。这本书主要讨论斯多葛哲学...
让我仔细分析每个章节的内容...
</thinking>

{"chapter_summaries": [{"chapter_number": "1", "title": "第一章", "core_argument": "测试"}], "core_concepts": [], "key_insights": [], "key_cases": [], "golden_quotes": []}"""

        result, success, error = parse_model_output(raw_response, "chunk_analysis")

        assert result is not None, "解析结果不应为 None"
        assert success, f"解析应成功，但失败: {error}"
        assert "chapter_summaries" in result


# ═══════════════════════════════════════════════════════════
# Test 2: instructor 库集成
# ═══════════════════════════════════════════════════════════

class TestInstructorIntegration:
    """测试 instructor 库强制结构化输出"""

    def test_instructor_forces_structured_output(self):
        """
        RED: 测试 instructor 库强制返回结构化输出

        期望：即使模型想返回非结构化文本，instructor 也强制返回 Pydantic 模型
        """
        # 这个测试需要 mock OpenAI 客户端
        # 因为我们还没有实现 instructor 集成，所以这个测试会失败
        pytest.skip("等待 instructor 集成实现")

    def test_instructor_handles_validation_error(self):
        """
        RED: 测试 instructor 处理验证错误

        场景：模型返回的字段不符合 Pydantic 模型定义
        期望：instructor 自动重试或返回明确的错误
        """
        pytest.skip("等待 instructor 集成实现")


# ═══════════════════════════════════════════════════════════
# Test 3: 字段名映射增强
# ═══════════════════════════════════════════════════════════

class TestFieldNameMapping:
    """测试字段名映射"""

    def test_map_chinese_field_names(self):
        """
        RED: 测试中文字段名映射到英文

        场景：模型返回：
        {"章节摘要": [...], "核心概念": [...]}

        期望：自动映射到 chapter_summaries, core_concepts
        """
        from core.model_output_format_spec import normalize_field_names

        raw_data = {
            "章节摘要": [{"chapter_number": "1", "title": "测试"}],
            "核心概念": [{"name": "概念1", "definition": "定义"}],
            "关键洞见": ["洞见1"],
            "关键案例": [],
            "金句": []
        }

        result = normalize_field_names(raw_data)

        assert "chapter_summaries" in result, "应映射到 chapter_summaries"
        assert "core_concepts" in result, "应映射到 core_concepts"
        assert "key_insights" in result, "应映射到 key_insights"
        assert "golden_quotes" in result, "应映射到 golden_quotes"

    def test_map_unknown_field_names(self):
        """
        RED: 测试未知字段名处理

        场景：模型返回未知字段名
        期望：保留原字段名，记录警告
        """
        from core.model_output_format_spec import normalize_field_names

        raw_data = {
            "chapter_summaries": [],
            "new_field": "some_value",  # 未知字段
            "another_field": []
        }

        result = normalize_field_names(raw_data)

        assert "new_field" in result, "未知字段应保留"
        assert "another_field" in result, "未知字段应保留"


# ═══════════════════════════════════════════════════════════
# Test 4: 截断修复
# ═══════════════════════════════════════════════════════════

class TestTruncationRepair:
    """测试 JSON 截断修复"""

    def test_repair_truncated_array(self):
        """
        RED: 测试修复截断的数组

        场景：JSON 在数组中间被截断：
        {"chapter_summaries": [{"chapter_number": "1", "title": "测试"

        期望：尝试修复为有效 JSON
        """
        from core.model_output_format_spec import repair_truncated_json

        truncated = '{"chapter_summaries": [{"chapter_number": "1", "title": "测试"'

        result = repair_truncated_json(truncated)

        assert result is not None, "应尝试修复"
        try:
            data = json.loads(result)
            assert "chapter_summaries" in data
        except json.JSONDecodeError:
            # 如果修复失败，应返回原始字符串或抛出明确错误
            pytest.fail(f"修复后的 JSON 仍无法解析: {result}")

    def test_repair_missing_closing_braces(self):
        """
        RED: 测试修复缺失的闭合括号
        """
        from core.model_output_format_spec import repair_truncated_json

        truncated = '{"chapter_summaries": [], "core_concepts": []'

        result = repair_truncated_json(truncated)

        assert result is not None, "应尝试修复"
        data = json.loads(result)
        assert isinstance(data, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
