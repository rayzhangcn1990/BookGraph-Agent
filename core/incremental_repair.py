"""
增量修复系统

支持对已生成但不合格的 BookGraph 进行定向修复，避免全量重新生成。

核心能力：
1. 质量不达标时先落盘，标记问题字段
2. 生成修复清单（JSON + Markdown）
3. 按清单定向修复，而非全量重新生成
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class FixItem:
    """单个修复项"""
    field_path: str          # 字段路径（如 "chapters[0].core_argument"）
    issue_type: str          # 问题类型（占位符/空洞/格式错误等）
    issue_description: str   # 详细描述
    current_value: str       # 当前值（截断到100字符）
    suggested_action: str    # 建议修复动作
    priority: str            # 优先级：CRITICAL / HIGH / MEDIUM


@dataclass
class RepairManifest:
    """修复清单"""
    book_title: str
    generated_at: str
    quality_score: float
    total_issues: int
    fix_items: List[Dict]
    output_path: str
    needs_fix: bool


class IncrementalRepairSystem:
    """增量修复系统"""

    def __init__(self, output_dir: Path):
        """
        初始化

        Args:
            output_dir: 输出目录（Obsidian vault 路径）
        """
        self.output_dir = Path(output_dir)
        self.repair_dir = self.output_dir / ".repair_manifests"
        self.repair_dir.mkdir(parents=True, exist_ok=True)

    def save_partial_result(
        self,
        book_graph_data: Dict,
        quality_report: str,
        quality_stats: Dict,
        original_output_path: Path
    ) -> Tuple[Path, Path, Path]:
        """
        保存部分合格结果（质量不达标时仍落盘）

        Args:
            book_graph_data: BookGraph 数据
            quality_report: 质量报告（Markdown）
            quality_stats: 质量统计（Dict）
            original_output_path: 原始输出路径

        Returns:
            Tuple[Path, Path, Path]: (实际输出路径, 修复清单JSON, 修复清单MD)
        """
        book_title = book_graph_data.get('metadata', {}).get('title', 'Unknown')

        # 1. 生成修复清单
        fix_items = self._analyze_quality_issues(quality_stats, book_graph_data)
        manifest = RepairManifest(
            book_title=book_title,
            generated_at=datetime.now().isoformat(),
            quality_score=quality_stats.get('score', 0),
            total_issues=len(fix_items),
            fix_items=[asdict(item) for item in fix_items],
            output_path=str(original_output_path),
            needs_fix=len(fix_items) > 0
        )

        # 2. 保存修复清单 JSON
        manifest_json_path = self.repair_dir / f"{book_title}_repair_manifest.json"
        with open(manifest_json_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)

        # 3. 生成修复清单 Markdown（人类可读）
        manifest_md_path = self.repair_dir / f"{book_title}_repair_manifest.md"
        self._write_repair_manifest_md(manifest, manifest_md_path)

        # 4. 在原始输出文件添加标记（如果已存在）
        if original_output_path.exists():
            # 读取现有内容
            existing_content = original_output_path.read_text(encoding='utf-8')

            # 添加修复标记到文件头部
            fix_notice = f"""
> [!warning] ⚠️ 质量标记
> 此文件存在 **{len(fix_items)}** 处质量问题，需增量修复。
> 修复清单：[[{manifest_md_path.name}]]
> 生成时间：{manifest.generated_at}

