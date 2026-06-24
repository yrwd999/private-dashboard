# exporter.py · 规格文档（不写代码）

> LCM 数据导出脚本规格 · Phase 2 由秃头虾落地
> 最后更新：2026-06-24 · 起草：小虾米 · 实施：秃头虾

---

## 🎯 目标

从 `~/.openclaw/lcm.db` 导出**脱敏聚合数据**到 `lcm/data/latest.json` + `lcm/data/history/YYYY-MM-DD.json`

---

## 📦 输入

| 项 | 值 |
|---|---|
| SQLite 路径 | `~/.openclaw/lcm.db` |
| 连接模式 | `mode=ro`（**只读**） |
| WAL 路径 | `~/.openclaw/lcm.db-wal`（用于 wal_size_mb） |
| 输出目录 | `<repo>/lcm/data/` |

---

## 📤 输出

### 1. `lcm/data/latest.json`（覆盖式）

格式严格遵循 [`../lcm/docs/DATA_SCHEMA.md`](../lcm/docs/DATA_SCHEMA.md) v1.0

### 2. `lcm/data/history/YYYY-MM-DD.json`（新建）

内容与 latest.json 完全相同（用于 30 天趋势）

### 3. 控制台输出（供 cron 捕获）

```json
{
  "executed_at": "2026-06-24T02:00:00+08:00",
  "task": "lcm-daily-snapshot",
  "operation": "export",
  "source": "~/.openclaw/lcm.db",
  "output": ["lcm/data/2026-06-24.json", "lcm/data/latest.json"],
  "size_before_mb": 442.4,
  "size_after_mb": 438.2,
  "result": "success",
  "duration_ms": 1234
}
```

---

## 🔧 函数签名（建议）

```python
def export_lcm_data(
    db_path: str = "~/.openclaw/lcm.db",
    output_dir: str = "./lcm/data",
    history: bool = True,
    verbose: bool = False,
) -> ExportResult:
    """导出 LCM 数据到 JSON 文件
    
    Returns:
        ExportResult: {
            success: bool,
            output_files: List[str],
            duration_ms: int,
            records: {...},
            errors: List[str],
        }
    """
```

---

## 📊 SQL 查询清单（白名单 SELECT）

### overview

```sql
SELECT 
  (SELECT COUNT(*) FROM conversations) AS total_conversations,
  (SELECT COUNT(*) FROM conversations WHERE active=1) AS active_conversations,
  (SELECT COUNT(*) FROM conversations WHERE active=0) AS archived_conversations,
  (SELECT COUNT(*) FROM messages) AS total_messages,
  (SELECT COUNT(*) FROM summaries) AS total_summaries,
  (SELECT COUNT(*) FROM summaries WHERE kind='leaf') AS leaf_summaries,
  (SELECT COUNT(*) FROM summaries WHERE kind='condensed') AS condensed_summaries;
```

### agent_distribution

```sql
SELECT 
  CASE 
    WHEN instr(session_key, ':') > 0 
    THEN substr(session_key, 7, instr(substr(session_key, 7), ':') - 1)
    ELSE 'unknown'
  END AS agent_role,
  SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active,
  SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) AS archived,
  (SELECT COUNT(*) FROM messages m WHERE m.conversation_id IN 
    (SELECT conversation_id FROM conversations WHERE session_key LIKE 'agent:' || agent_role || ':%')) AS messages
FROM conversations
WHERE session_key LIKE 'agent:%'
GROUP BY agent_role
ORDER BY messages DESC;
```

### session_key_patterns（脱敏聚合）

**禁用**：导出完整 session_key
**允许**：仅导出 `LIKE 'pattern%'` 的 COUNT

```sql
-- 仅聚合模式，不导出 session_key 本身
SELECT 
  'agent:*:dashboard:*' AS pattern,
  COUNT(*) AS count,
  SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active
FROM conversations 
WHERE session_key LIKE 'agent:%:dashboard:%'
UNION ALL
SELECT 'agent:*:main', COUNT(*), SUM(CASE WHEN active=1 THEN 1 ELSE 0 END)
FROM conversations 
WHERE session_key LIKE 'agent:%:main'
  AND session_key NOT LIKE 'agent:%:dashboard:%'
UNION ALL
SELECT 'agent:*:web*', COUNT(*), SUM(CASE WHEN active=1 THEN 1 ELSE 0 END)
FROM conversations 
WHERE session_key LIKE 'agent:%:web%';
```

