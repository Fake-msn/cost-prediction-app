"""
动态模型置信度引擎 (Dynamic Confidence Engine)

将单一固定准确率 (CV R²) 替换为"基础值 + 向导参数附加范围"的动态精度。

用户通过向导/对话流程补充的专业参数（foundation_type, seismic_grade 等）
虽然不在模型训练特征集中，但包含了行业经验信息——当用户提供这些参数时，
系统对预测结果的可信度应当提升。

用法:
    engine = ConfidenceEngine()
    assessment = engine.assess("subsection_xgb", project_data, base_accuracy=0.0)
    # => ConfidenceAssessment(base=0, bonus=15, effective=15, breakdown={"foundation_type": 15})
"""
import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceAssessment:
    """单模型的置信度评估结果"""
    base_accuracy: float            # CV R² × 100（训练数据得出的原始精度）
    input_bonus: float              # 向导参数贡献的额外置信度
    effective_accuracy: float       # min(base + bonus, 100)
    max_potential_bonus: float      # 所有关联参数都填满时的理论最大 bonus
    breakdown: Dict[str, float]     # {"foundation_type": 15.0, "seismic_grade": 5.0, ...}
    filled_params: int = 0          # 实际填写了的参数个数
    total_params: int = 0           # 该模型的 bonus_rules 参数总数

    def to_dict(self) -> Dict:
        return asdict(self)


class ConfidenceEngine:
    """动态置信度评估引擎

    从 confidence_coefficients.json 加载经验系数配置，
    根据用户提供的向导参数计算每个模型的动态置信度。
    """

    # 向导参数名 → 多个可能的参数名映射（处理前端/后端命名差异）
    PARAM_ALIASES: Dict[str, List[str]] = {
        "foundation_type": ["foundation_type", "基础形式", "基础类型", "基础类别"],
        "seismic_grade":   ["seismic_grade", "抗震等级"],
        "soil_condition":  ["soil_condition", "地质条件", "土质条件"],
    }

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "confidence_coefficients.json"
            )
        self._config: Dict = {}
        self._loaded = False
        self._load_config(config_path)

    def _load_config(self, config_path: str):
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                self._loaded = True
                logger.info(f"[ConfidenceEngine] 加载配置: {config_path} "
                           f"(version={self._config.get('version', '?')})")
            else:
                logger.warning(f"[ConfidenceEngine] 配置文件不存在: {config_path}, bonus 默认为 0")
        except Exception as e:
            logger.warning(f"[ConfidenceEngine] 加载配置失败: {e}")

    def _resolve_param_value(self, project_data: Dict[str, Any], param_key: str) -> Optional[str]:
        """从 project_data 中查找参数值（处理别名）"""
        aliases = self.PARAM_ALIASES.get(param_key, [param_key])
        for alias in aliases:
            val = project_data.get(alias)
            if val is not None and val != "" and str(val).lower() not in ("none", "undefined"):
                return str(val).strip()
        return None

    def assess(self, model_id: str, project_data: Dict[str, Any],
               base_accuracy: float) -> ConfidenceAssessment:
        """评估指定模型的动态置信度

        Args:
            model_id: 模型 ID（如 "subsection_xgb"）
            project_data: 用户提供的项目参数（含向导/对话填写的字段）
            base_accuracy: 模型的 CV R² × 100

        Returns:
            ConfidenceAssessment 含 base + bonus + effective + breakdown
        """
        if not self._loaded:
            return ConfidenceAssessment(
                base_accuracy=base_accuracy, input_bonus=0.0,
                effective_accuracy=base_accuracy, max_potential_bonus=0.0,
                breakdown={}
            )

        model_config = self._config.get("models", {}).get(model_id, {})
        if not model_config:
            return ConfidenceAssessment(
                base_accuracy=base_accuracy, input_bonus=0.0,
                effective_accuracy=base_accuracy, max_potential_bonus=0.0,
                breakdown={}
            )

        bonus_rules: Dict = model_config.get("bonus_rules", {})
        max_bonus: float = model_config.get("max_bonus", 0.0)

        breakdown: Dict[str, float] = {}
        input_bonus = 0.0
        filled = 0

        for param_key, rule in bonus_rules.items():
            bonus_amount: float = rule.get("bonus", 0.0)
            value = self._resolve_param_value(project_data, param_key)
            if value:
                breakdown[param_key] = bonus_amount
                input_bonus += bonus_amount
                filled += 1

        # 钳制到 max_bonus
        input_bonus = min(input_bonus, max_bonus)
        effective = min(base_accuracy + input_bonus, 100.0)

        return ConfidenceAssessment(
            base_accuracy=base_accuracy,
            input_bonus=input_bonus,
            effective_accuracy=effective,
            max_potential_bonus=max_bonus,
            breakdown=breakdown,
            filled_params=filled,
            total_params=len(bonus_rules),
        )

    def get_all_assessments(self, model_ids: List[str],
                            project_data: Dict[str, Any],
                            base_accuracies: Dict[str, float]) -> Dict[str, ConfidenceAssessment]:
        """批量评估多个模型"""
        return {
            mid: self.assess(mid, project_data, base_accuracies.get(mid, 0.0))
            for mid in model_ids
        }

    def get_empirical_correction(self, model_id: str,
                                  project_data: Dict[str, Any]) -> Dict[str, float]:
        """获取经验修正系数（用于调整预测值本身，而非仅置信度）

        例如：subsection_xgb + foundation_type="桩基础" → {"基础占比": 1.35}

        Returns:
            修正系数字典: {"基础占比": 1.35, "主体占比": 0.95, ...}
            空字典表示无需修正
        """
        if not self._loaded:
            return {}

        model_config = self._config.get("models", {}).get(model_id, {})
        empirical: Dict[str, Dict[str, float]] = model_config.get("empirical_correction", {})
        if not empirical:
            return {}

        corrections: Dict[str, float] = {}
        for param_key, value_map in empirical.items():
            value = self._resolve_param_value(project_data, param_key)
            if not value:
                continue

            # 精确匹配
            if value in value_map:
                corrections.update(value_map[value])
                continue

            # 模糊匹配：子串包含
            for known_val, factors in value_map.items():
                if known_val in value or value in known_val:
                    corrections.update(factors)
                    break

        return corrections

    def get_preview(self, model_ids: List[str],
                    partial_params: Dict[str, Any],
                    base_accuracies: Dict[str, float]) -> Dict[str, Dict]:
        """实时预览：给定部分参数，返回每个模型当前的 bonus + max"""
        result = {}
        for mid in model_ids:
            a = self.assess(mid, partial_params, base_accuracies.get(mid, 0.0))
            result[mid] = {
                "base_accuracy": a.base_accuracy,
                "current_bonus": a.input_bonus,
                "effective_accuracy": a.effective_accuracy,
                "max_potential_bonus": a.max_potential_bonus,
                "filled_params": a.filled_params,
                "total_params": a.total_params,
                "breakdown": {k: round(v, 1) for k, v in a.breakdown.items()},
            }
        return result


# ── 全局单例 ──
_engine: Optional[ConfidenceEngine] = None


def get_engine() -> ConfidenceEngine:
    global _engine
    if _engine is None:
        _engine = ConfidenceEngine()
    return _engine
