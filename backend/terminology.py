"""
建筑造价术语规范模块
参考: https://www.ahua.edu.cn/sjc/2025/0918/c834a42898/page.htm
建设工程"五算"解析：估算、概算、预算、结算、决算
"""
from typing import Dict, List

# ===== 三阶段造价精度定义 =====
COST_STAGES: Dict[str, Dict] = {
    "estimation": {
        "name": "估算阶段",
        "description": "快速概览项目投资规模",
        "accuracy": "70-80%",
        "error_rate": "±20%",
        "applicable": "项目前期可行性研究 / 投资决策参考",
        "basis": "类比估算 + 经验数据"
    },
    "preliminary": {
        "name": "概算阶段",
        "description": "初步设计阶段的成本测算",
        "accuracy": "80-90%",
        "error_rate": "±10%",
        "applicable": "初步设计阶段 / 投资控制基准",
        "basis": "初步设计图纸 + 方案"
    },
    "budget": {
        "name": "预算阶段",
        "description": "施工图设计阶段的精确测算",
        "accuracy": "95%+",
        "error_rate": "±3%",
        "applicable": "施工图设计 / 招投标与合同签订依据",
        "basis": "详细设计图纸 + 工程量清单"
    }
}

# ===== 六层级成本分解 =====
COST_HIERARCHY: List[Dict] = [
    {"level": 1, "name": "项目总造价", "code": "total", "description": "整个建设项目的总投资"},
    {"level": 2, "name": "单项工程", "code": "single_project", "description": "具有独立设计文件、可独立发挥生产能力或效益的工程"},
    {"level": 3, "name": "单位工程", "code": "unit_project", "description": "具有独立施工图、可独立施工的工程，如土建工程、安装工程"},
    {"level": 4, "name": "分部工程", "code": "section_project", "description": "按工程部位或工种划分的工程，如基础工程、主体结构、屋面工程"},
    {"level": 5, "name": "分项工程", "code": "item_project", "description": "按主要工种、材料、施工工艺等划分的工程，如混凝土工程、钢筋工程"},
    {"level": 6, "name": "明细级别", "code": "detail_level", "description": "工程量清单中最基本的造价构成单元"}
]

# ===== 工程类别 =====
PROJECT_TYPES: List[Dict] = [
    {"code": "school", "name": "学校", "icon": "school"},
    {"code": "hospital", "name": "医院", "icon": "hospital"},
    {"code": "office", "name": "办公楼", "icon": "office"},
    {"code": "residential", "name": "住宅", "icon": "home"},
    {"code": "industrial", "name": "工业建筑", "icon": "factory"},
    {"code": "commercial", "name": "商业建筑", "icon": "shop"},
    {"code": "infrastructure", "name": "基础设施", "icon": "road"},
    {"code": "public", "name": "公共建筑", "icon": "building"}
]

# ===== 结构类型 =====
STRUCTURE_TYPES: List[str] = [
    "框架结构", "框剪结构", "剪力墙结构", "砖混结构",
    "钢结构", "木结构", "框架-核心筒", "筒中筒"
]

# ===== 费用构成（参考建设工程费用划分）=====
COST_COMPOSITION: Dict = {
    "direct_cost": {
        "name": "直接工程费",
        "ratio_range": [55, 70],
        "items": [
            {"name": "人工费", "ratio": 20, "unit": "元/m²", "description": "直接从事建筑安装工程施工的生产工人开支"},
            {"name": "材料费", "ratio": 30, "unit": "元/m²", "description": "施工过程中耗用的构成工程实体的原材料、辅助材料等"},
            {"name": "机械费", "ratio": 10, "unit": "元/m²", "description": "施工机械作业所发生的机械使用费及场外运费"},
            {"name": "措施费", "ratio": 5, "unit": "元/m²", "description": "为完成工程项目施工发生于该工程施工前和施工过程中的技术、生活、安全等方面的非工程实体项目费用"}
        ]
    },
    "indirect_cost": {
        "name": "间接费",
        "ratio_range": [15, 25],
        "items": [
            {"name": "企业管理费", "ratio": 8, "unit": "元/m²", "description": "建筑安装企业组织施工生产和经营管理所需费用"},
            {"name": "规费", "ratio": 5, "unit": "元/m²", "description": "政府和有关部门规定必须缴纳的费用"},
            {"name": "其他间接费", "ratio": 2, "unit": "元/m²", "description": "其他间接性费用支出"}
        ]
    },
    "profit": {
        "name": "利润",
        "ratio_range": [5, 10],
        "items": [
            {"name": "施工利润", "ratio": 7, "unit": "元/m²", "description": "施工企业完成所承包工程获得的盈利"}
        ]
    },
    "tax": {
        "name": "税金",
        "ratio_range": [3, 5],
        "items": [
            {"name": "增值税及附加", "ratio": 4, "unit": "元/m²", "description": "国家税法规定应计入建筑安装工程造价内的增值税及附加税费"}
        ]
    }
}

