# Private Dashboard — Engineering Specification
> 内部工程规范文档 · 本文件**不在 GitHub Pages 上对外暴露**
> 部署：GitHub Pages（source: `/docs/`）· Dashboard 访问：`https://yrwd999.github.io/private-dashboard/docs/{id}/`

---

## 📐 架构决策（ADR-001）

### 策略选择：Monorepo（Strategy A）

**背景约束：**
- GitHub Pages Free 版：每个仓库只能有一个 Pages site
- 每个 Pages site 只能选 `main` 分支的 `/` 或 `/docs/` 作为 source
- 所有 dashboard 必须共享同一个 GitHub Pages deployment

**最终选择：**
- 一个仓库 `private-dashboard`，多个 dashboard 共存于 `docs/` 子目录
- GitHub Pages source = `/docs/`（**唯一 Pages site**）
- 未来扩展：新增 dashboard → 在 `docs/` 下建新子目录 → 不影响现有 dashboard

**为什么不选 Multi-repo（Strategy B）：**
- 当前阶段仅 LCM Memory Dashboard，不值得多 repo 维护开销
- 未来如需完全独立版本管理，可将 `docs/lcm/` 拆出为独立 repo
- GitHub Pages 的 URL 结构（`/docs/{name}/`）对单 dashboard 场景足够清晰

### Git 冲突防护策略

多个 cron job 同时 push 到同一个 repo 的防护机制：

| 机制 | 实现方式 | 说明 |
|------|----------|------|
| **时间分片** | 每个 dashboard cron 在不同分钟执行 | 默认错开 30min，如 LCM=02:00, Homelab=02:30 |
| **锁文件** | `scripts/.push-lock/{dashboard-id}.lock` | 持锁执行 git push，锁文件不过期（crash 后下次覆盖） |
| **重试** | cron job failureAlert 不包含 git retry | 失败后下次定时自然重试，不堆积 |
| **目录隔离** | 每个 dashboard 数据在独立子目录 | `docs/{id}/data/` 互不覆盖，git add 仅针对各自目录 |

**git push 原子性保证：**
```
cron_job_exporter → git add docs/{id}/data/ → git commit → git push
                                           ↑ 若 push 失败 → failureAlert 通知
```
不涉及多 dashboard 竞争同一文件的场景（各自数据在各自目录）。

---

## 📂 目录结构

```
private-dashboard/                     ← GitHub Pages source = /docs/
├── README.md                          ← 本文件（内部规范，不在 Pages 上暴露）
├── SPEC.md                            ← 架构设计文档（本文档，副本）
├── CHANGELOG.md                       ← 仓库级变更记录
├── .gitignore
│
├── docs/                              ← ⚠️ GitHub Pages source（从此目录对外服务）
│   │
│   ├── README.md                      ← 公开入口页（GitHub Pages 根 URL）
│   ├── DESIGN_TOKENS.md               ← 全局设计 token（Apple HIG 规范）
│   ├── DASHBOARD_REGISTRY.md          ← Dashboard 模块注册表
│   │
│   ├── lcm/                          ← LCM Memory Dashboard
│   │   ├── index.html                 ← Dashboard 入口（Apple HIG 风格）
│   │   ├── assets/
│   │   │   ├── css/dashboard.css
│   │   │   └── js/dashboard.js
│   │   ├── data/
│   │   │   ├── latest.json            ← 每日覆盖（cron 自动更新）
│   │   │   └── history/               ← 30 天滚动快照
│   │   │       └── YYYY-MM-DD.json
│   │   └── docs/                     ← LCM 专属规格
│   │       ├── DESIGN.md
│   │       ├── DATA_SCHEMA.md
│   │       └── SECURITY.md
│   │
│   ├── homelab/                      ← （预留）Homelab Dashboard
│   │   └── docs/
│   │
│   └── network/                      ← （预留）Network Dashboard
│       └── docs/
│
└── scripts/                           ← 内部工具（不在 GitHub Pages 上）
    ├── exporter_lcm.py               ← LCM 数据导出脚本
    ├── exporter_lcm_spec.md          ← LCM exporter 规格（不写实现代码）
    ├── tests/
    │   └── test_exporter_lcm.py
    └── README.md

```

**URL 映射：**
| 资源 | GitHub Pages URL |
|------|-------------------|
| Dashboard 入口 | `https://yrwd999.github.io/private-dashboard/docs/{id}/` |
| 公开规范文档 | `https://yrwd999.github.io/private-dashboard/docs/{id}/docs/SOMETHING.md` |
| 内部工程文档 | 不对外暴露（无 Pages mapping）|

---

## 🏷️ Dashboard 命名规范

### ID 命名规则

