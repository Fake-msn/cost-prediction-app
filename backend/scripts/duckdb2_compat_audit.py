"""
DuckDB 2.x interface-compatibility audit.

Exercises every DuckDB SQL/API construct this project actually uses so behavior
can be compared between the current production DuckDB (1.5.x) and a 2.x build.
Used to gate the DuckDB 2.0 cutover (see DUCKDB2_UPGRADE_RUNBOOK.md).

Run under each interpreter and diff the output:
    # production / baseline (1.5.x)
    python backend/scripts/duckdb2_compat_audit.py [path/to/cost_prediction.duckdb]
    # after installing DuckDB 2.x into the environment
    python backend/scripts/duckdb2_compat_audit.py [path/to/cost_prediction.duckdb]

The optional argument enables a read-only check against a real database file.
Console output is ASCII-only to avoid UnicodeEncodeError on GBK Windows terminals.
"""
import os
import sys
import tempfile

import duckdb

REAL_DB = sys.argv[1] if len(sys.argv) > 1 else None
results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((name, "PASS", detail or ""))
    except Exception as e:
        results.append((name, "FAIL", f"{type(e).__name__}: {e}"))


print(f"### duckdb {duckdb.__version__} ###")
con = duckdb.connect(":memory:")


# 1. Schema DDL with PRIMARY KEY / FOREIGN KEY / DEFAULT (init_duckdb.py)
def ddl():
    con.execute("""
        CREATE TABLE IF NOT EXISTS pm(
            project_id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            total_cost DOUBLE,
            data_quality_grade VARCHAR DEFAULT 'C',
            extraction_date DATE,
            mixed_types BOOLEAN
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS boq(
            item_id VARCHAR PRIMARY KEY,
            project_id VARCHAR,
            boq_code VARCHAR NOT NULL,
            comp_unit_price DOUBLE,
            price_adjust_factor DOUBLE,
            comp_unit_price_adj DOUBLE,
            FOREIGN KEY (project_id) REFERENCES pm(project_id)
        )""")
    return "2 tables"
check("DDL PK/FK/DEFAULT/IF NOT EXISTS", ddl)


# 2. INSERT OR REPLACE with ? params, explicit column list (data_loader / extract_boq)
def insert_or_replace():
    cols = "(project_id,name,total_cost,data_quality_grade,extraction_date,mixed_types)"
    con.execute(f"INSERT OR REPLACE INTO pm {cols} VALUES (?,?,?,?,?,?)",
                ("P1", "proj-1", 100.0, "A", "2026-01-01", False))
    con.execute(f"INSERT OR REPLACE INTO pm {cols} VALUES (?,?,?,?,?,?)",
                ("P1", "proj-1-edit", 200.0, "B", "2026-01-02", True))
    n = con.execute("SELECT COUNT(*) FROM pm WHERE project_id='P1'").fetchone()[0]
    nm = con.execute("SELECT name FROM pm WHERE project_id='P1'").fetchone()[0]
    assert n == 1, f"upsert produced {n} rows"
    return f"rows={n} name={nm}"
check("INSERT OR REPLACE upsert (? bind)", insert_or_replace)


# 2b. executemany with ? params (extract_boq.write_to_duckdb) — pm.P1 now exists
def executemany():
    rows = [(f"I{i}", "P1", f"01{i:03d}", 10.0 * i, 1.0, 10.0 * i) for i in range(5)]
    con.executemany("INSERT INTO boq VALUES (?,?,?,?,?,?)", rows)
    return f"inserted={con.execute('SELECT COUNT(*) FROM boq').fetchone()[0]}"
check("executemany (?)", executemany)


# 2c. ALTER TABLE ADD COLUMN IF NOT EXISTS, idempotent (init_duckdb / cost_breakdown_extractor)
def alter():
    con.execute("CREATE TABLE alt_t(a VARCHAR)")
    con.execute("ALTER TABLE alt_t ADD COLUMN IF NOT EXISTS foundation_type VARCHAR")
    con.execute("ALTER TABLE alt_t ADD COLUMN IF NOT EXISTS foundation_type VARCHAR")
    return f"alt_t cols={len(con.execute('DESCRIBE alt_t').fetchall())}"
check("ALTER ADD COLUMN IF NOT EXISTS (idempotent)", alter)


# 3. LIMIT ? binding
check("LIMIT ? bind",
      lambda: str(con.execute("SELECT project_id FROM pm ORDER BY extraction_date DESC LIMIT ?", [3]).fetchall()))


