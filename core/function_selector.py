#!/usr/bin/env python3
"""
功能选择器模块

基于 MetaGPT 的 Action 模式，提供可插拔的功能模块选择器。
避免因临时任务而生成新代码，所有功能模块预先注册，按需调用。

核心设计：
1. Action 抽象基类：所有功能模块的统一接口
2. ActionRegistry：功能模块注册表
3. FunctionSelector：智能选择器，根据任务自动选择合适的 Action

使用方法：
    from core.function_selector import FunctionSelector

    selector = FunctionSelector()
    action = selector.select("quality_check", vault_path="/path/to/vault")
    result = action.execute()
"""

import os
import sys
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
from datetime import datetime

# 🔑 修复：添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Action 抽象基类（MetaGPT 风格）
# ═══════════════════════════════════════════════════════════

class Action(ABC):
    """
    Action 抽象基类

    所有功能模块必须继承此类，实现 execute() 方法。
    """

    # Action 元信息（子类必须定义）
    name: str = "base_action"
    description: str = "基础动作"
    category: str = "general"
    tags: List[str] = []
    priority: int = 100  # 优先级（数值越小优先级越高）
    requires: List[str] = []  # 依赖的其他 Action

    def __init__(self, **kwargs):
        """初始化 Action，接收参数"""
        self.params = kwargs
        self.result = None
        self.status = "pending"  # pending/running/completed/failed
        self.error = None

    @abstractmethod
    def execute(self) -> Any:
        """
        执行动作

        Returns:
            Any: 执行结果
        """
        pass

    def validate_params(self) -> bool:
        """
        验证参数是否有效

        Returns:
            bool: 参数是否有效
        """
        return True

    def pre_execute(self):
        """执行前钩子"""
        self.status = "running"
        logger.info(f"开始执行 Action: {self.name}")

    def post_execute(self, result: Any):
        """执行后钩子"""
        self.result = result
        self.status = "completed"
        logger.info(f"完成执行 Action: {self.name}")

    def on_error(self, error: Exception):
        """错误处理钩子"""
        self.error = str(error)
        self.status = "failed"
        logger.error(f"Action {self.name} 执行失败: {error}")

    def run(self) -> Any:
        """
        运行 Action（包含生命周期钩子）

        Returns:
            Any: 执行结果
        """
        try:
            # 验证参数
            if not self.validate_params():
                raise ValueError(f"参数验证失败: {self.params}")

            # 执行前钩子
            self.pre_execute()

            # 执行
            result = self.execute()

            # 执行后钩子
            self.post_execute(result)

            return result

        except Exception as e:
            self.on_error(e)
            raise


# ═══════════════════════════════════════════════════════════
# 内置 Action 实现
# ═══════════════════════════════════════════════════════════

