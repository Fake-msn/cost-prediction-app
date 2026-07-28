#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工程造价预测AI项目 - 模板数据转换脚本
将 d:\工程造价预测AI项目模板 中的46个项目xlsx数据转换为仓库训练格式
增强版: 从表-02/03/04/08/11/13/21全面提取数据
"""

import os
import re
import argparse
import warnings
from pathlib import Path
import pandas as pd
import openpyxl

warnings.filterwarnings("ignore")

# === Constants ===

REQUIRED_FIELDS = [
    "项目名称", "建筑类型", "结构类型", "总建筑面积", "楼层数",
    "所在地区", "建造年份", "装修标准", "项目总造价", "单方造价"
]

OPTIONAL_FIELDS = [
    "人工费", "材料费", "机械费", "措施费",
    "企业管理费", "规费", "利润", "税金",
    "基础工程费", "主体结构费", "屋面工程费", "外墙工程费",
    "混凝土总用量", "钢筋总用量", "砌块总用量",
    "水泥总用量", "砂总用量", "碎石总用量",
    "防水卷材总用量", "模板总用量",
    "建筑工程费", "装饰工程费", "安装工程费",
    "清单项目数", "清单总合价", "暂列金额",
]

EXTRA_FIELDS = [
    "混凝土单方耗量",
    "基础工程费比例", "主体结构费比例", "屋面工程费比例", "外墙工程费比例", "人工费比例",
    "钢筋单方用量", "混凝土单方用量", "砌块单方用量",
    "source_type", "data_confidence"
]

ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS + EXTRA_FIELDS

BUILDING_TYPE_KEYWORDS = {
    "住宅": ["住宅", "居住", "安置", "小区", "公租房", "住房", "宿舍", "公寓", "棚户"],
    "商业建筑": ["商业", "商铺", "商场", "营业", "门店", "商业开发"],
    "办公楼": ["办公", "写字楼", "行政", "业务"],
    "学校": ["学校", "学院", "幼儿园", "教学", "教育", "文轩"],
    "医院": ["医院", "卫生", "医疗"],
    "工业建筑": ["厂房", "工业", "车间", "产业园", "产业"],
    "基础设施": ["基础设施", "道路", "桥梁", "管网", "市政"],
    "公共建筑": ["文化", "图书", "展览", "体育", "综合", "服务", "活动"]
}

VALID_BUILDING_TYPES = set(BUILDING_TYPE_KEYWORDS.keys())

STRUCTURE_TYPE_MAP = {
    "框架及剪力墙": "框剪结构",
    "框架剪力墙": "框剪结构",
    "框剪": "框剪结构",
    "框架结构": "框架结构",
    "框架": "框架结构",
    "砖混": "砖混结构",
    "钢结构": "钢结构",
    "剪力墙": "框剪结构",
}

VALID_STRUCTURE_TYPES = {"框架结构", "框剪结构", "砖混结构", "钢结构", "其他结构"}

DEFAULT_BUILDING_TYPE = "住宅"
DEFAULT_STRUCTURE_TYPE = "框架结构"
DEFAULT_REGION = "四川"
DEFAULT_YEAR = 2023
DEFAULT_DECORATION = "一般装修"
DEFAULT_FLOORS = 6
DEFAULT_AVG_UNIT_COST = 1500  # for estimating building area when not available

# 分部工程分类关键词
FOUNDATION_KW = ['土（石）方工程', '土石方工程', '桩与地基基础', '桩基工程', '支护工程',
                 '地基处理', '基坑支护']
STRUCTURE_KW = ['砌筑工程', '混凝土及钢筋混凝土', '金属结构工程', '钢筋混凝土',
                '混凝土工程']
ROOF_KW = ['屋面及防水工程', '屋面防水', '屋面工程']
EXTERIOR_KW = ['墙、柱面装饰', '幕墙工程', '墙、柱面工程', '墙面装饰']


# === Functions ===

def read_project_info(info_xlsx_path):
    """Read 项目信息.xlsx into a dict keyed by English field name."""
    result = {}
    try:
        wb = openpyxl.load_workbook(info_xlsx_path, read_only=True, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row and len(row) >= 4:
                english_name = row[3]  # Column D = English field name
                value = row[1]         # Column B = value
                if english_name and value is not None:
                    result[str(english_name).strip()] = value
        wb.close()
    except Exception as e:
        print(f"  [WARN] Failed to read project info {info_xlsx_path}: {e}")
    return result


def find_sheets_by_pattern(wb, pattern):
    """Find sheet names matching a pattern. wb is an openpyxl workbook."""
    return [s for s in wb.sheetnames if pattern in s]


def safe_float(val, default=0.0):
    """Safely convert a value to float."""
    if val is None:
        return default
    try:
        s = str(val).strip()
        if not s or s == '-' or s == '—':
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def extract_cost_from_02(wb):
    """从表-02提取总造价、安全文明施工费、规费。
    
    表-02布局: col[0]=序号, col[1]=名称, col[2]=造价, col[4]=安全文明施工费, col[5]=规费
    """
    result = {"total_cost": 0, "安全文明施工费_02": 0, "规费_02": 0}
    
    t02_sheets = find_sheets_by_pattern(wb, "表-02")
    if not t02_sheets:
        return result
    
    ws = wb[t02_sheets[0]]
    for row in ws.iter_rows(values_only=True):
        if not row or len(row) < 3:
            continue
        cell_a = str(row[0]).strip() if row[0] else ""
        
        # 合计行
        if "合" in cell_a and "计" in cell_a:
            val2 = safe_float(row[2]) if len(row) > 2 else 0
            val4 = safe_float(row[4]) if len(row) > 4 else 0
            result["total_cost"] = val2 if val2 > 0 else val4
            # 安全文明施工费 from col[4]
            if val4 > 0:
                result["安全文明施工费_02"] = val4
            # 规费 from col[5]
            val5 = safe_float(row[5]) if len(row) > 5 else 0
            if val5 > 0:
                result["规费_02"] = val5
            break
    
    return result


def extract_cost_from_04(wb):
    """从表-04提取分部分项费、措施费、规费、税金。"""
    result = {"分部分项费": 0, "措施费": 0, "规费": 0, "税金": 0}
    
    t04_sheets = find_sheets_by_pattern(wb, "表-04")
    for sheet_name in t04_sheets:
        ws = wb[sheet_name]
        for row in ws.iter_rows(values_only=True):
            if not row or len(row) < 3:
                continue
            cell_b = str(row[1]).strip() if row[1] else ""
            val = safe_float(row[2])
            
            if "分部分项工程" in cell_b and "清单" not in cell_b:
                if not cell_b.startswith("1."):
                    result["分部分项费"] += val
            elif "措施项目" in cell_b and "其中" not in cell_b and "安全" not in cell_b:
                result["措施费"] += val
            elif cell_b == "规费" or (cell_b.startswith("4") and "规费" in cell_b):
                result["规费"] += val
            elif "税金" in cell_b:
                result["税金"] += val
    
    return result


def _categorize_section(section_name):
    """根据分部名称返回分类key。"""
    if not section_name:
        return None
    for kw in FOUNDATION_KW:
        if kw in section_name:
            return '基础工程费'
    for kw in STRUCTURE_KW:
        if kw in section_name:
            return '主体结构费'
    for kw in ROOF_KW:
        if kw in section_name:
            return '屋面工程费'
    for kw in EXTERIOR_KW:
        if kw in section_name:
            return '外墙工程费'
    return None


def extract_section_costs_from_08(wb):
    """从表-08提取分部工程费和人工费。
    
    表-08布局: col[2]=项目名称, col[7]=合价, col[8]=定额人工费
    结构: 分部标题行(如'土石方工程') -> 数据行 -> 分部小计行
    分部小计行的col[7]是该分部的合价。
    """
    result = {
        '人工费': 0, '材料费': 0, '机械费': 0,
        '基础工程费': 0, '主体结构费': 0, '屋面工程费': 0, '外墙工程费': 0
    }
    
    for name in wb.sheetnames:
        if '表-08' not in name:
            continue
        # Skip 单价措施项目 sheets (different type)
        if '单价措施' in name:
            continue
        
        ws = wb[name]
        current_section = None  # Track current section header name
        
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if len(cells) < 3:
                continue
            
            name_cell = str(cells[2]).strip() if cells[2] else ""
            if not name_cell:
                continue
            
            amount = safe_float(cells[7]) if len(cells) > 7 else 0
            labor = safe_float(cells[8]) if len(cells) > 8 else 0
            
            # Check for 分部小计 row - categorize based on current_section
            if '小计' in name_cell:
                if current_section:
                    cat = _categorize_section(current_section)
                    if cat:
                        result[cat] += amount
                continue
            
            # Check for 合计 row
            if '合计' in name_cell:
                continue
            
            # Detect section headers: rows with Chinese text, no amount
            # e.g., "A 土石方工程", "砌筑工程", "桩与地基基础工程"
            if amount == 0 and labor == 0:
                # Section headers: starts with letter+space or pure Chinese, contains '工程'
                if re.match(r'^[A-Z]\s*[\u4e00-\u9fff]', name_cell) or \
                   (re.match(r'^[\u4e00-\u9fff]', name_cell) and '工程' in name_cell):
                    current_section = name_cell
                continue
            
            # Data rows: accumulate 人工费
            if labor > 0:
                result['人工费'] += labor
    
    return result


def extract_measure_fees_from_11(wb):
    """从表-11提取总价措施费明细（安全文明施工费等）。
    
    表-11布局: col[1]=项目名称, col[5]=金额(元)
    合计行: col[0]='合计', col[5]=总计
    """
    result = {'安全文明施工费': 0, '措施费_11': 0}
    
    for name in wb.sheetnames:
        if '表-11' not in name:
            continue
        ws = wb[name]
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if len(cells) < 6:
                continue
            
            name_cell = str(cells[1]).strip() if cells[1] else ""
            cell0 = str(cells[0]).strip() if cells[0] else ""
            amount = safe_float(cells[5]) if len(cells) > 5 else 0
            
            # 合计行
            if '合计' in cell0 or '合计' in name_cell:
                if amount > 0:
                    result['措施费_11'] = amount
                continue
            
            # 安全文明施工费 items
            if amount > 0 and name_cell:
                # 环境保护费, 文明施工费, 安全施工费, 临时设施 etc.
                if any(kw in name_cell for kw in ['环境保护', '文明施工', '安全施工',
                                                   '临时设施', '夜间施工', '冬季施工',
                                                   '雨季施工', '二次搬运']):
                    result['安全文明施工费'] += amount
    
    return result


def extract_fees_from_13(wb):
    """从表-13提取规费、税金明细。
    
    表-13布局: col[1]=项目名称, col[5]=金额(元)
    """
    result = {'规费_13': 0, '税金_13': 0}
    
    for name in wb.sheetnames:
        if '表-13' not in name:
            continue
        ws = wb[name]
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if len(cells) < 6:
                continue
            
            name_cell = str(cells[1]).strip() if cells[1] else ""
            amount = safe_float(cells[5]) if len(cells) > 5 else 0
            
            if not name_cell or amount <= 0:
                continue
            
            # 规费 (top-level)
            if name_cell == '规费' or name_cell == '规费\n':
                result['规费_13'] += amount
            # 税金/增值税
            elif '税金' in name_cell or '增值税' in name_cell:
                result['税金_13'] += amount
    
    return result


def extract_single_project_costs_from_03(wb):
    """从表-03提取单项工程费用分类（建筑/装饰/安装）。
    
    表-03布局: col[1]=名称, col[2]=造价, col[4]=安全文明施工费, col[5]=规费
    """
    result = {'建筑工程费': 0, '装饰工程费': 0, '安装工程费': 0}
    
    t03_sheets = find_sheets_by_pattern(wb, "表-03")
    if not t03_sheets:
        return result
    
    ws = wb[t03_sheets[0]]
    for row in ws.iter_rows(values_only=True):
        cells = list(row)
        if len(cells) < 3:
            continue
        
        name_cell = str(cells[1]).strip() if cells[1] else ""
        amount = safe_float(cells[2])
        
        if not name_cell or amount <= 0:
            continue
        
        # Skip summary rows
        if '合' in name_cell and '计' in name_cell:
            continue
        
        # Categorize by name
        if '建筑' in name_cell and ('工程' in name_cell or '土建' in name_cell):
            result['建筑工程费'] += amount
        elif '装饰' in name_cell or '装修' in name_cell:
            result['装饰工程费'] += amount
        elif '安装' in name_cell:
            result['安装工程费'] += amount
    
    return result


def extract_material_quantities_from_21(wb):
    """从表-21提取材料用量（混凝土、钢筋、砌块、水泥、砂、碎石、防水卷材、模板）。"""
    result = {
        "混凝土总用量": 0, "钢筋总用量": 0, "砌块总用量": 0,
        "水泥总用量": 0, "砂总用量": 0, "碎石总用量": 0,
        "防水卷材总用量": 0, "模板总用量": 0,
    }
    
    t21_sheets = find_sheets_by_pattern(wb, "表-21")
    for sheet_name in t21_sheets:
        ws = wb[sheet_name]
        for row in ws.iter_rows(values_only=True):
            if not row or len(row) < 4:
                continue
            name = str(row[1]).strip() if row[1] else ""
            qty = safe_float(row[3])
            
            if not name or qty <= 0:
                continue
            
            # 混凝土
            if "混凝土" in name or "砼" in name or "商砼" in name:
                result["混凝土总用量"] += qty
            # 钢筋
            elif ("钢筋" in name or "螺纹钢" in name or "圆钢" in name
                  or "HRB" in name.upper() or "HPB" in name.upper()
                  or "钢材" in name):
                result["钢筋总用量"] += qty
            # 砌块
            elif ("砌块" in name or "加气" in name):
                result["砌块总用量"] += qty
            # 水泥
            elif "水泥" in name:
                result["水泥总用量"] += qty
            # 砂
            elif "砂" in name and "砂" in name:
                # Avoid matching 防水卷材 etc.
                if "防水" not in name and "模板" not in name:
                    result["砂总用量"] += qty
            # 碎石/卵石
            elif "碎石" in name or "卵石" in name or "砾石" in name:
                result["碎石总用量"] += qty
            # 防水卷材
            elif "防水" in name and ("卷材" in name or "SBS" in name.upper() or "薄膜" in name):
                result["防水卷材总用量"] += qty
            # 模板
            elif "模板" in name:
                result["模板总用量"] += qty
    
    return result


def extract_boq_statistics_from_08(wb):
    """从表-08提取清单项目统计数据（项目数、总合价）。"""
    total_items = 0
    total_amount = 0
    for name in wb.sheetnames:
        if '表-08' not in name or '单价措施' in name:
            continue
        ws = wb[name]
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if len(cells) < 8:
                continue
            name_cell = str(cells[2]).strip() if cells[2] else ""
            amount = safe_float(cells[7]) if len(cells) > 7 else 0
            # Count data rows with positive amounts (skip headers/subtotals)
            if amount > 0 and name_cell and '小计' not in name_cell and '合计' not in name_cell:
                total_items += 1
                total_amount += amount
    return {
        '清单项目数': total_items,
        '清单总合价': total_amount,
    }


def extract_provisional_from_12(wb):
    """从表-12提取暂列金额和暂估价。"""
    provisional_sum = 0
    for name in wb.sheetnames:
        if '表-12' not in name:
            continue
        # Skip sub-tables (表-12-1, 表-12-3, 表-12-5)
        if '表-12-' in name:
            continue
        ws = wb[name]
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if len(cells) < 3:
                continue
            name_val = str(cells[1]).strip() if cells[1] else ''
            amount = safe_float(cells[2]) if len(cells) > 2 else 0
            if amount > 0 and ('暂列' in name_val or '暂估' in name_val):
                provisional_sum += amount
    return {'暂列金额': provisional_sum}


def infer_building_type(name, yetai=""):
    """Infer building type from project name and 业态描述."""
    combined = f"{yetai} {name}"
    for btype, keywords in BUILDING_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return btype
    return DEFAULT_BUILDING_TYPE


def infer_structure_type(raw_str):
    """Standardize structure type string."""
    if not raw_str:
        return DEFAULT_STRUCTURE_TYPE
    raw_str = str(raw_str).strip()
    if not raw_str:
        return DEFAULT_STRUCTURE_TYPE
    if raw_str in VALID_STRUCTURE_TYPES:
        return raw_str
    for key, value in STRUCTURE_TYPE_MAP.items():
        if key in raw_str:
            return value
    return DEFAULT_STRUCTURE_TYPE


def parse_floor_count(floor_str):
    """Parse floor count from strings like '1#2#楼23层，3#楼33层'."""
    if not floor_str:
        return DEFAULT_FLOORS
    floor_str = str(floor_str)
    matches = re.findall(r'(\d+)\s*层', floor_str)
    if matches:
        floors = [int(m) for m in matches]
        return max(floors)
    try:
        val = int(float(floor_str))
        if val > 0:
            return val
    except (ValueError, TypeError):
        pass
    return DEFAULT_FLOORS


def infer_region(address):
    """Extract region from address string."""
    if not address:
        return DEFAULT_REGION
    address = str(address).strip()
    regions = [
        "成都", "绵阳", "德阳", "宜宾", "泸州", "南充", "广元",
        "遂宁", "乐山", "达州", "眉山", "资阳", "雅安", "巴中",
        "自贡", "攀枝花", "内江", "广安", "凉山", "甘孜", "阿坝"
    ]
    for r in regions:
        if r in address:
            return f"{r}"
    if "四川" in address:
        return "四川"
    return DEFAULT_REGION


def clean_project_name(folder_name):
    """Remove leading number prefix from folder name."""
    name = re.sub(r'^\d+\.?\s*', '', folder_name)
    return name.strip()


def check_available_sheets(wb):
    """Check which key sheets are available in the workbook."""
    available = {"表-02": False, "表-03": False, "表-04": False,
                 "表-08": False, "表-11": False, "表-13": False, "表-21": False}
    for name in wb.sheetnames:
        for key in available:
            if key in name:
                available[key] = True
    return available


def extract_all_from_workbook(wb):
    """从已打开的workbook中提取所有数据。
    
    一次性调用所有提取函数，避免重复打开文件。
    Returns dict with all extracted fields.
    """
    result = {}
    
    # 表-02: 总造价、安全文明施工费、规费
    data_02 = extract_cost_from_02(wb)
    result["total_cost"] = data_02["total_cost"]
    
    # 表-04: 分部分项费、措施费、规费、税金
    data_04 = extract_cost_from_04(wb)
    
    # 表-08: 分部工程费、人工费
    data_08 = extract_section_costs_from_08(wb)
    result["人工费"] = data_08["人工费"]
    result["基础工程费"] = data_08["基础工程费"]
    result["主体结构费"] = data_08["主体结构费"]
    result["屋面工程费"] = data_08["屋面工程费"]
    result["外墙工程费"] = data_08["外墙工程费"]
    
    # 表-08: 清单项目统计
    boq_stats = extract_boq_statistics_from_08(wb)
    result["清单项目数"] = boq_stats["清单项目数"]
    result["清单总合价"] = boq_stats["清单总合价"]
    
    # 表-11: 措施费明细
    data_11 = extract_measure_fees_from_11(wb)
    
    # 表-12: 暂列金额
    provisional = extract_provisional_from_12(wb)
    result["暂列金额"] = provisional["暂列金额"]
    
    # 表-13: 规费、税金
    data_13 = extract_fees_from_13(wb)
    
    # 表-03: 单项工程分类
    data_03 = extract_single_project_costs_from_03(wb)
    
    # 表-21: 材料用量（扩展版）
    data_21 = extract_material_quantities_from_21(wb)
    
    # 合并措施费: 优先用表-11的，其次表-04的
    result["措施费"] = data_11["措施费_11"] if data_11["措施费_11"] > 0 else data_04["措施费"]
    
    # 安全文明施工费: 优先表-11明细合计, 其次表-02
    result["安全文明施工费"] = (data_11["安全文明施工费"] 
                                if data_11["安全文明施工费"] > 0 
                                else data_02["安全文明施工费_02"])
    
    # 规费: 优先表-13, 其次表-04, 最后表-02
    result["规费"] = (data_13["规费_13"] if data_13["规费_13"] > 0 
                      else (data_04["规费"] if data_04["规费"] > 0 
                            else data_02["规费_02"]))
    
    # 税金: 优先表-13, 其次表-04
    result["税金"] = data_13["税金_13"] if data_13["税金_13"] > 0 else data_04["税金"]
    
    # 分部分项费
    result["分部分项费"] = data_04["分部分项费"]
    
    # 材料用量（扩展版）
    result["混凝土总用量"] = data_21["混凝土总用量"]
    result["钢筋总用量"] = data_21["钢筋总用量"]
    result["砌块总用量"] = data_21["砌块总用量"]
    result["水泥总用量"] = data_21["水泥总用量"]
    result["砂总用量"] = data_21["砂总用量"]
    result["碎石总用量"] = data_21["碎石总用量"]
    result["防水卷材总用量"] = data_21["防水卷材总用量"]
    result["模板总用量"] = data_21["模板总用量"]
    
    # 单项工程分类（表-03）
    result["建筑工程费"] = data_03["建筑工程费"]
    result["装饰工程费"] = data_03["装饰工程费"]
    result["安装工程费"] = data_03["安装工程费"]
    
    return result


def convert_single_project(folder_path):
    """Convert a single project folder to repo training format dict.
    
    增强版: 打开workbook一次，提取所有sheet数据。
    """
    folder_name = os.path.basename(folder_path)
    project_name = clean_project_name(folder_name)
    
    # Find xlsx files
    xlsx_files = [f for f in os.listdir(folder_path)
                  if f.endswith('.xlsx') and not f.startswith('~')]
    info_files = [f for f in xlsx_files if '项目信息' in f]
    main_files = [f for f in xlsx_files if '项目信息' not in f]
    
    if not main_files:
        print(f"  [SKIP] No main xlsx found in {folder_name}")
        return None
    
    # === Determine source_type and confidence ===
    has_info = len(info_files) > 0
    
    # === Layer A: Read project info if available ===
    info = {}
    if info_files:
        info_path = os.path.join(folder_path, info_files[0])
        info = read_project_info(info_path)
    
    # === Open main workbook ONCE and extract everything ===
    main_path = os.path.join(folder_path, main_files[0])
    try:
        wb = openpyxl.load_workbook(main_path, read_only=True, data_only=True)
        all_data = extract_all_from_workbook(wb)
        available_sheets = check_available_sheets(wb)
        wb.close()
    except Exception as e:
        print(f"  [WARN] Failed to open/extract {main_path}: {e}")
        return None
    
    has_any_key_table = any(available_sheets.values())
    has_all_key_tables = all(available_sheets.values())
    
    if has_info:
        source_type = "A"
        data_confidence = "high"
    elif has_any_key_table:
        if has_all_key_tables or available_sheets.get("表-21", False):
            source_type = "B"
        else:
            source_type = "C"
        data_confidence = "medium" if source_type == "B" else "low"
    else:
        source_type = "C"
        data_confidence = "low"
    
    # === Merge results ===
    record = {}
    
    # 项目名称
    record["项目名称"] = info.get("name", project_name)
    
    # 建筑类型
    yetai = str(info.get("type", "")) if info.get("type") else ""
    record["建筑类型"] = infer_building_type(project_name, yetai)
    
    # 结构类型
    raw_structure = info.get("category_structure", "")
    record["结构类型"] = infer_structure_type(raw_structure)
    
    # 总建筑面积
    build_area = safe_float(info.get("build_area", 0))
    if build_area <= 0:
        total_cost = all_data["total_cost"]
        if total_cost > 0:
            build_area = total_cost / DEFAULT_AVG_UNIT_COST
        else:
            build_area = 0
    record["总建筑面积"] = round(build_area, 2)
    
    # 楼层数
    floor_str = info.get("above_ground_floors", "")
    record["楼层数"] = parse_floor_count(floor_str)
    
    # 所在地区
    address = info.get("address", "")
    record["所在地区"] = infer_region(address)
    
    # 建造年份
    record["建造年份"] = DEFAULT_YEAR
    
    # 装修标准
    decoration = info.get("decoration_situation", "")
    record["装修标准"] = str(decoration).strip() if decoration else DEFAULT_DECORATION
    
    # 项目总造价
    total_cost = all_data["total_cost"]
    if total_cost <= 0 and info.get("settlement_price"):
        total_cost = safe_float(info.get("settlement_price"))
    if total_cost <= 0 and info.get("sign_price"):
        total_cost = safe_float(info.get("sign_price"))
    record["项目总造价"] = round(total_cost, 2)
    
    # 单方造价
    unit_cost = safe_float(info.get("cost_unilateral", 0))
    if unit_cost <= 0 and build_area > 0 and total_cost > 0:
        unit_cost = total_cost / build_area
    record["单方造价"] = round(unit_cost, 2)
    
    # === Optional fields (enhanced extraction) ===
    record["人工费"] = round(all_data["人工费"], 2)
    record["材料费"] = 0  # Not directly extractable from current sheets
    record["机械费"] = 0  # Not directly extractable from current sheets
    record["措施费"] = round(all_data["措施费"], 2)
    record["企业管理费"] = 0
    record["规费"] = round(all_data["规费"], 2)
    record["利润"] = 0
    record["税金"] = round(all_data["税金"], 2)
    record["基础工程费"] = round(all_data["基础工程费"], 2)
    record["主体结构费"] = round(all_data["主体结构费"], 2)
    record["屋面工程费"] = round(all_data["屋面工程费"], 2)
    record["外墙工程费"] = round(all_data["外墙工程费"], 2)
    
    # Material quantities (expanded)
    record["混凝土总用量"] = round(all_data["混凝土总用量"], 2)
    record["钢筋总用量"] = round(all_data["钢筋总用量"], 2)
    record["砌块总用量"] = round(all_data["砌块总用量"], 2)
    record["水泥总用量"] = round(all_data["水泥总用量"], 2)
    record["砂总用量"] = round(all_data["砂总用量"], 2)
    record["碎石总用量"] = round(all_data["碎石总用量"], 2)
    record["防水卷材总用量"] = round(all_data["防水卷材总用量"], 2)
    record["模板总用量"] = round(all_data["模板总用量"], 2)
    
    # 单项工程分类（表-03）
    record["建筑工程费"] = round(all_data["建筑工程费"], 2)
    record["装饰工程费"] = round(all_data["装饰工程费"], 2)
    record["安装工程费"] = round(all_data["安装工程费"], 2)
    
    # P2: 清单项目统计、暂列金额
    record["清单项目数"] = all_data["清单项目数"]
    record["清单总合价"] = round(all_data["清单总合价"], 2)
    record["暂列金额"] = round(all_data["暂列金额"], 2)
    
    # 混凝土单方耗量
    if build_area > 0 and all_data["混凝土总用量"] > 0:
        record["混凝土单方耗量"] = round(all_data["混凝土总用量"] / build_area, 4)
    else:
        record["混凝土单方耗量"] = 0
    
    # === P3: Derived features ===
    total_cost_val = record["项目总造价"]
    
    # 分部工程费比例
    record["基础工程费比例"] = round(record["基础工程费"] / total_cost_val, 4) if total_cost_val > 0 else 0
    record["主体结构费比例"] = round(record["主体结构费"] / total_cost_val, 4) if total_cost_val > 0 else 0
    record["屋面工程费比例"] = round(record["屋面工程费"] / total_cost_val, 4) if total_cost_val > 0 else 0
    record["外墙工程费比例"] = round(record["外墙工程费"] / total_cost_val, 4) if total_cost_val > 0 else 0
    record["人工费比例"] = round(record["人工费"] / total_cost_val, 4) if total_cost_val > 0 else 0
    
    # 材料单方用量
    record["钢筋单方用量"] = round(record["钢筋总用量"] / build_area, 4) if build_area > 0 else 0
    record["混凝土单方用量"] = round(record["混凝土总用量"] / build_area, 4) if build_area > 0 else 0
    record["砌块单方用量"] = round(record["砌块总用量"] / build_area, 4) if build_area > 0 else 0
    
    # Source type and confidence
    record["source_type"] = source_type
    record["data_confidence"] = data_confidence
    
    # Log available sheets for debugging
    sheets_found = [k for k, v in available_sheets.items() if v]
    if sheets_found:
        print(f"  [SHEETS] {', '.join(sheets_found)}")
    
    return record


def convert_all(source_dir, output_path):
    """Batch convert all projects and output Excel."""
    source_dir = Path(source_dir)
    output_path = Path(output_path)
    
    if not source_dir.exists():
        print(f"[ERROR] Source directory not found: {source_dir}")
        return
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    subdirs = sorted([d for d in source_dir.iterdir() if d.is_dir()])
    print(f"Found {len(subdirs)} project directories in {source_dir}")
    
    records = []
    success_count = 0
    fail_count = 0
    
    for i, subdir in enumerate(subdirs):
        print(f"\n[{i+1}/{len(subdirs)}] Processing: {subdir.name}")
        try:
            record = convert_single_project(str(subdir))
            if record:
                records.append(record)
                success_count += 1
                print(f"  [OK] Cost: {record['项目总造价']:,.2f}, "
                      f"Area: {record['总建筑面积']:,.2f}, "
                      f"Type: {record['建筑类型']}, "
                      f"Source: {record['source_type']}, "
                      f"Confidence: {record['data_confidence']}")
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            print(f"  [FAIL] Error: {e}")
    
    if not records:
        print("[ERROR] No records were successfully converted!")
        return
    
    df = pd.DataFrame(records, columns=ALL_FIELDS)
    
    # === Validation ===
    print("\n=== Validation ===")
    for field in REQUIRED_FIELDS:
        null_count = df[field].isna().sum()
        if null_count > 0:
            print(f"  [WARN] {field} has {null_count} null values")
    
    invalid_types = df[~df["建筑类型"].isin(VALID_BUILDING_TYPES)]
    if len(invalid_types) > 0:
        print(f"  [WARN] {len(invalid_types)} records have invalid building type")
    
    invalid_struct = df[~df["结构类型"].isin(VALID_STRUCTURE_TYPES)]
    if len(invalid_struct) > 0:
        print(f"  [WARN] {len(invalid_struct)} records have invalid structure type, fixing...")
        df.loc[~df["结构类型"].isin(VALID_STRUCTURE_TYPES), "结构类型"] = DEFAULT_STRUCTURE_TYPE
    
    neg_cost = df[df["项目总造价"] <= 0]
    if len(neg_cost) > 0:
        print(f"  [WARN] {len(neg_cost)} records have zero/negative total cost")
    
    neg_area = df[df["总建筑面积"] <= 0]
    if len(neg_area) > 0:
        print(f"  [WARN] {len(neg_area)} records have zero/negative building area")
    
    # === Field fill rate report ===
    print("\n=== Field Fill Rates (Optional Fields) ===")
    for col in OPTIONAL_FIELDS:
        if col in df.columns:
            non_null = df[col].notna().sum()
            non_zero = (pd.to_numeric(df[col], errors='coerce') > 0).sum()
            pct = non_zero / len(df) * 100 if len(df) > 0 else 0
            print(f"  {col}: {non_zero}/{len(df)} non-zero ({pct:.1f}%)")
    
    # Write to Excel
    df.to_excel(str(output_path), index=False, engine="openpyxl")
    
    print(f"\n=== Summary ===")
    print(f"Total projects: {len(subdirs)}")
    print(f"Successfully converted: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Output written to: {output_path}")
    print(f"\nStatistics:")
    print(f"  Total cost range: {df['项目总造价'].min():,.2f} ~ {df['项目总造价'].max():,.2f}")
    print(f"  Building area range: {df['总建筑面积'].min():,.2f} ~ {df['总建筑面积'].max():,.2f}")
    print(f"  Unit cost range: {df['单方造价'].min():,.2f} ~ {df['单方造价'].max():,.2f}")
    print(f"  Building types: {df['建筑类型'].value_counts().to_dict()}")
    print(f"  Structure types: {df['结构类型'].value_counts().to_dict()}")
    if 'source_type' in df.columns:
        print(f"  Source types: {df['source_type'].value_counts().to_dict()}")
        print(f"  Data confidence: {df['data_confidence'].value_counts().to_dict()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="转换工程造价模板数据为训练格式")
    parser.add_argument("--source", default=r"d:\工程造价预测AI项目模板", help="模板数据目录")
    parser.add_argument("--output", default="data/real_training_data.xlsx", help="输出Excel路径")
    args = parser.parse_args()
    convert_all(args.source, args.output)
