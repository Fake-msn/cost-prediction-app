"""
数据加载器 - Excel 批量导入历史项目训练数据
支持 DuckDB 存储和查询
"""
from __future__ import annotations
import io
import os
import json
import random
from typing import Dict, List, Optional
from datetime import datetime, date
import pandas as pd
import numpy as np

# DuckDB 可选导入
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


REQUIRED_FIELDS = [
    "项目名称", "建筑类型", "结构类型", "总建筑面积", "楼层数",
    "所在地区", "建造年份", "装修标准", "项目总造价", "单方造价"
]

OPTIONAL_FIELDS = [
    "人工费", "材料费", "机械费", "措施费",
    "企业管理费", "规费", "利润", "税金",
    "基础工程费", "主体结构费", "屋面工程费", "外墙工程费",
    "混凝土总用量", "钢筋总用量", "砌块总用量"
]

# ============================================================
# 地区归一化 - 将省份/城市级别值映射为7个大区
# 与 ml_models.py 中的映射保持一致
# ============================================================
_CITY_TO_REGION = {
    "四川": "西南", "成都": "西南", "重庆": "西南", "广元": "西南", "昆明": "西南", "贵阳": "西南",
    "贵州": "西南", "云南": "西南", "西藏": "西南",
    "北京": "华北", "天津": "华北", "河北": "华北", "山西": "华北", "内蒙古": "华北",
    "上海": "华东", "江苏": "华东", "浙江": "华东", "安徽": "华东", "福建": "华东",
    "江西": "华东", "山东": "华东",
    "广东": "华南", "广西": "华南", "海南": "华南", "深圳": "华南", "广州": "华南",
    "湖北": "华中", "湖南": "华中", "河南": "华中", "武汉": "华中", "长沙": "华中", "郑州": "华中",
    "陕西": "西北", "甘肃": "西北", "青海": "西北", "宁夏": "西北", "新疆": "西北", "西安": "西北",
    "辽宁": "东北", "吉林": "东北", "黑龙江": "东北", "沈阳": "东北", "大连": "东北", "哈尔滨": "东北",
}
_VALID_REGIONS = {"华北", "华东", "华南", "华中", "西南", "西北", "东北"}


def _normalize_region(location) -> str:
    """将任意粒度地区值归一化为7个大区之一"""
    if not location:
        return "华东"
    location = str(location).strip()
    if location in _VALID_REGIONS:
        return location
    return _CITY_TO_REGION.get(location, "华东")


