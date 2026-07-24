# AI 建筑造价预测系统

基于 **AgentScope SDK v2.0.4 + scikit-learn** 的建筑工程造价预测 ReAct 智能体应用。三层模型体系覆盖估算→概算→预算三阶段，支持 8 种建筑类型的六层级成本分解。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | 原生 HTML/CSS/JS（无框架依赖） |
| 后端 | FastAPI + uvicorn |
| 智能体 | AgentScope SDK v2.0.4（ReActAgent 模式） |
| ML 训练 | scikit-learn（SVR / GBT / XGBoost / RandomForest / LinearRegression） |
| 数据 | Pandas + openpyxl（Excel 导入/导出） |
| 模型持久化 | joblib |
| LLM 提供商 | DashScope / OpenAI / Anthropic / Gemini / Ollama / OpenAI兼容 |

---

## 快速开始

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

首次启动后：
1. 左侧边栏切换到「数据」标签 → 点击「生成示例数据」（80 条均衡样本）
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
│   ├── main.py              # FastAPI 主服务，20+ API 路由
│   ├── agent.py             # AgentScope ReAct 智能体管理器
│   ├── ml_models.py         # scikit-learn 三层模型训练管线
│   ├── model_config.py      # 6 提供商 LLM 自定义配置
│   ├── data_loader.py       # Excel 导入 + 均衡样本生成
│   ├── terminology.py       # 建筑造价术语规范（五算标准）
│   └── requirements.txt     # Python 依赖清单
├── frontend/
│   ├── index.html           # 产品首页（Hero + 功能 + 流程）
│   ├── app.html             # 应用主界面（向导 + 对话 + 侧边栏）
│   └── static/
│       ├── css/             # main.css + landing.css + app.css
│       └── js/              # app.js（1,200+ 行交互逻辑）
├── data/
│   └── sample_training_data.xlsx  # 80 条均衡训练样本
├── models_cache/            # joblib 模型缓存（训练后生成，已 .gitignore）
├── model_config.json        # LLM 提供商持久化配置
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
│            │ 20+ REST 端点               │
├────────────┬────────────────────────────┤
│  AGENT     │ agent.py (AgentScope)      │
│  (对话)    │ 5 FunctionTools            │
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

| 层级 | 模型 | 算法 | 准确率 |
|---|---|---|---|
| L1 总造价预测 | 建筑安装_总造价_[通用]_[PSO-SVR] | SVR (rbf) | 9.5%* |
| | 单位工程_(总造价/单方造价)_[通用]_[GBT] | GradientBoosting | 89.6% |
| L2 分部/分项工程 | 分部工程_单方造价_[通用]_[XGBoost] | XGBoost | 90.0% |
| | 子分部工程_单方造价_[通用]_[XGBoost] | XGBoost | 91.0% |
| | 分项工程_单方造价_[通用]_[XGBoost] | XGBoost | 90.4% |
| L3 清单项目 | 指标体系(无清单)_[通用]_[Random Forest] | RandomForest | 83.2% |
| | 清单项目_清单组成_[通用]_[Apriori/FPGrowth] | Apriori (频率) | 85% |
| | 清单项目_单方耗量(混凝土)_[通用]_[LR] | LinearRegression | 0%* |

> \* 低精度模型自动排除融合（阈值 50%），不参与最终预测

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

## 设计原则

- **真实训练优先**：8 个模型全部使用 sklearn Pipeline 真实训练，非经验系数硬编码
- **低精度剔除**：训练中 R² < 50% 的模型自动排除融合，高精度模型主导预测
- **术语规范化**：建筑造价术语严格遵循《建设工程"五算"解析》（估算/概算/预算/结算/决算）
- **渐进式 LLM**：无 API Key 时回退 MockLLM，配置后自动切换真实 AgentScope
- **零前端依赖**：HTML/CSS/JS 原生实现，打开即用

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
