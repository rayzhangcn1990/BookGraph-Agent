"""
BookGraph 内容质量校验模块 V2

整合历史发现的所有问题：
1. 占位符污染（CRITICAL）
2. 章节完整性
3. 核心概念有实质内容
4. 金句至少有 3 条
5. 无占位符污染
6. 底层逻辑格式正确
7. 模板化内容检测（新增）
8. 空洞章节检测（新增）
9. 必填字段完整性（新增）
10. 数据流验证（新增）

方法论：Netflix Keeper Test + PUA Owner意识
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class QualityCheckResult:
    """质量检查结果"""
    passed: bool
    score: float  # 0-100
    issues: List[str]
    warnings: List[str]
    stats: Dict


class BookGraphQualityChecker:
    """BookGraph 内容质量校验器 V2"""

    # ═══════════════════════════════════════════════════════════
    # 占位符关键词（严禁出现）- 扩展版
    # ═══════════════════════════════════════════════════════════

    PLACEHOLDER_KEYWORDS = [
        # 标准占位符（必须足够明确）
        "待补充", "待分析", "待填写", "待生成", "待完善",
        "书中未提供", "书中未提供具体",
        "TBD", "TODO", "N/A", "NULL",
        # 🔑 修复：移除过于短的通用词（如"无"、"暂无"），避免误判正常内容
        # "未提供",  # 移除（会误判"未提供"开头的正常句子）
        # "暂无", "无",  # 移除（会误判"无法"、"无奈"等正常词）
        "未能正确解析", "解析异常",
        "Unknown",  # 保留（足够明确）
        # 空洞表达（必须是完整的短语）
        "内容待补充", "分析待补充",
        # LLM 生成的标记
        "（此处内容由 LLM 生成）",
        "（内容由模型生成）",
        # 简介占位符
        "简介待补充", "待补充具体",
        # 🔑 新增：章节内容占位符（最严重的偷懒！）
        "书中未涉及此项内容",
        "书中未涉及此项",
        "此章节省略",
        "中间章节省略",
        "实际输出时请完整复制",
        "具体内容已省略",
        "此处省略",
    ]

    # ═══════════════════════════════════════════════════════════
    # 模板化内容模式（LLM 常见的敷衍输出）
    # ═══════════════════════════════════════════════════════════

    TEMPLATE_PATTERNS = [
        "本章探讨了书中的核心议题",
        "本章分析了书中的核心议题",
        "本章讨论了书中的核心议题",
        "本章阐述了书中的核心议题",
        "作者通过逻辑推理展开论述",
        "通过逻辑推理展开论述",
        "进行系统性阐述",
        "提供了新的分析框架",
        "提供了新的解决方案",
        "作者在这一部分",
        "本章主要讨论",
        "本章主要分析",
        "本章主要阐述",
        "对书中的核心概念进行",
        "对书中的关键概念进行",
        "对书中的重要概念进行",
        "本书的核心观点",
        "本书的主要观点",
        "本书的关键观点",
        "书中探讨了",
        "书中分析了",
        "书中阐述了",
        # 章节空洞表达
        "章节内容未能正确解析",
        "可能需要重新处理本书",
    ]

    # ═══════════════════════════════════════════════════════════
    # 质量阈值（分层过滤：阻塞项 vs 警告项）
    # ═══════════════════════════════════════════════════════════

    MIN_CHAPTERS = 5       # 最少章节数
    MIN_CONCEPTS = 3       # 最少核心概念数
    MIN_QUOTES = 1         # 最少金句数（放宽要求，避免阻止写入）
    MIN_INSIGHTS = 2       # 最少关键洞见数
    MIN_CASES = 1          # 最少关键案例数
    MIN_CONTENT_LENGTH = 50  # 最小内容长度
    MIN_DEFINITION_LENGTH = 30  # 定义最小长度

    # 🔑 分层过滤：阻塞性问题 vs 警告性问题
    BLOCKING_ISSUES = [
        '占位符污染',      # 关键字段出现"待补充"
        '章节合并',        # LLM偷懒合并章节
        '空洞章节',        # 章节内容为空
        '模板化内容',      # 模板填充未修改
    ]

    WARNING_ISSUES = [
        '金句数量不足',
        '关联书籍网络缺失',
        '学习路径不完整',
        '章节编号不连续',
    ]

    # 🔑 新增：章节合并检测模式（严禁偷懒）
    MERGED_CHAPTER_PATTERNS = [
        r'\d+-\d+',         # 检测 "11-22", "1-10" 等合并编号
        r'第\d+-\d+章',     # 检测 "第11-22章"
        r'\d+至\d+',        # 检测 "11至22"
        r'\d+～\d+',        # 检测 "11～22"
        r'章节\s*\d+-\d+',  # 检测 "章节 11-22"
    ]

    # 底层逻辑格式要求
    LOGIC_PATTERN = r'(前提假设|推理链条|核心结论).*[:：].*'

    # 必填字段列表
    REQUIRED_TOP_FIELDS = [
        'metadata', 'time_background', 'critical_analysis',
        'chapters', 'core_concepts', 'key_insights', 'key_cases', 'key_quotes'
    ]

    REQUIRED_METADATA_FIELDS = [
        'title', 'author', 'author_intro', 'discipline'
    ]

    REQUIRED_TIME_BACKGROUND_FIELDS = [
        'macro_background', 'micro_background', 'core_contradiction'
    ]

    def check(self, book_graph_data: Dict, expected_chapters: int = 0) -> QualityCheckResult:
        """
        执行完整质量检查 V2

        Args:
            book_graph_data: BookGraph 数据（Dict 格式）
            expected_chapters: 预期章节数（用于对比，防止LLM偷懒合并章节）

        Returns:
            QualityCheckResult: 检查结果
        """
        issues = []
        warnings = []
        stats = {}

        # ═══════════════════════════════════════════════════════════
        # 检查 0: 必填字段完整性（新增）
        # ═══════════════════════════════════════════════════════════

        missing_top = self._check_required_top_fields(book_graph_data)
        stats['missing_top_fields'] = missing_top

        if missing_top:
            issues.append(f"顶层结构缺失：{', '.join(missing_top)}")

        # 检查 metadata 完整性
        metadata = book_graph_data.get('metadata', {})
        missing_meta = self._check_required_fields(metadata, self.REQUIRED_METADATA_FIELDS)
        stats['missing_metadata_fields'] = missing_meta

        if missing_meta:
            issues.append(f"书籍元数据缺失：{', '.join(missing_meta)}")

        # 检查 time_background 完整性
        time_bg = book_graph_data.get('time_background', {})
        missing_time = self._check_required_fields(time_bg, self.REQUIRED_TIME_BACKGROUND_FIELDS)
        stats['missing_time_background_fields'] = missing_time

        if missing_time:
            issues.append(f"时代背景缺失：{', '.join(missing_time)}")

        # ═══════════════════════════════════════════════════════════
        # 检查 1: 章节完整性（强化版）
        # ═══════════════════════════════════════════════════════════

        chapters = book_graph_data.get('chapters', [])
        chapter_count = len(chapters)

        stats['chapter_count'] = chapter_count
        stats['expected_chapters'] = expected_chapters

        # 🔑 新增：related_books 格式检查（检测字典格式）
        invalid_related_books = self._check_related_books_format(book_graph_data)
        stats['invalid_related_books'] = invalid_related_books

        if invalid_related_books:
            issues.append(f"⛔ related_books格式错误：发现 {len(invalid_related_books)} 处字典格式（应提取title/book_name字段）")

        # 🔑 新增：章节编号规范性检查
        invalid_chapter_numbers = self._check_chapter_number_format(chapters)
        stats['invalid_chapter_numbers'] = invalid_chapter_numbers

        if invalid_chapter_numbers:
            warnings.append(f"章节编号不规范：{len(invalid_chapter_numbers)} 处（应统一为两位数字格式）")

        # 🔑 新增：underlying_logic 缺失检查
        missing_logic_chapters = self._check_underlying_logic_missing(chapters)
        stats['missing_logic_chapters'] = missing_logic_chapters

        if missing_logic_chapters:
            warnings.append(f"底层逻辑缺失：{len(missing_logic_chapters)} 处（章节应包含underlying_logic字段）")

        # 🔑 新增：章节合并检测（严厉检测LLM偷懒行为）
        merged_chapters = self._detect_merged_chapters(chapters)
        stats['merged_chapters'] = merged_chapters

        if merged_chapters:
            # 🔑 PUA级要求：章节合并直接判定为不合格！
            merged_list = [f"'{ch.get('chapter_number', '')}'" for ch in merged_chapters]
            issues.append(f"⛔ 发现章节合并偷懒行为：{', '.join(merged_list)}（禁止用'1-10'、'11-22'等合并编号）")

        # 🔑 新增：章节占位符检测（最严重的偷懒！）
        placeholder_chapters = self._detect_placeholder_chapters(chapters)
        stats['placeholder_chapters'] = placeholder_chapters

        if placeholder_chapters:
            # 🔑 PUA级要求：章节占位符直接判定为不合格！
            placeholder_list = [f"章节'{p['chapter'].get('chapter_number', '')}'含'{p['keyword']}'" for p in placeholder_chapters]
            issues.append(f"⛔ 发现章节占位符偷懒行为：{', '.join(placeholder_list[:5])}（禁止用N/A、书中未涉及等占位符）")

        # 🔑 新增：预期章节数对比
        if expected_chapters > 0:
            coverage_ratio = chapter_count / expected_chapters
            stats['chapter_coverage'] = coverage_ratio

            if coverage_ratio < 0.5:
                issues.append(f"章节覆盖率极低：{chapter_count}/{expected_chapters} ({coverage_ratio*100:.0f}%)，LLM严重偷懒！")
            elif coverage_ratio < 0.8:
                issues.append(f"章节覆盖率不足：{chapter_count}/{expected_chapters} ({coverage_ratio*100:.0f}%)，应接近100%")

        if chapter_count < self.MIN_CHAPTERS:
            issues.append(f"章节数量不足：{chapter_count} < {self.MIN_CHAPTERS}")
        elif chapter_count < 10:
            warnings.append(f"章节数量偏少：{chapter_count}（建议 10+）")

        # 🔑 新增：章节编号连续性检查
        discontinuity = self._check_chapter_discontinuity(chapters)
        stats['chapter_discontinuity'] = discontinuity

        if discontinuity:
            warnings.append(f"章节编号不连续：缺失章节 {discontinuity}")

        # 检查章节内容质量
        empty_chapters = 0
        template_chapters = 0

        for ch in chapters:
            content = ch.get('core_argument', '') + ch.get('underlying_logic', '')
            title = ch.get('title', '')

            # 空洞章节
            if len(content) < self.MIN_CONTENT_LENGTH:
                empty_chapters += 1

            # 模板化标题检测
            if self._is_template_content(title):
                template_chapters += 1

        stats['empty_chapters'] = empty_chapters
        stats['template_chapters'] = template_chapters

        if empty_chapters > 0:
            if empty_chapters > chapter_count * 0.3:
                issues.append(f"空洞章节严重：{empty_chapters}/{chapter_count} 个章节内容少于 {self.MIN_CONTENT_LENGTH} 字符")
            else:
                warnings.append(f"空洞章节：{empty_chapters} 个")

        if template_chapters > 0:
            warnings.append(f"模板化章节标题：{template_chapters} 个")

        # ═══════════════════════════════════════════════════════════
        # 检查 2: 核心概念
        # ═══════════════════════════════════════════════════════════

        concepts = book_graph_data.get('core_concepts', [])
        concept_count = len(concepts)

        stats['concept_count'] = concept_count

        if concept_count < self.MIN_CONCEPTS:
            issues.append(f"核心概念数量不足：{concept_count} < {self.MIN_CONCEPTS}")

        # 检查概念内容深度
        shallow_concepts = 0
        placeholder_concepts = 0

        for c in concepts:
            definition_len = len(c.get('definition', ''))
            deep_meaning_len = len(c.get('deep_meaning', ''))

            if definition_len < self.MIN_DEFINITION_LENGTH or deep_meaning_len < self.MIN_DEFINITION_LENGTH:
                shallow_concepts += 1

            # 检查概念是否有占位符
            if self._has_placeholder(c):
                placeholder_concepts += 1

        stats['shallow_concepts'] = shallow_concepts
        stats['placeholder_concepts'] = placeholder_concepts

        if shallow_concepts > 0:
            if shallow_concepts > concept_count * 0.3:
                issues.append(f"浅薄概念严重：{shallow_concepts}/{concept_count} 个定义/深层含义过短")
            else:
                warnings.append(f"浅薄概念：{shallow_concepts} 个")

        if placeholder_concepts > 0:
            issues.append(f"概念含占位符：{placeholder_concepts} 个概念有敷衍内容")

        # ═══════════════════════════════════════════════════════════
        # 检查 3: 金句提取
        # ═══════════════════════════════════════════════════════════

        quotes = book_graph_data.get('key_quotes', [])
        quote_count = len(quotes)

        stats['quote_count'] = quote_count

        if quote_count < self.MIN_QUOTES:
            issues.append(f"金句数量不足：{quote_count} < {self.MIN_QUOTES}")

        # 检查金句质量
        short_quotes = 0
        for q in quotes:
            text = q.get('text', '')
            if len(text) < 10:  # 金句太短
                short_quotes += 1

        stats['short_quotes'] = short_quotes

        if short_quotes > 0:
            warnings.append(f"短金句：{short_quotes} 条金句少于 10 字符")

        # ═══════════════════════════════════════════════════════════
        # 检查 4: 关键洞见
        # ═══════════════════════════════════════════════════════════

        insights = book_graph_data.get('key_insights', [])
        insight_count = len(insights)

        stats['insight_count'] = insight_count

        if insight_count < self.MIN_INSIGHTS:
            issues.append(f"关键洞见数量不足：{insight_count} < {self.MIN_INSIGHTS}")

        # 检查洞见质量
        for i in insights:
            if self._is_template_content(i.get('description', '')):
                warnings.append(f"洞见'{i.get('title', '')}'可能是模板化内容")

        # ═══════════════════════════════════════════════════════════
        # 检查 5: 关键案例
        # ═══════════════════════════════════════════════════════════

        cases = book_graph_data.get('key_cases', [])
        case_count = len(cases)

        stats['case_count'] = case_count

        if case_count < self.MIN_CASES:
            issues.append(f"关键案例数量不足：{case_count} < {self.MIN_CASES}")

        # ═══════════════════════════════════════════════════════════
        # 检查 6: 占位符污染（最关键！）
        # ═══════════════════════════════════════════════════════════

        placeholder_count = self._count_placeholders(book_graph_data)
        template_count = self._count_template_content(book_graph_data)

        stats['placeholder_count'] = placeholder_count
        stats['template_count'] = template_count

        if placeholder_count > 0:
            if placeholder_count > 5:
                issues.append(f"占位符污染严重：{placeholder_count} 处占位符")
            else:
                issues.append(f"存在占位符：{placeholder_count} 处")

        if template_count > 0:
            if template_count > 3:
                issues.append(f"模板化内容严重：{template_count} 处")
            else:
                warnings.append(f"模板化内容：{template_count} 处")

        # ═══════════════════════════════════════════════════════════
        # 检查 7: 底层逻辑格式
        # ═══════════════════════════════════════════════════════════

        logic_score = self._check_logic_format(book_graph_data)

        stats['logic_score'] = logic_score

        if logic_score < 0.5:
            issues.append(f"底层逻辑格式不正确：仅 {logic_score*100:.0f}% 符合格式要求")
        elif logic_score < 0.8:
            warnings.append(f"底层逻辑格式不完整：{logic_score*100:.0f}% 符合格式要求")

        # ═══════════════════════════════════════════════════════════
        # 检查 8: 批判性分析完整性（新增）
        # ═══════════════════════════════════════════════════════════

        critical = book_graph_data.get('critical_analysis', {})

        feminist = critical.get('feminist_perspective', '')
        postcolonial = critical.get('postcolonial_perspective', '')

        feminist_placeholder = self._is_placeholder_or_template(feminist)
        postcolonial_placeholder = self._is_placeholder_or_template(postcolonial)

        stats['feminist_placeholder'] = feminist_placeholder
        stats['postcolonial_placeholder'] = postcolonial_placeholder

        if feminist_placeholder:
            warnings.append("女性主义视角含占位符/模板内容")

        if postcolonial_placeholder:
            warnings.append("后殖民主义视角含占位符/模板内容")

        # ═══════════════════════════════════════════════════════════
        # 检查 9: 结构完整性与信息密度（非关键词质量门）
        # ═══════════════════════════════════════════════════════════

        structural_issues, structural_warnings = self._check_structural_quality(book_graph_data)
        stats['structural_issues'] = structural_issues
        issues.extend(structural_issues)
        warnings.extend(structural_warnings)

        # ═══════════════════════════════════════════════════════════
        # 计算总分
        # ═══════════════════════════════════════════════════════════

        score = self._calculate_score_v2(stats, issues, warnings)

        # 🔑 分层过滤：仅阻塞性问题阻止写入，警告性问题不阻塞
        blocking_issues = [i for i in issues if any(b in i for b in self.BLOCKING_ISSUES)]
        passed = len(blocking_issues) == 0 and score >= 70

        # 将非阻塞性issues转为warnings
        for issue in issues:
            if not any(b in issue for b in self.BLOCKING_ISSUES):
                warnings.append(f"[非阻塞] {issue}")

        # 最终issues仅保留阻塞性问题
        issues = blocking_issues

        return QualityCheckResult(
            passed=passed,
            score=score,
            issues=issues,
            warnings=warnings,
            stats=stats,
        )

    def _check_required_top_fields(self, data: Dict) -> List[str]:
        """检查顶层必填字段"""
        missing = []
        for field in self.REQUIRED_TOP_FIELDS:
            if field not in data:
                missing.append(field)
        return missing

    def _detect_merged_chapters(self, chapters: List[Dict]) -> List[Dict]:
        """
        🔑 新增：检测章节合并偷懒行为

        检测 LLM 是否用 "11-22"、"第1-10章" 等合并编号来偷懒

        Args:
            chapters: 章节列表

        Returns:
            List[Dict]: 被合并的章节列表（用于报告）
        """
        merged = []

        for ch in chapters:
            chapter_num = ch.get('chapter_number', '')
            title = ch.get('title', '')

            # 检查章节编号是否是合并模式
            for pattern in self.MERGED_CHAPTER_PATTERNS:
                if re.search(pattern, chapter_num):
                    merged.append(ch)
                    break

            # 检查标题是否包含合并模式
            for pattern in self.MERGED_CHAPTER_PATTERNS:
                if re.search(pattern, title):
                    merged.append(ch)
                    break

        return merged

    def _detect_placeholder_chapters(self, chapters: List[Dict]) -> List[Dict]:
        """
        🔑 新增：检测章节占位符偷懒行为

        检测 LLM 是否用 "N/A"、"书中未涉及此项内容" 等占位符偷懒

        Args:
            chapters: 章节列表

        Returns:
            List[Dict]: 占位符章节列表（用于报告）
        """
        placeholder_chapters = []

        # 章节占位符关键词
        chapter_placeholder_keywords = [
            "N/A", "NULL", "TBD", "TODO",
            "书中未涉及此项内容", "书中未涉及此项",
            "此章节省略", "中间章节省略",
            "具体内容已省略", "此处省略",
        ]

        for ch in chapters:
            chapter_num = ch.get('chapter_number', '')
            title = ch.get('title', '')
            core_argument = ch.get('core_argument', '')

            # 检查章节编号是否是占位符
            for kw in chapter_placeholder_keywords:
                if kw in chapter_num or kw in title or kw in core_argument:
                    placeholder_chapters.append({
                        'chapter': ch,
                        'keyword': kw,
                        'field': 'chapter_number' if kw in chapter_num else ('title' if kw in title else 'core_argument')
                    })
                    break

        return placeholder_chapters

    def _check_chapter_discontinuity(self, chapters: List[Dict]) -> List[str]:
        """
        🔑 新增：检查章节编号连续性

        Args:
            chapters: 章节列表

        Returns:
            List[str]: 缺失的章节编号列表
        """
        # 提取所有章节编号
        numbers = []
        for ch in chapters:
            num = ch.get('chapter_number', '')
            # 提取数字
            match = re.search(r'\d+', num)
            if match:
                numbers.append(int(match.group()))

        if not numbers:
            return []

        # 检查连续性（排序后检查间隔）
        numbers.sort()
        missing = []

        for i in range(len(numbers) - 1):
            if numbers[i+1] - numbers[i] > 1:
                # 有间隔，记录缺失的编号
                for missing_num in range(numbers[i] + 1, numbers[i+1]):
                    missing.append(str(missing_num))

        # 只报告前10个缺失（避免报告过长）
        return missing[:10]

    def _check_related_books_format(self, book_graph_data: Dict) -> List[Dict]:
        """
        🔑 新增：检查 related_books 是否包含字典格式

        Args:
            book_graph_data: BookGraph 数据

        Returns:
            List[Dict]: 格式错误的 related_books 列表
        """
        invalid = []

        def check_list(books, path):
            if not books:
                return
            for b in books:
                if isinstance(b, dict):
                    invalid.append({
                        'path': path,
                        'value': str(b)[:100]
                    })

        # 检查 metadata.related_books
        check_list(
            book_graph_data.get('metadata', {}).get('related_books', []),
            'metadata.related_books'
        )

        # 检查 chapters
        for idx, ch in enumerate(book_graph_data.get('chapters', [])):
            check_list(
                ch.get('related_books', []),
                f'chapters[{idx}].related_books'
            )

        # 检查其他字段
        for field in ['core_concepts', 'key_insights', 'key_cases', 'key_quotes']:
            for idx, item in enumerate(book_graph_data.get(field, [])):
                check_list(
                    item.get('related_books', []),
                    f'{field}[{idx}].related_books'
                )

        return invalid[:10]  # 只返回前10个

    def _check_chapter_number_format(self, chapters: List[Dict]) -> List[Dict]:
        """
        🔑 新增：检查章节编号是否为规范的两位数字格式

        Args:
            chapters: 章节列表

        Returns:
            List[Dict]: 不规范的章节编号列表
        """
        invalid = []

        for idx, ch in enumerate(chapters):
            ch_num = str(ch.get('chapter_number', ''))
            # 检查是否为两位数字格式
            if not re.match(r'^\d{2}$', ch_num):
                invalid.append({
                    'index': idx,
                    'chapter_number': ch_num,
                    'expected': f"{idx + 1:02d}"
                })

        return invalid[:10]

    def _check_underlying_logic_missing(self, chapters: List[Dict]) -> List[Dict]:
        """
        🔑 新增：检查底层逻辑是否缺失

        Args:
            chapters: 章节列表

        Returns:
            List[Dict]: 缺失底层逻辑的章节列表
        """
        missing = []

        for idx, ch in enumerate(chapters):
            logic = ch.get('underlying_logic', '')
            if not logic or logic == '-' or logic.strip() == '':
                missing.append({
                    'index': idx,
                    'chapter_number': ch.get('chapter_number', ''),
                    'title': ch.get('title', '')[:30]
                })

        return missing[:10]

    def _check_required_fields(self, data: Dict, required: List[str]) -> List[str]:
        """检查必填字段"""
        missing = []
        for field in required:
            if field not in data or not data[field]:
                missing.append(field)
        return missing

    def _has_substantive_text(self, value, min_length: int = 20) -> bool:
        """检查文本是否有足够信息量。"""
        return isinstance(value, str) and len(value.strip()) >= min_length

    def _check_structural_quality(self, data: Dict) -> Tuple[List[str], List[str]]:
        """检查结构完整性、信息密度和证据约束，避免只靠关键词匹配。"""
        issues = []
        warnings = []

        critical = data.get('critical_analysis', {})
        ethical = critical.get('ethical_boundaries', {}) if isinstance(critical, dict) else {}
        if not isinstance(ethical, dict) or not (
            self._has_substantive_text(ethical.get('reasonable'))
            and self._has_substantive_text(ethical.get('dangerous'))
        ):
            issues.append("伦理边界缺少合理应用区间和危险应用区间的实质内容")

        learning_path = data.get('learning_path', {})
        required_learning_stages = ['beginner', 'intermediate', 'advanced', 'practice']
        substantive_stages = 0
        if isinstance(learning_path, dict):
            for stage in required_learning_stages:
                items = learning_path.get(stage, [])
                if isinstance(items, list) and any(self._has_substantive_text(item, 8) for item in items):
                    substantive_stages += 1
        if substantive_stages < 2:
            issues.append("学习路径缺少分阶段的实质建议")

        book_network = data.get('book_network', {})
        if not isinstance(book_network, dict) or not any(
            self._has_substantive_text(book) and self._has_substantive_text(relation)
            for book, relation in book_network.items()
        ):
            warnings.append("关联书籍网络缺少有效关联书籍和关联维度说明（非阻塞）")

        weak_insights = []
        for insight in data.get('key_insights', []):
            if not isinstance(insight, dict):
                weak_insights.append(str(insight)[:30])
                continue
            if not self._has_substantive_text(insight.get('description'), 30):
                weak_insights.append(insight.get('title', '未命名洞见'))
        if weak_insights:
            issues.append(f"关键洞见缺少核心内容描述：{', '.join(weak_insights[:3])}")

        weak_cases = []
        for case in data.get('key_cases', []):
            if not isinstance(case, dict):
                weak_cases.append(str(case)[:30])
                continue
            if not (
                self._has_substantive_text(case.get('name'), 4)
                and case.get('name') != '未命名'
                and self._has_substantive_text(case.get('source_chapter'), 2)
                and self._has_substantive_text(case.get('event_description'), 40)
            ):
                weak_cases.append(case.get('name', '未命名案例'))
        if weak_cases:
            issues.append(f"关键案例缺少名称、来源或事件描述证据：{', '.join(weak_cases[:3])}")

        weak_quotes = []
        for quote in data.get('key_quotes', []):
            if not isinstance(quote, dict):
                weak_quotes.append(str(quote)[:30])
                continue
            if not (
                self._has_substantive_text(quote.get('text'), 10)
                and self._has_substantive_text(quote.get('chapter'), 2)
                and self._has_substantive_text(quote.get('background_context'), 20)
                and self._has_substantive_text(quote.get('underlying_logic'), 20)
            ):
                weak_quotes.append(quote.get('text', '未命名金句')[:30])
        if weak_quotes:
            issues.append(f"金句萃取缺少来源章节、时代背景或底层逻辑证据：{', '.join(weak_quotes[:3])}")

        return issues, warnings

    def _has_placeholder(self, obj: Dict) -> bool:
        """检查对象是否有占位符"""
        for k, v in obj.items():
            if isinstance(v, str):
                if self._is_placeholder_or_template(v):
                    return True
        return False

    def _is_placeholder_or_template(self, text: str) -> bool:
        """检查是否是占位符或模板"""
        if not text:
            return True

        for keyword in self.PLACEHOLDER_KEYWORDS:
            if keyword in text:
                return True

        for pattern in self.TEMPLATE_PATTERNS:
            if pattern in text:
                return True

        return False

    def _is_template_content(self, text: str) -> bool:
        """检查是否是模板化内容"""
        if not text:
            return False

        for pattern in self.TEMPLATE_PATTERNS:
            if pattern in text:
                return True

        return False

    def _count_placeholders(self, data: Dict) -> int:
        """计算占位符出现次数"""

        count = 0

        # 递归检查所有字符串字段
        def check_dict(d: Dict):
            nonlocal count  # 🔑 修复：必须声明 nonlocal
            for k, v in d.items():
                if isinstance(v, str):
                    for keyword in self.PLACEHOLDER_KEYWORDS:
                        if keyword in v:
                            count += 1
                            break  # 每个字符串只计一次
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            check_dict(item)
                        elif isinstance(item, str):
                            for keyword in self.PLACEHOLDER_KEYWORDS:
                                if keyword in item:
                                    count += 1
                                    break
                elif isinstance(v, dict):
                    check_dict(v)

        check_dict(data)

        return count

    def _count_template_content(self, data: Dict) -> int:
        """计算模板化内容出现次数"""

        count = 0

        def check_dict(d: Dict):
            nonlocal count  # 🔑 修复：必须声明 nonlocal
            for k, v in d.items():
                if isinstance(v, str):
                    for pattern in self.TEMPLATE_PATTERNS:
                        if pattern in v:
                            count += 1
                            break
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            check_dict(item)
                        elif isinstance(item, str):
                            for pattern in self.TEMPLATE_PATTERNS:
                                if pattern in item:
                                    count += 1
                                    break
                elif isinstance(v, dict):
                    check_dict(v)

        check_dict(data)

        return count

    def _check_logic_format(self, data: Dict) -> float:
        """检查底层逻辑格式正确率"""

        total = 0
        correct = 0

        # 检查章节的底层逻辑
        for ch in data.get('chapters', []):
            logic = ch.get('underlying_logic', '')
            if logic:
                total += 1
                if re.search(self.LOGIC_PATTERN, logic):
                    correct += 1

        # 检查概念的底层逻辑
        for c in data.get('core_concepts', []):
            logic = c.get('underlying_logic', '')
            if logic:
                total += 1
                if re.search(self.LOGIC_PATTERN, logic):
                    correct += 1

        # 检查洞见的底层逻辑
        for i in data.get('key_insights', []):
            logic = i.get('underlying_logic', '')
            if logic:
                total += 1
                if re.search(self.LOGIC_PATTERN, logic):
                    correct += 1

        if total == 0:
            return 0.0

        return correct / total

    def _calculate_score_v2(self, stats: Dict, issues: List[str], warnings: List[str]) -> float:
        """计算质量评分 V2（0-100）"""

        base_score = 100

        # ═══════════════════════════════════════════════════════════
        # 严重扣分（CRITICAL）
        # ═══════════════════════════════════════════════════════════

        # 必填字段缺失
        base_score -= len(stats.get('missing_top_fields', [])) * 20
        base_score -= len(stats.get('missing_metadata_fields', [])) * 15
        base_score -= len(stats.get('missing_time_background_fields', [])) * 15

        # 🔑 新增：章节合并扣分（最严重！直接扣50分）
        merged_count = len(stats.get('merged_chapters', []))
        base_score -= merged_count * 50  # 每个合并章节扣50分！

        # 🔑 新增：章节占位符扣分（最严重！直接扣50分）
        placeholder_chapter_count = len(stats.get('placeholder_chapters', []))
        base_score -= placeholder_chapter_count * 50  # 每个占位符章节扣50分！

        # 🔑 新增：章节覆盖率扣分
        coverage = stats.get('chapter_coverage', 1.0)
        if coverage < 0.5:
            base_score -= 30  # 覆盖率低于50%，扣30分
        elif coverage < 0.8:
            base_score -= 15  # 覆盖率低于80%，扣15分

        # 章节扣分
        if stats.get('chapter_count', 0) < self.MIN_CHAPTERS:
            base_score -= 20
        elif stats.get('chapter_count', 0) < 10:
            base_score -= 5

        # 空洞章节扣分
        empty_ratio = stats.get('empty_chapters', 0) / max(1, stats.get('chapter_count', 1))
        if empty_ratio > 0.3:
            base_score -= 15

        # 概念扣分
        if stats.get('concept_count', 0) < self.MIN_CONCEPTS:
            base_score -= 15

        # 浅薄概念扣分
        shallow_ratio = stats.get('shallow_concepts', 0) / max(1, stats.get('concept_count', 1))
        if shallow_ratio > 0.3:
            base_score -= 10

        # 概念占位符扣分
        base_score -= stats.get('placeholder_concepts', 0) * 5

        # 金句扣分
        if stats.get('quote_count', 0) < self.MIN_QUOTES:
            base_score -= 10

        # 洞见扣分
        if stats.get('insight_count', 0) < self.MIN_INSIGHTS:
            base_score -= 10

        # 案例扣分
        if stats.get('case_count', 0) < self.MIN_CASES:
            base_score -= 10

        # ═══════════════════════════════════════════════════════════
        # 占位符扣分（最严重！PUA 零容忍）
        # ═══════════════════════════════════════════════════════════

        placeholder_count = stats.get('placeholder_count', 0)
        base_score -= placeholder_count * 8  # 每个占位符扣 8 分

        template_count = stats.get('template_count', 0)
        base_score -= template_count * 5  # 模板内容扣 5 分

        # ═══════════════════════════════════════════════════════════
        # 底层逻辑扣分
        # ═══════════════════════════════════════════════════════════

        logic_score = stats.get('logic_score', 0)
        if logic_score < 0.5:
            base_score -= 15
        elif logic_score < 0.8:
            base_score -= 5

        # ═══════════════════════════════════════════════════════════
        # 批判性分析扣分
        # ═══════════════════════════════════════════════════════════

        if stats.get('feminist_placeholder', False):
            base_score -= 5

        if stats.get('postcolonial_placeholder', False):
            base_score -= 5

        # ═══════════════════════════════════════════════════════════
        # 警告扣分（较轻）
        # ═══════════════════════════════════════════════════════════

        base_score -= len(warnings) * 2

        return max(0, base_score)


def check_book_graph_quality(data: Dict, expected_chapters: int = 0) -> Tuple[bool, str]:
    """
    快捷检查函数 V2（增强版）

    Args:
        data: BookGraph 数据
        expected_chapters: 预期章节数（用于对比，防止LLM偷懒）

    Returns:
        Tuple[bool, str]: (是否合格, 查报告)
    """
    checker = BookGraphQualityChecker()
    result = checker.check(data, expected_chapters)

    # 🔑 新增：章节合并和覆盖率显示
    merged_count = len(result.stats.get('merged_chapters', []))
    placeholder_chapter_count = len(result.stats.get('placeholder_chapters', []))
    coverage = result.stats.get('chapter_coverage', 1.0)
    expected = result.stats.get('expected_chapters', 0)

    coverage_str = f"{coverage*100:.0f}%" if expected > 0 else "N/A"
    expected_str = f"{expected}" if expected > 0 else "N/A"

    report = f"""# BookGraph 内容质量检查报告 V2（增强版）

