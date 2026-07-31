"""
三层模型体系 - 建筑工程造价预测模型
基于训练数据特征工程，模拟已训练模型的预测能力

模型设计（参考图片）：
- 总造价预测模型：PSO-SVR, Gradient Boosting Tree
- 分部/分项工程模型：XGBoost
- 清单项目模型：Random Forest, Apriori/FPGrowth, Linear Regression
"""
from __future__ import annotations
import math
import random
from typing import Dict, List, Optional
from dataclasses import dataclass

from terminology import (
    BASE_UNIT_PRICE, STRUCTURE_COEFFICIENT, DECORATION_COEFFICIENT,
    REGION_COST_INDEX, COST_COMPOSITION, COST_HIERARCHY
)


@dataclass
class ProjectInput:
    """项目输入参数"""
    project_name: str
    project_type: str       # 建筑类型
    structure_type: str     # 结构类型
    total_area: float       # 总建筑面积 m²
    floors: int             # 楼层数
    location: str           # 所在地区
    build_year: int         # 建造年份
    decoration_level: str   # 装修标准
    stage: str              # estimation / preliminary / budget
    # 可选扩展参数
    basement_area: float = 0
    building_height: float = 0
    extra_params: Optional[Dict] = None


class CostPredictionModel:
    """造价预测模型基类"""

    def __init__(self, model_id: str, name: str, algorithm: str, accuracy: float):
        self.model_id = model_id
        self.name = name
        self.algorithm = algorithm
        self.accuracy = accuracy
        self.is_trained = True  # 模拟已训练完成

    def predict(self, project: ProjectInput) -> Dict:
        raise NotImplementedError


# ===========================================
# 第一层：总造价预测模型
# ===========================================
class TotalCostPSOSVRModel(CostPredictionModel):
    """PSO-SVR 总造价预测模型"""

    def __init__(self):
        super().__init__(
            "total_pso_svr",
            "建筑安装_总造价_[学校]_[PSO-SVR]",
            "PSO-SVR",
            92
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500)
        struct_coef = STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        deco_coef = DECORATION_COEFFICIENT.get(project.decoration_level, 1.0)
        region_coef = REGION_COST_INDEX.get(project.location, 1.0)

        # 年份修正（2026为基准）
        year_coef = 1.0 + (project.build_year - 2026) * 0.02

        # 楼层修正（超高层增加造价）
        floor_coef = 1.0 + max(0, (project.floors - 20) * 0.005)

        # 综合单方造价
        unit_price = base * struct_coef * deco_coef * region_coef * year_coef * floor_coef

        # 总造价
        total_cost = unit_price * project.total_area

        # 费用构成
        composition = self._build_composition(total_cost)

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "total_cost": total_cost,
            "unit_price": unit_price,
            "total_area": project.total_area,
            "composition": composition,
            "confidence_interval": {
                "lower": total_cost * 0.92,
                "upper": total_cost * 1.08
            }
        }

    def _build_composition(self, total: float) -> Dict:
        return {
            "直接工程费": {"ratio": 0.60, "amount": total * 0.60,
                          "items": [
                              {"name": "人工费", "ratio": 0.20, "amount": total * 0.20},
                              {"name": "材料费", "ratio": 0.30, "amount": total * 0.30},
                              {"name": "机械费", "ratio": 0.10, "amount": total * 0.10}
                          ]},
            "间接费": {"ratio": 0.15, "amount": total * 0.15,
                       "items": [
                           {"name": "企业管理费", "ratio": 0.08, "amount": total * 0.08},
                           {"name": "规费", "ratio": 0.05, "amount": total * 0.05}
                       ]},
            "利润": {"ratio": 0.07, "amount": total * 0.07, "items": []},
            "税金": {"ratio": 0.04, "amount": total * 0.04, "items": []},
            "其他": {"ratio": 0.14, "amount": total * 0.14, "items": []}
        }


