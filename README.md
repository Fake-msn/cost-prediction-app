# AI 建筑造价预测系统

基于 **AgentScope SDK v2.0.5 + scikit-learn** 的建筑工程造价预测 ReAct 智能体应用。三层模型体系（8 个 ML 模型）覆盖估算→概算→预算三阶段，支持 8 种建筑类型的六层级成本分解。集成多格式文档解析（Word/PDF/Excel + OCR）、DuckDB 数据管线（30,490 条清单数据、138 个真实建设项目）、数据隔离机制、LLM 引导式交互（6 种意图识别）、模型泛化修复（特征泄漏修复、树模型 CV R² 36.7-86.9%）、数据充分性评估、预测透明度（置信区间+参考项目+数据来源），以及 Docker 容器化部署。

---

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | 原生 HTML/CSS/JS（无框架依赖） | 打开即用 |
| 后端 | FastAPI + uvicorn | 34 REST 端点 |
| 智能体 | AgentScope SDK v2.0.5（ReActAgent 模式） | 6 FunctionTools |
| ML 训练 | scikit-learn 1.9.0（SVR / GBT / XGBoost / RandomForest / LinearRegression） | 三层 8 模型体系 |
| 数据 | DuckDB 1.5.5（嵌入式）+ Pandas + openpyxl | 数据管线 + Excel 导入 |
| 文档解析 | pymupdf + python-docx + pdfplumber + pytesseract | Word/PDF/Excel + OCR |
| 模型持久化 | joblib | 模型缓存 |
| LLM 提供商 | DashScope / OpenAI / Anthropic / Gemini / Ollama / OpenAI兼容 | 6 提供商 |
| 部署 | Docker + docker-compose | 容器化部署，支持环境变量配置 |
| 数据提取 | pymupdf + python-docx + pdfplumber + pytesseract | 多格式文档解析（Word/PDF/Excel + OCR） |
| 数据充分性 | DataSufficiencyChecker | 5维评估，自动检测数据缺口 |

### 依赖组件与版本

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Python | >= 3.11 | 运行环境 |
| FastAPI | >= 0.140.0 | Web 框架 |
| scikit-learn | >= 1.4.0 | ML 模型训练 |
| pandas | >= 2.2.3 | 数据处理 |
| xgboost | >= 2.0.0 | 梯度提升模型 |
| agentscope | >= 2.0.5 | ReAct 智能体 SDK |
| pymupdf | >= 1.23.0 | PDF 解析 |
| pytesseract | >= 0.3.10 | OCR 文字识别 |
| duckdb | >= 0.10.0 | 嵌入式数据库 |

**系统级依赖：**

- **Tesseract OCR**：PDF 扫描件 OCR 功能需要
  - Ubuntu/Debian: `sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim`
  - macOS: `brew install tesseract tesseract-lang`
  - Windows: 下载安装 [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)

### 快速启动

**方式一：一键启动（推荐）**

```bash
# Windows
start.bat

# Linux / macOS
chmod +x start.sh && ./start.sh
```

自动完成：创建虚拟环境 → 激活 → 安装依赖 → 检测 Tesseract → 启动服务

**方式二：Docker**

```bash
docker-compose up -d
# 访问 http://localhost:8000
```

**方式三：手动启动**

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt
python backend/main.py
```

**首次使用：**
1. 浏览器打开 http://localhost:8000/app
2. 左侧边栏切换到「数据」标签 → 系统已预载 138 个真实建设项目数据 + 80 条模拟样本
3. 点击「训练所有模型」→ 8 个 sklearn 模型开始训练
4. 切换到「向导模式」或「对话模式」开始预测
5. （可选）点顶栏「⚙ LLM 配置」填入 API Key，启用真实智能体对话

---

## 快速开始

### 本地部署

```bash
# 1. 克隆仓库
git clone https://github.com/Fake-msn/cost-prediction-app.git
cd cost-prediction-app

# 2. 创建虚拟环境并安装依赖
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt

# 3. 启动服务
python backend/main.py

