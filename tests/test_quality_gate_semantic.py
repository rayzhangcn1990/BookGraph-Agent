"""语义质量门测试：避免只靠关键词匹配。"""

from core.book_graph_quality_checker import BookGraphQualityChecker


def _valid_chapter():
    return {
        "chapter_number": "1",
        "title": "第一章",
        "core_argument": "尼采通过批判传统道德二分法，揭示价值判断背后的生命冲动与权力结构。",
        "underlying_logic": "前提假设：传统道德并非永恒真理→推理链条：追溯善恶概念的历史生成与心理动机→核心结论：价值需要被重新估价。",
    }


def test_quality_gate_rejects_single_stage_learning_path():
    """学习路径只有单阶段内容时仍应判定不合格。"""
    data = {
        "metadata": {
            "title": "善恶的彼岸",
            "author": "尼采",
            "author_intro": "尼采是德国哲学家，以价值重估、权力意志和对传统道德的批判著称。",
            "discipline": "哲学",
        },
        "time_background": {
            "macro_background": "十九世纪欧洲思想危机推动传统价值体系瓦解。",
            "micro_background": "本书承接尼采后期对形而上学和基督教道德的批判。",
            "core_contradiction": "现代人想摆脱教条，却仍依赖旧价值获得安全感。",
        },
        "critical_analysis": {
            "feminist_perspective": "尼采的主体创造性可被女性主义重读，但其性别表达存在时代局限。",
            "postcolonial_perspective": "尼采的欧洲语境需要接受跨文化伦理传统的重新检验。",
            "ethical_boundaries": {
                "reasonable": "适用于反思教条化道德和训练独立判断。",
                "dangerous": "若直接转化为政治支配逻辑，可能滑向强者崇拜。",
            },
        },
        "chapters": [_valid_chapter() for _ in range(6)],
        "core_concepts": [
            {
                "name": "权力意志",
                "definition": "生命扩张和形式创造的根本冲动，不等同于狭义政治权力欲。",
                "deep_meaning": "它说明价值判断往往服务于某种生命形式的扩张和自我解释。",
                "underlying_logic": "前提假设：生命不是静态存在→推理链条：生命持续解释并塑造世界→核心结论：价值判断体现权力意志。",
            },
            {
                "name": "价值重估",
                "definition": "对既有善恶体系的历史来源、心理功能和生命效果进行重新审查。",
                "deep_meaning": "它要求读者不再把传统道德当成永恒真理，而要追问其生成机制。",
                "underlying_logic": "前提假设：旧价值已失去创造力→推理链条：揭露其来源和功能→核心结论：必须创造新价值。",
            },
            {
                "name": "自由精神",
                "definition": "能够脱离群体道德和教条束缚，承受无保障状态的独立思想者。",
                "deep_meaning": "自由精神不是任意怀疑，而是承担价值创造风险的精神状态。",
                "underlying_logic": "前提假设：思想受传统价值束缚→推理链条：摆脱教条并自我试炼→核心结论：自由精神承担价值创造风险。",
            },
        ],
        "key_insights": [
            {
                "title": "善恶不是永恒实体",
                "description": "尼采把善恶判断放回历史和心理结构中分析，拒绝把它们视为超历史真理。",
                "underlying_logic": "前提假设：道德概念有历史来源→推理链条：考察善恶如何服务不同生命类型→核心结论：善恶应被谱系化分析。",
            },
            {
                "title": "哲学体系暴露哲学家的本能",
                "description": "尼采把哲学主张视为生命状态和欲望结构的症状，而不只是抽象论证。",
                "underlying_logic": "前提假设：思想并非脱离身体→推理链条：哲学判断体现评价者的生命需要→核心结论：哲学也应接受心理诊断。",
            },
        ],
        "key_cases": [
            {
                "name": "基督教道德批判",
                "source_chapter": "论宗教的本质",
                "event_description": "尼采以基督教道德为案例，分析怜悯、禁欲和服从如何塑造弱者价值，并反过来约束生命力量。",
                "historical_limitations": "该批判主要针对欧洲基督教传统，不可直接套用于全部宗教经验。",
            }
        ],
        "key_quotes": [
            {
                "text": "从善恶的彼岸重新审查价值。",
                "chapter": "第一章",
                "core_theme": "价值重估",
                "background_context": "该表达概括尼采对传统善恶二分的反思方向。",
                "underlying_logic": "前提假设：善恶二分并非永恒→推理链条：追溯其历史功能→核心结论：需要重新估价。",
            },
            {
                "text": "哲学家的体系往往是本能的自白。",
                "chapter": "第一章",
                "core_theme": "哲学心理学",
                "background_context": "该表达概括尼采对哲学客观性神话的批判。",
                "underlying_logic": "前提假设：思想受生命状态影响→推理链条：哲学判断体现评价者本能→核心结论：哲学需要心理诊断。",
            },
            {
                "text": "自由精神要承受旧价值崩塌后的风险。",
                "chapter": "第二章",
                "core_theme": "自由精神",
                "background_context": "该表达概括尼采对真正自由精神的要求。",
                "underlying_logic": "前提假设：自由不是无代价怀疑→推理链条：摆脱教条会失去安全感→核心结论：自由精神必须承担创造责任。",
            },
        ],
        "learning_path": {"beginner": ["先阅读导言，理解价值重估的问题意识"], "intermediate": [], "advanced": [], "practice": []},
        "book_network": {"道德的谱系": "延续对基督教道德和奴隶道德的谱系式批判。"},
    }

    result = BookGraphQualityChecker().check(data, expected_chapters=6)

    assert not result.passed
    assert any("学习路径缺少" in issue for issue in result.issues)


