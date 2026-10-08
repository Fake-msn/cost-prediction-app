"""DuckDB excel-extension spreadsheet reader/exporter with graceful pandas fallback.

Why this exists
---------------
``pd.read_excel(engine="openpyxl")`` (the previous import path in ``data_loader``) loads an
entire workbook into memory at once and OOMs / silently truncates on large BOQ & history
files, especially under the 2 GB container limit. DuckDB's official ``excel`` extension
(``read_xlsx``) reads ``.xlsx`` with far lower memory and is ~10x faster, and it is already
covered by the existing ``duckdb`` dependency (no new runtime, no Node).

Design constraints
------------------
* Always returns a real ``pandas.DataFrame``. Whenever the extension cannot be used the
  helpers fall back to ``pd.read_excel(engine="openpyxl")`` so behaviour is unchanged for:
  - mocked ``duckdb`` in ``backend/tests`` (a MagicMock ``.df()`` is not a DataFrame),
  - environments without network to ``INSTALL excel``,
  - ``.xls`` (Excel 97-2003), which the excel extension does not support.
* ``stop_at_empty=false`` is mandatory: the default stops at the first blank row and would
  truncate sheets that contain empty separator rows.
* Merged cells: ``read_xlsx`` keeps only the top-left value and exposes no merge ranges, so
  merge-heavy BOQ sheets must still be parsed with openpyxl (see ``scripts/extract_boq.py``).
  This reader targets flat tabular imports (e.g. ``project_meta`` history).
"""
from __future__ import annotations

import io
import os
import tempfile
from typing import Union

import pandas as pd

try:  # DuckDB is an optional-but-expected dependency
    import duckdb
    HAS_DUCKDB = True
except ImportError:  # pragma: no cover - duckdb is in requirements.txt
    duckdb = None
    HAS_DUCKDB = False

PathLike = Union[str, "os.PathLike[str]"]
Source = Union[bytes, bytearray, PathLike]


class ExcelReaderUnavailable(RuntimeError):
    """The DuckDB excel extension could not be used; callers should fall back to pandas."""


def _ensure_excel_extension(con) -> None:
    """``LOAD excel`` (installing on demand). Raises :class:`ExcelReaderUnavailable` if impossible."""
    try:
        con.execute("LOAD excel;")
        return
    except Exception:
        pass
    try:
        con.execute("INSTALL excel;")
        con.execute("LOAD excel;")
        return
    except Exception as exc:  # no network / unsupported platform
        raise ExcelReaderUnavailable(f"excel extension unavailable: {exc}") from exc


def _read_xlsx_df(path: str) -> pd.DataFrame:
    if not HAS_DUCKDB:
        raise ExcelReaderUnavailable("duckdb is not installed")
    con = duckdb.connect()
    try:
        _ensure_excel_extension(con)
        rel = con.execute(
            "SELECT * FROM read_xlsx(?, header=true, stop_at_empty=false, ignore_errors=true)",
            [path],
        )
        df = rel.df()
    finally:
        try:
            con.close()
        except Exception:
            pass
    if not isinstance(df, pd.DataFrame):
        # Mocked duckdb (unit tests) returns a MagicMock rather than a real frame.
        raise ExcelReaderUnavailable("read_xlsx did not return a DataFrame")
    return df


def read_xlsx_to_dataframe(source: Source, filename: str = "upload.xlsx") -> pd.DataFrame:
    """Read an ``.xlsx`` via the DuckDB excel extension.

    Raises :class:`ExcelReaderUnavailable` (or another exception) if the fast path cannot be
    used; prefer :func:`read_table` which adds the pandas fallback.
    """
    if isinstance(source, (bytes, bytearray)):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        try:
            tmp.write(bytes(source))
            tmp.close()
            return _read_xlsx_df(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    return _read_xlsx_df(os.fspath(source))


def _pandas_read_excel(source: Source) -> pd.DataFrame:
    if isinstance(source, (bytes, bytearray)):
        return pd.read_excel(io.BytesIO(bytes(source)), engine="openpyxl")
    return pd.read_excel(os.fspath(source), engine="openpyxl")


def read_table(source: Source, filename: str = "upload.xlsx") -> pd.DataFrame:
    """Read a spreadsheet into a DataFrame: DuckDB excel fast path + pandas/openpyxl fallback.

    Guaranteed to return a real ``pandas.DataFrame`` (or raise the same error pandas would).
    Only ``.xlsx`` attempts the fast path; ``.xls`` and any extension failure fall back.
    """
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        try:
            return read_xlsx_to_dataframe(source, filename)
        except Exception:
            # Unavailable extension, mocked duckdb, or a parse issue -> fall back to pandas.
            pass
    return _pandas_read_excel(source)


def export_dataframe_to_xlsx(df: pd.DataFrame, dest: PathLike) -> str:
    """Export a DataFrame to ``.xlsx`` via ``COPY ... TO`` (excel extension), pandas fallback.

    Produces a basic workbook (no charts/rich styles). For styled reports use XlsxWriter.
    Returns the destination path.
    """
    dest_str = os.fspath(dest)
    if HAS_DUCKDB:
        con = duckdb.connect()
        try:
            _ensure_excel_extension(con)
            con.register("_export_df", df)
            try:
                # Forward slashes avoid any backslash-escaping surprises in the SQL literal.
                dest_sql = dest_str.replace("\\", "/")
                con.execute(f"COPY _export_df TO '{dest_sql}' (FORMAT xlsx, HEADER true)")
            finally:
                try:
                    con.unregister("_export_df")
                except Exception:
                    pass
            if os.path.exists(dest_str):
                return dest_str
        except Exception:
            pass
        finally:
            try:
                con.close()
            except Exception:
                pass
    df.to_excel(dest_str, index=False, engine="openpyxl")
    return dest_str
