"""
File Handler - 文件处理工具模块

提供文件读取、写入、备份等功能。
"""

import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List


class FileHandler:
    """
    文件处理器
    
    功能：
    - 文件格式检测
    - 文件备份
    - UTF-8 文件读写
    - 文件哈希计算
    """

    @staticmethod
    def detect_format(file_path: str) -> str:
        """
        检测文件格式
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 格式名称（epub/pdf/mobi/unknown）
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        
        format_map = {
            '.epub': 'epub',
            '.pdf': 'pdf',
            '.mobi': 'mobi',
            '.azw': 'mobi',
            '.azw3': 'mobi',
            '.txt': 'txt',
            '.md': 'markdown',
        }
        
        return format_map.get(suffix, 'unknown')

    @staticmethod
    def create_backup(file_path: str, backup_dir: Optional[str] = None) -> Path:
        """
        创建文件备份
        
        Args:
            file_path: 原文件路径
            backup_dir: 备份目录（可选，默认在同目录下）
            
        Returns:
            Path: 备份文件路径
        """
        src_path = Path(file_path)
        
        if not src_path.exists():
            raise FileNotFoundError(f"文件不存在：{file_path}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if backup_dir:
            backup_path = Path(backup_dir) / f"{src_path.stem}_backup_{timestamp}{src_path.suffix}"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            backup_path = src_path.parent / f"{src_path.stem}_backup_{timestamp}{src_path.suffix}"
        
        shutil.copy2(src_path, backup_path)
        return backup_path

    @staticmethod
    def read_utf8(file_path: str, encoding: str = 'utf-8') -> str:
        """
        读取 UTF-8 文件
        
        Args:
            file_path: 文件路径
            encoding: 文件编码
            
        Returns:
            str: 文件内容
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{file_path}")
        
        # 尝试不同编码读取
        encodings = [encoding, 'utf-8', 'gbk', 'gb2312', 'latin-1']
        
        for enc in encodings:
            try:
                with open(path, 'r', encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        
        # 如果所有编码都失败，使用 errors='ignore'
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    @staticmethod
    def write_utf8(file_path: str, content: str, encoding: str = 'utf-8') -> None:
        """
        写入 UTF-8 文件
        
        Args:
            file_path: 文件路径
            content: 文件内容
            encoding: 文件编码
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding=encoding) as f:
            f.write(content)

    @staticmethod
    def calculate_hash(file_path: str, algorithm: str = 'md5') -> str:
        """
        计算文件哈希值
        
        Args:
            file_path: 文件路径
            algorithm: 哈希算法（md5/sha1/sha256）
            
        Returns:
            str: 哈希值
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{file_path}")
        
        hash_func = getattr(hashlib, algorithm, hashlib.md5)
        hasher = hash_func()
        
        with open(path, 'rb') as f:
            # 分块读取，避免大文件内存溢出
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        
        return hasher.hexdigest()

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """
        获取文件大小（字节）
        
        Args:
            file_path: 文件路径
            
        Returns:
            int: 文件大小
        """
        return Path(file_path).stat().st_size

    @staticmethod
    def get_file_modified_time(file_path: str) -> datetime:
        """
        获取文件修改时间
        
        Args:
            file_path: 文件路径
            
        Returns:
            datetime: 修改时间
        """
        mtime = Path(file_path).stat().st_mtime
        return datetime.fromtimestamp(mtime)

    @staticmethod
    def delete_file(file_path: str) -> bool:
        """
        删除文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否成功删除
        """
        path = Path(file_path)
        
        if not path.exists():
            return False
        
        path.unlink()
        return True

    @staticmethod
    def move_file(src: str, dst: str, overwrite: bool = False) -> Path:
        """
        移动文件
        
        Args:
            src: 源文件路径
            dst: 目标文件路径
            overwrite: 是否覆盖已存在的文件
            
        Returns:
            Path: 目标文件路径
        """
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            raise FileNotFoundError(f"源文件不存在：{src}")
        
        if dst_path.exists() and not overwrite:
            raise FileExistsError(f"目标文件已存在：{dst}")
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        if overwrite and dst_path.exists():
            dst_path.unlink()
        
        shutil.move(str(src_path), str(dst_path))
        return dst_path

    @staticmethod
    def copy_file(src: str, dst: str, overwrite: bool = False) -> Path:
        """
        复制文件
        
        Args:
            src: 源文件路径
            dst: 目标文件路径
            overwrite: 是否覆盖已存在的文件
            
        Returns:
            Path: 目标文件路径
        """
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            raise FileNotFoundError(f"源文件不存在：{src}")
        
        if dst_path.exists() and not overwrite:
            raise FileExistsError(f"目标文件已存在：{dst}")
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_path), str(dst_path))
        return dst_path

    @staticmethod
    def list_files(
        directory: str, 
        pattern: str = "*", 
        recursive: bool = False
    ) -> List[Path]:
        """
        列出目录中的文件
        
        Args:
            directory: 目录路径
            pattern: 文件名模式（glob 语法）
            recursive: 是否递归子目录
            
        Returns:
            List[Path]: 文件路径列表
        """
        dir_path = Path(directory)
        
        if not dir_path.exists():
            return []
        
        if recursive:
            return sorted(dir_path.rglob(pattern))
        else:
            return sorted(dir_path.glob(pattern))

    @staticmethod
    def is_empty_file(file_path: str) -> bool:
        """
        检查文件是否为空
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为空
        """
        path = Path(file_path)
        
        if not path.exists():
            return True
        
        return path.stat().st_size == 0

    @staticmethod
    def get_file_extension(file_path: str) -> str:
        """
        获取文件扩展名
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 扩展名（包含点，如'.pdf'）
        """
        return Path(file_path).suffix.lower()

    @staticmethod
    def get_file_name(file_path: str, with_extension: bool = False) -> str:
        """
        获取文件名
        
        Args:
            file_path: 文件路径
            with_extension: 是否包含扩展名
            
        Returns:
            str: 文件名
        """
        path = Path(file_path)
        
        if with_extension:
            return path.name
        else:
            return path.stem
