"""
FastAPI 主服务 - AI 造价预测系统
"""
from __future__ import annotations
import os
import sys
import json
import uuid
import shutil
import asyncio
import random
import logging
import socket
import threading
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field

# ==================== 日志配置 ====================
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
os.makedirs(LOG_DIR, exist_ok=True)
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
# 文件日志（轮转，单文件 5MB，保留 5 份）
_file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
logging.getLogger().addHandler(_file_handler)
logger = logging.getLogger("cost_prediction.main")

# 添加 backend 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from terminology import (
    COST_STAGES, COST_HIERARCHY, PROJECT_TYPES, STRUCTURE_TYPES,
    ESTIMATION_PARAMS, PRELIMINARY_PARAMS, BUDGET_PARAMS,
    MODELS_REGISTRY, get_stage_info, get_param_categories
)
from ml_models import RealModelFactory, predict_with_real_models
from data_loader import DataLoader, generate_sample_excel
from model_config import ModelConfigManager
from agent import CostAgentManager, AGENTSCOPE_AVAILABLE
from document_parser import DocumentParser, ParseResult
from feature_extractor import FeatureExtractor


# ==================== App 初始化 ====================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(ROOT, "frontend")
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_DIR = os.path.join(ROOT, "output")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="AI 建筑工程造价预测系统", version="1.0.0")

# CORS 配置
# 生产环境通过环境变量 CORS_ORIGINS 配置，逗号分隔，例如：
#   CORS_ORIGINS=https://example.com,https://app.example.com
# 安全策略：默认仅允许本地开发来源，禁止通配符 "*" 与 allow_credentials=True 组合
_DEFAULT_CORS = ["http://localhost:8000", "http://127.0.0.1:8000"]
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] or _DEFAULT_CORS

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 全局异常处理 ====================
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """全局异常兜底：记录日志并返回 500，避免堆栈信息泄漏给客户端"""
    logger.exception("未处理的服务器异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试或联系管理员。"},
    )

# 预测文件上传配置
UPLOAD_DIR = os.path.join(ROOT, 'data', 'uploads')
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {'.docx', '.doc', '.pdf', '.xlsx', '.xls'}
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 上传任务有效期（小时）与单次清理上限
UPLOAD_TTL_HOURS = 24
UPLOAD_CLEANUP_BATCH = 200