# ===== 计价方式 =====
PRICING_METHODS: List[Dict] = [
    {
        "code": "bill_of_quantities",
        "name": "工程量清单计价法",
        "description": "根据《建设工程工程量清单计价规范》计算，使用国有资金的项目必须采用",
        "applicable": "施工图预算、招投标阶段",
        "advantages": "适应市场经济条件，体现竞争机制"
    },
    {
        "code": "quota_unit_price",
        "name": "定额单价法",
        "description": "套用地区单位估价表，根据定额规定的人工、材料、机械台班消耗量和单价计算",
        "applicable": "设计概算、施工图预算",
        "advantages": "计算简便，便于核算"
    },
    {
        "code": "physical_method",
        "name": "实物法",
        "description": "根据人工、材料、机械台班的市场价及有关部门发布的其它费用的计价依据按实计算",
        "applicable": "市场化程度高的项目",
        "advantages": "更准确反映实际成本"
    }
]

# ===== 参数分类（估算阶段7参数 / 概算24参数 / 预算24参数）=====
ESTIMATION_PARAMS = {
    "基础参数": [
        {"key": "project_type", "label": "建筑类型", "type": "select", "options": [p["name"] for p in PROJECT_TYPES]},
        {"key": "structure_type", "label": "结构类型", "type": "select", "options": STRUCTURE_TYPES},
        {"key": "total_area", "label": "总建筑面积(㎡)", "type": "number"},
        {"key": "floors", "label": "楼层数", "type": "number"},
        {"key": "location", "label": "所在地区", "type": "select", "options": ["华北", "华东", "华南", "华中", "西南", "西北", "东北"]},
        {"key": "build_year", "label": "建造年份", "type": "number"},
        {"key": "decoration_level", "label": "装修标准", "type": "select", "options": ["毛坯", "一般装修", "精装修", "豪华装修"]},
    ],
}

PRELIMINARY_PARAMS = {
    "基础参数": [
        {"key": "total_area", "label": "总建筑面积(㎡)", "type": "number"},
        {"key": "floors", "label": "地上楼层数", "type": "number"},
        {"key": "basement_area", "label": "地下室面积(㎡)", "type": "number"},
        {"key": "building_height", "label": "建筑高度(m)", "type": "number"},
        {"key": "build_year", "label": "建造年份", "type": "number"},
        {"key": "duration", "label": "工期(月)", "type": "number"},
    ],
    "结构参数": [
        {"key": "foundation_type", "label": "基础形式", "type": "select", "options": ["独立基础", "筏板基础", "桩基础", "条形基础"]},
        {"key": "seismic_grade", "label": "抗震等级", "type": "select", "options": ["特一级", "一级", "二级", "三级", "四级"]},
        {"key": "concrete_grade", "label": "混凝土等级", "type": "select", "options": ["C25", "C30", "C35", "C40", "C50"]},
        {"key": "steel_grade", "label": "钢筋等级", "type": "select", "options": ["HRB335", "HRB400", "HRB500"]},
        {"key": "soil_condition", "label": "地质条件", "type": "select", "options": ["良好", "一般", "较差", "复杂"]},
        {"key": "special_equipment", "label": "特殊设备", "type": "select", "options": ["无", "少量", "较多", "大量"]},
    ],
    "系统参数": [
        {"key": "hvac", "label": "暖通空调", "type": "select", "options": ["无", "分体空调", "中央空调", "多联机"]},
        {"key": "elevator", "label": "电梯配置", "type": "select", "options": ["无", "普通客梯", "高速客梯", "观光梯"]},
        {"key": "fire_system", "label": "消防系统", "type": "select", "options": ["基本", "标准", "高级", "特级"]},
        {"key": "smart_building", "label": "智能化", "type": "select", "options": ["无", "基本", "标准", "高级"]},
        {"key": "parking_ratio", "label": "车位配比(车位/百㎡)", "type": "number"},
        {"key": "green_rating", "label": "绿色等级", "type": "select", "options": ["无", "一星", "二星", "三星"]},
    ],
    "装修参数": [
        {"key": "decoration_level", "label": "装修标准", "type": "select", "options": ["毛坯", "一般装修", "精装修", "豪华装修"]},
        {"key": "exterior_wall", "label": "外墙装饰", "type": "select", "options": ["涂料", "面砖", "石材", "幕墙"]},
        {"key": "roof_type", "label": "屋面做法", "type": "select", "options": ["平屋面", "坡屋面", "种植屋面", "金属屋面"]},
        {"key": "window_type", "label": "门窗类型", "type": "select", "options": ["塑钢", "断桥铝", "铝合金", "幕墙窗"]},
        {"key": "elevator_count", "label": "电梯数量", "type": "number"},
        {"key": "parking_count", "label": "车位数量", "type": "number"},
    ],
}

