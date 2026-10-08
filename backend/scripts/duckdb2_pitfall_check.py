"""
DuckDB 2.x "pitfall" verification.

Empirically checks the specific pitfalls claimed in the wild about DuckDB v2.0,
against THIS project's database and usage, so we can tell real risk from FUD.
Run under each interpreter and diff the deterministic output:

    python backend/scripts/duckdb2_pitfall_check.py                       # 1.5.x baseline
    python backend/scripts/duckdb2_pitfall_check.py data/cost_prediction.duckdb --rw

Claims under test:
  C1 storage  : default storage version of a NEW db; whether opening+writing an
                EXISTING v1.5.x db bumps its on-disk storage version.
  C2 VARIANT  : does insert need an explicit cast; can values be read back and
                queried with the variant function family.
  C3 locking  : presence/absence of SELECT ... FOR UPDATE and SERIALIZABLE.
  C6 i18n/date: ICU extension availability; default text collation order for
                CJK; NOCASE; ISO week / datepart / date_trunc / invalid-date.
  C7 extension: which core extensions report installed/loaded.

ASCII-only output (GBK-safe). Never writes to the real db: --rw operates on a copy.
"""
import os
import re
import shutil
import sys
import tempfile

import duckdb

REAL_DB = None
RW_TEST = False
for a in sys.argv[1:]:
    if a == "--rw":
        RW_TEST = True
    else:
        REAL_DB = a


def hdr_token(path):
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
        toks = sorted({t.decode() for t in re.findall(rb"v\d+\.\d+\.\d+", head)})
        return ",".join(toks) if toks else "(none)"
    except OSError as e:
        return f"(unreadable: {e})"


def q(con, sql, params=None):
    """Run sql, return 'OK <value>' or 'ERR <ExcType>: <msg first line>'."""
    try:
        r = con.execute(sql, params or []).fetchall()
        return f"OK {r}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {str(e).splitlines()[0][:90]}"


print("=" * 70)
print(f"duckdb.__version__ = {duckdb.__version__}")
try:
    print(f"PRAGMA version     = {duckdb.connect(':memory:').execute('PRAGMA version').fetchall()}")
except Exception as e:
    print("PRAGMA version err:", e)
print("=" * 70)

# ---------------- C1: storage format ----------------
print("\n[C1] STORAGE FORMAT")
tmpdir = tempfile.mkdtemp(prefix="ddb_pit_")
fresh = os.path.join(tmpdir, "fresh.duckdb")
c = duckdb.connect(fresh)
c.execute("CREATE TABLE t(x INTEGER)")
c.execute("INSERT INTO t VALUES (1),(2)")
c.execute("CHECKPOINT")
c.close()
print(f"  new-db default storage token : {hdr_token(fresh)}")

if REAL_DB and os.path.exists(REAL_DB):
    c = duckdb.connect(REAL_DB, read_only=True)
    n = c.execute("SELECT COUNT(*) FROM boq_items").fetchone()[0]
    c.close()
    print(f"  existing db (read-only)      : token={hdr_token(REAL_DB)} boq_items={n}")
    if RW_TEST:
        work = os.path.join(tmpdir, "work.duckdb")
        shutil.copy2(REAL_DB, work)
        before = hdr_token(work)
        cw = duckdb.connect(work, read_only=False)
        cw.execute("CREATE TABLE _probe(x INTEGER)")
        cw.execute("INSERT INTO _probe VALUES (1)")
        cw.execute("CHECKPOINT")
        cw.execute("DROP TABLE _probe")
        cw.execute("CHECKPOINT")
        cw.close()
        after = hdr_token(work)
        print(f"  existing db after 2.x WRITE  : token {before} -> {after} "
              f"({'BUMPED (one-way!)' if before != after else 'UNCHANGED (still readable by old ver)'})")
else:
    print("  (no real db provided)")

