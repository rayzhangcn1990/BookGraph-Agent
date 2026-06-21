#!/usr/bin/env python3
"""
批量质量校验脚本

扫描已生成的书籍图谱，识别占位符、章节合并、模板化内容等问题，
生成修复清单和修复建议。

使用方法：
    python scripts/batch_quality_check.py --vault "/path/to/vault"
    python scripts/batch_quality_check.py --vault "/path/to/vault" --repair
"""

import os
import re
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

# 添加项目根目录到 Python 路径
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.book_graph_quality_checker import BookGraphQualityChecker, QualityCheckResult

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BatchQualityCheck")


@dataclass
class BookQualityReport:
    """单本书籍的质量报告"""
    book_name: str
    file_path: str
    json_path: Optional[str]
    passed: bool
    score: float
    issues: List[str]
    warnings: List[str]
    stats: Dict
    needs_repair: bool
    repair_priority: str  # HIGH/MEDIUM/LOW


class BatchQualityChecker:
    """批量质量校验器"""

    # 修复优先级阈值
    HIGH_PRIORITY_THRESHOLD = 50  # 分数<50为高优先级
    MEDIUM_PRIORITY_THRESHOLD = 70  # 分数<70为中优先级

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.checker = BookGraphQualityChecker()
        self.reports: List[BookQualityReport] = []
        self.stats = {
            'total_books': 0,
            'passed_books': 0,
            'failed_books': 0,
            'high_priority': 0,
            'medium_priority': 0,
            'low_priority': 0,
            'placeholder_issues': 0,
            'merged_chapter_issues': 0,
            'template_issues': 0,
            'empty_chapter_issues': 0,
        }

    def scan_books(self) -> List[BookQualityReport]:
        """
        扫描所有书籍图谱文件

        Returns:
            List[BookQualityReport]: 质量报告列表
        """
        logger.info(f"开始扫描书籍图谱目录: {self.vault_path}")

        # 查找所有书籍图谱目录
        book_graph_dirs = []
        for root, dirs, files in os.walk(self.vault_path):
            if '书籍图谱' in root:
                book_graph_dirs.append(Path(root))

        logger.info(f"找到 {len(book_graph_dirs)} 个书籍图谱目录")

        # 扫描每个目录
        for book_dir in book_graph_dirs:
            self._scan_book_dir(book_dir)

        # 统计结果
        self._calculate_stats()

        return self.reports

    def _scan_book_dir(self, book_dir: Path):
        """
        扫描单个书籍图谱目录

        Args:
            book_dir: 书籍图谱目录路径
        """
        # 查找所有 .md 和 .json 文件
        md_files = list(book_dir.glob('*.md'))
        json_files = list(book_dir.glob('*.json'))

        # 排除摘要和思维导图文件
        md_files = [f for f in md_files if not f.name.endswith('_summary.md')
                   and not f.name.endswith('.mindmap.md')]

        # 建立文件映射
        file_map: Dict[str, Dict] = {}
        for md_file in md_files:
            book_name = md_file.stem
            json_file = md_file.with_suffix('.json')
            file_map[book_name] = {
                'md_path': str(md_file),
                'json_path': str(json_file) if json_file.exists() else None,
            }

        # 检查每本书
        for book_name, paths in file_map.items():
            report = self._check_book(book_name, paths)
            self.reports.append(report)

    def _check_book(self, book_name: str, paths: Dict) -> BookQualityReport:
        """
        检查单本书籍质量

        Args:
            book_name: 书籍名称
            paths: 文件路径字典

        Returns:
            BookQualityReport: 质量报告
        """
        logger.info(f"检查书籍: {book_name}")

        # 读取 JSON 数据（如果存在）
        book_data = None
        json_path = paths.get('json_path')

        if json_path:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                    # 🔑 修复：处理嵌套的 JSON 结构
                    # 格式1: {"version": ..., "data": {...}}
                    # 格式2: 直接的 BookGraph 数据
                    if 'data' in raw_data:
                        book_data = raw_data['data']
                    else:
                        book_data = raw_data
            except Exception as e:
                logger.warning(f"读取 JSON 失败: {json_path}, 错误: {e}")

        # 如果没有 JSON，从 Markdown 解析
        if not book_data:
            book_data = self._parse_markdown(paths['md_path'])

        # 执行质量检查
        result = self.checker.check(book_data)

        # 计算修复优先级
        repair_priority = self._calculate_repair_priority(result)

        # 判断是否需要修复
        needs_repair = not result.passed or result.score < 80

        return BookQualityReport(
            book_name=book_name,
            file_path=paths['md_path'],
            json_path=json_path,
            passed=result.passed,
            score=result.score,
            issues=result.issues,
            warnings=result.warnings,
            stats=result.stats,
            needs_repair=needs_repair,
            repair_priority=repair_priority,
        )

    def _parse_markdown(self, md_path: str) -> Dict:
        """
        从 Markdown 解析 BookGraph 数据（简化版）

        Args:
            md_path: Markdown 文件路径

        Returns:
            Dict: BookGraph 数据
        """
        # 简化解析：提取基本信息
        data = {
            'metadata': {},
            'chapters': [],
            'core_concepts': [],
            'key_insights': [],
            'key_cases': [],
            'key_quotes': [],
            'critical_analysis': {},
        }

        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取标题和作者
            title_match = re.search(r'#\s*(.+?)\s*\n', content)
            if title_match:
                data['metadata']['title'] = title_match.group(1).strip()

            author_match = re.search(r'作者[：:]\s*(.+?)\n', content)
            if author_match:
                data['metadata']['author'] = author_match.group(1).strip()

            # 统计章节数（简化）
            chapter_matches = re.findall(r'###\s*章节\s*(\d+)', content)
            data['chapters'] = [{'chapter_number': ch} for ch in chapter_matches]

            # 统计概念数
            concept_matches = re.findall(r'###\s*核心概念\s*(\d+)', content)
            data['core_concepts'] = [{'name': f'概念{c}'} for c in concept_matches]

        except Exception as e:
            logger.warning(f"解析 Markdown 失败: {md_path}, 错误: {e}")

        return data

    def _calculate_repair_priority(self, result: QualityCheckResult) -> str:
        """
        计算修复优先级

        Args:
            result: 质量检查结果

        Returns:
            str: HIGH/MEDIUM/LOW
        """
        if result.score < self.HIGH_PRIORITY_THRESHOLD:
            return 'HIGH'
        elif result.score < self.MEDIUM_PRIORITY_THRESHOLD:
            return 'MEDIUM'
        else:
            return 'LOW'

    def _calculate_stats(self):
        """计算统计数据"""
        self.stats['total_books'] = len(self.reports)
        self.stats['passed_books'] = sum(1 for r in self.reports if r.passed)
        self.stats['failed_books'] = self.stats['total_books'] - self.stats['passed_books']

        # 按优先级统计
        self.stats['high_priority'] = sum(1 for r in self.reports if r.repair_priority == 'HIGH')
        self.stats['medium_priority'] = sum(1 for r in self.reports if r.repair_priority == 'MEDIUM')
        self.stats['low_priority'] = sum(1 for r in self.reports if r.repair_priority == 'LOW')

        # 统计各类问题
        for report in self.reports:
            stats = report.stats

            if stats.get('placeholder_count', 0) > 0:
                self.stats['placeholder_issues'] += 1

            if stats.get('merged_chapters', []):
                self.stats['merged_chapter_issues'] += 1

            if stats.get('template_count', 0) > 0:
                self.stats['template_issues'] += 1

            if stats.get('empty_chapters', 0) > 0:
                self.stats['empty_chapter_issues'] += 1

    def generate_report(self, output_path: Optional[str] = None) -> str:
        """
        生成质量检查报告

        Args:
            output_path: 输出文件路径（可选）

        Returns:
            str: 报告内容
        """
        report = f"""# BookGraph 批量质量检查报告

**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Vault路径**: {self.vault_path}

## 总体统计

| 指标 | 数值 | 百分比 |
|------|------|--------|
| 总书籍数 | {self.stats['total_books']} | 100% |
| ✅ 通过书籍 | {self.stats['passed_books']} | {self.stats['passed_books']/max(1,self.stats['total_books'])*100:.1f}% |
| ❌ 不合格书籍 | {self.stats['failed_books']} | {self.stats['failed_books']/max(1,self.stats['total_books'])*100:.1f}% |

## 修复优先级分布

| 优先级 | 数量 | 说明 |
|--------|------|------|
| 🔴 HIGH | {self.stats['high_priority']} | 分数<50，严重质量问题 |
| 🟡 MEDIUM | {self.stats['medium_priority']} | 分数50-70，需要修复 |
| 🟢 LOW | {self.stats['low_priority']} | 分数70-80，轻微问题 |

## 问题类型分布

| 问题类型 | 影响书籍数 | 说明 |
|----------|-----------|------|
| 🔑 占位符污染 | {self.stats['placeholder_issues']} | 含"待补充"、"N/A"等 |
| 🔑 章节合并 | {self.stats['merged_chapter_issues']} | LLM用"11-22章"偷懒 |
| 🟡 模板化内容 | {self.stats['template_issues']} | 模板填充未修改 |
| 🟡 空洞章节 | {self.stats['empty_chapter_issues']} | 章节内容为空 |

---

## 需要修复的书籍列表

"""

        # 添加高优先级书籍
        high_priority_books = [r for r in self.reports if r.repair_priority == 'HIGH']
        if high_priority_books:
            report += "### 🔴 高优先级（分数<50）\n\n"
            for r in sorted(high_priority_books, key=lambda x: x.score, reverse=True):
                report += f"#### {r.book_name}\n\n"
                report += f"- **文件路径**: `{r.file_path}`\n"
                report += f"- **质量分数**: {r.score:.0f}/100\n"
                report += f"- **JSON文件**: {'✅' if r.json_path else '❌ 无'}\n"

                if r.issues:
                    report += f"- **严重问题**:\n"
                    for issue in r.issues[:5]:
                        report += f"  - ❌ {issue}\n"

                if r.stats.get('placeholder_count', 0) > 0:
                    report += f"- **占位符数量**: {r.stats['placeholder_count']}\n"

                if r.stats.get('merged_chapters', []):
                    merged = [f"'{ch.get('chapter_number', '')}'" for ch in r.stats['merged_chapters']]
                    report += f"- **合并章节**: {', '.join(merged[:5])}\n"

                report += "\n"

        # 添加中优先级书籍
        medium_priority_books = [r for r in self.reports if r.repair_priority == 'MEDIUM']
        if medium_priority_books:
            report += "### 🟡 中优先级（分数50-70）\n\n"
            for r in sorted(medium_priority_books, key=lambda x: x.score, reverse=True)[:20]:
                report += f"#### {r.book_name}\n\n"
                report += f"- **质量分数**: {r.score:.0f}/100\n"
                report += f"- **文件路径**: `{r.file_path}`\n"

                if r.warnings:
                    report += f"- **警告问题**:\n"
                    for warning in r.warnings[:3]:
                        report += f"  - ⚠️ {warning}\n"

                report += "\n"

        # 添加修复建议
        report += self._generate_repair_suggestions()

        # 保存报告
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"报告已保存: {output_path}")

        return report

    def _generate_repair_suggestions(self) -> str:
        """生成修复建议"""
        suggestions = """---

## 修复建议

### 🔴 高优先级修复策略

针对分数<50的书籍，建议：

1. **占位符污染修复**：
   - 重新处理书籍，使用两阶段摄取（two_stage_ingest）
   - 启用质量门控（quality_gate）自动重试
   - 手动补充缺失内容

2. **章节合并修复**：
   - 重新处理书籍，强制 LLM 生成所有章节
   - 增加并发度（chunk_size降低）
   - 使用多轮合成（multi_round_synthesis）

3. **空洞章节修复**：
   - 检查原始书籍文件是否完整
   - 调整解析器参数（chunk_size, overlap）
   - 手动补充章节内容

### 🟡 中优先级修复策略

针对分数50-70的书籍，建议：

1. **模板化内容修复**：
   - 重新处理相关章节
   - 使用更具体的提示词
   - 手动修改模板化表述

2. **底层逻辑缺失修复**：
   - 补充前提假设、推理链条、核心结论
   - 使用结构化输出强制格式

3. **金句/洞见不足修复**：
   - 重新提取金句
   - 手动补充关键洞见

---

## 执行修复

### 方案1：批量重新处理

```bash
# 创建修复清单
python scripts/batch_quality_check.py --vault "/path/to/vault" --export-repair-list

# 批量重新处理高优先级书籍
python main.py --input repair_list_high.json --workers 2 --force
```

### 方案2：选择性修复

```bash
# 修复单本书籍
python main.py --input "/path/to/book.pdf" --force --quality-gate

# 修复特定章节
python main.py --input "/path/to/book.pdf" --repair-chapters "11,12,13"
```

---

## 质量监控

建议定期执行质量检查：

```bash
# 每周质量检查
python scripts/batch_quality_check.py --vault "/path/to/vault"

# 生成趋势报告
python scripts/batch_quality_check.py --vault "/path/to/vault" --trend
```

"""

        return suggestions

    def export_repair_list(self, output_path: str, priority: str = 'all'):
        """
        导出修复清单（JSON格式）

        Args:
            output_path: 输出文件路径
            priority: 优先级过滤（all/high/medium/low）
        """
        repair_list = []

        for report in self.reports:
            if not report.needs_repair:
                continue

            # 优先级过滤
            if priority != 'all' and report.repair_priority.lower() != priority:
                continue

            repair_item = {
                'book_name': report.book_name,
                'file_path': report.file_path,
                'json_path': report.json_path,
                'score': report.score,
                'priority': report.repair_priority,
                'issues': report.issues,
                'warnings': report.warnings,
                'stats': report.stats,
            }

            repair_list.append(repair_item)

        # 按优先级和分数排序
        priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        repair_list.sort(
            key=lambda x: (priority_order.get(x['priority'], 3), -x['score'])
        )

        # 保存
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(repair_list, f, ensure_ascii=False, indent=2)

        logger.info(f"修复清单已导出: {output_path} ({len(repair_list)} 项)")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='BookGraph 批量质量检查')

    parser.add_argument(
        '--vault',
        type=str,
        required=True,
        help='Obsidian Vault 路径'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='quality_report.md',
        help='报告输出路径'
    )

    parser.add_argument(
        '--export-repair-list',
        type=str,
        help='导出修复清单（JSON格式）'
    )

    parser.add_argument(
        '--priority',
        type=str,
        choices=['all', 'high', 'medium', 'low'],
        default='all',
        help='修复清单优先级过滤'
    )

    args = parser.parse_args()

    # 创建检查器
    checker = BatchQualityChecker(args.vault)

    # 执行扫描
    reports = checker.scan_books()

    # 生成报告
    report = checker.generate_report(args.output)
    print(report)

    # 导出修复清单
    if args.export_repair_list:
        checker.export_repair_list(args.export_repair_list, args.priority)


if __name__ == '__main__':
    main()