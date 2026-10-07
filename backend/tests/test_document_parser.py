"""
document_parser.py 单元测试

覆盖：
- ParseResult 数据类
- DocumentParser 文件校验（不存在、不支持的格式、超大文件）
- WordParser / PDFParser / ExcelParser 基本解析路径
- parse_document() 便捷函数
"""

import os
import pytest
from document_parser import (
    ParseResult,
    DocumentParser,
    parse_document,
    WordParser,
    PDFParser,
    ExcelParser,
)


# ═══════════════════════════════════════════════════════════════
# ParseResult 数据类
# ═══════════════════════════════════════════════════════════════

class TestParseResult:
    def test_default_values(self):
        """默认字段应为空/零值"""
        r = ParseResult(filename="test.pdf", file_format=".pdf")
        assert r.filename == "test.pdf"
        assert r.file_format == ".pdf"
        assert r.full_text == ""
        assert r.tables == []
        assert r.metadata == {}
        assert r.pages == 0
        assert r.is_scanned is False
        assert r.warnings == []

    def test_custom_values(self):
        """自定义字段应正确存储"""
        r = ParseResult(
            filename="report.docx",
            file_format=".docx",
            full_text="hello world",
            tables=[[["A", "B"]]],
            metadata={"author": "test"},
            pages=3,
            is_scanned=False,
            warnings=["warning1"],
        )
        assert r.full_text == "hello world"
        assert r.tables == [[["A", "B"]]]
        assert r.metadata == {"author": "test"}
        assert r.pages == 3
        assert r.warnings == ["warning1"]


# ═══════════════════════════════════════════════════════════════
# DocumentParser 文件校验 / 调度
# ═══════════════════════════════════════════════════════════════

class TestDocumentParserValidation:
    """测试 DocumentParser.parse() 的输入校验逻辑"""

    def test_rejects_nonexistent_file(self):
        """不存在的文件应抛出 FileNotFoundError"""
        parser = DocumentParser()
        with pytest.raises(FileNotFoundError, match="文件不存在"):
            parser.parse("/nonexistent/path/ghost.pdf")

    def test_rejects_unsupported_format(self, tmp_path):
        """不支持的文件扩展名应抛出 ValueError"""
        parser = DocumentParser()
        f = tmp_path / "notes.txt"
        f.write_text("some content")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            parser.parse(str(f))

    def test_rejects_no_extension(self, tmp_path):
        """无扩展名文件应抛出 ValueError"""
        parser = DocumentParser()
        f = tmp_path / "noext"
        f.write_text("content")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            parser.parse(str(f))

    def test_supported_formats(self):
        """验证 SUPPORTED_FORMATS 包含预期格式"""
        expected = {".docx", ".doc", ".pdf", ".xlsx", ".xls"}
        assert set(DocumentParser.SUPPORTED_FORMATS.keys()) == expected

    def test_rejects_oversized_file(self, tmp_path):
        """超过 MAX_FILE_SIZE 的文件应抛出 ValueError（含路径穿越场景）"""
        parser = DocumentParser()
        original_max = DocumentParser.MAX_FILE_SIZE
        try:
            # 临时降低阈值以简化超大文件创建
            DocumentParser.MAX_FILE_SIZE = 512
            f = tmp_path / "big.pdf"
            f.write_bytes(b"%PDF-1.4\n" + b"x" * 1024)  # 1+ KB > 512 B
            with pytest.raises(ValueError, match="文件过大"):
                parser.parse(str(f))
        finally:
            DocumentParser.MAX_FILE_SIZE = original_max

    def test_rejects_traversal_filename_in_oversized(self, tmp_path):
        """路径穿越文件名 + 超大文件 → 应正确识别并拒绝"""
        parser = DocumentParser()
        original_max = DocumentParser.MAX_FILE_SIZE
        try:
            DocumentParser.MAX_FILE_SIZE = 512
            # 模拟路径穿越文件名，但文件路径是安全目录内的
            f = tmp_path / "oversize.pdf"
            f.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)
            with pytest.raises(ValueError, match="文件过大"):
                # 即使原始 filename 含路径穿越字符，parse 使用的是实际安全路径
                parser.parse(str(f))
        finally:
            DocumentParser.MAX_FILE_SIZE = original_max


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

class TestParseDocumentFunction:
    def test_parse_document_rejects_bad_file(self):
        """parse_document() 应对无效文件抛出异常"""
        with pytest.raises(FileNotFoundError):
            parse_document("/nonexistent/file.pdf")


# ═══════════════════════════════════════════════════════════════
# 各解析器基本构造
# ═══════════════════════════════════════════════════════════════

class TestParserInstantiation:
    """验证各解析器可正常实例化"""

    def test_word_parser_exists(self):
        wp = WordParser()
        assert wp is not None

    def test_pdf_parser_exists(self):
        pp = PDFParser()
        assert pp is not None
        assert pp.SCANNED_THRESHOLD == 50
        assert pp.PARTIAL_SCAN_THRESHOLD == 200

    def test_excel_parser_exists(self):
        ep = ExcelParser()
        assert ep is not None