# 4. 浏览器打开
#    首页：http://localhost:8000/
#    应用：http://localhost:8000/app
```

### Docker 部署

```bash
docker-compose up -d
# 访问 http://localhost:8000
```

环境变量配置：
- `CORS_ORIGINS`：CORS 允许来源（逗号分隔，默认 `*`）
- `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` 等 LLM 密钥

首次启动后：
1. 左侧边栏切换到「数据」标签 → 系统已预载 138 个真实建设项目数据 + 80 条模拟样本
2. 点击「训练所有模型」→ 8 个 sklearn 模型开始训练
3. 切换到「向导模式」或「对话模式」开始预测

### 可选：配置真实 LLM

点顶栏「⚙ LLM 配置」，填入任一提供商的 API Key，对话将使用真实 AgentScope ReActAgent。

```bash
# 或通过环境变量配置
export DASHSCOPE_API_KEY="sk-xxxx"        # 阿里云通义千问
export OPENAI_API_KEY="sk-xxxx"           # OpenAI GPT
export ANTHROPIC_API_KEY="sk-ant-xxxx"    # Anthropic Claude
export GEMINI_API_KEY="xxxx"              # Google Gemini
# Ollama 本地模型无需 Key，自动检测 localhost:11434
```

未配置时自动回退到内置 MockLLM，保留完整 ReAct 推理链（思考→行动→观察→回答）。

---

## 项目架构

```
cost-prediction-app/
├── backend/
│   ├── main.py              # FastAPI 主服务，34 API 路由
│   ├── agent.py             # AgentScope ReAct 智能体管理器
│   ├── ml_models.py         # scikit-learn 三层模型训练管线
│   ├── models.py            # Pydantic 数据模型
│   ├── model_config.py      # 6 提供商 LLM 自定义配置
│   ├── data_loader.py       # Excel 导入 + 均衡样本生成
│   ├── data_sufficiency.py  # 数据充分性评估器
│   ├── document_parser.py   # 多格式文档解析（Word/PDF/Excel + OCR）
│   ├── feature_extractor.py # 特征提取与文档结构化
│   ├── terminology.py       # 建筑造价术语规范（五算标准）
│   ├── scripts/
│   │   ├── convert_template_data.py  # 模板数据提取脚本
│   │   ├── enrich_metadata.py        # 元数据富化
│   │   ├── extract_boq.py            # 清单提取
│   │   ├── init_duckdb.py            # DuckDB 初始化
│   │   ├── migrate_to_duckdb.py      # 数据迁移至 DuckDB
│   │   └── normalize_prices.py       # 价格归一化
│   └── requirements.txt     # Python 依赖清单
├── frontend/
│   ├── index.html           # 产品首页（Hero + 功能 + 流程）
│   ├── app.html             # 应用主界面（向导 + 对话 + 侧边栏）
│   └── static/
│       ├── css/             # main.css + landing.css + app.css
│       └── js/              # app.js + landing.js
├── data/
│   ├── cost_prediction.duckdb  # DuckDB 嵌入式数据库
│   ├── real_training_data.xlsx  # 138个真实项目训练数据
│   ├── sample_training_data.xlsx  # 80 条均衡训练样本
│   ├── projects.json            # 项目元数据
│   ├── sessions.json            # 会话记录
│   └── history.json             # 历史预测
├── models_cache/            # joblib 模型缓存（训练后生成，已 .gitignore）
├── model_config.json.example  # LLM 提供商配置示例
├── start.bat                # Windows 一键启动
├── start.sh                 # Linux/macOS 一键启动
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .gitignore
└── README.md
```

### 四层架构

```
┌─────────────────────────────────────────┐
│  FRONTEND  │ index.html / app.html      │
│            │ 5步向导 + 对话 + 侧边栏      │
├─────────────────────────────────────────┤
│  API       │ FastAPI main.py            │
│            │ 34 REST 端点                │
├────────────┬────────────────────────────┤
│  AGENT     │ agent.py (AgentScope)      │
│  (对话)    │ 6 FunctionTools            │
├────────────┼────────────────────────────┤
│  MODELS    │ ml_models.py (sklearn)     │
│  (训练)    │ 8 models × 3 layers        │
├────────────┼────────────────────────────┤
│  DOCUMENT  │ document_parser.py         │
│  PARSING   │ feature_extractor.py       │
│            │ Word/PDF/Excel + OCR       │
├────────────┴────────────────────────────┤
│  DATA      │ DuckDB + data/ + models_cache/ │
│  STORAGE   │ + model_config.json        │
└─────────────────────────────────────────┘
           ↕ 外部 LLM 服务（6 提供商）