# 4. information_schema.tables / .columns probing (many modules)
def info_schema():
    t = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    c = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='pm'").fetchall()
    return f"tables={len(t)} pm_cols={len(c)}"
check("information_schema.tables/.columns", info_schema)


# 5. DESCRIBE (enrich_metadata)
check("DESCRIBE", lambda: str(len(con.execute("DESCRIBE pm").fetchall())) + " cols")


# 6. CURRENT_TIMESTAMP comparison against stored value (main.py cleanup)
def current_ts():
    con.execute("CREATE TABLE up(task_id VARCHAR, expires_at TIMESTAMP)")
    con.execute("INSERT INTO up VALUES (?, ?)", ("t1", "2000-01-01 00:00:00"))
    r = con.execute("SELECT task_id FROM up WHERE expires_at < CURRENT_TIMESTAMP LIMIT ?", [10]).fetchall()
    return f"expired={r}"
check("CURRENT_TIMESTAMP compare + LIMIT ?", current_ts)


# 7. Analytic SELECT: CASE SUBSTR, SUM(CASE WHEN LIKE), COUNT(DISTINCT), ROUND, aliases
def analytics():
    q = """
        SELECT pm.name AS proj_name,
               CASE pm.data_quality_grade WHEN 'A' THEN 'A' ELSE 'other' END AS grade,
               SUM(CASE WHEN boq.boq_code LIKE '01%' THEN boq.comp_unit_price_adj ELSE 0 END) AS part_sum,
               COUNT(DISTINCT boq.project_id) AS n_proj,
               ROUND(AVG(boq.comp_unit_price) * 1.0, 4) AS avg_price
        FROM boq JOIN pm ON boq.project_id = pm.project_id
        GROUP BY pm.name, pm.data_quality_grade
    """
    return str(con.execute(q).fetchall())
check("analytic SELECT (CASE/SUM/LIKE/DISTINCT/ROUND)", analytics)


# 8. fetchdf() -> pandas DataFrame (data_loader 3 call sites)
def fetchdf():
    df = con.execute("SELECT project_id, name FROM pm").fetchdf()
    return f"df shape={df.shape} cols={list(df.columns)}"
check("fetchdf()", fetchdf)


# 9. UPDATE with f-string interpolated literals (normalize_prices workaround)
def update_fstring():
    factor = 1.23456
    pid = "P1"
    con.execute(f"UPDATE boq SET price_adjust_factor = {factor}, "
                f"comp_unit_price_adj = ROUND(comp_unit_price * {factor}, 4) "
                f"WHERE project_id = '{pid}'")
    return f"updated adj={con.execute('SELECT comp_unit_price_adj FROM boq LIMIT 1').fetchone()[0]}"
check("UPDATE f-string literals (normalize_prices)", update_fstring)


# 10. commit() lifecycle
check("commit()", lambda: con.commit() or "ok")


# 11. read_only connection open on a real file (data_loader / main.get_upload_result)
def ro_conn():
    fd, p = tempfile.mkstemp(suffix=".duckdb")
    os.close(fd)
    os.remove(p)
    w = duckdb.connect(p)
    w.execute("CREATE TABLE IF NOT EXISTS t(x INTEGER)")
    w.close()
    c2 = duckdb.connect(p, read_only=True)
    c2.execute("SELECT COUNT(*) FROM t").fetchone()
    c2.close()
    os.remove(p)
    return "ok"
check("connect(file, read_only=True)", ro_conn)


# 12. VARIANT type availability (2.x semi-structured feature)
def variant():
    con.execute("CREATE TABLE vt(v VARIANT)")
    con.execute("INSERT INTO vt VALUES (?)", ['{"a":1}'])
    return "VARIANT supported"
check("VARIANT type", variant)

con.close()

# 13. Read-path against a REAL db file (read_only) if provided
if REAL_DB:
    def real_read():
        c = duckdb.connect(REAL_DB, read_only=True)
        b = c.execute("SELECT COUNT(*) FROM boq_items").fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM project_meta").fetchone()[0]
        df = c.execute("SELECT project_id, name FROM project_meta LIMIT 3").fetchdf()
        c.close()
        return f"boq_items={b} project_meta={m} df={df.shape}"
    check(f"REAL read_only {REAL_DB}", real_read)

print()
w = max(len(n) for n, _, _ in results)
fails = 0
for name, status, detail in results:
    if status == "FAIL":
        fails += 1
    print(f"[{status}] {name.ljust(w)}  {detail}")
print()
print(f"### {len(results) - fails}/{len(results)} PASS, {fails} FAIL under duckdb {duckdb.__version__} ###")
sys.exit(1 if fails else 0)
