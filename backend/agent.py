"""
ReAct 智能体 - 真实 AgentScope SDK 集成
参考: https://doc.agentscope.io/zh_CN/tutorial/quickstart_agent.html
      https://doc.agentscope.io/zh_CN/tutorial/task_model.html

策略：
1. 优先使用真实 AgentScope Agent + ReActConfig（需配置 LLM provider）
2. 无可用 LLM 时回退到内置 MockLLM（保留 ReAct 推理链路）

注册工具：
- predict_cost: 三层模型预测造价
- find_similar_projects: 历史数据相似项目检索
- explain_terminology: 建筑造价术语解释
- train_models: 触发模型训练
- list_models: 列出所有模型及训练状态
"""
from __future__ import annotations

import os
import re
import json
import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

import pandas as pd

# 尝试导入真实 AgentScope
try:
    from agentscope.agent import Agent, ReActConfig
    from agentscope.tool import Toolkit, FunctionTool, ToolResponse
    from agentscope.message import Msg, TextBlock
    AGENTSCOPE_AVAILABLE = True
except ImportError:
    AGENTSCOPE_AVAILABLE = False
    Agent = None
    ReActConfig = None

from model_config import ModelConfigManager, build_agentscope_model
from terminology import (
    COST_STAGES, COST_HIERARCHY, PROJECT_TYPES, STRUCTURE_TYPES,
    BASE_UNIT_PRICE, STRUCTURE_COEFFICIENT, DECORATION_COEFFICIENT,
    REGION_COST_INDEX
)
from data_sufficiency import DataSufficiencyChecker


REACT_SYSTEM_PROMPT = """你是「北辰造价助手」——专业的建筑工程造价预测 ReAct 智能体。

## 可用工具（共6个）
1. **predict_cost** — 三层模型融合预测造价
2. **find_similar_projects** — 历史数据相似项目检索
3. **explain_terminology** — 建筑造价术语解释
4. **train_models** — 触发模型训练
5. **list_models** — 列出所有模型及训练状态
6. **search_supplementary_data** — 数据充分性评估与补充建议

## 工作流程（ReAct 模式）
- Thought: 分析用户输入，识别需要调用的工具
- Action: 选择工具并填充参数
- Observation: 接收工具返回结果
- Final Answer: 综合所有结果，给出专业建议

## 引导交互规则
当用户输入模糊（缺少关键参数）时，**绝不猜测缺失参数**，主动用以下模板请求补充：

请补充以下信息以便精准预测：
- 建筑类型：[住宅/学校/医院/办公楼/商业建筑/工业建筑/基础设施/公共建筑]
- 总建筑面积：[___] 平方米
- 结构类型：[框架结构/框剪结构/砖混结构/钢结构]
- 所在地区：[___]
- 楼层数：[___] 层
- 装修标准：[精装修/一般装修/毛坯]

## 知识补充规则
当训练数据不足（缺少项目类型或样本太少）时，用自身造价知识提供：
- 该类项目的典型单方造价区间
- 影响造价的关键因素
- 建议补充的数据类型
必须标注：「以下为本模型基于行业经验提供的参考信息，非基于本地训练数据」

## 数据评估规则
当用户询问数据是否充分时，调用 search_supplementary_data，并根据结果建议需补充的数据类型与来源。

## 回复规范
- 简洁专业，避免冗余
- 涉及造价数字时，给出区间或精度说明
- 使用规范的建筑造价术语（参考五算：估算/概算/预算/结算/决算）

## 反馈与追问处理
当用户对预测结果提出质疑或补充信息时：
- 认真分析用户的具体关切（价格高低、地区差异、数据准确性等）
- 用专业知识解释影响造价的关键因素
- 如训练数据不足，用行业经验提供参考信息并明确标注
- 不要简单重复功能列表，要直接回应用户的问题

## 上下文理解规则
- 当用户在预测后追问具体地区（如“成都高新区呢”），应理解为要求基于该地区重新分析
- 当用户说“XX呢”、“XX怎么样”，应理解为对前文话题的延伸追问
- 不要返回通用菜单，要直接理解用户的具体意图并回应
- 利用对话历史中的项目参数，结合用户新提供的信息进行回答
"""


