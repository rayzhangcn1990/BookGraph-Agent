"""主入口模块导入测试。"""

import importlib


def test_main_module_imports_successfully():
    """main.py 应该可以被导入，避免运行期类型注解缺失依赖。"""
    module = importlib.import_module("main")

    assert module is not None