# ---------------- C2: VARIANT ----------------
print("\n[C2] VARIANT")
c = duckdb.connect(":memory:")
print("  create VARIANT table       :", q(c, "CREATE TABLE vt(v VARIANT)"))
print("  insert literal (no cast)   :", q(c, "INSERT INTO vt VALUES ('{\"a\":1,\"b\":[2,3]}')"))
print("  insert via ? param         :", q(c, "INSERT INTO vt VALUES (?)", ['{"c":"x"}']))
print("  insert explicit ::VARIANT  :", q(c, "INSERT INTO vt VALUES ('{\"d\":true}'::VARIANT)"))
print("  read back raw              :", q(c, "SELECT v FROM vt ORDER BY rowid"))
print("  variant_extract $.a        :", q(c, "SELECT variant_extract(v, '$.a') FROM vt WHERE variant_extract(v,'$.a') IS NOT NULL"))
print("  v -> '$.a' arrow           :", q(c, "SELECT v -> '$.a' FROM vt LIMIT 1"))
print("  typeof(v)                  :", q(c, "SELECT typeof(v) FROM vt LIMIT 1"))
c.close()

# ---------------- C3: locking / isolation ----------------
print("\n[C3] LOCKING / ISOLATION")
c = duckdb.connect(":memory:")
c.execute("CREATE TABLE k(id INTEGER, val INTEGER)")
c.execute("INSERT INTO k VALUES (1,10)")
print("  SELECT ... FOR UPDATE      :", q(c, "SELECT * FROM k WHERE id=1 FOR UPDATE"))
print("  BEGIN ISOLATION SERIALIZABLE:", q(c, "BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
try:
    c.execute("COMMIT")
except Exception:
    pass
c.close()

# ---------------- C6: i18n / collation / date ----------------
print("\n[C6] I18N / COLLATION / DATE")
c = duckdb.connect(":memory:")
print("  icu extension row          :", q(c, "SELECT extension_name, installed, loaded FROM duckdb_extensions() WHERE extension_name='icu'"))
# CJK default collation order (reveals binary vs pinyin/ICU collation)
c.execute("CREATE TABLE cj(id VARCHAR, name VARCHAR)")
for i, nm in [("1", "张三"), ("2", "李四"), ("3", "王五"), ("4", "安娜")]:
    c.execute("INSERT INTO cj VALUES (?,?)", [i, nm])
print("  ORDER BY cjk name -> ids   :", q(c, "SELECT id FROM cj ORDER BY name"))
print("  binary codepoint order ref : (expected 4,1,2,3 if byte/binary collation)")
print("  NOCASE equality            :", q(c, "SELECT 'aBc' = 'abc' COLLATE NOCASE"))
print("  strftime ISO %G-%V         :", q(c, "SELECT strftime(DATE '2026-03-01', '%G-%V')"))
print("  datepart week              :", q(c, "SELECT datepart('week', DATE '2026-03-01')"))
print("  datepart isoyear           :", q(c, "SELECT datepart('isoyear', DATE '2026-01-01')"))
print("  date_trunc week            :", q(c, "SELECT date_trunc('week', DATE '2026-03-01')"))
print("  invalid date 2026-02-29    :", q(c, "SELECT DATE '2026-02-29'"))
print("  leap date 2024-02-29       :", q(c, "SELECT DATE '2024-02-29'"))
print("  CURRENT_TIMESTAMP type     :", q(c, "SELECT typeof(CURRENT_TIMESTAMP)"))
c.close()

# ---------------- C7: extensions ----------------
print("\n[C7] CORE EXTENSIONS")
c = duckdb.connect(":memory:")
print("  json/parquet/icu status    :", q(c, "SELECT extension_name, installed, loaded FROM duckdb_extensions() WHERE extension_name IN ('json','parquet','icu') ORDER BY extension_name"))
c.close()

shutil.rmtree(tmpdir, ignore_errors=True)
print("\n" + "=" * 70)
print("done")
