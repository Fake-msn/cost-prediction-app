// ============================================================
// AI 造价预测系统 - 主应用交互
// ============================================================
const API_BASE = '';
let currentSessionId = 'default';
let currentStep = 1;
let projectData = {
    project_name: '',
    project_type: '学校',
    structure_type: '框架结构',
    total_area: '',
    floors: 1,
    location: '华东',
    build_year: 2026,
    decoration_level: '普通装修',
    stage: 'estimation',
    selected_models: []
};
let projectResult = null;

// 工具：简单 markdown 渲染
function md(text) {
    if (!text) return '';
    return text
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h2>$1</h2>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>\n?)+/gs, m => '<ul>' + m + '</ul>')
        .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^(?!<[hu])/gm, '<p>');
}

// 工具：API 请求
async function api(path, options = {}) {
    try {
        const res = await fetch(API_BASE + path, {
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
            ...options
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || '请求失败');
        }
        return await res.json();
    } catch (e) {
        console.error('API error:', e);
        throw e;
    }
}

// 工具：Toast 提示
function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// 工具：金额格式化
function formatMoney(n) {
    if (n >= 1e8) return `${(n/1e8).toFixed(2)}亿元`;
    if (n >= 1e4) return `${(n/1e4).toFixed(2)}万元`;
    return `${n.toFixed(2)}元`;
}