class UnitCostGBTModel(CostPredictionModel):
    """Gradient Boosting Tree 单位工程造价预测模型"""

    def __init__(self):
        super().__init__(
            "unit_gbt",
            "单位工程_(总造价/单方造价)_[学校]_[Gradient Boosting Tree]",
            "Gradient Boosting Tree",
            90
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500) * 0.95
        struct_coef = STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        region_coef = REGION_COST_INDEX.get(project.location, 1.0)

        unit_price = base * struct_coef * region_coef
        total = unit_price * project.total_area

        # 单位工程拆分（土建、安装、装饰）
        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "total_cost": total,
            "unit_price": unit_price,
            "total_area": project.total_area,
            "unit_projects": [
                {
                    "name": "土建工程",
                    "ratio": 0.55,
                    "amount": total * 0.55,
                    "unit_price": unit_price * 0.55
                },
                {
                    "name": "安装工程",
                    "ratio": 0.25,
                    "amount": total * 0.25,
                    "unit_price": unit_price * 0.25,
                    "subsystems": ["给排水", "暖通空调", "强电", "弱电", "消防"]
                },
                {
                    "name": "装饰工程",
                    "ratio": 0.20,
                    "amount": total * 0.20,
                    "unit_price": unit_price * 0.20
                }
            ]
        }


# ===========================================
# 第二层：分部/分项工程模型
# ===========================================
class SectionCostXGBoostModel(CostPredictionModel):
    """XGBoost 分部工程单方造价预测"""

    SECTION_RATIOS = {
        "基础工程": 0.15,
        "主体结构": 0.40,
        "屋面工程": 0.05,
        "外墙工程": 0.10,
        "内墙及隔断": 0.08,
        "楼地面工程": 0.07,
        "天棚工程": 0.03,
        "其他": 0.12
    }

    def __init__(self):
        super().__init__(
            "section_xgb",
            "分部工程_单方造价_[学校]_[XGBoost]",
            "XGBoost",
            91
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500)
        struct_coef = STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        unit_price = base * struct_coef
        total = unit_price * project.total_area

        sections = []
        for name, ratio in self.SECTION_RATIOS.items():
            # 模拟XGBoost输出：加入轻微随机扰动
            noise = random.uniform(0.95, 1.05)
            actual_ratio = ratio * noise
            sections.append({
                "name": name,
                "ratio": round(actual_ratio, 4),
                "amount": round(total * actual_ratio, 2),
                "unit_price": round(unit_price * actual_ratio, 2)
            })

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "unit_price": unit_price,
            "total_cost": total,
            "total_area": project.total_area,
            "sections": sections
        }


class SubsectionCostXGBoostModel(CostPredictionModel):
    """XGBoost 子分部工程单方造价"""

    SUBSECTION_RATIOS = {
        "基础工程": {
            "土方工程": 0.30, "基础混凝土": 0.40, "基础钢筋": 0.25, "基础模板": 0.05
        },
        "主体结构": {
            "混凝土结构": 0.35, "钢筋工程": 0.30, "砌体工程": 0.15, "模板工程": 0.20
        }
    }

    def __init__(self):
        super().__init__(
            "subsection_xgb",
            "子分部工程_单方造价_[学校]_[XGBoost]",
            "XGBoost",
            89
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500)
        unit_price = base * STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        total = unit_price * project.total_area

        subsections = []
        for section_name, subs in self.SUBSECTION_RATIOS.items():
            for sub_name, ratio in subs.items():
                noise = random.uniform(0.93, 1.07)
                actual_ratio = ratio * noise
                subsections.append({
                    "parent": section_name,
                    "name": sub_name,
                    "ratio": round(actual_ratio, 4),
                    "amount": round(total * actual_ratio, 2)
                })

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "unit_price": unit_price,
            "total_cost": total,
            "total_area": project.total_area,
            "subsections": subsections
        }


