# Scripts · exporter_lcm

> LCM (Lossless-Claw Memory) 数据导出工具
> 用途：从本地 SQLite 导出**脱敏聚合数据**到 JSON，供 dashboard 可视化

---

## ⚠️ 安全护栏（硬约束）

**永不执行**：
- `SELECT content / large_content` （message 原始内容）
- `SELECT content` （summary 摘要内容）
- 导出完整 `session_key`（仅按 pattern 聚合）
- 写入源 DB（仅 mode=ro 连接）

**输出前双重校验**：
1. 扫描黑名单字段名（content / large_content / identity_hash / transcript_entry_id / session_id）
2. 扫描疑似 token 模式（ghp_ / github_pat_ / eyJ / PRIVATE KEY）

详见：[`../lcm/docs/SECURITY.md`](../lcm/docs/SECURITY.md)

---

## 🚀 快速开始

### 命令行

```bash
# 默认（导出到 ./lcm/data）
python3 scripts/exporter_lcm.py --output-dir ./lcm/data

# Dry-run（不写文件）
python3 scripts/exporter_lcm.py --output-dir ./lcm/data --dry-run

# 自定义 DB 路径
python3 scripts/exporter_lcm.py \
  --db-path ~/.openclaw/lcm.db \
  --output-dir ./lcm/data

# 不写 history（仅 latest.json）
python3 scripts/exporter_lcm.py --output-dir ./lcm/data --no-history

# 详细输出
python3 scripts/exporter_lcm.py --output-dir ./lcm/data --verbose
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--db-path` | `~/.openclaw/lcm.db` | LCM SQLite 路径 |
| `--output-dir` | （必填） | JSON 输出目录 |
| `--backup-dir` | `~/.openclaw` | LCM 备份所在目录 |
| `--no-history` | False | 不写 `history/YYYY-MM-DD.json` |
| `--dry-run` | False | 试运行（仅打印） |
| `--verbose` | False | 详细日志 |

### 退出码

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 1 | 通用错误 |
| 2 | ConfigError（DB 不存在、目录无权限） |
| 3 | **SecurityError**（检测到黑名单/token） |
| 4 | DataError（SQL 失败、字段异常） |

---

## 📤 输出示例

### `data/latest.json`

```json
{
  "meta": {
    "generated_at": "2026-06-24T02:00:00+08:00",
    "lcm_db_size_mb": 438.2,
    "lcm_db_path_hash": "sha256:abc123...",
    "schema_version": "1.0"
  },
  "overview": {
    "total_conversations": 92,
    "active_conversations": 40,
    "archived_conversations": 52,
    "total_messages": 41210,
    "total_summaries": 763,
    "leaf_summaries": 735,
    "condensed_summaries": 27,
    "storage_size_mb": 438.2,
    "last_archive_days_ago": 0,
    "wal_size_mb": 0
  },
  "agent_distribution": [
    {"agent": "main", "active": 18, "archived": 12, "messages": 12450}
  ],
  "session_key_patterns": [
    {"pattern": "agent:*:dashboard:*", "count": 35, "active": 28}
  ],
  "message_trend_30d": [
    {"date": "2026-06-24", "count": 1480, "size_mb": 15.2}
  ],
  "backup_status": {
    "total_size_mb": 438.0,
    "files": [
      {"name": "rotate-latest.bak", "size_mb": 438.0, "age_days": 0, "keep": true}
    ]
  },
  "health_alerts": [
    {"level": "info", "code": "WAL_OK", "message": "WAL 文件大小正常 (0 MB)", "timestamp": "..."}
  ]
}
```

### stdout（供 cron 捕获）

```json
{
  "executed_at": "2026-06-24T02:00:00+08:00",
  "task": "lcm-daily-snapshot",
  "operation": "export",
  "source": "/home/yrwd999/.openclaw/lcm.db",
  "output": [".../lcm/data/latest.json", ".../lcm/data/history/2026-06-24.json"],
  "result": "success",
  "duration_ms": 1234,
  "records": {
    "conversations": 92,
    "active": 40,
    "archived": 52,
    "messages_sampled": 0,
    "summaries_sampled": 0
  }
}
```

---

## 🧪 测试

### 运行所有测试

```bash
# 方式 1：纯 Python（无需 pytest）
python3 scripts/tests/test_exporter_lcm.py

# 方式 2：pytest
python3 -m pytest scripts/tests/test_exporter_lcm.py -v
```

### 测试覆盖

| # | 测试 | 场景 |
|---|------|------|
| 1 | `test_sha256_prefix` | 路径哈希稳定 |
| 2 | `test_scan_for_secrets_clean` | 干净文本无 token |
| 3 | `test_scan_for_secrets_github_pat` | 检测到 GitHub PAT |
| 4 | `test_scan_for_forbidden_fields_clean` | 无黑名单字段 |
| 5 | `test_scan_for_forbidden_fields_top_level` | 顶层 content 拦截 |
| 6 | `test_scan_for_forbidden_fields_nested` | 嵌套 content 拦截 |
| 7 | `test_size_mb_missing` | 不存在文件返回 0 |
| 8 | `test_now_iso_format` | ISO 8601 时间戳 |
| 9 | `test_query_overview_basic` | overview 聚合正确 |
| 10 | `test_query_agent_distribution_basic` | agent 分布正确 |
| 11 | `test_query_session_key_patterns_no_full_key` | 关键：完整 session_key 不导出 |
| 12 | `test_validate_output_clean` | 干净数据通过 |
| 13 | `test_validate_output_blocks_content` | content 字段被拦截 |
| 14 | `test_validate_output_blocks_token` | token 模式被拦截 |
| 15 | `test_validate_output_blocks_wrong_schema` | schema_version 错误拦截 |
| 16 | `test_cli_dry_run_on_real_db` | 真实 DB dry-run |
| 17 | `test_cli_real_run_creates_files` | 完整流程创建文件 |
| 18 | `test_cli_handles_missing_db` | DB 不存在优雅失败 |

---

## 🔧 故障排查

### "SecurityError: 检测到黑名单字段"

**原因**：输出 JSON 中包含敏感字段名（如 content、session_id）
**解决**：
1. 检查 SQL 是否 SELECT 了黑名单字段
2. 检查输入数据是否被污染
3. **不要**修改 `FORBIDDEN_FIELD_NAMES`，那是硬约束

### "无法打开 DB（只读模式）"

**原因**：
- DB 文件不存在（路径错误）
- DB 正在被 OpenClaw 写入（WAL 锁竞争）
- 权限不足

**解决**：
```bash
ls -la ~/.openclaw/lcm.db
sqlite3 ~/.openclaw/lcm.db "PRAGMA wal_checkpoint(FULL);"
```

### "WAL 文件偏大"

**原因**：OpenClaw 写入后未及时 checkpoint
**解决**：手动执行 `sqlite3 ~/.openclaw/lcm.db "PRAGMA wal_checkpoint(TRUNCATE);"`

---

## 📚 相关文档

- [`./exporter-lcm-spec.md`](./exporter-lcm-spec.md) — 脚本规格（详细 SQL + 测试规范）
- [`../lcm/docs/DATA_SCHEMA.md`](../lcm/docs/DATA_SCHEMA.md) — JSON 字段定义
- [`../lcm/docs/SECURITY.md`](../lcm/docs/SECURITY.md) — 脱敏策略

---

> 最后更新：2026-06-24 · 实施：小虾米 · 维护：Ray