"""
pytest 共享配置与 fixtures

本文件在测试收集阶段自动加载，提供：
- sys.path 注入，确保 backend/ 下模块可被直接导入
- 全局 mock，阻断对 DuckDB / sklearn / xgboost / agentscope 的意外加载
"""

import sys
import os
from unittest.mock import MagicMock

# ── 将 backend/ 目录加入 sys.path ──────────────────────────
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ── 全局 mock：阻断重型第三方库的副作用导入 ────────────────
# 以下模块在 backend/main.py 模块级代码中会被 import，
# 测试中无需真实功能，mock 即可避免连接 DB / 加载模型 / 网络请求。
_MOCK_MODULES = [
    "duckdb",
    "xgboost",
    "sklearn",
    "sklearn.ensemble",
    "sklearn.svm",
    "sklearn.linear_model",
    "sklearn.preprocessing",
    "sklearn.model_selection",
    "sklearn.metrics",
    "agentscope",
    "pytesseract",
]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
