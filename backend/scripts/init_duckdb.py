#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DuckDB Schema 初始化脚本
创建造价预测所需的4张核心表
"""
import os
import duckdb

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cost_prediction.duckdb')

SCHEMA_SQL = """
-- L1: 项目元数据表
CREATE TABLE IF NOT EXISTS project_meta (
    project_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    building_type VARCHAR,
    structure_type VARCHAR,
    location VARCHAR,
    build_year INTEGER,
    total_area DOUBLE,
    total_cost DOUBLE,
    unit_price DOUBLE,
    source_file VARCHAR,
    source_sheets INTEGER,
    extraction_date DATE,
    extraction_version VARCHAR,
    data_quality_grade VARCHAR DEFAULT 'C',
    metadata_completeness DOUBLE,
    outlier_count INTEGER DEFAULT 0,
    crosscheck_diff_pct DOUBLE,
    training_weight DOUBLE DEFAULT 0.5,
    confidence DOUBLE DEFAULT 0.5,
    field_source VARCHAR DEFAULT 'extracted',
    building_count INTEGER DEFAULT 1,
    buildings_json VARCHAR,
    max_floor INTEGER,
    min_floor INTEGER,
    mixed_types BOOLEAN DEFAULT FALSE
);

-- L2: 单位工程元数据表
CREATE TABLE IF NOT EXISTS unit_project_meta (
    unit_id VARCHAR PRIMARY KEY,
    project_id VARCHAR REFERENCES project_meta(project_id),
    unit_name VARCHAR,
    trade VARCHAR,
    floor_count INTEGER,
    area DOUBLE,
    cost_summary DOUBLE,
    division VARCHAR
);

-- L2.5: 费用构成表 (从源 Excel E.2/F.1.1/E.3/H表-13 提取)
CREATE TABLE IF NOT EXISTS project_cost_breakdown (
    project_id VARCHAR PRIMARY KEY,
    project_name VARCHAR NOT NULL,
    building_trade_cost DOUBLE,
    decoration_trade_cost DOUBLE,
    installation_trade_cost DOUBLE,
    foundation_division_cost DOUBLE,
    main_structure_cost DOUBLE,
    roofing_cost DOUBLE,
    exterior_wall_cost DOUBLE,
    part_item_cost DOUBLE,
    measure_cost DOUBLE,
    regulation_cost DOUBLE,
    tax_cost DOUBLE,
    labor_cost DOUBLE,
    labor_source VARCHAR,
    foundation_type VARCHAR,
    extraction_date DATE,
    source_file VARCHAR,
    e2_count INTEGER,
    f11_count INTEGER,
    e3_count INTEGER,
    h13_count INTEGER,
    extraction_errors TEXT,
    FOREIGN KEY (project_id) REFERENCES project_meta(project_id)
);

-- L3: 清单项目表 (核心)
CREATE TABLE IF NOT EXISTS boq_items (
    item_id VARCHAR PRIMARY KEY,
    project_id VARCHAR REFERENCES project_meta(project_id),
    unit_project VARCHAR,
    boq_code VARCHAR NOT NULL,
    item_name VARCHAR,
    spec_text VARCHAR,
    division VARCHAR,
    trade VARCHAR,
    unit VARCHAR,
    quantity DOUBLE,
    comp_unit_price DOUBLE,
    total_price DOUBLE,
    labor_fee DOUBLE,
    is_active INTEGER DEFAULT 1,
    flag_outlier INTEGER DEFAULT 0,
    flag_code_error INTEGER DEFAULT 0,
    price_base_year INTEGER DEFAULT 2020,
    price_adjust_factor DOUBLE DEFAULT 1.0,
    comp_unit_price_adj DOUBLE,
    total_price_adj DOUBLE
);

