"""
FastAPI 主服务 - AI 造价预测系统
"""
from __future__ import annotations
import os
import sys
import json
import asyncio
import random
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

# 添加 backend 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from terminology import (
    COST_STAGES, COST_HIERARCHY, PROJECT_TYPES, STRUCTURE_TYPES,
    ESTIMATION_PARAMS, MODELS_REGISTRY, get_stage_info, get_param_categories
)
from ml_models import RealModelFactory, predict_with_real_models
from data_loader import DataLoader, generate_sample_excel
from model_config import ModelConfigManager
from agent import CostAgentManager, AGENTSCOPE_AVAILABLE


# ==================== App 初始化 ====================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(ROOT, "frontend")
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_DIR = os.path.join(ROOT, "output")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="AI 建筑工程造价预测系统", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局单例
MODELS_CACHE_DIR = os.path.join(ROOT, "models_cache")
data_loader = DataLoader(data_dir=DATA_DIR)
model_factory = RealModelFactory(models_dir=MODELS_CACHE_DIR)
model_config_mgr = ModelConfigManager()
cost_agent = CostAgentManager(model_factory, data_loader, model_config_mgr)

# 启动时自动加载已有的示例训练数据
_sample_path = os.path.join(DATA_DIR, "sample_training_data.xlsx")
if os.path.exists(_sample_path) and not data_loader.history:
    try:
        with open(_sample_path, "rb") as _f:
            data_loader.import_from_excel(_f.read(), "sample_training_data.xlsx")
    except Exception:
        pass

# 内存会话存储
SESSIONS: Dict[str, List[Dict]] = {}
PROJECTS: Dict[str, Dict] = {}


# ==================== Pydantic 模型 ====================
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ProjectRequest(BaseModel):
    project_name: str
    project_type: str
    structure_type: str
    total_area: float
    floors: int
    location: str
    build_year: int = 2026
    decoration_level: str = "普通装修"
    stage: str = "estimation"
    selected_models: Optional[List[str]] = None
    basement_area: float = 0
    building_height: float = 0


# ==================== API 路由 ====================
@app.get("/")
async def index():
    """首页"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Frontend not found</h1>")


@app.get("/app")
async def app_page():
    """应用主界面"""
    app_path = os.path.join(FRONTEND_DIR, "app.html")
    if os.path.exists(app_path):
        return FileResponse(app_path)
    return HTMLResponse("<h1>App not found</h1>")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "framework": "AgentScope SDK " + ("(real)" if AGENTSCOPE_AVAILABLE else "(not installed)"),
        "agentscope_version": _get_agentscope_version(),
        "ml_backend": "scikit-learn + xgboost",
        "data_count": len(data_loader.history),
        "trained_models": sum(1 for m in model_factory.list_models() if m.get("is_trained")),
        "has_active_llm": model_config_mgr.has_active_llm(),
    }


@app.get("/api/terminology/stages")
async def get_stages():
    """获取三阶段造价定义"""
    return COST_STAGES


@app.get("/api/terminology/hierarchy")
async def get_hierarchy():
    """获取六层级成本分解"""
    return COST_HIERARCHY


@app.get("/api/terminology/project-types")
async def get_project_types():
    return PROJECT_TYPES


@app.get("/api/terminology/structure-types")
async def get_structure_types():
    return STRUCTURE_TYPES


@app.get("/api/models")
async def list_models():
    """列出所有模型（按层级）"""
    return model_factory.get_models_by_layer()


@app.get("/api/models/all")
async def list_all_models():
    return MODELS_REGISTRY


@app.get("/api/stage/{stage}/params")
async def get_stage_params(stage: str):
    """获取指定阶段的参数配置"""
    info = get_stage_info(stage)
    if not info:
        raise HTTPException(404, "Stage not found")
    return {
        "stage": info,
        "categories": get_param_categories(stage)
    }


@app.post("/api/predict")
async def predict_project(req: ProjectRequest):
    """使用真实训练的三层模型进行造价预测"""
    project = {
        "project_name": req.project_name,
        "project_type": req.project_type,
        "structure_type": req.structure_type,
        "total_area": req.total_area,
        "floors": req.floors,
        "location": req.location,
        "build_year": req.build_year,
        "decoration_level": req.decoration_level,
        "stage": req.stage,
        "basement_area": req.basement_area,
        "building_height": req.building_height,
    }

    # 默认模型：每个层级选一个
    if not req.selected_models:
        if req.stage == "estimation":
            req.selected_models = ["total_pso_svr", "section_xgb", "indicator_rf"]
        elif req.stage == "preliminary":
            req.selected_models = ["total_pso_svr", "unit_gbt", "section_xgb", "item_xgb", "indicator_rf"]
        else:
            req.selected_models = [
                "total_pso_svr", "unit_gbt", "section_xgb",
                "subsection_xgb", "item_xgb", "indicator_rf",
                "boq_apriori", "boq_lr"
            ]

    # 优先用已训练模型，未训练的也加入（会用基准价兜底）
    all_models = model_factory.list_models()
    trained_ids = {m["id"] for m in all_models if m.get("is_trained")}
    selected = [mid for mid in req.selected_models if mid in trained_ids] or req.selected_models

    result = predict_with_real_models(model_factory, project, selected)
    result["stage"] = req.stage
    result["stage_info"] = COST_STAGES.get(req.stage, {})
    result["predicted_at"] = datetime.now().isoformat()

    # 存储项目
    project_id = f"PRJ{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100, 999)}"
    PROJECTS[project_id] = {
        "id": project_id,
        "input": req.dict(),
        "result": result,
        "created_at": datetime.now().isoformat()
    }
    result["project_id"] = project_id

    return result


@app.post("/api/chat")
async def chat_with_agent(req: ChatRequest):
    """与 ReAct 智能体对话（真实 AgentScope 优先，回退 MockLLM）"""
    if req.session_id not in SESSIONS:
        SESSIONS[req.session_id] = []

    history = SESSIONS[req.session_id]
    result = await cost_agent.chat(req.message, history, req.session_id)

    # 更新会话历史
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": result["reply"]})

    return {
        "session_id": req.session_id,
        "reply": result["reply"],
        "react_steps": result["react_steps"],
        "tool_result": result.get("tool_result"),
        "backend": result.get("backend", "unknown"),
        "history_count": len(history)
    }


@app.get("/api/chat/sessions")
async def list_sessions():
    """列出所有会话"""
    sessions = []
    for sid, msgs in SESSIONS.items():
        title = msgs[0]["content"][:30] if msgs else "空会话"
        sessions.append({
            "id": sid,
            "title": title,
            "message_count": len(msgs),
            "updated_at": datetime.now().isoformat()
        })
    return sessions


@app.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id in SESSIONS:
        del SESSIONS[session_id]
    return {"success": True}


@app.post("/api/data/import")
async def import_data(file: UploadFile = File(...)):
    """导入 Excel 训练数据"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 Excel 文件 (.xlsx, .xls)")

    content = await file.read()
    result = data_loader.import_from_excel(content, file.filename)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "导入失败"))
    return result


