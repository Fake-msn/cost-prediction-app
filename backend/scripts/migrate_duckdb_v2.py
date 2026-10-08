"""
DuckDB v2 migration + verification tool.

Purpose
-------
Safely move data/cost_prediction.duckdb onto DuckDB 2.x with a verifiable,
reversible process. Empirically, DuckDB 2.0 keeps an existing v1.5.x database
in its current backward-compatible on-disk format when it opens/writes it (the
storage version is NOT auto-bumped), so a plain library upgrade needs no data
rewrite. This script therefore focuses on: backup -> snapshot -> optional
CHECKPOINT -> re-verify -> rollback info.

Run it with the DuckDB 2.x interpreter. All console output is ASCII-only to
avoid UnicodeEncodeError on GBK Windows terminals.

Usage
-----
    # verify only (default, read-only, no writes, still takes a backup)
    python backend/scripts/migrate_duckdb_v2.py --mode verify

    # verify + force a CHECKPOINT write through the 2.x engine
    python backend/scripts/migrate_duckdb_v2.py --mode checkpoint

    # operate on an explicit file / skip backup
    python backend/scripts/migrate_duckdb_v2.py --db data/cost_prediction.duckdb --no-backup
"""
import argparse
import os
import re
import shutil
import sys
from datetime import datetime

import duckdb

TABLES = [
    "project_meta",
    "unit_project_meta",
    "project_cost_breakdown",
    "boq_items",
    "price_index",
    "prediction_uploads",
]

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(ROOT, "data", "cost_prediction.duckdb")
DEFAULT_BACKUP_DIR = os.path.join(ROOT, "data", "backups")


def header_storage_token(path):
    """Read the version token stored in the DuckDB file header (first 8KB)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
        toks = sorted({t.decode() for t in re.findall(rb"v\d+\.\d+\.\d+", head)})
        return ",".join(toks) if toks else "(none)"
    except OSError as e:
        return f"(unreadable: {e})"


def snapshot(con):
    """Return {table: (row_count, sorted_column_signature)} for existing tables."""
    present = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    snap = {}
    for t in TABLES:
        if t not in present:
            snap[t] = None
            continue
        cnt = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cols = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=? ORDER BY column_name",
            [t],
        ).fetchall()
        sig = ";".join(f"{c}:{d}" for c, d in cols)
        snap[t] = (cnt, sig)
    return snap


def print_snapshot(snap):
    for t in TABLES:
        v = snap.get(t)
        if v is None:
            print(f"    {t:<26} (absent)")
        else:
            ncols = v[1].count(";") + 1 if v[1] else 0
            print(f"    {t:<26} rows={v[0]:<8} cols={ncols}")


def main():
    ap = argparse.ArgumentParser(description="DuckDB v2 migration + verification")
    ap.add_argument("--db", default=DEFAULT_DB, help="path to the .duckdb file")
    ap.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, help="where to write the backup copy")
    ap.add_argument("--mode", choices=["verify", "checkpoint"], default="verify",
                    help="verify=read-only checks; checkpoint=also run a write CHECKPOINT via 2.x")
    ap.add_argument("--no-backup", action="store_true", help="skip creating a backup copy (not recommended)")
    args = ap.parse_args()

    ver = duckdb.__version__
    print("=" * 64)
    print("DuckDB v2 migration + verification")
    print("=" * 64)
    print(f"  duckdb library : {ver}")
    print(f"  target db      : {args.db}")
    print(f"  mode           : {args.mode}")

    if tuple(int(x) for x in ver.split(".")[:1]) < (2,):
        print("\n[ABORT] This tool must run under DuckDB 2.x. "
              f"Detected {ver}. Activate the 2.x environment first.")
        return 2
    if not os.path.exists(args.db):
        print(f"\n[ABORT] database file not found: {args.db}")
        return 2

    # 1) Backup (rollback baseline)
    backup_path = None
    if not args.no_backup:
        os.makedirs(args.backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(args.backup_dir, f"cost_prediction.pre_v2_migration.{ts}.duckdb")
        shutil.copy2(args.db, backup_path)
        print(f"\n[1] backup written: {backup_path}")
    else:
        print("\n[1] backup SKIPPED (--no-backup)")

    tok_before = header_storage_token(args.db)
    print(f"[2] header storage token (before): {tok_before}")

    # 2) Pre snapshot (read-only)
    con = duckdb.connect(args.db, read_only=True)
    snap_before = snapshot(con)
    con.close()
    print("[3] schema/row snapshot (before):")
    print_snapshot(snap_before)

    # 3) Optional CHECKPOINT write through the 2.x engine
    if args.mode == "checkpoint":
        print("[4] opening read-write and running CHECKPOINT via 2.x ...")
        cw = duckdb.connect(args.db, read_only=False)
        cw.execute("CHECKPOINT")
        cw.close()
        print("    checkpoint done")
    else:
        print("[4] mode=verify -> no write performed")

    # 4) Post snapshot + compare
    con = duckdb.connect(args.db, read_only=True)
    snap_after = snapshot(con)
    con.close()
    tok_after = header_storage_token(args.db)
    print(f"[5] header storage token (after) : {tok_after}")
    print("[6] schema/row snapshot (after):")
    print_snapshot(snap_after)

    mismatches = [t for t in TABLES if snap_before.get(t) != snap_after.get(t)]
    print("\n" + "=" * 64)
    if mismatches:
        print(f"[FAIL] data/schema changed during migration: {mismatches}")
        if backup_path:
            print(f"       rollback: restore {backup_path} and run under duckdb 1.5.x")
        return 1

    print("[OK] verification passed: row counts + schema unchanged under DuckDB 2.x")
    if tok_before == tok_after:
        print(f"[OK] storage format unchanged ({tok_after}) -> file is STILL readable by 1.5.x")
        print("     => rollback is trivial: reinstall duckdb 1.5.x, no data restore needed.")
    else:
        print(f"[WARN] storage token changed {tok_before} -> {tok_after}: "
              "file may no longer open under 1.5.x.")
        if backup_path:
            print(f"       to roll back, restore {backup_path}.")
    if backup_path:
        print(f"\nBackup kept at: {backup_path}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
