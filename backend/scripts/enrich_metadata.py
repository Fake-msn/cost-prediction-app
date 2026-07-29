#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
元数据批量补全脚本
从表-01(工程计价总说明)中提取缺失的元数据字段
"""

import duckdb
import openpyxl
import re
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# 正则模式定义
PATTERNS = {
    'structure_type': [
        (r'框.*?剪.*?墙', '框剪结构'),
        (r'剪力墙结构', '框剪结构'),
        (r'框架结构', '框架结构'),
        (r'砖混结构', '砖混结构'),
        (r'钢结构', '钢结构'),
    ],
    'decoration': [
        (r'精装修', '精装修'),
        (r'精装', '精装修'),
        (r'简装', '简装修'),
        (r'毛坯', '毛坯'),
    ],
    'foundation': [
        (r'筏板基础', '筏板基础'),
        (r'筏.*?基础', '筏板基础'),
        (r'桩.*?基础', '桩基础'),
        (r'独立基础', '独立基础'),
        (r'条.*?基础', '条形基础'),
    ],
    'year_from_quota': [
        (r'09定额', 2012),
        (r'15定额', 2017),
        (r'20定额', 2021),
    ],
}


def extract_floors(text: str) -> Tuple[Optional[int], Optional[int]]:
    """提取地上层数和地下层数"""
    above = re.findall(r'(\d+)\s*层', text)
    above_max = max([int(x) for x in above]) if above else None

    under = re.findall(r'[地底]下?\s*(\d+)\s*层', text)
    under_max = max([int(x) for x in under]) if under else None

    return above_max, under_max


def extract_field(text: str, pattern_list: list) -> Optional[str]:
    """从文本中提取字段"""
    for pattern, value in pattern_list:
        if re.search(pattern, text):
            return value
    return None


def extract_year(text: str) -> Optional[int]:
    """从文本中提取建造年份"""
    for pattern, year in PATTERNS['year_from_quota']:
        if re.search(pattern, text):
            return year

    years = re.findall(r'(20\d{2})年', text)
    if years:
        return max([int(y) for y in years])

    return None


def find_table_01_sheet(wb) -> Optional[str]:
    """查找表-01工作表"""
    for sheet_name in wb.sheetnames:
        if '表-01' in sheet_name or '表-01' in sheet_name:
            return sheet_name
        if sheet_name.startswith('D ') and '工程计价总说明' in sheet_name:
            return sheet_name
    return None


def read_sheet_text(wb, sheet_name: str) -> str:
    """读取工作表的文本内容"""
    ws = wb[sheet_name]
    text_parts = []
    for row in ws.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                text_parts.append(str(cell))
    return '\n'.join(text_parts)


def find_xlsx_file(source_file: str, project_name: str, template_dir: Path) -> Optional[Path]:
    """在模板目录中查找对应的xlsx文件
    
    匹配策略:
    1. 先按source_file精确匹配
    2. 再按project_name在文件夹名中查找
    """
    # 策略1: 按source_file精确匹配
    for project_dir in template_dir.iterdir():
        if project_dir.is_dir():
            for xlsx_file in project_dir.glob('*.xlsx'):
                if xlsx_file.name == source_file:
                    return xlsx_file
    
    # 策略2: 按project_name匹配(文件夹名通常以数字前缀+项目名组成)
    if project_name:
        for project_dir in template_dir.iterdir():
            if project_dir.is_dir():
                # 检查项目名是否在文件夹名中
                if project_name in project_dir.name:
                    # 找到对应的xlsx文件
                    for xlsx_file in project_dir.glob('*.xlsx'):
                        return xlsx_file
    
    return None


def infer_from_name(name: str) -> Dict[str, Any]:
    """从项目名称推断元数据"""
    result = {}

    if '框架' in name:
        result['structure_type'] = '框架结构'
    elif '剪力墙' in name or '框剪' in name:
        result['structure_type'] = '框剪结构'
    elif '砖混' in name:
        result['structure_type'] = '砖混结构'
    elif '钢结构' in name:
        result['structure_type'] = '钢结构'

    if '精装' in name:
        result['decoration_standard'] = '精装修'
    elif '简装' in name:
        result['decoration_standard'] = '简装修'
    elif '毛坯' in name:
        result['decoration_standard'] = '毛坯'

    return result


def enrich_metadata(db_path: str, template_dir: str):
    """批量补全元数据"""
    template_path = Path(template_dir)

    conn = duckdb.connect(db_path)

    # 检查并添加缺失的列
    existing_cols = [row[0] for row in conn.execute('DESCRIBE project_meta').fetchall()]

    new_columns = {
        'decoration_standard': 'VARCHAR',
        'foundation_type': 'VARCHAR',
        'above_ground_floors': 'INTEGER',
        'under_ground_floors': 'INTEGER',
    }

    for col_name, col_type in new_columns.items():
        if col_name not in existing_cols:
            print(f"添加列: {col_name}")
            conn.execute(f'ALTER TABLE project_meta ADD COLUMN {col_name} {col_type}')

    # 获取所有项目 (用 dict 方便处理)
    projects = conn.execute('''
        SELECT project_id, name, source_file, structure_type, build_year,
               decoration_standard, foundation_type, above_ground_floors, under_ground_floors
        FROM project_meta
    ''').fetchall()

    col_names = ['project_id', 'name', 'source_file', 'structure_type', 'build_year',
                 'decoration_standard', 'foundation_type', 'above_ground_floors', 'under_ground_floors']

    print(f"\n总共 {len(projects)} 个项目")

    stats = {k: 0 for k in list(new_columns.keys()) + ['structure_type', 'build_year']}
    extracted_count = 0
    inferred_count = 0
    failed_count = 0

    for row in projects:
        proj = dict(zip(col_names, row))
        project_id = proj['project_id']
        name = proj['name']
        source_file = proj['source_file']

        updates = {}
        source_label = None  # 'extracted' or 'inferred'

        xlsx_path = find_xlsx_file(source_file, name, template_path)

        parsed_from_sheet = False

        if xlsx_path and xlsx_path.exists():
            try:
                wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
                sheet_name = find_table_01_sheet(wb)

                if sheet_name:
                    text = read_sheet_text(wb, sheet_name)

                    # 结构类型
                    if not proj['structure_type']:
                        val = extract_field(text, PATTERNS['structure_type'])
                        if val:
                            updates['structure_type'] = val

                    # 建造年份
                    if not proj['build_year']:
                        val = extract_year(text)
                        if val:
                            updates['build_year'] = val

                    # 装修标准
                    if not proj['decoration_standard']:
                        val = extract_field(text, PATTERNS['decoration'])
                        if val:
                            updates['decoration_standard'] = val

                    # 基础类型
                    if not proj['foundation_type']:
                        val = extract_field(text, PATTERNS['foundation'])
                        if val:
                            updates['foundation_type'] = val

                    # 层数
                    if not proj['above_ground_floors'] or not proj['under_ground_floors']:
                        above, under = extract_floors(text)
                        if above and not proj['above_ground_floors']:
                            updates['above_ground_floors'] = above
                        if under and not proj['under_ground_floors']:
                            updates['under_ground_floors'] = under

                    if updates:
                        source_label = 'extracted'
                        parsed_from_sheet = True

                wb.close()

            except Exception as e:
                print(f"  [WARN] 处理 {project_id} ({source_file}) 时出错: {e}")

        # 如果未能从表-01提取，尝试从名称推断
        if not parsed_from_sheet:
            inferred = infer_from_name(name)
            for field, value in inferred.items():
                if not proj.get(field):
                    updates[field] = value
            if updates:
                source_label = 'inferred'

        # 更新数据库
        if updates:
            set_clauses = []
            params = []

            for field, value in updates.items():
                set_clauses.append(f'{field} = ?')
                params.append(value)
                stats[field] = stats.get(field, 0) + 1

            if source_label:
                set_clauses.append('field_source = ?')
                params.append(source_label)

            params.append(project_id)

            sql = f"UPDATE project_meta SET {', '.join(set_clauses)} WHERE project_id = ?"
            conn.execute(sql, params)

            if source_label == 'extracted':
                extracted_count += 1
            else:
                inferred_count += 1
        else:
            failed_count += 1

    # 更新 metadata_completeness
    conn.execute('''
        UPDATE project_meta 
        SET metadata_completeness = (
            (CASE WHEN structure_type IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN build_year IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN decoration_standard IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN foundation_type IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN above_ground_floors IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN under_ground_floors IS NOT NULL THEN 1 ELSE 0 END) / 6.0
        )
    ''')

    conn.commit()
    conn.close()

    # 打印统计
    print("\n=== 元数据补全统计 ===")
    print(f"从表-01提取: {extracted_count} 个项目")
    print(f"从名称推断: {inferred_count} 个项目")
    print(f"未能补全: {failed_count} 个项目")
    print("\n各字段补全数量:")
    for field, count in stats.items():
        print(f"  {field}: {count}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='元数据批量补全')
    parser.add_argument('--source', type=str, required=True, help='模板数据目录')
    parser.add_argument('--db', type=str, default='data/cost_prediction.duckdb', help='数据库路径')

    args = parser.parse_args()

    enrich_metadata(args.db, args.source)
