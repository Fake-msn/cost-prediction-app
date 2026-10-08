# DuckDB 2.0 升级 Runbook（风险管控 / 数据迁移 / 接口适配）

> 状态：**已就绪，等待正式切换**。本文件记录 2026-10-09 用真实 DuckDB 2.0 nightly 完成的全部验证与已落地的管控措施。

## 1. 现状与前提（决定性事实）

- **PyPI 稳定源最新为 `1.5.6`，没有稳定的 2.0**。2.0 目前只有 nightly 预发布：最新 `2.0.0.dev2610011535`（`v2.0.0-alpha43763 / Cyanoptera`），需 `--pre` 才能安装。GA 仍未发布。
- 生产运行时：`duckdb 1.5.5`（Python 3.11 / win_amd64），库文件 `data/cost_prediction.duckdb`（约 71MB，头部存储标记 `v1.5.5`）。
- 结论：**现在无法在稳定版上"升级到 2.0"**。本 runbook 用 nightly 完成了全部技术验证，正式切换门控在 §5，建议等 2.0 稳定 GA 后执行。

## 2. 实测结论（全部基于 nightly `2.0.0.dev2610011535` 的真实运行证据）

| 验证项 | 方法 | 结果 |
|---|---|---|
| 2.0 能否读现有 v1.5.5 库 | 只读打开生产库副本 | ✅ 正常，行数一致 |
| 2.0 写入是否升级存储格式 | 建表/插入/CHECKPOINT 后读文件头 | ✅ **仍是 `v1.5.5`，未自动升级** |
| 单向门（1.5.5 能否再打开被 2.0 写过的库） | 用生产 venv(1.5.5) 打开 2.0 写过的副本 | ✅ **仍能打开并读到正确数据** → 回滚无需还原数据 |
| 接口兼容性 | 15 项 SQL/API 构造在 1.5.5 与 2.0 下对跑 | ✅ **两版 15/15 完全一致，零差异** |
| 应用数据层 E2E | 2.0 下实例化 `DataLoader` 跑全部读路径（隔离副本） | ✅ 全通过：history 232、boq df (64155,14)、聚合 arch=0.765、get_boq_items 65027、to_dataframe (232,13) |

**关键判断**：网上流传的"2.0 存储单向门、1.5 打不开"在**默认路径下不成立**。只有在使用 2.0 独有存储特性（如把列改成需要 v2 格式的类型）时才会关闭回滚门。因此本项目的升级属于**低风险、可平滑回滚**。

接口兼容覆盖的构造：`INSERT OR REPLACE`、`executemany(?)`、`ALTER ADD COLUMN IF NOT EXISTS`（幂等）、`LIMIT ?`、`information_schema.tables/.columns`、`DESCRIBE`、`CURRENT_TIMESTAMP` 比较、分析型 SELECT（`CASE/SUM(CASE WHEN LIKE)/COUNT(DISTINCT)/ROUND/中文别名`）、`fetchdf()`、normalize_prices 的 f-string UPDATE 变通、只读连接。

## 3. 已落地的风险管控（本次已执行）

1. **数据备份**：`data/backups/cost_prediction.pre_v2_upgrade.<时间戳>.duckdb`（71MB 全量副本）。
2. **依赖快照**：`data/backups/pip_freeze_duckdb1.5.5.<时间戳>.txt`（回滚基线）。
3. **版本 pin 收紧**：4 个 requirements 由危险的 `duckdb>=0.10.0`（无上限）改为 `duckdb>=1.5.6,<2.0`，防止 2.0 GA 后被自动拉进生产镜像：
   - `backend/requirements.txt`
   - `deploy/modelscope/requirements-ms.txt`
   - `.modelscope-deploy/requirements-ms.txt`
   - `.modelscope-deploy/backend/requirements.txt`
4. **start.bat 非破坏化**：完整性检查的"确认删除"分支由 `del` 改为 `ren` 到 `cost_prediction.corrupt-<随机>.duckdb`，任何情况下库文件都可恢复。
5. **迁移/校验工具**：`backend/scripts/migrate_duckdb_v2.py`（备份→快照→可选 CHECKPOINT→复核→回滚提示，退出码可判定）。
6. **schema 补全**：`backend/scripts/init_duckdb.py` 新增 `CREATE TABLE IF NOT EXISTS prediction_uploads`（main.py 的上传生命周期一直在用但从未建表；此为**与 2.0 无关的既存缺陷**，1.5.5 下同样缺失，顺手修复）。

## 4. 数据迁移说明

