# vX.Y.Z — [版本标题]

> 发布日期: YYYY-MM-DD

## 新增特性 (Features)

### 模块名
- **特性简述**: 一句话描述，说明解决了什么问题、对用户的价值。

## 问题修复 (Bug Fixes)

### 模块名
- **修复简述**: 一句话描述原问题现象和修复方案。

## 改进优化 (Improvements)

### 模块名
- **改进简述**: 非功能性改进（性能、稳定性、用户体验等）。

## 破坏性变更 (Breaking Changes)

> 如果本次发布包含不向后兼容的 API 变更、数据格式变更或配置变更，请在此说明。

- **变更项**: 影响范围 + 迁移指引。

## 贡献者

- @contributor

---

## 使用说明

1. 复制本模板，重命名为 `vX.Y.Z.md`（与 git tag 完全一致）
2. 按实际改动填写各模块内容，删除未使用的分类标题
3. 提交到仓库：`git add release-notes/ && git commit -m "docs: release notes for vX.Y.Z"`
4. 推送 tag 触发自动发布：`git push origin vX.Y.Z`

> GitHub Actions 工作流会优先读取 `release-notes/${{ github.ref_name }}.md`；
> 若该文件不存在，则自动从 git log 生成简要 release notes。
