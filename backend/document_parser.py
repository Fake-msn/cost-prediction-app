"""
document_parser.py - 多格式文档解析器
支持 .docx, .pdf, .xlsx, .xls 等工程造价相关文档格式
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# Set Tesseract path
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    pytesseract = None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """文档解析结果"""
    filename: str
    file_format: str
    full_text: str = ""
    tables: List[List[List[str]]] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    pages: int = 0
    is_scanned: bool = False
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

class WordParser:
    """解析 Word 文档 (.docx)"""

    def parse(self, file_path: str) -> ParseResult:
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        result = ParseResult(filename=filename, file_format=ext)

        if ext == '.doc':
            result.warnings.append(
                ".doc 格式（旧版 Word）暂不支持直接解析，"
                "请先使用 Microsoft Word 将文件转换为 .docx 格式后重试。"
            )
            return result

        # ext == '.docx'
        try:
            from docx import Document
        except ImportError:
            result.warnings.append("缺少 python-docx 库，无法解析 .docx 文件。请运行: pip install python-docx")
            return result

        try:
            doc = Document(file_path)

            # 提取段落文本
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    paragraphs.append(text)
            result.full_text = "\n".join(paragraphs)

            # 提取表格
            for table in doc.tables:
                table_data: List[List[str]] = []
                for row in table.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    table_data.append(row_data)
                if table_data:
                    result.tables.append(table_data)

            # 元数据
            core = doc.core_properties
            result.metadata = {
                "author": core.author or "",
                "title": core.title or "",
                "subject": core.subject or "",
                "created": str(core.created) if core.created else "",
                "modified": str(core.modified) if core.modified else "",
            }
            result.pages = 1  # docx 无法准确获取页数

        except Exception as exc:
            result.warnings.append(f"解析 .docx 文件时出错: {exc}")

        return result


class PDFParser:
    """解析 PDF 文档（支持扫描件 OCR）"""

    SCANNED_THRESHOLD = 50  # 每页文本字符数低于此值视为扫描件
    PARTIAL_SCAN_THRESHOLD = 200  # 低于此值视为半扫描页（文本稀疏）

    def parse(self, file_path: str) -> ParseResult:
        filename = os.path.basename(file_path)
        result = ParseResult(filename=filename, file_format='.pdf')

        # ---- 使用 pymupdf (fitz) 提取文本 ----
        try:
            import fitz  # pymupdf
        except ImportError:
            result.warnings.append("缺少 pymupdf 库，无法解析 PDF。请运行: pip install pymupdf")
            return result

        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            result.warnings.append(f"无法打开 PDF 文件: {exc}")
            return result

        result.pages = len(doc)
        result.metadata = dict(doc.metadata) if doc.metadata else {}

        text_pages: List[str] = []
        scanned_page_count = 0
        ocr_confidences: List[float] = []

        for page_idx, page in enumerate(doc):
            page_text = page.get_text().strip()

            # 智能检测：文本极少 → 扫描页；文本稀疏 → 半扫描页
            if len(page_text) < self.SCANNED_THRESHOLD:
                scanned_page_count += 1
                ocr_text, confidence = self._ocr_page_with_confidence(page)
                text_pages.append(ocr_text)
                if confidence > 0:
                    ocr_confidences.append(confidence)
            elif len(page_text) < self.PARTIAL_SCAN_THRESHOLD:
                # 半扫描页：尝试 OCR 补充，但优先用已有文本
                ocr_text, confidence = self._ocr_page_with_confidence(page)
                if len(ocr_text) > len(page_text) * 1.5:
                    text_pages.append(ocr_text)
                    if confidence > 0:
                        ocr_confidences.append(confidence)
                else:
                    text_pages.append(page_text)
            else:
                text_pages.append(page_text)

        doc.close()

        result.full_text = "\n".join(text_pages)
        if result.pages > 0 and scanned_page_count / result.pages > 0.5:
            result.is_scanned = True

        # OCR 质量报告
        if ocr_confidences:
            avg_conf = sum(ocr_confidences) / len(ocr_confidences)
            result.metadata['ocr_avg_confidence'] = round(avg_conf, 2)
            result.metadata['ocr_pages'] = len(ocr_confidences)
            if avg_conf < 60:
                result.warnings.append(
                    f"OCR 识别置信度偏低 ({avg_conf:.0f}%)，"
                    f"建议检查扫描件质量或手动核对关键字段。"
                )

        # ---- 使用 pdfplumber 提取表格 ----
        try:
            import pdfplumber
        except ImportError:
            result.warnings.append("缺少 pdfplumber 库，无法提取表格。请运行: pip install pdfplumber")
            return result

        try:
            with pdfplumber.open(file_path) as pdf:
                for pdf_page in pdf.pages:
                    extracted_tables = pdf_page.extract_tables()
                    if extracted_tables:
                        for tbl in extracted_tables:
                            # 将 None 替换为空字符串
                            cleaned = [
                                [str(cell).strip() if cell is not None else "" for cell in row]
                                for row in tbl
                            ]
                            if cleaned:
                                result.tables.append(cleaned)
        except Exception as exc:
            result.warnings.append(f"pdfplumber 提取表格时出错: {exc}")

        return result

    def _ocr_page(self, page) -> str:
        """对单页进行 OCR 识别（增强版：预处理 + 后处理）"""
        if pytesseract is None:
            return "[OCR 不可用：缺少 pytesseract]"
        try:
            import fitz as _fitz
            from PIL import Image, ImageFilter, ImageOps
            import io

            # 以 300 DPI 渲染页面为图像
            mat = _fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            # ── 图像预处理 ──
            img = self._preprocess_image(img)

            # ── OCR 识别（优化参数）──
            # --psm 6: 假设为统一文本块，适合整页文档
            # --oem 1: LSTM 引擎，对中文识别率最高
            config = '--psm 6 --oem 1 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz，。：；！？、（）《》""''—·㎡m³/kg个套台组只系统樘层'
            text = pytesseract.image_to_string(img, lang='chi_sim+eng', config=config)

            # ── 后处理：修复 OCR 常见问题 ──
            text = self._postprocess_ocr_text(text)
            return text.strip()
        except Exception as exc:
            return f"[OCR 失败: {exc}]"

    def _preprocess_image(self, img):
        """图像预处理：灰度 → 降噪 → 自适应阈值 → 倾斜矫正"""
        from PIL import Image, ImageFilter, ImageOps
        import io

        # 1. 转灰度
        if img.mode != 'L':
            img = img.convert('L')

        # 2. 中值滤波降噪（保留边缘）
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # 3. 自动对比度增强
        img = ImageOps.autocontrast(img, cutoff=2)

        # 4. 二值化（自适应阈值，使用 Otsu 近似）
        # PIL 没有自适应阈值，用 point 操作做简单二值化
        threshold = 140
        img = img.point(lambda x: 255 if x > threshold else 0, '1')

        # 5. 轻微锐化
        img = img.convert('L').filter(ImageFilter.SHARPEN)

        return img

    def _postprocess_ocr_text(self, text: str) -> str:
        """OCR 文本后处理：修复断行、碎片合并、常见误识"""
        if not text:
            return text

        import re

        # 1. 修复断行：行尾非标点且下一行非空 → 合并
        lines = text.split('\n')
        merged = []
        for i, line in enumerate(lines):
            line = line.rstrip()
            if not line:
                if merged and merged[-1]:
                    merged.append('')  # 保留空行作为段落分隔
                continue
            # 如果上一行末尾不是标点/符号，且当前行不是新段落开头（不以数字/项目编号开头）
            if merged and merged[-1] and merged[-1][-1] not in '。；：！？、）》」』,;:!?)>..．':
                if not re.match(r'^[\d一二三四五六七八九十]+[、.．]', line) and not line.startswith('【'):
                    merged[-1] += line
                    continue
            merged.append(line)

        text = '\n'.join(merged)

        # 2. 修复常见 OCR 误识
        fixes = {
            'l': '1',  # 小写L → 1 (在数字上下文中)
            'O': '0',  # 大写O → 0
            '。.': '。',  # 重复标点
            '，，': '，',
            '  ': ' ',   # 双空格
        }
        # 仅在数字上下文中替换 l→1, O→0
        text = re.sub(r'(?<=\d)l(?=\d)', '1', text)
        text = re.sub(r'(?<=\d)O(?=\d)', '0', text)
        text = re.sub(r'。。+', '。', text)
        text = re.sub(r'，，+', '，', text)
        text = re.sub(r'  +', ' ', text)

        # 3. 合并跨行数字（如 "69,474" 被拆成 "69,\n474"）
        text = re.sub(r',\n(\d)', r',\1', text)

        # 4. 修复"㎡"被 OCR 拆成"m2"或"rn2"的情况
        text = re.sub(r'[rn]2', '㎡', text)
        text = re.sub(r'm2(?![0-9])', '㎡', text)

        return text

    def _ocr_page_with_confidence(self, page) -> tuple:
        """OCR 识别并返回 (text, avg_confidence)"""
        if pytesseract is None:
            return ("[OCR 不可用]", 0.0)
        try:
            import fitz as _fitz
            from PIL import Image
            import io

            mat = _fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img = self._preprocess_image(img)

            config = '--psm 6 --oem 1'
            text = pytesseract.image_to_string(img, lang='chi_sim+eng', config=config)
            text = self._postprocess_ocr_text(text)

            # 获取置信度
            import pytesseract as _pt
            data = _pt.image_to_data(img, lang='chi_sim+eng', config=config,
                                     output_type=_pt.Output.DICT)
            confidences = [int(c) for c in data['conf'] if int(c) > 0]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

            return (text, avg_conf)
        except Exception as exc:
            return (f"[OCR 失败: {exc}]", 0.0)


class ExcelParser:
    """解析 Excel 文档 (.xlsx / .xls)"""

    def parse(self, file_path: str) -> ParseResult:
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        result = ParseResult(filename=filename, file_format=ext)

        if ext == '.xlsx':
            self._parse_xlsx(file_path, result)
        elif ext == '.xls':
            self._parse_xls(file_path, result)

        return result

    def _parse_xlsx(self, file_path: str, result: ParseResult) -> None:
        try:
            from openpyxl import load_workbook
        except ImportError:
            result.warnings.append("缺少 openpyxl 库，无法解析 .xlsx。请运行: pip install openpyxl")
            return

        try:
            wb = load_workbook(file_path, read_only=True, data_only=True)
            all_text_parts: List[str] = []

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                sheet_rows: List[List[str]] = []
                for row in ws.iter_rows(values_only=True):
                    row_data = [str(cell).strip() if cell is not None else "" for cell in row]
                    # 跳过全空行
                    if any(row_data):
                        sheet_rows.append(row_data)
                        all_text_parts.append("\t".join(row_data))
                if sheet_rows:
                    result.tables.append(sheet_rows)

            wb.close()
            result.full_text = "\n".join(all_text_parts)
            result.pages = len(wb.sheetnames) if hasattr(wb, 'sheetnames') else 1

        except Exception as exc:
            result.warnings.append(f"解析 .xlsx 文件时出错: {exc}")

    def _parse_xls(self, file_path: str, result: ParseResult) -> None:
        try:
            import xlrd
        except ImportError:
            result.warnings.append("缺少 xlrd 库，无法解析 .xls。请运行: pip install xlrd")
            return

        try:
            wb = xlrd.open_workbook(file_path)
            all_text_parts: List[str] = []

            for sheet in wb.sheets():
                sheet_rows: List[List[str]] = []
                for row_idx in range(sheet.nrows):
                    row_data = [str(sheet.cell_value(row_idx, col_idx)).strip()
                                for col_idx in range(sheet.ncols)]
                    if any(row_data):
                        sheet_rows.append(row_data)
                        all_text_parts.append("\t".join(row_data))
                if sheet_rows:
                    result.tables.append(sheet_rows)

            result.full_text = "\n".join(all_text_parts)
            result.pages = wb.nsheets

        except Exception as exc:
            result.warnings.append(f"解析 .xls 文件时出错: {exc}")


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

class DocumentParser:
    """多格式文档解析调度器"""

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

    SUPPORTED_FORMATS: Dict[str, str] = {
        '.docx': 'word',
        '.doc':  'word',
        '.pdf':  'pdf',
        '.xlsx': 'excel',
        '.xls':  'excel',
    }

    def __init__(self):
        self._parsers = {
            'word':  WordParser(),
            'pdf':   PDFParser(),
            'excel': ExcelParser(),
        }

    def parse(self, file_path: str) -> ParseResult:
        """解析指定路径的文档，返回 ParseResult"""

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        if ext not in self.SUPPORTED_FORMATS:
            supported = ", ".join(sorted(self.SUPPORTED_FORMATS.keys()))
            raise ValueError(
                f"不支持的文件格式: '{ext}'。支持的格式: {supported}"
            )

        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > self.MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            raise ValueError(
                f"文件过大 ({size_mb:.1f} MB)，超过限制 ({self.MAX_FILE_SIZE // (1024*1024)} MB): {filename}"
            )

        fmt = self.SUPPORTED_FORMATS[ext]
        parser = self._parsers[fmt]
        return parser.parse(file_path)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def parse_document(file_path: str) -> ParseResult:
    """便捷函数：解析文档并返回 ParseResult"""
    parser = DocumentParser()
    return parser.parse(file_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python document_parser.py <file_path>")
        sys.exit(1)

    result = parse_document(sys.argv[1])
    print(f"File: {result.filename}")
    print(f"Format: {result.file_format}")
    print(f"Pages: {result.pages}")
    print(f"Scanned: {result.is_scanned}")
    print(f"Text length: {len(result.full_text)}")
    print(f"Tables: {len(result.tables)}")
    print(f"Warnings: {result.warnings}")
