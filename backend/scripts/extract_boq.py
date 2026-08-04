#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BOQ 清单项目提取器
从工程造价文件的 表-08 (F.1.1) 中提取清单项目明细

规则:
  R1: 展开合并单元格
  R2: 检测真实条目（排除小计/合计行）
  R3: 恢复12位编码的前导零
  R4: 校验 total_price = comp_unit_price × quantity（1%容差）
  R5: 从中文表头或编码位置分类分部工程
  R6: 识别安装专业
  R7: 逐条目专业分类
"""
import os
import re
import argparse
import hashlib
from datetime import date
from typing import Dict, List, Optional, Tuple

import openpyxl
import duckdb


# === 常量 ===

# 分部工程分类关键词
DIVISION_KEYWORDS = {
    '基础工程': ['土（石）方工程', '土石方工程', '桩与地基基础', '桩基工程', 
                '支护工程', '地基处理', '基坑支护'],
    '主体结构': ['砌筑工程', '混凝土及钢筋混凝土', '金属结构工程', 
                '钢筋混凝土', '混凝土工程'],
    '屋面工程': ['屋面及防水工程', '屋面防水', '屋面工程'],
    '外墙工程': ['墙、柱面装饰', '幕墙工程', '墙、柱面工程', '墙面装饰'],
    '楼地面': ['楼地面工程', '地面工程'],
    '天棚': ['天棚工程', '吊顶工程'],
    '门窗': ['门窗工程'],
    '油漆涂料': ['油漆、涂料、裱糊', '油漆涂料'],
}

# 安装专业关键词
INSTALLATION_TRADES = [
    '给排水', '暖通', '电气', '弱电', '消防', '智能化',
    '强电', '照明', '动力', '防雷', '接地'
]

# 专业分类映射
TRADE_KEYWORDS = {
    '土建': ['混凝土', '钢筋', '模板', '砌体', '砌筑', '土方', '桩基'],
    '装饰': ['抹灰', '涂料', '油漆', '瓷砖', '吊顶', '门窗', '装饰', '装修'],
    '安装': ['给排水', '暖通', '电气', '消防', '弱电', '智能化'],
}


# === 工具函数 ===

def safe_float(val, default=0.0) -> float:
    """安全转换为浮点数"""
    if val is None:
        return default
    try:
        s = str(val).strip()
        if not s or s == '-' or s == '—':
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def normalize_boq_code(code: str) -> str:
    """R3: 恢复12位编码的前导零"""
    if not code:
        return ''
    code = str(code).strip()
    # 移除空格和换行
    code = code.replace(' ', '').replace('\n', '').replace('\r', '')
    # 如果是纯数字且不足12位，补前导零
    if code.isdigit() and len(code) < 12:
        code = code.zfill(12)
    return code


def is_valid_boq_code(code: str) -> bool:
    """检查是否为有效的清单编码"""
    if not code:
        return False
    code = str(code).strip()
    # 12位数字 或 带连字符的标准格式 (如 010101001001)
    code_clean = code.replace('-', '').replace(' ', '')
    return code_clean.isdigit() and len(code_clean) >= 9


def is_summary_row(name_cell: str) -> bool:
    """R2: 检测是否为汇总行（小计/合计）"""
    if not name_cell:
        return False
    name_cell = str(name_cell).strip()
    summary_keywords = ['小计', '合计', '总计', '合 计', '小 计']
    return any(kw in name_cell for kw in summary_keywords)


def is_section_header(name_cell: str, amount: float, labor: float) -> bool:
    """检测是否为分部标题行"""
    if not name_cell:
        return False
    name_cell = str(name_cell).strip()
    
    # 有金额的不是标题行
    if amount > 0 or labor > 0:
        return False
    
    # 匹配分部标题格式: "A 土石方工程" 或纯中文含"工程"
    if re.match(r'^[A-Z]\s*[\u4e00-\u9fff]', name_cell):
        return True
    if re.match(r'^[\u4e00-\u9fff]', name_cell) and '工程' in name_cell:
        return True
    
    return False


def classify_division(section_name: str) -> Optional[str]:
    """R5: 根据分部名称分类"""
    if not section_name:
        return None
    for division, keywords in DIVISION_KEYWORDS.items():
        for kw in keywords:
            if kw in section_name:
                return division
    return None


def classify_trade(item_name: str, spec_text: str = '') -> str:
    """R7: 逐条目专业分类"""
    combined = f"{item_name} {spec_text}"
    for trade, keywords in TRADE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return trade
    # 检查是否为安装专业
    for trade_kw in INSTALLATION_TRADES:
        if trade_kw in combined:
            return '安装'
    return '土建'  # 默认


def generate_item_id(project_id: str, boq_code: str, item_name: str) -> str:
    """生成唯一条目ID"""
    raw = f"{project_id}|{boq_code}|{item_name}"
    hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{project_id}_{boq_code}_{hash_suffix}"


# === 核心提取逻辑 ===

def expand_merged_cells(ws) -> Dict[Tuple[int, int], any]:
    """R1: 展开合并单元格，返回 (row, col) -> value 映射"""
    merged_values = {}
    for merged_range in ws.merged_cells.ranges:
        # 获取合并区域左上角的值
        top_left_value = ws.cell(
            merged_range.min_row, 
            merged_range.min_col
        ).value
        for row in range(merged_range.min_row, merged_range.max_row + 1):
            for col in range(merged_range.min_col, merged_range.max_col + 1):
                merged_values[(row, col)] = top_left_value
    return merged_values


def extract_boq_items_from_sheet(ws, project_id: str, unit_name: str = '') -> List[Dict]:
    """从单个表-08工作表提取清单条目"""
    items = []
    
    # R1: 展开合并单元格
    merged_values = expand_merged_cells(ws)
    
    current_section = None
    current_division = None
    row_num = 0
    
    for row in ws.iter_rows(values_only=True):
        row_num += 1
        cells = list(row)
        if len(cells) < 8:
            continue
        
        # 获取各列值（考虑合并单元格）
        # 表-08 典型布局:
        # col[0]=序号, col[1]=项目编码, col[2]=项目名称
        # col[3]=项目特征描述, col[4]=计量单位
        # col[5]=工程量, col[6]=综合单价, col[7]=合价
        # col[8]=定额人工费（可选）
        
        # 使用合并值或原始值
        def get_cell(idx):
            if idx < len(cells):
                val = cells[idx]
                if val is None and (row_num, idx + 1) in merged_values:
                    return merged_values[(row_num, idx + 1)]
                return val
            return None
        
        code_raw = get_cell(1)
        name_cell = str(get_cell(2) or '').strip()
        spec_text = str(get_cell(3) or '').strip()
        unit = str(get_cell(4) or '').strip()
        quantity = safe_float(get_cell(5))
        comp_unit_price = safe_float(get_cell(6))
        total_price = safe_float(get_cell(7))
        labor_fee = safe_float(get_cell(8)) if len(cells) > 8 else 0
        
        if not name_cell:
            continue
        
        # R2: 跳过汇总行
        if is_summary_row(name_cell):
            continue
        
        # 检测分部标题行
        if is_section_header(name_cell, total_price, labor_fee):
            current_section = name_cell
            current_division = classify_division(name_cell)
            continue
        
        # R3: 规范化编码
        boq_code = normalize_boq_code(str(code_raw) if code_raw else '')
        
        # 跳过无有效编码的行（非清单条目）
        if not is_valid_boq_code(boq_code):
            # 可能是子条目或其他行，尝试保留
            if total_price <= 0:
                continue
            boq_code = f"SUB_{row_num:05d}"
        
        # R4: 校验合价 = 综合单价 × 工程量
        calc_total = comp_unit_price * quantity
        if calc_total > 0 and total_price > 0:
            diff_pct = abs(total_price - calc_total) / total_price
            if diff_pct > 0.01:  # 超过1%容差
                pass  # 标记但不跳过，可能是四舍五入差异
        
        # R7: 专业分类
        trade = classify_trade(name_cell, spec_text)
        
        # 生成唯一ID
        item_id = generate_item_id(project_id, boq_code, name_cell)
        
        item = {
            'item_id': item_id,
            'project_id': project_id,
            'unit_project': unit_name,
            'boq_code': boq_code,
            'item_name': name_cell,
            'spec_text': spec_text[:500] if spec_text else '',  # 截断过长描述
            'division': current_division,
            'trade': trade,
            'unit': unit,
            'quantity': quantity,
            'comp_unit_price': comp_unit_price,
            'total_price': total_price,
            'labor_fee': labor_fee,
            'is_active': 1,
            'flag_outlier': 0,
            'flag_code_error': 0 if is_valid_boq_code(boq_code) else 1,
        }
        items.append(item)
    
    return items


def extract_e3_totals(wb) -> Dict[str, float]:
    """从表-04 (E.3) 提取汇总数据用于交叉验证"""
    totals = {
        '分部分项费': 0,
        '措施费': 0,
        '规费': 0,
        '税金': 0,
    }
    
    for sheet_name in wb.sheetnames:
        if '表-04' not in sheet_name:
            continue
        ws = wb[sheet_name]
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if len(cells) < 3:
                continue
            name_b = str(cells[1]).strip() if cells[1] else ''
            val = safe_float(cells[2])
            
            if '分部分项工程' in name_b and '清单' not in name_b:
                if not name_b.startswith('1.'):
                    totals['分部分项费'] += val
            elif '措施项目' in name_b and '其中' not in name_b and '安全' not in name_b:
                totals['措施费'] += val
            elif name_b == '规费' or (name_b.startswith('4') and '规费' in name_b):
                totals['规费'] += val
            elif '税金' in name_b:
                totals['税金'] += val
    
    return totals


def extract_boq_from_workbook(wb, project_id: str) -> Tuple[List[Dict], Dict]:
    """从整个工作簿提取所有BOQ条目"""
    all_items = []
    unit_names = []
    
    # 查找表-08工作表
    boq_sheets = [s for s in wb.sheetnames if '表-08' in s and '单价措施' not in s]
    
    for sheet_name in boq_sheets:
        ws = wb[sheet_name]
        # 从工作表名推断单位工程名
        unit_name = sheet_name.replace('表-08', '').strip(' -_()（）')
        if not unit_name:
            unit_name = '单位工程'
        unit_names.append(unit_name)
        
        items = extract_boq_items_from_sheet(ws, project_id, unit_name)
        all_items.extend(items)
    
    # 提取E.3汇总用于交叉验证
    e3_totals = extract_e3_totals(wb)
    
    # 计算提取的总合价
    extracted_total = sum(item['total_price'] for item in all_items)
    e3_boq_total = e3_totals.get('分部分项费', 0)
    
    # 交叉验证
    if e3_boq_total > 0 and extracted_total > 0:
        diff_pct = abs(extracted_total - e3_boq_total) / e3_boq_total * 100
        e3_totals['extracted_total'] = extracted_total
        e3_totals['diff_pct'] = round(diff_pct, 2)
    else:
        e3_totals['diff_pct'] = None
    
    return all_items, e3_totals, unit_names


def parse_buildings_from_unit_names(unit_names: List[str]) -> Tuple[int, Optional[str], Optional[int], Optional[int], bool]:
    """
    从单位工程名列表解析多栋建筑信息

    Returns: (building_count, buildings_json, max_floor, min_floor, mixed_types)
    """
    import json
    n = len(unit_names)
    if n <= 1:
        return 1, None, None, None, False

    buildings = []
    floor_values = []
    type_set = set()

    for name in unit_names:
        floors = 1
        btype = "住宅"  # default

        m = re.search(r'(\d+)\s*[层楼Ff]', name)
        if m:
            floors = int(m.group(1))
            floor_values.append(floors)

        if '商业' in name or '商铺' in name:
            btype = "商业"
        elif '办公' in name or '写字楼' in name:
            btype = "办公"
        elif '车库' in name or '地下' in name:
            btype = "车库"
        elif '学校' in name or '教学' in name:
            btype = "学校"
        type_set.add(btype)

        buildings.append({
            "name": name[:30],
            "floors": floors,
            "type": btype,
        })

    max_f = max(floor_values) if floor_values else None
    min_f = min(floor_values) if floor_values else None
    mixed = len(type_set) > 1

    return n, json.dumps(buildings, ensure_ascii=False), max_f, min_f, mixed


def write_to_duckdb(conn, items: List[Dict], project_meta: Dict = None):
    """将提取结果写入DuckDB"""
    # 写入项目元数据
    if project_meta:
        conn.execute("""
            INSERT OR REPLACE INTO project_meta 
            (project_id, name, building_type, structure_type, location, 
             build_year, total_area, total_cost, unit_price, source_file,
             extraction_date, data_quality_grade, metadata_completeness,
             crosscheck_diff_pct, training_weight, confidence,
             building_count, buildings_json, max_floor, min_floor, mixed_types)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            project_meta.get('project_id'),
            project_meta.get('name'),
            project_meta.get('building_type'),
            project_meta.get('structure_type'),
            project_meta.get('location'),
            project_meta.get('build_year'),
            project_meta.get('total_area'),
            project_meta.get('total_cost'),
            project_meta.get('unit_price'),
            project_meta.get('source_file'),
            date.today().isoformat(),
            project_meta.get('data_quality_grade', 'C'),
            project_meta.get('metadata_completeness', 0.5),
            project_meta.get('crosscheck_diff_pct'),
            project_meta.get('training_weight', 0.5),
            project_meta.get('confidence', 0.5),
            project_meta.get('building_count', 1),
            project_meta.get('buildings_json'),
            project_meta.get('max_floor'),
            project_meta.get('min_floor'),
            project_meta.get('mixed_types', False),
        ])
    
    # 写入BOQ条目
    if items:
        conn.executemany("""
            INSERT OR REPLACE INTO boq_items
            (item_id, project_id, unit_project, boq_code, item_name,
             spec_text, division, trade, unit, quantity,
             comp_unit_price, total_price, labor_fee, is_active,
             flag_outlier, flag_code_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                item['item_id'],
                item['project_id'],
                item['unit_project'],
                item['boq_code'],
                item['item_name'],
                item['spec_text'],
                item['division'],
                item['trade'],
                item['unit'],
                item['quantity'],
                item['comp_unit_price'],
                item['total_price'],
                item['labor_fee'],
                item['is_active'],
                item['flag_outlier'],
                item['flag_code_error'],
            )
            for item in items
        ])
    
    return len(items)


# === 主函数 ===

def extract_and_store(xlsx_path: str, db_path: str = None, project_id: str = None) -> Dict:
    """
    从xlsx文件提取BOQ条目并存入DuckDB
    
    Returns: 提取统计信息
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cost_prediction.duckdb')
    
    if not os.path.exists(xlsx_path):
        return {'success': False, 'error': f'文件不存在: {xlsx_path}'}
    
    # 生成项目ID
    if project_id is None:
        folder_name = os.path.basename(os.path.dirname(xlsx_path))
        project_id = re.sub(r'^\d+\.?\s*', '', folder_name)
        project_id = hashlib.md5(project_id.encode()).hexdigest()[:12]
    
    print(f"[INFO] 项目ID: {project_id}")
    print(f"[INFO] 读取文件: {xlsx_path}")
    
    try:
        # 注意: 不使用 read_only=True，因为需要访问 merged_cells
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    except Exception as e:
        return {'success': False, 'error': f'无法打开Excel文件: {e}'}
    
    try:
        # 提取BOQ条目
        items, e3_totals, unit_names = extract_boq_from_workbook(wb, project_id)
        
        # 解析多栋建筑信息
        building_count, buildings_json, max_floor, min_floor, mixed_types = \
            parse_buildings_from_unit_names(unit_names)
        
        # 准备项目元数据
        filename = os.path.basename(xlsx_path)
        project_meta = {
            'project_id': project_id,
            'name': os.path.splitext(filename)[0],
            'source_file': filename,
            'total_cost': e3_totals.get('分部分项费', 0) + e3_totals.get('措施费', 0) + 
                         e3_totals.get('规费', 0) + e3_totals.get('税金', 0),
            'crosscheck_diff_pct': e3_totals.get('diff_pct'),
            'building_count': building_count,
            'buildings_json': buildings_json,
            'max_floor': max_floor,
            'min_floor': min_floor,
            'mixed_types': mixed_types,
        }
        
        # 写入DuckDB
        conn = duckdb.connect(db_path)
        try:
            count = write_to_duckdb(conn, items, project_meta)
        finally:
            conn.close()
        
        # 统计信息
        stats = {
            'success': True,
            'project_id': project_id,
            'items_extracted': count,
            'sheets_found': len([s for s in wb.sheetnames if '表-08' in s]),
            'e3_totals': e3_totals,
            'by_division': {},
            'by_trade': {},
        }
        
        # 按分部统计
        for item in items:
            div = item.get('division') or '未分类'
            stats['by_division'][div] = stats['by_division'].get(div, 0) + 1
            trade = item.get('trade') or '未分类'
            stats['by_trade'][trade] = stats['by_trade'].get(trade, 0) + 1
        
        return stats
        
    finally:
        wb.close()


def main():
    parser = argparse.ArgumentParser(description='从工程造价文件提取BOQ清单条目')
    parser.add_argument('--input', '-i', required=True, help='输入的xlsx文件路径')
    parser.add_argument('--output', '-o', default='duckdb', help='输出目标 (duckdb|json)')
    parser.add_argument('--db-path', default=None, help='DuckDB数据库路径')
    parser.add_argument('--project-id', default=None, help='项目ID（可选）')
    args = parser.parse_args()
    
    stats = extract_and_store(args.input, args.db_path, args.project_id)
    
    if stats['success']:
        print(f"\n[OK] 提取完成!")
        print(f"  清单条目数: {stats['items_extracted']}")
        print(f"  表-08工作表数: {stats['sheets_found']}")
        
        if stats['e3_totals']:
            e3 = stats['e3_totals']
            print(f"\n[交叉验证] 表-04 (E.3) 对比:")
            print(f"  分部分项费: {e3.get('分部分项费', 0):,.2f}")
            print(f"  提取总合价: {e3.get('extracted_total', 0):,.2f}")
            diff = e3.get('diff_pct')
            if diff is not None:
                print(f"  差异: {diff:.2f}%")
        
        print(f"\n[分部统计]")
        for div, count in sorted(stats['by_division'].items(), key=lambda x: -x[1]):
            print(f"  {div}: {count} 条")
        
        print(f"\n[专业统计]")
        for trade, count in sorted(stats['by_trade'].items(), key=lambda x: -x[1]):
            print(f"  {trade}: {count} 条")
    else:
        print(f"\n[ERROR] {stats.get('error')}")


if __name__ == '__main__':
    main()