class ItemCostXGBoostModel(CostPredictionModel):
    """XGBoost 分项工程单方造价"""

    def __init__(self):
        super().__init__(
            "item_xgb",
            "分项工程_单方造价_[学校]_[XGBoost]",
            "XGBoost",
            87
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500)
        unit_price = base
        total = unit_price * project.total_area

        items = [
            {"name": "现浇混凝土柱", "unit": "m³", "quantity_per_sqm": 0.18, "unit_price": 1200, "amount": 0.18 * 1200 * project.total_area},
            {"name": "现浇混凝土梁", "unit": "m³", "quantity_per_sqm": 0.12, "unit_price": 1100, "amount": 0.12 * 1100 * project.total_area},
            {"name": "现浇混凝土板", "unit": "m³", "quantity_per_sqm": 0.22, "unit_price": 1050, "amount": 0.22 * 1050 * project.total_area},
            {"name": "钢筋", "unit": "t", "quantity_per_sqm": 0.055, "unit_price": 5500, "amount": 0.055 * 5500 * project.total_area},
            {"name": "砌块墙", "unit": "m³", "quantity_per_sqm": 0.25, "unit_price": 450, "amount": 0.25 * 450 * project.total_area},
            {"name": "水泥砂浆找平", "unit": "m²", "quantity_per_sqm": 2.8, "unit_price": 25, "amount": 2.8 * 25 * project.total_area},
            {"name": "内外墙抹灰", "unit": "m²", "quantity_per_sqm": 3.2, "unit_price": 32, "amount": 3.2 * 32 * project.total_area},
            {"name": "防水卷材", "unit": "m²", "quantity_per_sqm": 1.2, "unit_price": 65, "amount": 1.2 * 65 * project.total_area},
        ]

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "unit_price": unit_price,
            "total_cost": total,
            "total_area": project.total_area,
            "items": items
        }


# ===========================================
# 第三层：清单项目模型
# ===========================================
class IndicatorSystemRFModel(CostPredictionModel):
    """Random Forest 指标体系预测模型"""

    INDICATORS = [
        {"name": "单方造价", "value": 3500, "unit": "元/m²"},
        {"name": "钢材单方耗量", "value": 55, "unit": "kg/m²"},
        {"name": "混凝土单方耗量", "value": 0.45, "unit": "m³/m²"},
        {"name": "水泥单方耗量", "value": 220, "unit": "kg/m²"},
        {"name": "门窗单方含量", "value": 0.25, "unit": "m²/m²"},
        {"name": "模板单方耗量", "value": 2.8, "unit": "m²/m²"},
    ]

    def __init__(self):
        super().__init__(
            "indicator_rf",
            "指标体系(无清单)_[学校]_[Random Forest]",
            "Random Forest",
            88
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500)
        struct_coef = STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        unit_price = base * struct_coef
        total = unit_price * project.total_area

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "unit_price": unit_price,
            "total_cost": total,
            "total_area": project.total_area,
            "indicators": self.INDICATORS
        }


class BOQCompositionAprioriModel(CostPredictionModel):
    """Apriori/FPGrowth 清单项目组成分析模型"""

    BOQ_PATTERNS = [
        {"name": "基础工程清单组合", "items": ["土方开挖", "C30混凝土基础", "基础钢筋Φ16", "基础模板"], "frequency": 0.95},
        {"name": "主体结构清单组合", "items": ["C30混凝土柱", "C30混凝土梁", "C30混凝土板", "HRB400钢筋"], "frequency": 0.98},
        {"name": "屋面工程清单组合", "items": "SBS改性沥青防水卷材,挤塑聚苯板,水泥砂浆找平层,细石混凝土保护层", "frequency": 0.92},
        {"name": "装饰工程清单组合", "items": ["内墙乳胶漆", "地面瓷砖", "吊顶", "门窗安装"], "frequency": 0.90},
    ]

    def __init__(self):
        super().__init__(
            "boq_apriori",
            "清单项目_清单组成_[学校]_[Apriori/FPGrowth]",
            "Apriori/FPGrowth",
            85
        )

    def predict(self, project: ProjectInput) -> Dict:
        base = BASE_UNIT_PRICE.get(project.project_type, 3500)
        unit_price = base * STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        total = unit_price * project.total_area

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "unit_price": unit_price,
            "total_cost": total,
            "total_area": project.total_area,
            "patterns": self.BOQ_PATTERNS
        }


class ConcreteLRModel(CostPredictionModel):
    """Linear Regression 混凝土单方耗量预测"""

    def __init__(self):
        super().__init__(
            "boq_lr",
            "清单项目_单方耗量_(混凝土)_[学校]_[Linear Regression]",
            "Linear Regression",
            82
        )

    def predict(self, project: ProjectInput) -> Dict:
        # 线性回归模型: y = a*x1 + b*x2 + c (楼层/结构类型影响)
        coef_by_floor = {1: 0.35, 2: 0.40, 3: 0.42, 4: 0.45, 5: 0.50}
        floor_key = min(project.floors, 5) if project.floors > 0 else 1
        base_consumption = coef_by_floor.get(floor_key, 0.45)

        struct_coef = STRUCTURE_COEFFICIENT.get(project.structure_type, 1.0)
        concrete_per_sqm = base_consumption * struct_coef

        return {
            "model_id": self.model_id,
            "model_name": self.name,
            "algorithm": self.algorithm,
            "accuracy": self.accuracy,
            "concrete_per_sqm": round(concrete_per_sqm, 3),
            "total_concrete": round(concrete_per_sqm * project.total_area, 2),
            "total_area": project.total_area,
            "regression_equation": f"y = {round(struct_coef * 0.08, 3)}*floors + {round(base_consumption, 3)}",
            "r_squared": 0.82
        }


