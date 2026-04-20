"""
Cache - 缓存管理模块

提供基于文件哈希的缓存功能，避免重复解析。
"""

import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class Cache:
    """
    缓存管理器
    
    功能：
    - 基于文件哈希的缓存
    - 支持 TTL 过期
    - 自动清理过期缓存
    """
    
    def __init__(self, cache_dir: str = "~/.bookgraph/cache", ttl_days: int = 30):
        """
        初始化缓存
        
        Args:
            cache_dir: 缓存目录
            ttl_days: 缓存有效期（天）
        """
        self.cache_dir = Path(cache_dir).expanduser()
        self.ttl_days = ttl_days
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载缓存索引
        self.index_file = self.cache_dir / "index.json"
        self.index = self._load_index()
    
    def _load_index(self) -> Dict:
        """加载缓存索引"""
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def _save_index(self):
        """保存缓存索引"""
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)
    
    def _get_file_hash(self, file_path: str) -> str:
        """
        计算文件哈希
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: MD5 哈希值
        """
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            # 分块读取，避免大文件内存溢出
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def get(self, file_path: str) -> Optional[Dict]:
        """
        获取缓存
        
        Args:
            file_path: 原文件路径
            
        Returns:
            Optional[Dict]: 缓存数据，不存在或过期则返回 None
        """
        file_hash = self._get_file_hash(file_path)
        
        if file_hash not in self.index:
            return None
        
        cache_entry = self.index[file_hash]
        
        # 检查 TTL
        created_at = datetime.fromisoformat(cache_entry['created_at'])
        if datetime.now() - created_at > timedelta(days=self.ttl_days):
            # 过期，删除
            self.delete(file_path)
            return None
        
        # 加载缓存数据
        cache_file = self.cache_dir / f"{file_hash}.json"
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    
    def set(self, file_path: str, data: Dict):
        """
        设置缓存
        
        Args:
            file_path: 原文件路径
            data: 缓存数据
        """
        file_hash = self._get_file_hash(file_path)
        
        # 保存缓存数据
        cache_file = self.cache_dir / f"{file_hash}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 更新索引
        self.index[file_hash] = {
            'file_path': file_path,
            'created_at': datetime.now().isoformat(),
            'cache_file': str(cache_file),
        }
        self._save_index()
    
    def delete(self, file_path: str) -> bool:
        """
        删除缓存
        
        Args:
            file_path: 原文件路径
            
        Returns:
            bool: 是否成功删除
        """
        file_hash = self._get_file_hash(file_path)
        
        if file_hash not in self.index:
            return False
        
        cache_entry = self.index[file_hash]
        cache_file = Path(cache_entry['cache_file'])
        
        # 删除缓存文件
        if cache_file.exists():
            cache_file.unlink()
        
        # 删除索引
        del self.index[file_hash]
        self._save_index()
        
        return True
    
    def clear(self):
        """清空所有缓存"""
        for cache_file in self.cache_dir.glob("*.json"):
            if cache_file != self.index_file:
                cache_file.unlink()
        
        self.index = {}
        self._save_index()
    
    def cleanup(self) -> int:
        """
        清理过期缓存
        
        Returns:
            int: 清理的文件数量
        """
        cleaned = 0
        expired_hashes = []
        
        for file_hash, entry in self.index.items():
            created_at = datetime.fromisoformat(entry['created_at'])
            if datetime.now() - created_at > timedelta(days=self.ttl_days):
                expired_hashes.append(file_hash)
        
        for file_hash in expired_hashes:
            entry = self.index[file_hash]
            cache_file = Path(entry['cache_file'])
            
            if cache_file.exists():
                cache_file.unlink()
                cleaned += 1
            
            del self.index[file_hash]
        
        if cleaned > 0:
            self._save_index()
        
        return cleaned
    
    def get_stats(self) -> Dict:
        """
        获取缓存统计
        
        Returns:
            Dict: 统计信息
        """
        total_size = 0
        file_count = 0
        
        for cache_file in self.cache_dir.glob("*.json"):
            if cache_file != self.index_file:
                total_size += cache_file.stat().st_size
                file_count += 1
        
        return {
            'file_count': file_count,
            'total_size_mb': round(total_size / 1024 / 1024, 2),
            'ttl_days': self.ttl_days,
        }
