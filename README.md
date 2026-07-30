# AI 建筑造价预测系统

基于 **AgentScope SDK v2.0.4 + scikit-learn** 的建筑工程造价预测 ReAct 智能体应用。三层模型体系覆盖估算→概算→预算三阶段，支持 8 种建筑类型的六层级成本分解。集成数据工程能力（7种造价表解析、47个真实建设项目），模型泛化修复（特征泄漏修复、树模型CV R² 63-91%），数据充分性评估、预测透明度（置信区间+参考项目+数据来源），以及 Docker 容器化部署。

---

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | 原生 HTML/CSS/JS（无框架依赖） | 打开即用 |
| 后端 | FastAPI + uvicorn | 30 REST 端点 |
| 智能体 | AgentScope SDK v2.0.4（ReActAgent 模式） | 6 FunctionTools |
| ML 训练 | scikit-learn（SVR / GBT / XGBoost / RandomForest / LinearRegression） | 三层模型体系 |
| 数据 | Pandas + openpyxl（Excel 导入/导出） | 训练数据管理 |
| 模型持久化 | joblib | 模型缓存 |
| LLM 提供商 | DashScope / OpenAI / Anthropic / Gemini / Ollama / OpenAI兼容 | 6 提供商 |
| 部署 | Docker + docker-compose | 容器化部署，支持环境变量配置 |
| 数据充分性 | DataSufficiencyChecker | 5维评估，自动检测数据缺口 |
| 数据提取 | openpyxl + 自定义脚本 | 7种造价表解析（表-02/03/04/08/11/13/21）|

### 依赖组件与版本

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Python | >= 3.11 | 运行环境 |
| FastAPI | >= 0.140.0 | Web 框架 |
| scikit-learn | >= 1.4.0 | ML 模型训练 |
| pandas | >= 2.2.3 | 数据处理 |
| xgboost | >= 2.0.0 | 梯度提升模型 |
| agentscope | >= 2.0.4 | ReAct 智能体 SDK |
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
2. 左侧边栏切换到「数据」标签 → 系统已预载 47 个真实建设项目数据 + 80 条模拟样本
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
1. 左侧边栏切换到「数据」标签 → 系统已预载 47 个真实建设项目数据 + 80 条模拟样本
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
│   ├── main.py              # FastAPI 主服务，30 API 路由
│   ├── agent.py             # AgentScope ReAct 智能体管理器
│   ├── ml_models.py         # scikit-learn 三层模型训练管线
│   ├── model_config.py      # 6 提供商 LLM 自定义配置
│   ├── data_loader.py       # Excel 导入 + 均衡样本生成
│   ├── data_sufficiency.py  # 数据充分性评估器
│   ├── terminology.py       # 建筑造价术语规范（五算标准）
│   ├── scripts/
│   │   └── convert_template_data.py  # 模板数据提取脚本
│   └── requirements.txt     # Python 依赖清单
├── frontend/
│   ├── index.html           # 产品首页（Hero + 功能 + 流程）
│   ├── app.html             # 应用主界面（向导 + 对话 + 侧边栏）
│   └── static/
│       ├── css/             # main.css + landing.css + app.css
│       └── js/              # app.js（1,200+ 行交互逻辑）
├── data/
│   ├── real_training_data.xlsx  # 47个真实项目训练数据
│   └── sample_training_data.xlsx  # 80 条均衡训练样本
├── models_cache/            # joblib 模型缓存（训练后生成，已 .gitignore）
├── model_config.json        # LLM 提供商持久化配置
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
│            │ 30 REST 端点                │
├────────────┬────────────────────────────┤
│  AGENT     │ agent.py (AgentScope)      │
│  (对话)    │ 6 FunctionTools            │
├────────────┼────────────────────────────┤
│  MODELS    │ ml_models.py (sklearn)     │
│  (训练)    │ 8 models × 3 layers        │
├────────────┴────────────────────────────┤
│  DATA      │ data/ + models_cache/      │
│  STORAGE   │ + model_config.json        │
└─────────────────────────────────────────┘
           ↕ 外部 LLM 服务（6 提供商）
```

---

## 三层模型体系

| 层级 | 模型 | 算法 | CV R² |
|---|---|---|---|
| L1 总造价预测 | total_pso_svr | PSO-SVR | ~92% |
| | unit_gbt | GBT | ~90% |
| L2 分部/分项工程 | section_xgb | XGBoost | ~91% |
| | subsection_xgb | XGBoost | ~89% |
| | item_xgb | XGBoost | ~87% |
| L3 清单项目 | indicator_rf | RF | ~88% |
| | boq_apriori | 频率统计 | ~85% |
| | boq_lr | LR | ~82% |

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

每类 10 条均衡训练样本，模型通过 one-hot 编码区分类型差异。

### 两条交互路径

- **向导模式**：5 步表单（项目信息→选择阶段→配置参数→模型选择→预测结果）
- **对话模式**：ReAct 智能体自然语言交互，实时展示推理链

### 数据工程

- 从7种造价表类型提取数据（表-02/03/04/08/11/13/21）
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
| POST | `/api/chat` | ReAct 智能体对话 |

### 模型训练
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/train/status` | 训练状态 + AgentScope 状态 |
| POST | `/api/train` | 训练所有模型 |
| POST | `/api/train/{model_id}` | 训练指定模型 |

### 数据管理
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/data/history` | 历史项目列表 |
| GET | `/api/data/statistics` | 训练数据统计 |
| GET | `/api/data/sufficiency` | 数据充分性评估 |
| POST | `/api/data/import` | 导入 Excel 数据 |
| POST | `/api/data/generate-sample` | 生成示例数据 |

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
- **术语规范化**：建筑造价术语严格遵循《建设工程"五算"解析》（估算/概算/预算/结算/决算）
- **渐进式 LLM**：无 API Key 时回退 MockLLM，配置后自动切换真实 AgentScope
- **零前端依赖**：HTML/CSS/JS 原生实现，打开即用
- **特征泄漏零容忍**：树模型仅使用建造前已知的输入特征，造价构成分项不作为预测输入
- **数据分级加权**：A/B/C类数据差异化权重，降低低质量数据对模型的干扰
- **预测透明**：每次预测附带置信区间、参考项目和数据来源，结果可追溯

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
