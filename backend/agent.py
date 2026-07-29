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
        # 10. general (兜底)
        return "general"

    def extract_params(self, text: str) -> Dict:
        params = {}
        # 面积
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:万\s*)?(?:平米|平|m²|平方米)", text)
        if m:
            v = float(m.group(1))
            if "万" in text[m.start():m.end()+5]:
                v *= 10000
            params["total_area"] = v

        # 建筑类型
        types_map = {"学校": "学校", "医院": "医院", "办公楼": "办公楼", "写字楼": "办公楼",
                     "住宅": "住宅", "厂房": "工业建筑", "工业": "工业建筑",
                     "商业": "商业建筑", "商场": "商业建筑", "公共": "公共建筑"}
        for kw, v in types_map.items():
            if kw in text:
                params["project_type"] = v
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

        params.setdefault("project_type", "学校")
        params.setdefault("structure_type", "框架结构")
        params.setdefault("location", "华东")
        params.setdefault("floors", 6)
        params.setdefault("build_year", 2026)
        params.setdefault("decoration_level", "普通装修")
        params.setdefault("project_name", "对话生成项目")
        params.setdefault("total_area", 10000)
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
        if session_id not in self._real_agents:
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

        real_agent = self.get_or_build_agent(session_id)
        if real_agent is not None:
            return await self._chat_with_real_agent(real_agent, user_message, history, session_id)
        else:
            return await self._chat_with_mock(user_message, history, session_id)

    async def _chat_with_real_agent(self, agent, user_message: str, history: List[Dict], session_id: str) -> Dict:
        """使用真实 AgentScope Agent"""
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
            if not reply_text or "waiting for your permission" in reply_text.lower() or "external execution" in reply_text.lower():
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
            print(f"[real agent chat error] {e}")
            # 回退到 Mock
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
            prediction = predict_with_real_models(self.model_factory, params, selected, data_loader=self.data_loader)
            tool_result = prediction
            final_answer = self._format_prediction(prediction, backend_note)
            if sufficiency_warning:
                final_answer += sufficiency_warning
            # Check if user provided key parameters
            _has_type = any(kw in user_message for kw in ["住宅", "学校", "医院", "办公楼", "商业", "工业", "公共", "基础设施"])
            _has_area = any(kw in user_message for kw in ["平米", "平", "m²", "平方米", "万平"])
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
            similar = self.data_loader.find_similar_projects(
                params.get("project_type", ""),
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

            # Check if the queried type exists in training data
            has_type = False
            if df is not None and '建筑类型' in df.columns:
                # Try to detect which type user is asking about
                for bt in ['医院', '学校', '办公楼', '商业', '工业', '住宅', '基础设施', '公共']:
                    if bt in user_message:
                        matching = df[df['建筑类型'].str.contains(bt, na=False)]
                        if len(matching) > 0:
                            has_type = True
                            prices = pd.to_numeric(matching['单方造价'], errors='coerce')
                            final_answer = f"## 当前数据中有{bt}类型项目\n\n"
                            final_answer += f"- 样本数: {len(matching)}个\n"
                            final_answer += f"- 单方造价范围: {prices.min():.0f} ~ {prices.max():.0f} 元/m²\n"
                            final_answer += f"- 平均单方造价: {prices.mean():.0f} 元/m²\n"
                        else:
                            final_answer = f"## 当前数据中缺少{bt}类型项目\n\n"
                            final_answer += "> 以下为本模型基于行业经验提供的参考信息，非基于本地训练数据\n\n"
                            # Provide typical ranges based on general knowledge
                            typical_ranges = {
                                '医院': (3500, 8000, "医院项目因功能复杂、设备要求高，单方造价通常在3500-8000元/m²"),
                                '学校': (2500, 5000, "学校项目因结构相对简单，单方造价通常在2500-5000元/m²"),
                                '办公楼': (3000, 7000, "办公楼项目因装修标准和设备配置差异大，单方造价通常在3000-7000元/m²"),
                                '商业': (3000, 8000, "商业项目因功能和地段差异，单方造价通常在3000-8000元/m²"),
                            }
                            if bt in typical_ranges:
                                low, high, desc = typical_ranges[bt]
                                final_answer += f"**{bt}项目典型单方造价**: {low} ~ {high} 元/m²\n\n"
                                final_answer += f"{desc}\n\n"
                            final_answer += "### 建议\n"
                            final_answer += f"为提高{bt}类型项目的预测准确性，建议补充该类真实项目数据。\n"
                            final_answer += "可参考来源：各省建设工程造价管理总站发布的造价指标。\n"
                        break

            if not has_type and 'final_answer' not in dir():
                final_answer = "请告诉我您想了解哪种建筑类型的造价信息？（住宅/学校/医院/办公楼/商业建筑/工业建筑/基础设施/公共建筑）"

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
                final_answer = (f"我理解了您的输入：「{user_message}」\n\n"
                                "作为造价助手，我可以帮您完成以下操作：\n"
                                "1. **造价预测** — 告诉我项目类型、面积、地区等信息\n"
                                "2. **模型训练** — 用历史数据训练预测模型\n"
                                "3. **术语解释** — 解答建筑造价专业术语\n"
                                "4. **相似项目检索** — 查找历史相似项目\n\n"
                                "请问您具体想了解或预测什么？我可以更精准地帮助您。")

        react_steps.append({"step": "final_answer", "content": final_answer[:200]})

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
