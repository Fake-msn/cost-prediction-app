"""excel_reader 单元测试（backend/tests：duckdb 被 conftest 全局 mock）。

重点验证「优雅回退」契约：当 excel 扩展不可用（此处 duckdb 为 MagicMock，
read_xlsx().df() 返回 MagicMock 而非 DataFrame）时，read_table 必须回退到
pd.read_excel(openpyxl) 并返回真实、正确的 DataFrame；export 亦回退 pandas 落地文件。
真实引擎下的快路径在 backend/tests_integration/test_excel_reader_real.py 覆盖。
"""
import os
import sys

import pandas as pd
import pytest
from openpyxl import Workbook

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import excel_reader  # noqa: E402
from excel_reader import (  # noqa: E402
    ExcelReaderUnavailable,
    export_dataframe_to_xlsx,
    read_table,
    read_xlsx_to_dataframe,
)

HEADERS = ["项目名称", "建筑类型", "总建筑面积", "单方造价"]


@pytest.fixture()
def sample_xlsx(tmp_path):
    path = tmp_path / "sample.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    ws.append(["A项目", "住宅", 12000.0, 4500.0])
    ws.append(["B项目", "办公", 8000.0, 6200.0])
    wb.save(str(path))
    return str(path)


def test_read_xlsx_fast_path_guarded_when_duckdb_mocked(sample_xlsx):
    """mock 的 duckdb 返回 MagicMock（非 DataFrame）→ 快路径判定为不可用并抛错。"""
    with pytest.raises(ExcelReaderUnavailable):
        read_xlsx_to_dataframe(sample_xlsx, "sample.xlsx")


def test_read_table_bytes_falls_back_to_pandas(sample_xlsx):
    """bytes 输入 + .xlsx：快路径不可用时回退 pandas，返回正确 DataFrame。"""
    with open(sample_xlsx, "rb") as f:
        content = f.read()
    df = read_table(content, "sample.xlsx")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == HEADERS
    assert len(df) == 2
    assert df.iloc[0]["项目名称"] == "A项目"
    assert float(df.iloc[1]["单方造价"]) == 6200.0


def test_read_table_path_input(sample_xlsx):
    """路径输入同样回退 pandas 并正确读取。"""
    df = read_table(sample_xlsx, "sample.xlsx")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2


def test_read_table_xls_routes_to_pandas(sample_xlsx):
    """.xls 不走 excel 扩展（不支持），直接回退 pandas。

    这里用 .xlsx 内容配 .xls 文件名，只为验证「不尝试快路径」的路由分支；
    pandas 以 openpyxl 引擎读取该文件仍可成功（文件真实为 xlsx 容器）。
    """
    df = read_table(sample_xlsx, "legacy.xls")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2


def test_export_dataframe_to_xlsx_writes_real_file(tmp_path):
    """mock duckdb 下 COPY 为 no-op（文件不存在）→ 必须回退 pandas 真正写出文件。"""
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    dest = tmp_path / "out.xlsx"
    out = export_dataframe_to_xlsx(df, str(dest))
    assert os.path.exists(out)
    back = pd.read_excel(out, engine="openpyxl")
    assert len(back) == 2
    assert list(back.columns) == ["a", "b"]


def test_module_exposes_has_duckdb_flag():
    """HAS_DUCKDB 标志存在（mock 下 import 成功即为 True）。"""
    assert hasattr(excel_reader, "HAS_DUCKDB")