### message_trend_30d

```sql
SELECT 
  date(created_at) AS date,
  COUNT(*) AS count,
  SUM(token_count) * 4 / 1024 / 1024 AS size_mb  -- 估算
FROM messages
WHERE created_at >= datetime('now', '-30 days')
GROUP BY date(created_at)
ORDER BY date ASC;
```

**⚠️ 关键约束**：
- 仅按 `date(created_at)` 聚合
- **不 SELECT content / large_content**
- `size_mb` 是估算值（`token_count * 4 bytes`），不是精确

### last_archive_days_ago

```sql
SELECT CAST(julianday('now') - julianday(MAX(archived_at)) AS INTEGER) AS days_ago
FROM conversations 
WHERE active=0 AND archived_at IS NOT NULL;
```

---

## 🚫 黑名单（永不 SELECT）

```sql
-- ❌ 永不执行
SELECT content FROM messages;
SELECT large_content FROM messages;
SELECT content FROM summaries;
SELECT session_id FROM conversations;
SELECT session_key FROM conversations;  -- 完整 session_key
SELECT identity_hash FROM messages;
SELECT transcript_entry_id FROM messages;
```

**强校验**：exporter.py 启动时检查 SQL 语句，若发现黑名单字段则**立即终止**。

---

## 🧪 测试用例（必过）

| # | 场景 | 期望 |
|---|------|------|
| 1 | 正常 DB | 输出 latest.json + history |
| 2 | DB 不存在 | 返回 error，不创建文件 |
| 3 | DB 损坏 | 返回 error，错误信息含 path |
| 4 | 输出目录不存在 | 自动创建 |
| 5 | 历史 30 天数据不足 | 补 0 项 |
| 6 | 含 message.content 字段 | 测试失败（防回归） |
| 7 | 含完整 session_key | 测试失败（防回归） |
| 8 | 含 token / secret 字符串 | 测试失败 |

---

## 🛡️ 错误处理

| 错误 | 行为 |
|------|------|
| DB 不存在 | log error + 返回非零 exit code |
| DB 损坏 | log error + 返回非零 exit code |
| 输出目录无写权限 | log error + 返回非零 exit code |
| SQL 错误 | log error + 返回非零 exit code |
| 磁盘满 | log error + 返回非零 exit code |

**永不**：
- 静默失败
- 写入部分文件后失败
- 覆盖未提交的 latest.json（先用 .tmp，再 rename）

---

## ⏱️ 性能预算

| 项 | 阈值 |
|---|------|
| 执行时间 | < 30 秒 |
| 输出文件大小 | < 5MB |
| 内存占用 | < 100MB |

---

## 🔄 cron 接入（Phase 4）

```yaml
name: lcm-daily-snapshot
schedule:
  kind: cron
  expr: "0 2 * * *"
  tz: "Asia/Shanghai"
sessionTarget: isolated
payload:
  kind: agentTurn
  message: |
    执行 LCM Dashboard 数据导出：
    1. cd ~/openclaw/workspace-work/repos/private-dashboard
    2. python3 scripts/exporter_lcm.py --output-dir ./lcm/data
    3. 若成功，git add lcm/data/ && git commit -m "[LCM] auto-update $(date +%Y-%m-%d)" && git push
    4. 若失败，发 Signal 告警
  timeoutSeconds: 180
delivery:
  mode: none  # 静默执行，结果通过 dashboard 可视化
```

---

## 📚 参考资料

- [`../lcm/docs/DATA_SCHEMA.md`](../lcm/docs/DATA_SCHEMA.md) — 数据 schema
- [`../lcm/docs/SECURITY.md`](../lcm/docs/SECURITY.md) — 脱敏策略
- [SQLite Python 文档 — connection isolation](https://docs.python.org/3/library/sqlite3.html)
- [`../../docs/DASHBOARD_REGISTRY.md`](../../docs/DASHBOARD_REGISTRY.md) — 模块清单