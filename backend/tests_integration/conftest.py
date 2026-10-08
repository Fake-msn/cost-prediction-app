"""tests_integration 使用真实 DuckDB 引擎（非 mock）。

backend/tests/conftest.py 会把 duckdb/sklearn/xgboost 等替换为 MagicMock。
若两个目录在同一进程被收集，本目录将拿到 mock 而非真实引擎。这里在收集前
清除这些 mock 模块，确保 import 到真实库。

CI 中 backend/tests 与 backend/tests_integration 以独立进程分别运行，
本文件仅作双保险。
"""
import sys

_MOCK_ROOTS = {"duckdb", "sklearn", "xgboost", "pytesseract", "agentscope"}

for _name in list(sys.modules):
    if _name.split(".")[0] in _MOCK_ROOTS and type(sys.modules[_name]).__name__ == "MagicMock":
        del sys.modules[_name]