- **无需格式转换**。实测 2.0 打开/写入现有库不会升级存储格式，文件保持 `v1.5.5` 且对 1.5.x 可读。因此"数据迁移"= **校验 + CHECKPOINT + 备份**，而不是重写文件。
- 迁移命令（在 2.0 环境下）：
  ```bash
  # 只读校验（默认，仍会先备份）
  python backend/scripts/migrate_duckdb_v2.py --mode verify
  # 校验 + 通过 2.x 引擎做一次 CHECKPOINT 写入
  python backend/scripts/migrate_duckdb_v2.py --mode checkpoint
  ```
- 脚本会逐表比对迁移前后的行数与列签名，任一不一致即以非零码退出并给出回滚提示。

## 5. 正式切换门控（Cutover — 需人工确认，逐步执行）

> 触发条件建议：**2.0 稳定版（非 dev）发布** 后再执行；若需在 staging 提前验证，可用 nightly。

1. 确认已存在 §3.1 的库备份（或重新备份）。
2. 安装目标版本到运行环境：`python -m pip install "duckdb==2.0.<稳定版>"`（staging 可用 `--pre "duckdb==2.0.0.dev2610011535"`）。
3. 跑迁移校验：`python backend/scripts/migrate_duckdb_v2.py --mode verify`，通过后再 `--mode checkpoint`。
4. 跑接口审计（见 §6）。
5. 把 4 个 requirements 的 pin 从 `>=1.5.6,<2.0` 改为 `==2.0.<稳定版>`。
6. 重建镜像：`docker-compose build` / ModelScope 部署构建；确认镜像内 `python -c "import duckdb;print(duckdb.__version__)"` 为 2.0。
7. 冒烟：启动后端，验证上传/预测/训练数据读取路径。
8. 如需在生产库物化 `prediction_uploads`：运行 `python backend/scripts/init_duckdb.py`（幂等，只建缺失表，不动现有数据）。

## 6. 接口审计复跑方法

审计脚本已固化为正式工具 `backend/scripts/duckdb2_compat_audit.py`（退出码：全 PASS=0，有 FAIL=1）。在两个环境各跑一次并逐行对比：
```bash
# 基线：当前 1.5.x 环境
python backend/scripts/duckdb2_compat_audit.py data/cost_prediction.duckdb
# 目标：装好 DuckDB 2.x 的环境（GA 后 pip install "duckdb==2.0.<stable>"）
python backend/scripts/duckdb2_compat_audit.py data/cost_prediction.duckdb
```
本次 nightly 实测两版 **15/15 完全一致**。该脚本已接入 CI（见 §10）：`.github/workflows/ci.yml` 新增 "DuckDB compatibility audit" 步骤，对真实安装的 duckdb（pin `<2.0`）跑通全部构造，退出码非零即失败。注意 `backend/tests/conftest.py` 仍**全量 mock 掉 duckdb**，因此真实回归由独立的 `backend/tests_integration/`（非 mock）+ 本审计脚本共同把关。

## 7. 回滚

- **默认情形（未使用 v2 独有特性）**：库文件仍是 `v1.5.5` 兼容格式 → 只需 `python -m pip install "duckdb==1.5.6"` 降级即可，**无需还原数据文件**。
- **极端情形（存储格式已被抬到 v2.0.0）**：用 §3.1 备份覆盖 `data/cost_prediction.duckdb`，再降级到 1.5.x。
- requirements 回滚：`git revert` 对应提交，或把 pin 改回 `>=1.5.6,<2.0`。

## 8. 注意事项 / 禁止项

- **不要**在生产镜像里使用 nightly（dev）构建；仅 staging 验证可用。CI 严禁使用 `pip --pre`（否则 2.0 GA 前会拉到 dev 预发布版）。
- **不要**在准备好接受单向门之前，把任何列改成 2.0 独有存储特性（会关闭 1.5.x 回滚路径）。
- **不要**在任何环境仍为 1.5.x 时，用 2.0 重建/新建生产库（`init_duckdb.py` 从零建库、`start.bat` 删库重建、`migrate_duckdb_v2.py --mode checkpoint` 都要守住这条）——新建库令牌会是 `v2.0.0`，1.5.x 打不开。发布前跑 §9 的令牌护栏。
- ~~现有测试完全 mock 掉 duckdb，捕获不到 2.0 回归~~ → 已补 `backend/tests_integration/`（真实引擎，非 mock）并接入 CI，见 §10。
- ~~`to_dataframe` 对 `above_ground_floors/...` 的引用会命中 binder 错误~~ → 已由 H2 在 `init_duckdb.py` 补齐这些列消除，见 §10。

## 9. 网络文章坑点复核结论（对本文项目实测）

针对 https://www.shengyayun.com/blog/tech-implementation-2026-08-18/ 所述 2.0 坑点，用 `backend/scripts/duckdb2_pitfall_check.py` 在 1.5.5 与 2.0 nightly 下对跑（除版本号/新建库令牌/`SELECT FOR UPDATE` 报错文案外，输出逐字节相同）：