| 规则 | 说明 | 示例 |
|------|------|------|
| 格式 | 小写字母 + 数字 + 连字符 | `lcm`, `homelab`, `network-ops` |
| 长度 | 2~20 字符 | — |
| 唯一性 | 全仓库唯一 | — |
| 语义化 | 与业务 domain 对应 | `lcm`=记忆系统, `homelab`=智能家居 |

### GitHub Pages URL 规则

```
https://yrwd999.github.io/private-dashboard/docs/{id}/
                           ↑ "docs" 是 GitHub Pages source 目录名，固定不变
```

### 文件命名（强制）

```
docs/{id}/index.html              ← 必须有（Dashboard 入口）
docs/{id}/assets/css/dashboard.css
docs/{id}/assets/js/dashboard.js
docs/{id}/data/latest.json       ← cron 自动覆盖
docs/{id}/data/history/          ← cron 自动写入
docs/{id}/docs/DESIGN.md
docs/{id}/docs/DATA_SCHEMA.md
docs/{id}/docs/SECURITY.md
```

---

## 🔧 Git 工作流

### 分支策略

```
main   ← 稳定分支（GitHub Pages 从 main /docs 部署）
        ↑ 仅通过 cron job 和人工 PR 合并
        ↑ 永远不直接在 main 上开发

开发流程（人工）：
  feature/* → PR → review → merge to main

Cron job 流程（自动）：
  main ──push──→ origin/main （触发 Pages rebuild）
```

### Cron Job 提交流程

```bash
# 伪代码：每个 dashboard cron job 的 git 操作
cd /mnt/github/private-dashboard

git fetch origin main
# 若本地 main 落后远程 origin/main，先 pull --rebase
if [[ $(git rev-parse HEAD) != $(git rev-parse origin/main) ]]; then
    git rebase origin/main
fi

# 运行 exporter
python3 scripts/exporter_{id}.py --output-dir docs/{id}/data

# git add 仅针对本 dashboard 的数据目录
git add docs/{id}/data/latest.json docs/{id}/data/history/
git commit -m "[{id}] auto-update $(date +%Y-%m-%d)"
git push origin main
```

### 锁文件机制（防并发）

```bash
LOCK_DIR=".push-locks"
LOCK_FILE="$LOCK_DIR/{id}.lock"

mkdir -p "$LOCK_DIR"
if ln "$LOCK_FILE" "$LOCK_FILE" 2>/dev/null; then
    # 持锁成功，执行 git push
    trap "rm -f '$LOCK_FILE'" EXIT
else
    # 已有锁，退出（下次 cron 自然重试）
    exit 0
fi
```

> 注：ln 原子性保证即使进程 crash，锁文件也会在下下次执行时被覆盖。

---

## ⏰ Cron 任务调度

### 调度原则

1. **时间分片**：相邻 dashboard 至少错开 30 分钟
2. **低峰期执行**：全部安排在 02:00~06:00（北京时间）
3. **isolated session**：每个 cron job 独立 session，不共享上下文
4. **静默执行**：delivery.mode = "none"，异常通过 failureAlert 通知

### 当前任务表

| 任务名 | Dashboard | 执行时间 | 上次状态 |
|--------|-----------|----------|----------|
| `lcm-daily-snapshot` | LCM Memory | 每日 02:00 | ✅ 已创建 |
| （预留） | Homelab | 每日 02:30 | — |
| （预留） | Network | 每日 03:00 | — |

### Cron Payload 模板

```yaml
name: {id}-daily-snapshot
schedule:
  kind: cron
  expr: "{minute} {hour} * * *"   # 例：0 2 = 02:00
  tz: "Asia/Shanghai"
sessionTarget: isolated
payload:
  kind: agentTurn
  message: |
    执行 {id} Dashboard 每日数据导出：

    1. 持锁（防止并发 push）
    2. 运行数据导出：
       python3 /mnt/github/private-dashboard/scripts/exporter_{id}.py \
         --db-path ~/.openclaw/{db_path} \
         --output-dir /mnt/github/private-dashboard/docs/{id}/data
    3. 若成功，提交 Git：
       cd /mnt/github/private-dashboard
       git add docs/{id}/data/latest.json docs/{id}/data/history/
       git commit -m "[{id}] auto-update $(date +%Y-%m-%d)"
       git push origin main
    4. 若失败，静默退出（failureAlert 会通知 Ray）
  timeoutSeconds: 180
delivery:
  mode: none
failureAlert:
  after: 1
  channel: telegram
  to: "8130748132"
  cooldownMs: 3600000
  mode: announce
```

---

## 🚀 新增 Dashboard 流程

### 检查清单（按顺序执行）

- [ ] **1. 在 `docs/DASHBOARD_REGISTRY.md` 添加记录**（先登记，再开发）
- [ ] **2. 创建目录骨架**

