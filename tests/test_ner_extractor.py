#!/usr/bin/env python3
"""
NER Extractor 单元测试

测试覆盖：
- 词典加载
- 实体识别
- 正则匹配
- 去重逻辑
"""

import pytest
from core.ner_extractor import (
    W2NERRecognizer,
    Entity,
    recognize_entities,
    get_person_entities,
    get_book_entities,
)


class TestW2NERRecognizer:
    """测试 W2NER 实体识别器"""

    def test_init(self):
        """测试初始化"""
        recognizer = W2NERRecognizer()
        assert recognizer.entity_dict is not None
        assert len(recognizer.entity_dict) > 0

    def test_load_entity_dict_from_config(self):
        """测试从配置文件加载词典"""
        recognizer = W2NERRecognizer()
        # 应包含配置文件中的实体类型
        assert "人物" in recognizer.entity_dict
        assert "著作" in recognizer.entity_dict

        # 应包含具体的实体
        all_entities = []
        for entities in recognizer.entity_dict.values():
            all_entities.extend(entities)
        assert "基辛格" in all_entities
        assert "霍布斯" in all_entities
        assert "利维坦" in all_entities

    def test_recognize_basic(self):
        """测试基本实体识别"""
        text = "基辛格在《世界秩序》中提出均势理论"
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text)

        # 应识别出基辛格、世界秩序、均势
        assert len(entities) >= 3

        entity_texts = [e.text for e in entities]
        assert "基辛格" in entity_texts
        assert "世界秩序" in entity_texts

    def test_recognize_with_type_filter(self):
        """测试按类型筛选"""
        text = "基辛格是一位著名政治家"
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text, entity_types=["人物"])

        # 应至少识别出一个人物
        assert len(entities) >= 1

        # 如果有结果，应包含人物
        entity_types = [e.type for e in entities]
        assert "人物" in entity_types

    def test_recognize_book_pattern(self):
        """测试书名模式识别"""
        text = "他在《君主论》中写道..."
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text)

        entity_texts = [e.text for e in entities]
        assert "君主论" in entity_texts

    def test_recognize_person_pattern(self):
        """测试人名模式识别"""
        text = "邓小平指出改革开放的重要性"
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text)

        # 应识别出邓小平
        person_entities = [e for e in entities if e.type == "人物"]
        assert len(person_entities) >= 1

    def test_deduplicate_entities(self):
        """测试实体去重"""
        text = "基辛格基辛格基辛格"  # 重复
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text)

        # 相同位置不应重复
        positions = [(e.start, e.end) for e in entities]
        # 去重后应唯一
        assert len(positions) == len(set(positions))

    def test_get_entities_by_type(self):
        """测试按类型获取"""
        text = "基辛格在《世界秩序》中提出均势"
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text)

        persons = recognizer.get_entities_by_type(entities, "人物")
        assert all(e.type == "人物" for e in persons)

    def test_get_unique_entities(self):
        """测试获取唯一实体"""
        text = "基辛格基辛格霍布斯霍布斯"
        recognizer = W2NERRecognizer()
        entities = recognizer.recognize(text)

        unique_texts = recognizer.get_unique_entities(entities)
        assert "基辛格" in unique_texts
        assert "霍布斯" in unique_texts


class TestEntity:
    """测试实体类"""

    def test_entity_creation(self):
        """测试实体创建"""
        entity = Entity(
            text="基辛格",
            type="人物",
            start=0,
            end=3,
            confidence=0.9
        )
        assert entity.text == "基辛格"
        assert entity.type == "人物"
        assert entity.start == 0
        assert entity.end == 3


class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_recognize_entities(self):
        """测试便捷识别函数"""
        text = "基辛格在《世界秩序》中提出均势"
        entities = recognize_entities(text)
        assert len(entities) > 0

    def test_get_person_entities(self):
        """测试获取人物"""
        text = "基辛格和霍布斯讨论政治"
        entities = get_person_entities(text)
        assert all(e.type == "人物" for e in entities)

    def test_get_book_entities(self):
        """测试获取著作"""
        text = "《君主论》和《利维坦》"
        entities = get_book_entities(text)
        assert all(e.type == "著作" for e in entities)


class TestPerformance:
    """测试性能"""

    def test_long_text_performance(self):
        """测试长文本性能"""
        import time

        # 构建长文本
        text = "基辛格在《世界秩序》中提出均势。" * 100

        recognizer = W2NERRecognizer()
        start = time.time()
        entities = recognizer.recognize(text)
        elapsed = time.time() - start

        # 应在 1 秒内完成
        assert elapsed < 1.0

        # 应识别出大量实体
        assert len(entities) >= 200


# ═══════════════════════════════════════════════════════════════════════
# 运行测试命令:
#   pytest tests/test_ner_extractor.py -v
# ═══════════════════════════════════════════════════════════════════════