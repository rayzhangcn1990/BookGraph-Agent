"""
Progress Tracker - 处理进度跟踪模块

提供处理进度的持久化，支持中断后继续处理。
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set


class ProgressTracker:
    """
    进度跟踪器
    
    功能：
    - 记录已处理的文件
    - 支持中断后继续
    - 记录处理结果统计
    """
    
    def __init__(self, progress_file: str = "~/.bookgraph/progress.json"):
        """
        初始化进度跟踪器
        
        Args:
            progress_file: 进度文件路径
        """
        self.progress_file = Path(progress_file).expanduser()
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
    
    def _load(self) -> Dict:
        """加载进度数据"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return self._empty_data()
        return self._empty_data()
    
    def _empty_data(self) -> Dict:
        """创建空数据结构"""
        return {
            'processed': [],      # 已处理的文件路径列表
            'failed': [],         # 处理失败的文件
            'skipped': [],        # 跳过的文件
            'stats': {
                'total': 0,
                'success': 0,
                'failed': 0,
                'skipped': 0,
            },
            'last_updated': None,
        }
    
    def _save(self):
        """保存进度数据"""
        self.data['last_updated'] = datetime.now().isoformat()
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def is_processed(self, file_path: str) -> bool:
        """
        检查文件是否已处理
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否已处理
        """
        return file_path in self.data['processed']
    
    def is_failed(self, file_path: str) -> bool:
        """
        检查文件是否处理失败
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否失败
        """
        return file_path in self.data['failed']
    
    def mark_processed(self, file_path: str, result: Dict = None):
        """
        标记文件为已处理
        
        Args:
            file_path: 文件路径
            result: 处理结果（可选）
        """
        if file_path not in self.data['processed']:
            self.data['processed'].append(file_path)
            self.data['stats']['success'] += 1
            self._save()
    
    def mark_failed(self, file_path: str, error: str = None):
        """
        标记文件为处理失败
        
        Args:
            file_path: 文件路径
            error: 错误信息（可选）
        """
        if file_path not in self.data['failed']:
            self.data['failed'].append({
                'file_path': file_path,
                'error': error,
                'timestamp': datetime.now().isoformat(),
            })
            self.data['stats']['failed'] += 1
            self._save()
    
    def mark_skipped(self, file_path: str, reason: str = None):
        """
        标记文件为跳过
        
        Args:
            file_path: 文件路径
            reason: 跳过原因（可选）
        """
        if file_path not in self.data['skipped']:
            self.data['skipped'].append({
                'file_path': file_path,
                'reason': reason,
                'timestamp': datetime.now().isoformat(),
            })
            self.data['stats']['skipped'] += 1
            self._save()
    
    def get_unprocessed(self, file_paths: List[str]) -> List[str]:
        """
        获取未处理的文件列表
        
        Args:
            file_paths: 所有文件路径
            
        Returns:
            List[str]: 未处理的文件路径
        """
        processed = set(self.data['processed'])
        failed = set(item['file_path'] if isinstance(item, dict) else item for item in self.data['failed'])
        
        return [f for f in file_paths if f not in processed and f not in failed]
    
    def get_stats(self) -> Dict:
        """
        获取处理统计
        
        Returns:
            Dict: 统计信息
        """
        return {
            **self.data['stats'],
            'total_files': len(self.data['processed']) + len(self.data['failed']) + len(self.data['skipped']),
            'last_updated': self.data['last_updated'],
        }
    
    def reset(self):
        """重置进度"""
        self.data = self._empty_data()
        self._save()
    
    def remove_processed(self, file_path: str):
        """
        从已处理列表中移除文件（用于重新处理）
        
        Args:
            file_path: 文件路径
        """
        if file_path in self.data['processed']:
            self.data['processed'].remove(file_path)
            self.data['stats']['success'] -= 1
            self._save()
    
    def remove_failed(self, file_path: str):
        """
        从失败列表中移除文件（用于重试）
        
        Args:
            file_path: 文件路径
        """
        self.data['failed'] = [
            item for item in self.data['failed']
            if (item['file_path'] if isinstance(item, dict) else item) != file_path
        ]
        self.data['stats']['failed'] -= 1
        self._save()