```bash
mkdir -p docs/{new-id}/{assets/{css,js},data/history,docs}
```

- [ ] **3. 编写三份规格文档**（在 `docs/{new-id}/docs/` 下）
  - `DESIGN.md`：视觉规范（颜色/字体/布局/交互）
  - `DATA_SCHEMA.md`：导出的 JSON schema
  - `SECURITY.md`：数据脱敏策略、禁止导出的字段列表

- [ ] **4. 编写 exporter 规格**（`scripts/exporter-{new-id}-spec.md`）
  - 只写规格，**不写实现代码**
  - 定义 SQL 查询逻辑、输出字段、安全约束

- [ ] **5. 实现 exporter 脚本**（`scripts/exporter_{new-id}.py`）
  - 遵循规格，可复用 `scripts/exporter_lcm.py` 的模式
  - 通过 `scripts/exporter_{new-id}_spec.md` 验证

- [ ] **6. 编写 Dashboard HTML**（`docs/{new-id}/index.html`）
  - 复用 `docs/DESIGN_TOKENS.md` 全局 token
  - 单文件 < 50KB，仅使用 Chart.js CDN + Google Fonts

- [ ] **7. 本地验证**
  ```bash
  python3 scripts/exporter_{new-id}.py --dry-run
  # 或启动本地 http server
  python3 -m http.server 8000 --directory /mnt/github/private-dashboard
  # 访问 http://localhost:8000/docs/{new-id}/
  ```

- [ ] **8. Commit 并推送**
  ```bash
  git add docs/{new-id}/ scripts/exporter-{new-id}*
  git commit -m "feat({new-id}): initial dashboard scaffold"
  git push origin main
  ```

- [ ] **9. 创建 cron 任务**（参照上方模板）
- [ ] **10. 更新 `docs/DASHBOARD_REGISTRY.md`** 状态为 ✅

---

## 🔒 安全模型

### 数据导出约束（强制）

**禁止导出（全部在 exporter 脚本层拦截）：**
- `message.content` / `summary.content` / `large_content`
- 完整的 `session_key`（允许 agent:*:role 前缀）
- 任何包含 token、key、password 的字段
- 完整的 UUID / entity_id 列表（需 hash 处理）

**允许导出（聚合统计）：**
- conversation / message / summary 计数
- 时间分布（按天/按周/按月）
- 会话类型分布（active / archived / web-*）
- token 消耗聚合值（无明细）
- L0/L1/L2 层级的统计值

### 凭证管理

- **仓库内零凭据**：无 GitHub token、无 HA URL、无 SSH key
- **凭据在 OpenClaw 本地**：`~/.openclaw/secrets.json` 或 env var
- **Exporter 连接数据库**：本地 read-only SQLite，不走网络

### 安全审计

每次 export 在 `latest.json` 中记录：
```json
{
  "executed_at": "ISO-8601",
  "security_scan": {
    "forbidden_fields_blocked": 0,
    "token_patterns_found": 0,
    "large_content_excluded": 0
  }
}
```

---

## 🎨 设计系统

所有 dashboard 必须遵循 `docs/DESIGN_TOKENS.md` 定义的设计规范：

| Token | 值 | 说明 |
|-------|-----|------|
| `--color-bg` | `#FFFFFF` | 背景色 |
| `--color-surface` | `#F5F5F7` | 卡片/面板背景 |
| `--color-primary` | `#007AFF` | Apple Blue |
| `--color-text` | `#1D1D1F` | 主文字 |
| `--color-text-secondary` | `#86868B` | 次要文字 |
| `--radius` | `12px` | 圆角 |
| `--shadow` | `0 2px 12px rgba(0,0,0,0.08)` | 卡片阴影 |
| `--font` | `-apple-system, SF Pro, BlinkMacSystemFont` | 字体栈 |

新增 dashboard 的 CSS **必须继承这些 token**，不允许硬编码颜色值。

---

## 📋 Dashboard 模块注册表

> 详见 [`docs/DASHBOARD_REGISTRY.md`](./docs/DASHBOARD_REGISTRY.md)

| ID | 名称 | 路径 | 状态 | 数据源 | Cron |
|----|------|------|------|--------|------|
| `lcm` | LCM Memory | `/docs/lcm/` | ✅ 运行中 | `~/.openclaw/lcm.db` | 每日 02:00 |
| `homelab` | Homelab | `/docs/homelab/` | 📋 规划中 | — | — |
| `network` | Network | `/docs/network/` | 📋 规划中 | — | — |

---

## 📌 维护记录

| 日期 | 变更 |
|------|------|
| 2026-06-24 | 仓库创建 · LCM Phase 1~4 落地 |
| 2026-06-24 | 确立 Strategy A Monorepo 架构 · 本规范写入 README |
