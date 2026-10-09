---
name: modelscope-studio-deploy
description: 部署应用到魔搭创空间(ModelScope Studio)。当用户需要部署项目到魔搭创空间、生成 ms_deploy.json 配置文件、或询问魔搭创空间部署相关问题时使用此 skill。触发词包括：魔搭创空间、ModelScope Studio、ms_deploy.json、创空间部署。
metadata:
  author: cursor-skill
  version: "1.0.0"
  tags: modelscope, deployment, cloud, china
---

# 魔搭创空间部署指南

部署应用到魔搭创空间(ModelScope Studio)的完整指南。支持 Gradio、Streamlit、Docker 和静态网站四种部署类型。

## 适用场景

- 用户请求部署项目到魔搭创空间
- 用户需要生成 `ms_deploy.json` 配置文件
- 用户需要了解魔搭创空间部署要求
- 用户部署失败需要排查问题

## 快速开始

### 部署工作流程

```
1. 分析项目结构 → 2. 确定部署类型 → 3. 生成配置文件 → 4. 上传部署
```

### 步骤 1：分析项目结构

阅读项目代码，确定：
- 项目使用的框架（Gradio/Streamlit/纯前端/Docker）
- 依赖文件（requirements.txt、package.json 等）
- 入口文件（app.py、main.py、index.html 等）
- 是否需要 GPU 资源

### 步骤 2：选择部署类型

| 项目类型 | sdk_type | 适用场景 |
|---------|----------|---------|
| Gradio | `gradio` | Gradio 应用，最常见 |
| Streamlit | `streamlit` | Streamlit 应用 |
| Docker | `docker` | 自定义环境、前后端分离 |
| Static | `static` | 纯静态 HTML/CSS/JS |

### 步骤 3：生成 ms_deploy.json

在项目根目录创建 `ms_deploy.json` 文件：

**Gradio 类型（最常用）：**
```json
{
  "$schema": "https://modelscope.cn/api/v1/studios/deploy_schema.json",
  "sdk_type": "gradio",
  "sdk_version": "5.29.0",
  "base_image": "ubuntu22.04-py311-torch2.3.1-modelscope1.31.0",
  "resource_configuration": "platform/2v-cpu-16g-mem"
}
```

**Docker 类型：**
```json
{
  "$schema": "https://modelscope.cn/api/v1/studios/deploy_schema.json",
  "sdk_type": "docker",
  "resource_configuration": "platform/2v-cpu-16g-mem",
  "port": 7860
}
```

**Static 类型：**
```json
{
  "$schema": "https://modelscope.cn/api/v1/studios/deploy_schema.json",
  "sdk_type": "static",
  "resource_configuration": "platform/2v-cpu-16g-mem"
}
```

### 步骤 4：上传部署

1. 前往 [创空间列表页](https://modelscope.cn/studios) → 创建创空间 → 编程式创空间
2. 切换到"快速部署并创建"模式
3. 填写基础信息（名称、描述等）
4. 上传项目文件夹
5. 点击"确认创建并部署"

## 关键配置字段

| 字段 | 说明 | 必填 |
|-----|------|-----|
| `sdk_type` | 部署类型：gradio/streamlit/docker/static | ✅ |
| `sdk_version` | SDK版本，仅 gradio 类型需要 | gradio必填 |
| `base_image` | 基础镜像，gradio/streamlit 类型需要 | gradio/streamlit必填 |
| `resource_configuration` | 云资源配置 | ✅ |
| `port` | 服务端口，docker 类型必须为 7860 | docker必填 |
| `environment_variables` | 环境变量列表 | 可选 |

## 资源配置选项

| 配置 | 说明 | 适用场景 |
|-----|------|---------|
| `platform/2v-cpu-16g-mem` | 2核CPU + 16G内存 | 轻量应用（免费） |
| `xgpu/8v-cpu-32g-mem-16g` | 8核CPU + 32G内存 + 16G显存 | 需要GPU |
| `xgpu/8v-cpu-64g-mem-48g` | 8核CPU + 64G内存 + 48G显存 | 大模型 |

> **注意**：xGPU 资源需要先申请加入「xGPU乐园」组织

## Docker 部署注意事项

Docker 类型部署时，需要：

1. **端口必须为 7860**：魔搭创空间要求服务监听在 7860 端口
2. **创建 Dockerfile**：在项目根目录创建 Dockerfile
3. **前后端合并**：如果是前后端分离项目，需要合并到一个容器中

Docker 部署示例 Dockerfile：
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["python", "app.py"]
```

## 更多资源

- 详细配置说明：[schema.md](schema.md)
- 部署示例：[examples.md](examples.md)
- 问题排查：[troubleshooting.md](troubleshooting.md)

## AI 辅助部署提示词模板

向 AI 发送以下提示词来生成部署配置：

```
现在我需要在生产环境部署这个项目，目标环境是魔搭创空间。请完整阅读整个项目，并根据魔搭创空间部署要求，帮我制定部署方案，并生成 ms_deploy.json 及其他必要的部署配置文件。

注意事项：
- 当前项目已经能在本地运行，请务必尽量不改动或少改动项目代码文件本身
- 如需选择 Docker 类型部署，请尽量直接从 Docker 官方拉取已经安装好必要依赖的 Docker 镜像文件
- 服务端口必须为 7860
```