```

---

## 三层模型体系

系统采用**多维度融合预测**架构：L1 层通过 PSO-SVR 与 GBT 双模型加权融合得到单方造价；L2 层分别用 XGBoost 预测专业占比、分部占比和材料单方耗量，实现造价结构的三维分解；L3 层提供指标体系（RF）和清单综合单价（XGBoost + LR 双模型），支持从宏观估算到微观清单的全链路预测。最终预测结果通过精度加权融合，高精度模型主导输出。

| 层级 | 模型 | 算法 | 目标 | CV R² |
|---|---|---|---|---|
| L1 总造价 | total_pso_svr | PSO-SVR | 单方造价 | 86.9% |
| L1 总造价 | unit_gbt | GBT | 单方造价 | 74.6% |
| L2 专业占比 | section_xgb | MultiOutput XGBoost | 建筑/装饰/安装占比 | 51.6% |
| L2 分部占比 | subsection_xgb | MultiOutput XGBoost | 基础/主体/屋面/外墙占比 | 36.7% |
| L2 材料耗量 | item_xgb | MultiOutput XGBoost | 混凝土/钢筋/砌块单方 | 39.4% |
| L3 指标体系 | indicator_rf | MultiOutput RF | 人工费/基础/主体占比 | 60.3% |
| L3 BOQ | boq_xgb | XGBoost | item级综合单价 | 73.7% |
| L3 BOQ | boq_lr_v2 | LinearRegression | item级综合单价 | 68.3% |

> 所有精度指标均为 RepeatedKFold 交叉验证 R²，反映真实泛化性能

### 模型泛化改进

- **根因修复**：移除输出型特征泄漏（人工费/措施费等不作为输入特征）
- **树模型仅用6核心输入特征**（4类别+2数值），one-hot后约12维
- **log1p目标变换**压缩目标范围
- **简化超参数**（max_depth=2, min_samples_leaf=10）防止过拟合
- **RepeatedKFold交叉验证**（适应小样本场景）

### 融合公式

```
fused_unit_price = Σ(pred_i × accuracy_i) / Σ(accuracy_i)   (accuracy ≥ 50%)
fused_total_cost = fused_unit_price × total_area
```

---

## 核心功能

### 多格式文档上传解析

- 支持 Word（.docx）、PDF、Excel（.xlsx/.xls）文件上传
- PDF 扫描件通过 OCR（pytesseract + pymupdf）提取文本
- 自动识别文档结构，提取造价相关字段
- 解析结果自动填充项目参数，减少手动输入

### 数据隔离机制

- 预测数据与训练数据完全隔离，上传文档不会污染训练集
- 独立的 prediction_uploads 表管理上传任务生命周期
- 任务完成后支持清理和删除

### LLM 引导式交互

- 对话模式支持 6 种意图识别：预测、数据查询、知识问答、数据充分性检查、模型状态、闲聊
- ReAct 智能体自然语言交互，实时展示推理链（思考→行动→观察→回答）
- 未配置 LLM API Key 时自动回退内置 MockLLM，保留完整推理链

### DuckDB 数据管线

- 嵌入式 DuckDB 数据库存储结构化数据
- 5 张数据表：project_meta（138 项目）、boq_items（30,490 清单）、price_index（17 条价格指数）等
- 数据迁移脚本支持从 Excel 迁移至 DuckDB
- 价格归一化、元数据富化等数据质量管线

### 三阶段造价预测

| 阶段 | 参数数 | 精度 | 误差率 | 适用场景 |
|---|---|---|---|---|
| 估算 | 7 | 70-80% | ±20% | 项目建议书/可行性研究 |
| 概算 | 32 | 80-90% | ±10% | 初步设计/投资控制基准 |
| 预算 | 35 | 95%+ | ±3% | 施工图设计/招投标 |

### 六层级成本分解

```
L1 项目总造价 → L2 单项工程 → L3 单位工程（土建55%/安装25%/装饰20%）
→ L4 分部工程（基础/主体/屋面/外墙...）→ L5 分项工程（混凝土/钢筋/砌体...）
→ L6 明细级别（工程量清单基本单元）
```

### 8 种建筑类型

学校 · 医院 · 办公楼 · 住宅 · 工业建筑 · 商业建筑 · 基础设施 · 公共建筑

每类约 10-17 条均衡训练样本，模型通过 one-hot 编码区分类型差异。

### 两条交互路径

- **向导模式**：5 步表单（项目信息→选择阶段→配置参数→模型选择→预测结果）
- **对话模式**：ReAct 智能体自然语言交互，实时展示推理链

### 数据工程

- 多格式文档解析：Word/PDF/Excel + OCR，自动提取造价字段
- 从 DuckDB 结构化数据中训练模型
- 项目数据A/B/C分类与置信度标记
- 差异化样本权重（A=1.0, B=0.7, C=0.5, 模拟=0.3）
- 衍生特征：费用比例、材料单方用量

### 数据充分性评估

- 5维检查：样本量、类型覆盖、地区覆盖、特征方差、模拟比例
- 对话模式 `check_data` 意图识别
- LLM工具 `search_supplementary_data`（权威数据源推荐）
- REST端点 `GET /api/data/sufficiency`

### 预测透明性

- 68%置信区间（基于CV残差统计）
- Top-3相似参考项目
- 数据来源展示（真实/模拟标记）
- 特征贡献度提取

---

## API 端点

### 预测与对话
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/predict` | 三层模型融合预测 |
| POST | `/api/predict/upload` | 文档上传解析预测 |
| GET | `/api/predict/upload/{task_id}/result` | 获取上传任务结果 |
| DELETE | `/api/predict/upload/{task_id}` | 删除上传任务 |
| POST | `/api/predict/upload/cleanup` | 清理过期上传任务 |
| POST | `/api/chat` | ReAct 智能体对话 |
| GET/DELETE | `/api/chat/sessions` | 会话管理 |
| DELETE | `/api/chat/sessions/{session_id}` | 删除指定会话 |