BUDGET_PARAMS = {
    "基础参数": [
        {"key": "total_area", "label": "总建筑面积(㎡)", "type": "number"},
        {"key": "floors", "label": "地上楼层数", "type": "number"},
        {"key": "basement_area", "label": "地下室面积(㎡)", "type": "number"},
        {"key": "building_height", "label": "建筑高度(m)", "type": "number"},
        {"key": "build_year", "label": "建造年份", "type": "number"},
        {"key": "duration", "label": "工期(月)", "type": "number"},
    ],
    "结构参数": [
        {"key": "foundation_type", "label": "基础形式", "type": "select", "options": ["独立基础", "筏板基础", "桩基础", "条形基础"]},
        {"key": "seismic_grade", "label": "抗震等级", "type": "select", "options": ["特一级", "一级", "二级", "三级", "四级"]},
        {"key": "concrete_grade", "label": "混凝土等级", "type": "select", "options": ["C25", "C30", "C35", "C40", "C50"]},
        {"key": "steel_grade", "label": "钢筋等级", "type": "select", "options": ["HRB335", "HRB400", "HRB500"]},
        {"key": "soil_condition", "label": "地质条件", "type": "select", "options": ["良好", "一般", "较差", "复杂"]},
        {"key": "special_equipment", "label": "特殊设备", "type": "select", "options": ["无", "少量", "较多", "大量"]},
    ],
    "系统参数": [
        {"key": "hvac", "label": "暖通空调", "type": "select", "options": ["无", "分体空调", "中央空调", "多联机"]},
        {"key": "elevator", "label": "电梯配置", "type": "select", "options": ["无", "普通客梯", "高速客梯", "观光梯"]},
        {"key": "fire_system", "label": "消防系统", "type": "select", "options": ["基本", "标准", "高级", "特级"]},
        {"key": "smart_building", "label": "智能化", "type": "select", "options": ["无", "基本", "标准", "高级"]},
        {"key": "parking_ratio", "label": "车位配比(车位/百㎡)", "type": "number"},
        {"key": "green_rating", "label": "绿色等级", "type": "select", "options": ["无", "一星", "二星", "三星"]},
    ],
    "装修参数": [
        {"key": "decoration_level", "label": "装修标准", "type": "select", "options": ["毛坯", "一般装修", "精装修", "豪华装修"]},
        {"key": "exterior_wall", "label": "外墙装饰", "type": "select", "options": ["涂料", "面砖", "石材", "幕墙"]},
        {"key": "roof_type", "label": "屋面做法", "type": "select", "options": ["平屋面", "坡屋面", "种植屋面", "金属屋面"]},
        {"key": "window_type", "label": "门窗类型", "type": "select", "options": ["塑钢", "断桥铝", "铝合金", "幕墙窗"]},
        {"key": "elevator_count", "label": "电梯数量", "type": "number"},
        {"key": "parking_count", "label": "车位数量", "type": "number"},
    ],
}

# ===== 地区造价指数（基于行业经验）=====
REGION_COST_INDEX: Dict[str, float] = {
    "华北": 1.05,
    "华东": 1.12,
    "华南": 1.08,
    "华中": 0.95,
    "西南": 0.92,
    "西北": 0.88,
    "东北": 0.85
}

# ===== 建筑类型单方造价基准（元/m²）=====
BASE_UNIT_PRICE: Dict[str, float] = {
    "学校": 3500,
    "医院": 4500,
    "办公楼": 4000,
    "住宅": 3200,
    "工业建筑": 2800,
    "商业建筑": 5000,
    "基础设施": 2500,
    "公共建筑": 3800
}

# ===== 结构类型造价修正系数 =====
STRUCTURE_COEFFICIENT: Dict[str, float] = {
    "框架结构": 1.00,
    "框剪结构": 1.05,
    "剪力墙结构": 1.08,
    "砖混结构": 0.85,
    "钢结构": 1.25,
    "木结构": 1.40,
    "框架-核心筒": 1.15,
    "筒中筒": 1.20
}

# ===== 装修标准修正系数 =====
DECORATION_COEFFICIENT: Dict[str, float] = {
    "简单装修": 0.85,
    "普通装修": 1.00,
    "精装修": 1.25,
    "豪华装修": 1.60
}