# ===========================================
# Mock LLM（无 API key 时的回退方案）
# ===========================================
class MockLLM:
    """模拟大语言模型 - 提供 ReAct 推理能力"""

    def __init__(self):
        self.call_count = 0

    def detect_intent(self, text: str) -> str:
        # 1. check_data / search_data (最具体 - 关于数据充分性)
        if any(kw in text for kw in ["数据够", "数据不足", "样本量", "数据充分", "数据质量", "够不够", "数据检查"]):
            return "check_data"
        if any(kw in text for kw in ["搜索数据", "找数据", "补充数据", "数据源"]):
            return "search_data"
        # 2. knowledge_query (行业知识查询)
        if any(kw in text for kw in ["造价一般", "通常多少", "行业", "经验", "参考", "一般是多少", "造价范围", "造价水平"]):
            return "knowledge_query"
        # 3. predict (造价预测)
        if any(kw in text for kw in ["预测", "估算", "多少钱", "造价多少", "总造价", "单方造价", "算一下", "帮我算", "造价预测", "预测造价"]):
            return "predict"
        # 4. train (模型训练)
        if any(kw in text for kw in ["训练", "train", "重新训练", "fit"]):
            return "train"
        # 5. explain_term
        if any(kw in text for kw in ["解释", "什么是", "含义", "定义", "什么叫", "是什么意思", "介绍"]):
            return "explain_term"
        # 6. list_models
        if any(kw in text for kw in ["推荐模型", "用什么模型", "模型列表", "列出模型", "有哪些模型"]):
            return "list_models"
        # 7. find_similar
        if any(kw in text for kw in ["相似", "类似", "历史项目", "以往项目"]):
            return "find_similar"
        # 8. cost_breakdown
        if any(kw in text for kw in ["拆分", "分解", "成本构成", "费用构成", "费用组成"]):
            return "cost_breakdown"
        # 9. greeting / thanks / help
        if any(kw in text for kw in ["你好", "您好", "hi", "hello", "Hi", "Hello", "在吗", "嗨"]):
            return "greeting"
        if any(kw in text for kw in ["谢谢", "感谢", "thanks", "thank", "辛苦了", "好的", "明白了", "了解"]):
            return "thanks"
        if any(kw in text for kw in ["能做什么", "功能", "帮助", "怎么用", "你会什么", "你的功能"]):
            return "help"
        # 10. implicit predict (描述了具体建筑项目参数，隐含预测意图)
        # 当用户提到建筑面积、楼层数等具体参数时，通常是想要造价预测
        has_area = bool(re.search(r"\d+(?:\.\d+)?\s*(?:平米|平方米|㎡|m[²32]|万平)", text))
        has_building_action = any(kw in text for kw in ["修一", "建一", "盖一", "修建", "建造", "建设", "拟建", "计划建"])
        if has_area and has_building_action:
            return "predict"
        # 11. region_refine - user specifies a more precise location (MUST be before feedback, because feedback contains '如何')
        if any(kw in text for kw in ["高新区", "新区", "开发区", "科技园", "工业园", "经开区", "自贸区", "CBD", "中心区"]) or \
           (any(kw in text for kw in ["呢", "的话", "怎么样", "如何"]) and any(city in text for city in ["成都", "北京", "上海", "广州", "深圳", "杭州", "武汉", "重庆", "西安", "南京", "天津", "苏州", "长沙"])):
            return "region_refine"
        # 12. feedback/questioning intent - user questions the prediction result
        if any(kw in text for kw in ["太便宜", "太贵", "偏高", "偏低", "不合理", "准确吗", "对吗", "是不是", "会不会", "考虑", "地区", "差异", "影响", "为什么", "怎么", "如何"]):
            return "feedback"
        # 13. supplementary info intent - user adds/corrects project details
        if any(kw in text for kw in ["补充", "另外", "还有", "修改", "改为", "改成", "不对", "错了", "应该是"]):
            return "supplement"
        # 14. repredict - user wants to adjust parameters and re-predict
        if any(kw in text for kw in ["重新预测", "重新算", "再算", "换成", "改为", "改成", "调整"]):
            return "repredict"
        # 15. compare - comparison request
        if any(kw in text for kw in ["对比", "比较", "差别", "区别"]) or re.search(r"vs|和.{1,6}比", text):
            return "compare"
        # 16. Parameter adjustment: "如果是X呢", "改为X", "变成X", "X层", "X平米"
        if any(kw in text for kw in ["如果是", "改为", "变成", "换成", "改成"]):
            return "repredict"
        # Number + unit pattern indicating parameter change
        if re.search(r'\d+\s*(层|楼|平米|m[²2]|平方米)', text) and len(text) < 30:
            return "repredict"
        # 17. Data availability query: "有...数据吗", "有没有", "数据够吗", "样本"
        if any(kw in text for kw in ["有没有", "数据够", "样本", "训练数据", "涵盖", "包含"]):
            return "data_query"
        if any(kw in text for kw in ["数据", "样本", "训练"]) and any(kw in text for kw in ["吗", "呢", "有没有", "是否"]):
            return "data_query"
        # 18. general (兜底)
        if any(kw in text for kw in ["高新区", "新区", "开发区", "科技园", "工业园", "经开区", "自贸区", "CBD", "中心区"]):
            return "region_refine"
        if len(text) < 20 and any(kw in text for kw in ["呢", "怎么样"]) and any(c in text for c in ["成都", "北京", "上海", "广州", "深圳", "杭州", "武汉", "重庆", "天府", "锦江", "青羊", "武侯", "新都"]):
            return "region_refine"
        if any(kw in text for kw in ["重新预测", "重新算", "再算"]):
            return "repredict"
        if any(kw in text for kw in ["对比", "比较", "差别"]):
            return "compare"
        return "general"

    # 建筑类型同义词映射：用户输入关键词 -> 训练数据中的标准类型
    BUILDING_TYPE_MAP = {
        '住宅': ['住宅', '安置', '小区', '住房', '公寓', '别墅'],
        '学校': ['学校', '学院', '教育', '教学', '校区', '幼儿园'],
        '医院': ['医院', '卫生', '医疗', '诊所'],
        '办公楼': ['办公', '写字楼', '行政', '商务楼'],
        '商业建筑': ['商业', '商铺', '商场', '酒店', '宾馆', '饭店', '旅馆', '度假', '餐饮'],
        '工业建筑': ['厂房', '工业', '车间', '仓库'],
        '基础设施': ['道路', '桥梁', '管网', '市政', '隧道'],
        '公共建筑': ['文化', '图书', '展览', '体育', '综合', '服务', '活动'],
    }

    @classmethod
    def normalize_building_type(cls, raw_type: str) -> str:
        """将用户输入的建筑类型关键词映射为标准训练数据类型"""
        if not raw_type:
            return raw_type
        for standard_type, keywords in cls.BUILDING_TYPE_MAP.items():
            for kw in keywords:
                if kw in raw_type:
                    return standard_type
        return raw_type

    def extract_params(self, text: str) -> Dict:
        params = {}
        # 面积 —— 支持 m², m2, m3, 平米, 平方米, ㎡, 平 等多种写法
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:万\s*)?(?:平方米|平米|㎡|m[²32]|平)", text)
        if m:
            v = float(m.group(1))
            # 检查匹配范围内是否包含"万"字
            matched_text = text[m.start():m.end()]
            if "万" in matched_text:
                v *= 10000
            params["total_area"] = v

        # 建筑类型（使用 BUILDING_TYPE_MAP 进行同义词映射）
        for standard_type, keywords in self.BUILDING_TYPE_MAP.items():
            if any(kw in text for kw in keywords):
                params["project_type"] = standard_type
                break

        # 地区
        for r in ["华北", "华东", "华南", "华中", "西南", "西北", "东北",
                  "北京", "上海", "广州", "深圳", "成都", "杭州", "南京", "武汉"]:
            if r in text:
                params["location"] = r
                break

        # 结构
        for s in ["框架", "框剪", "剪力墙", "钢结构", "砖混"]:
            if s in text:
                params["structure_type"] = f"{s}结构" if s != "钢结构" else "钢结构"
                break

        # 楼层
        m = re.search(r"(\d+)\s*[层楼]", text)
        if m:
            params["floors"] = int(m.group(1))

        # 装修
        for d in ["简单装修", "普通装修", "精装修", "豪华装修", "毛坯"]:
            if d in text:
                params["decoration_level"] = "简单装修" if d == "毛坯" else d
                break

        params.setdefault("project_type", "住宅")
        params.setdefault("structure_type", "框架结构")
        params.setdefault("location", "华东")
        params.setdefault("floors", 6)
        params.setdefault("build_year", 2026)
        params.setdefault("decoration_level", "普通装修")
        params.setdefault("project_name", "对话生成项目")
        # 注意：面积不设默认值，若用户未提供则在 predict_cost 中再回退
        if "total_area" not in params:
            params["total_area"] = 10000
        return params

    def think(self, text: str) -> str:
        intent = self.detect_intent(text)
        m = {
            "predict": "用户希望进行造价预测。我需要识别项目参数，并调用 predict_cost 工具进行预测。",
            "train": "用户希望训练模型。我将调用 train_models 工具触发 scikit-learn 训练流程。",
            "explain_term": "用户希望了解建筑造价术语。我将调用 explain_terminology 工具进行解释。",
            "list_models": "用户希望查看模型列表。我将调用 list_models 工具展示所有模型状态。",
            "cost_breakdown": "用户希望了解成本结构。我将调用 predict_cost 工具并展示六层级分解。",
            "find_similar": "用户希望查找相似历史项目。我将调用 find_similar_projects 工具。",
            "check_data": "用户希望检查数据充分性。我将调用 DataSufficiencyChecker 评估当前训练数据是否足够。",
            "search_data": "用户希望搜索和补充数据。我将调用 search_supplementary_data 工具评估数据充分性并推荐权威数据源。",
            "knowledge_query": "用户询问行业造价知识。我将结合训练数据和行业经验提供典型造价参考信息。",
            "general": "用户的输入较为通用，我将尝试理解其意图并提供有针对性的引导。"
        }
        return m.get(intent, m["general"])


def _format_money(n: float) -> str:
    if n >= 1e8: return f"{n/1e8:.2f}亿元"
    if n >= 1e4: return f"{n/1e4:.2f}万元"
    return f"{n:.2f}元"


