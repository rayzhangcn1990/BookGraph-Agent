#!/usr/bin/env python3
"""
NER (Named Entity Recognition) Extractor

基于词典和正则的实体识别器，用于从文本中提取人物、著作、概念等实体。
"""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """实体数据类"""
    text: str
    type: str
    start: int
    end: int
    confidence: float


class W2NERRecognizer:
    """基于词典的 W2NER 实体识别器"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化识别器

        Args:
            config_path: 配置文件路径，默认为 config/entity_dict.yaml
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "entity_dict.yaml"

        self.entity_dict = self._load_entity_dict(config_path)
        self.regex_patterns = self._load_regex_patterns(config_path)

    def _load_entity_dict(self, config_path: Path) -> Dict[str, List[str]]:
        """
        从配置文件加载实体词典

        Args:
            config_path: 配置文件路径

        Returns:
            Dict[type, entities]: 类型到实体列表的映射
        """
        if not config_path.exists():
            logger.warning(f"配置文件不存在: {config_path}")
            return {}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            entities = config.get('entities', {})
            logger.info(f"已加载 {len(entities)} 类实体词典")
            return entities

        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return {}

    def _load_regex_patterns(self, config_path: Path) -> Dict[str, str]:
        """
        从配置文件加载正则模式

        Args:
            config_path: 配置文件路径

        Returns:
            Dict[pattern_name, pattern]: 模式名称到正则表达式的映射
        """
        if not config_path.exists():
            return {}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            patterns = config.get('regex_patterns', {})
            logger.info(f"已加载 {len(patterns)} 个正则模式")
            return patterns

        except Exception as e:
            logger.error(f"加载正则模式失败: {e}")
            return {}

    def recognize(self, text: str, entity_types: Optional[List[str]] = None) -> List[Entity]:
        """
        识别文本中的实体

        Args:
            text: 待识别文本
            entity_types: 要识别的实体类型列表，None 表示识别所有类型

        Returns:
            List[Entity]: 识别出的实体列表
        """
        entities = []

        # 词典匹配
        entities.extend(self._match_by_dict(text, entity_types))

        # 正则匹配（书名、人名等）
        entities.extend(self._match_by_regex(text))

        # 去重（相同位置的实体）
        entities = self._deduplicate(entities)

        return entities

    def _match_by_dict(self, text: str, entity_types: Optional[List[str]]) -> List[Entity]:
        """
        词典匹配

        Args:
            text: 待匹配文本
            entity_types: 实体类型筛选

        Returns:
            List[Entity]: 匹配到的实体列表
        """
        entities = []

        for entity_type, entity_list in self.entity_dict.items():
            # 类型筛选
            if entity_types and entity_type not in entity_types:
                continue

            for entity_text in entity_list:
                # 查找所有出现位置
                start = 0
                while True:
                    pos = text.find(entity_text, start)
                    if pos == -1:
                        break

                    entities.append(Entity(
                        text=entity_text,
                        type=entity_type,
                        start=pos,
                        end=pos + len(entity_text),
                        confidence=0.95  # 词典匹配置信度较高
                    ))
                    start = pos + 1

        return entities

    def _match_by_regex(self, text: str) -> List[Entity]:
        """
        正则模式匹配

        Args:
            text: 待匹配文本

        Returns:
            List[Entity]: 匹配到的实体列表
        """
        entities = []

        # 书名模式：《书名》
        book_pattern = self.regex_patterns.get('book_pattern', r'《([^》]+)》')
        for match in re.finditer(book_pattern, text):
            book_name = match.group(1)
            entities.append(Entity(
                text=book_name,
                type="著作",
                start=match.start(1),
                end=match.end(1),
                confidence=0.90
            ))

        # 人名模式：人名 + 说/认为/提出等
        person_pattern = self.regex_patterns.get('person_pattern', r'[一-龥]{2,4}(说|认为|提出|指出|写道)')
        for match in re.finditer(person_pattern, text):
            person_name = match.group(0)[:-len(match.group(1))]  # 去掉动词部分
            entities.append(Entity(
                text=person_name,
                type="人物",
                start=match.start(),
                end=match.start() + len(person_name),
                confidence=0.80
            ))

        return entities

    def _deduplicate(self, entities: List[Entity]) -> List[Entity]:
        """
        去重相同位置的实体

        Args:
            entities: 实体列表

        Returns:
            List[Entity]: 去重后的实体列表
        """
        # 按位置和文本去重
        seen = {}
        for entity in entities:
            key = (entity.start, entity.end)
            if key not in seen:
                seen[key] = entity
            else:
                # 如果同一位置有多个实体，选择置信度更高的
                if entity.confidence > seen[key].confidence:
                    seen[key] = entity

        return sorted(seen.values(), key=lambda e: e.start)

    def get_entities_by_type(self, entities: List[Entity], entity_type: str) -> List[Entity]:
        """
        按类型筛选实体

        Args:
            entities: 实体列表
            entity_type: 实体类型

        Returns:
            List[Entity]: 筛选后的实体列表
        """
        return [e for e in entities if e.type == entity_type]

    def get_unique_entities(self, entities: List[Entity]) -> List[str]:
        """
        获取唯一实体文本列表

        Args:
            entities: 实体列表

        Returns:
            List[str]: 唯一实体文本列表
        """
        return sorted(set(e.text for e in entities))


# ═══════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════

def recognize_entities(text: str) -> List[Entity]:
    """
    便捷函数：识别文本中的所有实体

    Args:
        text: 待识别文本

    Returns:
        List[Entity]: 实体列表
    """
    recognizer = W2NERRecognizer()
    return recognizer.recognize(text)


def get_person_entities(text: str) -> List[Entity]:
    """
    便捷函数：获取人物实体

    Args:
        text: 待识别文本

    Returns:
        List[Entity]: 人物实体列表
    """
    recognizer = W2NERRecognizer()
    entities = recognizer.recognize(text)
    return recognizer.get_entities_by_type(entities, "人物")


def get_book_entities(text: str) -> List[Entity]:
    """
    便捷函数：获取著作实体

    Args:
        text: 待识别文本

    Returns:
        List[Entity]: 著作实体列表
    """
    recognizer = W2NERRecognizer()
    entities = recognizer.recognize(text)
    return recognizer.get_entities_by_type(entities, "著作")