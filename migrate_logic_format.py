#!/usr/bin/env python3
"""
迁移底层逻辑格式（全面版）

功能：
1. 标签规范化：前提→前提假设，推理→推理链条，结论→核心结论
2. 格式转换：核心概念/关键洞见/学科核心思想的底层逻辑从代码块转为三行列表
3. 检测章节表格中被截断的底层逻辑（标记需重新生成的书籍）

扫描范围：整个知识图谱目录
"""

import re
from pathlib import Path

KNOWLEDGE_GRAPH_ROOT = Path("/Users/rayzhang/Documents/知识体系/📚 知识图谱")


def normalize_labels(logic_text: str) -> str:
    """规范化标签名称：前提→前提假设，推理→推理链条，结论→核心结论"""
    text = logic_text.strip()

    # 模式 1: 前提：→推理：→结论：
    text = re.sub(
        r'前提：(.+?)→推理：(.+?)→结论：(.+?)(?=\n|$)',
        lambda m: f'前提假设：{m.group(1).strip()}→推理链条：{m.group(2).strip()}→核心结论：{m.group(3).strip()}',
        text
    )
    # 模式 2: 前提假设：→推理：→结论：
    text = re.sub(
        r'前提假设：(.+?)→推理：(.+?)→结论：(.+?)(?=\n|$)',
        lambda m: f'前提假设：{m.group(1).strip()}→推理链条：{m.group(2).strip()}→核心结论：{m.group(3).strip()}',
        text
    )
    # 模式 3: 前提：→推理链条：→结论：
    text = re.sub(
        r'前提：(.+?)→推理链条：(.+?)→结论：(.+?)(?=\n|$)',
        lambda m: f'前提假设：{m.group(1).strip()}→推理链条：{m.group(2).strip()}→核心结论：{m.group(3).strip()}',
        text
    )

    return text


def convert_logic_to_three_lines(logic_text: str) -> str:
    """将单行底层逻辑转换为三行格式（含标签规范化）"""
    text = normalize_labels(logic_text)

    # 匹配完整格式：前提假设：xxx→推理链条：xxx→核心结论：xxx
    pattern = r'前提假设：(.+?)→推理链条：(.+?)→核心结论：(.+)$'
    m = re.match(pattern, text)
    if m:
        premise = m.group(1).strip()
        reasoning = m.group(2).strip()
        conclusion = m.group(3).strip()
        return (
            f"- **前提假设**：{premise}\n"
            f"- **推理链条**：{reasoning}\n"
            f"- **核心结论**：{conclusion}"
        )

    # 已经是多行格式或其他格式
    lines = text.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('-'):
            result.append(f"- {stripped}")
        elif stripped:
            result.append(stripped)
    return '\n'.join(result) if result else text


def process_file(file_path: Path) -> dict:
    """处理单个文件，返回修改统计"""
    content = file_path.read_text(encoding='utf-8')
    original = content
    stats = {'labels_normalized': 0, 'blocks_converted': 0}

    # ═══════════════════════════════════════════════════
    # 1. 规范化所有行内底层逻辑标签
    # ═══════════════════════════════════════════════════
    # 匹配表格和行内出现的 "前提：...→推理：...→结论：..." 变体
    for old_pat, new_pat in [
        (r'前提：(.+?)→推理：(.+?)→结论：(.+?)(?=\n|\||$)', '前提假设：\\1→推理链条：\\2→核心结论：\\3'),
    ]:
        new_content = re.sub(old_pat, lambda m: f'前提假设：{m.group(1).strip()}→推理链条：{m.group(2).strip()}→核心结论：{m.group(3).strip()}', content)
        if new_content != content:
            stats['labels_normalized'] += content.count('前提：') - new_content.count('前提：')
            content = new_content

    # 修复 "前提假设：→推理：→结论：" 变体
    content = re.sub(
        r'前提假设：(.+?)→推理：(.+?)→结论：(.+?)(?=\n|\||$)',
        lambda m: f'前提假设：{m.group(1).strip()}→推理链条：{m.group(2).strip()}→核心结论：{m.group(3).strip()}',
        content
    )
    # 修复 "前提：→推理链条：→结论：" 变体
    content = re.sub(
        r'前提：(.+?)→推理链条：(.+?)→结论：(.+?)(?=\n|\||$)',
        lambda m: f'前提假设：{m.group(1).strip()}→推理链条：{m.group(2).strip()}→核心结论：{m.group(3).strip()}',
        content
    )

    # ═══════════════════════════════════════════════════
    # 2. 转换代码块中的底层逻辑为三行列表
    # ═══════════════════════════════════════════════════
    # 匹配：
    # **底层逻辑**：
    # ```
    # 前提假设：xxx→推理链条：xxx→核心结论：xxx
    # ```
    block_pattern = re.compile(
        r'(\*\*底层逻辑\*\*：\s*\n)```\s*\n(.*?)\n```',
        re.DOTALL
    )

    def replace_block(match):
        header = match.group(1)
        logic_content = match.group(2).strip()
        three_lines = convert_logic_to_three_lines(logic_content)
        stats['blocks_converted'] += 1
        return f"{header}\n{three_lines}"

    content = block_pattern.sub(replace_block, content)

    if content != original:
        file_path.write_text(content, encoding='utf-8')

    return stats


