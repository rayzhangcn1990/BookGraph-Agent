"""
OCR Engine - 光学字符识别引擎

支持双引擎切换（PaddleOCR / Tesseract），处理图片型 PDF。
"""

from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re
import json
import os
from datetime import datetime

try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

from tqdm import tqdm


class OcrEngine:
    """
    OCR 引擎类
    
    功能：
    - 支持双引擎切换（PaddleOCR / Tesseract）
    - 处理单页图片和整个 PDF
    - 实现断点续传（已处理页面缓存）
    - OCR 后处理（修复错误、合并段落、清理页眉页脚）
    """

    def __init__(self, config: Dict = None):
        """
        初始化 OCR 引擎
        
        Args:
            config: 配置字典
                - engine: 'paddleocr' 或 'tesseract'
                - language: 'ch', 'en', 'ch+en'
                - enable_gpu: 是否启用 GPU
                - dpi: 渲染 DPI（默认 300）
        """
        self.config = config or {}
        self.engine_type = self.config.get('engine', 'paddleocr')
        self.language = self.config.get('language', 'ch')
        self.enable_gpu = self.config.get('enable_gpu', False)
        self.dpi = self.config.get('dpi', 300)
        
        # 缓存目录
        self.cache_dir = Path.home() / ".bookgraph" / "ocr_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化 OCR 引擎
        self._init_engine()

    def _init_engine(self):
        """初始化 OCR 引擎实例"""
        self.paddle_ocr = None
        self.tesseract_lang = None
        
        if self.engine_type == 'paddleocr' and PADDLEOCR_AVAILABLE:
            try:
                # PaddleOCR 语言映射
                lang_map = {
                    'ch': 'ch',
                    'en': 'en',
                    'ch+en': 'ch',
                    'ja': 'japan',
                    'ko': 'korean',
                }
                lang = lang_map.get(self.language, 'ch')
                
                self.paddle_ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang=lang,
                    use_gpu=self.enable_gpu,
                )
                print(f"✅ PaddleOCR 初始化成功（语言：{lang}）")
            except Exception as e:
                print(f"⚠️ PaddleOCR 初始化失败：{e}")
                # 回退到 Tesseract
                if TESSERACT_AVAILABLE:
                    self.engine_type = 'tesseract'
                    self._init_tesseract()
        
        elif self.engine_type == 'tesseract' and TESSERACT_AVAILABLE:
            self._init_tesseract()
        
        else:
            raise RuntimeError(
                "OCR 引擎不可用。请安装：\n"
                "  - PaddleOCR: pip install paddlepaddle paddleocr\n"
                "  - Tesseract: pip install pytesseract pillow + 安装 tesseract-ocr"
            )

    def _init_tesseract(self):
        """初始化 Tesseract 引擎"""
        # Tesseract 语言映射
        lang_map = {
            'ch': 'chi_sim+chi_tra',
            'en': 'eng',
            'ch+en': 'chi_sim+chi_tra+eng',
            'ja': 'jpn',
            'ko': 'kor',
        }
        self.tesseract_lang = lang_map.get(self.language, 'chi_sim+chi_tra')
        print(f"✅ Tesseract 初始化成功（语言：{self.tesseract_lang}）")

    def process_pdf_page(self, page_image: bytes) -> str:
        """
        处理单页图片，返回识别文字
        
        Args:
            page_image: PNG 图片数据（bytes）
            
        Returns:
            str: OCR 识别的文字
        """
        try:
            if self.engine_type == 'paddleocr' and self.paddle_ocr:
                return self._process_with_paddle(page_image)
            elif self.engine_type == 'tesseract':
                return self._process_with_tesseract(page_image)
            else:
                return ""
        except Exception as e:
            print(f"⚠️ OCR 识别失败：{e}")
            return ""

    def _process_with_paddle(self, page_image: bytes) -> str:
        """使用 PaddleOCR 处理图片"""
        # 将 bytes 转换为 numpy 数组
        import numpy as np
        from PIL import Image
        import io
        
        img = Image.open(io.BytesIO(page_image))
        img_array = np.array(img)
        
        # 执行 OCR
        result = self.paddle_ocr.ocr(img_array, cls=True)
        
        # 提取文字
        texts = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0]  # 文字内容
                    confidence = line[1][1]  # 置信度
                    
                    # 过滤低置信度结果
                    if confidence > 0.5:
                        texts.append(text)
        
        return "\n".join(texts)

    def _process_with_tesseract(self, page_image: bytes) -> str:
        """使用 Tesseract 处理图片"""
        from PIL import Image
        import io
        
        img = Image.open(io.BytesIO(page_image))
        
        # 执行 OCR
        text = pytesseract.image_to_string(
            img,
            lang=self.tesseract_lang,
            config='--psm 3',  # 自动页面分割
        )
        
        return text

    def process_pdf(
        self, 
        pdf_path: str, 
        output_path: Optional[str] = None
    ) -> Dict:
        """
        处理整个图片型 PDF
        
        Args:
            pdf_path: PDF 文件路径
            output_path: 输出文件路径（可选）
            
        Returns:
            Dict: 包含以下字段
                - success: 是否成功
                - content: 完整文字内容
                - pages: 每页文字列表
                - page_count: 总页数
                - error: 错误信息（如果有）
        """
        if not PYMUPDF_AVAILABLE:
            return {
                "success": False,
                "error": "PyMuPDF 未安装：pip install pymupdf",
            }
        
        try:
            # 打开 PDF
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            
            # 生成缓存键
            cache_key = self._generate_cache_key(pdf_path)
            cache_file = self.cache_dir / f"{cache_key}.json"
            
            # 尝试从缓存加载
            cached_result = self._load_from_cache(cache_file)
            if cached_result and len(cached_result.get('pages', [])) == page_count:
                print(f"✅ 从缓存加载 OCR 结果（{page_count}页）")
                doc.close()
                return {
                    "success": True,
                    "content": cached_result['content'],
                    "pages": cached_result['pages'],
                    "page_count": page_count,
                    "from_cache": True,
                }
            
            # 逐页处理
            pages_text = []
            for page_num in tqdm(range(page_count), desc="OCR 处理中"):
                # 检查缓存
                page_cache_key = f"{cache_key}_page_{page_num}"
                page_cache_file = self.cache_dir / f"{page_cache_key}.txt"
                
                if page_cache_file.exists():
                    # 从缓存加载
                    with open(page_cache_file, 'r', encoding='utf-8') as f:
                        page_text = f.read()
                else:
                    # 渲染页面为图片
                    page = doc[page_num]
                    zoom = self.dpi / 72.0
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat)
                    page_image = pix.tobytes("png")
                    
                    # OCR 识别
                    page_text = self.process_pdf_page(page_image)
                    
                    # 保存到缓存
                    with open(page_cache_file, 'w', encoding='utf-8') as f:
                        f.write(page_text)
                
                pages_text.append(page_text)
            
            doc.close()
            
            # 合并所有内容
            full_content = "\n\n".join(pages_text)
            
            # 后处理
            full_content = self.post_process_text(full_content)
            
            # 保存到缓存
            cache_data = {
                "content": full_content,
                "pages": pages_text,
                "page_count": page_count,
                "created_at": datetime.now().isoformat(),
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            # 写入输出文件（如果指定）
            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(full_content)
            
            return {
                "success": True,
                "content": full_content,
                "pages": pages_text,
                "page_count": page_count,
                "from_cache": False,
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"OCR 处理失败：{str(e)}",
            }

    def _generate_cache_key(self, pdf_path: str) -> str:
        """生成缓存键（基于文件路径和修改时间）"""
        import hashlib
        
        path = str(Path(pdf_path).resolve())
        mtime = os.path.getmtime(pdf_path)
        
        key_str = f"{path}_{mtime}"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]

    def _load_from_cache(self, cache_file: Path) -> Optional[Dict]:
        """从缓存文件加载"""
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def post_process_text(self, text: str) -> str:
        """
        OCR 后处理
        
        功能：
        - 修复常见 OCR 错误（数字与字母混淆等）
        - 合并跨页段落
        - 清理页眉页脚
        
        Args:
            text: OCR 识别的原始文本
            
        Returns:
            str: 处理后的文本
        """
        if not text:
            return ""
        
        # 1. 修复常见 OCR 错误
        ocr_fixes = {
            'rn': 'm',  # rn → m
            'vv': 'w',  # vv → w
            'cl': 'd',  # cl → d
            ' .': '.',  # 修复标点前空格
            ' ,': ',',
            ' ;': ';',
            ' :': ':',
            'O': '0',   # 字母 O → 数字 0（在数字上下文中）
            'l': '1',   # 字母 l → 数字 1（在数字上下文中）
            'I': '1',   # 字母 I → 数字 1（在数字上下文中）
        }
        
        for wrong, right in ocr_fixes.items():
            text = text.replace(wrong, right)
        
        # 2. 修复中文 OCR 常见错误
        chinese_fixes = {
            '己': '已',
            '已': '已',
            '戊': '戌',
            '茶': '茶',
            '冒': '冒',
        }
        
        for wrong, right in chinese_fixes.items():
            text = text.replace(wrong, right)
        
        # 3. 合并跨页段落
        # 检测段落断裂（行末没有标点，下一行以小写或中文开始）
        lines = text.split('\n')
        merged_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                merged_lines.append('')
                i += 1
                continue
            
            # 检查是否需要与下一行合并
            while i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                
                if not next_line:
                    break
                
                # 当前行末没有标点
                if not line[-1] in '。.！？!?；;：:，,\n':
                    # 下一行不是大写开头（英文）或是中文
                    if next_line[0].islower() or '\u4e00' <= next_line[0] <= '\u9fff':
                        line = line + ' ' + next_line
                        i += 1
                        continue
                
                break
            
            merged_lines.append(line)
            i += 1
        
        text = '\n'.join(merged_lines)
        
        # 4. 清理页眉页脚
        # 移除重复出现的短行（可能是页眉页脚）
        lines = text.split('\n')
        line_counts = {}
        
        for line in lines:
            if line.strip() and len(line.strip()) < 50:
                line_counts[line.strip()] = line_counts.get(line.strip(), 0) + 1
        
        # 找出重复超过 3 次的短行
        repeated_lines = {line for line, count in line_counts.items() if count > 3}
        
        # 移除这些行
        cleaned_lines = []
        for line in lines:
            if line.strip() not in repeated_lines:
                cleaned_lines.append(line)
        
        text = '\n'.join(cleaned_lines)
        
        # 5. 移除连续空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()

    def clear_cache(self):
        """清除 OCR 缓存"""
        import shutil
        
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ OCR 缓存已清除")
