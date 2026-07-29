#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DuckDB 迁移脚本
将 data/real_training_data.xlsx 中的数据迁移到 DuckDB

流程:
1. 读取 Excel 训练数据
2. 导入项目级数据到 project_meta
3. 对每个项目（如有原始xlsx）运行 extract_boq.py 填充 boq_items
4. 运行验证检查
5. 输出迁移统计报告
"""
import os
import sys
import hashlib
from datetime import date
from typing import Dict, List

import pandas as pd
import duckdb

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scripts.init_duckdb import init_database


# === 常量 ===

EXCEL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'real_training_data.xlsx')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cost_prediction.duckdb')

# 字段映射: Excel列名 -> DuckDB列名
FIELD_MAP = {
    '项目名称': 'name',
    '建筑类型': 'building_type',
    '结构类型': 'structure_type',
    '所在地区': 'location',
    '建造年份': 'build_year',
    '总建筑面积': 'total_area',
    '项目总造价': 'total_cost',
    '单方造价': 'unit_price',
}

# 质量等级映射
QUALITY_MAP = {
    ('A', 'high'): 'A',
    ('B', 'medium'): 'B',
    ('C', 'low'): 'C',
}


def generate_project_id(name: str, index: int) -> str:
    """生成稳定的项目ID"""
    raw = f"{name}_{index}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def migrate_excel_to_duckdb(excel_path: str, db_path: str = None) -> Dict:
    """
    将 Excel 训练数据迁移到 DuckDB
    
    Returns: 迁移统计信息
    """
    if db_path is None:
        db_path = DB_PATH
    
    # 确保数据库已初始化
    if not os.path.exists(db_path):
        print("[INFO] 初始化 DuckDB 数据库...")
        init_database(db_path)
    
    # 读取 Excel
    if not os.path.exists(excel_path):
        return {'success': False, 'error': f'Excel文件不存在: {excel_path}'}
    
    print(f"[INFO] 读取 Excel: {excel_path}")
    df = pd.read_excel(excel_path, engine='openpyxl')
    print(f"[INFO] 共 {len(df)} 条项目记录")
    
    # 连接数据库
    conn = duckdb.connect(db_path)
    
    stats = {
        'success': True,
        'total_records': len(df),
        'migrated': 0,
        'skipped': 0,
        'errors': [],
        'by_type': {},
        'by_region': {},
        'by_quality': {},
    }
    
    try:
        for idx, row in df.iterrows():
            try:
                project_id = generate_project_id(str(row.get('项目名称', '')), idx)
                
                # 确定质量等级
                source_type = str(row.get('source_type', 'C'))
                confidence = str(row.get('data_confidence', 'low'))
                quality_grade = QUALITY_MAP.get((source_type, confidence), 'C')
                
                # 计算元数据完整度
                required_fields = ['项目名称', '建筑类型', '结构类型', '总建筑面积', 
                                   '项目总造价', '单方造价']
                filled = sum(1 for f in required_fields if pd.notna(row.get(f)))
                metadata_completeness = filled / len(required_fields)
                
                # 计算训练权重
                weight_map = {'A': 1.0, 'B': 0.7, 'C': 0.5}
                training_weight = weight_map.get(quality_grade, 0.5)
                
                # 置信度
                conf_map = {'high': 0.9, 'medium': 0.7, 'low': 0.5}
                confidence_val = conf_map.get(confidence, 0.5)
                
                # 插入 project_meta
                conn.execute("""
                    INSERT OR REPLACE INTO project_meta
                    (project_id, name, building_type, structure_type, location,
                     build_year, total_area, total_cost, unit_price, source_file,
                     extraction_date, data_quality_grade, metadata_completeness,
                     training_weight, confidence, field_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    project_id,
                    str(row.get('项目名称', '')),
                    str(row.get('建筑类型', '')),
                    str(row.get('结构类型', '')),
                    str(row.get('所在地区', '')),
                    int(row.get('建造年份', 2023)) if pd.notna(row.get('建造年份')) else 2023,
                    float(row.get('总建筑面积', 0)) if pd.notna(row.get('总建筑面积')) else 0,
                    float(row.get('项目总造价', 0)) if pd.notna(row.get('项目总造价')) else 0,
                    float(row.get('单方造价', 0)) if pd.notna(row.get('单方造价')) else 0,
                    str(row.get('source_file', 'real_training_data.xlsx')),
                    date.today().isoformat(),
                    quality_grade,
                    metadata_completeness,
                    training_weight,
                    confidence_val,
                    'migrated_excel',
                ])
                
                stats['migrated'] += 1
                
                # 统计
                btype = str(row.get('建筑类型', '未知'))
                stats['by_type'][btype] = stats['by_type'].get(btype, 0) + 1
                
                region = str(row.get('所在地区', '未知'))
                stats['by_region'][region] = stats['by_region'].get(region, 0) + 1
                
                stats['by_quality'][quality_grade] = stats['by_quality'].get(quality_grade, 0) + 1
                
            except Exception as e:
                stats['skipped'] += 1
                stats['errors'].append(f"Row {idx}: {str(e)}")
        
        # 验证检查
        print("\n[验证] 运行数据验证...")
        
        # 检查记录数
        db_count = conn.execute("SELECT COUNT(*) FROM project_meta").fetchone()[0]
        print(f"  project_meta 记录数: {db_count}")
        
        # 检查空值
        null_checks = conn.execute("""
            SELECT 
                COUNT(*) - COUNT(name) as null_name,
                COUNT(*) - COUNT(building_type) as null_type,
                COUNT(*) - COUNT(total_area) as null_area,
                COUNT(*) - COUNT(total_cost) as null_cost
            FROM project_meta
        """).fetchone()
        
        if null_checks[0] > 0:
            print(f"  [WARN] {null_checks[0]} 条记录缺少项目名称")
        if null_checks[1] > 0:
            print(f"  [WARN] {null_checks[1]} 条记录缺少建筑类型")
        
        # 检查数值范围
        area_stats = conn.execute("""
            SELECT MIN(total_area), MAX(total_area), AVG(total_area)
            FROM project_meta WHERE total_area > 0
        """).fetchone()
        if area_stats[0]:
            print(f"  面积范围: {area_stats[0]:,.2f} ~ {area_stats[1]:,.2f} sqm, 均值: {area_stats[2]:,.2f}")
        
        cost_stats = conn.execute("""
            SELECT MIN(total_cost), MAX(total_cost), AVG(total_cost)
            FROM project_meta WHERE total_cost > 0
        """).fetchone()
        if cost_stats[0]:
            print(f"  造价范围: {cost_stats[0]:,.2f} ~ {cost_stats[1]:,.2f} 元, 均值: {cost_stats[2]:,.2f}")
        
        # 检查 boq_items (如果有)
        boq_count = conn.execute("SELECT COUNT(*) FROM boq_items").fetchone()[0]
        print(f"  boq_items 记录数: {boq_count}")
        
    finally:
        conn.close()
    
    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description='将Excel训练数据迁移到DuckDB')
    parser.add_argument('--input', default=EXCEL_PATH, help='输入Excel路径')
    parser.add_argument('--db-path', default=DB_PATH, help='DuckDB路径')
    args = parser.parse_args()
    
    print("=" * 60)
    print("DuckDB 迁移工具")
    print("=" * 60)
    
    stats = migrate_excel_to_duckdb(args.input, args.db_path)
    
    print("\n" + "=" * 60)
    print("迁移统计报告")
    print("=" * 60)
    
    if stats['success']:
        print(f"总记录数: {stats['total_records']}")
        print(f"成功迁移: {stats['migrated']}")
        print(f"跳过: {stats['skipped']}")
        
        if stats['by_type']:
            print(f"\n按建筑类型:")
            for t, c in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
                print(f"  {t}: {c}")
        
        if stats['by_region']:
            print(f"\n按地区:")
            for r, c in sorted(stats['by_region'].items(), key=lambda x: -x[1]):
                print(f"  {r}: {c}")
        
        if stats['by_quality']:
            print(f"\n按质量等级:")
            for q, c in sorted(stats['by_quality'].items()):
                print(f"  {q}: {c}")
        
        if stats['errors']:
            print(f"\n错误 ({len(stats['errors'])}):")
            for err in stats['errors'][:5]:
                print(f"  - {err}")
    else:
        print(f"[ERROR] {stats.get('error')}")


if __name__ == '__main__':
    main()