class QualityCheckAction(Action):
    """质量检查 Action"""

    name = "quality_check"
    description = "批量质量检查书籍图谱"
    category = "quality"
    tags = ["quality", "batch", "validation"]
    priority = 10

    def validate_params(self) -> bool:
        return "vault_path" in self.params

    def execute(self) -> Dict:
        """执行批量质量检查"""
        from core.book_graph_quality_checker import BookGraphQualityChecker

        vault_path = Path(self.params["vault_path"])
        output_path = self.params.get("output_path", "quality_report.md")
        export_repair_list = self.params.get("export_repair_list", None)

        # 扫描书籍图谱
        reports = []
        book_graph_dirs = []
        for root, dirs, files in os.walk(vault_path):
            if '书籍图谱' in root:
                book_graph_dirs.append(Path(root))

        logger.info(f"找到 {len(book_graph_dirs)} 个书籍图谱目录")

        checker = BookGraphQualityChecker()

        for book_dir in book_graph_dirs:
            md_files = list(book_dir.glob('*.md'))
            md_files = [f for f in md_files if not f.name.endswith('_summary.md')
                       and not f.name.endswith('.mindmap.md')]

            for md_file in md_files:
                book_name = md_file.stem
                json_file = md_file.with_suffix('.json')

                # 读取 JSON 数据
                book_data = {}
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            raw_data = json.load(f)
                            if 'data' in raw_data:
                                book_data = raw_data['data']
                            else:
                                book_data = raw_data
                    except Exception as e:
                        logger.warning(f"读取 JSON 失败: {json_file}")

                # 执行质量检查
                result = checker.check(book_data)

                reports.append({
                    'book_name': book_name,
                    'file_path': str(md_file),
                    'json_path': str(json_file) if json_file.exists() else None,
                    'passed': result.passed,
                    'score': result.score,
                    'issues': result.issues,
                    'warnings': result.warnings,
                    'stats': result.stats,
                })

        # 统计结果
        total = len(reports)
        passed = sum(1 for r in reports if r['passed'])

        result = {
            'total': total,
            'passed': passed,
            'failed': total - passed,
            'reports': reports,
            'timestamp': datetime.now().isoformat(),
        }

        # 生成报告
        if output_path:
            self._generate_report(result, output_path)

        # 导出修复清单
        if export_repair_list:
            self._export_repair_list(reports, export_repair_list)

        return result

    def _generate_report(self, result: Dict, output_path: str):
        """生成质量报告"""
        report = f"""# BookGraph 批量质量检查报告

**检查时间**: {result['timestamp']}
**总计**: {result['total']} 本
**通过**: {result['passed']} 本 ({result['passed']/max(1,result['total'])*100:.1f}%)
**不合格**: {result['failed']} 本

## 需要修复的书籍

"""
        failed_books = [r for r in result['reports'] if not r['passed']]
        failed_books.sort(key=lambda x: x['score'])

        for book in failed_books[:20]:
            report += f"### {book['book_name']}\n\n"
            report += f"- **分数**: {book['score']:.0f}/100\n"
            if book['issues']:
                report += f"- **问题**:\n"
                for issue in book['issues'][:3]:
                    report += f"  - {issue}\n"
            report += "\n"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        logger.info(f"报告已保存: {output_path}")

    def _export_repair_list(self, reports: List[Dict], output_path: str):
        """导出修复清单"""
        repair_list = [r for r in reports if not r['passed'] or r['score'] < 80]
        repair_list.sort(key=lambda x: x['score'])

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(repair_list, f, ensure_ascii=False, indent=2)

        logger.info(f"修复清单已导出: {output_path} ({len(repair_list)} 项)")


class BookProcessAction(Action):
    """书籍处理 Action"""

    name = "book_process"
    description = "处理单本书籍，生成知识图谱"
    category = "process"
    tags = ["book", "process", "graph"]
    priority = 20

    def validate_params(self) -> bool:
        return "input_path" in self.params

    def execute(self) -> Dict:
        """执行书籍处理"""
        from main import process_book

        input_path = self.params["input_path"]
        discipline = self.params.get("discipline", None)
        force = self.params.get("force", False)

        # 调用主处理流程
        result = process_book(
            input_path=input_path,
            discipline=discipline,
            force=force,
        )

        return result


class BatchProcessAction(Action):
    """批量书籍处理 Action"""

    name = "batch_process"
    description = "批量处理书籍目录"
    category = "process"
    tags = ["batch", "process", "graph"]
    priority = 21

    def validate_params(self) -> bool:
        return "input_dir" in self.params

    def execute(self) -> Dict:
        """执行批量处理"""
        from main import process_batch

        input_dir = self.params["input_dir"]
        workers = self.params.get("workers", 2)
        discipline = self.params.get("discipline", None)

        result = process_batch(
            input_dir=input_dir,
            workers=workers,
            discipline=discipline,
        )

        return result


