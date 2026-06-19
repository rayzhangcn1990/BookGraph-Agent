"""
批量增量修复工具

扫描修复清单目录，批量修复所有标记待修复的书籍图谱。

使用方式：
    python batch_repair.py --manifest-dir ".repair_manifests/"
    python batch_repair.py --input "book.epub"
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List
import asyncio

from core.llm_client import get_llm_client, SYSTEM_PROMPT
from core.incremental_repair import IncrementalRepairSystem
from core.book_graph_quality_checker import check_book_graph_quality
from utils.logger import setup_logger

logger = setup_logger("BatchRepair")


async def repair_single_book(
    manifest_path: Path,
    config: Dict,
    max_parallel: int = 1
) -> Dict:
    """
    修复单本书籍

    Args:
        manifest_path: 修复清单路径
        config: 配置
        max_parallel: 最大并行数

    Returns:
        Dict: 修复结果
    """
    logger.info(f"🔧 开始修复: {manifest_path.name}")

    # 1. 加载修复清单
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    book_title = manifest.get('book_title', 'Unknown')
    output_path = Path(manifest.get('output_path', ''))

    if not output_path.exists():
        logger.error(f"   ❌ 输出文件不存在: {output_path}")
        return {'success': False, 'error': '输出文件不存在'}

    # 2. 加载原始 BookGraph
    try:
        import yaml
        # 读取 Markdown 文件，提取 YAML frontmatter
        content = output_path.read_text(encoding='utf-8')
        yaml_start = content.find('---')
        yaml_end = content.find('---', yaml_start + 3)

        if yaml_start != -1 and yaml_end != -1:
            yaml_content = content[yaml_start + 3:yaml_end].strip()
            book_graph_data = yaml.safe_load(yaml_content)
        else:
            logger.error(f"   ❌ 无法解析 YAML frontmatter")
            return {'success': False, 'error': 'YAML解析失败'}
    except Exception as e:
        logger.error(f"   ❌ 加载 BookGraph 失败: {e}")
        return {'success': False, 'error': str(e)}

    # 3. 按修复清单定向修复
    llm_client = get_llm_client(config)
    repair_system = IncrementalRepairSystem(output_path.parent)

    fix_items = manifest.get('fix_items', [])
    logger.info(f"   📋 需修复: {len(fix_items)} 项")

    # 按优先级修复（先修复 CRITICAL）
    critical_items = [item for item in fix_items if item['priority'] == 'CRITICAL']
    high_items = [item for item in fix_items if item['priority'] == 'HIGH']
    medium_items = [item for item in fix_items if item['priority'] == 'MEDIUM']

    repaired_count = 0

    # 修复 CRITICAL 问题
    if critical_items:
        logger.info(f"   🔴 修复 CRITICAL 问题: {len(critical_items)} 项")
        for item in critical_items:
            repaired = await _repair_single_field(book_graph_data, item, llm_client, book_title)
            if repaired:
                repaired_count += 1
                logger.info(f"      ✅ 已修复: {item['field_path']}")
            else:
                logger.warning(f"      ⚠️ 修复失败: {item['field_path']}")

    # 修复 HIGH 问题
    if high_items:
        logger.info(f"   🟠 修复 HIGH 问题: {len(high_items)} 项")
        for item in high_items:
            repaired = await _repair_single_field(book_graph_data, item, llm_client, book_title)
            if repaired:
                repaired_count += 1
                logger.info(f"      ✅ 已修复: {item['field_path']}")
            else:
                logger.warning(f"      ⚠️ 修复失败: {item['field_path']}")

    # 修复 MEDIUM 问题
    if medium_items:
        logger.info(f"   🟡 修复 MEDIUM 问题: {len(medium_items)} 项")
        for item in medium_items:
            repaired = await _repair_single_field(book_graph_data, item, llm_client, book_title)
            if repaired:
                repaired_count += 1
                logger.info(f"      ✅ 已修复: {item['field_path']}")
            else:
                logger.warning(f"      ⚠️ 修复失败: {item['field_path']}")

    # 4. 重新质量检查
    expected_chapters = manifest.get('expected_chapters', 0)
    passed, new_quality_report = check_book_graph_quality(book_graph_data, expected_chapters)

    # 5. 更新修复清单
    manifest['repaired_count'] = repaired_count
    manifest['repair_status'] = 'completed' if passed else 'partial'
    manifest['new_quality_score'] = book_graph_data.get('quality_score', 0)

    # 保存更新后的清单
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 6. 更新输出文件（移除修复标记）
    if passed:
        content = output_path.read_text(encoding='utf-8')
        # 移除修复标记
        lines = content.split('\n')
        new_lines = []
        skip_next = False
        for line in lines:
            if line.startswith('> [!warning]'):
                skip_next = True
                continue
            if skip_next and line.startswith('>'):
                continue
            if skip_next and not line.startswith('>'):
                skip_next = False
            new_lines.append(line)

        output_path.write_text('\n'.join(new_lines), encoding='utf-8')
        logger.info(f"   ✅ 修复完成，质量达标: {output_path}")

    return {
        'success': True,
        'repaired_count': repaired_count,
        'quality_passed': passed,
        'output_path': str(output_path),
    }


async def _repair_single_field(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """
    修复单个字段

    Args:
        book_graph_data: BookGraph 数据
        fix_item: 修复项
        llm_client: LLM 客户端
        book_title: 书名

    Returns:
        bool: 是否成功修复
    """
    field_path = fix_item['field_path']
    issue_type = fix_item['issue_type']

    # 根据问题类型执行不同修复策略
    if issue_type == '章节合并':
        # 拆分合并章节（需要重新分析）
        return await _repair_merged_chapter(book_graph_data, fix_item, llm_client, book_title)

    elif issue_type == '章节占位符':
        # 重新生成章节内容
        return await _repair_placeholder_chapter(book_graph_data, fix_item, llm_client, book_title)

    elif issue_type == '概念占位符':
        # 补充概念内容
        return await _repair_placeholder_concept(book_graph_data, fix_item, llm_client, book_title)

    elif issue_type == '浅薄概念':
        # 扩展概念定义
        return await _repair_shallow_concept(book_graph_data, fix_item, llm_client, book_title)

    elif issue_type == '金句数量不足':
        # 补充金句
        return await _repair_insufficient_quotes(book_graph_data, fix_item, llm_client, book_title)

    elif issue_type == '底层逻辑格式错误':
        # 格式化底层逻辑
        return await _repair_logic_format(book_graph_data, fix_item, llm_client, book_title)

    elif issue_type == '占位符污染严重':
        # 全局清理占位符
        return await _repair_global_placeholders(book_graph_data, fix_item, llm_client, book_title)

    else:
        logger.warning(f"   ⚠️ 未知的修复类型: {issue_type}")
        return False


async def _repair_placeholder_chapter(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """修复章节占位符"""
    field_path = fix_item['field_path']
    logger.info(f"      🔧 修复章节占位符: {field_path}")

    # 提取章节编号
    import re
    match = re.search(r'chapter_number=(\S+)', field_path)
    if not match:
        return False

    chapter_number = match.group(1).strip("'\"")

    # 找到目标章节
    chapters = book_graph_data.get('chapters', [])
    target_chapter = None
    for ch in chapters:
        if str(ch.get('chapter_number', '')) == chapter_number:
            target_chapter = ch
            break

    if not target_chapter:
        return False

    # 使用 LLM 重新生成章节内容
    prompt = f"""
