---
title: AI 建筑工程造价预测系统
emoji: 🏗️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
license: mit
---

# AI 建筑工程造价预测系统

基于三阶段预测流水线的智能工程造价预测系统：

1. **特征提取** — 从招标文件/工程量清单（BOQ）中解析项目特征
2. **指标预测** — 基于特征预测关键造价指标（单方造价、分部造价等）
3. **置信度评估** — 综合数据充分性与模型置信度，给出预测可信度区间

## 功能特性

- 支持 Excel/PDF 招标文件智能解析
- 支持多栋建筑组合体项目预测
- 基于 XGBoost/RandomForest/SVR 集成模型
- Canvas 可视化报告生成
- Docker 一键部署

## 技术栈

- **后端**: FastAPI + DuckDB + scikit-learn + XGBoost
- **前端**: 原生 HTML/CSS/JavaScript
- **OCR**: Tesseract (中文识别)
- **部署**: Docker

## 使用说明

1. 上传招标文件（Excel/PDF）
2. 系统自动提取项目特征
3. 选择预测模型并执行预测
4. 查看预测结果与置信度区间

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | 服务监听端口 | `7860` |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔） | `http://localhost:7860` |
| `UVICORN_WORKERS` | Uvicorn worker 进程数 | `1` |

## 项目仓库

GitHub: https://github.com/Fake-msn/cost-prediction-app