### 模型训练
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/train/status` | 训练状态 + AgentScope 状态 |
| POST | `/api/train` | 训练所有模型 |
| POST | `/api/train/{model_id}` | 训练指定模型 |
| GET | `/api/models` | 模型列表 |
| GET | `/api/models/all` | 全部模型详情 |
| DELETE | `/api/models/cache` | 清除模型缓存 |

### 数据管理
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/data/history` | 历史项目列表 |
| GET | `/api/data/statistics` | 训练数据统计 |
| GET | `/api/data/sufficiency` | 数据充分性评估 |
| POST | `/api/data/import` | 导入 Excel 数据 |
| POST | `/api/data/generate-sample` | 生成示例数据 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{project_id}` | 项目详情 |
| GET | `/api/stage/{stage}/params` | 阶段参数定义 |
| GET | `/api/health` | 健康检查 |

### LLM 配置
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/llm/providers` | 提供商列表 |
| GET/POST | `/api/llm/active` | 激活提供商 |
| POST | `/api/llm/config/{provider}` | 更新提供商配置 |

### 术语规范
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/terminology/stages` | 三阶段定义 |
| GET | `/api/terminology/hierarchy` | 六层级结构 |
| GET | `/api/terminology/project-types` | 建筑类型列表 |
| GET | `/api/terminology/structure-types` | 结构类型列表 |

---

## 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CORS_ORIGINS` | CORS允许来源（逗号分隔） | `*` |
| `DASHSCOPE_API_KEY` | 阿里云通义千问 API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | - |
| `GEMINI_API_KEY` | Google Gemini API Key | - |

---

## 设计原则

- **真实训练优先**：8 个模型全部使用 sklearn Pipeline 真实训练，非经验系数硬编码
- **低精度剔除**：训练中 R² < 50% 的模型自动排除融合，高精度模型主导预测
- **术语规范化**：建筑造价术语严格遵循《建设工程“五算”解析》（估算/概算/预算/结算/决算）
- **渐进式 LLM**：无 API Key 时回退 MockLLM，配置后自动切换真实 AgentScope
- **零前端依赖**：HTML/CSS/JS 原生实现，打开即用
- **特征泄漏零容忍**：树模型仅使用建造前已知的输入特征，造价构成分项不作为预测输入
- **数据分级加权**：A/B/C类数据差异化权重，降低低质量数据对模型的干扰
- **预测透明**：每次预测附带置信区间、参考项目和数据来源，结果可追溯
- **数据隔离**：上传解析数据与训练数据完全隔离，防止数据污染
- **文档驱动**：支持多格式文档上传解析，减少手动参数输入

---

## 术语参考

基于 [ahua.edu.cn《建设工程"五算"解析》](https://www.ahua.edu.cn/sjc/2025/0918/c834a42898/page.htm)：

- **估算**：项目建议书/可行性研究阶段，±20% 误差率
- **概算**：初步设计阶段，以设计图纸和概算定额为依据，±10% 误差率
- **预算**：施工图设计阶段，按《工程量清单计价规范》详细计算，±3% 误差率
- **结算**：施工单位与建设单位合同价款结算
- **决算**：项目竣工后实际花费的财务汇总

---

## License

MIT
