"""
硬件自适应配置模块

根据系统硬件能力自动优化并发参数：
- CPU核心数 → 并发数
- 内存大小 → 缓存大小、chunk大小
- 网络带宽 → API调用间隔
"""

import os
import sys
import logging
from typing import Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class HardwareProfile:
    """硬件配置画像"""
    cpu_cores: int          # 逻辑核心数
    physical_cores: int     # 物理核心数
    memory_gb: float        # 内存大小 (GB)
    cpu_brand: str          # CPU型号

    # 推荐配置
    recommended_parallel_books: int      # 推荐书籍并行数
    recommended_chunk_parallel: int      # 推荐chunk并行数
    recommended_chunk_size: int          # 推荐chunk大小
    recommended_cache_size_mb: int       # 推荐缓存大小


def detect_hardware() -> HardwareProfile:
    """
    检测系统硬件配置

    Returns:
        HardwareProfile: 硬件配置画像
    """
    # CPU 核心
    if sys.platform == 'darwin':
        # macOS
        import subprocess
        try:
            physical_cores = int(subprocess.check_output(['sysctl', '-n', 'hw.physicalcpu']).decode().strip())
            logical_cores = int(subprocess.check_output(['sysctl', '-n', 'hw.logicalcpu']).decode().strip())
            cpu_brand = subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string']).decode().strip()
            memory_bytes = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize']).decode().strip())
        except:
            physical_cores = 2
            logical_cores = 4
            cpu_brand = "Unknown"
            memory_bytes = 8 * 1024 * 1024 * 1024  # 默认 8GB
    else:
        # Linux/其他
        try:
            logical_cores = os.cpu_count() or 4
            physical_cores = logical_cores // 2
            cpu_brand = "Unknown"
            # 尝试读取内存
            with open('/proc/meminfo', 'r') as f:
                mem_line = f.readline()
                memory_kb = int(mem_line.split(':')[1].strip().split()[0])
                memory_bytes = memory_kb * 1024
        except:
            physical_cores = 2
            logical_cores = 4
            cpu_brand = "Unknown"
            memory_bytes = 8 * 1024 * 1024 * 1024

    memory_gb = memory_bytes / (1024 * 1024 * 1024)

    # 根据硬件能力计算推荐配置
    # 并发数 = CPU核心数（但不超过API限制）
    recommended_parallel_books = min(logical_cores, 4)  # 最大4本书并行
    recommended_chunk_parallel = min(logical_cores, 4)  # 最大4个chunk并行

    # chunk大小 = 根据内存调整（内存越大，chunk越大）
    if memory_gb >= 32:
        recommended_chunk_size = 40000
    elif memory_gb >= 16:
        recommended_chunk_size = 30000
    elif memory_gb >= 8:
        recommended_chunk_size = 25000
    else:
        recommended_chunk_size = 20000

    # 缓存大小 = 内存的一小部分
    recommended_cache_size_mb = int(memory_gb * 100)  # 约内存的10%

    profile = HardwareProfile(
        cpu_cores=logical_cores,
        physical_cores=physical_cores,
        memory_gb=memory_gb,
        cpu_brand=cpu_brand,
        recommended_parallel_books=recommended_parallel_books,
        recommended_chunk_parallel=recommended_chunk_parallel,
        recommended_chunk_size=recommended_chunk_size,
        recommended_cache_size_mb=recommended_cache_size_mb,
    )

    logger.info(f"🔍 硬件检测: {cpu_brand}, {physical_cores}物理/{logical_cores}逻辑核心, {memory_gb:.1f}GB内存")
    logger.info(f"   推荐配置: 并行书籍={recommended_parallel_books}, 并行chunks={recommended_chunk_parallel}")

    return profile


def get_optimized_config(base_config: Dict, profile: HardwareProfile) -> Dict:
    """
    根据硬件配置优化参数

    Args:
        base_config: 基础配置
        profile: 硬件画像

    Returns:
        Dict: 优化后的配置
    """
    optimized = base_config.copy()

    # 优化 LLM 配置
    if 'llm' not in optimized:
        optimized['llm'] = {}

    optimized['llm']['chunk_size'] = profile.recommended_chunk_size
    optimized['llm']['merge_threshold'] = int(profile.recommended_chunk_size * 0.6)

    # 优化批量配置
    if 'batch' not in optimized:
        optimized['batch'] = {}

    optimized['batch']['max_workers'] = profile.recommended_parallel_books
    optimized['batch']['chunk_parallel'] = profile.recommended_chunk_parallel

    # 添加硬件信息
    optimized['hardware'] = {
        'cpu_cores': profile.cpu_cores,
        'physical_cores': profile.physical_cores,
        'memory_gb': profile.memory_gb,
        'cpu_brand': profile.cpu_brand,
    }

    return optimized


