"""发布前存储令牌护栏（N1）。

DuckDB 2.0 新建/重建的库文件存储令牌为 v2.0.0，1.5.x 无法打开（单向门）。
本脚本读取库文件头部的存储版本令牌，并与当前安装的 duckdb 主版本比对：

- 库令牌 v2.x 而运行时 duckdb < 2.0  -> 危险（打不开），退出码 2
- 库令牌 v1.x 而运行时 duckdb >= 2.0 -> 可读写、令牌保留，退出码 0（附警告）
- 一致                                -> 退出码 0

在打包 ModelScope 部署包（经 Git LFS 分发 .duckdb）或发布前运行，
确保不会把 1.5.x 环境无法打开的库文件发出去。

用法：
    python backend/scripts/check_db_storage_token.py [path/to/cost_prediction.duckdb]
默认检查 data/cost_prediction.duckdb。ASCII 输出，避免 GBK 终端 UnicodeEncodeError。
"""
import os
import re
import sys

import duckdb

DEFAULT_DB = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "cost_prediction.duckdb"))


def read_storage_token(path: str):
    """从库文件头部 8KB 内读取形如 v1.5.5 / v2.0.0 的存储版本令牌。"""
    with open(path, "rb") as f:
        head = f.read(8192)
    matches = re.findall(rb"v\d+\.\d+\.\d+", head)
    return matches[0].decode() if matches else None


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    if not os.path.exists(db):
        print(f"[SKIP] database not found: {db}")
        return 0

    token = read_storage_token(db)
    runtime = duckdb.__version__
    runtime_major = int(runtime.split(".")[0])
    print(f"database        : {db}")
    print(f"storage token   : {token}")
    print(f"runtime duckdb  : {runtime} (major {runtime_major})")

    if token is None:
        print("[WARN] could not locate a storage token in the file header")
        return 0

    token_major = int(token.lstrip("v").split(".")[0])
    if token_major >= 2 and runtime_major < 2:
        print("[FAIL] database uses v2.x storage but runtime duckdb < 2.0 -> cannot open (one-way door).")
        print("       Restore a v1.x backup, or cut the whole fleet over to DuckDB 2.x together.")
        return 2
    if token_major < 2 and runtime_major >= 2:
        print("[OK] v1.x database under a duckdb 2.x runtime: readable/writable, token preserved.")
        print("     Do NOT recreate/init this DB while any environment is still on 1.5.x.")
        return 0

    print("[OK] storage token and runtime major version are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