-- 价格指数表
CREATE TABLE IF NOT EXISTS price_index (
    year INTEGER PRIMARY KEY,
    labor_index DOUBLE,
    material_index DOUBLE,
    adjustment_factor DOUBLE
);
"""


def init_database(db_path: str = None) -> str:
    """初始化 DuckDB 数据库，返回数据库路径"""
    if db_path is None:
        db_path = DB_PATH
    
    # 确保目录存在
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = duckdb.connect(db_path)
    try:
        # 创建4张表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_meta (
                project_id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                building_type VARCHAR,
                structure_type VARCHAR,
                location VARCHAR,
                build_year INTEGER,
                total_area DOUBLE,
                total_cost DOUBLE,
                unit_price DOUBLE,
                source_file VARCHAR,
                source_sheets INTEGER,
                extraction_date DATE,
                extraction_version VARCHAR,
                data_quality_grade VARCHAR DEFAULT 'C',
                metadata_completeness DOUBLE,
                outlier_count INTEGER DEFAULT 0,
                crosscheck_diff_pct DOUBLE,
                training_weight DOUBLE DEFAULT 0.5,
                confidence DOUBLE DEFAULT 0.5,
                field_source VARCHAR DEFAULT 'extracted',
                building_count INTEGER DEFAULT 1,
                buildings_json VARCHAR,
                max_floor INTEGER,
                min_floor INTEGER,
                mixed_types BOOLEAN DEFAULT FALSE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unit_project_meta (
                unit_id VARCHAR PRIMARY KEY,
                project_id VARCHAR REFERENCES project_meta(project_id),
                unit_name VARCHAR,
                trade VARCHAR,
                floor_count INTEGER,
                area DOUBLE,
                cost_summary DOUBLE,
                division VARCHAR
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boq_items (
                item_id VARCHAR PRIMARY KEY,
                project_id VARCHAR REFERENCES project_meta(project_id),
                unit_project VARCHAR,
                boq_code VARCHAR NOT NULL,
                item_name VARCHAR,
                spec_text VARCHAR,
                division VARCHAR,
                trade VARCHAR,
                unit VARCHAR,
                quantity DOUBLE,
                comp_unit_price DOUBLE,
                total_price DOUBLE,
                labor_fee DOUBLE,
                is_active INTEGER DEFAULT 1,
                flag_outlier INTEGER DEFAULT 0,
                flag_code_error INTEGER DEFAULT 0,
                price_base_year INTEGER DEFAULT 2020,
                price_adjust_factor DOUBLE DEFAULT 1.0,
                comp_unit_price_adj DOUBLE,
                total_price_adj DOUBLE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_index (
                year INTEGER PRIMARY KEY,
                labor_index DOUBLE,
                material_index DOUBLE,
                adjustment_factor DOUBLE
            )
        """)
        
        # 插入默认价格指数（2020-2026）
        conn.execute("""
            INSERT OR REPLACE INTO price_index (year, labor_index, material_index, adjustment_factor) VALUES
            (2020, 100.0, 100.0, 1.0),
            (2021, 105.0, 103.0, 1.03),
            (2022, 108.0, 106.0, 1.06),
            (2023, 112.0, 108.0, 1.09),
            (2024, 115.0, 110.0, 1.12),
            (2025, 118.0, 112.0, 1.14),
            (2026, 120.0, 114.0, 1.16)
        """)
        
        # 多栋建筑支持：为旧表补充新增列
        conn.execute("ALTER TABLE project_meta ADD COLUMN IF NOT EXISTS building_count INTEGER DEFAULT 1")
        conn.execute("ALTER TABLE project_meta ADD COLUMN IF NOT EXISTS buildings_json VARCHAR")
        conn.execute("ALTER TABLE project_meta ADD COLUMN IF NOT EXISTS max_floor INTEGER")
        conn.execute("ALTER TABLE project_meta ADD COLUMN IF NOT EXISTS min_floor INTEGER")
        conn.execute("ALTER TABLE project_meta ADD COLUMN IF NOT EXISTS mixed_types BOOLEAN DEFAULT FALSE")

        print(f"[OK] DuckDB 数据库已初始化: {db_path}")
        
        # 打印表结构
        tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
        for (table_name,) in tables:
            cols = conn.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table_name}'").fetchall()
            print(f"  表 {table_name}: {len(cols)} 列")
        
        return db_path
    finally:
        conn.close()


if __name__ == '__main__':
    init_database()
