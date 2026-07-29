"""
数据加载器 - Excel 批量导入历史项目训练数据
"""
from __future__ import annotations
import io
import os
import json
import random
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd


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


class DataLoader:
    """训练数据加载器"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.history: List[Dict] = []
        os.makedirs(data_dir, exist_ok=True)
        self._load_existing()

    def _load_existing(self):
        """加载已有数据"""
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
        self._save()
        return {
            "success": True,
            "imported_count": len(imported),
            "total_count": len(self.history),
            "samples": imported[:3]
        }

    def _save(self):
        history_file = os.path.join(self.data_dir, "history.json")
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self.history[-limit:]

    def to_dataframe(self):
        """转换为 pandas DataFrame 供训练使用"""
        if not self.history:
            return None
        try:
            return pd.DataFrame(self.history)
        except Exception as e:
            print(f"[to_dataframe] {e}")
            return None

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
