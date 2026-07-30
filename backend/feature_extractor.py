"""
feature_extractor.py - 从解析文档中提取结构化项目特征
支持从文本和表格中提取工程造价相关的项目信息
"""

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProjectFeatures:
    """从文档中提取的项目特征"""
    # 必填字段
    project_name: Optional[str] = None
    building_type: Optional[str] = None   # 住宅/学校/医院/办公楼/商业建筑/工业建筑/基础设施/公共建筑
    structure_type: Optional[str] = None  # 框架结构/框剪结构/砖混结构/钢结构
    total_area: Optional[float] = None    # 平方米
    floor_count: Optional[int] = None
    location: Optional[str] = None
    build_year: Optional[int] = None
    decoration_standard: Optional[str] = None
    total_cost: Optional[float] = None    # 元
    unit_price: Optional[float] = None    # 元/m²

    # 可选字段
    land_area: Optional[float] = None
    above_ground_floors: Optional[int] = None
    under_ground_floors: Optional[int] = None

    # 置信度
    confidence: Dict[str, float] = field(default_factory=dict)        # field_name -> 0.0-1.0
    extraction_source: Dict[str, str] = field(default_factory=dict)   # field_name -> 'text'|'table'|'inferred'

    def to_dict(self) -> dict:
        """转换为字典（用于API响应），过滤掉None值"""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def completeness(self) -> float:
        """计算特征完整度（0-1）"""
        required = ['building_type', 'total_area', 'structure_type', 'location']
        filled = sum(1 for f in required if getattr(self, f) is not None)
        return filled / len(required)


# ---------------------------------------------------------------------------
# FeatureExtractor
# ---------------------------------------------------------------------------

