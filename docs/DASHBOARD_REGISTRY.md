# Dashboard Registry

> Dashboard 模块注册表 · 维护者：Ray
> 新增 dashboard 必须先在此登记 → 再开发 → 最后更新状态

---

## 📋 当前注册的 Dashboard

| ID | 名称 | 路径 | 状态 | 数据源 | Cron |
|----|------|------|------|--------|------|
| `lcm` | LCM Memory | `/docs/lcm/` | ✅ 运行中 | `~/.openclaw/lcm.db` | 每日 02:00 |
| `homelab` | Homelab | `/docs/homelab/` | 📋 规划中 | — | — |
| `network` | Network | `/docs/network/` | 📋 规划中 | — | — |

**公开 URL**：`https://yrwd999.github.io/private-dashboard/docs/{id}/`

---

## 📂 Dashboard 目录规范

每个 dashboard 必须遵循以下目录结构：

```
docs/{id}/                    ← GitHub Pages 路径（/{id}/ 出现在 URL 中）
├── index.html                ← Dashboard 入口（必填）
├── assets/
│   ├── css/dashboard.css      ← 样式（必须继承 DESIGN_TOKENS.md）
│   └── js/dashboard.js       ← 图表逻辑
├── data/                     ← 由 cron exporter 自动写入（无需人工维护）
│   ├── latest.json          ← 每日覆盖
│   └── history/             ← 30 天滚动
│       └── YYYY-MM-DD.json
└── docs/                   ← 规格文档（仪表盘专属）
    ├── DESIGN.md            ← 视觉规范
    ├── DATA_SCHEMA.md       ← JSON schema
    └── SECURITY.md         ← 脱敏策略
```

**命名规范：**
- ID：`[a-z][a-z0-9-]{1,19}`（小写字母开头，可含数字和连字符）
- CSS 类：`.db-{id}-*`（前缀避免冲突）
- JS 全局变量：`Dashboard{id}`（PascalCase）

---

## 🚀 接入流程

### Phase 1：规划与登记
- [ ] 在本文件添加记录（状态：`📋 规划中`）
- [ ] 创建 `docs/{id}/` 目录骨架
- [ ] 编写 `docs/{id}/docs/DESIGN.md`（视觉规范）
- [ ] 编写 `docs/{id}/docs/DATA_SCHEMA.md`（数据 schema）
- [ ] 编写 `docs/{id}/docs/SECURITY.md`（脱敏策略）

### Phase 2：Exporter 脚本
- [ ] 编写 `scripts/exporter-{id}-spec.md`（只写规格，**不写代码**）
- [ ] 实现 `scripts/exporter_{id}.py`（遵循规格）
- [ ] 运行 dry-run 验证：`python3 scripts/exporter_{id}.py --dry-run`

### Phase 3：Dashboard 前端
- [ ] 实现 `docs/{id}/index.html`（复用 `DESIGN_TOKENS.md`）
- [ ] 实现 `docs/{id}/assets/css/dashboard.css`
- [ ] 实现 `docs/{id}/assets/js/dashboard.js`
- [ ] 本地验证（`python3 -m http.server 8000 --directory /mnt/github/private-dashboard`）

### Phase 4：Cron 任务
- [ ] 创建 cron 任务（参考 README.md 中的 cron payload 模板）
- [ ] 验证每日自动更新
- [ ] 确认 failureAlert 生效（故意制造一次失败）

### Phase 5：上线
- [ ] 本文件更新状态为 `✅ 运行中`
- [ ] GitHub Pages 已激活（Settings → Pages → Source: main branch, /docs）
- [ ] 确认 URL 可访问

---

## 🔒 全局安全约束

| 约束 | 说明 |
|------|------|
| **禁止导出** | message.content、summary.content、完整 session_key、token、password、UUID 明文 |
| **session_key** | 仅保留 `agent:*` 前缀（不含后缀 ID） |
| **数据范围** | 仅聚合统计（计数、分布、时间趋势） |
| **零凭据** | 仓库内无任何 credential、token、key |
| **数据脱敏** | 在 exporter 脚本层完成，dashboard 层无感知 |

---

## 🏗️ 架构说明

本仓库采用 **Monorepo（Strategy A）**：
- GitHub Pages source = `/docs/`（唯一 Pages site）
- 多个 dashboard 共存于 `docs/` 子目录
- 每个 dashboard 有独立 cron schedule、独立数据目录
- 全局设计规范（DESIGN_TOKENS.md）所有 dashboard 共享

详见根目录 `README.md`（内部工程规范）。

---

## 状态说明

| 状态 | 含义 |
|------|------|
| 📋 规划中 | 仅目录 + 规格文档，无实际数据 |
| 🚧 开发中 | Exporter 脚本或 HTML 在开发 |
| ✅ 运行中 | 每日自动更新，dashboard 可视化 |
| ⚠️ 维护中 | 有已知问题，部分功能异常 |
| ⏸️ 暂停 | 暂时停止更新 |

---

> 最后更新：2026-06-24 · 维护者：Ray
