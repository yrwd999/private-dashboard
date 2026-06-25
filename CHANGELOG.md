# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `LICENSE` — MIT License
- `.editorconfig` — 跨编辑器代码风格配置
- `.github/workflows/ci.yaml` — Python lint (ruff + black) + 测试 + 安全扫描 + JS 语法检查
- `.github/ISSUE_TEMPLATE/` — Bug Report 和 Feature Request 模板
- `.github/PULL_REQUEST_TEMPLATE.md` — PR 模板
- `CONTRIBUTING.md` — 项目贡献规范（分支策略 / commit 格式 / 安全约束 / 测试规范）
- **审计评分**：36% → 100% (19/19)

---

## [v1.0.0] — 2026-06-24

### Added

#### LCM Dashboard（2026-06-22 ~ 2026-06-24）
- `docs/lcm/` — LCM Memory Dashboard 前端（HTML + CSS + JS + Chart.js）
- `docs/lcm/docs/DESIGN.md` — 视觉规范
- `docs/lcm/docs/DATA_SCHEMA.md` — JSON 数据 schema
- `docs/lcm/docs/SECURITY.md` — LCM 专项脱敏策略
- `docs/lcm/docs/exporter-lcm-spec.md` — Exporter 规格文档
- `scripts/lcm/exporter.py` — LCM 数据导出器（7 张卡片）
- `scripts/lcm/wal_health_check.py` — WAL 健康诊断
- `scripts/lcm/doctor_scan.py` — 全量只读诊断扫描
- `scripts/lcm/web_archive.py` — 长期未活跃会话归档
- `scripts/lcm/backup_cleanup.py` — .bak 文件清理
- `scripts/lcm/tests/test_exporter.py` — 18 项测试覆盖

#### memory-tdai Dashboard（2026-06-23 ~ 2026-06-24）
- `docs/memory-tdai/` — memory-tdai Dashboard 前端
- `scripts/memory-tdai/exporter.py` — memory-tdai 数据导出器
- `scripts/memory-tdai/fix_missing_embeddings.py` — embedding 修复工具

#### 安全体系（2026-06-23 ~ 2026-06-24）
- `SECURITY.md` — 全仓库通用安全约束（绝对路径 / session_key / token / PII 禁止规则）
- `scripts/security_scan.py` — Commit 前安全扫描器

#### 文档与规范（2026-06-22 ~ 2026-06-24）
- `README.md` — 工程规范总览（架构决策 / Git 工作流 / Cron 调度 / 新增 Dashboard 流程）
- `docs/README.md` — 公开 GitHub Pages 入口页
- `docs/DASHBOARD_REGISTRY.md` — Dashboard 注册表（状态 / Cron 任务 / 阈值配置）
- `docs/DESIGN_TOKENS.md` — 全局设计 Token（Apple HIG 风格）
- `scripts/README.md` — 脚本层说明文档

### Changed
- 重构 `scripts/` 为模块化目录结构（`scripts/lcm/` / `scripts/memory-tdai/`）
- 修复 datetime 处理（timezone-aware ISO 8601）
- 修复 magic numbers（阈值提取为环境变量）
- 修复 Path 处理（相对路径 → 绝对路径）
- 修正 GitHub Pages URL 映射（移除 `/docs/` 前缀）
- 更新 cron 脚本路径为完整路径

### Security
- 建立绝对路径脱敏规范（`/home/yrwd999/` → `~/.openclaw/`）
- 建立 session_key 哈希规范（禁止明文导出）
- 建立 API token / PII 检测规范
- SQLite 连接强制 mode=ro

---

## [v0.1.0] — 2026-06-22

### Added
- 项目初始化（Monorepo 架构决策 + GitHub Pages 部署方案）
- 初期文档骨架

---

> **维护者**：Ray  
> **历史格式说明**：v1.0.0 之前的版本为项目内部里程碑，v1.0.0 = LCM + memory-tdai 双 Dashboard 上线状态。
