"""
normalize_prices.py
价格基准标准化：将 boq_items 的综合单价/合价折算至 2020 年基期。

步骤：
1. 填充 price_index 表（建设成本指数，基期 2020 = 1.0）
2. 根据 project_meta.build_year 查找修正系数，更新 boq_items 的折算列
3. 无 build_year 的项目 factor = 1.0（不调整）
4. 仅处理需要更新的行，避免重复处理
"""

import sys
import os
import duckdb

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cost_prediction.duckdb'))

# 近似建设成本指数（基期 2020 = 1.0）
# 基于国家统计局建筑安装工程投资价格指数
PRICE_INDICES = {
    2010: 0.72, 2011: 0.76, 2012: 0.80, 2013: 0.84, 2014: 0.88,
    2015: 0.91, 2016: 0.93, 2017: 0.95, 2018: 0.97, 2019: 0.99,
    2020: 1.00, 2021: 1.04, 2022: 1.07, 2023: 1.10,
}

BASE_YEAR = 2020
BASE_INDEX = PRICE_INDICES[BASE_YEAR]  # 1.0


def populate_price_index(conn: duckdb.DuckDBPyConnection) -> None:
    """填充 price_index 表（仅插入尚不存在的年份）"""
    inserted = 0
    for year, adj_factor in PRICE_INDICES.items():
        exists = conn.execute(
            "SELECT COUNT(*) FROM price_index WHERE year = ?", [year]
        ).fetchone()[0]
        if exists == 0:
            conn.execute(
                "INSERT INTO price_index (year, labor_index, material_index, adjustment_factor) "
                "VALUES (?, ?, ?, ?)",
                [year, adj_factor, adj_factor, adj_factor]
            )
            inserted += 1
    print(f"[price_index] 插入 {inserted} 条年份指数记录")


def normalize_project_prices(conn: duckdb.DuckDBPyConnection) -> dict:
    """
    对每个有 build_year 的项目，计算 price_adjust_factor 并更新 boq_items。
    全部使用绑定参数（? 占位）——实测 DuckDB 1.5.x/2.x 的 UPDATE SET 子句均支持
    参数绑定，无需再用 f-string 拼接 SQL（消除注入面与多余规避）。
    """
    projects = conn.execute(
        "SELECT project_id, build_year FROM project_meta"
    ).fetchall()

    stats = {
        'projects_with_year': 0,
        'projects_without_year': 0,
        'items_adjusted': 0,
        'items_no_change': 0,
        'factors': {},
    }

    for project_id, build_year in projects:
        if build_year is not None and build_year in PRICE_INDICES:
            factor = round(BASE_INDEX / PRICE_INDICES[build_year], 6)
            stats['projects_with_year'] += 1
            stats['factors'][build_year] = factor

            # 先统计需要更新的行数
            cnt = conn.execute(
                "SELECT COUNT(*) FROM boq_items WHERE project_id = ? AND comp_unit_price_adj IS NULL",
                [project_id]
            ).fetchone()[0]

            if cnt > 0:
                conn.execute("""
                    UPDATE boq_items
                    SET price_adjust_factor = ?,
                        comp_unit_price_adj = ROUND(comp_unit_price * ?, 4),
                        total_price_adj    = ROUND(total_price * ?, 4),
                        price_base_year    = ?
                    WHERE project_id = ?
                      AND comp_unit_price_adj IS NULL
                """, [factor, factor, factor, BASE_YEAR, project_id])
                stats['items_adjusted'] += cnt

        else:
            stats['projects_without_year'] += 1

            cnt = conn.execute(
                "SELECT COUNT(*) FROM boq_items WHERE project_id = ? AND comp_unit_price_adj IS NULL",
                [project_id]
            ).fetchone()[0]

            if cnt > 0:
                conn.execute("""
                    UPDATE boq_items
                    SET price_adjust_factor = ?,
                        comp_unit_price_adj = comp_unit_price,
                        total_price_adj    = total_price,
                        price_base_year    = ?
                    WHERE project_id = ?
                      AND comp_unit_price_adj IS NULL
                """, [1.0, BASE_YEAR, project_id])
                stats['items_no_change'] += cnt

    return stats


def print_report(conn: duckdb.DuckDBPyConnection, stats: dict) -> None:
    """输出统计报告"""
    print("\n" + "=" * 60)
    print("价格基准标准化报告")
    print("=" * 60)

    print(f"\n基期年份: {BASE_YEAR}")
    print(f"处理项目数（有年份）: {stats['projects_with_year']}")
    print(f"处理项目数（无年份）: {stats['projects_without_year']}")

    if stats['factors']:
        print("\n年份修正系数表（build_year -> factor）:")
        for year in sorted(stats['factors']):
            print(f"  {year} -> {stats['factors'][year]:.6f}")

    print(f"\n本次折算条目数: {stats['items_adjusted']}")
    print(f"本次未调整条目数（factor=1.0）: {stats['items_no_change']}")

    total_items = conn.execute("SELECT COUNT(*) FROM boq_items").fetchone()[0]
    null_adj = conn.execute(
        "SELECT COUNT(*) FROM boq_items WHERE comp_unit_price_adj IS NULL"
    ).fetchone()[0]
    adj_items = conn.execute(
        "SELECT COUNT(*) FROM boq_items WHERE price_adjust_factor IS NOT NULL AND price_adjust_factor != 1.0"
    ).fetchone()[0]

    print(f"\nboq_items 总计: {total_items}")
    print(f"  已折算（factor!=1.0）: {adj_items}")
    print(f"  未调整（factor=1.0）: {total_items - adj_items - null_adj}")
    print(f"  待处理（adj IS NULL）: {null_adj}")

    row = conn.execute(
        """
        SELECT
            AVG(comp_unit_price),
            AVG(comp_unit_price_adj),
            AVG(total_price),
            AVG(total_price_adj)
        FROM boq_items
        WHERE is_active = 1
          AND comp_unit_price > 0
          AND comp_unit_price_adj IS NOT NULL
          AND comp_unit_price_adj > 0
        """
    ).fetchone()

    if row[0] and row[1]:
        avg_orig, avg_adj, avg_tot_orig, avg_tot_adj = row
        print(f"\n活跃条目价格对比（comp_unit_price > 0）:")
        print(f"  原始平均综合单价: {avg_orig:.4f}")
        print(f"  折算平均综合单价: {avg_adj:.4f}")
        print(f"  综合单价调整比:   {avg_adj / avg_orig:.4f}")
        print(f"  原始平均合价:     {avg_tot_orig:.4f}")
        print(f"  折算平均合价:     {avg_tot_adj:.4f}")
        print(f"  合价调整比:       {avg_tot_adj / avg_tot_orig:.4f}")

    print("\n" + "=" * 60)


def main():
    print(f"数据库路径: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"错误: 数据库文件不存在: {DB_PATH}")
        sys.exit(1)

    conn = duckdb.connect(DB_PATH)

    try:
        # Step 1: 填充 price_index 表
        print("\n[Step 1] 填充 price_index 表...")
        populate_price_index(conn)

        print("\nprice_index 表内容:")
        for row in conn.execute("SELECT * FROM price_index ORDER BY year").fetchall():
            print(f"  {row[0]}: labor={row[1]}, material={row[2]}, factor={row[3]}")

        # Step 2: 价格折算
        print("\n[Step 2] 执行价格折算...")
        stats = normalize_project_prices(conn)

        # Step 3: 输出报告
        print_report(conn, stats)

    finally:
        conn.close()


if __name__ == '__main__':
    main()