def _safe_upload_filename(task_id: str, original_filename: str) -> str:
    """生成安全的保存文件名：仅保留白名单扩展名，丢弃原始文件名（防路径穿越）。

    原始文件名可能包含 '../'、绝对路径、分隔符等，绝不能直接拼入路径。
    最终保存名为 "{task_id}{ext}"，与 task_id 一一对应。
    """
    ext = os.path.splitext(original_filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ""
    return f"{task_id}{ext}"


def _cleanup_expired_uploads():
    """清理过期上传记录及对应临时文件（惰性调用，限制单次处理量）。

    清理两类：
    1. prediction_uploads 表中 expires_at 已过期的记录
    2. uploads 目录中与数据库记录无关的孤儿文件
    """
    try:
        import duckdb
        conn = duckdb.connect(DB_PATH)
        try:
            expired = conn.execute(
                "SELECT task_id FROM prediction_uploads WHERE expires_at < CURRENT_TIMESTAMP LIMIT ?",
                [UPLOAD_CLEANUP_BATCH],
            ).fetchall()
            for (tid,) in expired:
                conn.execute("DELETE FROM prediction_uploads WHERE task_id = ?", [tid])
                for f in os.listdir(UPLOAD_DIR):
                    if f.startswith(tid):
                        try:
                            os.remove(os.path.join(UPLOAD_DIR, f))
                        except OSError:
                            pass
            # 清理孤儿文件（目录中未被任何记录引用的文件）
            active = {r[0] for r in conn.execute("SELECT task_id FROM prediction_uploads").fetchall()}
            removed = 0
            for f in os.listdir(UPLOAD_DIR):
                fname = os.path.basename(f)
                tid_part = fname.split(".")[0][:8]
                if len(tid_part) == 8 and tid_part not in active:
                    try:
                        os.remove(os.path.join(UPLOAD_DIR, f))
                        removed += 1
                    except OSError:
                        pass
            if expired or removed:
                logger.info("[cleanup] 过期记录 %d 条，孤儿文件 %d 个", len(expired), removed)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[cleanup] 上传文件清理失败: %s", e)


# 全局单例
DB_PATH = os.path.join(ROOT, 'data', 'cost_prediction.duckdb')
MODELS_CACHE_DIR = os.path.join(ROOT, "models_cache")
data_loader = DataLoader(data_dir=DATA_DIR)
model_factory = RealModelFactory(models_dir=MODELS_CACHE_DIR)
model_config_mgr = ModelConfigManager()
cost_agent = CostAgentManager(model_factory, data_loader, model_config_mgr)

# 启动时自动加载已有的训练数据（避免重复加载）
_existing_sources = {h.get('source_file') for h in data_loader.history}

_real_path = os.path.join(DATA_DIR, "real_training_data.xlsx")
if os.path.exists(_real_path) and "real_training_data.xlsx" not in _existing_sources:
    try:
        with open(_real_path, "rb") as _f:
            data_loader.import_from_excel(_f.read(), "real_training_data.xlsx")
    except Exception:
        pass

_sample_path = os.path.join(DATA_DIR, "sample_training_data.xlsx")
if os.path.exists(_sample_path) and "sample_training_data.xlsx" not in _existing_sources:
    try:
        with open(_sample_path, "rb") as _f:
            data_loader.import_from_excel(_f.read(), "sample_training_data.xlsx")
    except Exception:
        pass

# 内存会话存储（带 JSON 持久化）
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")

# 上限控制（防无界增长）
MAX_SESSIONS = 200      # 最多保留会话数
MAX_PROJECTS = 500      # 最多保留预测项目数
MAX_MESSAGES_PER_SESSION = 200  # 单会话最多消息数


def _prune_sessions():
    """会话上限治理：清理空会话并裁剪最旧会话，避免 sessions.json 无界增长。"""
    with _sessions_lock:
        # 清理空会话
        empty_ids = [sid for sid, msgs in SESSIONS.items() if not msgs]
        for sid in empty_ids:
            del SESSIONS[sid]
        # 裁剪消息数（保留每会话最近 MAX_MESSAGES_PER_SESSION 条）
        for sid, msgs in SESSIONS.items():
            if len(msgs) > MAX_MESSAGES_PER_SESSION:
                SESSIONS[sid] = msgs[-MAX_MESSAGES_PER_SESSION:]
        # 会话数量超限：按创建先后裁剪最旧会话
        if len(SESSIONS) > MAX_SESSIONS:
            excess = len(SESSIONS) - MAX_SESSIONS
            for sid in list(SESSIONS.keys())[:excess]:
                del SESSIONS[sid]


def _prune_projects():
    """项目记录上限治理：超出 MAX_PROJECTS 时删除最旧记录。"""
    with _projects_lock:
        if len(PROJECTS) > MAX_PROJECTS:
            excess = len(PROJECTS) - MAX_PROJECTS
            for pid in list(PROJECTS.keys())[:excess]:
                del PROJECTS[pid]


def _load_sessions() -> Dict[str, List[Dict]]:
    """从 JSON 文件加载会话"""
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("加载 sessions.json 失败: %s", e)
    return {}


def _save_sessions():
    """将会话保存到 JSON 文件（线程安全）"""
    with _sessions_lock:
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(SESSIONS, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存 sessions.json 失败: %s", e)


def _load_projects() -> Dict[str, Dict]:
    """从 JSON 文件加载项目"""
    try:
        if os.path.exists(PROJECTS_FILE):
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("加载 projects.json 失败: %s", e)
    return {}


def _save_projects():
    """将项目保存到 JSON 文件（线程安全）"""
    with _projects_lock:
        try:
            with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
                json.dump(PROJECTS, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存 projects.json 失败: %s", e)


SESSIONS: Dict[str, List[Dict]] = _load_sessions()
PROJECTS: Dict[str, Dict] = _load_projects()

# 线程安全锁：多线程并发修改/持久化 SESSIONS、PROJECTS 时防止竞态
_sessions_lock = threading.RLock()
_projects_lock = threading.RLock()


# ==================== Pydantic 模型 ====================
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: str = Field("default", max_length=100)


class ProjectRequest(BaseModel):
    project_name: str = Field("", max_length=200)
    project_type: str = Field("住宅", max_length=50)
    structure_type: str = Field("框架结构", max_length=50)
    total_area: float = Field(10000, gt=0, le=10_000_000, description="总建筑面积(m²)，必须大于 0")
    floors: int = Field(10, ge=1, le=500, description="楼层数")
    location: str = Field("华东", max_length=50)
    build_year: int = Field(2026, ge=1900, le=2100, description="建造年份")
    decoration_level: str = Field("普通装修", max_length=50)
    stage: str = Field("estimation", max_length=20)
    selected_models: Optional[List[str]] = Field(None, max_length=20)
    basement_area: float = Field(0, ge=0, le=10_000_000)
    building_height: float = Field(0, ge=0, le=2000, description="建筑高度(m)")
    # Step3 extension parameters (all optional)
    foundation_type: str = Field("", max_length=100)
    seismic_grade: str = Field("", max_length=100)
    concrete_grade: str = Field("", max_length=100)
    steel_grade: str = Field("", max_length=100)
    soil_condition: str = Field("", max_length=100)
    special_equipment: str = Field("", max_length=100)
    hvac: str = Field("", max_length=100)
    elevator: str = Field("", max_length=100)
    fire_system: str = Field("", max_length=100)
    smart_building: str = Field("", max_length=100)
    exterior_wall: str = Field("", max_length=100)
    roof_type: str = Field("", max_length=100)
    window_type: str = Field("", max_length=100)
    duration: int = Field(0, ge=0, le=3600, description="工期(天)")
    parking_ratio: float = Field(0, ge=0, le=100)
    green_rating: str = Field("", max_length=100)
    elevator_count: int = Field(0, ge=0, le=200)
    parking_count: int = Field(0, ge=0, le=1_000_000)


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
    # Merge static registry with actual trained model data
    trained = {m["id"]: m for m in model_factory.list_models()}
    result = []
    for entry in MODELS_REGISTRY:
        mid = entry.get("id", "")
        merged = dict(entry)
        if mid in trained:
            t = trained[mid]
            merged["accuracy"] = t.get("accuracy", entry.get("accuracy", 0))
            merged["is_trained"] = t.get("is_trained", False)
            merged["train_samples"] = t.get("train_samples", 0)
            merged["trained_at"] = t.get("trained_at", "")
        result.append(merged)
    return result


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


@app.get("/api/param-categories")
async def get_param_categories_api(stage: str = "estimation"):
    """获取指定阶段的参数分类"""
    return get_param_categories(stage)


@app.post("/api/predict")
def predict_project(req: ProjectRequest):
    """使用真实训练的三层模型进行造价预测

    使用同步 def：FastAPI 自动将其放入线程池执行，
    避免 sklearn 预测阻塞事件循环（高并发下健康检查等轻量请求不受影响）。
    """
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
        # Step3 extension params
        "foundation_type": req.foundation_type,
        "seismic_grade": req.seismic_grade,
        "concrete_grade": req.concrete_grade,
        "steel_grade": req.steel_grade,
        "soil_condition": req.soil_condition,
        "special_equipment": req.special_equipment,
        "hvac": req.hvac,
        "elevator": req.elevator,
        "fire_system": req.fire_system,
        "smart_building": req.smart_building,
        "exterior_wall": req.exterior_wall,
        "roof_type": req.roof_type,
        "window_type": req.window_type,
        "duration": req.duration,
        "parking_ratio": req.parking_ratio,
        "green_rating": req.green_rating,
        "elevator_count": req.elevator_count,
        "parking_count": req.parking_count,
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
                "boq_xgb", "boq_lr_v2"
            ]

    # 优先用已训练模型，未训练的也加入（会用基准价兜底）
    all_models = model_factory.list_models()
    trained_ids = {m["id"] for m in all_models if m.get("is_trained")}
    selected = [mid for mid in req.selected_models if mid in trained_ids] or req.selected_models

    result = predict_with_real_models(model_factory, project, selected, data_loader=data_loader)
    result["stage"] = req.stage
    result["stage_info"] = COST_STAGES.get(req.stage, {})
    result["predicted_at"] = datetime.now().isoformat()

    # 存储项目（上限治理：超出 MAX_PROJECTS 时裁剪最旧）
    project_id = f"PRJ{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100, 999)}"
    with _projects_lock:
        PROJECTS[project_id] = {
            "id": project_id,
            "input": req.model_dump(),
            "result": result,
            "created_at": datetime.now().isoformat()
        }
        _prune_projects()
        _save_projects()
    result["project_id"] = project_id

    return result


@app.post("/api/chat")
def chat_with_agent(req: ChatRequest):
    """与 ReAct 智能体对话（真实 AgentScope 优先，回退 MockLLM）

    同步 def：对话推理在独立线程的事件循环中运行，不阻塞主事件循环。
    """
    with _sessions_lock:
        if req.session_id not in SESSIONS:
            SESSIONS[req.session_id] = []
        history = SESSIONS[req.session_id]

    # 在线程中创建独立事件循环运行 agent（兼容真实 AgentScope 的 async 接口）
    result = asyncio.run(cost_agent.chat(req.message, history, req.session_id))

    # 更新会话历史（线程安全）
    with _sessions_lock:
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": result["reply"]})
        _prune_sessions()
        _save_sessions()

    return {
        "session_id": req.session_id,
        "reply": result["reply"],
        "react_steps": result["react_steps"],
        "tool_result": result.get("tool_result"),
        "backend": result.get("backend", "unknown"),
        "history_count": len(history)
    }


def _is_parse_failed(parse_result) -> bool:
    """判断文档解析是否完全失败（损坏/空文件）。

    判定条件：未提取到任何文本或表格，且存在致命警告
    （文件无法打开、解析过程出错等）。
    """
    if not parse_result:
        return True
    if parse_result.full_text or parse_result.tables:
        return False
    fatal_keywords = ("无法打开", "Cannot open", "解析失败", "出错", "failed", "empty file")
    return any(
        any(kw in w for kw in fatal_keywords)
        for w in getattr(parse_result, "warnings", [])
    )


@app.post("/api/chat/upload")
def chat_upload_file(file: UploadFile = File(...), session_id: str = "default"):
    """对话模式文件上传：解析文件 → 提取特征 → LLM 智能分析

    返回文件解析结果 + LLM 对文件内容的分析建议
    同步 def：解析与推理在线程池中执行，不阻塞事件循环。
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的格式: {ext}，支持: {ALLOWED_EXTENSIONS}")

    content = file.file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"文件过大，限制: {MAX_UPLOAD_SIZE // 1024 // 1024}MB")

    task_id = str(uuid.uuid4())[:8]
    temp_path = os.path.join(UPLOAD_DIR, _safe_upload_filename(task_id, file.filename))

    with open(temp_path, 'wb') as f:
        f.write(content)

    try:
        # 1. 解析文档
        parser = DocumentParser()
        result = parser.parse(temp_path)

        # 2. 解析失败（损坏/空文件）：明确返回 4xx，不落库、不调用 LLM
        if _is_parse_failed(result):
            raise HTTPException(400, f"文件无法解析（可能已损坏或为空）: {'；'.join(result.warnings)}")

        # 3. 提取特征
        extractor = FeatureExtractor()
        features = extractor.extract(result)

        # 4. 构造 LLM 分析上下文
        file_context = _build_file_context_for_agent(file.filename, result, features)

        # 5. 调用 agent 分析文件内容
        analysis_prompt = (
            f"用户上传了一份项目文件「{file.filename}」，我已解析并提取了以下关键信息：\n\n"
            f"{file_context}\n\n"
            f"请基于这些信息：\n"
            f"1. 总结项目的关键特征\n"
            f"2. 指出哪些信息已成功提取、哪些仍缺失需要用户补充\n"
            f"3. 给出初步的造价预测建议（可调用 predict_cost 工具）\n"
            f"4. 如果信息不足以预测，明确告诉用户还需要哪些参数"
        )

        with _sessions_lock:
            if session_id not in SESSIONS:
                SESSIONS[session_id] = []
            history = SESSIONS[session_id]
        agent_result = asyncio.run(cost_agent.chat(analysis_prompt, history, session_id))

        # 更新会话历史（线程安全）
        with _sessions_lock:
            history.append({"role": "user", "content": f"📎 上传文件: {file.filename}"})
            history.append({"role": "assistant", "content": agent_result["reply"]})
            _prune_sessions()
            _save_sessions()

        return {
            "task_id": task_id,
            "session_id": session_id,
            "filename": file.filename,
            "format": result.file_format,
            "is_scanned": result.is_scanned,
            "pages": result.pages,
            "features": features.to_dict(),
            "completeness": features.completeness(),
            "confidence": features.confidence,
            "warnings": result.warnings,
            "reply": agent_result["reply"],
            "react_steps": agent_result.get("react_steps", []),
            "tool_result": agent_result.get("tool_result"),
            "backend": agent_result.get("backend", "unknown"),
            "message": "文件解析完成，AI 已分析项目信息并给出预测建议。"
        }

    except HTTPException:
        # 业务校验错误：清理临时文件后原样抛出
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    except Exception as e:
        logger.exception("文件解析失败: %s", file.filename)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(500, f"解析失败: {str(e)}")


def _build_file_context_for_agent(filename: str, parse_result, features) -> str:
    """构造供 LLM 分析的文件上下文摘要"""
    lines = [f"📁 文件: {filename}"]
    lines.append(f"📄 格式: {parse_result.file_format} | 页数: {parse_result.pages} | "
                 f"扫描件: {'是' if parse_result.is_scanned else '否'}")

    if features.project_name:
        lines.append(f"📝 项目名称: {features.project_name}")
    if features.building_type:
        lines.append(f"🏢 建筑类型: {features.building_type}")
    if features.structure_type:
        lines.append(f"🏗️ 结构类型: {features.structure_type}")
    if features.total_area:
        lines.append(f"📐 总建筑面积: {features.total_area:,.0f} ㎡")
    if features.floor_count:
        lines.append(f"🏗️ 楼层数: {features.floor_count}")
        if features.above_ground_floors or features.under_ground_floors:
            ag = features.above_ground_floors or '?'
            ug = features.under_ground_floors or '?'
            lines.append(f"   (地上 {ag} 层, 地下 {ug} 层)")
    if features.location:
        lines.append(f"📍 所在地区: {features.location}")
    if features.build_year:
        lines.append(f"📅 建造年份: {features.build_year}")
    if features.decoration_standard:
        lines.append(f"🎨 装修标准: {features.decoration_standard}")
    if features.total_cost:
        lines.append(f"💰 项目总造价: {features.total_cost:,.2f} 元")
    if features.unit_price:
        lines.append(f"💵 单方造价: {features.unit_price:,.2f} 元/㎡")

    lines.append(f"\n📊 特征完整度: {features.completeness():.0%}")

    # 添加文本摘要（前 500 字符）
    if parse_result.full_text:
        text_preview = parse_result.full_text[:500].replace('\n', ' ')
        lines.append(f"\n📄 文档摘要: {text_preview}...")

    if parse_result.warnings:
        lines.append(f"\n⚠️ 解析警告: {'; '.join(parse_result.warnings)}")

    return '\n'.join(lines)


@app.get("/api/chat/sessions")
def list_sessions():
    """列出所有会话（返回前清理空会话与超限会话）"""
    _prune_sessions()
    with _sessions_lock:
        _items = list(SESSIONS.items())
    sessions = []
    for sid, msgs in _items:
        title = msgs[0]["content"][:30] if msgs else "空会话"
        sessions.append({
            "id": sid,
            "title": title,
            "message_count": len(msgs),
            "updated_at": datetime.now().isoformat()
        })
    return sessions


@app.delete("/api/chat/sessions/{session_id}")
def delete_session(session_id: str):
    with _sessions_lock:
        if session_id in SESSIONS:
            del SESSIONS[session_id]
            _prune_sessions()
            _save_sessions()
    return {"success": True}


@app.delete("/api/chat/sessions")
def delete_all_sessions():
    """删除所有会话"""
    with _sessions_lock:
        count = len(SESSIONS)
        SESSIONS.clear()
        _save_sessions()
    return {"success": True, "deleted_count": count}


@app.delete("/api/models/cache")
async def clear_model_cache():
    """清除本地模型缓存文件"""
    import glob
    deleted = []
    if os.path.isdir(MODELS_CACHE_DIR):
        for f in glob.glob(os.path.join(MODELS_CACHE_DIR, "*.joblib")):
            try:
                os.remove(f)
                deleted.append(os.path.basename(f))
            except Exception as e:
                logger.warning("Failed to delete %s: %s", f, e)
    # 重置模型工厂状态
    model_factory._models = {}
    return {"success": True, "deleted_count": len(deleted), "deleted_files": deleted}


@app.post("/api/data/import")
def import_data(file: UploadFile = File(...)):
    """导入 Excel 训练数据（同步 def，解析在线程池执行）"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 Excel 文件 (.xlsx, .xls)")

    content = file.file.read()
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


@app.get("/api/data/sufficiency")
def get_data_sufficiency():
    """数据充分性评估（DataFrame 处理较重，走线程池）"""
    from data_sufficiency import DataSufficiencyChecker
    from dataclasses import asdict
    df = data_loader.to_dataframe()
    if df is None or len(df) == 0:
        return {"sufficient": False, "score": 0, "issues": ["无任何训练数据"], "recommendations": ["请先导入Excel数据"]}
    checker = DataSufficiencyChecker()
    report = checker.assess(df)
    return asdict(report)


@app.post("/api/data/generate-sample")
def generate_sample(n: int = 80):
    """生成示例训练数据（8 种建筑类型均衡覆盖）并自动导入"""
    n = min(max(n, 8), 1000)  # 限制单次生成量
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
    with _projects_lock:
        return list(PROJECTS.values())


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    with _projects_lock:
        if project_id not in PROJECTS:
            raise HTTPException(404, "项目不存在")
        return PROJECTS[project_id]


# ==================== 模型训练 API ====================
@app.post("/api/train")
def train_all_models():
    """训练所有三层模型（使用已加载的历史数据 + DuckDB BOQ清单项数据）

    同步 def：重 CPU 训练在线程池中执行。
    """
    df = data_loader.to_dataframe()
    if df is None or len(df) == 0:
        raise HTTPException(400, "无训练数据，请先导入 Excel 或生成示例数据")

    # 加载BOQ清单项数据用于L3模型
    boq_df = data_loader.load_boq_items_from_duckdb()
    boq_info = f"{len(boq_df)} 条BOQ清单项" if boq_df is not None and len(boq_df) > 0 else "无BOQ数据"

    results = model_factory.train_all(df, boq_df=boq_df)
    trained = sum(1 for r in results.values() if r.get("success"))

    # 删除旧模型文件
    for old_file in ["boq_apriori.joblib", "boq_lr.joblib"]:
        old_path = os.path.join(MODELS_CACHE_DIR, old_file)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
                logger.info("[train] 删除旧模型文件: %s", old_file)
            except Exception as e:
                logger.warning("[train] 删除旧模型文件失败 %s: %s", old_file, e)

    return {
        "success": True,
        "total": len(results),
        "trained": trained,
        "failed": len(results) - trained,
        "sample_count": len(df),
        "boq_sample_count": len(boq_df) if boq_df is not None else 0,
        "boq_info": boq_info,
        "results": results,
        "backend": "scikit-learn"
    }


@app.post("/api/train/{model_id}")
def train_one_model(model_id: str):
    """训练单个模型（同步 def，重 CPU 训练在线程池执行）"""
    df = data_loader.to_dataframe()
    if df is None or len(df) == 0:
        raise HTTPException(400, "无训练数据")
    # BOQ模型需要清单项数据
    boq_df = None
    if model_id in RealModelFactory.BOQ_MODEL_IDS:
        boq_df = data_loader.load_boq_items_from_duckdb()
        if boq_df is None or len(boq_df) == 0:
            raise HTTPException(400, "BOQ模型需要DuckDB中的清单项数据")
    result = model_factory.train_one(model_id, df, boq_df=boq_df)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "训练失败"))
    return result