| 文章坑点 | 实测判定 | 依据 |
|---|---|---|
| C1 存储单向门 | **部分成立**：仅对**新建/重建**库 | 新建库令牌 1.5.5=`v1.5.5`、2.0=`v2.0.0`；1.5.5 打不开 v2.0.0 库。但**已有生产库被 2.0 写入后令牌仍 v1.5.5**，可回滚 |
| C2 VARIANT 需显式 cast / 2.0 独有 | **不成立** | 两版一致：建表、字面量/参数/`::cast` 插入、`v->'$.a'`、`typeof=VARIANT` 全通过 |
| C3 行锁 / SERIALIZABLE 缺失 | **成立但非新增** | `SELECT FOR UPDATE`、`SERIALIZABLE` 在 1.5.5 与 2.0 **都**报错（DuckDB 单写者固有特性） |
| C6 i18n / 日期静默差异 | **本 nightly 不成立** | ICU 两版均 installed+loaded；CJK 排序、`NOCASE`、ISO 周、`date_trunc`、闰日校验、`CURRENT_TIMESTAMP` 类型全部一致 |
| C7 扩展未捆绑 | **核心不成立** | icu/json/parquet 两版均 installed+loaded |
| C4 打包被 `--pre` 拉到 dev | **成立，已防护** | PyPI 稳定版最新 1.5.6；requirements pin `<2.0`；CI 无 `--pre` |

**发布前存储令牌护栏（N1）**：`python backend/scripts/check_db_storage_token.py [db]`（默认查 `data/cost_prediction.duckdb`）。读取文件头存储令牌并与运行时 duckdb 主版本比对：库为 v2.x 而运行时 <2.0 → 退出码 2（单向门，打不开）；一致 → 0。打包 ModelScope（经 Git LFS 分发 .duckdb）或发布前运行。

## 10. 本次落地的修复（H1–H7 / N1–N2）

| 编号 | 问题 | 落地改动 | 验证 |
|---|---|---|---|
| H1 | `prediction_uploads` 表被 main.py 使用却从未建表 | `init_duckdb.py` 增 `CREATE TABLE IF NOT EXISTS prediction_uploads` | 集成测试 `test_init_creates_prediction_uploads_and_meta_columns` |
| H2 | `data_loader._load_duckdb_dataframe` 直接 SELECT `above_ground_floors/under_ground_floors/decoration_standard/foundation_type`，缺列触发 binder error 被静默吞掉 | `init_duckdb.py` 在 CREATE 与幂等 ALTER 块补齐 4 列 | 集成测试 `test_load_duckdb_dataframe_no_binder_error` |
| H3 | 测试全量 mock duckdb，无法防真实回归 | 新增 `backend/tests_integration/`（真实引擎，独立 conftest 去 mock）；CI 增 "DuckDB integration tests" + "compatibility audit" 两步 | 6 项集成测试在 1.5.5 全通过 |
| H4 | `normalize_prices.py` 用 f-string 拼 UPDATE/SELECT（多余规避 + 注入面） | 全部改绑定参数（`?`），实测 1.5.x/2.x 的 UPDATE SET 均支持 | 集成测试 `test_normalize_prices_bound_params` / `_no_year_factor_one` |
| H5 | main.py 每请求新建读写连接，DuckDB 单写者下并发写有冲突面 | 写操作经 `data_loader` 统一持模块级 `_DB_WRITE_LOCK` 串行化；读路径用 `read_only=True` | 集成测试 `test_prediction_uploads_lifecycle_via_data_loader` |
| H6 | `data/backups/`（71MB 库副本）、`_duckdb2_tmp/` 未忽略 | `.gitignore` 增 `data/backups/`、`_duckdb2_tmp/` | `git status` 不再列出 |
| H7 | 架构漂移：main.py 直连 duckdb，偏离 AGENTS.md "所有读写经 data_loader.py" | prediction_uploads 生命周期（record/get/list_expired/list_active/delete）全部下沉到 `DataLoader`；main.py 不再 `import duckdb` | `import main` 真实依赖下通过；grep 确认 main.py 无 `duckdb.connect` |
| N1 | 存储单向门（仅新建/重建库） | 令牌护栏脚本 `check_db_storage_token.py` + §8/§9 禁止项 + pin `<2.0` | 对生产库运行退出码 0（v1.5.5 一致） |
| N2 | 打包被 `--pre` 拉到 dev / GA 后自动升级 | requirements pin `>=1.5.6,<2.0`；CI 无 `--pre`；compat audit 作为 CI 门禁 | CI 步骤已加 |

> 切换正式 2.0 时（§5），把 pin 改为精确 `==2.0.<稳定版>`，并在合并前重跑 §6 审计与 §9 令牌护栏。