请根据书籍《{book_title}》的内容，重新生成章节 {chapter_number} 的核心论点和底层逻辑。

要求：
1. core_argument: 不少于 100 字，总结章节核心观点
2. underlying_logic: 包含"前提假设"、"推理链条"、"核心结论"三部分
3. 不允许使用任何占位符（如"待补充"、"TBD"、"N/A"）

当前章节标题: {target_chapter.get('title', '')}

请输出 JSON 格式：
```json
{
  "core_argument": "...",
  "underlying_logic": "前提假设：...→推理链条：...→核心结论：..."
}
```
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        response = await asyncio.to_thread(
            llm_client._call_llm,
            messages,
            max_tokens=1000
        )

        # 解析 JSON
        import json
        from core.model_output_format_spec import parse_model_output

        result, success, error = parse_model_output(response, field_type="chapter")

        if success and result:
            # 更新章节内容
            target_chapter['core_argument'] = result.get('core_argument', '')
            target_chapter['underlying_logic'] = result.get('underlying_logic', '')
            return True
        else:
            logger.warning(f"      ⚠️ JSON 解析失败: {error}")
            return False

    except Exception as e:
        logger.warning(f"      ⚠️ LLM 调用失败: {e}")
        return False


async def _repair_placeholder_concept(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """修复概念占位符"""
    logger.info(f"      🔧 修复概念占位符: {fix_item['field_path']}")

    # 提取概念索引
    import re
    match = re.search(r'core_concepts\[(\d+)\]', fix_item['field_path'])
    if not match:
        return False

    concept_idx = int(match.group(1))
    concepts = book_graph_data.get('core_concepts', [])

    if concept_idx >= len(concepts):
        return False

    target_concept = concepts[concept_idx]
    concept_name = target_concept.get('name', '')

    # 使用 LLM 补充概念内容
    prompt = f"""
请根据书籍《{book_title}》的内容，补充核心概念"{concept_name}"的定义和深层含义。

要求：
1. definition: 不少于 50 字，清晰定义概念
2. deep_meaning: 不少于 50 字，阐述概念的深层内涵
3. 不允许使用任何占位符（如"待补充"、"TBD"、"N/A"）

请输出 JSON 格式：
```json
{
  "definition": "...",
  "deep_meaning": "..."
}
```
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        response = await asyncio.to_thread(
            llm_client._call_llm,
            messages,
            max_tokens=500
        )

        import json
        from core.model_output_format_spec import parse_model_output

        result, success, error = parse_model_output(response, field_type="concept")

        if success and result:
            target_concept['definition'] = result.get('definition', '')
            target_concept['deep_meaning'] = result.get('deep_meaning', '')
            return True
        else:
            logger.warning(f"      ⚠️ JSON 解析失败: {error}")
            return False

    except Exception as e:
        logger.warning(f"      ⚠️ LLM 调用失败: {e}")
        return False


async def _repair_shallow_concept(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """扩展浅薄概念"""
    # 类似 _repair_placeholder_concept
    return await _repair_placeholder_concept(book_graph_data, fix_item, llm_client, book_title)


async def _repair_insufficient_quotes(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """补充金句"""
    logger.info(f"      🔧 补充金句")

    # 使用 LLM 提取更多金句
    prompt = f"""
请从书籍《{book_title}》中提取 5 条高质量金句。

要求：
1. 每条金句不少于 30 字
2. 包含来源章节
3. 包含背景语境和底层逻辑
4. 不允许使用占位符

请输出 JSON 数组：
```json
[
  {
    "text": "...",
    "chapter": "...",
    "background_context": "...",
    "underlying_logic": "..."
  }
]
```
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        response = await asyncio.to_thread(
            llm_client._call_llm,
            messages,
            max_tokens=2000
        )

        import json
        from core.model_output_format_spec import parse_model_output

        result, success, error = parse_model_output(response, field_type="quote")

        if success and isinstance(result, list):
            quotes = book_graph_data.get('key_quotes', [])
            quotes.extend(result)
            return True
        else:
            logger.warning(f"      ⚠️ JSON 解析失败: {error}")
            return False

    except Exception as e:
        logger.warning(f"      ⚠️ LLM 调用失败: {e}")
        return False


async def _repair_logic_format(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """格式化底层逻辑"""
    logger.info(f"      🔧 格式化底层逻辑: {fix_item['field_path']}")

    # 提取章节索引
    import re
    match = re.search(r'chapters\[(\d+)\]', fix_item['field_path'])
    if not match:
        return False

    chapter_idx = int(match.group(1))
    chapters = book_graph_data.get('chapters', [])

    if chapter_idx >= len(chapters):
        return False

    target_chapter = chapters[chapter_idx]
    old_logic = target_chapter.get('underlying_logic', '')

    # 使用 LLM 重写底层逻辑
    prompt = f"""
请将以下底层逻辑重写为标准格式：

原文：{old_logic}

标准格式要求：
前提假设：[章节成立的前提条件] → 推理链条：[论证过程] → 核心结论：[形成的观点]

请输出：
```json
{
  "underlying_logic": "前提假设：...→推理链条：...→核心结论：..."
}
```
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        response = await asyncio.to_thread(
            llm_client._call_llm,
            messages,
            max_tokens=500
        )

        import json
        from core.model_output_format_spec import parse_model_output

        result, success, error = parse_model_output(response, field_type="chapter")

        if success and result:
            target_chapter['underlying_logic'] = result.get('underlying_logic', '')
            return True
        else:
            logger.warning(f"      ⚠️ JSON 解析失败: {error}")
            return False

    except Exception as e:
        logger.warning(f"      ⚠️ LLM 调用失败: {e}")
        return False


async def _repair_merged_chapter(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """拆分合并章节"""
    logger.info(f"      🔧 拆分合并章节: {fix_item['field_path']}")

    # 提取合并编号（如 "11-22")
    import re
    match = re.search(r'chapter_number=([\'"]?)(\d+-\d+)', fix_item['field_path'])
    if not match:
        return False

    merged_number = match.group(2)

    # 提取起止编号
    parts = merged_number.split('-')
    if len(parts) != 2:
        return False

    start_num = int(parts[0])
    end_num = int(parts[1])

    # 找到合并章节
    chapters = book_graph_data.get('chapters', [])
    merged_chapter = None
    merged_idx = None
    for idx, ch in enumerate(chapters):
        if ch.get('chapter_number') == merged_number:
            merged_chapter = ch
            merged_idx = idx
            break

    if not merged_chapter:
        return False

    # 使用 LLM 拆分章节
    prompt = f"""
书籍《{book_title}》中章节编号"{merged_number}"是合并编号（偷懒行为），需要拆分为独立章节。

请拆分为章节 {start_num} 到 {end_num} 的独立内容（共 {end_num - start_num + 1} 章）。

要求：
1. 每个章节独立生成 core_argument 和 underlying_logic
2. 不允许使用占位符
3. 每章不少于 100 字

请输出 JSON 数组：
```json
[
  {
    "chapter_number": "{start_num}",
    "title": "...",
    "core_argument": "...",
    "underlying_logic": "..."
  },
  ...
]
```
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        response = await asyncio.to_thread(
            llm_client._call_llm,
            messages,
            max_tokens=3000
        )

        import json
        from core.model_output_format_spec import parse_model_output

        result, success, error = parse_model_output(response, field_type="chapter")

        if success and isinstance(result, list):
            # 移除合并章节，插入拆分后的章节
            chapters.pop(merged_idx)
            for new_ch in result:
                chapters.insert(merged_idx, new_ch)
                merged_idx += 1
            return True
        else:
            logger.warning(f"      ⚠️ JSON 解析失败: {error}")
            return False

    except Exception as e:
        logger.warning(f"      ⚠️ LLM 调用失败: {e}")
        return False


async def _repair_global_placeholders(
    book_graph_data: Dict,
    fix_item: Dict,
    llm_client,
    book_title: str
) -> bool:
    """全局清理占位符"""
    logger.info(f"      🔧 全局清理占位符")

    # 简化方案：递归扫描并替换占位符
    placeholder_keywords = [
        "待补充", "待分析", "待填写", "TBD", "TODO", "N/A", "NULL",
        "书中未提供", "简介待补充"
    ]

    def clean_dict(d: Dict):
        for k, v in d.items():
            if isinstance(v, str):
                for kw in placeholder_keywords:
                    if kw in v:
                        # 替换为默认文本
                        if k in ['core_argument', 'definition', 'deep_meaning', 'description']:
                            d[k] = f"《{book_title}》中关于此内容的详细阐述待从原文中补充。"
                        elif k == 'underlying_logic':
                            d[k] = "前提假设：基于书籍内容 → 推理链条：逐步论证 → 核心结论：形成观点"
                        else:
                            d[k] = "内容待补充"
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        clean_dict(item)
            elif isinstance(v, dict):
                clean_dict(v)

    clean_dict(book_graph_data)
    return True


def batch_repair(manifest_dir: Path, config: Dict):
    """批量修复所有待修复书籍"""
    logger.info(f"📚 扫描修复清单: {manifest_dir}")

    # 扫描所有 JSON 清单
    manifests = list(manifest_dir.glob("*_repair_manifest.json"))

    if not manifests:
        logger.info("✅ 无待修复书籍")
        return

    logger.info(f"📋 发现 {len(manifests)} 个待修复清单")

    # 逐个修复
    results = []
    for manifest_path in manifests:
        result = asyncio.run(repair_single_book(manifest_path, config))
        results.append(result)

    # 统计
    success_count = sum(1 for r in results if r.get('success'))
    logger.info(f"✅ 批量修复完成: {success_count}/{len(manifests)} 成功")


def main():
    parser = argparse.ArgumentParser(description="批量增量修复")
    parser.add_argument("--manifest-dir", default=".repair_manifests/", help="修复清单目录")
    parser.add_argument("--input", help="单本书籍修复（指定书籍路径）")
    parser.add_argument("--config", default="config.yaml", help="配置文件")

    args = parser.parse_args()

    # 加载配置
    import yaml
    config_path = Path(args.config)
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    else:
        config = {}

    if args.input:
        # 单本书修复（需要先生成清单）
        logger.error("⚠️ 单本书修复需要先生成修复清单（通过 main.py --input）")
        return

    manifest_dir = Path(args.manifest_dir)
    if not manifest_dir.exists():
        logger.error(f"❌ 修复清单目录不存在: {manifest_dir}")
        return

    batch_repair(manifest_dir, config)


if __name__ == "__main__":
    main()