"""
            # 插入到第一个标题之后
            lines = existing_content.split('\n')
            insert_pos = 0
            for i, line in enumerate(lines):
                if line.startswith('#'):
                    insert_pos = i + 1
                    break

            updated_content = '\n'.join(lines[:insert_pos]) + '\n' + fix_notice + '\n'.join(lines[insert_pos:])
            original_output_path.write_text(updated_content, encoding='utf-8')

        return original_output_path, manifest_json_path, manifest_md_path

    def _analyze_quality_issues(
        self,
        quality_stats: Dict,
        book_graph_data: Dict
    ) -> List[FixItem]:
        """
        分析质量问题，生成修复清单

        Args:
            quality_stats: 质量统计
            book_graph_data: BookGraph 数据

        Returns:
            List[FixItem]: 修复项列表
        """
        fix_items = []

        # 1. 章节合并问题（CRITICAL）
        merged_chapters = quality_stats.get('merged_chapters', [])
        for ch in merged_chapters:
            ch_num = ch.get('chapter_number', '')
            fix_items.append(FixItem(
                field_path=f"chapters[chapter_number={ch_num}]",
                issue_type="章节合并",
                issue_description=f"章节编号 '{ch_num}' 为合并编号，LLM偷懒行为",
                current_value=str(ch.get('title', ''))[:100],
                suggested_action="拆分为独立章节，逐章分析",
                priority="CRITICAL"
            ))

        # 2. 章节占位符问题（CRITICAL）
        placeholder_chapters = quality_stats.get('placeholder_chapters', [])
        for pch in placeholder_chapters:
            ch = pch.get('chapter', {})
            kw = pch.get('keyword', '')
            field = pch.get('field', '')
            ch_num = ch.get('chapter_number', '')
            fix_items.append(FixItem(
                field_path=f"chapters[chapter_number={ch_num}].{field}",
                issue_type="章节占位符",
                issue_description=f"章节含占位符 '{kw}'，内容敷衍",
                current_value=str(ch.get(field, ''))[:100],
                suggested_action="重新生成该章节内容",
                priority="CRITICAL"
            ))

        # 3. 章节覆盖率不足（HIGH）
        coverage = quality_stats.get('chapter_coverage', 1.0)
        if coverage < 0.8:
            fix_items.append(FixItem(
                field_path="chapters",
                issue_type="章节覆盖率不足",
                issue_description=f"覆盖率 {coverage*100:.0f}%，应有更多章节",
                current_value=f"{quality_stats.get('chapter_count', 0)}/{quality_stats.get('expected_chapters', 0)}",
                suggested_action="补充缺失章节",
                priority="HIGH"
            ))

        # 4. 概念占位符（HIGH）
        placeholder_concepts = quality_stats.get('placeholder_concepts', 0)
        if placeholder_concepts > 0:
            concepts = book_graph_data.get('core_concepts', [])
            for idx, concept in enumerate(concepts):
                # 检查是否有占位符
                for field in ['definition', 'deep_meaning', 'underlying_logic']:
                    value = str(concept.get(field, ''))
                    if any(kw in value for kw in ['待补充', 'TBD', 'TODO', 'N/A']):
                        fix_items.append(FixItem(
                            field_path=f"core_concepts[{idx}].{field}",
                            issue_type="概念占位符",
                            issue_description=f"概念 '{concept.get('name', '')}' 字段 '{field}' 含占位符",
                            current_value=value[:100],
                            suggested_action="补充概念的实质性内容",
                            priority="HIGH"
                        ))
                        break

        # 5. 浅薄概念（MEDIUM）
        shallow_concepts = quality_stats.get('shallow_concepts', 0)
        if shallow_concepts > 0:
            concepts = book_graph_data.get('core_concepts', [])
            for idx, concept in enumerate(concepts):
                def_len = len(concept.get('definition', ''))
                deep_len = len(concept.get('deep_meaning', ''))
                if def_len < 30 or deep_len < 30:
                    fix_items.append(FixItem(
                        field_path=f"core_concepts[{idx}]",
                        issue_type="浅薄概念",
                        issue_description=f"概念 '{concept.get('name', '')}' 定义过短 ({def_len}字符)",
                        current_value=concept.get('definition', '')[:100],
                        suggested_action="扩展概念定义和深层含义",
                        priority="MEDIUM"
                    ))

        # 6. 占位符污染（CRITICAL）
        placeholder_count = quality_stats.get('placeholder_count', 0)
        if placeholder_count > 5:
            fix_items.append(FixItem(
                field_path="全局",
                issue_type="占位符污染严重",
                issue_description=f"发现 {placeholder_count} 处占位符",
                current_value="-",
                suggested_action="全局清理占位符，补充实质内容",
                priority="CRITICAL"
            ))

        # 7. 金句不足（MEDIUM）
        quote_count = quality_stats.get('quote_count', 0)
        if quote_count < 3:
            fix_items.append(FixItem(
                field_path="key_quotes",
                issue_type="金句数量不足",
                issue_description=f"仅 {quote_count} 条金句，应有更多",
                current_value="-",
                suggested_action="从原文提取更多高质量金句",
                priority="MEDIUM"
            ))

        # 8. 底层逻辑格式（MEDIUM）
        logic_score = quality_stats.get('logic_score', 0)
        if logic_score < 0.8:
            chapters = book_graph_data.get('chapters', [])
            for idx, ch in enumerate(chapters):
                logic = ch.get('underlying_logic', '')
                if logic and not ('前提假设' in logic and '推理链条' in logic and '核心结论' in logic):
                    fix_items.append(FixItem(
                        field_path=f"chapters[{idx}].underlying_logic",
                        issue_type="底层逻辑格式错误",
                        issue_description="应包含：前提假设 / 推理链条 / 核心结论",
                        current_value=logic[:100],
                        suggested_action="按标准格式重写底层逻辑",
                        priority="MEDIUM"
                    ))

        # 按优先级排序
        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2}
        fix_items.sort(key=lambda x: priority_order.get(x.priority, 99))

        return fix_items

    def _write_repair_manifest_md(self, manifest: RepairManifest, output_path: Path):
        """
        生成人类可读的修复清单 Markdown

        Args:
            manifest: 修复清单
            output_path: 输出路径
        """
        md_content = f"""# 📋 修复清单：{manifest.book_title}