@app.get("/api/data/history")
async def get_history(limit: int = 50):
    return data_loader.get_history(limit=limit)


@app.get("/api/data/statistics")
async def get_statistics():
    return data_loader.get_statistics()


@app.post("/api/data/generate-sample")
async def generate_sample(n: int = 80):
    """生成示例训练数据（8 种建筑类型均衡覆盖）并自动导入"""
    output_path = os.path.join(DATA_DIR, "sample_training_data.xlsx")
    count = generate_sample_excel(output_path, n)
    # 自动加载到内存
    with open(output_path, "rb") as f:
        content = f.read()
    data_loader.import_from_excel(content, "sample_training_data.xlsx")
    return {
        "success": True,
        "file_path": output_path,
        "count": count,
        "loaded_into_memory": len(data_loader.history)
    }


@app.get("/api/projects")
async def list_projects():
    return list(PROJECTS.values())


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    if project_id not in PROJECTS:
        raise HTTPException(404, "项目不存在")
    return PROJECTS[project_id]


# ==================== 模型训练 API ====================
@app.post("/api/train")
async def train_all_models():
    """训练所有三层模型（使用已加载的历史数据）"""
    df = data_loader.to_dataframe()
    if df is None or len(df) == 0:
        raise HTTPException(400, "无训练数据，请先导入 Excel 或生成示例数据")
    results = model_factory.train_all(df)
    trained = sum(1 for r in results.values() if r.get("success"))
    return {
        "success": True,
        "total": len(results),
        "trained": trained,
        "failed": len(results) - trained,
        "sample_count": len(df),
        "results": results,
        "backend": "scikit-learn"
    }


@app.post("/api/train/{model_id}")
async def train_one_model(model_id: str):
    """训练单个模型"""
    df = data_loader.to_dataframe()
    if df is None or len(df) == 0:
        raise HTTPException(400, "无训练数据")
    result = model_factory.train_one(model_id, df)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "训练失败"))
    return result


@app.get("/api/train/status")
async def train_status():
    """获取所有模型训练状态"""
    return {
        "models": model_factory.list_models(),
        "agentscope_available": AGENTSCOPE_AVAILABLE,
        "agentscope_version": _get_agentscope_version(),
        "has_active_llm": model_config_mgr.has_active_llm(),
    }


def _get_agentscope_version():
    try:
        import agentscope
        return getattr(agentscope, "__version__", "unknown")
    except Exception:
        return None


# ==================== LLM 配置 API ====================
@app.get("/api/llm/providers")
async def list_llm_providers():
    """列出所有 LLM 提供商及状态"""
    return {
        "providers": model_config_mgr.list_providers(),
        "active_provider": model_config_mgr._active_provider,
        "has_active": model_config_mgr.has_active_llm(),
        "agentscope_available": AGENTSCOPE_AVAILABLE,
    }


@app.get("/api/llm/active")
async def get_active_llm():
    active = model_config_mgr.get_active()
    if not active:
        return {"active": None, "configured": False}
    return {
        "active": active.provider,
        "model_name": active.model_name,
        "configured": active.is_configured(),
        "stream": active.stream,
    }


@app.post("/api/llm/active")
async def set_active_llm(req: dict = Body(...)):
    """切换激活的 LLM 提供商"""
    provider = req.get("provider")
    if not provider:
        raise HTTPException(400, "provider 字段必填")
    if not model_config_mgr.set_active(provider):
        raise HTTPException(404, "提供商不存在")
    # 清空缓存的智能体，下次对话重建
    cost_agent.invalidate_agents()
    return {"success": True, "active_provider": provider}


@app.post("/api/llm/config/{provider}")
async def update_llm_config(provider: str, req: dict = Body(...)):
    """更新 LLM 提供商配置（api_key / model_name / base_url 等）"""
    if not model_config_mgr.update_provider(provider, req):
        raise HTTPException(404, "提供商不存在")
    cost_agent.invalidate_agents()
    return {"success": True, "provider": provider}


# ==================== 静态资源 ====================
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    print("🚀 启动 AI 造价预测系统...")
    print(f"   数据目录: {DATA_DIR}")
    print(f"   前端目录: {FRONTEND_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
