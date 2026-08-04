"""
费用构成提取器 (Cost Breakdown Extractor)

从源 Excel 文件中提取项目级费用构成数据，写入 DuckDB project_cost_breakdown 表。
覆盖人工费、分部工程费（基础/主体/屋面/外墙）、专业工程费（建筑/装饰/安装）、
措施费、规费、税金等字段。

数据源优先级（人工费）：
  1. F.1.1 分部分项清单 c9 列（定额人工费）逐行加总
  2. H 表-13 反推：人工费 = 养老保险费 ÷ 费率
  3. 无法提取则标记为 None

数据源（分部费）：
  F.1.1 建筑工程 sheet → BOQ 编码前 4 位分组 → 聚合合价(c8)

数据源（专业费）：
  E.2 表-03 → 建筑工程/装饰工程/安装工程(sum of sub-items) 金额

数据源（措施/规费/税金）：
  E.3 表-04 → 措施项目/规费/税金 行

作者: 伯牙
日期: 2026-08-01
"""
import os
import re
import json
import logging
from typing import Dict, Optional, List, Tuple
from collections import defaultdict

import openpyxl
import duckdb

logger = logging.getLogger(__name__)

# ── GB50500 BOQ 编码 → 分部映射 ──
# 前4位编码：XXYY, XX=专业(01=建筑/02=装饰/03=安装), YY=分部
CODE_TO_DIVISION: Dict[str, str] = {
    # 建筑工程 (01xx)
    '0101': '基础工程',   # 土石方工程
    '0102': '基础工程',   # 地基处理与边坡支护
    '0103': '基础工程',   # 桩基工程
    '0104': '主体结构',   # 砌筑工程
    '0105': '主体结构',   # 混凝土及钢筋混凝土工程
    '0106': '主体结构',   # 金属结构工程
    '0107': '主体结构',   # 木结构工程
    '0108': '主体结构',   # 门窗工程
    '0109': '屋面工程',   # 屋面及防水工程
    '0110': '装饰工程',   # 防腐、隔热、保温工程
    '0111': '装饰工程',   # 楼地面装饰工程
    '0112': '外墙工程',   # 墙、柱面装饰与隔断、幕墙工程
    '0113': '装饰工程',   # 天棚工程
    '0114': '装饰工程',   # 油漆、涂料、裱糊工程
    '0115': '装饰工程',   # 其他装饰工程
    # 装饰装修工程 (02xx) — 部分可归入分部
    '0201': '装饰工程',   # 楼地面装饰
    '0202': '外墙工程',   # 墙、柱面装饰（装饰专业的外墙）
    '0203': '装饰工程',   # 天棚装饰
    '0204': '主体结构',   # 门窗装饰
    '0205': '装饰工程',   # 油漆涂料
    '0206': '装饰工程',   # 其他装饰
    # 补充编码
    '0116': '主体结构',   # 钢筋工程（部分地区标准）
    '0117': '主体结构',   # 模板工程
    '0118': '屋面工程',   # 防水工程变体
}

# 要聚合的分部类别
DIVISION_CATEGORIES = ['基础工程', '主体结构', '屋面工程', '外墙工程']

# ── 社保费率（用于 H 表反推人工费）──
# 四川 2015/2020 定额：养老保险费率 2.3415%（分部分项定额人工费+措施定额人工费）
PENSION_RATE = 0.023415


def normalize_project_name(name: str) -> str:
    """标准化项目名称，用于匹配"""
    name = name.strip()
    # 移除常见的后缀变体
    name = re.sub(r'\s+', '', name)
    name = re.sub(r'（', '(', name)
    name = re.sub(r'）', ')', name)
    return name