class GraphInsightsAction(Action):
    """图洞察分析 Action"""

    name = "graph_insights"
    description = "分析知识图谱的洞察（社区检测、孤立节点等）"
    category = "analysis"
    tags = ["graph", "insights", "community"]
    priority = 30

    def validate_params(self) -> bool:
        return "vault_path" in self.params

    def execute(self) -> Dict:
        """执行图洞察分析"""
        from core.graph_insights import GraphInsightsAnalyzer

        vault_path = self.params["vault_path"]
        discipline = self.params.get("discipline", None)

        analyzer = GraphInsightsAnalyzer(vault_path)
        result = analyzer.analyze(discipline=discipline)

        return result


class EntityResolutionAction(Action):
    """实体消歧 Action"""

    name = "entity_resolution"
    description = "实体消歧（合并相似概念）"
    category = "analysis"
    tags = ["entity", "resolution", "dedup"]
    priority = 31

    def execute(self) -> Dict:
        """执行实体消歧"""
        # TODO: 实现实体消歧逻辑
        return {"status": "not_implemented"}


class ExportAction(Action):
    """导出 Action"""

    name = "export"
    description = "导出知识图谱为其他格式（JSON、思维导图等）"
    category = "export"
    tags = ["export", "json", "mindmap"]
    priority = 40

    def validate_params(self) -> bool:
        return "output_format" in self.params and "input_path" in self.params

    def execute(self) -> Dict:
        """执行导出"""
        output_format = self.params["output_format"]
        input_path = self.params["input_path"]
        output_path = self.params.get("output_path", None)

        if output_format == "json":
            from exporters.json_exporter import JSONExporter
            exporter = JSONExporter()
            result = exporter.export(input_path, output_path)
        elif output_format == "mindmap":
            from exporters.mindmap_exporter import MindmapExporter
            exporter = MindmapExporter()
            result = exporter.export(input_path, output_path)
        else:
            raise ValueError(f"不支持的导出格式: {output_format}")

        return result


class StatsAction(Action):
    """统计信息 Action"""

    name = "stats"
    description = "显示书籍图谱统计信息"
    category = "info"
    tags = ["stats", "info"]
    priority = 50

    def execute(self) -> Dict:
        """执行统计"""
        vault_path = self.params.get("vault_path", None)

        if not vault_path:
            vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")

        if not vault_path:
            raise ValueError("未指定 vault_path")

        # 统计书籍数量
        book_count = 0
        total_size = 0

        for root, dirs, files in os.walk(vault_path):
            if '书籍图谱' in root:
                for f in files:
                    if f.endswith('.md') and not f.endswith('_summary.md') and not f.endswith('.mindmap.md'):
                        book_count += 1
                        total_size += os.path.getsize(os.path.join(root, f))

        return {
            "book_count": book_count,
            "total_size_mb": total_size / (1024 * 1024),
            "vault_path": vault_path,
        }


# ═══════════════════════════════════════════════════════════
# Action 注册表
# ═══════════════════════════════════════════════════════════

class ActionRegistry:
    """
    Action 注册表

    管理所有可用的 Action，支持注册、查询、列举等操作。
    """

    def __init__(self):
        self._actions: Dict[str, type[Action]] = {}
        self._register_builtin_actions()

    def _register_builtin_actions(self):
        """注册内置 Action"""
        builtin_actions = [
            QualityCheckAction,
            BookProcessAction,
            BatchProcessAction,
            GraphInsightsAction,
            EntityResolutionAction,
            ExportAction,
            StatsAction,
        ]

        for action_cls in builtin_actions:
            self.register(action_cls)

    def register(self, action_cls: type[Action]):
        """
        注册 Action

        Args:
            action_cls: Action 类
        """
        if not issubclass(action_cls, Action):
            raise TypeError(f"{action_cls} 不是 Action 的子类")

        name = action_cls.name
        if name in self._actions:
            logger.warning(f"Action '{name}' 已存在，将被覆盖")

        self._actions[name] = action_cls
        logger.debug(f"注册 Action: {name}")

    def get(self, name: str) -> Optional[type[Action]]:
        """
        获取 Action 类

        Args:
            name: Action 名称

        Returns:
            Optional[type[Action]]: Action 类
        """
        return self._actions.get(name)

    def list(self, category: Optional[str] = None) -> List[type[Action]]:
        """
        列举所有 Action

        Args:
            category: 分类过滤（可选）

        Returns:
            List[type[Action]]: Action 列表
        """
        actions = list(self._actions.values())

        if category:
            actions = [a for a in actions if a.category == category]

        # 按优先级排序
        actions.sort(key=lambda a: a.priority)

        return actions

    def list_by_category(self) -> Dict[str, List[type[Action]]]:
        """
        按分类列举 Action

        Returns:
            Dict[str, List[type[Action]]]: 分类 -> Action 列表
        """
        result = {}

        for action_cls in self._actions.values():
            category = action_cls.category
            if category not in result:
                result[category] = []
            result[category].append(action_cls)

        # 每个分类内按优先级排序
        for category in result:
            result[category].sort(key=lambda a: a.priority)

        return result