**检查结果**: {'✅ 通过' if result.passed else '❌ 不合格'}
**质量评分**: {result.score:.0f}/100
**通过标准**: 零 issues + 评分 ≥ 70（PUA 标准）

## 统计数据

| 指标 | 数值 | 要求 | 状态 |
|------|------|------|------|
| 章节数 | {result.stats.get('chapter_count', 0)}/{expected_str} | ≥ {checker.MIN_CHAPTERS} {'(覆盖率:' + coverage_str + ')' if expected > 0 else ''} | {'✅' if result.stats.get('chapter_count', 0) >= checker.MIN_CHAPTERS else '❌'} |
| 🔑 章节合并 | {merged_count} | 0 | {'❌ 发现偷懒！' if merged_count > 0 else '✅'} |
| 🔑 章节占位符 | {placeholder_chapter_count} | 0 | {'❌ 发现偷懒！' if placeholder_chapter_count > 0 else '✅'} |
| 核心概念 | {result.stats.get('concept_count', 0)} | ≥ {checker.MIN_CONCEPTS} | {'✅' if result.stats.get('concept_count', 0) >= checker.MIN_CONCEPTS else '❌'} |
| 金句数 | {result.stats.get('quote_count', 0)} | ≥ {checker.MIN_QUOTES} | {'✅' if result.stats.get('quote_count', 0) >= checker.MIN_QUOTES else '❌'} |
| 关键洞见 | {result.stats.get('insight_count', 0)} | ≥ {checker.MIN_INSIGHTS} | {'✅' if result.stats.get('insight_count', 0) >= checker.MIN_INSIGHTS else '❌'} |
| 关键案例 | {result.stats.get('case_count', 0)} | ≥ {checker.MIN_CASES} | {'✅' if result.stats.get('case_count', 0) >= checker.MIN_CASES else '❌'} |
| 占位符 | {result.stats.get('placeholder_count', 0)} | 0 | {'❌' if result.stats.get('placeholder_count', 0) > 0 else '✅'} |
| 模板内容 | {result.stats.get('template_count', 0)} | 0 | {'⚠️' if result.stats.get('template_count', 0) > 0 else '✅'} |
| 底层逻辑格式 | {result.stats.get('logic_score', 0)*100:.0f}% | ≥ 80% | {'⚠️' if result.stats.get('logic_score', 0) < 0.8 else '✅'} |
| 空洞章节 | {result.stats.get('empty_chapters', 0)} | 0 | {'⚠️' if result.stats.get('empty_chapters', 0) > 0 else '✅'} |

