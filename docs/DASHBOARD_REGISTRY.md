# Dashboard Registry

> 所有 dashboard 模块的注册表 · 维护者：Ray
> 新增 dashboard 必须先在此登记 → 再开发 → 最后更新

---

## 当前注册的 Dashboard

| ID | 名称 | 路径 | 状态 | 数据源 | 更新频率 | 创建日期 |
|----|------|------|------|--------|----------|----------|
| `lcm` | LCM Memory | `/lcm/` | 🚧 Phase 1 | `~/.openclaw/lcm.db` | 每日 02:00 | 2026-06-24 |

---

## Dashboard 命名规范

- **目录名**：小写、连字符分隔（如 `lcm`, `homelab`, `network`）
- **数据子目录**：`/data/latest.json` + `/data/history/YYYY-MM-DD.json`
- **文档子目录**：`/docs/{DESIGN,DATA_SCHEMA,SECURITY}.md`

---

## 登记流程（强制）

新增 dashboard 必须完成以下步骤：

### 1. 在本文件添加记录

```markdown
| `your-id` | 名称 | `/your-id/` | 📋 规划中 | 数据源 | 频率 | 日期 |
```

### 2. 创建目录骨架

```bash
mkdir -p your-id/{assets/{css,js},data/history,docs}
```

### 3. 编写三份规格文档

- `your-id/docs/DESIGN.md`（视觉规范）
- `your-id/docs/DATA_SCHEMA.md`（数据 schema）
- `your-id/docs/SECURITY.md`（脱敏 + 审计策略）

### 4. 编写数据导出脚本规格

- `scripts/exporter-{your-id}-spec.md`（不写代码）
- 由秃头虾落地 Python 脚本

### 5. 编写 dashboard HTML

- 复用 [`DESIGN_TOKENS.md`](./DESIGN_TOKENS.md)
- 单文件 `index.html` < 50KB

### 6. 接入 cron 任务

- 由小虾米 + 极客虾协调
- 复用 LCM cron 模板（export → git push）

---

## 状态说明

| 状态 | 含义 |
|------|------|
| 📋 规划中 | 仅目录 + 规格文档，无实际数据 |
| 🚧 开发中 | exporter 脚本或 HTML 在开发 |
| ✅ 运行中 | 每日自动更新，dashboard 可视化 |
| ⚠️ 维护中 | 有已知问题，部分功能异常 |
| ⏸️ 暂停 | 暂时停止更新 |

---

## 全局约束

| 约束 | 说明 |
|------|------|
| **仓库状态** | public（GitHub Pages Free 要求） |
| **数据脱敏** | 仅聚合统计，**永不导出** message.content / summary.content / 完整 session_key |
| **凭据** | 仓库内零凭据（凭据在 OpenClaw 本地的 secrets.json） |
| **依赖** | 仅 CDN（Chart.js + Google Fonts），无 npm 依赖 |
| **体积** | 单 dashboard < 200KB（不含数据） |
| **更新频率** | 最低每日一次，避免频繁 git push |

---

> 最后更新：2026-06-24 · 维护者：Ray