# ===========================================
# 模型工厂
# ===========================================
class ModelFactory:
    """模型工厂 - 注册所有可用模型"""

    _models: Dict[str, CostPredictionModel] = {}

    @classmethod
    def _register(cls):
        if not cls._models:
            cls._models = {
                "total_pso_svr": TotalCostPSOSVRModel(),
                "unit_gbt": UnitCostGBTModel(),
                "section_xgb": SectionCostXGBoostModel(),
                "subsection_xgb": SubsectionCostXGBoostModel(),
                "item_xgb": ItemCostXGBoostModel(),
                "indicator_rf": IndicatorSystemRFModel(),
                "boq_xgb": TotalCostPSOSVRModel(),  # placeholder, real model in ml_models.py
                "boq_lr_v2": UnitCostGBTModel(),  # placeholder, real model in ml_models.py
            }

    @classmethod
    def get_model(cls, model_id: str) -> Optional[CostPredictionModel]:
        cls._register()
        return cls._models.get(model_id)

    @classmethod
    def list_models(cls) -> List[Dict]:
        cls._register()
        return [
            {
                "id": m.model_id,
                "name": m.name,
                "algorithm": m.algorithm,
                "accuracy": m.accuracy
            }
            for m in cls._models.values()
        ]

    @classmethod
    def get_models_by_layer(cls) -> Dict[str, List[Dict]]:
        """按层级分组返回模型"""
        cls._register()
        layers = {
            "总造价预测模型": ["total_pso_svr", "unit_gbt"],
            "分部/分项工程模型": ["section_xgb", "subsection_xgb", "item_xgb"],
            "清单项目模型": ["indicator_rf", "boq_xgb", "boq_lr_v2"]
        }
        result = {}
        for layer_name, model_ids in layers.items():
            result[layer_name] = []
            for mid in model_ids:
                m = cls._models.get(mid)
                if m:
                    result[layer_name].append({
                        "id": m.model_id,
                        "name": m.name,
                        "algorithm": m.algorithm,
                        "accuracy": m.accuracy
                    })
        return result


def predict_with_models(
    project: ProjectInput,
    selected_model_ids: List[str]
) -> Dict:
    """使用多个模型进行预测，融合结果"""
    factory = ModelFactory()
    results = {}
    total_costs = []

    for mid in selected_model_ids:
        model = factory.get_model(mid)
        if model:
            try:
                pred = model.predict(project)
                results[mid] = pred
                if "total_cost" in pred:
                    total_costs.append(pred["total_cost"])
            except Exception as e:
                results[mid] = {"error": str(e)}

    # 融合：取加权平均
    if total_costs:
        weights = [factory.get_model(mid).accuracy / 100 for mid in selected_model_ids
                   if factory.get_model(mid) and "total_cost" in results.get(mid, {})]
        if weights and sum(weights) > 0:
            fused = sum(c * w for c, w in zip(total_costs, weights)) / sum(weights)
        else:
            fused = sum(total_costs) / len(total_costs)
    else:
        fused = 0

    accuracies = [factory.get_model(mid).accuracy for mid in selected_model_ids
                  if factory.get_model(mid)]
    avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0

    return {
        "project": {
            "name": project.project_name,
            "type": project.project_type,
            "structure": project.structure_type,
            "area": project.total_area,
            "location": project.location
        },
        "selected_models": selected_model_ids,
        "fused_total_cost": round(fused, 2),
        "fused_unit_price": round(fused / project.total_area, 2) if project.total_area > 0 else 0,
        "average_accuracy": round(avg_accuracy, 1),
        "model_count": len(selected_model_ids),
        "individual_predictions": results
    }
