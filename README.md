# Private Dashboard

> 私有 dashboard 聚合仓库 · 仅导出**聚合统计数据**，不含任何敏感内容
> 部署：GitHub Pages（Free，公开仓库） · 访问：`https://yrwd999.github.io/private-dashboard/`

## 📋 Dashboard 模块

| 模块 | 路径 | 状态 | 数据源 | 更新频率 |
|------|------|------|--------|----------|
| **LCM Memory** | [`/lcm/`](./lcm/) | 🚧 Phase 1 规划中 | `~/.openclaw/lcm.db` | 每日 02:00 |
| （预留位） | `/homelab/` | — | — | — |
| （预留位） | `/network/` | — | — | — |

## 🎨 设计原则

- **Apple Human Interface** 风格：白底浅灰、SF Pro 字体、大圆角、柔和阴影
- **Chart.js** 图表库（CDN 引入）
- **零外部依赖**：所有 dashboard 仅消费 `data/*.json`，不调用任何 API
- **零凭据**：仓库本身无 token、不连接 HA / OpenClaw / 阿里云

## 🔒 安全护栏

1. **数据脱敏在源头完成**：所有 dashboard 数据由本地脚本导出时已做哈希处理
2. **永不导出 message.content / summary.content**
3. **session_key 仅保留 agent:role 前缀**（如 `agent:main`），不暴露后缀 ID
4. **推送链路审计**：每次 commit 记录 executed_at + 操作人

详见：[`docs/DESIGN_TOKENS.md`](./docs/DESIGN_TOKENS.md) + 各模块的 `SECURITY.md`

## 🛠️ 仓库维护

| 操作 | 命令 |
|------|------|
| 拉取最新 | `git pull origin main` |
| 推送更新 | `git add . && git commit -m "..." && git push` |
| 本地预览 | `python3 -m http.server 8000` → 访问 `http://localhost:8000/` |

## 📅 时间线

- **2026-06-24**：仓库创建 · Phase 1 规格文档落地
- 待定：Phase 2 exporter.py 脚本
- 待定：Phase 3 LCM dashboard HTML
- 待定：Phase 4 cron 任务接入

## 📂 目录结构

```
private-dashboard/
├── README.md                 # 本文件
├── index.html                # 首页（dashboard 导航入口）
├── lcm/                      # LCM Memory Dashboard
│   ├── index.html            # LCM dashboard 主页（待开发）
│   ├── assets/               # 静态资源
│   │   ├── css/
│   │   └── js/
│   ├── data/                 # JSON 数据
│   │   ├── latest.json       # 最新数据（每日覆盖）
│   │   └── history/          # 历史快照（30 天滚动）
│   └── docs/                 # 规格文档
│       ├── DESIGN.md
│       ├── DATA_SCHEMA.md
│       └── SECURITY.md
├── docs/
│   ├── DESIGN_TOKENS.md      # 全局设计 token
│   └── DASHBOARD_REGISTRY.md # dashboard 模块清单
└── .gitignore
```

---

🤖 自动维护（cron 任务）：
- 每日 02:00：exporter.py 生成 `lcm/data/YYYY-MM-DD.json` + 覆盖 `latest.json`
- 每日 02:05：清理 30 天前的 history
- 每日 02:10：git push 到 GitHub（触发 Pages rebuild）