def check_truncated_logic(file_path: Path) -> list:
    """检测章节表格中被截断的底层逻辑"""
    truncated = []
    content = file_path.read_text(encoding='utf-8')

    # 匹配表格行中底层逻辑列以 ... 结尾的行
    for line in content.split('\n'):
        if re.search(r'\| \d+ \| .+? \| .+? \| .+?\.\.\.(?=\s*\|)', line):
            chapter_match = re.search(r'\| (\d+) \| (.+?) \|', line)
            if chapter_match:
                truncated.append(f"第{chapter_match.group(1)}章: {chapter_match.group(2)}")

    return truncated


def main():
    print("=" * 70)
    print("底层逻辑格式迁移工具（全面版）")
    print("=" * 70)
    print()
    print("功能：")
    print("  1. 标签规范化：前提→前提假设，推理→推理链条，结论→核心结论")
    print("  2. 格式转换：代码块 → 三行列表")
    print("  3. 检测截断：标记章节表格中被截断的底层逻辑")
    print()

    if not KNOWLEDGE_GRAPH_ROOT.exists():
        print(f"错误：目录不存在 - {KNOWLEDGE_GRAPH_ROOT}")
        return

    total = 0
    modified = 0
    total_labels = 0
    total_blocks = 0
    truncated_books = []

    for md_file in sorted(KNOWLEDGE_GRAPH_ROOT.rglob("*.md")):
        if md_file.name.startswith('.'):
            continue
        total += 1

        # 处理文件
        stats = process_file(md_file)
        if stats['labels_normalized'] > 0 or stats['blocks_converted'] > 0:
            modified += 1
            total_labels += stats['labels_normalized']
            total_blocks += stats['blocks_converted']
            rel = md_file.relative_to(KNOWLEDGE_GRAPH_ROOT)
            parts = []
            if stats['labels_normalized']:
                parts.append(f"规范化{stats['labels_normalized']}处")
            if stats['blocks_converted']:
                parts.append(f"转换{stats['blocks_converted']}个代码块")
            print(f"  [已更新] {rel} ({', '.join(parts)})")

        # 检测截断
        trunc = check_truncated_logic(md_file)
        if trunc:
            truncated_books.append((md_file, trunc))

    print()
    print("=" * 70)
    print(f"处理完成：共 {total} 个文件，更新 {modified} 个")
    print(f"  - 标签规范化：{total_labels} 处")
    print(f"  - 代码块转换：{total_blocks} 个")

    if truncated_books:
        print()
        print(f"以下 {len(truncated_books)} 个文件存在截断的底层逻辑（需重新生成）：")
        for f, chapters in truncated_books:
            print(f"  - {f.relative_to(KNOWLEDGE_GRAPH_ROOT)}")
            for ch in chapters:
                print(f"      {ch}")

    print()


if __name__ == "__main__":
    main()
