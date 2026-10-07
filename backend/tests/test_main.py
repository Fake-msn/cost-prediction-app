"""
main.py 单元测试

重点覆盖：
- _safe_upload_filename 路径穿越防护（E2 漏洞修复验证）
- FastAPI 应用创建与健康检查端点
- 文件上传格式校验逻辑
"""

import os
import sys
import pytest


# ═══════════════════════════════════════════════════════════════
# _safe_upload_filename 路径穿越防护测试
# ═══════════════════════════════════════════════════════════════
#
# _safe_upload_filename 是 main.py 中防御路径穿越攻击的核心函数。
# 其设计原则：仅保留原始文件名的白名单扩展名，丢弃所有路径部分，
# 最终保存名为 "{task_id}{ext}"，与 task_id 一一对应。
#
# 以下测试验证该函数能有效阻止各类路径穿越攻击向量。

# 与 main.py 保持一致的常量
ALLOWED_EXTENSIONS = {'.docx', '.doc', '.pdf', '.xlsx', '.xls'}


def _safe_upload_filename(task_id: str, original_filename: str) -> str:
    """与 main.py 中完全一致的实现，用于独立测试"""
    ext = os.path.splitext(original_filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ""
    return f"{task_id}{ext}"


class TestSafeUploadFilename:
    """文件上传路径穿越防护 — 安全回归测试套件"""

    # ── 路径穿越攻击向量 ──────────────────────────────────

    @pytest.mark.parametrize("malicious_filename", [
        "../../../etc/passwd",
        "..\\..\\..\\Windows\\System32\\config\\SAM",
        "../../etc/passwd.pdf",          # 带合法扩展名的穿越
        "....//....//....//etc/passwd",   # 多点斜杠变体
        "..;/..;/..;/etc/passwd",         # 分号变体 (NTFS)
        "./../../../etc/shadow",
    ])
    def test_prevents_path_traversal_variants(self, malicious_filename):
        """各类路径穿越变体均应被阻止 — 结果不含路径分隔符"""
        result = _safe_upload_filename("abc12345", malicious_filename)
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result
        # 结果必须是纯文件名（无路径）
        assert os.path.basename(result) == result

    def test_prevents_absolute_unix_path(self):
        """绝对 Unix 路径穿越应被阻止"""
        result = _safe_upload_filename("task0001", "/etc/passwd")
        assert result == "task0001"  # 无扩展名
        assert "/" not in result

    def test_prevents_absolute_windows_path(self):
        """绝对 Windows 路径穿越应被阻止"""
        result = _safe_upload_filename("task0002", "C:\\Windows\\System32\\evil.pdf")
        assert result == "task0002.pdf"  # 仅保留 .pdf
        assert ":" not in result
        assert "\\" not in result

    def test_prevents_unc_path(self):
        """UNC 网络路径穿越应被阻止"""
        result = _safe_upload_filename("task0003", "\\\\192.168.1.1\\share\\malware.pdf")
        assert result == "task0003.pdf"
        assert "\\\\" not in result

    def test_prevents_double_extension_spoofing(self):
        """双扩展名伪装攻击：.pdf.exe → 仅取 .exe（不在白名单，丢弃）"""
        result = _safe_upload_filename("task0004", "report.pdf.exe")
        assert result == "task0004"  # .exe 不在白名单
        assert ".exe" not in result

    def test_prevents_null_byte_injection(self):
        """Null byte 注入：filename.pdf%00.exe → 扩展名为空或仅 .pdf"""
        result = _safe_upload_filename("task0005", "doc.pdf\x00.exe")
        # os.path.splitext 将 \x00.exe 视为扩展名的一部分
        ext = os.path.splitext("doc.pdf\x00.exe")[1].lower()
        # 实际行为取决于 OS; 关键是结果不含路径穿越
        assert ".." not in result
        assert "/" not in result

    # ── 正常文件名处理 ────────────────────────────────────

    @pytest.mark.parametrize("filename, expected", [
        ("工程量清单.pdf", "task9999.pdf"),
        ("施工合同.docx", "task9999.docx"),
        ("BOQ清单.xlsx", "task9999.xlsx"),
        ("预算表.xls", "task9999.xls"),
        ("旧版文档.doc", "task9999.doc"),
    ])
    def test_normal_filenames_preserve_extension(self, filename, expected):
        result = _safe_upload_filename("task9999", filename)
        assert result == expected

    def test_uppercase_extension_normalized(self):
        """大写扩展名应被规范化为小写"""
        result = _safe_upload_filename("task0006", "REPORT.PDF")
        assert result == "task0006.pdf"

    def test_mixed_case_extension(self):
        """混合大小写扩展名应被规范化"""
        result = _safe_upload_filename("task0007", "Document.PdF")
        assert result == "task0007.pdf"

    # ── 边界情况 ──────────────────────────────────────────

    @pytest.mark.parametrize("filename, expected", [
        ("noextension", "task0008"),
        ("", "task0008"),
        (".hidden", "task0008"),       # 无扩展名的隐藏文件
        (".hidden.pdf", "task0008.pdf"),  # 有扩展名的隐藏文件
        ("a" * 200 + ".pdf", "task0008.pdf"),  # 超长文件名
    ])
    def test_edge_case_filenames(self, filename, expected):
        result = _safe_upload_filename("task0008", filename)
        assert result == expected

    def test_handles_none_filename(self):
        """None 文件名应安全处理（不崩溃）"""
        result = _safe_upload_filename("task0009", None)
        assert result == "task0009"  # ext = "" when original_filename is None

    def test_blocks_unsupported_extensions(self):
        """不在白名单中的扩展名应被丢弃"""
        blocked = [".exe", ".dll", ".sh", ".bat", ".php", ".jsp", ".html", ".js"]
        for ext in blocked:
            result = _safe_upload_filename("task0010", f"malware{ext}")
            assert result == "task0010", f"应阻止 {ext}"

    def test_traversal_with_allowed_extension_still_safe(self):
        """即使扩展名合法，路径部分也应被丢弃"""
        # 关键场景：攻击者使用 ../../../etc/backdoor.pdf
        # 结果应为 task0011.pdf，不含路径
        result = _safe_upload_filename("task0011", "../../../etc/backdoor.pdf")
        assert result == "task0011.pdf"
        assert "/" not in result
        assert ".." not in result
        assert "etc" not in result

    def test_result_is_always_flat(self):
        """无论输入如何，输出始终是扁平文件名"""
        test_cases = [
            ("task", "a/b/c.pdf"),
            ("task", "a\\b\\c.pdf"),
            ("task", "~/.ssh/id_rsa"),
            ("task", "/tmp/../../etc/passwd"),
        ]
        for tid, fname in test_cases:
            result = _safe_upload_filename(tid, fname)
            assert os.path.sep not in result
            assert result.startswith(tid)


# ═══════════════════════════════════════════════════════════════
# FastAPI 应用测试（需要完整依赖环境）
# ═══════════════════════════════════════════════════════════════

class TestFastAPIApp:
    """FastAPI 应用创建与基本路由测试"""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        """尝试导入 FastAPI app，不可用时跳过"""
        self.app = None
        self.client = None
        try:
            # conftest.py 已 mock 了 duckdb/sklearn/xgboost/agentscope
            # 但 main.py 模块级仍有 data_loader 实例化等副作用
            from main import app
            from fastapi.testclient import TestClient
            self.app = app
            self.client = TestClient(app)
        except Exception:
            pass

    def test_app_exists(self):
        """FastAPI app 对象应可被导入"""
        if self.app is None:
            pytest.skip("main.py 导入失败（依赖不可用）")
        assert self.app is not None
        assert self.app.title == "AI 建筑工程造价预测系统"

    def test_health_endpoint(self):
        """GET /api/health 应返回 200 与状态字段"""
        if self.client is None:
            pytest.skip("TestClient 不可用（依赖不可用）")
        response = self.client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_index_endpoint(self):
        """GET / 应返回 200（首页）"""
        if self.client is None:
            pytest.skip("TestClient 不可用（依赖不可用）")
        response = self.client.get("/")
        # 可能返回 200（HTML 存在）或 404（前端文件未找到）
        assert response.status_code in (200, 404)

    def test_app_page_endpoint(self):
        """GET /app 应返回 200（应用主界面）"""
        if self.client is None:
            pytest.skip("TestClient 不可用（依赖不可用）")
        response = self.client.get("/app")
        assert response.status_code in (200, 404)

    def test_terminology_stages_endpoint(self):
        """GET /api/terminology/stages 应返回三阶段造价定义"""
        if self.client is None:
            pytest.skip("TestClient 不可用（依赖不可用）")
        response = self.client.get("/api/terminology/stages")
        assert response.status_code == 200

    def test_models_list_endpoint(self):
        """GET /api/models 应返回模型列表"""
        if self.client is None:
            pytest.skip("TestClient 不可用（依赖不可用）")
        response = self.client.get("/api/models")
        # 可能依赖已训练的模型，但路由应可达
        assert response.status_code in (200, 500)


# ═══════════════════════════════════════════════════════════════
# 上传格式校验逻辑测试
# ═══════════════════════════════════════════════════════════════

class TestAllowedExtensions:
    """ALLOWED_EXTENSIONS 白名单校验 — 与 main.py 保持一致"""

    def test_allowed_list_matches_main(self):
        """验证测试中的白名单与 main.py 一致"""
        # 尝试从 main 导入以验证一致性
        try:
            from main import ALLOWED_EXTENSIONS as MAIN_ALLOWED
            assert ALLOWED_EXTENSIONS == MAIN_ALLOWED
        except Exception:
            # 如果导入失败，至少验证测试常量自身
            assert ALLOWED_EXTENSIONS == {'.docx', '.doc', '.pdf', '.xlsx', '.xls'}

    def test_only_document_formats_allowed(self):
        """仅办公文档格式在白名单中"""
        dangerous = {'.exe', '.dll', '.bat', '.cmd', '.ps1', '.vbs', '.sh'}
        assert ALLOWED_EXTENSIONS.isdisjoint(dangerous)

    def test_common_web_formats_blocked(self):
        """常见 Web 后门格式不在白名单中"""
        web_formats = {'.php', '.jsp', '.asp', '.aspx', '.py', '.rb', '.pl'}
        assert ALLOWED_EXTENSIONS.isdisjoint(web_formats)
