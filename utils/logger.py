"""
Logger - 日志工具模块

提供统一的日志配置，支持彩色控制台输出和文件输出。
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional


# ANSI 颜色代码
class Colors:
    """控制台颜色代码"""
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""
    
    COLORS = {
        logging.DEBUG: Colors.CYAN,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: Colors.RED + Colors.BOLD,
    }
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelno, Colors.WHITE)
        record.levelname = f"{log_color}{record.levelname}{Colors.RESET}"
        record.name = f"{Colors.BLUE}{record.name}{Colors.RESET}"
        return super().format(record)


def setup_logger(
    name: str = "BookGraph-Agent",
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_size_mb: int = 10
) -> logging.Logger:
    """
    设置日志器
    
    Args:
        name: 日志器名称
        level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        log_file: 日志文件路径（可选）
        max_size_mb: 日志文件最大大小（MB）
        
    Returns:
        logging.Logger: 配置好的日志器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    # 创建格式化器
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # 控制台 handler（彩色）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_formatter = ColoredFormatter(log_format, datefmt=date_format)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 文件 handler（如果指定了日志文件）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(getattr(logging, level.upper()))
        file_formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = "BookGraph-Agent") -> logging.Logger:
    """
    获取日志器
    
    Args:
        name: 日志器名称
        
    Returns:
        logging.Logger: 日志器
    """
    return logging.getLogger(name)