**生成时间**：{manifest.generated_at}
**质量评分**：{manifest.quality_score:.0f}/100
**问题总数**：{manifest.total_issues}
**输出文件**：`{manifest.output_path}`

---

## 🚨 需修复项（按优先级排序）

"""

        # 按优先级分组
        critical_items = [item for item in manifest.fix_items if item['priority'] == 'CRITICAL']
        high_items = [item for item in manifest.fix_items if item['priority'] == 'HIGH']
        medium_items = [item for item in manifest.fix_items if item['priority'] == 'MEDIUM']

        if critical_items:
            md_content += "### 🔴 CRITICAL（必须修复）\n\n"
            for idx, item in enumerate(critical_items, 1):
                md_content += f"#### {idx}. {item['issue_type']}\n\n"
                md_content += f"- **字段路径**：`{item['field_path']}`\n"
                md_content += f"- **问题描述**：{item['issue_description']}\n"
                md_content += f"- **当前值**：`{item['current_value']}`\n"
                md_content += f"- **建议操作**：{item['suggested_action']}\n\n"

        if high_items:
            md_content += "### 🟠 HIGH（高优先级）\n\n"
            for idx, item in enumerate(high_items, 1):
                md_content += f"#### {idx}. {item['issue_type']}\n\n"
                md_content += f"- **字段路径**：`{item['field_path']}`\n"
                md_content += f"- **问题描述**：{item['issue_description']}\n"
                md_content += f"- **当前值**：`{item['current_value']}`\n"
                md_content += f"- **建议操作**：{item['suggested_action']}\n\n"

        if medium_items:
            md_content += "### 🟡 MEDIUM（中优先级）\n\n"
            for idx, item in enumerate(medium_items, 1):
                md_content += f"#### {idx}. {item['issue_type']}\n\n"
                md_content += f"- **字段路径**：`{item['field_path']}`\n"
                md_content += f"- **问题描述**：{item['issue_description']}\n"
                md_content += f"- **当前值**：`{item['current_value']}`\n"
                md_content += f"- **建议操作**：{item['suggested_action']}\n\n"

        md_content += """---

## 🔧 修复指南

### 如何使用此清单

1. **定位问题**：根据 `字段路径` 找到需要修复的字段
2. **理解问题**：阅读 `问题描述` 了解具体问题
3. **执行修复**：按照 `建议操作` 进行修复
4. **验证修复**：修复后重新运行质量检查

### 批量修复命令

```bash
# 针对单本书修复
python main.py --input "book.epub" --repair-manifest ".repair_manifests/{book_title}_repair_manifest.json"

# 批量修复所有待修复书籍
python batch_repair.py --manifest-dir ".repair_manifests/"
```

### 增量修复原则

- ✅ **只修复标记的问题字段**，不重新生成整本书
- ✅ **保持已合格内容不变**，避免引入新问题
- ✅ **修复后更新修复清单**，标记为已修复
"""

        output_path.write_text(md_content, encoding='utf-8')


def get_repair_system(output_dir: Path) -> IncrementalRepairSystem:
    """获取增量修复系统实例"""
    return IncrementalRepairSystem(output_dir)