def test_quality_gate_rejects_structurally_empty_sections_without_placeholder_keywords():
    """即使没有关键词占位符，空结构和低信息密度也应判定不合格。"""
    data = {
        "metadata": {
            "title": "善恶的彼岸",
            "author": "尼采",
            "author_intro": "尼采是德国哲学家，以价值重估、权力意志和对传统道德的批判著称。",
            "discipline": "哲学",
        },
        "time_background": {
            "macro_background": "十九世纪欧洲宗教权威衰退、科学兴起与现代平等主义扩张形成思想危机。",
            "micro_background": "本书处于尼采后期思想转向价值重估的阶段，承接其对形而上学和基督教道德的批判。",
            "core_contradiction": "现代人既追求自由，又继续依赖传统善恶框架来获得安全感。",
        },
        "critical_analysis": {
            "core_doubts": [],
            "feminist_perspective": "尼采对主体创造性的强调可以激发女性主义重读，但其文本中的性别化表达也保留男性中心局限。",
            "postcolonial_perspective": "尼采的欧洲语境使其价值批判需要接受跨文化伦理传统的重新检验。",
            "ethical_boundaries": {},
        },
        "chapters": [_valid_chapter() for _ in range(6)],
        "core_concepts": [
            {
                "name": "权力意志",
                "definition": "生命扩张和形式创造的根本冲动。",
                "deep_meaning": "该概念把道德判断还原到生命力量的组织方式，而不是抽象规则。",
                "underlying_logic": "前提假设：生命不是静态存在→推理链条：生命不断解释、占有、塑形世界→核心结论：价值判断体现权力意志。",
            },
            {
                "name": "价值重估",
                "definition": "对既有善恶体系的根本审查与重新排序。",
                "deep_meaning": "它不是任意否定道德，而是追问道德背后的生命功能。",
                "underlying_logic": "前提假设：旧价值已失去创造力→推理链条：揭露其历史来源和心理功能→核心结论：必须创造新价值。",
            },
            {
                "name": "自由精神",
                "definition": "能够脱离群体道德和教条束缚的独立思想者。",
                "deep_meaning": "自由精神不是随意怀疑，而是能承受无保障状态并继续创造价值。",
                "underlying_logic": "前提假设：思想受传统价值束缚→推理链条：摆脱教条并进行自我试炼→核心结论：自由精神承担价值创造风险。",
            },
        ],
        "key_insights": [
            {
                "title": "善恶不是永恒实体",
                "description": "",
                "underlying_logic": "前提假设：道德概念有历史来源→推理链条：考察善恶如何服务不同生命类型→核心结论：善恶应被谱系化分析。",
            },
            {
                "title": "哲学体系暴露哲学家的本能",
                "description": "尼采把哲学主张视为生命状态和欲望结构的症状，而不只是抽象论证。",
                "underlying_logic": "前提假设：思想并非脱离身体→推理链条：哲学判断体现评价者的生命需要→核心结论：哲学也应接受心理诊断。",
            },
        ],
        "key_cases": [
            {
                "name": "未命名",
                "source_chapter": "",
                "event_description": "",
                "historical_limitations": "",
            }
        ],
        "key_quotes": [
            {
                "text": "善恶的彼岸不在于超越，而在于重新评估价值的根基。",
                "chapter": "",
                "core_theme": "",
                "background_context": "",
                "underlying_logic": "",
            },
            {
                "text": "权力意志不是权力的欲望，而是生命本身的冲动。",
                "chapter": "",
                "core_theme": "",
                "background_context": "",
                "underlying_logic": "",
            },
            {
                "text": "教条主义是思想的死亡。",
                "chapter": "",
                "core_theme": "",
                "background_context": "",
                "underlying_logic": "",
            },
        ],
        "learning_path": {"beginner": [], "intermediate": [], "advanced": [], "practice": []},
        "book_network": {},
    }

    result = BookGraphQualityChecker().check(data, expected_chapters=6)

    assert not result.passed
    assert any("伦理边界缺少" in issue for issue in result.issues)
    assert any("学习路径缺少" in issue for issue in result.issues)
    assert any("关联书籍网络缺少" in issue for issue in result.issues)
    assert any("关键洞见缺少核心内容描述" in issue for issue in result.issues)
    assert any("关键案例缺少名称、来源或事件描述证据" in issue for issue in result.issues)
    assert any("金句萃取缺少来源章节、时代背景或底层逻辑证据" in issue for issue in result.issues)