# ===== 模型清单（三层多维度融合架构，通用适配 8 种建筑类型）=====
# 建筑类型：学校/医院/办公楼/住宅/工业建筑/商业建筑/基础设施/公共建筑
MODELS_REGISTRY: List[Dict] = [
    # ── L1 总造价层：双模型加权融合 ──
    {
        "id": "total_pso_svr",
        "name": "建筑安装_总造价_[通用]_[PSO-SVR]",
        "version": "V1.0",
        "algorithm": "PSO-SVR",
        "accuracy": 86.9,
        "layer": "总造价预测模型",
        "description": "基于PSO优化SVR的多类型建筑单方造价预测模型（L1主模型），支持学校/医院/办公楼/住宅/工业/商业/基础设施/公共建筑",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    {
        "id": "unit_gbt",
        "name": "单位工程_(单方造价)_[通用]_[Gradient Boosting Tree]",
        "version": "V1.0",
        "algorithm": "Gradient Boosting Tree",
        "accuracy": 74.6,
        "layer": "总造价预测模型",
        "description": "基于梯度提升树的多类型单方造价预测模型（L1辅助模型），与PSO-SVR加权融合",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    # ── L2 专业/分部/材料层：三维结构分解 ──
    {
        "id": "section_xgb",
        "name": "专业占比_建筑/装饰/安装_[通用]_[MultiOutput XGBoost]",
        "version": "V1.0",
        "algorithm": "MultiOutput XGBoost",
        "accuracy": 51.6,
        "layer": "分部/分项工程模型",
        "description": "基于MultiOutput XGBoost的专业造价占比预测（建筑/装饰/安装），实现L2专业维度分解",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    {
        "id": "subsection_xgb",
        "name": "分部占比_基础/主体/屋面/外墙_[通用]_[MultiOutput XGBoost]",
        "version": "V1.0",
        "algorithm": "MultiOutput XGBoost",
        "accuracy": 36.7,
        "layer": "分部/分项工程模型",
        "description": "基于MultiOutput XGBoost的分部造价占比预测（基础/主体/屋面/外墙），实现L2分部维度分解",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    {
        "id": "item_xgb",
        "name": "材料耗量_混凝土/钢筋/砌块_[通用]_[MultiOutput XGBoost]",
        "version": "V1.0",
        "algorithm": "MultiOutput XGBoost",
        "accuracy": 39.4,
        "layer": "分部/分项工程模型",
        "description": "基于MultiOutput XGBoost的材料的单方耗量预测（混凝土/钢筋/砌块），实现L2材料维度分解",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    # ── L3 清单/指标层：微观预测 ──
    {
        "id": "indicator_rf",
        "name": "指标体系_人工费/基础/主体占比_[通用]_[MultiOutput RF]",
        "version": "V1.0",
        "algorithm": "MultiOutput Random Forest",
        "accuracy": 60.3,
        "layer": "清单项目模型",
        "description": "基于MultiOutput Random Forest的经济技术指标预测（人工费/基础/主体占比），L3指标体系",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    {
        "id": "boq_xgb",
        "name": "清单项目_XGBoost_[通用]_[XGBoost]",
        "version": "V1.0",
        "algorithm": "XGBoost",
        "accuracy": 73.7,
        "layer": "清单项目模型",
        "description": "基于XGBoost的清单项目综合单价预测模型（item级），L3 BOQ主模型",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    },
    {
        "id": "boq_lr_v2",
        "name": "清单项目_LR_[通用]_[Linear Regression]",
        "version": "V1.0",
        "algorithm": "Linear Regression",
        "accuracy": 68.3,
        "layer": "清单项目模型",
        "description": "基于线性回归的清单项目综合单价预测模型（item级，可解释对照），L3 BOQ辅助模型",
        "supported_types": ["学校", "医院", "办公楼", "住宅", "工业建筑", "商业建筑", "基础设施", "公共建筑"]
    }
]


def get_stage_info(stage: str) -> Dict:
    """获取阶段信息"""
    return COST_STAGES.get(stage, {})


def get_param_categories(stage: str = "estimation"):
    """获取参数分类，动态从实际参数列表计算"""
    params_map = {
        "estimation": ESTIMATION_PARAMS,
        "preliminary": PRELIMINARY_PARAMS,
        "budget": BUDGET_PARAMS,
    }
    stage_params = params_map.get(stage, ESTIMATION_PARAMS)
    categories = []
    total = 0
    for cat_name, param_list in stage_params.items():
        categories.append({"name": cat_name, "count": len(param_list), "params": param_list})
        total += len(param_list)
    return {"categories": categories, "total": total}