# ═══════════════════════════════════════════════════════════
# 书籍大小自适应策略
# ═══════════════════════════════════════════════════════════

# 书籍大小分类阈值
BOOK_SIZE_THRESHOLDS = {
    'short': 30000,      # 短书：< 30k字符
    'medium': 100000,    # 中等书：30k-100k字符
    'long': 300000,      # 长书：100k-300k字符
    'extra_long': 300000, # 超长书：> 300k字符
}

# 不同大小书籍的处理策略
BOOK_PROCESSING_STRATEGIES = {
    'short': {
        'description': '短书策略 - 快速处理，单模型，高并行数',
        'chunk_strategy': 'single',          # 不分块，单次处理
        'max_chunks': 1,                     # 最大chunk数
        'parallel_books': 4,                 # 可并行处理的书数量
        'parallel_chunks': 1,                # chunk并行数（无效）
        'chunk_size': 30000,                 # chunk大小（整书）
        'quality_level': 'fast',             # 质量等级
        'max_tokens': 16384,                 # 最大输出token
        'temperature': 0.3,                  # 温度
        'timeout_multiplier': 1.0,           # 超时倍数
    },
    'medium': {
        'description': '中等书策略 - 标准处理，适度分块',
        'chunk_strategy': 'semantic',        # 语义分块
        'max_chunks': 4,                     # 最大chunk数
        'parallel_books': 3,                 # 可并行处理的书数量
        'parallel_chunks': 2,                # chunk并行数
        'chunk_size': 25000,                 # chunk大小
        'quality_level': 'standard',         # 贪量等级
        'max_tokens': 16384,
        'temperature': 0.4,
        'timeout_multiplier': 1.2,
    },
    'long': {
        'description': '长书策略 - 深度处理，多chunk并行',
        'chunk_strategy': 'semantic',        # 语义分块
        'max_chunks': 10,                    # 最大chunk数
        'parallel_books': 2,                 # 可并行处理的书数量（降低）
        'parallel_chunks': 3,                # chunk并行数
        'chunk_size': 30000,                 # chunk大小
        'quality_level': 'high',             # 高质量
        'max_tokens': 24576,                 # 增加输出token
        'temperature': 0.5,
        'timeout_multiplier': 1.5,
    },
    'extra_long': {
        'description': '超长书策略 - 分批处理，质量优先',
        'chunk_strategy': 'chapter',         # 按章节分块
        'max_chunks': 20,                    # 最大chunk数
        'parallel_books': 1,                 # 单书独占处理
        'parallel_chunks': 4,                # chunk并行数最大化
        'chunk_size': 35000,                 # 更大chunk
        'quality_level': 'high',
        'max_tokens': 24576,
        'temperature': 0.5,
        'timeout_multiplier': 2.0,
    },
}


def classify_book_size(char_count: int) -> str:
    """
    根据字符数分类书籍大小

    Args:
        char_count: 字符数

    Returns:
        str: 书籍大小分类 (short/medium/long/extra_long)
    """
    if char_count < BOOK_SIZE_THRESHOLDS['short']:
        return 'short'
    elif char_count < BOOK_SIZE_THRESHOLDS['medium']:
        return 'medium'
    elif char_count < BOOK_SIZE_THRESHOLDS['long']:
        return 'long'
    else:
        return 'extra_long'


def get_book_strategy(char_count: int, hardware_profile: HardwareProfile = None) -> Dict:
    """
    根据书籍大小和硬件能力获取处理策略

    Args:
        char_count: 字符数
        hardware_profile: 硬件画像（可选）

    Returns:
        Dict: 处理策略
    """
    book_size = classify_book_size(char_count)
    base_strategy = BOOK_PROCESSING_STRATEGIES[book_size].copy()

    # 根据硬件能力调整并发数
    if hardware_profile:
        # 确保不超过硬件能力上限
        max_parallel = min(hardware_profile.cpu_cores, 4)
        base_strategy['parallel_books'] = min(base_strategy['parallel_books'], max_parallel)
        base_strategy['parallel_chunks'] = min(base_strategy['parallel_chunks'], max_parallel)

        # 根据内存调整chunk大小
        if hardware_profile.memory_gb >= 16:
            base_strategy['chunk_size'] = min(base_strategy['chunk_size'] + 5000, 40000)
        elif hardware_profile.memory_gb < 8:
            base_strategy['chunk_size'] = max(base_strategy['chunk_size'] - 5000, 20000)

    logger.info(f"📚 书籍分类: {book_size} ({char_count}字符) → 策略: {base_strategy['description']}")

    return base_strategy