def find_source_excel(project_name: str, source_dir: str) -> Optional[str]:
    """根据项目名在源目录中查找对应的主 Excel 文件"""
    if not os.path.isdir(source_dir):
        return None

    norm_name = normalize_project_name(project_name)

    for entry in os.listdir(source_dir):
        entry_path = os.path.join(source_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        # 尝试匹配：项目文件夹名包含项目关键词
        # 提取项目名中的关键词（去掉数字序号前缀和标点）
        keywords = re.findall(r'[\u4e00-\u9fff]{3,}', project_name)
        entry_keywords = re.findall(r'[\u4e00-\u9fff]{3,}', entry)

        if not keywords or not entry_keywords:
            continue

        # 计算重叠的关键词
        # 降级阈值：至少 1 个长关键词 (≥4字) 匹配即可
        overlap = len(set(keywords) & set(entry_keywords))
        long_match = any(len(k) >= 4 and k in entry for k in keywords)
        if overlap >= min(2, len(keywords)) or (len(keywords) <= 3 and long_match):
            # 找到匹配的文件夹，在其中找主 Excel
            for fname in os.listdir(entry_path):
                if fname.endswith('.xlsx') and '项目信息' not in fname:
                    fpath = os.path.join(entry_path, fname)
                    return fpath

    return None


def _safe_float(val):
    """安全转换为 float，处理 str/None/数字 等类型"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def extract_from_e2(ws) -> Dict[str, float]:
    """从 E.2 单项工程汇总表提取 建筑工程/装饰工程/安装工程 金额"""
    result = {'建筑工程': 0.0, '装饰工程': 0.0, '安装工程': 0.0}
    install_sub_total = 0.0

    for row in ws.iter_rows(min_row=5, max_row=50, values_only=True):
        if row[1] is None or row[2] is None:
            continue

        eng_name = str(row[1]).strip()
        amount = _safe_float(row[2])

        if amount is None or amount == 0:
            continue

        if '建筑' in eng_name and '装饰' not in eng_name and '安装' not in eng_name:
            result['建筑工程'] += amount
        elif '建筑与装饰' in eng_name or '建筑及装饰' in eng_name:
            # 合并标签：归入建筑工程
            result['建筑工程'] += amount
        elif '装饰' in eng_name:
            result['装饰工程'] += amount
        else:
            install_sub_total += amount

    result['安装工程'] = install_sub_total
    return result


def extract_division_from_f11(ws) -> Tuple[Dict[str, float], float]:
    """从 F.1.1 分部分项清单提取分部费用和人工费

    Returns:
        (division_costs, labor_cost)
        division_costs: {'基础工程': xxx, '主体结构': xxx, ...}
        labor_cost: 定额人工费合计
    """
    division_totals = defaultdict(float)
    labor_total = 0.0
    unrecognized = 0.0

    for row in ws.iter_rows(min_row=8, values_only=True):
        seq = row[0]
        boq_code = row[1]
        total_price = row[7]  # c8 = 合价
        labor_fee = row[8]    # c9 = 定额人工费

        # 跳过非数据行（序号不是数字，或为分部标题行）
        if seq is None:
            continue
        if isinstance(seq, str) and not seq.strip().isdigit():
            continue

        # 需要有效的 BOQ 编码
        if not boq_code or not isinstance(boq_code, str):
            continue
        boq_code = boq_code.strip()

        # 聚合合价
        tp = _safe_float(total_price)
        if tp and tp != 0:
            prefix = boq_code[:4] if len(boq_code) >= 4 else boq_code
            division = CODE_TO_DIVISION.get(prefix, '其他')
            division_totals[division] += tp

        # 聚合人工费
        lf = _safe_float(labor_fee)
        if lf:
            labor_total += lf

    # 只返回我们关心的四个分部 + 其他
    result = {}
    for cat in DIVISION_CATEGORIES:
        result[cat] = round(division_totals.get(cat, 0.0), 2)
    result['其他'] = round(division_totals.get('其他', 0.0) + division_totals.get('装饰工程', 0.0), 2)

    return result, round(labor_total, 2)


def extract_from_e3(ws) -> Dict[str, float]:
    """从 E.3 单位工程报价汇总表提取 分部分项费/措施费/规费/税金"""
    result = {
        '分部分项工程费': 0.0,
        '措施费': 0.0,
        '规费': 0.0,
        '税金': 0.0,
    }

    for row in ws.iter_rows(min_row=4, max_row=25, values_only=True):
        if row[1] is None:
            continue
        label = str(row[1]).strip()
        amount = _safe_float(row[2])

        if amount is None:
            continue

        if '分部分项工程费' in label or label.startswith('分部分项'):
            result['分部分项工程费'] = float(amount)
        elif '措施项目' in label or label.startswith('措施'):
            result['措施费'] = float(amount)
        elif '规费' in label and '税金' not in label:
            result['规费'] = float(amount)
        elif '税金' in label:
            result['税金'] = float(amount)

    return result


def extract_labor_from_h13(ws) -> Optional[float]:
    """从 H 表-13 规费税金表反推人工费

    养老保险费 = (分部分项定额人工费 + 措施项目定额人工费) × 2.3415%
    人工费 = 养老保险费 / 0.023415
    """
    pension_amount = None

    for row in ws.iter_rows(min_row=4, max_row=30, values_only=True):
        if row[1] is None:
            continue
        label = str(row[1]).strip()
        amount = _safe_float(row[5])  # c6 = 金额

        if '养老保险' in label and amount is not None and amount > 0:
            pension_amount = float(amount)
            break

    if pension_amount:
        labor = pension_amount / PENSION_RATE
        return round(labor, 2)

    return None


def _concrete_price_to_grade(price: float) -> str:
    """混凝土价格 → 等级反推（四川地区价格体系）"""
    if price >= 450:
        return "C50"
    elif price >= 390:
        return "C40"
    elif price >= 350:
        return "C35"
    elif price >= 310:
        return "C30"
    else:
        return "C25"


def _steel_price_to_grade(price: float) -> str:
    """钢筋价格 → 等级反推"""
    if price >= 4500:
        return "HRB500"
    elif price >= 3700:
        return "HRB400"
    else:
        return "HRB335"


def extract_metadata_from_info_xlsx(project_dir: str) -> Dict[str, Optional[str]]:
    """从项目信息 Excel 提取结构化参数

    读取 项目信息.xlsx 的「项目基础信息」sheet，提取模型可用字段。
    混凝土/钢筋等级通过价格反推（如 320元→C30）。
    """
    result = {
        'foundation_type': None,
        'structure_type_detail': None,
        'pile_foundation_type': None,
        'seismic_grade': None,
        'earthwork_difficulty': None,
        'concrete_grade': None,
        'steel_grade': None,
    }
    field_map = {
        '基础类别': 'foundation_type',
        '结构类别': 'structure_type_detail',
        '桩基类别': 'pile_foundation_type',
        '抗震等级': 'seismic_grade',
        '土方处理难度': 'earthwork_difficulty',
    }
    # 价格→等级映射
    concrete_price = None
    steel_price = None

    if not os.path.isdir(project_dir):
        return result

    for fname in os.listdir(project_dir):
        if '项目信息' not in fname or not fname.endswith('.xlsx'):
            continue
        fpath = os.path.join(project_dir, fname)
        try:
            wb = openpyxl.load_workbook(fpath, read_only=True, data_only=True)
            if '项目基础信息' not in wb.sheetnames:
                wb.close()
                continue
            ws = wb['项目基础信息']
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0] is None:
                    continue
                key = str(row[0]).strip()
                if key in field_map:
                    val = str(row[1]).strip() if row[1] else None
                    if val and val.lower() not in ('none', '', '-', 'nan'):
                        result[field_map[key]] = val
                if key == '混凝土价格' and row[1]:
                    try:
                        concrete_price = float(row[1])
                    except (ValueError, TypeError):
                        pass
                if key == '钢筋价格' and row[1]:
                    try:
                        steel_price = float(row[1])
                    except (ValueError, TypeError):
                        pass
            wb.close()

            # 价格反推等级
            if concrete_price:
                result['concrete_grade'] = _concrete_price_to_grade(concrete_price)
            if steel_price:
                result['steel_grade'] = _steel_price_to_grade(steel_price)
            break  # 找到一个就够了
        except Exception:
            pass
    return result


def process_project(excel_path: str, project_name: str) -> Dict:
    """处理单个项目的 Excel，提取所有费用构成字段"""
    result = {
        'project_name': project_name,
        'source_file': excel_path,
        # 专业工程费 (E.2)
        '建筑工程费': 0.0,
        '装饰工程费': 0.0,
        '安装工程费': 0.0,
        # 分部工程费 (F.1.1 聚合)
        '基础工程费': 0.0,
        '主体结构费': 0.0,
        '屋面工程费': 0.0,
        '外墙工程费': 0.0,
        # 费用构成 (E.3)
        '分部分项工程费': 0.0,
        '措施费': 0.0,
        '规费': 0.0,
        '税金': 0.0,
        # 人工费
        '人工费': None,
        '人工费_source': None,
        # 元数据
        'e2_count': 0,
        'f11_arch_count': 0,
        'e3_count': 0,
        'h13_count': 0,
        'foundation_type': None,
        'errors': [],
    }

    if not excel_path or not os.path.exists(excel_path):
        result['errors'].append(f'文件不存在: {excel_path}')
        return result

    # 从项目信息 Excel 提取结构参数
    project_dir = os.path.dirname(excel_path)
    metadata = extract_metadata_from_info_xlsx(project_dir)
    result['foundation_type'] = metadata.get('foundation_type')
    result['concrete_grade'] = metadata.get('concrete_grade')
    result['steel_grade'] = metadata.get('steel_grade')

    try:
        wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    except Exception as e:
        result['errors'].append(f'无法打开 Excel: {e}')
        return result

    labor_f11_total = 0.0

    try:
        for sn in wb.sheetnames:
            ws = wb[sn]

            # ── E.2 单项工程汇总表 ──
            if '表-03' in sn and 'E.2' in sn:
                try:
                    e2_data = extract_from_e2(ws)
                    result['建筑工程费'] += e2_data['建筑工程']
                    result['装饰工程费'] += e2_data['装饰工程']
                    result['安装工程费'] += e2_data['安装工程']
                    result['e2_count'] += 1
                except Exception as e:
                    result['errors'].append(f'E.2 [{sn[:30]}]: {e}')

            # ── F.1.1 分部分项清单 ──
            elif '表-08' in sn and 'F.1.1' in sn:
                r2 = str(ws.cell(row=2, column=1).value or '')
                # 处理 建筑工程、装饰工程、建筑与装饰 三种类型
                is_arch = '建筑工程' in r2 or '建筑与装饰' in r2
                is_deco = '装饰工程' in r2
                if not (is_arch or is_deco):
                    continue
                try:
                    div_data, labor = extract_division_from_f11(ws)
                    for cat in DIVISION_CATEGORIES:
                        result[f'{cat}费'] += div_data.get(cat, 0.0)
                    labor_f11_total += labor
                    if is_arch:
                        result['f11_arch_count'] += 1
                except Exception as e:
                    result['errors'].append(f'F.1.1 [{sn[:30]}]: {e}')

            # ── E.3 单位工程报价汇总表 ──
            elif '表-04' in sn and 'E.3' in sn:
                try:
                    e3_data = extract_from_e3(ws)
                    result['分部分项工程费'] += e3_data['分部分项工程费']
                    result['措施费'] += e3_data['措施费']
                    result['规费'] += e3_data['规费']
                    result['税金'] += e3_data['税金']
                    result['e3_count'] += 1
                except Exception as e:
                    result['errors'].append(f'E.3 [{sn[:30]}]: {e}')

            # ── H 规费税金表 ──
            elif '表-13' in sn and 'H' in sn:
                result['h13_count'] += 1

    finally:
        wb.close()

    # ── 人工费：优先 F.1.1 逐行汇总，fallback H 表反推 ──
    if labor_f11_total > 0:
        result['人工费'] = round(labor_f11_total, 2)
        result['人工费_source'] = 'f11_c9_sum'
    else:
        # 重新打开 Excel 读 H 表反推
        try:
            wb2 = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
            for sn in wb2.sheetnames:
                if '表-13' in sn and 'H' in sn:
                    labor_h = extract_labor_from_h13(wb2[sn])
                    if labor_h and labor_h > 0:
                        result['人工费'] = round(labor_h, 2)
                        result['人工费_source'] = 'h13_pension_reverse'
                        break
            wb2.close()
        except Exception:
            pass

    # 四舍五入
    for k in ['建筑工程费', '装饰工程费', '安装工程费',
              '基础工程费', '主体结构费', '屋面工程费', '外墙工程费',
              '分部分项工程费', '措施费', '规费', '税金']:
        result[k] = round(result[k], 2)

    return result


# ═══════════════════════════════════════════════════════════════
# DuckDB 集成
# ═══════════════════════════════════════════════════════════════

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'cost_prediction.duckdb'
)

SOURCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    '..', '..', '..', '..', '..'
)
# 默认源 Excel 目录
DEFAULT_SOURCE_DIR = r'D:\工程造价预测AI项目模板'


def ensure_cost_breakdown_table(db_path: str = None):
    """在 DuckDB 中创建 project_cost_breakdown 表（如果不存在）"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    if not os.path.exists(db_path):
        logger.warning(f"DuckDB 不存在: {db_path}")
        return False

    conn = duckdb.connect(db_path)
    try:
        # 建表（如果不存在）
        conn.execute("""
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
            )
        """)
        # 迁移：为旧表补充 missing columns
        conn.execute("""
            ALTER TABLE project_cost_breakdown
            ADD COLUMN IF NOT EXISTS foundation_type VARCHAR
        """)
        conn.execute("""
            ALTER TABLE project_cost_breakdown
            ADD COLUMN IF NOT EXISTS concrete_grade VARCHAR
        """)
        conn.execute("""
            ALTER TABLE project_cost_breakdown
            ADD COLUMN IF NOT EXISTS steel_grade VARCHAR
        """)
        conn.commit()
        return True
    finally:
        conn.close()


def get_project_id_by_name(db_path: str, project_name: str) -> Optional[str]:
    """根据项目名查找 project_id"""
    conn = duckdb.connect(db_path)
    try:
        result = conn.execute(
            "SELECT project_id FROM project_meta WHERE name = ?",
            [project_name]
        ).fetchone()
        return result[0] if result else None
    finally:
        conn.close()


def get_all_project_names(db_path: str) -> List[Tuple[str, str]]:
    """获取所有项目的 (project_id, name)"""
    conn = duckdb.connect(db_path)
    try:
        return conn.execute(
            "SELECT project_id, name FROM project_meta WHERE name IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()


def insert_breakdown(db_path: str, project_id: str, data: Dict):
    """插入或更新一条费用构成记录"""
    conn = duckdb.connect(db_path)
    try:
        import datetime
        conn.execute("""
            INSERT OR REPLACE INTO project_cost_breakdown
            (project_id, project_name, building_trade_cost, decoration_trade_cost,
             installation_trade_cost, foundation_division_cost, main_structure_cost,
             roofing_cost, exterior_wall_cost, part_item_cost, measure_cost,
             regulation_cost, tax_cost, labor_cost, labor_source,
             foundation_type, extraction_date, source_file,
             e2_count, f11_count, e3_count, h13_count, extraction_errors,
             concrete_grade, steel_grade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            project_id,
            data.get('project_name', ''),
            data.get('建筑工程费', 0),
            data.get('装饰工程费', 0),
            data.get('安装工程费', 0),
            data.get('基础工程费', 0),
            data.get('主体结构费', 0),
            data.get('屋面工程费', 0),
            data.get('外墙工程费', 0),
            data.get('分部分项工程费', 0),
            data.get('措施费', 0),
            data.get('规费', 0),
            data.get('税金', 0),
            data.get('人工费'),
            data.get('人工费_source'),
            data.get('foundation_type'),
            datetime.date.today().isoformat(),
            data.get('source_file', ''),
            data.get('e2_count', 0),
            data.get('f11_arch_count', 0),
            data.get('e3_count', 0),
            data.get('h13_count', 0),
            json.dumps(data.get('errors', []), ensure_ascii=False),
            data.get('concrete_grade'),
            data.get('steel_grade'),
        ])
        conn.commit()
    finally:
        conn.close()


def load_breakdown_from_db(db_path: str = None) -> Dict[str, Dict]:
    """从 DuckDB 加载所有费用构成数据，返回 {project_name: breakdown_dict}"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    if not os.path.exists(db_path):
        return {}

    conn = duckdb.connect(db_path)
    try:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        if 'project_cost_breakdown' not in [t[0] for t in tables]:
            return {}

        rows = conn.execute("""
            SELECT project_name, building_trade_cost, decoration_trade_cost,
                   installation_trade_cost, foundation_division_cost, main_structure_cost,
                   roofing_cost, exterior_wall_cost, part_item_cost, measure_cost,
                   regulation_cost, tax_cost, labor_cost, labor_source, foundation_type
            FROM project_cost_breakdown
        """).fetchall()

        result = {}
        for row in rows:
            result[row[0]] = {
                '建筑工程费': row[1] or 0,
                '装饰工程费': row[2] or 0,
                '安装工程费': row[3] or 0,
                '基础工程费': row[4] or 0,
                '主体结构费': row[5] or 0,
                '屋面工程费': row[6] or 0,
                '外墙工程费': row[7] or 0,
                '分部分项工程费': row[8] or 0,
                '措施费': row[9] or 0,
                '规费': row[10] or 0,
                '税金': row[11] or 0,
                '人工费': row[12],
                '人工费_source': row[13],
                'foundation_type': row[14],
            }
        return result
    finally:
        conn.close()


def extract_all_projects(source_dir: str = None, db_path: str = None) -> Dict:
    """批量提取所有项目

    Args:
        source_dir: 源 Excel 目录
        db_path: DuckDB 路径

    Returns:
        {'success': int, 'failed': int, 'source': str, 'details': [...]}
    """
    if source_dir is None:
        source_dir = DEFAULT_SOURCE_DIR
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    # 确保表存在
    ensure_cost_breakdown_table(db_path)

    projects = get_all_project_names(db_path)
    summary = {'total': len(projects), 'success': 0, 'failed': 0,
               'source': source_dir, 'details': []}

    for project_id, proj_name in projects:
        excel_path = find_source_excel(proj_name, source_dir)
        if not excel_path:
            detail = {'name': proj_name, 'status': 'not_found',
                      'reason': '未匹配到源 Excel'}
            summary['failed'] += 1
            summary['details'].append(detail)
            continue

        data = process_project(excel_path, proj_name)
        data['project_name'] = proj_name

        try:
            insert_breakdown(db_path, project_id, data)
            detail = {
                'name': proj_name,
                'status': 'ok',
                'e2_count': data['e2_count'],
                'f11_count': data['f11_arch_count'],
                'e3_count': data['e3_count'],
                'h13_count': data['h13_count'],
                'labor_source': data.get('人工费_source'),
                'errors': data.get('errors', [])
            }
            summary['success'] += 1
            summary['details'].append(detail)
        except Exception as e:
            detail = {'name': proj_name, 'status': 'write_error', 'reason': str(e)}
            summary['failed'] += 1
            summary['details'].append(detail)

    return summary


# ═══════════════════════════════════════════════════════════════
# CLI & 测试入口
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    if len(sys.argv) > 1 and sys.argv[1] == '--extract-all':
        # 批量提取所有项目
        source = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SOURCE_DIR
        result = extract_all_projects(source_dir=source)
        print(f"\n=== 提取完成 ===")
        print(f"总数: {result['total']} | 成功: {result['success']} | 失败: {result['failed']}")
        for d in result['details']:
            status_icon = '[OK]' if d['status'] == 'ok' else '[FAIL]'
            labor_info = f"labor={d.get('labor_source','?')}" if d['status'] == 'ok' else d.get('reason','')
            print(f"  {status_icon} {d['name'][:30]} | E2={d.get('e2_count',0)} F11={d.get('f11_count',0)} E3={d.get('e3_count',0)} | {labor_info}")

    elif len(sys.argv) > 1 and sys.argv[1] == '--test':
        # 测试单个项目
        test_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SOURCE_DIR
        projects = sorted(os.listdir(test_dir))
        test_proj = projects[0]
        proj_path = os.path.join(test_dir, test_proj)

        excel_path = None
        for f in os.listdir(proj_path):
            if f.endswith('.xlsx') and '项目信息' not in f:
                excel_path = os.path.join(proj_path, f)
                break

        if excel_path:
            data = process_project(excel_path, test_proj)
            print(f"\n=== 测试提取: {test_proj} ===")
            for k, v in data.items():
                if k not in ('errors',):
                    print(f"  {k}: {v}")
            if data['errors']:
                print(f"  ⚠ 错误: {data['errors']}")