# ═══════════════════════════════════════════════════════════
# 功能选择器
# ═══════════════════════════════════════════════════════════

class FunctionSelector:
    """
    功能选择器

    根据任务类型自动选择合适的 Action，并执行。
    """

    def __init__(self):
        self.registry = ActionRegistry()

    def select(self, action_name: str, **kwargs) -> Action:
        """
        选择并实例化 Action

        Args:
            action_name: Action 名称
            **kwargs: Action 参数

        Returns:
            Action: 实例化的 Action
        """
        action_cls = self.registry.get(action_name)

        if not action_cls:
            raise ValueError(f"未找到 Action: {action_name}")

        return action_cls(**kwargs)

    def execute(self, action_name: str, **kwargs) -> Any:
        """
        选择并执行 Action

        Args:
            action_name: Action 名称
            **kwargs: Action 参数

        Returns:
            Any: 执行结果
        """
        action = self.select(action_name, **kwargs)
        return action.run()

    def list_actions(self, category: Optional[str] = None) -> List[Dict]:
        """
        列举可用的 Action

        Args:
            category: 分类过滤（可选）

        Returns:
            List[Dict]: Action 信息列表
        """
        actions = self.registry.list(category)

        return [
            {
                "name": a.name,
                "description": a.description,
                "category": a.category,
                "tags": a.tags,
                "priority": a.priority,
            }
            for a in actions
        ]

    def print_actions(self):
        """打印所有可用的 Action"""
        by_category = self.registry.list_by_category()

        print("\n可用的功能模块：\n")

        for category, actions in sorted(by_category.items()):
            print(f"## {category}\n")

            for action in actions:
                print(f"  - {action.name}: {action.description}")
                if action.tags:
                    print(f"    标签: {', '.join(action.tags)}")

            print()


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def get_selector() -> FunctionSelector:
    """获取功能选择器单例"""
    return FunctionSelector()


def execute_action(action_name: str, **kwargs) -> Any:
    """
    执行指定 Action

    Args:
        action_name: Action 名称
        **kwargs: Action 参数

    Returns:
        Any: 执行结果
    """
    selector = get_selector()
    return selector.execute(action_name, **kwargs)


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description='BookGraph 功能选择器')

    parser.add_argument(
        'action',
        type=str,
        nargs='?',
        help='Action 名称'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='列出所有可用的 Action'
    )

    parser.add_argument(
        '--vault',
        type=str,
        help='Vault 路径'
    )

    parser.add_argument(
        '--input',
        type=str,
        help='输入路径'
    )

    parser.add_argument(
        '--output',
        type=str,
        help='输出路径'
    )

    args = parser.parse_args()

    selector = FunctionSelector()

    # 列举 Action
    if args.list:
        selector.print_actions()
        return

    # 执行 Action
    if args.action:
        kwargs = {}

        if args.vault:
            kwargs['vault_path'] = args.vault

        if args.input:
            kwargs['input_path'] = args.input

        if args.output:
            kwargs['output_path'] = args.output

        result = selector.execute(args.action, **kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