@app.get("/api/confidence/preview")
async def confidence_preview(
    request: Request,
):
    """实时置信度预览 — 用户填写 Step3 表单时调用"""
    from confidence import get_engine

    params = {k: v for k, v in request.query_params.items() if v and k != "model_ids"}
    engine = get_engine()

    models_status = model_factory.list_models()
    base_accs = {m["id"]: m.get("accuracy", 0) for m in models_status}

    model_id_str = request.query_params.get("model_ids", "subsection_xgb,section_xgb,item_xgb")
    model_ids = [m.strip() for m in model_id_str.split(",") if m.strip()]

    preview = engine.get_preview(model_ids, params, base_accs)
    return {"models": preview}


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


# ==================== 预测文件上传 API（数据隔离） ====================

@app.post("/api/predict/upload")
def upload_for_prediction(file: UploadFile = File(...)):
    """上传文件用于预测（严格隔离，不写入训练数据库）

    同步 def：文档解析在线程池中执行，不阻塞事件循环。
    保存文件名使用 task_id + 白名单扩展名，杜绝路径穿越。
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的格式: {ext}，支持: {ALLOWED_EXTENSIONS}")

    content = file.file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"文件过大，限制: {MAX_UPLOAD_SIZE // 1024 // 1024}MB")

    task_id = str(uuid.uuid4())[:8]
    temp_path = os.path.join(UPLOAD_DIR, _safe_upload_filename(task_id, file.filename))

    with open(temp_path, 'wb') as f:
        f.write(content)

    try:
        parser = DocumentParser()
        result = parser.parse(temp_path)

        # 解析失败（损坏/空文件）：明确返回 4xx，不落库
        if _is_parse_failed(result):
            raise HTTPException(400, f"文件无法解析（可能已损坏或为空）: {'；'.join(result.warnings)}")

        extractor = FeatureExtractor()
        features = extractor.extract(result)

        import duckdb
        conn = duckdb.connect(DB_PATH)
        conn.execute(
            "INSERT INTO prediction_uploads (task_id, filename, file_format, extracted_features, expires_at) VALUES (?, ?, ?, ?, ?)",
            [task_id, file.filename, result.file_format,
             json.dumps(features.to_dict(), ensure_ascii=False),
             (datetime.now() + timedelta(hours=UPLOAD_TTL_HOURS)).isoformat()]
        )
        conn.close()

        return {
            "task_id": task_id,
            "filename": file.filename,
            "format": result.file_format,
            "is_scanned": result.is_scanned,
            "pages": result.pages,
            "features": features.to_dict(),
            "completeness": features.completeness(),
            "confidence": features.confidence,
            "warnings": result.warnings,
            "message": "文件解析完成，特征已提取。此数据仅用于本次预测，不会纳入训练数据库。"
        }
    except HTTPException:
        # 业务校验错误：清理临时文件后原样抛出
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    except Exception as e:
        logger.exception("上传文件解析失败: %s", file.filename)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(500, f"解析失败: {str(e)}")


@app.get("/api/predict/upload/{task_id}/result")
async def get_upload_result(task_id: str):
    """获取上传文件的解析结果"""
    import duckdb
    conn = duckdb.connect(DB_PATH, read_only=True)
    row = conn.execute(
        "SELECT task_id, filename, file_format, uploaded_at, extracted_features, expires_at FROM prediction_uploads WHERE task_id = ?",
        [task_id]
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "未找到该上传记录")

    return {
        "task_id": row[0],
        "filename": row[1],
        "format": row[2],
        "uploaded_at": str(row[3]),
        "features": json.loads(row[4]) if row[4] else {},
        "expires_at": str(row[5]),
    }


@app.delete("/api/predict/upload/{task_id}")
async def delete_upload(task_id: str):
    """删除上传记录及临时文件"""
    import duckdb
    conn = duckdb.connect(DB_PATH)
    conn.execute("DELETE FROM prediction_uploads WHERE task_id = ?", [task_id])
    conn.close()

    for f in os.listdir(UPLOAD_DIR):
        if f.startswith(task_id):
            try:
                os.remove(os.path.join(UPLOAD_DIR, f))
            except Exception:
                pass

    return {"deleted": task_id}


@app.post("/api/predict/upload/cleanup")
def cleanup_expired_uploads():
    """清理过期的上传记录（UPLOAD_TTL_HOURS 小时）及孤儿文件"""
    _cleanup_expired_uploads()
    return {"cleaned": True}


# ==================== 静态资源 ====================
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 启动时清理一次过期上传（避免历史残留累积）
try:
    _cleanup_expired_uploads()
except Exception:
    pass


if __name__ == "__main__":
    import uvicorn
    print("🚀 启动 AI 造价预测系统...")
    print(f"   数据目录: {DATA_DIR}")
    print(f"   前端目录: {FRONTEND_DIR}")

    # H2: localhost 在部分系统上优先解析为 IPv6(::1)，而服务仅监听 IPv4，
    # 会导致新连接约 2 秒超时回退。主动检测并提示使用 127.0.0.1。
    try:
        infos = socket.getaddrinfo("localhost", 8000)
        ipv6_first = any(i[0] == socket.AF_INET6 for i in infos)
        if ipv6_first:
            print("⚠️  检测到 localhost 优先解析为 IPv6(::1)，而服务仅监听 IPv4。")
            print("   建议通过 http://127.0.0.1:8000 访问，避免每次连接 2 秒超时回退。")
    except Exception:
        pass

    # H1: 多进程部署支持（可选）。
    # 通过环境变量 UVICORN_WORKERS 控制 worker 数（默认 1）。
    # 注意：多 worker 时 SESSIONS/PROJECTS 为各进程独立内存副本，
    # JSON 持久化由各进程各自写入；若需共享一致状态，请配合外部存储（Redis/DB）。
    _workers = int(os.environ.get("UVICORN_WORKERS", "1") or "1")
    _workers = max(1, min(_workers, 8))  # 限制在 1-8 之间
    if _workers > 1:
        print(f"⚙️  已启用多进程模式：{_workers} workers（会话/项目状态为各进程独立副本）")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", workers=_workers)