class FeatureExtractor:
    """从ParseResult中提取项目特征"""

    # 建筑类型关键词
    BUILDING_TYPE_PATTERNS = {
        '住宅': [r'住宅', r'安置', r'小区', r'住房', r'公寓', r'别墅', r'公租房', r'保障房'],
        '学校': [r'学校', r'学院', r'幼儿园', r'教学', r'校区', r'教育'],
        '医院': [r'医院', r'卫生', r'医疗', r'诊所'],
        '商业建筑': [r'商业', r'酒店', r'商场', r'宾馆', r'饭店', r'度假', r'商铺'],
        '办公楼': [r'办公', r'写字楼', r'行政', r'商务楼'],
        '工业建筑': [r'厂房', r'工业', r'车间', r'仓库', r'产业园'],
        '基础设施': [r'基础设施', r'道路', r'桥梁', r'管网', r'市政', r'隧道'],
        '公共建筑': [r'文化', r'图书', r'展览', r'体育', r'综合', r'服务', r'活动'],
    }

    STRUCTURE_PATTERNS = [
        (r'框.*?剪.*?墙', '框剪结构'),
        (r'剪力墙结构', '框剪结构'),
        (r'框架结构', '框架结构'),
        (r'砖混结构', '砖混结构'),
        (r'钢结构', '钢结构'),
    ]

    DECORATION_PATTERNS = [
        (r'精装修', '精装修'),
        (r'精装', '精装修'),
        (r'简装|简单装修', '简装修'),
        (r'毛坯', '毛坯'),
        (r'公共区域精装', '公共区域精装'),
    ]

    FOUNDATION_PATTERNS = [
        (r'筏板基础', '筏板基础'),
        (r'筏.*?基础', '筏板基础'),
        (r'桩.*?基础', '桩基础'),
        (r'独立基础', '独立基础'),
        (r'条.*?基础', '条形基础'),
    ]

    # 常见城市/地区列表（用于地点提取）
    CITIES = [
        '成都', '北京', '上海', '广州', '深圳', '杭州', '武汉', '重庆',
        '西安', '南京', '天津', '苏州', '长沙', '郑州', '东莞', '青岛',
        '四川', '广元', '新都', '青羊', '锦江', '天府', '邛崃', '崇州',
        '德阳', '宜宾', '绵阳', '南充', '达州', '乐山', '自贡', '泸州',
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, parsed_content) -> ProjectFeatures:
        """从ParseResult中提取项目特征

        Parameters
        ----------
        parsed_content : ParseResult
            document_parser.parse_document() 的返回值

        Returns
        -------
        ProjectFeatures
        """
        features = ProjectFeatures()
        text = parsed_content.full_text or ''
        tables = parsed_content.tables or []

        # ---- 从文本提取 ----
        features.project_name = self._extract_project_name(
            parsed_content.filename, text
        )
        features.building_type = self._match_building_type(text)
        features.structure_type = self._extract_structure(text)
        features.total_area = self._extract_area(text)
        features.land_area = self._extract_land_area(text)
        features.location = self._extract_location(text)
        features.build_year = self._extract_year(text)
        features.floor_count = self._extract_floors(text)
        features.above_ground_floors, features.under_ground_floors = (
            self._extract_floor_breakdown(text)
        )
        features.decoration_standard = self._extract_decoration(text)

        # ---- 从表格提取造价 ----
        features.total_cost, features.unit_price = self._extract_cost_from_tables(
            tables, features.total_area
        )

        # ---- 计算置信度 & 记录来源 ----
        self._calculate_confidence(features, text, tables)

        return features

    # ------------------------------------------------------------------
    # 文本提取方法
    # ------------------------------------------------------------------

    def _match_building_type(self, text: str) -> Optional[str]:
        """通过关键词匹配建筑类型"""
        if not text:
            return None
        for btype, patterns in self.BUILDING_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return btype
        return None

    def _extract_structure(self, text: str) -> Optional[str]:
        """提取结构类型"""
        if not text:
            return None
        for pattern, value in self.STRUCTURE_PATTERNS:
            if re.search(pattern, text):
                return value
        return None

    def _extract_area(self, text: str) -> Optional[float]:
        """提取总建筑面积（平方米）"""
        if not text:
            return None
        patterns = [
            r'总.*?面积.*?(\d+(?:\.\d+)?)\s*(?:平方米|m[²2]|平米|㎡)',
            r'建筑.*?面积.*?(\d+(?:\.\d+)?)\s*(?:平方米|m[²2]|平米|㎡)',
            r'(\d+(?:\.\d+)?)\s*(?:平方米|m[²2]|平米|㎡)',
            r'占地面积.*?(\d+(?:\.\d+)?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    def _extract_land_area(self, text: str) -> Optional[float]:
        """提取占地面积（平方米）"""
        if not text:
            return None
        patterns = [
            r'占地.*?面积.*?(\d+(?:\.\d+)?)\s*(?:平方米|m[²2]|平米|㎡)',
            r'用地.*?面积.*?(\d+(?:\.\d+)?)\s*(?:平方米|m[²2]|平米|㎡)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """提取项目地点"""
        if not text:
            return None
        for city in self.CITIES:
            if city in text:
                return city
        return None

    def _extract_year(self, text: str) -> Optional[int]:
        """提取建设年份"""
        if not text:
            return None
        match = re.search(r'(20\d{2}|19\d{2})\s*(?:年)?', text)
        if match:
            year = int(match.group(1))
            if 1950 <= year <= 2030:
                return year
        return None

    def _extract_floors(self, text: str) -> Optional[int]:
        """提取总层数"""
        if not text:
            return None
        matches = re.findall(r'(\d+)\s*(?:层|楼)', text)
        if matches:
            return max(int(m) for m in matches)
        return None

    def _extract_floor_breakdown(self, text: str):
        """提取地上/地下层数分解

        Returns
        -------
        (above_ground_floors, under_ground_floors) : tuple[Optional[int], Optional[int]]
        """
        above = None
        under = None
        if not text:
            return above, under

        above_match = re.search(r'地上\s*(\d+)\s*(?:层|楼)', text)
        if above_match:
            above = int(above_match.group(1))

        under_match = re.search(r'地下\s*(\d+)\s*(?:层|楼)', text)
        if under_match:
            under = int(under_match.group(1))

        return above, under

    def _extract_decoration(self, text: str) -> Optional[str]:
        """提取装修标准"""
        if not text:
            return None
        for pattern, value in self.DECORATION_PATTERNS:
            if re.search(pattern, text):
                return value
        return None

    def _extract_project_name(self, filename: str, text: str) -> Optional[str]:
        """提取项目名称，文件名作为回退"""
        if text:
            match = re.search(
                r'(?:项目名称|工程名称|项目).*?[：:]\s*(.+?)(?:\n|$)', text
            )
            if match:
                return match.group(1).strip()

        # 回退到文件名
        if filename:
            return os.path.splitext(filename)[0]
        return None

    # ------------------------------------------------------------------
    # 表格提取方法
    # ------------------------------------------------------------------

    def _extract_cost_from_tables(self, tables, area):
        """从表格中提取总造价和单价

        Parameters
        ----------
        tables : list
            ParseResult.tables
        area : Optional[float]
            已提取的总面积，用于计算单价

        Returns
        -------
        (total_cost, unit_price) : tuple[Optional[float], Optional[float]]
        """
        total_cost = None
        unit_price = None

        if not tables:
            return total_cost, unit_price

        for table in tables:
            if not table:
                continue
            for row in table:
                if not row:
                    continue
                row_text = ' '.join(str(cell) for cell in row)
                if re.search(r'合计|总计|总造价|招标控制价|合同价', row_text):
                    for cell in row:
                        cost = self._parse_cost_value(str(cell))
                        if cost and cost > 10000:  # 合理最低值
                            total_cost = cost
                            if area and area > 0:
                                unit_price = round(total_cost / area, 2)
                            break
                    if total_cost is not None:
                        break
            if total_cost is not None:
                break

        return total_cost, unit_price

    def _parse_cost_value(self, text: str) -> Optional[float]:
        """解析造价数值，支持多种格式

        支持格式: 1,234,567.89 / 1234.56万元 / 1.23亿元
        """
        if not text:
            return None
        text = text.replace(',', '').replace('，', '').strip()

        if '亿元' in text:
            match = re.search(r'(\d+(?:\.\d+)?)', text)
            if match:
                return float(match.group(1)) * 100_000_000
        elif '万元' in text:
            match = re.search(r'(\d+(?:\.\d+)?)', text)
            if match:
                return float(match.group(1)) * 10_000
        else:
            match = re.search(r'(\d+(?:\.\d+)?)', text)
            if match:
                val = float(match.group(1))
                if val > 1000:  # 合理最低值
                    return val
        return None

    # ------------------------------------------------------------------
    # 置信度计算
    # ------------------------------------------------------------------

    def _calculate_confidence(self, features: ProjectFeatures, text: str, tables):
        """计算各字段的置信度并记录提取来源"""
        # 文本正则提取的字段
        text_fields = [
            'building_type', 'structure_type', 'total_area', 'location',
            'build_year', 'floor_count', 'decoration_standard',
        ]
        for field_name in text_fields:
            value = getattr(features, field_name)
            if value is not None:
                features.confidence[field_name] = 0.8
                features.extraction_source[field_name] = 'text'
            else:
                features.confidence[field_name] = 0.0

        # 表格提取的字段
        if features.total_cost is not None:
            features.confidence['total_cost'] = 0.7
            features.extraction_source['total_cost'] = 'table'
        else:
            features.confidence['total_cost'] = 0.0

        # 计算得出的字段
        if features.unit_price is not None:
            features.confidence['unit_price'] = 0.6
            features.extraction_source['unit_price'] = 'inferred'
        else:
            features.confidence['unit_price'] = 0.0

        # 可选字段
        if features.land_area is not None:
            features.confidence['land_area'] = 0.8
            features.extraction_source['land_area'] = 'text'

        if features.above_ground_floors is not None:
            features.confidence['above_ground_floors'] = 0.8
            features.extraction_source['above_ground_floors'] = 'text'

        if features.under_ground_floors is not None:
            features.confidence['under_ground_floors'] = 0.8
            features.extraction_source['under_ground_floors'] = 'text'


# ---------------------------------------------------------------------------
# CLI 测试入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from document_parser import parse_document

    if len(sys.argv) < 2:
        print("Usage: python feature_extractor.py <file_path>")
        sys.exit(1)

    result = parse_document(sys.argv[1])
    extractor = FeatureExtractor()
    features = extractor.extract(result)

    print(f"Project: {features.project_name}")
    print(f"Type: {features.building_type}")
    print(f"Structure: {features.structure_type}")
    print(f"Area: {features.total_area} m²")
    print(f"Location: {features.location}")
    print(f"Year: {features.build_year}")
    print(f"Floors: {features.floor_count}")
    print(f"Decoration: {features.decoration_standard}")
    print(f"Total cost: {features.total_cost}")
    print(f"Unit price: {features.unit_price}")
    print(f"Completeness: {features.completeness():.0%}")
    print(f"Confidence: {features.confidence}")
