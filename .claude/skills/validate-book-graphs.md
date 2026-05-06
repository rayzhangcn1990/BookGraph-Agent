---
name: validate-book-graphs
description: 校验知识图谱质量 - 批量检查已生成的知识图谱，检测章节合并、占位符、章节数不足等问题，并输出修复建议
---

# 知识图谱质量校验 Skill

## 目标

批量检查已生成的知识图谱文件，检测：
1. **章节合并问题**（LLM偷懒行为）：如"11-22"、"1-10"
2. **占位符污染**：如"无法确定"、"书中未提供"、"待补充"
3. **章节数不足**：章节数少于预期值
4. **空洞内容**：core_argument 内容过短

## 执行流程

### Step 1: 扫描所有知识图谱文件

```bash
find "/Users/rayzhang/Documents/知识体系/📚 知识图谱" -path "*/书籍图谱/*.md" -type f
```

### Step 2: 对每个文件执行质量检查

使用 `BookGraphQualityChecker` 进行检测：

```python
from core.book_graph_quality_checker import BookGraphQualityChecker, check_book_graph_quality

checker = BookGraphQualityChecker()

# 检测章节合并
merged = checker._detect_merged_chapters(chapters)

# 检测占位符
placeholder_count = checker._count_placeholders(data)

# 检测模板内容
template_count = checker._count_template_content(data)
```

### Step 3: 输出问题报告

格式：
```
文件: 平面国：多维空间传奇往事.md
问题:
  - ⛔ 章节合并: ['11-22'] (偷懒行为)
  - ⚠️ 章节数不足: 11章 (预期24章)
  - ⚠️ 占位符: 2处

修复建议:
  - 重新处理此书，禁用章节合并
  - 提高质量阈值，要求覆盖率>=80%
```

### Step 4: 生成修复清单

列出所有需要重新处理的书籍，并生成修复脚本建议。

## 质量检查指标

| 指标 | 合格标准 | 检测方法 |
|------|---------|---------|
| 章节合并 | 0个 | `_detect_merged_chapters()` |
| 占位符 | 0处 | `_count_placeholders()` |
| 章节数 | ≥预期80% | 对比 expected_chapters |
| 空洞章节 | ≤30% | 检查 core_argument 长度 |
| 底层逻辑格式 | ≥80% | 检查"前提假设→推理链条→核心结论"格式 |

## 输出格式

### 问题报告（JSON）

```json
{
  "total_files": 44,
  "issues": {
    "merged_chapters": [
      {"file": "平面国.md", "merged": ["11-22"]}
    ],
    "placeholder_issues": [
      {"file": "真实世界的脉络.md", "placeholders": ["无法确定:11", "完整内容未提供:10"]}
    ],
    "low_chapter_count": [
      {"file": "中国的选择.md", "count": 0}
    ]
  },
  "stats": {
    "merged_files": 1,
    "placeholder_files": 13,
    "low_chapter_files": 18
  }
}
```

### 修复建议

对于问题文件，建议：
1. 重新处理书籍，传入预期章节数
2. 使用更严格的 quality_checker
3. 调高 SYNTHESIS_PROMPT 的质量要求
4. 考虑使用更强模型（如 Claude Opus）

## 使用示例

```bash
# 校验所有知识图谱
python scripts/validate_book_graphs.py --all

# 校验指定文件
python scripts/validate_book_graphs.py --file "平面国：多维空间传奇往事.md"

# 生成修复清单
python scripts/validate_book_graphs.py --output repair_list.json
```

## 注意事项

1. **章节合并检测是最关键的**：这是LLM最常见的偷懒行为
2. **占位符检测要严格**：任何"无法确定"、"书中未提供"都不合格
3. **章节数对比**：需要从原始书籍解析结果中获取预期值
4. **修复优先级**：章节合并 > 占位符 > 章节数不足 > 空洞内容