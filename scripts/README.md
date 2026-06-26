# scripts/ — Dashboard 工具脚本

> 本目录**不在 GitHub Pages 上对外暴露**
> 所有脚本均为私有内部工具

---

## 📁 目录结构

每个 dashboard 对应一个同名子目录：

```
scripts/
├── lcm/           ← LCM Memory Dashboard 工具集
│   ├── exporter.py          ← 主导出器（lcm-daily-snapshot cron 调用）
│   ├── wal_health_check.py  ← WAL 健康检查（lcm-wal-health cron 调用）
│   ├── doctor_scan.py       ← 每周只读诊断（lcm-doctor-scan cron 调用）
│   ├── web_archive.py       ← Web Session 归档（lcm-web-archive cron 调用）
│   ├── backup_cleanup.py    ← 备份文件清理（lcm-backup-cleanup cron 调用）
│   ├── README.md            ← LCM 脚本使用文档
│   └── tests/
│       └── test_exporter.py ← Exporter 单元测试套件
│
├── memory-tdai/   ← memory-tdai Dashboard 工具集
│   ├── exporter.py               ← memory-tdai-daily-export cron 调用
│   ├── fix_missing_embeddings.py ← memory-tdai-hourly-repair cron 调用
│   └── README.md
│
├── security_scan.py     ← 全仓库安全扫描器（必读：每次 commit 前必跑）
└── README.md            ← 本文件
```

---

## 🔑 命名规范

| 类型 | 规则 | 示例 |
|------|------|------|
| 脚本文件名 | `{功能}.py` | `exporter.py`, `wal_health_check.py` |
| 测试文件 | `tests/test_{模块}.py` | `tests/test_exporter.py` |
| Dashboard 目录 | `{id}` | `lcm`, `memory-tdai` |

---

## ⚙️ 脚本通用规范

### 参数规范

所有 exporter 脚本必须支持以下标准参数：

| 参数 | 说明 |
|------|------|
| `--db-path` | 数据库路径（默认从环境或标准位置） |
| `--output-dir` | JSON 输出目录 |
| `--dry-run` | 试运行，不写文件 |
| `--verbose` | 详细日志 |

### 退出码

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 1 | 通用错误 |
| 2 | ConfigError（文件不存在、权限不足） |
| 3 | **SecurityError**（检测到黑名单/token） |
| 4 | DataError（SQL 失败、schema 异常） |

### 安全护栏（所有 exporter 必须实现）

- Read-only SQLite 连接
- 黑名单字段扫描（`content`、`large_content`、`identity_hash`、`transcript_entry_id`、`session_id`）
- Token 模式扫描（`ghp_`、`github_pat_`、`eyJ`、`PRIVATE KEY`）
- 输出前双重校验

---

## 📋 各 Dashboard 脚本详情

### LCM（`scripts/lcm/`）

详见 [`lcm/README.md`](./lcm/README.md)

| 脚本 | Cron 任务 | 频率 |
|------|-----------|------|
| `exporter.py` | `lcm-daily-snapshot` | 每日 02:00 |
| `wal_health_check.py` | `lcm-wal-health` | 每日 03:00 |
| `doctor_scan.py` | `lcm-doctor-scan` | 每周六 02:00 |
| `web_archive.py` | `lcm-web-archive` | 每月 1日 03:00 |
| `backup_cleanup.py` | `lcm-backup-cleanup` | 每月 1日 04:00 |

### memory-tdai（`scripts/memory-tdai/`）

✅ 运行中。详见 [`memory-tdai/README.md`](./memory-tdai/README.md)

| 脚本 | Cron 任务 | 频率 |
|------|-----------|------|
| `exporter.py` | `memory-tdai-daily-snapshot` | 每日 03:00 |
| `fix_missing_embeddings.py` | `memory-tdai-hourly-repair` | 每小时第 30 分 |

---

## 🔒 提交前安全检查（强制）

**每次 commit 前必须执行**，尤其涉及 JSON 数据文件或 Python 脚本时：

```bash
# 方式 1：扫描所有数据文件（推荐）
python3 scripts/security_scan.py

# 方式 2：仅扫描暂存文件
python3 scripts/security_scan.py --staged

# 方式 3：扫描指定文件
python3 scripts/security_scan.py --files docs/lcm/data/latest.json

# CI / 严格模式：发现违规即 exit 1
python3 scripts/security_scan.py --strict
```

**违规类型覆盖**：
- 🔴 CRITICAL：session_key 明文、GitHub/OpenAI Token、message.content 泄漏
- 🟠 HIGH：绝对路径（/home/）、JWT Token、HA Token
- 🟡 MEDIUM：手机号、邮箱、内网 IP

**严格模式失败** → 必须修复后再 commit。详见 [`../SECURITY.md`](../SECURITY.md)。

---

## 🔧 本地测试

```bash
# 验证语法
python3 -m py_compile scripts/lcm/exporter.py

# Dry-run（不触碰真实数据）
python3 scripts/lcm/exporter.py --dry-run --output-dir /tmp/lcm-test/

# 完整 exporter 测试套件
python3 scripts/lcm/tests/test_exporter.py
```

---

## 📌 添加新脚本到已有 Dashboard

1. 将脚本放入 `scripts/{id}/`
2. 在对应 cron job 的 `message` 中引用完整路径：`python3 /mnt/github/private-dashboard/scripts/{id}/{script}.py`
3. 如脚本有 cron 任务，更新 `docs/DASHBOARD_REGISTRY.md` 的 cron 任务表
4. 更新 `scripts/{id}/README.md`
5. **提交前**：运行 `python3 scripts/security_scan.py --staged` 确认无违规

---

## 🛡️ 安全规范（必读）

所有脚本和 JSON 输出文件必须遵循：

| 规则 | 说明 | 违规级别 |
|------|------|---------|
| 禁止绝对路径 | JSON 中路径必须用 `~` 或相对路径 | HIGH |
| 禁止 session_key 明文 | 必须用 `sha256:xxx` 前缀 | CRITICAL |
| 禁止 message.content | 禁止导出任何对话内容 | CRITICAL |
| 禁止 API Token | `ghp_`、`sk-`、`eyJ` 等 | CRITICAL |
| 禁止 PII | 手机号、邮箱、身份证 | MEDIUM |

完整规范 → [`../SECURITY.md`](../SECURITY.md)

---

> 最后更新：2026-06-24 · 维护：Ray