# ═══════════════════════════════════════════════════════════
# 质量分级配置
# ═══════════════════════════════════════════════════════════

QUALITY_LEVELS = {
    'high': {
        'min_concepts': 5,        # 最少核心概念数
        'min_insights': 3,        # 最少关键洞见数
        'min_chapters': 3,        # 最少章节摘要数
        'max_retry': 3,           # 最大重试次数
        'timeout_multiplier': 1.5, # 超时时间倍数
    },
    'standard': {
        'min_concepts': 3,
        'min_insights': 2,
        'min_chapters': 2,
        'max_retry': 2,
        'timeout_multiplier': 1.0,
    },
    'fast': {
        'min_concepts': 1,
        'min_insights': 1,
        'min_chapters': 1,
        'max_retry': 1,
        'timeout_multiplier': 0.7,
    },
}


def get_quality_config(quality_level: str = 'standard') -> Dict:
    """
    获取质量配置

    Args:
        quality_level: 质量等级 (high/standard/fast)

    Returns:
        Dict: 质量配置
    """
    return QUALITY_LEVELS.get(quality_level, QUALITY_LEVELS['standard'])


# ═══════════════════════════════════════════════════════════
# API 调度优化
# ═══════════════════════════════════════════════════════════

API_RETRY_CONFIG = {
    'rate_limit': {
        'base_wait': 30,          # 限流基础等待时间（秒）
        'max_wait': 90,           # 最大等待时间
        'multiplier': 2,          # 指数退避倍数
    },
    'timeout': {
        'base_wait': 10,
        'max_wait': 30,
        'multiplier': 1.5,
    },
    'error': {
        'base_wait': 5,
        'max_wait': 15,
        'multiplier': 1.2,
    },
}


def get_retry_wait(error_type: str, retry_count: int) -> int:
    """
    根据错误类型和重试次数计算等待时间

    Args:
        error_type: 错误类型 (rate_limit/timeout/error)
        retry_count: 重试次数

    Returns:
        int: 等待时间（秒）
    """
    config = API_RETRY_CONFIG.get(error_type, API_RETRY_CONFIG['error'])

    wait = config['base_wait'] * (config['multiplier'] ** retry_count)
    wait = min(wait, config['max_wait'])

    return int(wait)


# ═══════════════════════════════════════════════════════════
# 全局硬件实例
# ═══════════════════════════════════════════════════════════

_hardware_profile: HardwareProfile = None


def get_hardware_profile() -> HardwareProfile:
    """获取全局硬件画像（单例）"""
    global _hardware_profile
    if _hardware_profile is None:
        _hardware_profile = detect_hardware()
    return _hardware_profile


if __name__ == "__main__":
    # 测试
    profile = detect_hardware()
    print(f"\n硬件配置:")
    print(f"  CPU: {profile.cpu_brand}")
    print(f"  核心: {profile.physical_cores}物理/{profile.cpu_cores}逻辑")
    print(f"  内存: {profile.memory_gb:.1f}GB")
    print(f"\n推荐配置:")
    print(f"  并行书籍: {profile.recommended_parallel_books}")
    print(f"  并行chunks: {profile.recommended_chunk_parallel}")
    print(f"  chunk大小: {profile.recommended_chunk_size}")
    print(f"  缓存大小: {profile.recommended_cache_size_mb}MB")

    # 测试书籍策略
    print(f"\n书籍大小自适应策略测试:")
    test_sizes = [20000, 50000, 150000, 400000]
    for size in test_sizes:
        strategy = get_book_strategy(size, profile)
        classification = classify_book_size(size)
        print(f"\n  {size}字符 ({classification}):")
        print(f"    分块策略: {strategy['chunk_strategy']}")
        print(f"    并行书籍: {strategy['parallel_books']}")
        print(f"    并行chunks: {strategy['parallel_chunks']}")
        print(f"    chunk大小: {strategy['chunk_size']}")
        print(f"    贪量等级: {strategy['quality_level']}")