# ===========================================
# 智能体管理器
# ===========================================
class CostAgentManager:
    """智能体管理器：真实 AgentScope 与 MockLLM 统一接口"""

    def __init__(self, model_factory, data_loader, model_config_manager: ModelConfigManager):
        self.model_factory = model_factory
        self.data_loader = data_loader
        self.config_mgr = model_config_manager
        self.mock_llm = MockLLM()
        self._real_agents: Dict[str, Any] = {}  # session_id -> Agent

    def _build_toolkit(self) -> Optional[Any]:
        """构建 AgentScope Toolkit（含真实工具函数）"""
        if not AGENTSCOPE_AVAILABLE:
            return None

        factory = self.model_factory
        data_loader = self.data_loader

        async def predict_cost(
            project_name: str = "对话生成项目",
            project_type: str = "学校",
            structure_type: str = "框架结构",
            total_area: float = 10000,
            floors: int = 6,
            location: str = "华东",
            build_year: int = 2026,
            decoration_level: str = "普通装修",
        ) -> ToolResponse:
            """使用三层模型体系预测建筑工程造价。

            Args:
                project_name: 项目名称
                project_type: 建筑类型（学校/医院/办公楼/住宅/工业建筑/商业建筑/基础设施/公共建筑）
                structure_type: 结构类型（框架结构/框剪结构/剪力墙结构/钢结构等）
                total_area: 总建筑面积（平方米）
                floors: 楼层数
                location: 所在地区（华北/华东/华南/华中/西南/西北/东北）
                build_year: 建造年份
                decoration_level: 装修标准（简单装修/普通装修/精装修/豪华装修）
            """
            from ml_models import predict_with_real_models
            # 标准化建筑类型（如 酒店 -> 商业建筑）
            project_type = MockLLM.normalize_building_type(project_type)
            project = {
                "project_name": project_name, "project_type": project_type,
                "structure_type": structure_type, "total_area": total_area,
                "floors": floors, "location": location,
                "build_year": build_year, "decoration_level": decoration_level,
            }
            # 默认选所有已训练模型
            all_models = factory.list_models()
            trained_ids = [m["id"] for m in all_models if m.get("is_trained")]
            selected = trained_ids if trained_ids else ["total_pso_svr", "section_xgb", "indicator_rf"]
            result = predict_with_real_models(factory, project, selected, data_loader=data_loader)
            summary = f"预测完成：总造价 {_format_money(result['fused_total_cost'])}，单方造价 {result['fused_unit_price']:.0f} 元/m²，综合精度 {result['average_accuracy']}%"
            return ToolResponse(
                output=[{"type": "text", "text": summary + "\n" + json.dumps(result, ensure_ascii=False, default=str)}]
            )

        async def train_models(model_id: str = "") -> ToolResponse:
            """触发 scikit-learn 模型训练。传空字符串训练所有模型。

            Args:
                model_id: 模型 ID（留空则训练所有模型）
            """
            df = data_loader.to_dataframe()
            if df is None or len(df) == 0:
                return ToolResponse(output=[{"type": "text", "text": "暂无训练数据，请先导入 Excel 历史项目数据"}])
            if model_id:
                r = factory.train_one(model_id, df)
            else:
                r = factory.train_all(df)
            return ToolResponse(output=[{"type": "text", "text": json.dumps(r, ensure_ascii=False, default=str)}])

        async def list_models() -> ToolResponse:
            """列出所有已注册模型及训练状态。"""
            models = factory.list_models()
            return ToolResponse(output=[{"type": "text", "text": json.dumps(models, ensure_ascii=False)}])

        async def find_similar_projects(
            project_type: str = "",
            structure_type: str = "",
            area: float = 0,
        ) -> ToolResponse:
            """在历史数据中查找相似项目。

            Args:
                project_type: 建筑类型
                structure_type: 结构类型
                area: 总面积（平方米）
            """
            # 标准化建筑类型
            project_type = MockLLM.normalize_building_type(project_type)
            similar = data_loader.find_similar_projects(project_type, structure_type, area)
            return ToolResponse(output=[{"type": "text", "text": json.dumps(similar, ensure_ascii=False, default=str)}])

        async def explain_terminology(term: str) -> ToolResponse:
            """解释建筑造价专业术语。

            Args:
                term: 要解释的术语
            """
            explanation = _explain_term(term)
            return ToolResponse(output=[{"type": "text", "text": explanation}])

        async def search_supplementary_data(query: str = "construction_cost") -> ToolResponse:
            """评估训练数据充分性并推荐权威数据源。

            Args:
                query: 搜索关键词（默认 construction_cost）
            """
            df = data_loader.to_dataframe()
            if df is None or len(df) == 0:
                return ToolResponse(output=[{"type": "text", "text": "当前无任何训练数据。请先导入 Excel 项目数据或生成示例数据。"}])
            checker = DataSufficiencyChecker()
            report = checker.assess(df)
            result = f"## 数据充分性评估报告\n\n"
            result += f"**评分**: {report.score}/100 {'✅ 基本充分' if report.sufficient else '⚠️ 不足'}\n\n"
            result += f"**样本统计**: 总计{report.total_samples}条（真实{report.real_samples}条，模拟{report.simulated_samples}条）\n\n"
            if report.issues:
                result += "### 发现的问题\n"
                for issue in report.issues:
                    result += f"- ⚠️ {issue}\n"
                result += "\n"
            if report.recommendations:
                result += "### 改进建议\n"
                for rec in report.recommendations:
                    result += f"- 💡 {rec}\n"
                result += "\n"
            sources = DataSufficiencyChecker.get_authoritative_sources()
            result += "### 权威数据源推荐\n"
            for s in sources:
                result += f"- **{s['name']}** ({s['type']})"
                if s.get('url'):
                    result += f" - {s['url']}"
                result += f"\n  {s.get('description', '')}\n"
            result += "\n> 提示：从以上来源获取数据后，可通过「导入Excel」功能添加到训练集。"
            return ToolResponse(output=[{"type": "text", "text": result}])

        tools = [
            FunctionTool(predict_cost),
            FunctionTool(train_models),
            FunctionTool(list_models),
            FunctionTool(find_similar_projects),
            FunctionTool(explain_terminology),
            FunctionTool(search_supplementary_data),
        ]
        return Toolkit(tools=tools)

    def _build_real_agent(self) -> Optional[Any]:
        """构建真实 AgentScope Agent"""
        if not AGENTSCOPE_AVAILABLE:
            print("[build real agent] AgentScope not installed, falling back to MockLLM")
            return None

        active = self.config_mgr.get_active()
        if not active or not active.is_configured():
            print(f"[build real agent] No active LLM configured (active={self.config_mgr._active_provider})")
            return None

        print(f"[build real agent] Building model for provider={active.provider}, model={active.model_name}")
        model = build_agentscope_model(active)
        if model is None:
            print(f"[build real agent] build_agentscope_model() returned None for {active.provider}")
            return None

        toolkit = self._build_toolkit()
        try:
            agent = Agent(
                name="CostAgent",
                system_prompt=REACT_SYSTEM_PROMPT,
                model=model,
                toolkit=toolkit,
                react_config=ReActConfig(max_iters=10),
            )
            print(f"[build real agent] Successfully built AgentScope Agent: {type(agent)}")
            return agent
        except Exception as e:
            print(f"[build real agent] Agent creation failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_or_build_agent(self, session_id: str):
        """获取或构建智能体（真实优先，回退 Mock）"""
        if session_id not in self._real_agents or self._real_agents[session_id] is None:
            agent = self._build_real_agent()
            self._real_agents[session_id] = agent  # None 表示用 Mock
        return self._real_agents[session_id]

    def invalidate_agents(self):
        """配置变更后清空缓存的智能体"""
        self._real_agents.clear()

    async def chat(self, user_message: str, history: List[Dict] = None, session_id: str = "default") -> Dict:
        """处理用户消息（统一入口：真实 / Mock）"""
        if history is None:
            history = []

        try:
            real_agent = self.get_or_build_agent(session_id)
            print(f"[chat] session={session_id}, real_agent={'AgentScope' if real_agent is not None else 'None→MockLLM'}, msg_len={len(user_message)}")
            if real_agent is not None:
                return await self._chat_with_real_agent(real_agent, user_message, history, session_id)
            else:
                return await self._chat_with_mock(user_message, history, session_id)
        except Exception as e:
            # 顶层容错（M6）：任何未预期的异常都不应使对话端点崩溃
            import traceback
            traceback.print_exc()
            return {
                "session_id": session_id,
                "reply": f"抱歉，处理您的消息时出现异常（{type(e).__name__}）。请稍后重试或描述得更具体一些。",
                "react_steps": [{"step": "thought", "content": "处理异常，已降级返回"}],
                "tool_result": None,
                "backend": "error_fallback",
                "history_count": len(history) + 2,
            }

    async def _chat_with_real_agent(self, agent, user_message: str, history: List[Dict], session_id: str) -> Dict:
        """使用真实 AgentScope Agent（含重试）"""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                # 构造 Msg（content 必须是 block 列表）
                msg = Msg(
                    name="user",
                    content=[TextBlock(type="text", text=user_message)],
                    role="user",
                )
                response = await agent.reply(msg)

                # 提取回复文本
                reply_text = ""
                if hasattr(response, "content") and isinstance(response.content, list):
                    for block in response.content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            reply_text += block.get("text", "")
                        elif hasattr(block, "text"):
                            reply_text += block.text
                elif isinstance(response, str):
                    reply_text = response

                # Fallback to MockLLM if AgentScope returns timeout/waiting message
                # Only fallback for short replies containing error indicators, not just mentions
                print(f"[real agent] reply_len={len(reply_text)}, attempt={attempt}, session={session_id}")
                if not reply_text or (len(reply_text) < 100 and ("waiting for your permission" in reply_text.lower() or "external execution" in reply_text.lower())):
                    print(f"[real agent] falling back to MockLLM (reply empty or short+error-like)")
                    return await self._chat_with_mock(user_message, history, session_id)

                return {
                    "session_id": session_id,
                    "reply": reply_text or "(空回复)",
                    "react_steps": [
                        {"step": "thought", "content": "调用真实 AgentScope ReActAgent 推理"},
                        {"step": "final_answer", "content": reply_text[:200]},
                    ],
                    "tool_result": None,
                    "backend": "agentscope_sdk",
                    "history_count": len(history) + 2,
                }
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[real agent] attempt {attempt+1} failed: {e}, retrying...")
                    await asyncio.sleep(1)
                    continue
                print(f"[real agent] all {max_retries} attempts failed: {e}, falling back to MockLLM")
                return await self._chat_with_mock(user_message, history, session_id)

    async def _chat_with_mock(self, user_message: str, history: List[Dict], session_id: str) -> Dict:
        """使用 MockLLM 推理（无 API key 时）"""
        thought = self.mock_llm.think(user_message)
        intent = self.mock_llm.detect_intent(user_message)
        params = self.mock_llm.extract_params(user_message)

        react_steps = [
            {"step": "thought", "content": thought},
            {"step": "action", "content": f"调用工具: {intent}", "params": params},
        ]

        tool_result = None
        final_answer = ""

        if intent == "predict":
            # Check data sufficiency first
            checker = DataSufficiencyChecker()
            df = self.data_loader.to_dataframe()
            sufficiency_warning = ""
            if df is not None:
                report = checker.assess(df)
                if not report.sufficient:
                    sufficiency_warning = f"\n\n> ⚠️ **数据充分性警告**：当前数据评分 {report.score}/100，可能影响预测可靠性。"
                    if report.issues:
                        sufficiency_warning += "\n> 主要问题：" + "；".join(report.issues[:3])

            from ml_models import predict_with_real_models
            all_models = self.model_factory.list_models()
            trained_ids = [m["id"] for m in all_models if m.get("is_trained")]
            if trained_ids:
                selected = trained_ids[:5]  # 取前 5 个已训练模型
                backend_note = "scikit-learn 真实模型"
            else:
                selected = ["total_pso_svr", "section_xgb", "indicator_rf"]
                backend_note = "未训练（仅占位）"
            # 确保建筑类型已标准化（如 酒店 -> 商业建筑）
            if params.get("project_type"):
                params["project_type"] = MockLLM.normalize_building_type(params["project_type"])
            prediction = predict_with_real_models(self.model_factory, params, selected, data_loader=self.data_loader)
            tool_result = prediction
            final_answer = self._format_prediction(prediction, backend_note)
            if sufficiency_warning:
                final_answer += sufficiency_warning
            # Check if user provided key parameters
            _has_type = any(kw in user_message for kw in ["住宅", "学校", "医院", "办公楼", "商业", "工业", "公共", "基础设施", "酒店", "宾馆", "商场", "商铺", "厂房", "公寓", "别墅"]) 
            _has_area = any(kw in user_message for kw in ["平米", "平方米", "m²", "m2", "m3", "㎡", "万平"])
            _has_location = any(kw in user_message for kw in ["华北", "华东", "华南", "华中", "西南", "西北", "东北", "北京", "上海", "广州", "深圳", "成都", "杭州", "南京", "武汉"])
            if not (_has_type and _has_area and _has_location):
                final_answer += "\n\n💡 为更精准预测，建议补充：建筑类型、总建筑面积、所在地区等参数"
            react_steps.append({
                "step": "observation",
                "content": f"预测完成：总造价 {_format_money(prediction['fused_total_cost'])}，单方造价 {prediction['fused_unit_price']:.0f} 元/m²"
            })

        elif intent == "train":
            df = self.data_loader.to_dataframe()
            if df is None or len(df) == 0:
                final_answer = "暂无训练数据。请先点击侧边栏「生成示例数据」或「导入 Excel」加载数据。"
            else:
                results = self.model_factory.train_all(df)
                trained_count = sum(1 for r in results.values() if r.get("success"))
                final_answer = f"## 模型训练完成\n\n使用 {len(df)} 条历史数据进行训练：\n\n"
                for mid, r in results.items():
                    if r.get("success"):
                        final_answer += f"- **{mid}** ({r.get('algorithm', '')})：准确率 {r['accuracy']}%，MAPE {r.get('mape', 0)}%\n"
                    else:
                        final_answer += f"- **{mid}**：训练失败（{r.get('error', '未知')}）\n"
                final_answer += f"\n> 共成功训练 {trained_count} 个模型，使用 {backend_note if 'backend_note' in dir() else 'scikit-learn'}"
                tool_result = results
                react_steps.append({"step": "observation", "content": f"训练完成：{trained_count}/{len(results)} 成功"})

        elif intent == "explain_term":
            final_answer = _explain_term(user_message)

        elif intent == "list_models":
            models = self.model_factory.list_models()
            trained = sum(1 for m in models if m.get("is_trained"))
            final_answer = f"## 模型清单\n\n共 {len(models)} 个模型，已训练 {trained} 个：\n\n"
            for m in models:
                status = "✓ 已训练" if m.get("is_trained") else "✗ 未训练"
                final_answer += f"- **{m['name']}** ({m['algorithm']}) — {status}"
                if m.get("is_trained"):
                    final_answer += f"，准确率 {m['accuracy']}%，{m['train_samples']} 样本"
                final_answer += "\n"
            tool_result = {"models": models}

        elif intent == "find_similar":
            raw_type = params.get("project_type", "")
            normalized_type = MockLLM.normalize_building_type(raw_type)
            similar = self.data_loader.find_similar_projects(
                normalized_type,
                params.get("structure_type", ""),
                params.get("total_area", 0),
            )
            tool_result = {"similar_projects": similar}
            final_answer = self._format_similar(similar)

        elif intent == "check_data":
            checker = DataSufficiencyChecker()
            df = self.data_loader.to_dataframe()
            if df is None or len(df) == 0:
                final_answer = "当前无任何训练数据。请先导入 Excel 项目数据或生成示例数据。"
            else:
                report = checker.assess(df)
                final_answer = self._format_sufficiency_report(report)
            tool_result = {"sufficient": report.sufficient, "score": report.score} if 'report' in dir() else None

        elif intent == "search_data":
            df = self.data_loader.to_dataframe()
            if df is None or len(df) == 0:
                final_answer = "当前无任何训练数据。请先导入 Excel 项目数据或生成示例数据。"
            else:
                checker = DataSufficiencyChecker()
                report = checker.assess(df)
                final_answer = f"## 数据充分性评估与补充建议\n\n"
                final_answer += f"**评分**: {report.score}/100 {'✅ 基本充分' if report.sufficient else '⚠️ 不足'}\n\n"
                final_answer += f"**样本统计**: 总计{report.total_samples}条（真实{report.real_samples}条，模拟{report.simulated_samples}条）\n\n"
                if report.issues:
                    final_answer += "### 发现的问题\n"
                    for issue in report.issues:
                        final_answer += f"- ⚠️ {issue}\n"
                    final_answer += "\n"
                if report.recommendations:
                    final_answer += "### 改进建议\n"
                    for rec in report.recommendations:
                        final_answer += f"- 💡 {rec}\n"
                    final_answer += "\n"
                sources = DataSufficiencyChecker.get_authoritative_sources()
                final_answer += "### 权威数据源推荐\n"
                for s in sources:
                    final_answer += f"- **{s['name']}** ({s['type']})"
                    if s.get('url'):
                        final_answer += f" - {s['url']}"
                    final_answer += f"\n  {s.get('description', '')}\n"
                final_answer += "\n> 提示：从以上来源获取数据后，可通过「导入Excel」功能添加到训练集。"
                tool_result = {"sufficient": report.sufficient, "score": report.score}

        elif intent == "cost_breakdown":
            from ml_models import predict_with_real_models
            all_models = self.model_factory.list_models()
            trained_ids = [m["id"] for m in all_models if m.get("is_trained")]
            selected = trained_ids[:5] if trained_ids else ["total_pso_svr"]
            prediction = predict_with_real_models(self.model_factory, params, selected, data_loader=self.data_loader)
            tool_result = prediction
            final_answer = self._format_breakdown(prediction)

        elif intent == "knowledge_query":
            # Provide knowledge-based guidance
            checker = DataSufficiencyChecker()
            df = self.data_loader.to_dataframe()

            # Comprehensive typical ranges for ALL building types
            typical_ranges = {
                '医院': (3500, 8000, "医院项目因功能复杂、设备要求高，单方造价通常在3500-8000元/m²"),
                '学校': (2500, 5000, "学校项目因结构相对简单，单方造价通常在2500-5000元/m²"),
                '办公楼': (3000, 7000, "办公楼项目因装修标准和设备配置差异大，单方造价通常在3000-7000元/m²"),
                '商业': (3000, 8000, "商业项目因功能和地段差异，单方造价通常在3000-8000元/m²"),
                '住宅': (2000, 5000, "住宅项目因结构类型和装修标准差异，单方造价通常在2000-5000元/m²"),
                '工业': (1500, 4000, "工业建筑因用途和跨度不同，单方造价通常在1500-4000元/m²"),
                '基础设施': (1000, 5000, "基础设施项目因类型差异大（道路/桥梁/管网等），造价区间较宽"),
                '公共': (2500, 6000, "公共建筑因功能多样，单方造价通常在2500-6000元/m²"),
            }

            # Check if the queried type exists in training data
            found_type = False
            if df is not None and '建筑类型' in df.columns:
                # Try to detect which type user is asking about
                for bt in ['医院', '学校', '办公楼', '商业', '工业', '住宅', '基础设施', '公共']:
                    if bt in user_message:
                        found_type = True
                        matching = df[df['建筑类型'].str.contains(bt, na=False)]
                        if len(matching) > 0:
                            prices = pd.to_numeric(matching['单方造价'], errors='coerce')
                            final_answer = f"## 当前数据中有{bt}类型项目\n\n"
                            final_answer += f"- 样本数: {len(matching)}个\n"
                            final_answer += f"- 单方造价范围: {prices.min():.0f} ~ {prices.max():.0f} 元/m²\n"
                            final_answer += f"- 平均单方造价: {prices.mean():.0f} 元/m²\n"
                        else:
                            final_answer = f"## 当前数据中缺少{bt}类型项目\n\n"
                            final_answer += "> 以下为本模型基于行业经验提供的参考信息，非基于本地训练数据\n\n"
                            if bt in typical_ranges:
                                low, high, desc = typical_ranges[bt]
                                final_answer += f"**{bt}项目典型单方造价**: {low} ~ {high} 元/m²\n\n"
                                final_answer += f"{desc}\n\n"
                            final_answer += "### 建议\n"
                            final_answer += f"为提高{bt}类型项目的预测准确性，建议补充该类真实项目数据。\n"
                            final_answer += "可参考来源：各省建设工程造价管理总站发布的造价指标。\n"
                        break

            if not found_type:
                # No specific building type detected — provide general overview
                final_answer = "## 各类建筑典型单方造价参考\n\n"
                final_answer += "> 以下为本模型基于行业经验提供的参考信息，非基于本地训练数据\n\n"
                for bt, (low, high, desc) in typical_ranges.items():
                    final_answer += f"- **{bt}**: {low} ~ {high} 元/m²\n"
                final_answer += "\n请问您想了解哪种建筑类型的详细造价信息？"
                final_answer += "（住宅/学校/医院/办公楼/商业建筑/工业建筑/基础设施/公共建筑）"

        elif intent == "feedback":
            response_parts = []
            if any(kw in user_message for kw in ["太便宜", "偏低", "便宜"]):
                response_parts.append("## 关于造价偏低的分析\n\n")
                response_parts.append("您提出的质疑很有价值。单方造价受以下因素影响：\n\n")
                response_parts.append("### 地区差异\n")
                response_parts.append("- 不同地区的材料价格、人工成本、运输费用差异显著\n")
                response_parts.append("- 成都地区作为西南地区核心城市，造价水平处于中等偏上\n")
                response_parts.append("- 一线城市（北京/上海/深圳）通常比成都高15-30%\n")
                response_parts.append("- 三四线城市通常比成都低10-20%\n\n")
                response_parts.append("### 项目规模影响\n")
                response_parts.append("- 小型项目（<10000m²）因固定成本分摊，单方造价通常更高\n")
                response_parts.append("- 大型项目可享受规模经济效应\n\n")
                response_parts.append("### 建议\n")
                response_parts.append("- 如需更精准预测，请提供具体地区（如成都高新区 vs 成都郊县）\n")
                response_parts.append("- 可参考当地建设工程造价管理总站发布的最新造价指标\n")
                response_parts.append("- 建议补充同地区同类项目的真实数据以提高预测准确性\n")
            elif any(kw in user_message for kw in ["地区", "区域", "地方", "城市"]):
                response_parts.append("## 地区差异对造价的影响\n\n")
                response_parts.append("地区是影响工程造价的关键因素之一：\n\n")
                response_parts.append("| 地区 | 相对造价指数 | 说明 |\n")
                response_parts.append("|------|------------|------|\n")
                response_parts.append("| 一线城市（北上广深） | 1.15~1.30 | 人工/材料/运输成本最高 |\n")
                response_parts.append("| 新一线城市（成都/杭州/武汉等） | 1.00~1.10 | 基准水平 |\n")
                response_parts.append("| 二三线城市 | 0.85~1.00 | 成本相对较低 |\n")
                response_parts.append("| 县城/乡镇 | 0.75~0.90 | 最低但运输成本可能增加 |\n\n")
                response_parts.append("> 以上为行业经验参考值，实际造价需结合具体项目条件。\n")
            final_answer = "".join(response_parts) if response_parts else "感谢您的反馈。请问您具体关注哪方面的信息？我可以提供更详细的分析。"

        elif intent == "supplement":
            response_parts = []
            response_parts.append("收到您的补充信息。让我重新分析：\n\n")
            new_params = self.mock_llm.extract_params(user_message)
            if new_params.get('total_area'):
                response_parts.append(f"- 建筑面积更新为：{new_params['total_area']} m²\n")
            if new_params.get('project_type'):
                response_parts.append(f"- 建筑类型：{new_params['project_type']}\n")
            if new_params.get('location'):
                response_parts.append(f"- 所在地区：{new_params['location']}\n")
            response_parts.append("\n请告诉我完整的预测需求，我将基于最新信息重新预测。")
            final_answer = "".join(response_parts)

        elif intent == "region_refine":
            # Extract the region from user's message
            region = None
            for kw in ["高新区", "新区", "开发区", "科技园", "工业园", "经开区", "自贸区", "CBD", "中心区"]:
                if kw in user_message:
                    for city in ["成都", "北京", "上海", "广州", "深圳", "杭州", "武汉", "重庆", "西安", "南京", "天津", "苏州", "长沙"]:
                        if city in user_message:
                            region = f"{city}{kw}"
                            break
                    if not region:
                        region = kw
                    break
            if not region:
                match = re.search(r'([\u4e00-\u9fa5]{2,4}(?:高新区|新区|开发区|科技园|工业园|经开区))', user_message)
                if match:
                    region = match.group(1)
            if not region:
                # Try to find any city mentioned
                for city in ["成都", "北京", "上海", "广州", "深圳", "杭州", "武汉", "重庆", "西安", "南京", "天津", "苏州", "长沙"]:
                    if city in user_message:
                        region = city
                        break

            if region:
                final_answer = f"## {region}地区造价分析\n\n"
                final_answer += f"针对您提到的**{region}**地区，以下是专业分析：\n\n"
                final_answer += "### 地区造价特点\n"
                if "高新" in region:
                    final_answer += "- 高新区通常基础设施完善，施工条件较好\n"
                    final_answer += "- 但土地成本和人工成本可能略高于普通城区\n"
                    final_answer += "- 建筑材料运输便利，物流成本较低\n"
                    final_answer += "- 综合造价指数通常比所在城市平均水平高 **5-15%**\n\n"
                elif "新区" in region:
                    final_answer += "- 新区建设标准通常较高\n"
                    final_answer += "- 可能存在基础设施配套不完善的额外成本\n"
                    final_answer += "- 综合造价指数与所在城市平均水平基本持平\n\n"
                elif "CBD" in region or "中心" in region:
                    final_answer += "- 核心区域施工场地受限，运输组织成本高\n"
                    final_answer += "- 人工成本、材料运输成本均高于外围区域\n"
                    final_answer += "- 综合造价指数通常比所在城市平均水平高 **10-20%**\n\n"
                else:
                    final_answer += f"- {region}作为特定功能区域，有其独特的造价特征\n"
                    final_answer += "- 需结合当地材料价格、人工成本、运输条件综合分析\n"
                    final_answer += "- 综合造价指数通常比所在城市平均水平高 **5-15%**\n\n"
                final_answer += "### 建议\n"
                final_answer += f"- 如需精准预测{region}项目，建议补充该地区同类项目的真实数据\n"
                final_answer += "- 可参考当地建设工程造价管理总站发布的分区造价指标\n"
                final_answer += "- 不同区域的材料价格、人工成本差异可达10-20%\n"
            else:
                final_answer = "请告诉我您具体想了解哪个地区的造价情况？例如：成都高新区、北京朝阳区等。"

        elif intent == "repredict":
            new_params = self.mock_llm.extract_params(user_message)
            
            # Check for specific parameter changes
            changes = []
            if new_params.get('total_area'):
                changes.append(f"面积: {new_params['total_area']} m²")
            if new_params.get('floors'):
                changes.append(f"楼层: {new_params['floors']} 层")
            if new_params.get('project_type'):
                changes.append(f"类型: {new_params['project_type']}")
            if new_params.get('region'):
                changes.append(f"地区: {new_params['region']}")
            
            if changes:
                final_answer = "## 参数调整分析\n\n"
                final_answer += "基于您的调整：\n\n"
                for c in changes:
                    final_answer += f"- {c}\n"
                final_answer += "\n"
                
                # Provide analysis based on the change
                if new_params.get('floors'):
                    floors = new_params['floors']
                    final_answer += f"### {floors}层建筑造价分析\n\n"
                    if floors <= 6:
                        final_answer += "- 多层建筑，通常采用砖混或框架结构\n"
                        final_answer += "- 单方造价相对较低，约 2000-4000 元/m²\n"
                        final_answer += "- 无需电梯，公摊面积小\n"
                    elif floors <= 18:
                        final_answer += "- 小高层建筑，通常采用框架或框剪结构\n"
                        final_answer += "- 单方造价中等，约 3000-5000 元/m²\n"
                        final_answer += "- 需配置电梯，基础要求较高\n"
                    else:
                        final_answer += "- 高层建筑，通常采用框剪或剪力墙结构\n"
                        final_answer += "- 单方造价较高，约 4000-7000 元/m²\n"
                        final_answer += "- 基础工程量大，结构要求严格\n"
                    final_answer += f"\n> 以上为行业经验参考，实际造价需结合具体项目条件。\n"
                else:
                    final_answer += "请提供完整项目参数，我将重新预测。"
            else:
                final_answer = "请告诉我具体要调整哪个参数？例如：改为20层、面积5000m²等。"

        elif intent == "compare":
            # Try to detect what's being compared
            final_answer = "## 造价对比分析\n\n"
            
            # Check if comparing building types
            if any(kw in user_message for kw in ["住宅", "酒店", "学校", "医院", "办公", "商业"]):
                final_answer += "### 不同建筑类型单方造价参考\n\n"
                final_answer += "| 类型 | 典型范围(元/m²) | 说明 |\n"
                final_answer += "|------|----------------|------|\n"
                final_answer += "| 住宅 | 2000-4500 | 结构相对简单 |\n"
                final_answer += "| 商业/酒店 | 3000-8000 | 装修和设备要求高 |\n"
                final_answer += "| 办公楼 | 3000-7000 | 机电系统复杂 |\n"
                final_answer += "| 学校 | 2500-5000 | 功能相对标准化 |\n"
                final_answer += "| 医院 | 3500-8000 | 专业设备要求高 |\n\n"
                final_answer += "> 酒店通常比住宅高 **30-80%**，主要差异在装修标准、机电系统和消防设施。\n"
            else:
                final_answer += "| 对比维度 | 造价差异 |\n|------|------|\n"
                final_answer += "| 一线 vs 新一线 | +15~30% |\n"
                final_answer += "| 核心区 vs 郊区 | +5~15% |\n"
                final_answer += "| 高层 vs 多层 | +20~40% |\n"
            
            final_answer += "\n请说明具体对比条件，我可以提供更精准的分析。"

        elif intent == "data_query":
            checker = DataSufficiencyChecker()
            df = self.data_loader.to_dataframe()
            
            if df is not None and len(df) > 0:
                # Check what types exist
                types = df['建筑类型'].value_counts().to_dict() if '建筑类型' in df.columns else {}
                
                # Try to detect what type user is asking about
                asked_type = None
                for bt in ['酒店', '宾馆', '住宅', '学校', '医院', '办公楼', '商业', '工业', '基础设施', '公共']:
                    if bt in user_message:
                        asked_type = bt
                        break
                
                final_answer = "## 训练数据情况\n\n"
                final_answer += f"当前训练集共 **{len(df)}** 条项目数据：\n\n"
                
                if asked_type:
                    # Map to training data type
                    type_map = {'酒店': '商业建筑', '宾馆': '商业建筑', '饭店': '商业建筑'}
                    mapped_type = type_map.get(asked_type, asked_type)
                    count = types.get(mapped_type, 0)
                    
                    if count > 0:
                        final_answer += f"### {asked_type}（{mapped_type}）\n\n"
                        final_answer += f"✅ 当前数据中有 **{count}** 个{mapped_type}类型项目\n\n"
                        subset = df[df['建筑类型'] == mapped_type]
                        prices = pd.to_numeric(subset['单方造价'], errors='coerce')
                        final_answer += f"- 单方造价范围：{prices.min():.0f} ~ {prices.max():.0f} 元/m²\n"
                        final_answer += f"- 平均单方造价：{prices.mean():.0f} 元/m²\n"
                    else:
                        final_answer += f"### {asked_type}项目\n\n"
                        final_answer += f"⚠️ 当前训练数据中**没有**{asked_type}类型项目\n\n"
                        final_answer += f"> 以下为基于行业经验的参考信息，非基于本地训练数据\n\n"
                        # Provide knowledge-based info
                        if asked_type in ['酒店', '宾馆']:
                            final_answer += "**酒店项目典型单方造价**: 3000 ~ 8000 元/m²\n\n"
                            final_answer += "- 经济型酒店：3000-4500 元/m²\n"
                            final_answer += "- 中档酒店：4500-6000 元/m²\n"
                            final_answer += "- 高档/度假酒店：6000-8000+ 元/m²\n\n"
                            final_answer += "酒店造价受星级标准、装修档次、配套设施影响显著。\n"
                        final_answer += f"\n**建议**: 补充{asked_type}类型真实项目数据以提高预测准确性。\n"
                
                if not asked_type:
                    final_answer += "### 各类型分布\n\n"
                    for bt, count in sorted(types.items(), key=lambda x: -x[1]):
                        final_answer += f"- {bt}: {count}个\n"
            else:
                final_answer = "当前暂无训练数据。请先导入Excel项目数据。"

        else:
            if intent == "greeting":
                final_answer = ("您好！我是北辰造价助手，专注于建筑工程造价预测与分析。\n\n"
                                "我可以帮您：\n"
                                "- **造价预测**：描述项目信息（类型、面积、地区等），即可获得预测结果\n"
                                "- **模型训练**：使用历史项目数据训练预测模型\n"
                                "- **术语解释**：解答建筑造价专业术语\n"
                                "- **数据检查**：评估训练数据是否充分\n\n"
                                "试试说：「帮我预测一个5万平米住宅项目的造价」")
            elif intent == "thanks":
                final_answer = "不客气！如果还有其他造价相关的问题，随时可以问我。祝您工作顺利！"
            elif intent == "help":
                final_answer = ("## 功能介绍\n\n"
                                "我是北辰造价助手，核心功能包括：\n\n"
                                "1. **造价预测** — 输入项目描述，自动预测总造价和单方造价\n"
                                "   例：「预测5万平米华东住宅项目造价」\n\n"
                                "2. **模型训练** — 用历史数据训练/更新预测模型\n"
                                "   例：「训练所有模型」\n\n"
                                "3. **术语解释** — 解答建筑造价专业术语含义\n"
                                "   例：「什么是工程量清单计价法」\n\n"
                                "4. **数据评估** — 检查训练数据充分性\n"
                                "   例：「数据充分吗」\n\n"
                                "5. **相似项目** — 查找历史相似项目\n"
                                "   例：「找类似的住宅项目」")
            else:
                # Context-aware general handler
                location_keywords = ["区", "市", "省", "县", "镇", "街道", "高新区", "新区", "开发区"]
                has_location = any(kw in user_message for kw in location_keywords)
                if has_location:
                    final_answer = "我注意到您提到了地区信息。请问您是想：\n\n"
                    final_answer += "1. **了解该地区的造价水平** — 我可以提供地区差异分析\n"
                    final_answer += "2. **基于该地区重新预测** — 请提供完整项目参数\n"
                    final_answer += "3. **对比不同地区** — 请说明对比的地区\n"
                elif history and len(history) > 2:
                    final_answer = "感谢您的消息。基于我们之前的对话，请问您具体想了解：\n\n"
                    final_answer += "- **调整预测参数**（请说明要修改的内容）\n"
                    final_answer += "- **深入了解造价构成**（我可以详细解释）\n"
                    final_answer += "- **了解地区差异**（请说明具体地区）\n"
                    final_answer += "- **其他问题**（请具体描述）"
                else:
                    final_answer = "您好！请告诉我您的项目信息，我来帮您预测造价。\n\n"
                    final_answer += "需要：建筑类型、总建筑面积、结构类型、所在地区、楼层数、装修标准"

        react_steps.append({"step": "final_answer", "content": final_answer[:200]})

        # Safety net: ensure reply is never empty or too short
        if not final_answer or len(final_answer.strip()) < 10:
            print(f"[mock llm safety net] final_answer was empty/short (len={len(final_answer) if final_answer else 0}), intent={intent}")
            final_answer = f"我理解了您的输入：「{user_message}」\n\n抱歉，我暂时无法给出详细回答。请尝试：\n- 描述具体的建筑项目信息来进行造价预测\n- 询问建筑造价术语的含义\n- 检查训练数据是否充分\n\n请问您需要什么帮助？"

        print(f"[mock llm] intent={intent}, reply_len={len(final_answer)}, backend=ml_engine")
        return {
            "session_id": session_id,
            "reply": final_answer,
            "react_steps": react_steps,
            "tool_result": tool_result,
            "backend": "ml_engine",
            "history_count": len(history) + 2,
        }

    def _format_sufficiency_report(self, report) -> str:
        text = "## 数据充分性评估\n\n"
        text += f"**评分**: {report.score}/100 {'✅ 基本充分' if report.sufficient else '⚠️ 不足'}\n\n"
        text += f"**样本统计**: 总计{report.total_samples}条（真实{report.real_samples}条，模拟{report.simulated_samples}条）\n\n"
        if report.issues:
            text += "### 发现的问题\n"
            for issue in report.issues:
                text += f"- ⚠️ {issue}\n"
        if report.recommendations:
            text += "\n### 改进建议\n"
            for rec in report.recommendations:
                text += f"- 💡 {rec}\n"
        if report.category_coverage:
            text += "\n### 建筑类型覆盖\n"
            for cat, count in report.category_coverage.items():
                status = "✅" if count >= 5 else "⚠️"
                text += f"- {status} {cat}: {count}条\n"
        return text

    def _format_prediction(self, prediction: Dict, backend: str = "") -> str:
        total = prediction["fused_total_cost"]
        unit = prediction["fused_unit_price"]
        unit_raw = prediction.get("fused_unit_price_raw", unit)
        acc = prediction["average_accuracy"]
        area = prediction["project"]["area"]
        name = prediction["project"]["name"]
        scale_factor = prediction.get("scale_factor", 1.0)
        scale_note = prediction.get("scale_note", "")

        text = f"## 造价预测结果\n\n"
        text += f"**项目**: {name}\n\n"
        text += f"### 核心数据\n"
        text += f"- **项目总造价**: {_format_money(total)}\n"
        text += f"- **单方造价**: {unit:,.0f} 元/m²"
        if abs(scale_factor - 1.0) > 0.001:
            text += f"  （调整后，原始预测 {unit_raw:,.0f} 元/m²）\n"
        else:
            text += "\n"
        text += f"- **总建筑面积**: {area:,.0f} m²\n"
        text += f"- **综合预测精度**: {acc}%\n"
        text += f"- **使用模型数**: {prediction['model_count']}\n"
        if backend:
            text += f"- **训练后端**: {backend}\n"

        # 规模调整说明
        if abs(scale_factor - 1.0) > 0.001 and scale_note:
            text += f"\n> 📏 {scale_note}\n"

        # NEW: 置信区间
        ci = prediction.get("confidence_interval")
        if ci and ci.get("lower") != ci.get("upper"):
            text += f"\n### 预测区间\n"
            text += f"- 单方造价区间: {ci['lower']:,.0f} ~ {ci['upper']:,.0f} 元/m²（置信度 {ci.get('level', '68%')}）\n"

        # NEW: 参考项目（含类型匹配警告）
        ref_warning = prediction.get("reference_warning", "")
        ref_projects = prediction.get("reference_projects", [])
        if ref_projects:
            text += f"\n### 参考项目\n"
            if ref_warning:
                text += f"> ⚠️ {ref_warning}\n\n"
            for p in ref_projects:
                text += f"- {p['name']} — {p.get('area', 0):,.0f}m², {p.get('unit_price', 0):,.0f}元/m²\n"

        # NEW: 数据充分性
        evidence = prediction.get("model_evidence")
        if evidence and evidence.get("data_sufficiency_score", 100) < 60:
            text += f"\n> ⚠️ 训练数据不足（评分{evidence['data_sufficiency_score']:.0f}），预测结果仅供参考\n"

        text += "\n### 费用构成\n"
        if "composition" in prediction:
            for cat, data in prediction["composition"].items():
                text += f"- {cat}：{data['ratio']*100:.0f}%（{_format_money(data['amount'])}）\n"
        text += "\n### 使用的模型\n"
        for mid in prediction.get("selected_models", []):
            m = self.model_factory.get_model(mid)
            if m:
                status = f"准确率 {m.info.accuracy}%" if m.info.is_trained else "未训练"
                text += f"- {m.info.name}（{m.info.algorithm}）— {status}\n"

        # Data sources
        if "data_sources" in prediction:
            text += "\n### 数据来源\n"
            for src in prediction["data_sources"]:
                icon = "📊" if src.get("source_type") == "real" else "🔧"
                text += f"- {icon} {src.get('description', src.get('source_file', '未知'))}: {src.get('sample_count', '?')}条\n"

        return text

    def _format_similar(self, similar: List[Dict]) -> str:
        if not similar:
            return "未找到相似历史项目。请先导入 Excel 历史项目数据。"
        text = f"找到 {len(similar)} 个相似历史项目：\n\n"
        for i, p in enumerate(similar[:5], 1):
            text += f"### {i}. {p.get('项目名称', '未知')}\n"
            text += f"- 类型: {p.get('建筑类型', '-')} | 结构: {p.get('结构类型', '-')}\n"
            text += f"- 面积: {p.get('总建筑面积', '-')} m² | 单方造价: {p.get('单方造价', '-')} 元/m²\n\n"
        return text

    def _format_breakdown(self, prediction: Dict) -> str:
        text = "## 六层级成本分解\n\n"
        text += "**L1 项目总造价**: " + _format_money(prediction["fused_total_cost"]) + "\n\n"
        text += "**L2 单项工程**: 按主要功能划分\n\n"
        text += "**L3 单位工程**: 土建 55% / 安装 25% / 装饰 20%\n\n"
        if "composition" in prediction:
            text += "**L4 分部工程**:\n"
            for cat, data in prediction["composition"].items():
                text += f"  - {cat}：{data['ratio']*100:.0f}%\n"
        text += "\n**L5 分项工程**: 混凝土、钢筋、砌体、抹灰等\n\n"
        text += "**L6 明细级别**: 工程量清单基本单元\n"
        return text


def _explain_term(text: str) -> str:
    """术语解释"""
    terms = {
        "估算": "**投资估算**：发生在项目建议书和可行性研究阶段，基于类似工程经验、估算指标进行的初步投资测算。误差率约 ±20%，精度 70-80%。",
        "概算": "**设计概算**：在初步设计或施工图设计阶段，以设计图纸、概算定额为依据编制的投资测算。误差率约 ±10%，精度 80-90%。",
        "预算": "**施工图预算**：基于施工图纸及施工组织设计，按照《建设工程工程量清单计价规范》详细计算。误差率约 ±3%，精度 95%+。",
        "结算": "**工程结算**：施工单位与建设单位根据合同对工程价款进行结算的过程，包含中间结算、竣工结算等。",
        "决算": "**竣工决算**：整个项目竣工后对实际花费的财务汇总，是项目经济评价的最终依据。",
        "工程量清单": "**工程量清单**：依据《建设工程工程量清单计价规范》（GB50500），载明建设工程分部分项工程项目、措施项目、其他项目、规费税金项目的名称、规格、数量等的明细清单。",
        "计价": "**工程量清单计价法**：一种国际通行的工程造价计价方式，以工程量清单为载体，由投标人根据企业定额和市场信息自主报价。其核心是「量价分离」——工程量由招标人统一提供，单价由投标人自主确定。包含分部分项工程费、措施项目费、其他项目费、规费和税金五部分。",
        "定额": "**定额**：在正常施工条件下，完成一定计量单位的合格产品所消耗的人工、材料、机械台班的数量标准。",
        "直接费": "**直接费**：直接构成工程实体或有助于工程实体形成的费用，包括直接工程费和措施费。",
        "间接费": "**间接费**：建筑安装企业为组织施工生产和经营管理所需的费用，包括企业管理费、规费等。",
        "单方造价": "**单方造价**：每平方米建筑面积的造价金额，是衡量项目经济性的重要指标。计算公式：单方造价 = 总造价 ÷ 总建筑面积。",
        "框架结构": "**框架结构**：由梁和柱以刚接或铰接相连接而构成的承重结构体系，具有空间分隔灵活、自重轻等优点，广泛应用于办公楼、学校等公共建筑。",
        "剪力墙结构": "**剪力墙结构**：用钢筋混凝土墙板来代替框架结构中的梁柱，承担各类荷载引起的内力，常用于住宅建筑。",
    }
    for kw, exp in terms.items():
        if kw in text:
            return exp
    return "请告诉我具体想了解哪个建筑造价术语？例如：估算、概算、预算、工程量清单、定额、直接费、间接费等。"
