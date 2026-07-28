"""
数据充分性评估器 - 判断训练数据是否足够支撑可靠预测
"""
from __future__ import annotations
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class SufficiencyReport:
    sufficient: bool
    score: float  # 0-100
    total_samples: int
    real_samples: int
    simulated_samples: int
    issues: List[str]
    recommendations: List[str]
    category_coverage: Dict[str, int]  # 建筑类型 -> 样本数
    region_coverage: Dict[str, int]    # 地区 -> 样本数
    feature_variance: Dict[str, float] # 特征名 -> 方差


class DataSufficiencyChecker:
    MIN_SAMPLES = 30
    MIN_PER_CATEGORY = 5
    RECOMMENDED = 100
    REQUIRED_CATEGORIES = ["住宅", "学校", "医院", "办公楼", "工业建筑", "商业建筑", "基础设施", "公共建筑"]

    def assess(self, df: pd.DataFrame) -> SufficiencyReport:
        """评估数据充分性"""
        issues = []
        recommendations = []
        score = 100.0

        total = len(df)
        real = len(df[df.get('source_type', pd.Series(dtype=str)) != '']) if 'source_type' in df.columns else total
        simulated = total - real

        # Check 1: Total sample count
        if total < self.MIN_SAMPLES:
            issues.append(f"总样本量不足（{total} < {self.MIN_SAMPLES}）")
            score -= 30
        elif total < self.RECOMMENDED:
            issues.append(f"建议增加样本量至{self.RECOMMENDED}条以上（当前{total}条）")
            score -= 10

        # Check 2: Category coverage
        category_coverage = {}
        if '建筑类型' in df.columns:
            category_coverage = df['建筑类型'].value_counts().to_dict()
            missing_cats = [c for c in self.REQUIRED_CATEGORIES if category_coverage.get(c, 0) < self.MIN_PER_CATEGORY]
            if missing_cats:
                issues.append(f"以下建筑类型样本不足（每类需≥{self.MIN_PER_CATEGORY}条）：{', '.join(missing_cats)}")
                recommendations.append(f"建议补充以下类型的真实项目数据：{', '.join(missing_cats)}")
                score -= len(missing_cats) * 5

        # Check 3: Region coverage
        region_coverage = {}
        if '所在地区' in df.columns:
            region_coverage = df['所在地区'].value_counts().to_dict()
            low_regions = [r for r, c in region_coverage.items() if c < 3]
            if low_regions:
                issues.append(f"以下地区样本稀少：{', '.join(low_regions[:5])}")
                score -= len(low_regions) * 2

        # Check 4: Feature variance
        feature_variance = {}
        numeric_cols = ['总建筑面积', '楼层数', '项目总造价', '单方造价']
        for col in numeric_cols:
            if col in df.columns:
                var = pd.to_numeric(df[col], errors='coerce').var()
                feature_variance[col] = float(var) if pd.notna(var) else 0
                if feature_variance[col] == 0:
                    issues.append(f"特征'{col}'方差为零（所有值相同），无信息量")
                    score -= 10

        # Check 5: Simulated data ratio
        if total > 0 and simulated / total > 0.5:
            issues.append(f"模拟数据占比过高（{simulated}/{total} = {simulated/total*100:.0f}%），可能影响泛化")
            recommendations.append("建议增加真实项目数据以降低模拟数据权重影响")
            score -= 10

        score = max(0, score)
        sufficient = score >= 60 and total >= self.MIN_SAMPLES

        if not sufficient:
            recommendations.insert(0, "当前数据不足以支撑可靠预测，建议补充真实项目数据")
            # Add authoritative sources
            recommendations.append("可参考以下权威数据源：各省建设工程造价管理总站、住建部标准定额司、中国建设工程造价管理协会(CCEA)")

        return SufficiencyReport(
            sufficient=sufficient,
            score=round(score, 1),
            total_samples=total,
            real_samples=real,
            simulated_samples=simulated,
            issues=issues,
            recommendations=recommendations,
            category_coverage=category_coverage,
            region_coverage=region_coverage,
            feature_variance=feature_variance,
        )

    @staticmethod
    def get_authoritative_sources() -> List[Dict]:
        """返回权威造价数据源列表"""
        return [
            {"name": "各省建设工程造价管理总站", "url": "https://www.ccead.org.cn/", "type": "government", "description": "各省市官方造价指标和指数"},
            {"name": "住建部标准定额司", "url": "https://www.mohurd.gov.cn/", "type": "government", "description": "国家工程计价标准和规范"},
            {"name": "中国建设工程造价管理协会", "url": "https://www.ccead.org.cn/", "type": "industry", "description": "行业造价指数和典型案例"},
            {"name": "全国工程造价信息平台", "type": "platform", "description": "各地造价指标数据汇总"},
        ]