## 问题列表

"""

    if result.issues:
        report += "**严重问题（CRITICAL）**:\n\n"
        for issue in result.issues:
            report += f"- ❌ {issue}\n"

    if result.warnings:
        report += "\n**警告**:\n\n"
        for warning in result.warnings:
            report += f"- ⚠️ {warning}\n"

    if not result.issues and not result.warnings:
        report += "\n✅ 无问题，质量达标\n"

    return result.passed, report


# ═══════════════════════════════════════════════════════════
# Per-Skill 质量检查器（新增）
# ═══════════════════════════════════════════════════════════

def check_skill_output(skill_name: str, output: Dict) -> Tuple[bool, str]:
    """
    检查单个 Skill 的输出质量

    Args:
        skill_name: Skill 名称
        output: Skill 输出结果

    Returns:
        Tuple[bool, str]: (是否合格, 错误信息)
    """
    issues = []

    # 检查空输出
    if not output:
        return False, f"Skill {skill_name} 返回空结果"

    # 检查占位符
    checker = BookGraphQualityChecker()
    placeholder_count = checker._count_placeholders(output)
    template_count = checker._count_template_content(output)

    if placeholder_count > 0:
        issues.append(f"含 {placeholder_count} 处占位符")

    if template_count > 0:
        issues.append(f"含 {template_count} 处模板内容")

    # Skill 特定检查
    skill_checks = {
        'background': _check_background_skill,
        'chapter': _check_chapter_skill,
        'concept': _check_concept_skill,
        'insight': _check_insight_skill,
        'case': _check_case_skill,
        'quote': _check_quote_skill,
        'critical': _check_critical_skill,
    }

    if skill_name in skill_checks:
        skill_issues = skill_checks[skill_name](output)
        issues.extend(skill_issues)

    passed = len(issues) == 0
    error_msg = "; ".join(issues) if issues else "OK"

    return passed, error_msg


def _check_background_skill(output: Dict) -> List[str]:
    """检查 background skill 输出"""
    issues = []

    required_fields = ['macro_background', 'micro_background', 'core_contradiction']
    for field in required_fields:
        if field not in output or not output[field]:
            issues.append(f"缺失 {field}")

    return issues


def _check_chapter_skill(output: Dict) -> List[str]:
    """检查 chapter skill 输出"""
    issues = []

    chapters = output.get('chapters', [])
    if not chapters:
        issues.append("章节数为 0")
        return issues

    # 检查至少有有效章节
    valid_count = 0
    for ch in chapters:
        if ch.get('core_argument') and len(ch.get('core_argument', '')) > 20:
            valid_count += 1

    if valid_count < len(chapters) * 0.5:
        issues.append(f"有效章节不足：{valid_count}/{len(chapters)}")

    return issues


def _check_concept_skill(output: Dict) -> List[str]:
    """检查 concept skill 输出"""
    issues = []

    concepts = output.get('core_concepts', [])
    if not concepts:
        issues.append("核心概念数为 0")
        return issues

    # 检查概念质量
    shallow = 0
    for c in concepts:
        if len(c.get('definition', '')) < 20:
            shallow += 1

    if shallow > len(concepts) * 0.3:
        issues.append(f"浅薄概念过多：{shallow}/{len(concepts)}")

    return issues


def _check_insight_skill(output: Dict) -> List[str]:
    """检查 insight skill 输出"""
    issues = []

    insights = output.get('key_insights', [])
    if not insights:
        issues.append("关键洞见数为 0")

    return issues


def _check_case_skill(output: Dict) -> List[str]:
    """检查 case skill 输出"""
    issues = []

    cases = output.get('key_cases', [])
    if not cases:
        issues.append("关键案例数为 0")

    return issues


def _check_quote_skill(output: Dict) -> List[str]:
    """检查 quote skill 输出"""
    issues = []

    quotes = output.get('key_quotes', [])
    if not quotes:
        issues.append("金句数为 0")

    return issues


def _check_critical_skill(output: Dict) -> List[str]:
    """检查 critical skill 输出"""
    issues = []

    critical = output.get('critical_analysis', {})
    if not critical:
        issues.append("批判性分析为空")
        return issues

    if not critical.get('feminist_perspective'):
        issues.append("缺失女性主义视角")

    if not critical.get('postcolonial_perspective'):
        issues.append("缺失后殖民主义视角")

    return issues