class DataLoader:
    """训练数据加载器 - 支持 Excel 和 DuckDB 双存储"""

    def __init__(self, data_dir: str = "data", use_duckdb: bool = True):
        self.data_dir = data_dir
        self.history: List[Dict] = []
        self.use_duckdb = use_duckdb and HAS_DUCKDB
        self.db_path = os.path.join(data_dir, 'cost_prediction.duckdb')
        os.makedirs(data_dir, exist_ok=True)
        # to_dataframe 结果缓存：避免并发对话/评估时重复读 Excel + DuckDB（性能优化）
        self._df_cache = None
        self._load_existing()

    def _invalidate_df_cache(self):
        """数据源变化后失效 to_dataframe 缓存"""
        self._df_cache = None

    def _load_existing(self):
        """加载已有数据 - 优先从 DuckDB，回退到 JSON"""
        if self.use_duckdb and os.path.exists(self.db_path):
            try:
                self.history = self.load_from_duckdb()
                if self.history:
                    return
            except Exception as e:
                print(f"[DataLoader] DuckDB 加载失败，回退到 JSON: {e}")
        
        # 回退到 JSON
        history_file = os.path.join(self.data_dir, "history.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def import_from_excel(self, file_content: bytes, filename: str) -> Dict:
        """从 Excel 文件导入历史项目数据"""
        try:
            df = pd.read_excel(io.BytesIO(file_content), engine="openpyxl")
        except Exception as e:
            return {"success": False, "error": f"Excel 解析失败: {e}"}

        # 校验字段
        missing = [f for f in REQUIRED_FIELDS if f not in df.columns]
        if missing:
            return {
                "success": False,
                "error": f"缺少必填字段: {', '.join(missing)}",
                "required": REQUIRED_FIELDS,
                "optional": OPTIONAL_FIELDS
            }

        # 计算样本权重 _sample_weight
        if 'source_type' in df.columns:
            weight_map = {
                ('A', 'high'): 1.0,
                ('B', 'medium'): 0.7,
                ('C', 'low'): 0.5,
            }
            df['_sample_weight'] = df.apply(
                lambda r: weight_map.get(
                    (str(r.get('source_type', '')), str(r.get('data_confidence', ''))),
                    0.7
                ),
                axis=1
            )
        else:
            # 模拟数据或无来源信息的数据
            df['_sample_weight'] = 0.3

        # ===== 数据质量校验（H3）：过滤明显异常的行，避免污染训练集 =====
        # 规则：
        #   1. 单方造价超出合理区间 [500, 50000] 元/m² 视为异常
        #   2. 总建筑面积 <= 0 视为异常
        #   3. 项目总造价 <= 0 视为异常
        dropped_reasons = {"单方造价异常": 0, "面积异常": 0, "总造价异常": 0}
        _up = pd.to_numeric(df.get("单方造价"), errors="coerce")
        _area = pd.to_numeric(df.get("总建筑面积"), errors="coerce")
        _cost = pd.to_numeric(df.get("项目总造价"), errors="coerce")
        _keep = pd.Series(True, index=df.index)
        _bad_up = _up.notna() & ~_up.between(500, 50000)
        _bad_area = _area.notna() & (_area <= 0)
        _bad_cost = _cost.notna() & (_cost <= 0)
        dropped_reasons["单方造价异常"] = int(_bad_up.sum())
        dropped_reasons["面积异常"] = int(_bad_area.sum())
        dropped_reasons["总造价异常"] = int(_bad_cost.sum())
        _keep &= ~_bad_up & ~_bad_area & ~_bad_cost
        if not _keep.all():
            dropped_count = int((~_keep).sum())
            df = df[_keep].copy()
            print(f"[DataLoader] 数据质量过滤: 丢弃 {dropped_count} 条异常记录 "
                  f"(单方造价异常 {dropped_reasons['单方造价异常']}, 面积异常 {dropped_reasons['面积异常']}, "
                  f"总造价异常 {dropped_reasons['总造价异常']})")

        if len(df) == 0:
            return {"success": False, "error": "导入文件中无有效数据（所有行均被质量校验过滤）", "dropped": dropped_reasons}

        imported = []
        for idx, row in df.iterrows():
            record = {
                "id": f"P{len(self.history) + idx + 1:04d}",
                "imported_at": datetime.now().isoformat(),
                "source_file": filename
            }
            for col in df.columns:
                val = row[col]
                if pd.isna(val):
                    record[col] = None
                elif isinstance(val, (int, float)):
                    record[col] = float(val) if isinstance(val, float) else int(val)
                else:
                    record[col] = str(val)
            imported.append(record)

        self.history.extend(imported)
        self._invalidate_df_cache()  # 数据源已变化，失效 to_dataframe 缓存
        self._save()
        
        # 同步写入 DuckDB
        if self.use_duckdb:
            try:
                self._sync_to_duckdb(imported, filename)
                # 自动提取新项目的费用构成（如果源 Excel 可用）
                self._auto_extract_cost_breakdown([r.get('项目名称') for r in imported])
            except Exception as e:
                print(f"[DataLoader] DuckDB 同步失败: {e}")
        
        return {
            "success": True,
            "imported_count": len(imported),
            "total_count": len(self.history),
            "dropped": dropped_reasons if any(dropped_reasons.values()) else None,
            "samples": imported[:3]
        }

    def _save(self):
        history_file = os.path.join(self.data_dir, "history.json")
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def _sync_to_duckdb(self, records: List[Dict], source_file: str):
        """将导入的记录同步到 DuckDB"""
        if not HAS_DUCKDB or not records:
            return
        
        conn = duckdb.connect(self.db_path)
        try:
            for rec in records:
                project_id = rec.get('id', f"P{hash(str(rec)) % 10000:04d}")
                conn.execute("""
                    INSERT OR REPLACE INTO project_meta
                    (project_id, name, building_type, structure_type, location,
                     build_year, total_area, total_cost, unit_price, source_file,
                     extraction_date, data_quality_grade, metadata_completeness,
                     training_weight, confidence, field_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    project_id,
                    rec.get('项目名称', ''),
                    rec.get('建筑类型', ''),
                    rec.get('结构类型', ''),
                    rec.get('所在地区', ''),
                    int(rec.get('建造年份', 2023)) if rec.get('建造年份') else 2023,
                    float(rec.get('总建筑面积', 0)) if rec.get('总建筑面积') else 0,
                    float(rec.get('项目总造价', 0)) if rec.get('项目总造价') else 0,
                    float(rec.get('单方造价', 0)) if rec.get('单方造价') else 0,
                    source_file,
                    date.today().isoformat(),
                    rec.get('source_type', 'C'),
                    0.5,
                    rec.get('_sample_weight', 0.5),
                    0.5,
                    'imported_excel',
                ])
        finally:
            conn.close()

    def _auto_extract_cost_breakdown(self, new_project_names: List[str] = None):
        """自动提取新导入项目的费用构成（懒加载 extractor，避免循环依赖）

        导入流程完成后调用：检查 DuckDB 中缺少 cost_breakdown 的项目，
        尝试从源 Excel 目录匹配并提取。
        """
        if not HAS_DUCKDB:
            return
        try:
            from cost_breakdown_extractor import (
                ensure_cost_breakdown_table, find_source_excel,
                process_project, insert_breakdown, get_project_id_by_name,
                DEFAULT_SOURCE_DIR
            )

            ensure_cost_breakdown_table(self.db_path)

            conn = duckdb.connect(self.db_path)
            try:
                if new_project_names:
                    placeholders = ','.join(['?'] * len(new_project_names))
                    missing = conn.execute(f"""
                        SELECT pm.project_id, pm.name FROM project_meta pm
                        WHERE pm.name IN ({placeholders})
                          AND pm.name NOT IN (
                              SELECT project_name FROM project_cost_breakdown
                          )
                    """, new_project_names).fetchall()
                else:
                    missing = conn.execute("""
                        SELECT pm.project_id, pm.name FROM project_meta pm
                        WHERE pm.name NOT IN (
                            SELECT project_name FROM project_cost_breakdown
                        )
                    """).fetchall()
            finally:
                conn.close()

            if not missing:
                return

            extracted = 0
            for project_id, proj_name in missing:
                excel_path = find_source_excel(proj_name, DEFAULT_SOURCE_DIR)
                if not excel_path:
                    continue
                try:
                    data = process_project(excel_path, proj_name)
                    insert_breakdown(self.db_path, project_id, data)
                    extracted += 1
                except Exception as e:
                    print(f"[DataLoader] 自动提取失败 {proj_name}: {e}")

            if extracted > 0:
                print(f"[DataLoader] 自动提取了 {extracted}/{len(missing)} 个新项目的费用构成")
        except ImportError:
            pass  # extractor 模块不可用时静默跳过
        except Exception as e:
            print(f"[DataLoader] 自动提取费用构成失败: {e}")

    def load_from_duckdb(self, limit: int = 1000) -> List[Dict]:
        """从 DuckDB 加载项目数据"""
        if not HAS_DUCKDB:
            return []
        
        if not os.path.exists(self.db_path):
            return []
        
        conn = duckdb.connect(self.db_path)
        try:
            # 检查表是否存在
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            
            if 'project_meta' not in table_names:
                return []
            
            rows = conn.execute(f"""
                SELECT project_id, name, building_type, structure_type, location,
                       build_year, total_area, total_cost, unit_price, source_file,
                       data_quality_grade, training_weight, confidence
                FROM project_meta
                ORDER BY extraction_date DESC
                LIMIT {limit}
            """).fetchall()
            
            records = []
            for row in rows:
                records.append({
                    'id': row[0],
                    '项目名称': row[1],
                    '建筑类型': row[2],
                    '结构类型': row[3],
                    '所在地区': row[4],
                    '建造年份': row[5],
                    '总建筑面积': row[6],
                    '项目总造价': row[7],
                    '单方造价': row[8],
                    'source_file': row[9],
                    'source_type': row[10],
                    '_sample_weight': row[11],
                    'data_confidence': 'high' if row[10] == 'A' else ('medium' if row[10] == 'B' else 'low'),
                })
            
            return records
        finally:
            conn.close()

    def load_boq_items_from_duckdb(self, db_path=None):
        """从DuckDB加载BOQ清单项用于L3模型训练

        修复: boq_items.project_id (hex格式) 与 project_meta.project_id (P00xx格式)
        无法直接JOIN，因此直接加载所有BOQ items，并从boq_code前缀推导division。
        项目级特征(building_type等)使用默认值，由extract_boq_features处理。
        """
        import duckdb as _duckdb
        if db_path is None:
            db_path = self.db_path  # 使用DataLoader已配置的数据库路径
        if not os.path.exists(db_path):
            print(f"[DataLoader] DuckDB文件不存在: {db_path}")
            return None

        conn = _duckdb.connect(db_path, read_only=True)
        try:
            # 直接从boq_items加载，不做无效JOIN
            # 使用COALESCE从boq_code前缀推导division，确保所有item都有division值
            df = conn.execute("""
                SELECT 
                    bi.project_id, bi.boq_code,
                    COALESCE(bi.division, 
                        CASE SUBSTR(bi.boq_code, 1, 2)
                            WHEN '00' THEN '土建结构'
                            WHEN '01' THEN '土建结构'
                            WHEN '02' THEN '门窗工程'
                            WHEN '03' THEN '安装工程'
                            WHEN '04' THEN '装饰装修'
                            WHEN '05' THEN '装饰装修'
                            WHEN '07' THEN '土建结构'
                            WHEN '20' THEN '其他'
                            ELSE '未知'
                        END
                    ) AS division,
                    bi.trade,
                    bi.unit, bi.quantity, bi.comp_unit_price,
                    bi.is_active
                FROM boq_items bi
                WHERE bi.is_active = 1 
                  AND bi.comp_unit_price > 0
            """).fetchdf()
        except Exception as e:
            print(f"[DataLoader] load_boq_items_from_duckdb 失败: {e}")
            conn.close()
            return None
        conn.close()

        if df is not None and len(df) > 0:
            # 项目级特征使用默认值（boq_items与project_meta的ID格式不匹配）
            df['building_type'] = '未知'
            df['structure_type'] = '未知'
            df['location'] = '未知'
            df['above_ground_floors'] = 0
            df['total_area'] = 0
            df['build_year'] = 2020
            print(f"[DataLoader] 从DuckDB加载 {len(df)} 条BOQ清单项 (全量，含推导division)")
        return df

    def load_boq_aggregations(self, db_path=None):
        """从DuckDB聚合BOQ数据，生成项目级/全局 trade 比例统计

        由于 boq_items.project_id (hex格式) 与 project_meta.project_id (P00xx格式)
        无法直接JOIN，因此同时返回:
          - per-project 聚合 (df, 按project_id分组)
          - 全局平均比例 (global_ratios dict)
        返回 dict: {'df': DataFrame, 'global_ratios': dict} 或 None
        """
        import duckdb as _duckdb
        if db_path is None:
            db_path = self.db_path
        if not os.path.exists(db_path):
            return None

        conn = _duckdb.connect(db_path, read_only=True)
        try:
            # 检查boq_items表是否存在
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
            if 'boq_items' not in [t[0] for t in tables]:
                return None

            # 按项目聚合 trade 费用
            # 映射规则:
            #   建筑/土建 trade → arch_cost (建筑工程费)
            #   装饰 trade → deco_cost (装饰工程费)
            #   装修 trade → inst_cost (安装工程费, 装修通常指机电安装)
            df = conn.execute("""
                SELECT 
                    bi.project_id,
                    -- Trade costs
                    SUM(CASE WHEN bi.trade LIKE '%建筑%' OR bi.trade LIKE '%土建%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as arch_cost,
                    SUM(CASE WHEN bi.trade = '装饰' OR bi.trade LIKE '%装饰%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as deco_cost,
                    SUM(CASE WHEN bi.trade = '装修' OR bi.trade LIKE '%安装%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as inst_cost,
                    -- Division costs
                    SUM(CASE WHEN bi.division LIKE '%基础%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as foundation_cost,
                    SUM(CASE WHEN bi.division LIKE '%主体%' OR bi.division LIKE '%结构%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as structure_cost,
                    SUM(CASE WHEN bi.division LIKE '%屋面%' OR bi.division LIKE '%楼地面%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as roof_cost,
                    SUM(CASE WHEN bi.division LIKE '%外墙%'
                             THEN bi.comp_unit_price * bi.quantity ELSE 0 END) as wall_cost,
                    -- Material consumption
                    SUM(CASE WHEN bi.item_name LIKE '%混凝土%' OR bi.item_name LIKE '%砼%'
                             THEN bi.quantity ELSE 0 END) as concrete_total,
                    SUM(CASE WHEN bi.item_name LIKE '%钢筋%' OR bi.item_name LIKE '%螺纹钢%'
                             THEN bi.quantity ELSE 0 END) as rebar_total,
                    SUM(CASE WHEN bi.item_name LIKE '%砌块%' OR bi.item_name LIKE '%砖%'
                             THEN bi.quantity ELSE 0 END) as block_total,
                    -- Stats
                    COUNT(*) as item_count,
                    COUNT(DISTINCT bi.division) as division_count,
                    SUM(bi.comp_unit_price * bi.quantity) as total_boq_cost
                FROM boq_items bi
                WHERE bi.is_active = 1 AND bi.comp_unit_price > 0
                GROUP BY bi.project_id
            """).fetchdf()

            if df is None or len(df) == 0:
                return None

            # 计算全局平均比例
            total_arch = df['arch_cost'].sum()
            total_deco = df['deco_cost'].sum()
            total_inst = df['inst_cost'].sum()
            grand_total = total_arch + total_deco + total_inst

            if grand_total > 0:
                # 如果安装工程费为0（无装修/安装trade），用装饰的一半估算
                if total_inst == 0 and total_deco > 0:
                    total_inst = total_deco * 0.5
                    total_deco = total_deco * 0.5
                    grand_total = total_arch + total_deco + total_inst

                global_ratios = {
                    'arch_ratio': total_arch / grand_total,
                    'deco_ratio': total_deco / grand_total,
                    'inst_ratio': total_inst / grand_total,
                }

                # 合理性检查: 建筑工程费占比不应超过80%，否则用行业基准平滑
                if global_ratios['arch_ratio'] > 0.80:
                    print(f"[load_boq_aggregations] BOQ建筑占比异常高({global_ratios['arch_ratio']:.2f})，使用行业基准平滑")
                    # 用行业基准(0.60/0.20/0.20)和BOQ比例加权平均
                    global_ratios = {
                        'arch_ratio': 0.5 * global_ratios['arch_ratio'] + 0.5 * 0.60,
                        'deco_ratio': 0.5 * global_ratios['deco_ratio'] + 0.5 * 0.20,
                        'inst_ratio': 0.5 * global_ratios['inst_ratio'] + 0.5 * 0.20,
                    }
                    # 重新归一化
                    s = sum(global_ratios.values())
                    global_ratios = {k: v/s for k, v in global_ratios.items()}

                # 最终归一化确保比例之和=1.0（BOQ仅包含部分费用类别）
                s = sum(global_ratios.values())
                if s > 0 and abs(s - 1.0) > 0.01:
                    global_ratios = {k: v/s for k, v in global_ratios.items()}
                    print(f"[load_boq_aggregations] 归一化后: arch={global_ratios['arch_ratio']:.3f}, deco={global_ratios['deco_ratio']:.3f}, inst={global_ratios['inst_ratio']:.3f}")
            else:
                # 回退到行业基准
                global_ratios = {'arch_ratio': 0.72, 'deco_ratio': 0.14, 'inst_ratio': 0.14}

            print(f"[load_boq_aggregations] {len(df)} 个BOQ项目, "
                  f"global_ratios: arch={global_ratios['arch_ratio']:.3f}, "
                  f"deco={global_ratios['deco_ratio']:.3f}, inst={global_ratios['inst_ratio']:.3f}")

            return {'df': df, 'global_ratios': global_ratios}

        except Exception as e:
            print(f"[load_boq_aggregations] 失败: {e}")
            return None
        finally:
            conn.close()

    def get_boq_items(self, project_id: str = None) -> List[Dict]:
        """从 DuckDB 获取清单条目"""
        if not HAS_DUCKDB or not os.path.exists(self.db_path):
            return []
        
        conn = duckdb.connect(self.db_path)
        try:
            if project_id:
                rows = conn.execute("""
                    SELECT item_id, project_id, unit_project, boq_code, item_name,
                           spec_text, division, trade, unit, quantity,
                           comp_unit_price, total_price, labor_fee
                    FROM boq_items
                    WHERE project_id = ? AND is_active = 1
                """, [project_id]).fetchall()
            else:
                rows = conn.execute("""
                    SELECT item_id, project_id, unit_project, boq_code, item_name,
                           spec_text, division, trade, unit, quantity,
                           comp_unit_price, total_price, labor_fee
                    FROM boq_items
                    WHERE is_active = 1
                """).fetchall()
            
            return [
                {
                    'item_id': r[0],
                    'project_id': r[1],
                    'unit_project': r[2],
                    'boq_code': r[3],
                    'item_name': r[4],
                    'spec_text': r[5],
                    'division': r[6],
                    'trade': r[7],
                    'unit': r[8],
                    'quantity': r[9],
                    'comp_unit_price': r[10],
                    'total_price': r[11],
                    'labor_fee': r[12],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self.history[-limit:]

    def to_dataframe(self):
        """转换为 pandas DataFrame 供训练使用（合并 DuckDB + Excel 数据）

        合并策略：
        - Excel 数据有完整费用构成，作为基础
        - DuckDB 数据有 build_year、decoration_standard 等元数据
        - 对同名项目，将 DuckDB 元数据合并到 Excel 行
        - 仅在 DuckDB 中的项目，用规范比例估算费用构成
        """
        # 1. 加载 Excel 训练数据（含完整费用构成、材料用量）
        # 缓存命中：数据源未变化时直接复用，避免并发场景重复读 Excel + DuckDB
        if self._df_cache is not None:
            return self._df_cache

        excel_dfs = []
        excel_files = [
            os.path.join(self.data_dir, 'real_training_data.xlsx'),
            os.path.join(self.data_dir, 'sample_training_data.xlsx'),
        ]
        for excel_path in excel_files:
            if os.path.exists(excel_path):
                try:
                    xls = pd.read_excel(excel_path, engine='openpyxl')
                    fname = os.path.basename(excel_path)
                    if '_sample_weight' not in xls.columns:
                        xls['_sample_weight'] = 1.0 if 'real' in fname else 0.7
                    if 'source_type' not in xls.columns:
                        xls['source_type'] = 'A' if 'real' in fname else 'B'
                    excel_dfs.append(xls)
                    print(f"[to_dataframe] 从 {fname} 加载 {len(xls)} 条记录")
                except Exception as e:
                    print(f"[to_dataframe] Excel 加载失败 {excel_path}: {e}")

        # 2. 加载 DuckDB 元数据
        db_df = None
        if self.use_duckdb and os.path.exists(self.db_path):
            try:
                db_df = self._load_duckdb_dataframe()
                if db_df is not None and len(db_df) > 0:
                    print(f"[to_dataframe] DuckDB 加载 {len(db_df)} 条元数据")
            except Exception as e:
                print(f"[to_dataframe] DuckDB 加载失败: {e}")

        if not excel_dfs and db_df is None:
            # 回退到 JSON
            if self.history:
                try:
                    return pd.DataFrame(self.history)
                except Exception:
                    pass
            return None

        # 3. 合并：以 Excel 数据为基础，补充 DuckDB 元数据
        result_dfs = []
        excel_names = set()

        if excel_dfs:
            base_df = pd.concat(excel_dfs, ignore_index=True)
            if '项目名称' in base_df.columns:
                excel_names = set(base_df['项目名称'].tolist())

            # 将 DuckDB 元数据合并到 Excel 行（按项目名称匹配）
            if db_df is not None and '项目名称' in db_df.columns and '项目名称' in base_df.columns:
                # 从 DuckDB 提取 build_year, decoration_standard, above_ground_floors
                meta_cols = ['项目名称']
                meta_map = {}
                for _, row in db_df.iterrows():
                    name = row.get('项目名称')
                    if name:
                        meta_map[name] = {
                            '建造年份': row.get('建造年份'),
                            '装修标准': row.get('装修标准'),
                            '楼层数': row.get('楼层数'),
                            '基础类型': row.get('基础类型'),
                        }
                # 更新 base_df 中的对应字段
                for col in ['建造年份', '装修标准', '楼层数', '基础类型']:
                    if col not in base_df.columns:
                        base_df[col] = None
                    for name, meta in meta_map.items():
                        mask = base_df['项目名称'] == name
                        if mask.any() and meta.get(col) is not None:
                            base_df.loc[mask, col] = meta[col]

            result_dfs.append(base_df)

        # 4. 添加仅在 DuckDB 中、不在 Excel 中的项目
        if db_df is not None and len(db_df) > 0:
            db_only = db_df[~db_df['项目名称'].isin(excel_names)] if excel_names else db_df
            if len(db_only) > 0:
                result_dfs.append(db_only)
                print(f"[to_dataframe] DuckDB 独有项目 {len(db_only)} 条")

        if not result_dfs:
            return None

        try:
            merged = pd.concat(result_dfs, ignore_index=True)

            # 5. 为所有行派生 建筑工程费/装饰工程费/安装工程费（section_xgb 关键目标字段）
            # Excel行有基础/主体/屋面/外墙但没有建筑/装饰/安装，需补充
            if '项目总造价' in merged.columns:
                tc = pd.to_numeric(merged['项目总造价'], errors='coerce').fillna(0)
                boq_agg = self.load_boq_aggregations()
                arch_r = boq_agg['global_ratios']['arch_ratio'] if boq_agg else 0.72
                deco_r = boq_agg['global_ratios']['deco_ratio'] if boq_agg else 0.14
                inst_r = boq_agg['global_ratios']['inst_ratio'] if boq_agg else 0.14

                # 建筑工程费: 优先用已有字段(基础+主体+屋面+外墙)加和，否则用BOQ比例
                if '建筑工程费' not in merged.columns:
                    merged['建筑工程费'] = np.nan
                mask_arch_na = merged['建筑工程费'].isna() | (merged['建筑工程费'] == 0)
                if '基础工程费' in merged.columns:
                    computed_arch = (
                        pd.to_numeric(merged.get('基础工程费', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(merged.get('主体结构费', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(merged.get('屋面工程费', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(merged.get('外墙工程费', 0), errors='coerce').fillna(0)
                    )
                    # 用加和结果填充NA行，仅当加和>0时
                    fill_mask = mask_arch_na & (computed_arch > 0)
                    merged.loc[fill_mask, '建筑工程费'] = computed_arch[fill_mask]
                    # 其余NA行用BOQ比例
                    still_na = merged['建筑工程费'].isna() | (merged['建筑工程费'] == 0)
                    merged.loc[still_na, '建筑工程费'] = tc[still_na] * arch_r
                else:
                    merged.loc[mask_arch_na, '建筑工程费'] = tc[mask_arch_na] * arch_r

                # 装饰工程费: NA行用BOQ比例填充
                if '装饰工程费' not in merged.columns:
                    merged['装饰工程费'] = np.nan
                mask_deco_na = merged['装饰工程费'].isna() | (merged['装饰工程费'] == 0)
                merged.loc[mask_deco_na, '装饰工程费'] = tc[mask_deco_na] * deco_r

                # 安装工程费: NA行用BOQ比例填充
                if '安装工程费' not in merged.columns:
                    merged['安装工程费'] = np.nan
                mask_inst_na = merged['安装工程费'].isna() | (merged['安装工程费'] == 0)
                merged.loc[mask_inst_na, '安装工程费'] = tc[mask_inst_na] * inst_r

                print(f"[to_dataframe] 已派生 建筑工程费/装饰工程费/安装工程费 (BOQ ratios: {arch_r:.3f}/{deco_r:.3f}/{inst_r:.3f})")

            # 归一化地区：将省份/城市级别值（如四川/成都/广元）统一为7个大区
            if '所在地区' in merged.columns:
                before = merged['所在地区'].value_counts().to_dict()
                merged['所在地区'] = merged['所在地区'].apply(_normalize_region)
                after = merged['所在地区'].value_counts().to_dict()
                if before != after:
                    print(f"[to_dataframe] 地区归一化: {before} → {after}")

            print(f"[to_dataframe] 合并后总计 {len(merged)} 条记录, {len(merged.columns)} 列")
            self._df_cache = merged  # 写入缓存
            return merged
        except Exception as e:
            print(f"[to_dataframe] 合并失败: {e}")
            return result_dfs[0] if result_dfs else None

    def _load_duckdb_dataframe(self) -> Optional[pd.DataFrame]:
        """从 DuckDB 直接加载训练用 DataFrame（含完整字段映射）"""
        if not HAS_DUCKDB or not os.path.exists(self.db_path):
            return None

        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            # 检查表是否存在
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
            if 'project_meta' not in [t[0] for t in tables]:
                return None

            df = conn.execute("""
                SELECT
                    pm.name           AS 项目名称,
                    pm.building_type  AS 建筑类型,
                    pm.structure_type AS 结构类型,
                    pm.total_area     AS 总建筑面积,
                    pm.above_ground_floors AS 楼层数,
                    pm.under_ground_floors AS 地下层数,
                    pm.location       AS 所在地区,
                    pm.build_year     AS 建造年份,
                    pm.decoration_standard AS 装修标准,
                    pm.foundation_type AS 基础类型,
                    pm.total_cost     AS 项目总造价,
                    pm.unit_price     AS 单方造价,
                    pm.training_weight AS _sample_weight,
                    pm.data_quality_grade AS source_type,
                    CASE pm.data_quality_grade
                        WHEN 'A' THEN 'high'
                        WHEN 'B' THEN 'medium'
                        ELSE 'low'
                    END AS data_confidence
                FROM project_meta pm
                WHERE pm.building_type IS NOT NULL
                  AND pm.unit_price IS NOT NULL
                  AND pm.unit_price > 0
            """).fetchdf()

            # 将 above_ground_floors NULL 填充为 0
            if '楼层数' in df.columns:
                df['楼层数'] = df['楼层数'].fillna(1).astype(int).clip(lower=1)
            if '建造年份' in df.columns:
                df['建造年份'] = df['建造年份'].fillna(2023).astype(int)

            # ── 费用构成字段：优先级链加载 ──
            # P1: DuckDB project_cost_breakdown 表（源 Excel 提取的真实数据）
            # P2: BOQ 聚合估算（按建筑类型差异化）
            # P3: 固定比例兜底（确保模型不因全0受影响）
            bd_loaded = False
            try:
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
                ).fetchall()
                if 'project_cost_breakdown' in [t[0] for t in tables]:
                    bd_rows = conn.execute("""
                        SELECT project_name, building_trade_cost, decoration_trade_cost,
                               installation_trade_cost, foundation_division_cost, main_structure_cost,
                               roofing_cost, exterior_wall_cost, part_item_cost, measure_cost,
                               regulation_cost, tax_cost, labor_cost, foundation_type,
                               concrete_grade, steel_grade
                        FROM project_cost_breakdown
                    """).fetchall()
                    bd_map = {}
                    for row in bd_rows:
                        bd_map[row[0]] = {
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
                            '人工费': row[12] if row[12] and row[12] > 0 else None,
                            '基础类型': row[13] if row[13] else None,
                            '混凝土等级': row[14] if row[14] else None,
                            '钢筋等级': row[15] if row[15] else None,
                        }
                    if bd_map:
                        for col_name in ['人工费', '措施费', '规费', '税金',
                                         '基础工程费', '主体结构费', '屋面工程费', '外墙工程费',
                                         '建筑工程费', '装饰工程费', '安装工程费', '基础类型',
                                         '混凝土等级', '钢筋等级']:
                            if col_name not in df.columns:
                                df[col_name] = 0.0 if col_name not in ('基础类型', '混凝土等级', '钢筋等级') else None
                        for idx in df.index:
                            name = df.at[idx, '项目名称']
                            if name in bd_map:
                                bd = bd_map[name]
                                for col_name, val in bd.items():
                                    if val is not None and (isinstance(val, str) or val > 0):
                                        df.at[idx, col_name] = val
                        bd_loaded = True
                        print(f"[data_loader] 从 project_cost_breakdown 加载了 {len(bd_map)} 个项目的费用构成")
            except Exception as e:
                print(f"[data_loader] 加载 cost_breakdown 失败: {e}")

            # P3: 兜底 —— 固定比例合成（仅对仍然缺失的字段）
            if not bd_loaded and '项目总造价' in df.columns:
                missing_cost = df.get('人工费', pd.Series([0]*len(df))).fillna(0).sum() == 0
                if missing_cost:
                    tc = df['项目总造价'].fillna(0)
                    df['人工费'] = tc * 0.20
                    df['措施费'] = tc * 0.05
                    df['规费'] = tc * 0.05
                    df['税金'] = tc * 0.04
                    df['基础工程费'] = tc * 0.15
                    df['主体结构费'] = tc * 0.40
                    df['屋面工程费'] = tc * 0.05
                    df['外墙工程费'] = tc * 0.10
                    # 材料用量估算（按面积）
                    area = df['总建筑面积'].fillna(0)
                    df['混凝土总用量'] = area * 0.45
                    df['钢筋总用量'] = area * 0.055
                    df['砌块总用量'] = area * 0.25
                    print("[data_loader] 费用构成字段使用固定比例估算（兜底）")

            # 使用BOQ聚合数据派生 建筑工程费/装饰工程费/安装工程费
            # 这是 section_xgb 模型的关键目标字段
            boq_agg = self.load_boq_aggregations()
            if boq_agg is not None:
                ratios = boq_agg['global_ratios']
                tc = df['项目总造价'].fillna(0)
                # 建筑工程费 = 基础 + 主体 + 屋面 + 外墙 (已有字段直接加和)
                if '基础工程费' in df.columns:
                    df['建筑工程费'] = (
                        pd.to_numeric(df.get('基础工程费', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(df.get('主体结构费', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(df.get('屋面工程费', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(df.get('外墙工程费', 0), errors='coerce').fillna(0)
                    )
                else:
                    df['建筑工程费'] = tc * ratios['arch_ratio']
                # 装饰工程费/安装工程费: 用BOQ比例从总造价派生
                df['装饰工程费'] = tc * ratios['deco_ratio']
                df['安装工程费'] = tc * ratios['inst_ratio']
                print(f"[_load_duckdb_dataframe] 用BOQ比例派生 建筑/装饰/安装 工程费, "
                      f"ratios: arch={ratios['arch_ratio']:.3f}, deco={ratios['deco_ratio']:.3f}, inst={ratios['inst_ratio']:.3f}")
            else:
                # 无BOQ数据，使用行业基准比例
                tc = df['项目总造价'].fillna(0)
                if '建筑工程费' not in df.columns:
                    if '基础工程费' in df.columns:
                        df['建筑工程费'] = (
                            pd.to_numeric(df.get('基础工程费', 0), errors='coerce').fillna(0) +
                            pd.to_numeric(df.get('主体结构费', 0), errors='coerce').fillna(0) +
                            pd.to_numeric(df.get('屋面工程费', 0), errors='coerce').fillna(0) +
                            pd.to_numeric(df.get('外墙工程费', 0), errors='coerce').fillna(0)
                        )
                    else:
                        df['建筑工程费'] = tc * 0.72
                if '装饰工程费' not in df.columns:
                    df['装饰工程费'] = tc * 0.14
                if '安装工程费' not in df.columns:
                    df['安装工程费'] = tc * 0.14

            # 归一化地区：将省份/城市级别值统一为7个大区
            if '所在地区' in df.columns:
                before = df['所在地区'].value_counts().to_dict()
                df['所在地区'] = df['所在地区'].apply(_normalize_region)
                after = df['所在地区'].value_counts().to_dict()
                if before != after:
                    print(f"[_load_duckdb_dataframe] 地区归一化: {before} → {after}")

            # 从所在地区推导设防烈度（归一化后，与 predict 路径一致）
            try:
                from ml_models import resolve_seismic_intensity
                if '设防烈度' not in df.columns and '所在地区' in df.columns:
                    df['设防烈度'] = df['所在地区'].apply(
                        lambda x: resolve_seismic_intensity(str(x)) if pd.notna(x) else "7度"
                    )
            except ImportError:
                pass

            return df
        finally:
            conn.close()

    def get_statistics(self) -> Dict:
        """获取训练数据集统计信息"""
        if not self.history:
            return {"count": 0}

        df = pd.DataFrame(self.history)
        stats = {
            "count": len(self.history),
            "fields": {
                "total": len(REQUIRED_FIELDS) + len(OPTIONAL_FIELDS),
                "required": len(REQUIRED_FIELDS),
                "optional": len(OPTIONAL_FIELDS)
            }
        }

        # 数值字段统计
        if "单方造价" in df.columns:
            unit_prices = pd.to_numeric(df["单方造价"], errors="coerce").dropna()
            if len(unit_prices) > 0:
                stats["unit_price"] = {
                    "min": float(unit_prices.min()),
                    "max": float(unit_prices.max()),
                    "mean": float(unit_prices.mean()),
                    "median": float(unit_prices.median())
                }

        if "总建筑面积" in df.columns:
            areas = pd.to_numeric(df["总建筑面积"], errors="coerce").dropna()
            if len(areas) > 0:
                stats["area"] = {
                    "min": float(areas.min()),
                    "max": float(areas.max()),
                    "mean": float(areas.mean())
                }

        # 按建筑类型分组
        if "建筑类型" in df.columns:
            stats["by_project_type"] = df["建筑类型"].value_counts().to_dict()

        # 按地区分组
        if "所在地区" in df.columns:
            stats["by_region"] = df["所在地区"].value_counts().to_dict()

        return stats

    def find_similar_projects(
        self,
        project_type: str,
        structure_type: str,
        area: float,
        limit: int = 5
    ) -> List[Dict]:
        """在历史数据中查找相似项目（用于类比估算）

        匹配策略（优先级递减）：
        1. 必须首先按建筑类型过滤（硬性约束）
        2. 若无同类型项目，回退到最接近的类型并给出警告
        3. 在同类型项目中按面积相似度排序
        """
        if not self.history:
            return []

        # 第一轮：严格按建筑类型过滤
        same_type = [
            r for r in self.history
            if r.get("建筑类型") == project_type
        ]

        if same_type:
            # Additional name-based validation
            type_keywords = {
                '住宅': ['住宅', '安置', '小区', '楼', '住房', '公苑', '居', '苑', '房', '新村', '花园', '家园', '小区'],
                '学校': ['学校', '学院', '教育', '教学', '校区'],
                '商业建筑': ['商业', '商铺', '商场', '营业'],
                '办公楼': ['办公', '写字楼', '行政'],
                '公共建筑': ['文化', '图书', '展览', '体育', '综合', '整治', '环境', '服务'],
                '工业建筑': ['厂房', '工业', '车间', '产业园'],
                '基础设施': ['道路', '桥梁', '管网', '市政'],
            }
            keywords = type_keywords.get(project_type, [])
            if keywords and len(same_type) > 3:
                name_filtered = [p for p in same_type if any(kw in str(p.get('项目名称', '')) for kw in keywords)]
                if len(name_filtered) >= 3:
                    same_type = name_filtered

            # 在同类型项目中按面积相似度排序
            def area_similarity_score(record):
                score = 0
                if record.get("结构类型") == structure_type:
                    score += 2
                try:
                    rec_area = float(record.get("总建筑面积", 0) or 0)
                    if rec_area > 0 and area > 0:
                        area_diff = abs(rec_area - area) / max(area, 1)
                        if area_diff < 0.3:
                            score += 3
                        elif area_diff < 0.5:
                            score += 2
                        elif area_diff < 1.0:
                            score += 1
                except Exception:
                    pass
                return score

            same_type.sort(key=area_similarity_score, reverse=True)
            return same_type[:limit]

        # 第二轮：无同类型项目，回退到面积最接近的其他类型
        fallback = []
        for record in self.history:
            rec_type = record.get("建筑类型", "")
            if not rec_type or rec_type == project_type:
                continue
            score = 0
            if record.get("结构类型") == structure_type:
                score += 1
            try:
                rec_area = float(record.get("总建筑面积", 0) or 0)
                if rec_area > 0 and area > 0:
                    area_diff = abs(rec_area - area) / max(area, 1)
                    if area_diff < 0.3:
                        score += 3
                    elif area_diff < 0.5:
                        score += 2
                    elif area_diff < 1.0:
                        score += 1
            except Exception:
                pass
            if score > 0:
                fallback.append((score, record))

        fallback.sort(key=lambda x: -x[0])
        return [r for _, r in fallback[:limit]]


def generate_sample_excel(output_path: str, n: int = 80):
    """
    生成示例 Excel 训练数据 —— 8 种建筑类型均衡覆盖

    建筑类型：学校/医院/办公楼/住宅/工业建筑/商业建筑/基础设施/公共建筑
    每种类型至少 n/8 条，确保模型能学习类型差异
    """
    random.seed(42)

    project_types = ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    structures = ["框架结构", "框剪结构", "剪力墙结构", "砖混结构", "钢结构"]
    regions = ["华北", "华东", "华南", "华中", "西南", "西北", "东北"]
    decorations = ["简单装修", "普通装修", "精装修", "豪华装修"]

    # 各建筑类型基准单方造价（元/m²）—— 反映真实造价差异
    base_prices = {
        "学校": 3500, "医院": 4500, "办公楼": 4000, "住宅": 3200,
        "工业建筑": 2800, "商业建筑": 5000, "基础设施": 2500, "公共建筑": 3800
    }
    # 各建筑类型常用结构（影响结构系数分布）
    type_structures = {
        "学校": ["框架结构", "框剪结构"],
        "医院": ["框架结构", "框剪结构"],
        "办公楼": ["框架结构", "框剪结构", "钢结构"],
        "住宅": ["剪力墙结构", "框剪结构", "砖混结构"],
        "工业建筑": ["钢结构", "框架结构"],
        "商业建筑": ["框架结构", "钢结构", "框剪结构"],
        "基础设施": ["框架结构", "钢结构"],
        "公共建筑": ["框架结构", "框剪结构", "钢结构"],
    }
    # 各建筑类型常见面积范围（m²）
    type_area_range = {
        "学校": (5000, 50000), "医院": (8000, 80000), "办公楼": (10000, 100000),
        "住宅": (3000, 60000), "工业建筑": (2000, 30000), "商业建筑": (5000, 80000),
        "基础设施": (1000, 20000), "公共建筑": (3000, 40000),
    }
    # 各建筑类型常见楼层范围
    type_floors_range = {
        "学校": (3, 8), "医院": (5, 20), "办公楼": (8, 40), "住宅": (6, 33),
        "工业建筑": (1, 5), "商业建筑": (3, 12), "基础设施": (1, 4), "公共建筑": (3, 15),
    }
    # 各建筑类型常见装修标准
    type_decorations = {
        "学校": ["普通装修", "简单装修", "精装修"],
        "医院": ["普通装修", "精装修"],
        "办公楼": ["普通装修", "精装修", "豪华装修"],
        "住宅": ["简单装修", "普通装修", "精装修", "豪华装修"],
        "工业建筑": ["简单装修", "普通装修"],
        "商业建筑": ["普通装修", "精装修", "豪华装修"],
        "基础设施": ["简单装修"],
        "公共建筑": ["普通装修", "精装修"],
    }

    struct_coef = {"框架结构": 1.0, "框剪结构": 1.05, "剪力墙结构": 1.08, "砖混结构": 0.85, "钢结构": 1.25}
    region_coef = {"华北": 1.05, "华东": 1.12, "华南": 1.08, "华中": 0.95, "西南": 0.92, "西北": 0.88, "东北": 0.85}
    deco_coef = {"简单装修": 0.85, "普通装修": 1.0, "精装修": 1.25, "豪华装修": 1.6}

    # 均衡分配：每种建筑类型至少 floor(n/8) 条，余数轮流补
    per_type = n // len(project_types)
    remainder = n % len(project_types)
    type_counts = {pt: per_type + (1 if i < remainder else 0) for i, pt in enumerate(project_types)}

    rows = []
    idx = 0
    for pt in project_types:
        count = type_counts[pt]
        for _ in range(count):
            st = random.choice(type_structures[pt])
            rg = random.choice(regions)
            dc = random.choice(type_decorations[pt])
            area_min, area_max = type_area_range[pt]
            area = random.randint(area_min, area_max)
            floors_min, floors_max = type_floors_range[pt]
            floors = random.randint(floors_min, floors_max)
            year = random.randint(2020, 2025)

            unit_price = (base_prices[pt] * struct_coef[st] * region_coef[rg] *
                          deco_coef[dc] * random.uniform(0.92, 1.08))
            total_cost = unit_price * area

            # 费用构成（各类型略有差异）
            labor_ratio = 0.20 + random.uniform(-0.02, 0.02)
            material_ratio = 0.30 + random.uniform(-0.02, 0.02)
            machine_ratio = 0.10 + random.uniform(-0.01, 0.01)
            measure_ratio = 0.05
            mgmt_ratio = 0.08
            regulation_ratio = 0.05
            profit_ratio = 0.07
            tax_ratio = 0.04

            labor = total_cost * labor_ratio
            material = total_cost * material_ratio
            machine = total_cost * machine_ratio
            measure = total_cost * measure_ratio
            mgmt = total_cost * mgmt_ratio
            regulation = total_cost * regulation_ratio
            profit = total_cost * profit_ratio
            tax = total_cost * tax_ratio

            # 分部工程（各类型比例略有差异）
            foundation_ratio = 0.15 + random.uniform(-0.02, 0.02)
            main_structure_ratio = 0.40 + random.uniform(-0.03, 0.03)
            roofing_ratio = 0.05
            exterior_wall_ratio = 0.10 + random.uniform(-0.01, 0.01)

            foundation = total_cost * foundation_ratio
            main_structure = total_cost * main_structure_ratio
            roofing = total_cost * roofing_ratio
            exterior_wall = total_cost * exterior_wall_ratio

            # 材料耗量（按建筑类型差异化）
            if pt == "工业建筑":
                concrete_per_sqm = random.uniform(0.30, 0.45)
                steel_per_sqm = random.uniform(0.06, 0.09)
            elif pt == "住宅":
                concrete_per_sqm = random.uniform(0.42, 0.55)
                steel_per_sqm = random.uniform(0.045, 0.065)
            elif pt == "医院":
                concrete_per_sqm = random.uniform(0.48, 0.62)
                steel_per_sqm = random.uniform(0.05, 0.07)
            else:
                concrete_per_sqm = random.uniform(0.40, 0.55)
                steel_per_sqm = random.uniform(0.04, 0.07)
            concrete = area * concrete_per_sqm
            steel = area * steel_per_sqm
            block = area * random.uniform(0.2, 0.3)

            # 混凝土单方耗量字段（供 LR 模型训练）
            concrete_per_sqm_val = round(concrete_per_sqm, 4)

            rows.append({
                "项目名称": f"{pt}{rg}{year}年第{idx+1:03d}号项目",
                "建筑类型": pt,
                "结构类型": st,
                "总建筑面积": area,
                "楼层数": floors,
                "所在地区": rg,
                "建造年份": year,
                "装修标准": dc,
                "项目总造价": round(total_cost, 2),
                "单方造价": round(unit_price, 2),
                "人工费": round(labor, 2),
                "材料费": round(material, 2),
                "机械费": round(machine, 2),
                "措施费": round(measure, 2),
                "企业管理费": round(mgmt, 2),
                "规费": round(regulation, 2),
                "利润": round(profit, 2),
                "税金": round(tax, 2),
                "基础工程费": round(foundation, 2),
                "主体结构费": round(main_structure, 2),
                "屋面工程费": round(roofing, 2),
                "外墙工程费": round(exterior_wall, 2),
                "混凝土总用量": round(concrete, 2),
                "钢筋总用量": round(steel, 2),
                "砌块总用量": round(block, 2),
                "混凝土单方耗量": concrete_per_sqm_val,
            })
            idx += 1

    # 打乱顺序，避免按类型聚集
    random.shuffle(rows)

    df = pd.DataFrame(rows)
    df.to_excel(output_path, index=False, engine="openpyxl")
    return len(rows)


if __name__ == "__main__":
    n = generate_sample_excel("data/sample_training_data.xlsx", 80)
    print(f"已生成 {n} 条示例数据到 data/sample_training_data.xlsx")
    # 验证类型分布
    df = pd.read_excel("data/sample_training_data.xlsx")
    print("\n建筑类型分布:")
    print(df["建筑类型"].value_counts().to_string())
