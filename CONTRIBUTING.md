# Contributing to Private Dashboard

> 内部工程规范文档 · 适用于所有模块（LCM、memory-tdai 及未来新增）
> 维护者：Ray · 最后更新：2026-06-25

---

## 项目概述

**Private Dashboard** 是一个内部工程规范 + 监控 Dashboard 的混合 monorepo：

- **docs/{id}/** — GitHub Pages 部署的 Dashboard 前端（HTML/CSS/JS + JSON 数据）
- **scripts/{id}/** — Python 数据导出脚本（cron 驱动，写入 docs/{id}/data/）
- **当前 Dashboard**：`lcm`（LCM Memory）、`memory-tdai`
- **部署地址**：`https://yrwd999.github.io/private-dashboard/{id}/`

---

## 开发设置

### 1. 克隆仓库

```bash
git clone https://github.com/yrwd999/private-dashboard.git
cd private-dashboard
```

### 2. Python 环境

```bash
# 推荐 venv
python3 -m venv .venv
source .venv/bin/activate

# 无外部依赖（脚本使用标准库 + sqlite3）
# 如需运行测试：
python3 scripts/lcm/tests/test_exporter.py
```

### 3. 本地预览 Dashboard

```bash
# 在仓库根目录启动静态服务器
python3 -m http.server 8000 --directory /mnt/github/private-dashboard
# 访问 http://localhost:8000/docs/lcm/
```

### 4. 安全扫描（commit 前必跑）

```bash
python3 scripts/security_scan.py
# 扫描覆盖：绝对路径、session_key 明文、API token、PII
# 检查失败 → abort commit
```

---

## 分支规范

| 分支 | 用途 | 示例 |
|------|------|------|
| `main` | 生产分支，所有变更通过 PR 合并 | — |
| `feat/lcm-*` | LCM 模块新功能 | `feat/lcm-add-agent-filter` |
| `feat/memory-tdai-*` | memory-tdai 模块新功能 | `feat/memory-tdai-export-30d` |
| `feat/dashboard-*` | 通用 dashboard 框架 | `feat/dashboard-add-export-health-check` |
| `fix/*` | 修复分支 | `fix/lcm-fix-wal-threshold` |
| `docs/*` | 文档更新 | `docs/update-registry` |

---

## Commit 规范（强制）

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

feat(lcm): add 30-day message trend export
fix(memory-tdai): handle missing vector db gracefully
fix(lcm): correct wal_health threshold unit (MB vs GB)
docs: update DASHBOARD_REGISTRY cron schedule
refactor(dashboard): extract shared chart.js utility
```

**Type 列表：**

| Type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `refactor` | 重构（不影响功能） |
| `perf` | 性能优化 |
| `test` | 测试添加/修复 |
| `ci` | CI/CD 更新 |
| `chore` | 维护性变更（依赖、配置） |

**Scope（模块）：**

| Scope | 含义 |
|-------|------|
| `lcm` | LCM Dashboard 模块 |
| `memory-tdai` | memory-tdai Dashboard 模块 |
| `dashboard` | 通用 dashboard 框架（DESIGN_TOKENS 等） |
| `scripts` | 跨模块脚本（security_scan.py 等） |

---

## 新增 Dashboard 流程

详见 [`docs/DASHBOARD_REGISTRY.md`](docs/DASHBOARD_REGISTRY.md) § 接入流程。

快速检查清单：

- [ ] 在 `docs/DASHBOARD_REGISTRY.md` 添加记录（先登记再开发）
- [ ] 在 `docs/README.md` 添加公开 URL 入口
- [ ] 创建 `docs/{id}/docs/DESIGN.md`、`DATA_SCHEMA.md`、`SECURITY.md`
- [ ] 实现 `scripts/{id}/exporter.py`（遵循 SECURITY.md 约束）
- [ ] 编写 `docs/{id}/docs/exporter-{id}-spec.md`（只写规格，不写代码）
- [ ] 实现 `docs/{id}/index.html`（复用 `docs/DESIGN_TOKENS.md`）
- [ ] Dry-run 验证：`python3 scripts/{id}/exporter.py --dry-run --output-dir ./docs/{id}/data`
- [ ] 跑安全扫描：`python3 scripts/security_scan.py`
- [ ] 更新 `docs/DASHBOARD_REGISTRY.md` 状态为 ✅

---

## Python 脚本规范

### 退出码（强制）

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 1 | 通用错误 |
| 2 | ConfigError（DB 不存在、目录无权限） |
| 3 | **SecurityError**（检测到黑名单/token） |
| 4 | DataError（SQL 失败、字段异常） |

### 安全约束（硬约束）

违反以下任一规则 → **立即停止，退出码 3**

1. **禁止 SELECT content / large_content / summary.content**（消息原始内容）
2. **禁止导出完整 session_key**（仅允许 SHA256 哈希前缀）
3. **禁止出现绝对路径**（`/home/yrwd999/` → `~/.openclaw/`）
4. **禁止包含 API token**（ghp_/sk-/eyJ/ha_ 模式）
5. **禁止包含 PII**（手机号、邮箱、身份证）
6. **SQLite 连接必须使用 mode=ro**

详见：[`SECURITY.md`](SECURITY.md)

### 测试规范

每个 exporter 必须有对应测试文件：

```bash
# 方式 1：纯 Python（无需 pytest）
python3 scripts/lcm/tests/test_exporter.py

# 方式 2：pytest
python3 -m pytest scripts/lcm/tests/test_exporter.py -v
```

测试必须覆盖：
- 安全扫描（黑名单字段、token 检测）
- 路径脱敏（绝对路径 → ~）
- session_key 哈希
- 错误处理（DB 不存在、权限拒绝）
- 输出 schema 验证

---

## JSON 数据文件规范

所有写入 `docs/{id}/data/` 的 JSON 文件：

- **路径字段**：使用 `~/.openclaw/` 而非绝对路径
- **session_key**：仅允许 `sha256:xxxx` 格式
- **禁止字段**：`content`、`large_content`、`summary.content`、`transcript_entry_id`、`identity_hash`
- **meta 必填字段**：`generated_at`（ISO 8601）、`schema_version`

---

## Cron 任务规范

新增 cron 任务时：

- 在 `docs/DASHBOARD_REGISTRY.md` 的 Cron 任务表中登记
- 使用 OpenClaw cron job（`openclaw cron add`）
- 设置 `failureAlert`（连续失败 2 次触发通知）
- 首次部署后**手动触发一次**验证

详见：[`README.md`](README.md) § Cron 任务调度

---

## PR 流程

1. Fork 仓库，创建功能分支
2. 开发 + 测试 + 安全扫描
3. 提交（符合 Conventional Commits）
4. 发起 PR，填写 PR 模板
5. CI 通过后，由维护者合并

---

## 相关文档

- [`README.md`](README.md) — 工程规范总览
- [`SECURITY.md`](SECURITY.md) — 全仓库安全约束
- [`docs/DASHBOARD_REGISTRY.md`](docs/DASHBOARD_REGISTRY.md) — Dashboard 注册表
- [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md) — 全局设计 token
- [`scripts/lcm/README.md`](scripts/lcm/README.md) — LCM Exporter 详细规范
