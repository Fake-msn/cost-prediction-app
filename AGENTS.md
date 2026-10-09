# AGENTS.md

## 项目概述

AI 建筑造价预测系统，基于三阶段预测流水线：
1. **特征提取** — 从上传的招标文件/工程量清单（BOQ）中解析项目特征
2. **指标预测** — 基于特征预测关键造价指标（如单方造价、分部造价等）
3. **置信度评估** — 综合数据充分性与模型置信度，给出预测可信度区间

## 模块边界

| 目录 | 职责 | 说明 |
|------|------|------|
| `backend/` | API 服务 + 模型推理 | FastAPI 应用，包含特征提取、ML 模型、数据加载等核心逻辑 |
| `frontend/` | 静态前端 | HTML/CSS/JS，通过 API 与后端交互 |
| `data/` | 持久化数据 | DuckDB 数据库 (`cost_prediction.duckdb`)、上传文件、训练数据 |
| `models_cache/` | 已训练的模型文件 | **只读**，存放 `.joblib` 模型及配置 |

## 关键约束

1. **路径安全** — 文件上传时，必须对 `filename` 做 `os.path.basename()` 清洗，防止路径穿越攻击
2. **数据库访问** — DuckDB 数据库文件 (`data/cost_prediction.duckdb`) **不可直接编辑**，所有读写须通过 `backend/data_loader.py` 进行
3. **临时/分析文件** — `_stress_test_tmp/` 目录和所有 `_analysis*.py` 文件为临时压测/分析用途，不应修改
4. **模型保护** — `models_cache/*.joblib` 为已训练模型，重新训练需明确授权

## 常用命令

```bash
# 一键启动（Windows）
start.bat

# 一键启动（Linux/Mac）
bash start.sh

# Docker 部署
docker-compose up
```