// 工具：日期格式化
function formatDate(iso) {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff/60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff/3600)}小时前`;
    return d.toLocaleDateString('zh-CN');
}

// ============================================================
// 初始化
// ============================================================
document.addEventListener('DOMContentLoaded', async () => {
    bindEvents();
    await loadSessions();
    await loadDataStats();
    await loadTrainStatus();
    renderStep(1);
    initChat();
});

function bindEvents() {
    // 模式切换
    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.addEventListener('click', () => switchMode(tab.dataset.mode));
    });
    // 侧边栏标签
    document.querySelectorAll('.tab-btn').forEach(tab => {
        tab.addEventListener('click', () => switchSidebar(tab.dataset.tab));
    });
    // 步骤导航
    document.getElementById('btn-prev-step').addEventListener('click', prevStep);
    document.getElementById('btn-next-step').addEventListener('click', nextStep);
    document.getElementById('btn-back').addEventListener('click', prevStep);
    document.getElementById('btn-new-project').addEventListener('click', resetProject);
    // 侧边栏按钮
    document.getElementById('btn-new-session').addEventListener('click', createNewSession);
    document.getElementById('btn-import-excel').addEventListener('click', () => document.getElementById('file-input').click());
    document.getElementById('btn-train-all').addEventListener('click', trainAllModels);
    document.getElementById('btn-llm-config').addEventListener('click', openLLMConfig);
    document.getElementById('btn-llm-cancel').addEventListener('click', () => document.getElementById('modal-llm').style.display = 'none');
    document.getElementById('btn-llm-save').addEventListener('click', saveLLMConfig);
    document.getElementById('file-input').addEventListener('change', handleFileImport);
    document.getElementById('btn-generate-sample').addEventListener('click', generateSampleData);
    document.getElementById('btn-view-stats').addEventListener('click', showDataStats);
    // 弹窗关闭
    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById(btn.dataset.modal).style.display = 'none';
        });
    });
    document.getElementById('btn-download-report').addEventListener('click', downloadReportJSON);
    document.getElementById('btn-download-html').addEventListener('click', downloadReportHTML);
}

// ============================================================
// 模式切换
// ============================================================
function switchMode(mode) {
    document.querySelectorAll('.mode-tab').forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
    document.getElementById('wizard-area').style.display = mode === 'wizard' ? 'block' : 'none';
    document.getElementById('chat-area').style.display = mode === 'chat' ? 'flex' : 'none';
}

function switchSidebar(tab) {
    document.querySelectorAll('.tab-btn').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.getElementById('tab-sessions').style.display = tab === 'sessions' ? 'block' : 'none';
    document.getElementById('tab-data').style.display = tab === 'data' ? 'block' : 'none';
}

// ============================================================
// 步骤导航
// ============================================================
function goToStep(step) {
    currentStep = step;
    document.querySelectorAll('.step').forEach((s, i) => {
        s.classList.toggle('active', i + 1 === step);
        s.classList.toggle('completed', i + 1 < step);
    });
    document.getElementById('btn-back').style.display = step > 1 ? 'block' : 'none';
    renderStep(step);
}

function prevStep() {
    if (currentStep > 1) goToStep(currentStep - 1);
}

function nextStep() {
    if (currentStep < 5) {
        if (currentStep === 1 && !validateStep1()) return;
        if (currentStep === 2 && !projectData.stage) {
            toast('请先选择预测阶段');
            return;
        }
        if (currentStep === 4) {
            runPrediction();
            return;
        }
        goToStep(currentStep + 1);
    }
}

function validateStep1() {
    if (!projectData.project_name) {
        toast('请填写项目名称');
        return false;
    }
    if (!projectData.total_area || projectData.total_area <= 0) {
        toast('请填写正确的总建筑面积');
        return false;
    }
    return true;
}

function resetProject() {
    projectData = {
        project_name: '',
        project_type: '学校',
        structure_type: '框架结构',
        total_area: '',
        floors: 1,
        location: '华东',
        build_year: 2026,
        decoration_level: '普通装修',
        stage: 'estimation',
        selected_models: []
    };
    projectResult = null;
    goToStep(1);
}

// ============================================================
// 步骤渲染
// ============================================================
function renderStep(step) {
    const nextBtn = document.getElementById('btn-next-step');
    switch (step) {
        case 1:
            renderStep1();
            nextBtn.textContent = '下一步：选择阶段';
            break;
        case 2:
            renderStep2();
            nextBtn.textContent = '下一步：配置参数';
            break;
        case 3:
            renderStep3();
            nextBtn.textContent = '下一步：选择模型';
            break;
        case 4:
            renderStep4();
            nextBtn.textContent = '开始预测';
            break;
        case 5:
            renderStep5();
            nextBtn.style.display = 'none';
            return;
    }
    nextBtn.style.display = 'inline-flex';
    document.getElementById('btn-prev-step').style.display = step > 1 ? 'inline-flex' : 'none';
}

function renderStep1() {
    const html = `
        <h2>创建新项目</h2>
        <p class="step-subtitle">请填写项目基本信息，系统将根据信息自动匹配预测模型</p>

        <div class="form-card">
            <div class="form-card-title">项目基本信息</div>
            <div class="form-card-desc">请填写项目的基本概况信息</div>
            <div class="form-grid">
                <div class="full">
                    <label class="required">项目名称</label>
                    <input type="text" id="f-project_name" value="${projectData.project_name}" placeholder="请输入项目名称">
                </div>
                <div>
                    <label class="required">建筑类型</label>
                    <select id="f-project_type">
                        <option ${projectData.project_type === '学校' ? 'selected' : ''}>学校</option>
                        <option ${projectData.project_type === '医院' ? 'selected' : ''}>医院</option>
                        <option ${projectData.project_type === '办公楼' ? 'selected' : ''}>办公楼</option>
                        <option ${projectData.project_type === '住宅' ? 'selected' : ''}>住宅</option>
                        <option ${projectData.project_type === '工业建筑' ? 'selected' : ''}>工业建筑</option>
                        <option ${projectData.project_type === '商业建筑' ? 'selected' : ''}>商业建筑</option>
                        <option ${projectData.project_type === '基础设施' ? 'selected' : ''}>基础设施</option>
                        <option ${projectData.project_type === '公共建筑' ? 'selected' : ''}>公共建筑</option>
                    </select>
                </div>
                <div>
                    <label class="required">结构类型</label>
                    <select id="f-structure_type">
                        ${['框架结构','框剪结构','剪力墙结构','砖混结构','钢结构','木结构','框架-核心筒','筒中筒']
                          .map(s => `<option ${projectData.structure_type === s ? 'selected' : ''}>${s}</option>`).join('')}
                    </select>
                </div>
                <div>
                    <label class="required">所在地区</label>
                    <select id="f-location">
                        ${['华北','华东','华南','华中','西南','西北','东北']
                          .map(r => `<option ${projectData.location === r ? 'selected' : ''}>${r}</option>`).join('')}
                    </select>
                </div>
                <div>
                    <label class="required">建造年份</label>
                    <input type="number" id="f-build_year" value="${projectData.build_year}" min="2020" max="2030">
                </div>
                <div>
                    <label class="required">总建筑面积 (m²) <span class="required"></span></label>
                    <input type="number" id="f-total_area" value="${projectData.total_area}" placeholder="请输入建筑面积">
                </div>
                <div>
                    <label class="required">楼层数</label>
                    <input type="number" id="f-floors" value="${projectData.floors}" min="1" max="200">
                </div>
            </div>
        </div>

        <div class="form-card">
            <div class="form-card-title">相关文件</div>
            <div class="form-card-desc">上传项目相关文件，如概算批复、用地许可证、招投标文件等</div>
            <div class="upload-zone" onclick="document.getElementById('file-input').click()">
                <div class="upload-zone-icon">⬆️</div>
                <div>点击或拖拽文件到此处上传</div>
            </div>
        </div>
    `;
    document.getElementById('step-content').innerHTML = html;
    bindStep1Events();
}

function bindStep1Events() {
    ['project_name','project_type','structure_type','total_area','floors','location','build_year']
        .forEach(k => {
            const el = document.getElementById(`f-${k}`);
            if (el) el.addEventListener('input', e => {
                projectData[k] = k === 'total_area' || k === 'floors' || k === 'build_year'
                    ? parseFloat(e.target.value) || 0 : e.target.value;
            });
        });
}

function renderStep2() {
    const stages = [
        { id: 'estimation', icon: '⚡', cls: 'est', name: '估算阶段', desc: '快速概览项目投资规模',
          params: '7 个参数', accuracy: '70-80%',
          points: ['适用于项目前期可行性研究', '基于类比估算和经验数据', '提供投资决策参考依据'] },
        { id: 'preliminary', icon: '🎯', cls: 'pre', name: '概算阶段', desc: '初步设计阶段的成本测算',
          params: '32 个参数', accuracy: '80-90%',
          points: ['适用于初步设计阶段', '基于初步设计图纸和方案', '作为项目投资控制的基准'] },
        { id: 'budget', icon: '🌿', cls: 'bud', name: '预算阶段', desc: '施工图设计阶段的精确测算',
          params: '35 个参数', accuracy: '95%+',
          points: ['适用于施工图设计阶段', '基于详细设计图纸和清单', '作为招投标和合同签订依据'] }
    ];

    const html = `
        <h2>选择造价阶段</h2>
        <p class="step-subtitle">根据项目当前阶段选择合适的预测精度</p>

        <div class="stage-options">
            ${stages.map(s => `
                <div class="stage-card ${projectData.stage === s.id ? 'selected' : ''}" data-stage="${s.id}">
                    <div class="stage-icon ${s.cls}">${s.icon}</div>
                    <h3>${s.name}</h3>
                    <div class="stage-card-desc">${s.desc}</div>
                    <div class="stage-tags">
                        <span class="tag">${s.params}</span>
                        <span class="tag accuracy">精度 ${s.accuracy}</span>
                    </div>
                    <ul>
                        ${s.points.map(p => `<li>${p}</li>`).join('')}
                    </ul>
                </div>
            `).join('')}
        </div>
    `;
    document.getElementById('step-content').innerHTML = html;
    document.querySelectorAll('.stage-card').forEach(card => {
        card.addEventListener('click', () => {
            projectData.stage = card.dataset.stage;
            document.querySelectorAll('.stage-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
        });
    });
}

function renderStep3() {
    const stageInfo = {
        estimation: { count: 7, accuracy: '70-80%', tabs: [{ id: 'basic', name: '基础参数 (3)' }] },
        preliminary: { count: 32, accuracy: '80-90%', tabs: [
            { id: 'basic', name: '基础参数 (8)' }, { id: 'struct', name: '结构参数 (8)' },
            { id: 'system', name: '系统参数 (8)' }, { id: 'decoration', name: '装修参数 (6)' }
        ]},
        budget: { count: 35, accuracy: '95%+', tabs: [
            { id: 'basic', name: '基础参数 (8)' }, { id: 'struct', name: '结构参数 (8)' },
            { id: 'system', name: '系统参数 (10)' }, { id: 'decoration', name: '装修参数 (9)' }
        ]}
    };
    const info = stageInfo[projectData.stage] || stageInfo.estimation;

    const html = `
        <div class="form-card" style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <div class="form-card-title">${projectData.stage === 'estimation' ? '估算' : projectData.stage === 'preliminary' ? '概算' : '预算'}阶段</div>
                <div class="form-card-desc">共 ${info.count} 个参数 · 精度 ${info.accuracy}</div>
            </div>
            <button class="btn btn-ghost btn-sm">快速概览</button>
        </div>

        <div class="form-card">
            <div class="form-card-title">配置 ${info.count} 个参数</div>
            <div class="form-card-desc">根据选择的阶段配置相应的技术参数，参数越详细预测越准确</div>

            <div class="param-tabs">
                ${info.tabs.map((t, i) => `<button class="param-tab ${i === 0 ? 'active' : ''}" data-tab="${t.id}">${t.name}</button>`).join('')}
            </div>

            <div class="param-content" id="param-content">
                ${renderParamFields('basic')}
            </div>

            <div class="param-hint">
                <span class="param-hint-icon">ⓘ</span>
                <span>参数说明：${projectData.stage === 'estimation' ? '估算阶段仅需基础参数，系统将根据历史数据推算其他参数' : '已配置参数将用于提升预测精度'}</span>
            </div>
        </div>
    `;
    document.getElementById('step-content').innerHTML = html;
    document.querySelectorAll('.param-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.param-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('param-content').innerHTML = renderParamFields(tab.dataset.tab);
        });
    });
}

function renderParamFields(tab) {
    const fieldMap = {
        basic: [
            { id: 'decoration', label: '装修标准', type: 'select', options: ['简单装修', '普通装修', '精装修', '豪华装修'] },
            { id: 'decoration_inside', label: '室内装修', type: 'select', options: ['简单装修', '普通装修', '精装修', '豪华装修'] },
            { id: 'basement', label: '地下室面积', type: 'number', unit: 'm²' },
            { id: 'building_height', label: '建筑高度', type: 'number', unit: 'm' },
        ],
        struct: [
            { id: 'foundation', label: '基础类型', type: 'select', options: ['筏板基础','条形基础','独立基础','桩基础'] },
            { id: 'seismic', label: '抗震设防烈度', type: 'select', options: ['6度','7度','8度','9度'] },
            { id: 'concrete_grade', label: '混凝土强度等级', type: 'select', options: ['C25','C30','C35','C40','C45','C50'] },
            { id: 'steel_grade', label: '钢筋等级', type: 'select', options: ['HPB300','HRB400','HRB500'] },
        ],
        system: [
            { id: 'hvac', label: '空调系统', type: 'select', options: ['分体空调','多联机','集中空调','无'] },
            { id: 'elevator', label: '电梯配置', type: 'select', options: ['无','客梯','客货梯','医用梯'] },
            { id: 'fire', label: '消防系统', type: 'select', options: ['消火栓','自动喷淋','气体灭火','智能消防'] },
            { id: 'smart', label: '智能化系统', type: 'select', options: ['基础','标准','高级','智慧'] },
        ],
        decoration: [
            { id: 'exterior', label: '外立面装修', type: 'select', options: ['涂料','面砖','石材','幕墙','铝板'] },
            { id: 'roof', label: '屋面做法', type: 'select', options: ['防水卷材','刚性防水','种植屋面','金属屋面'] },
            { id: 'window', label: '外窗类型', type: 'select', options: ['普通铝合金','断桥铝','塑钢','木铝复合'] },
            { id: 'duration', label: '施工周期 (月)', type: 'number', placeholder: '24' },
        ]
    };
    const fields = fieldMap[tab] || fieldMap.basic;
    return `
        <div class="param-grid">
            ${fields.map(f => `
                <div>
                    <label>${f.label}</label>
                    ${f.type === 'select' ? `
                        <select>
                            ${f.options.map(o => `<option>${o}</option>`).join('')}
                        </select>
                    ` : `
                        <input type="number" placeholder="${f.placeholder || ''}">
                    `}
                </div>
            `).join('')}
            <div class="full">
                <label>特殊设备</label>
                <select>
                    <option>有</option><option>无</option>
                </select>
            </div>
            <div class="full">
                <label>地质条件</label>
                <select>
                    <option>一般</option><option>复杂</option><option>简单</option>
                </select>
            </div>
        </div>
    `;
}

async function renderStep4() {
    let models;
    try {
        models = await api('/api/models');
    } catch (e) {
        models = {};
    }

    const html = `
        <h2>模型选择</h2>
        <p class="step-subtitle">根据项目阶段已自动激活匹配模型，您也可以手动调整</p>

        <div style="display:flex; gap:8px; margin-bottom:20px;">
            <button class="btn btn-ghost btn-sm" id="btn-select-all">全选</button>
            <button class="btn btn-ghost btn-sm" id="btn-clear-all">清空</button>
        </div>

        <div id="models-container">
            ${renderModelGroups(models)}
        </div>
    `;
    document.getElementById('step-content').innerHTML = html;

    // 默认选中
    const defaults = {
        estimation: ['total_pso_svr', 'section_xgb', 'indicator_rf'],
        preliminary: ['total_pso_svr', 'unit_gbt', 'section_xgb', 'item_xgb', 'indicator_rf'],
        budget: ['total_pso_svr', 'unit_gbt', 'section_xgb', 'subsection_xgb', 'item_xgb', 'indicator_rf', 'boq_apriori', 'boq_lr']
    };
    projectData.selected_models = [...(defaults[projectData.stage] || defaults.estimation)];

    applyModelSelection();

    document.querySelectorAll('.model-item').forEach(item => {
        item.addEventListener('click', () => {
            const mid = item.dataset.model;
            const idx = projectData.selected_models.indexOf(mid);
            if (idx >= 0) {
                projectData.selected_models.splice(idx, 1);
                item.classList.remove('selected');
                item.querySelector('.model-check').textContent = '';
            } else {
                projectData.selected_models.push(mid);
                item.classList.add('selected');
                item.querySelector('.model-check').textContent = '✓';
            }
        });
    });
    document.getElementById('btn-select-all').addEventListener('click', () => {
        document.querySelectorAll('.model-item').forEach(item => {
            if (!item.classList.contains('selected')) {
                item.classList.add('selected');
                item.querySelector('.model-check').textContent = '✓';
                projectData.selected_models.push(item.dataset.model);
            }
        });
    });
    document.getElementById('btn-clear-all').addEventListener('click', () => {
        document.querySelectorAll('.model-item').forEach(item => {
            item.classList.remove('selected');
            item.querySelector('.model-check').textContent = '';
        });
        projectData.selected_models = [];
    });
}

function renderModelGroups(groups) {
    const descriptions = {
        '总造价预测模型': { icon: '⚙️', desc: '预测项目总造价和单方造价' },
        '分部/分项工程模型': { icon: '📊', desc: '预测各部分分项工程的单方造价' },
        '清单项目模型': { icon: '📋', desc: '预测清单组成和单方耗量' }
    };
    return Object.entries(groups).map(([layer, models]) => {
        const info = descriptions[layer] || { icon: '🔧', desc: '' };
        return `
            <div class="model-group">
                <div class="model-group-header">
                    <span class="icon">${info.icon}</span>
                    <span>${layer}</span>
                </div>
                <div class="model-group-desc">${info.desc}</div>
                ${models.map(m => `
                    <div class="model-item" data-model="${m.id}">
                        <div class="model-check"></div>
                        <div class="model-info">
                            <div class="model-name">${m.name}</div>
                            <div class="model-desc">基于${m.algorithm}的${layer.replace('模型','')}预测模型</div>
                        </div>
                        <div class="model-tags">
                            <span class="model-tag">${m.algorithm}</span>
                            <span class="model-accuracy ${m.accuracy >= 90 ? 'high' : m.accuracy >= 85 ? 'mid' : 'low'}">准确率 ${m.accuracy}%</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }).join('');
}

function applyModelSelection() {
    projectData.selected_models.forEach(mid => {
        const item = document.querySelector(`.model-item[data-model="${mid}"]`);
        if (item) {
            item.classList.add('selected');
            item.querySelector('.model-check').textContent = '✓';
        }
    });
}

async function runPrediction() {
    const nextBtn = document.getElementById('btn-next-step');
    nextBtn.disabled = true;
    nextBtn.textContent = '预测中...';

    try {
        const result = await api('/api/predict', {
            method: 'POST',
            body: JSON.stringify(projectData)
        });
        projectResult = result;
        goToStep(5);
        toast('预测完成！');
    } catch (e) {
        toast('预测失败：' + e.message, 'error');
    } finally {
        nextBtn.disabled = false;
        nextBtn.textContent = '开始预测';
    }
}

function renderStep5() {
    if (!projectResult) {
        document.getElementById('step-content').innerHTML = '<p>暂无预测结果</p>';
        return;
    }
    const r = projectResult;
    const total = r.fused_total_cost;
    const unitPrice = r.fused_unit_price;
    const accuracy = r.average_accuracy;

    const html = `
        <h2>预测结果</h2>
        <p class="step-subtitle">预测精度 ${accuracy}% · 使用 ${r.model_count} 个模型</p>

        <div class="result-summary">
            <div>
                <div class="result-summary-label">项目总造价</div>
                <div class="result-summary-value">${formatMoney(total)}</div>
                <div class="result-summary-meta">
                    <span>建筑面积: ${r.project.area.toLocaleString()} m²</span>
                    <span>单方造价: <strong>${unitPrice.toLocaleString()} 元/m²</strong></span>
                </div>
            </div>
            <div class="result-summary-actions">
                <button class="btn btn-ghost btn-sm" onclick="adjustParams()">⚙ 调整指标</button>
                <button class="btn btn-ghost btn-sm" onclick="rePredict()">↻ 重新预测</button>
                <button class="btn btn-primary btn-sm" onclick="exportReport()">↓ 导出报告</button>
            </div>
        </div>

        <div class="result-tabs">
            <button class="result-tab active" data-tab="indicator">📈 指标体系</button>
            <button class="result-tab" data-tab="unit">🏢 单位工程</button>
            <button class="result-tab" data-tab="boq">📋 工程量清单</button>
        </div>

        <div class="result-content" id="result-content">
            ${renderCostComposition(r.individual_predictions)}
        </div>
    `;
    document.getElementById('step-content').innerHTML = html;
    bindResultTabs(r);
}

function renderCostComposition(predictions) {
    const totalModel = predictions['total_pso_svr'];
    if (!totalModel || !totalModel.composition) {
        return '<p>无成本构成数据</p>';
    }
    const comp = totalModel.composition;
    const rows = [];

    Object.entries(comp).forEach(([catName, cat]) => {
        const ratioPct = Math.round(cat.ratio * 100);
        const amount = cat.amount;
        rows.push(`
            <div class="composition-row parent" onclick="toggleChildren(this)">
                <div class="composition-toggle">▾</div>
                <div class="composition-name">${catName}</div>
                <div class="composition-bar">
                    <div class="composition-bar-fill" style="width:${ratioPct}%"></div>
                </div>
                <div class="composition-ratio">${ratioPct}%</div>
                <div class="composition-amount">${formatMoney(amount)}</div>
            </div>
        `);
        if (cat.items && cat.items.length) {
            rows.push(`<div class="composition-children">`);
            cat.items.forEach(item => {
                const ir = Math.round(item.ratio * 100);
                rows.push(`
                    <div class="composition-row">
                        <div class="composition-toggle">·</div>
                        <div class="composition-name">${item.name}</div>
                        <div class="composition-bar">
                            <div class="composition-bar-fill" style="width:${ir}%; background: var(--text-soft);"></div>
                        </div>
                        <div class="composition-ratio">${ir}%</div>
                        <div class="composition-amount">${formatMoney(item.amount)}</div>
                    </div>
                `);
            });
            rows.push(`</div>`);
        }
    });
    return `<div class="composition-list">${rows.join('')}</div>`;
}

function toggleChildren(row) {
    const children = row.nextElementSibling;
    if (children && children.classList.contains('composition-children')) {
        const isVisible = children.style.display !== 'none';
        children.style.display = isVisible ? 'none' : 'block';
        row.querySelector('.composition-toggle').textContent = isVisible ? '▸' : '▾';
    }
}

function bindResultTabs(r) {
    document.querySelectorAll('.result-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.result-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const tabId = tab.dataset.tab;
            if (tabId === 'indicator') {
                document.getElementById('result-content').innerHTML = renderCostComposition(r.individual_predictions);
            } else if (tabId === 'unit') {
                document.getElementById('result-content').innerHTML = renderUnitProjects(r.individual_predictions);
            } else if (tabId === 'boq') {
                document.getElementById('result-content').innerHTML = renderBOQ(r.individual_predictions);
            }
        });
    });
}

function renderUnitProjects(predictions) {
    const unit = predictions['unit_gbt'];
    if (!unit || !unit.unit_projects) return '<p>无单位工程数据</p>';
    return `
        <div class="composition-list">
            ${unit.unit_projects.map(p => {
                const r = Math.round(p.ratio * 100);
                return `
                    <div class="composition-row parent">
                        <div class="composition-toggle">·</div>
                        <div class="composition-name">${p.name}</div>
                        <div class="composition-bar">
                            <div class="composition-bar-fill" style="width:${r}%"></div>
                        </div>
                        <div class="composition-ratio">${r}%</div>
                        <div class="composition-amount">${formatMoney(p.amount)}</div>
                    </div>
                `;
            }).join('')}
        </div>
        <div style="margin-top:16px; padding:12px; background:var(--bg-soft); border-radius:8px; font-size:12px; color:var(--text-soft);">
            安装工程包含：给排水、暖通空调、强电、弱电、消防等子系统
        </div>
    `;
}

function renderBOQ(predictions) {
    const items = predictions['item_xgb'];
    if (!items) return '<p>无清单数据</p>';
    return `
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background:var(--bg-soft); border-bottom:1px solid var(--border);">
                        <th style="padding:10px; text-align:left;">清单项目</th>
                        <th style="padding:10px; text-align:right;">单方耗量</th>
                        <th style="padding:10px; text-align:right;">单价 (元)</th>
                        <th style="padding:10px; text-align:right;">总金额</th>
                    </tr>
                </thead>
                <tbody>
                    ${items.items.map(it => `
                        <tr style="border-bottom:1px solid var(--border);">
                            <td style="padding:10px;">${it.name}</td>
                            <td style="padding:10px; text-align:right;">${it.quantity_per_sqm} ${it.unit}/m²</td>
                            <td style="padding:10px; text-align:right;">${it.unit_price.toLocaleString()}</td>
                            <td style="padding:10px; text-align:right; font-weight:500;">${formatMoney(it.amount)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function adjustParams() {
    goToStep(3);
}

function rePredict() {
    runPrediction();
}

function exportReport() {
    if (!projectResult) {
        toast('暂无预测结果');
        return;
    }
    document.getElementById('report-content').innerHTML = generateReportHTML(projectResult);
    document.getElementById('modal-report').style.display = 'flex';
}

function generateReportHTML(r) {
    return `
        <h2 style="margin-bottom:8px;">${r.project.name} - 造价分析报告</h2>
        <p style="color:var(--text-soft); font-size:13px; margin-bottom:16px;">生成时间：${new Date().toLocaleString('zh-CN')}</p>

        <div class="result-summary" style="margin-bottom:20px;">
            <div>
                <div class="result-summary-label">项目总造价</div>
                <div class="result-summary-value">${formatMoney(r.fused_total_cost)}</div>
                <div class="result-summary-meta">
                    <span>建筑面积: ${r.project.area.toLocaleString()} m²</span>
                    <span>单方造价: <strong>${r.fused_unit_price.toLocaleString()} 元/m²</strong></span>
                    <span>综合精度: ${r.average_accuracy}%</span>
                </div>
            </div>
        </div>

        <h3>使用模型</h3>
        <ul>${r.selected_models.map(m => `<li>${m}</li>`).join('')}</ul>

        <h3 style="margin-top:20px;">费用构成</h3>
        ${renderCostComposition(r.individual_predictions)}

        <p style="margin-top:24px; font-size:12px; color:var(--text-mute);">
            本报告由 AI 造价预测系统基于历史项目数据训练的专业模型生成，仅供决策参考。
        </p>
    `;
}

function downloadReportJSON() {
    if (!projectResult) return;
    const blob = new Blob([JSON.stringify(projectResult, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `造价分析报告_${projectResult.project.name}_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

function downloadReportHTML() {
    if (!projectResult) return;
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>造价分析报告</title>
    <style>${document.querySelector('style') ? '' : ''}</style></head><body>${generateReportHTML(projectResult)}</body></html>`;
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `造价分析报告_${projectResult.project.name}.html`;
    a.click();
    URL.revokeObjectURL(url);
}

// ============================================================
// 会话管理
// ============================================================
async function loadSessions() {
    try {
        const sessions = await api('/api/chat/sessions');
        const list = document.getElementById('session-list');
        if (sessions.length === 0) {
            list.innerHTML = '<p style="color:var(--text-mute); font-size:12px; padding:12px; text-align:center;">暂无历史会话</p>';
            return;
        }
        list.innerHTML = sessions.map(s => `
            <div class="session-item ${s.id === currentSessionId ? 'active' : ''}" data-id="${s.id}">
                <div class="session-item-title">${s.title}</div>
                <div class="session-item-meta">${s.message_count} 条消息 · ${formatDate(s.updated_at)}</div>
                <button class="session-delete" data-id="${s.id}">×</button>
            </div>
        `).join('');
        list.querySelectorAll('.session-item').forEach(item => {
            item.addEventListener('click', e => {
                if (e.target.classList.contains('session-delete')) return;
                currentSessionId = item.dataset.id;
                document.querySelectorAll('.session-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                switchMode('chat');
                loadChatHistory();
            });
        });
        list.querySelectorAll('.session-delete').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                await api(`/api/chat/sessions/${btn.dataset.id}`, { method: 'DELETE' });
                loadSessions();
            });
        });
    } catch (e) {
        console.error('Load sessions failed:', e);
    }
}

function createNewSession() {
    currentSessionId = 'session_' + Date.now();
    document.getElementById('chat-messages').innerHTML = document.querySelector('.chat-welcome').outerHTML;
    document.querySelectorAll('.session-item').forEach(i => i.classList.remove('active'));
    loadSessions();
    switchMode('chat');
}

// ============================================================
// 对话功能
// ============================================================
function initChat() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('btn-send');
    sendBtn.addEventListener('click', sendChat);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChat();
        }
    });
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            input.value = chip.dataset.q;
            sendChat();
        });
    });
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    appendMessage('user', msg);
    input.value = '';
    input.style.height = 'auto';

    const loadingId = appendLoading();

    try {
        const res = await api('/api/chat', {
            method: 'POST',
            body: JSON.stringify({ message: msg, session_id: currentSessionId })
        });
        document.getElementById(loadingId).remove();
        appendMessage('assistant', res.reply, res.react_steps);
        loadSessions();
    } catch (e) {
        document.getElementById(loadingId).remove();
        appendMessage('assistant', '抱歉，对话出错：' + e.message);
    }
}

function appendMessage(role, content, reactSteps) {
    const div = document.createElement('div');
    div.className = 'chat-message';
    const avatar = role === 'user' ? '👤' : '🤖';
    div.innerHTML = `
        <div class="chat-avatar ${role}">${avatar}</div>
        <div class="chat-bubble ${role}">${md(content)}</div>
    `;
    if (reactSteps && reactSteps.length > 0) {
        const trace = document.createElement('div');
        trace.style.marginLeft = '44px';
        trace.innerHTML = `
            <div class="react-trace">
                <div style="font-weight:500; margin-bottom:6px;">🧠 ReAct 推理过程</div>
                ${reactSteps.map(s => `
                    <div class="react-step">
                        <span class="react-step-label">${s.step === 'thought' ? '思考' : s.step === 'action' ? '行动' : s.step === 'observation' ? '观察' : '回答'}</span>
                        <span class="react-step-content">${s.content}</span>
                    </div>
                `).join('')}
            </div>
        `;
        div.appendChild(trace);
    }
    document.getElementById('chat-messages').appendChild(div);
    document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
}

function appendLoading() {
    const id = 'loading_' + Date.now();
    const div = document.createElement('div');
    div.className = 'chat-message';
    div.id = id;
    div.innerHTML = `
        <div class="chat-avatar assistant">🤖</div>
        <div class="chat-bubble assistant">
            <div class="loading-dots"><span></span><span></span><span></span></div>
        </div>
    `;
    document.getElementById('chat-messages').appendChild(div);
    document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
    return id;
}

async function loadChatHistory() {
    // 简单实现：切换会话时清空
    const messages = document.getElementById('chat-messages');
    messages.innerHTML = `
        <div class="chat-welcome">
            <div class="welcome-icon">🤖</div>
            <h3>会话已切换</h3>
            <p>开始新的对话</p>
        </div>
    `;
}

// ============================================================
// 数据管理
// ============================================================
async function loadDataStats() {
    try {
        const stats = await api('/api/data/statistics');
        document.getElementById('data-count').textContent = stats.count;
        document.getElementById('data-status').textContent = stats.count > 0 ? '已就绪' : '未导入';
    } catch (e) {
        console.error('Load stats failed:', e);
    }
}

async function handleFileImport(e) {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const result = await fetch('/api/data/import', {
            method: 'POST',
            body: formData
        }).then(r => r.json());
        if (result.success) {
            toast(`导入成功：${result.imported_count} 条记录`);
            loadDataStats();
        } else {
            toast('导入失败：' + (result.error || '未知错误'), 'error');
        }
    } catch (err) {
        toast('导入失败：' + err.message, 'error');
    }
    e.target.value = '';
}

async function generateSampleData() {
    try {
        const result = await api('/api/data/generate-sample?n=30', { method: 'POST' });
        toast(`已生成 ${result.count} 条示例数据`);
        loadDataStats();
    } catch (e) {
        toast('生成失败：' + e.message, 'error');
    }
}

async function showDataStats() {
    try {
        const stats = await api('/api/data/statistics');
        const html = `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                <div class="data-stat"><span>总样本数</span><strong>${stats.count}</strong></div>
                <div class="data-stat"><span>字段数</span><strong>${stats.fields?.total || '-'}</strong></div>
                ${stats.unit_price ? `
                    <div class="data-stat"><span>单方造价均值</span><strong>${stats.unit_price.mean.toFixed(0)} 元/m²</strong></div>
                    <div class="data-stat"><span>单方造价范围</span><strong>${stats.unit_price.min.toFixed(0)} - ${stats.unit_price.max.toFixed(0)}</strong></div>
                ` : ''}
            </div>
            ${stats.by_project_type ? `
                <h4 style="margin-top:20px; margin-bottom:8px;">按建筑类型分布</h4>
                <div style="display:flex; flex-wrap:wrap; gap:8px;">
                    ${Object.entries(stats.by_project_type).map(([k, v]) =>
                        `<span class="tag">${k}: ${v}</span>`).join('')}
                </div>
            ` : ''}
            ${stats.by_region ? `
                <h4 style="margin-top:16px; margin-bottom:8px;">按地区分布</h4>
                <div style="display:flex; flex-wrap:wrap; gap:8px;">
                    ${Object.entries(stats.by_region).map(([k, v]) =>
                        `<span class="tag">${k}: ${v}</span>`).join('')}
                </div>
            ` : ''}
        `;
        document.getElementById('stats-content').innerHTML = html;
        document.getElementById('modal-stats').style.display = 'flex';
    } catch (e) {
        toast('加载统计失败：' + e.message, 'error');
    }
}

// ============================================================
// 模型训练管理（scikit-learn 真实训练）
// ============================================================
async function loadTrainStatus() {
    try {
        const status = await api('/api/train/status');
        const models = status.models || [];
        const trained = models.filter(m => m.is_trained).length;
        document.getElementById('trained-count').textContent = `${trained}/${models.length}`;
        document.getElementById('agentscope-status').textContent = status.agentscope_available
            ? `✓ v${status.agentscope_version || ''}` : '未安装';
        document.getElementById('agentscope-status').style.color = status.agentscope_available ? 'var(--success)' : 'var(--text-mute)';

        // 后端标识
        const badge = document.getElementById('backend-badge');
        if (status.has_active_llm) {
            badge.textContent = 'AgentScope (LLM 已激活)';
            badge.style.color = 'var(--success)';
        } else if (status.agentscope_available) {
            badge.textContent = 'AgentScope SDK + scikit-learn';
            badge.style.color = 'var(--text-soft)';
        } else {
            badge.textContent = 'scikit-learn (MockLLM)';
            badge.style.color = 'var(--text-mute)';
        }

        // 模型列表
        const list = document.getElementById('model-status-list');
        list.innerHTML = models.map(m => `
            <div class="model-status-item" style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; font-size:12px;">
                <span style="color:var(--text-soft); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;" title="${m.name}">${m.id}</span>
                <span style="color:${m.is_trained ? 'var(--success)' : 'var(--text-mute)'}; font-weight:500;">
                    ${m.is_trained ? `${m.accuracy}%` : '未训练'}
                </span>
            </div>
        `).join('');
    } catch (e) {
        console.error('Load train status failed:', e);
    }
}

async function trainAllModels() {
    const btn = document.getElementById('btn-train-all');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '训练中...';
    try {
        const result = await api('/api/train', { method: 'POST' });
        toast(`训练完成：${result.trained}/${result.total} 个模型成功（${result.sample_count} 样本）`);
        await loadTrainStatus();
    } catch (e) {
        toast('训练失败：' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// ============================================================
// LLM 配置管理（多提供商自定义模型）
// ============================================================
let currentLLMProviders = [];
let activeLLMProvider = '';

async function openLLMConfig() {
    try {
        const data = await api('/api/llm/providers');
        currentLLMProviders = data.providers || [];
        activeLLMProvider = data.active_provider || '';

        const html = `
            <div style="margin-bottom:16px; padding:12px; background:var(--bg-soft); border-radius:8px; font-size:13px; color:var(--text-soft);">
                <strong>💡 说明：</strong>配置 LLM API Key 后，对话将使用真实 AgentScope ReActAgent 推理。
                未配置时回退到内置 MockLLM（仍可调用所有工具，但无真实大模型推理）。
                参考：<a href="https://doc.agentscope.io/zh_CN/tutorial/task_model.html" target="_blank" style="color:var(--info);">AgentScope 模型文档</a>
            </div>

            <div style="margin-bottom:16px;">
                <label>激活提供商</label>
                <select id="llm-active-select" style="margin-bottom:8px;">
                    <option value="">— 未激活（使用 MockLLM）—</option>
                    ${currentLLMProviders.map(p => `
                        <option value="${p.provider}" ${p.provider === activeLLMProvider ? 'selected' : ''} ${!p.is_configured ? 'disabled' : ''}>
                            ${p.name} ${p.is_configured ? '✓' : '(未配置)'}
                        </option>
                    `).join('')}
                </select>
            </div>

            <div id="llm-provider-forms">
                ${currentLLMProviders.map(p => renderProviderForm(p)).join('')}
            </div>
        `;
        document.getElementById('llm-config-content').innerHTML = html;

        // 切换激活时只显示对应表单
        document.getElementById('llm-active-select').addEventListener('change', (e) => {
            activeLLMProvider = e.target.value;
            document.querySelectorAll('.provider-form').forEach(f => {
                f.style.display = f.dataset.provider === activeLLMProvider ? 'block' : 'none';
            });
        });
        // 初始显示
        document.querySelectorAll('.provider-form').forEach(f => {
            f.style.display = f.dataset.provider === activeLLMProvider ? 'block' : 'none';
        });

        document.getElementById('modal-llm').style.display = 'flex';
    } catch (e) {
        toast('加载配置失败：' + e.message, 'error');
    }
}

function renderProviderForm(p) {
    const needsApiKey = p.provider !== 'ollama';
    const needsBaseUrl = p.provider === 'openai_compatible' || p.provider === 'ollama';
    return `
        <div class="provider-form" data-provider="${p.provider}" style="display:none; padding:16px; border:1px solid var(--border); border-radius:8px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <strong>${p.name}</strong>
                <span style="font-size:11px; padding:2px 8px; border-radius:999px; background:${p.is_configured ? 'var(--accent-green)' : 'var(--bg-soft)'}; color:${p.is_configured ? '#065f46' : 'var(--text-mute)'};">
                    ${p.is_configured ? '已配置' : '未配置'}
                </span>
            </div>
            <div class="form-grid" style="grid-template-columns:1fr 1fr; gap:12px;">
                <div>
                    <label>模型名称</label>
                    <input type="text" id="llm-model-${p.provider}" value="${p.model_name}" placeholder="${p.available_models[0] || ''}" list="models-${p.provider}">
                    <datalist id="models-${p.provider}">
                        ${p.available_models.map(m => `<option value="${m}">`).join('')}
                    </datalist>
                </div>
                ${needsApiKey ? `
                    <div>
                        <label>API Key</label>
                        <input type="password" id="llm-key-${p.provider}" placeholder="${p.env_key}" value="">
                    </div>
                ` : ''}
                ${needsBaseUrl ? `
                    <div class="full" style="grid-column:1/-1;">
                        <label>Base URL</label>
                        <input type="text" id="llm-url-${p.provider}" value="${p.has_base_url ? '' : ''}" placeholder="${p.provider === 'ollama' ? 'http://localhost:11434' : 'http://localhost:8000/v1'}">
                    </div>
                ` : ''}
            </div>
            <div style="margin-top:8px; font-size:11px; color:var(--text-mute);">
                环境变量：${p.env_key} · 文档：<a href="${p.docs}" target="_blank" style="color:var(--info);">${p.docs}</a>
                ${p.supports_tools ? ' · ✓ 工具调用' : ''}${p.supports_thinking ? ' · ✓ 推理模式' : ''}
            </div>
        </div>
    `;
}

async function saveLLMConfig() {
    const newActive = document.getElementById('llm-active-select').value;
    try {
        // 保存各 provider 配置
        for (const p of currentLLMProviders) {
            const modelEl = document.getElementById(`llm-model-${p.provider}`);
            const keyEl = document.getElementById(`llm-key-${p.provider}`);
            const urlEl = document.getElementById(`llm-url-${p.provider}`);
            const config = {};
            if (modelEl && modelEl.value) config.model_name = modelEl.value;
            if (keyEl && keyEl.value) config.api_key = keyEl.value;
            if (urlEl && urlEl.value) config.base_url = urlEl.value;
            if (Object.keys(config).length > 0) {
                await api(`/api/llm/config/${p.provider}`, {
                    method: 'POST', body: JSON.stringify(config)
                });
            }
        }
        // 设置激活
        if (newActive) {
            await api('/api/llm/active', {
                method: 'POST', body: JSON.stringify({ provider: newActive })
            });
        }
        toast('LLM 配置已保存');
        document.getElementById('modal-llm').style.display = 'none';
        await loadTrainStatus();
    } catch (e) {
        toast('保存失败：' + e.message, 'error');
    }
}
