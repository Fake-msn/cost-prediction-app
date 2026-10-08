"""真实 DuckDB 集成测试（非 mock）。

与 backend/tests/ 不同：本目录不使用全局 mock，直接对真实 DuckDB 引擎跑通
项目核心 DB 构造。覆盖本次 DuckDB 2.0 评估落地的修复：

- H1  init_duckdb 创建 prediction_uploads 表
- H2  project_meta 补齐 data_loader._load_duckdb_dataframe 直接 SELECT 的列
- H4  normalize_prices 绑定参数 UPDATE 正确折算
- H5/H7 prediction_uploads 生命周期全部经 data_loader（写锁串行化 + 只读连接）

所有用例都在 tempfile 目录中的独立库上运行，绝不触碰 data/cost_prediction.duckdb。
CI 以独立步骤运行（真实安装 duckdb），作为 DuckDB 兼容性门禁。
"""
import os
import sys
import json
import tempfile
from datetime import datetime, timedelta

import pytest
import duckdb

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import init_duckdb          # noqa: E402
import normalize_prices     # noqa: E402
from data_loader import DataLoader  # noqa: E402


@pytest.fixture()
def db_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _init(db_dir):
    db_path = os.path.join(db_dir, "cost_prediction.duckdb")
    init_duckdb.init_database(db_path)
    return db_path


def test_init_creates_prediction_uploads_and_meta_columns(db_dir):
    """H1 + H2：init 后 prediction_uploads 存在，project_meta 含 data_loader 直接 SELECT 的列。"""
    db_path = _init(db_dir)
    conn = duckdb.connect(db_path, read_only=True)
    try:
        tables = {t[0] for t in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()}
        assert "prediction_uploads" in tables, "H1: prediction_uploads 表未创建"

        cols = {c[0] for c in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='project_meta'"
        ).fetchall()}
        for col in ("above_ground_floors", "under_ground_floors",
                    "decoration_standard", "foundation_type"):
            assert col in cols, f"H2: project_meta 缺少列 {col}"
    finally:
        conn.close()


def test_load_duckdb_dataframe_no_binder_error(db_dir):
    """H2 回归：_load_duckdb_dataframe 的 SELECT 不应再因缺列触发 binder error。"""
    db_path = _init(db_dir)
    conn = duckdb.connect(db_path)
    conn.execute(
        "INSERT INTO project_meta (project_id, name, building_type, total_area, "
        "unit_price, total_cost, extraction_date) VALUES (?,?,?,?,?,?,?)",
        ["P0001", "测试项目", "住宅", 1000.0, 3000.0, 3000000.0, "2026-01-01"],
    )
    conn.close()

    loader = DataLoader(data_dir=db_dir)
    df = loader._load_duckdb_dataframe()
    assert df is not None and len(df) == 1
    assert "楼层数" in df.columns and "装修标准" in df.columns


def test_normalize_prices_bound_params(db_dir):
    """H4：绑定参数 UPDATE 正确折算价格至 2020 基期。"""
    db_path = _init(db_dir)
    conn = duckdb.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO project_meta (project_id, name, build_year) VALUES (?,?,?)",
            ["PX", "折算项目", 2023],
        )
        conn.execute(
            "INSERT INTO boq_items (item_id, project_id, boq_code, comp_unit_price, total_price) "
            "VALUES (?,?,?,?,?)",
            ["I1", "PX", "01001", 100.0, 1000.0],
        )
        normalize_prices.populate_price_index(conn)
        stats = normalize_prices.normalize_project_prices(conn)
        assert stats["items_adjusted"] == 1

        factor, cu_adj, tp_adj, base_year = conn.execute(
            "SELECT price_adjust_factor, comp_unit_price_adj, total_price_adj, price_base_year "
            "FROM boq_items WHERE item_id='I1'"
        ).fetchone()
        expected = round(normalize_prices.BASE_INDEX / normalize_prices.PRICE_INDICES[2023], 6)
        assert factor == expected
        assert cu_adj == round(100.0 * expected, 4)
        assert tp_adj == round(1000.0 * expected, 4)
        assert base_year == normalize_prices.BASE_YEAR
    finally:
        conn.close()


def test_normalize_prices_no_year_factor_one(db_dir):
    """H4：无 build_year 的项目 factor=1.0，折算列等于原值。"""
    db_path = _init(db_dir)
    conn = duckdb.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO project_meta (project_id, name, build_year) VALUES (?,?,?)",
            ["PY", "无年份项目", None],
        )
        conn.execute(
            "INSERT INTO boq_items (item_id, project_id, boq_code, comp_unit_price, total_price) "
            "VALUES (?,?,?,?,?)",
            ["I2", "PY", "02001", 50.0, 500.0],
        )
        normalize_prices.populate_price_index(conn)
        stats = normalize_prices.normalize_project_prices(conn)
        assert stats["items_no_change"] == 1
        factor, cu_adj, tp_adj = conn.execute(
            "SELECT price_adjust_factor, comp_unit_price_adj, total_price_adj "
            "FROM boq_items WHERE item_id='I2'"
        ).fetchone()
        assert factor == 1.0 and cu_adj == 50.0 and tp_adj == 500.0
    finally:
        conn.close()


def test_prediction_uploads_lifecycle_via_data_loader(db_dir):
    """H5/H7：上传记录生命周期全部经 data_loader（写锁串行化 + 只读连接）。"""
    _init(db_dir)
    loader = DataLoader(data_dir=db_dir)

    future = (datetime.now() + timedelta(hours=24)).isoformat()
    past = (datetime.now() - timedelta(hours=2)).isoformat()

    loader.record_upload("aaaa1111", "a.pdf", "pdf", json.dumps({"x": 1}), future)
    loader.record_upload("bbbb2222", "b.docx", "docx", json.dumps({"y": 2}), past)

    row = loader.get_upload("aaaa1111")
    assert row is not None and row[0] == "aaaa1111"
    assert json.loads(row[4]) == {"x": 1}
    assert loader.get_upload("does-not-exist") is None

    # 仅 bbbb2222 已过期
    assert loader.list_expired_upload_ids(100) == ["bbbb2222"]
    assert loader.list_active_upload_ids() == {"aaaa1111", "bbbb2222"}

    loader.delete_uploads(["bbbb2222"])
    assert loader.list_active_upload_ids() == {"aaaa1111"}

    loader.delete_upload("aaaa1111")
    assert loader.list_active_upload_ids() == set()


def test_record_upload_persists_across_connections(db_dir):
    """写入经独立连接持久化，重新打开只读连接仍可读回。"""
    db_path = _init(db_dir)
    loader = DataLoader(data_dir=db_dir)
    loader.record_upload("cccc3333", "c.xlsx", "xlsx", "{}",
                         (datetime.now() + timedelta(hours=1)).isoformat())

    conn = duckdb.connect(db_path, read_only=True)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM prediction_uploads WHERE task_id='cccc3333'"
        ).fetchone()[0]
        assert n == 1
    finally:
        conn.close()
