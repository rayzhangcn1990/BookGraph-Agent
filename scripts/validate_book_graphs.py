"""
知识图谱格式验证脚本（增强版）

验证所有书籍知识图谱是否符合标准格式：
1. YAML frontmatter 必要字段
2. 核心章节完整性
3. 无占位符（待补充、TODO等）
4. 表格格式正确
5. ⛔ 禁止章节合并（LLM偷懒行为） - 新增
6. 章节数量检查 - 新增
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from core.book_graph_quality_checker import BookGraphQualityChecker
    CHECKER_AVAILABLE = True
except ImportError:
    CHECKER_AVAILABLE = False

# 必要章节
REQUIRED_SECTIONS = [
    "时代背景",
    "章节结构总览",
    "核心概念",
    "关键洞见",
    "关键案例",
    "金句萃取",
    "批判性解读",
    "伦理边界",
    "学习路径",
    "关联书籍网络",
]

# 必要 YAML 字段
REQUIRED_YAML_FIELDS = [
    "title",
    "author",
    "discipline",
    "tags",
]

# 占位符关键词（禁止出现）
PLACEHOLDER_KEYWORDS = [
    "待补充",
    "待分析",
    "待填写",
    "待生成",
    "TBD",
    "TODO",
    "N/A",
    "NULL",
    "暂无",
    "（此处内容由 LLM 生成）",
    "（内容由模型生成）",
    # 🔑 新增：更多占位符检测
    "无法确定",
    "书中未提供",
    "完整内容未提供",
    "（完整内容未提供）",
]

# 🔑 新增：章节合并模式（最严重的偷懒行为！）
MERGED_CHAPTER_PATTERNS = [
    r'\d+-\d+',         # "11-22", "1-10"
    r'第\d+-\d+章',     # "第11-22章"
    r'\d+至\d+',        # "11至22"
    r'\d+～\d+',        # "11～22"
]


def validate_book_graph(file_path: Path) -> Dict:
    """
    验证单本书籍知识图谱（增强版）

    Returns:
        Dict: {
            'file': 文件名,
            'valid': 是否合格,
            'errors': 错误列表,
            'warnings': 警告列表,
            'stats': 统计信息
        }
    """
    result = {
        'file': file_path.name,
        'valid': True,
        'errors': [],
        'warnings': [],
        'stats': {}
    }

    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        result['valid'] = False
        result['errors'].append(f"无法读取文件: {e}")
        return result

    # 统计
    result['stats']['total_chars'] = len(content)
    result['stats']['total_lines'] = content.count('\n')

    # ═══════════════════════════════════════════════════════════
    # 🔑 新增：章节合并检测（最严重的偷懒行为！）
    # ═══════════════════════════════════════════════════════════

    chapter_section = re.search(r'## .*章节结构.*\n\n\|.*\n\|.*\n', content)

    if chapter_section:
        # 提取章节表格
        table_start = chapter_section.end()
        table_content = content[table_start:]

        # 提取所有章节编号行
        chapter_rows = re.findall(r'\|\s*(\d+[-\d]*)\s*\|', table_content[:3000])

        # 检测合并章节
        merged = []
        for row in chapter_rows:
            for pattern in MERGED_CHAPTER_PATTERNS:
                if re.match(pattern, row):
                    merged.append(row)
                    break

        if merged:
            result['valid'] = False  # 🔑 CRITICAL：直接不合格
            result['errors'].append(f"⛔ 章节合并偷懒: {merged}（禁止用'11-22'等合并编号）")

        # 统计章节数
        result['stats']['chapter_count'] = len(chapter_rows)

        if len(chapter_rows) < 10:
            result['warnings'].append(f"章节数偏少: {len(chapter_rows)} (<10)")
        elif len(chapter_rows) == 0:
            result['valid'] = False
            result['errors'].append("无章节结构")

    # ═══════════════════════════════════════════════════════════
    # 验证 YAML frontmatter
    # ═══════════════════════════════════════════════════════════

    yaml_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)

    if not yaml_match:
        result['valid'] = False
        result['errors'].append("缺少 YAML frontmatter")
        return result

    yaml_content = yaml_match.group(1)

    for field in REQUIRED_YAML_FIELDS:
        if field not in yaml_content:
            result['errors'].append(f"YAML 缺少字段: {field}")

    # ═══════════════════════════════════════════════════════════
    # 验证必要章节
    # ═══════════════════════════════════════════════════════════

    for section in REQUIRED_SECTIONS:
        section_pattern = f"## .*{section}"

        if not re.search(section_pattern, content):
            result['errors'].append(f"缺少章节: {section}")

    # ═══════════════════════════════════════════════════════════
    # 检查占位符
    # ═══════════════════════════════════════════════════════════

    placeholders_found = []

    for keyword in PLACEHOLDER_KEYWORDS:
        if keyword in content:
            # 找到所有出现位置
            matches = re.finditer(keyword, content)
            for match in matches:
                # 找到所在行
                line_num = content[:match.start()].count('\n') + 1
                placeholders_found.append(f"行 {line_num}: {keyword}")

    if placeholders_found:
        result['warnings'].append(f"发现占位符 ({len(placeholders_found)} 处)")
        result['warnings'].extend(placeholders_found[:5])  # 只显示前5个

    # ═══════════════════════════════════════════════════════════
    # 验证表格格式
    # ═══════════════════════════════════════════════════════════

    # 检查章节结构表格
    chapter_table_match = re.search(r'## .*章节结构.*\n\n\|.*\n\|.*\n', content)

    if not chapter_table_match:
        result['warnings'].append("章节结构缺少标准表格格式")

    # 检查核心概念表格
    concept_table_match = re.search(r'### .*\n\n\| 阶段 |', content)

    if not concept_table_match:
        # 允许部分概念缺少发展演化表
        pass

    # ═══════════════════════════════════════════════════════════
    # 验证底层逻辑格式
    # ═══════════════════════════════════════════════════════════

    logic_pattern = r'\*\*底层逻辑\*\*：\n\n- \*\*前提假设\*\*：.*\n- \*\*推理链条\*\*：.*\n- \*\*核心结论\*\*：.*'

    logic_matches = re.findall(logic_pattern, content)
    result['stats']['logic_blocks'] = len(logic_matches)

    if len(logic_matches) < 3:
        result['warnings'].append(f"底层逻辑块数量较少 ({len(logic_matches)} 个)")

    # ═══════════════════════════════════════════════════════════
    # 验证关联书籍
    # ═══════════════════════════════════════════════════════════

    related_books_match = re.search(r'## .*关联书籍.*\n\n\*\*本书\*\*：', content)

    if not related_books_match:
        result['warnings'].append("关联书籍网络格式不标准")

    # 统计关联书籍数量
    book_links = re.findall(r'\[\[.*?\]\]', content)
    result['stats']['book_links'] = len(book_links)

    # ═══════════════════════════════════════════════════════════
    # 最终判定
    # ═══════════════════════════════════════════════════════════

    if result['errors']:
        result['valid'] = False

    return result


def validate_all_books(directory: Path) -> List[Dict]:
    """验证目录下所有书籍"""

    results = []

    # 查找所有书籍图谱文件
    book_files = list(directory.glob("**/*.md"))

    # 过滤掉非书籍图谱（学科图谱等）
    book_files = [f for f in book_files if "书籍图谱" in str(f)]

    print(f"找到 {len(book_files)} 个书籍图谱文件")

    for file_path in sorted(book_files):
        result = validate_book_graph(file_path)
        results.append(result)

    return results


def generate_report(results: List[Dict]) -> str:
    """生成验证报告（增强版）"""

    report = "# 知识图谱格式验证报告（增强版）\n\n"
    report += f"**验证时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"**书籍总数**: {len(results)}\n\n"

    # 统计
    valid_count = sum(1 for r in results if r['valid'])
    invalid_count = len(results) - valid_count

    # 🔑 新增：统计各类问题
    merged_files = [r for r in results if any('章节合并' in e for e in r['errors'])]
    placeholder_files = [r for r in results if r['warnings'] and any('占位符' in w for w in r['warnings'])]
    low_chapter_files = [r for r in results if r['stats'].get('chapter_count', 0) < 10]

    report += "## 统计概览\n\n"
    report += f"| 指标 | 数值 |\n"
    report += f"|------|------|\n"
    report += f"| 总书籍数 | {len(results)} |\n"
    report += f"| 合格数 | {valid_count} |\n"
    report += f"| 不合格数 | {invalid_count} |\n"
    report += f"| 合格率 | {valid_count / len(results) * 100:.1f}% |\n"
    report += f"| ⛔ 章节合并问题 | {len(merged_files)} |\n"
    report += f"| ⚠️ 占位符问题 | {len(placeholder_files)} |\n"
    report += f"| ⚠️ 章节数不足 | {len(low_chapter_files)} |\n\n"

    # 🔑 新增：章节合并问题详情（最严重）
    if merged_files:
        report += "## ⛔ 章节合并问题（LLM偷懒行为）\n\n"
        report += "**这是最严重的质量问题，需要立即修复！**\n\n"

        for r in merged_files:
            report += f"- `{r['file']}`\n"
            for error in r['errors']:
                if '章节合并' in error:
                    report += f"  - {error}\n"
        report += "\n"

    # 合格书籍
    if valid_count > 0:
        report += "## ✅ 合格书籍\n\n"

        for r in results:
            if r['valid']:
                warnings_str = f" ({len(r['warnings'])} 个警告)" if r['warnings'] else ""
                chapter_str = f" {r['stats'].get('chapter_count', '?')}章" if r['stats'].get('chapter_count') else ""
                report += f"- {r['file']}{chapter_str}{warnings_str}\n"

    # 不合格书籍
    if invalid_count > 0:
        report += "## ❌ 不合格书籍\n\n"

        for r in results:
            if not r['valid']:
                report += f"### {r['file']}\n\n"
                report += f"**错误列表**:\n\n"

                for error in r['errors']:
                    report += f"- {error}\n"

                if r['warnings']:
                    report += f"\n**警告列表**:\n\n"
                    for warning in r['warnings'][:10]:
                        report += f"- {warning}\n"

    # 详细统计
    report += "\n## 详细统计\n\n"

    for r in results:
        stats = r.get('stats', {})
        if stats:
            report += f"### {r['file']}\n\n"
            report += f"| 指标 | 数值 |\n"
            report += f"|------|------|\n"
            report += f"| 总字符数 | {stats.get('total_chars', 0)} |\n"
            report += f"| 总行数 | {stats.get('total_lines', 0)} |\n"
            report += f"| 底层逻辑块 | {stats.get('logic_blocks', 0)} |\n"
            report += f"| 书籍链接数 | {stats.get('book_links', 0)} |\n\n"

    return report


def main():
    """主函数"""

    # 知识图谱目录
    graph_dir = Path("/Users/rayzhang/Documents/知识体系/📚 知识图谱")

    print("=" * 60)
    print("🔍 知识图谱格式验证")
    print("=" * 60)

    # 验证所有书籍
    results = validate_all_books(graph_dir)

    # 生成报告
    report = generate_report(results)

    # 保存报告
    report_path = Path("/Users/rayzhang/BookGraph-Agent/知识图谱格式验证报告.md")
    report_path.write_text(report, encoding='utf-8')

    print(f"\n✅ 验证完成")
    print(f"   合格: {sum(1 for r in results if r['valid'])}/{len(results)}")
    print(f"   报告: {report_path}")

    # 输出不合格书籍
    invalid = [r for r in results if not r['valid']]

    if invalid:
        print(f"\n❌ 不合格书籍 ({len(invalid)} 个):")

        for r in invalid:
            print(f"   - {r['file']}")
            for error in r['errors'][:3]:
                print(f"      {error}")

    # 返回状态码
    sys.exit(0 if all(r['valid'] for r in results) else 1)


if __name__ == "__main__":
    main()