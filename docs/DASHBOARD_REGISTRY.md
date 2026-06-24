# Dashboard Registry

> Dashboard 模块注册表 · 维护者：Ray
> 新增 dashboard 必须先在此登记 → 再开发 → 最后更新状态

---

## 📋 当前注册的 Dashboard

| ID | 名称 | 路径 | 状态 | 数据源 | Cron |
|----|------|------|------|--------|------|
| `lcm` | LCM Memory | `/docs/lcm/` | ✅ 运行中 | `~/.openclaw/lcm.db` | 5 个 cron 任务（见下） |
| `memory-tdai` | memory-tdai | `/docs/memory-tdai/` | ✅ 运行中 | `~/.openclaw/memory-tdai/vectors.db` | 2 个 cron（每日 03:00 + 每小时 :30） |
| `homelab` | Homelab | `/docs/homelab/` | 📋 规划中 | — | — |
| `network` | Network | `/docs/network/` | 📋 规划中 | — | — |

**公开 URL**：`https://yrwd999.github.io/private-dashboard/docs/{id}/`

### LCM Dashboard Cron 任务详情

| # | 任务名 | Cron | 脚本 | 产出文件 | 类型 |
|---|--------|------|------|---------|------|
| 1 | `lcm-daily-snapshot` | 每日 02:00 | `scripts/lcm/exporter.py` | `latest.json` + `history/YYYY-MM-DD.json` | 数据导出 |
| 2 | `lcm-wal-health` | 每日 03:00 | `scripts/lcm/wal_health_check.py` | `wal_health.json` | 诊断 |
| 3 | `lcm-doctor-scan` | 每周六 02:00 | `scripts/lcm/doctor_scan.py` | `history/lcm-doctor-YYYY-MM-DD.json` | 只读诊断 |
| 4 | `lcm-web-archive` | 每月 1日 03:00 | `scripts/lcm/web_archive.py` | `history/lcm-web-archive-YYYY-MM-DD.json` | 归档（destructive） |
| 5 | `lcm-backup-cleanup` | 每月 1日 04:00 | `scripts/lcm/backup_cleanup.py` | `history/lcm-backup-cleanup-YYYY-MM-DD.json` | 清理（destructive） |

**阈值配置（环境变量）：**

| 脚本 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `wal_health_check.py` | `WAL_THRESHOLD_RATIO` | `0.10` | WAL/DB > 此值 → warning |
| | `WAL_THRESHOLD_DAILY_GB` | `0.05` | DB 日增长 > 此值 → warning |
| | `WAL_THRESHOLD_ARCHIVE_DAYS` | `7` | 超过此天数无归档 → warning |
| | `WAL_THRESHOLD_MSG_DROP` | `0.80` | 消息量比昨日下跌 > 此比例 → warning |
| | `WAL_SIZE_MB_WARN` | `50` | WAL 绝对大小阈值 MB |
| `web_archive.py` | `WEB_ARCHIVE_THRESHOLD_DAYS` | `3` | 超过此天数未活跃 → 归档候选 |
| `backup_cleanup.py` | `CLEANUP_CUTOFF_DAYS` | `90` | .bak 文件超过此天数 → 删除候选 |
| | `CLEANUP_RECENT_PROTECTION_DAYS` | `30` | 最近 N 天内即使满足也保护 |
| 所有脚本 | `LCM_DB_PATH` | `~/.openclaw/lcm.db` | 数据库路径 |
| | `LCM_REPO_DIR` | `/mnt/github/private-dashboard` | 仓库路径 |

> 路径前缀已更新：所有 LCM 脚本现位于 `scripts/lcm/` 下。
> cron job payload 中的调用路径同步更新为完整路径。

> 在 cron job payload 中通过环境变量注入自定义阈值，例如：
> `WAL_THRESHOLD_RATIO=0.05 python3 scripts/wal_health_check.py`

**Dashboard 7 张卡片数据来源：**

| 卡片 | 数据来源 | 文件 |
|------|---------|------|
| ① 核心指标 | `exporter_lcm.py` → `overview` | `latest.json` |
| ② 30天消息趋势 | `exporter_lcm.py` → `message_trend_30d` | `latest.json` |
| ③ Agent分布 | `exporter_lcm.py` → `agent_distribution` | `latest.json` |
| ④ 会话类型分布 | `exporter_lcm.py` → `session_key_patterns` | `latest.json` |
| ⑤ 备份文件状态 | `exporter_lcm.py` → `backup_status` | `latest.json` |
| ⑥ 健康状态 | `exporter_lcm.py` + `wal_health_check.py` → `health_alerts` | `latest.json` + `wal_health.json`（合并） |
| ⑦ 最近7天记录 | `history/` 目录历史 JSON | 自动读取 |

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
- [ ] 编写 `docs/{id}/docs/exporter-{id}-spec.md`（只写规格，**不写代码**）
- [ ] 实现 `scripts/{id}/exporter.py`（遵循规格，参考 `scripts/lcm/exporter.py`）
- [ ] 运行 dry-run 验证：`python3 scripts/{id}/exporter.py --dry-run --output-dir ./docs/{id}/data`

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
- [x] 本文件更新状态为 `✅ 运行中`（2026-06-24）
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
