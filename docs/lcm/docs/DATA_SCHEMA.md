# LCM Dashboard · Data Schema

> `data/latest.json` + `data/history/YYYY-MM-DD.json` 字段定义
> 最后更新：2026-06-24 · 维护者：Ray

---

## 📦 文件清单

| 文件 | 生成方式 | 用途 |
|------|----------|------|
| `data/latest.json` | 每日 02:00 覆盖 | 主页直接 fetch |
| `data/history/YYYY-MM-DD.json` | 每日 02:00 新建 | 30 天历史滚动（趋势图数据源） |

---

## 🧬 Schema v1.0

```typescript
interface LcmData {
  meta: MetaInfo;
  overview: OverviewStats;
  agent_distribution: AgentStat[];
  session_key_patterns: SessionKeyPattern[];
  message_trend_30d: DailyMessageCount[];
  backup_status: BackupStatus;
  health_alerts: HealthAlert[];
}

interface MetaInfo {
  generated_at: string;              // ISO 8601, e.g. "2026-06-24T02:00:00+08:00"
  lcm_db_size_mb: number;            // 438.2
  lcm_db_path_hash: string;          // "sha256:abc123..." (脱敏)
  schema_version: string;            // "1.0"
}

interface OverviewStats {
  total_conversations: number;
  active_conversations: number;
  archived_conversations: number;
  total_messages: number;
  total_summaries: number;
  leaf_summaries: number;
  condensed_summaries: number;
  storage_size_mb: number;
  last_archive_days_ago: number;     // 0 = today, 1 = yesterday
  wal_size_mb: number;               // 0 = healthy
}

interface AgentStat {
  agent: string;                     // "main" | "geek" | "coding" | "netops" | "homelab"
  active: number;
  archived: number;
  messages: number;
}

interface SessionKeyPattern {
  pattern: string;                   // "agent:*:dashboard:*"
  count: number;
  active: number;
  note?: string;                     // 可选备注，如 "全部已归档"
}

interface DailyMessageCount {
  date: string;                      // "2026-06-24"
  count: number;                     // 消息数
  size_mb: number;                   // 当日新增数据大小
}

interface BackupStatus {
  total_size_mb: number;
  files: BackupFile[];
}

interface BackupFile {
  name: string;                      // "rotate-latest.bak"
  size_mb: number;
  age_days: number;                  // 自最后修改起天数
  keep: boolean;                     // 是否保留（true = 永保留）
}

interface HealthAlert {
  level: "info" | "success" | "warning" | "error";
  code: string;                      // "ARCHIVE_DONE" | "WAL_OK" | "BACKUP_OVERSIZE"
  message: string;
  timestamp: string;                 // ISO 8601
}
```

---

## 📊 示例数据

```json
{
  "meta": {
    "generated_at": "2026-06-24T02:00:00+08:00",
    "lcm_db_size_mb": 438.2,
    "lcm_db_path_hash": "sha256:7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a",
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
    { "agent": "main", "active": 18, "archived": 12, "messages": 12450 },
    { "agent": "geek", "active": 8, "archived": 15, "messages": 8920 },
    { "agent": "coding", "active": 9, "archived": 14, "messages": 11280 },
    { "agent": "netops", "active": 3, "archived": 5, "messages": 4560 },
    { "agent": "homelab", "active": 2, "archived": 6, "messages": 4000 }
  ],
  "session_key_patterns": [
    { "pattern": "agent:*:dashboard:*", "count": 35, "active": 28 },
    { "pattern": "agent:*:main", "count": 12, "active": 8 },
    { "pattern": "agent:*:web*", "count": 10, "active": 0, "note": "全部已归档" }
  ],
  "message_trend_30d": [
    { "date": "2026-05-25", "count": 1200, "size_mb": 12.3 },
    { "date": "2026-05-26", "count": 1350, "size_mb": 13.8 },
    { "date": "2026-06-24", "count": 1480, "size_mb": 15.2 }
  ],
  "backup_status": {
    "total_size_mb": 438.0,
    "files": [
      { "name": "rotate-latest.bak", "size_mb": 438.0, "age_days": 0, "keep": true }
    ]
  },
  "health_alerts": [
    {
      "level": "success",
      "code": "ARCHIVE_DONE",
      "message": "今日归档 10 个 web 会话，释放 4.2MB",
      "timestamp": "2026-06-24T02:00:15+08:00"
    },
    {
      "level": "info",
      "code": "WAL_OK",
      "message": "WAL 文件大小正常 (0 MB)",
      "timestamp": "2026-06-24T02:00:10+08:00"
    }
  ]
}
```

---

## 🔢 字段计算逻辑（exporter.py 实现）

| 字段 | 计算方式 |
|------|----------|
| `total_conversations` | `SELECT COUNT(*) FROM conversations` |
| `active_conversations` | `WHERE active=1` |
| `archived_conversations` | `WHERE active=0` |
| `total_messages` | `SELECT COUNT(*) FROM messages` |
| `total_summaries` | `SELECT COUNT(*) FROM summaries` |
| `leaf_summaries` | `WHERE kind='leaf'` |
| `condensed_summaries` | `WHERE kind='condensed'` |
| `storage_size_mb` | `os.path.getsize(LDB) / 1024 / 1024` |
| `wal_size_mb` | `os.path.getsize(WAL) / 1024 / 1024`（若无文件 = 0） |
| `message_trend_30d` | 按 `messages.created_at` 分组，30 天滚动 |
| `agent_distribution` | 从 `session_key` 第一段（`agent:<role>:<source>`）提取 role |
| `session_key_patterns` | 按 `session_key LIKE 'pattern%'` 聚合 |
| `last_archive_days_ago` | `julianday('now') - julianday(MAX(archived_at))` |

---

## ⚠️ 字段约束

| 字段 | 约束 |
|------|------|
| `meta.schema_version` | 升级时 Bump（如 1.0 → 1.1），HTML 端按版本兼容 |
| `message_trend_30d.length` | 必须恰好 30 项（不够补 0） |
| `agent_distribution` | 按 `messages` 数倒序排列 |
| `health_alerts` | 上限 10 项（按 timestamp 倒序） |

---

## 📚 参考资料

- [`./DESIGN.md`](./DESIGN.md) — 视觉规范
- [`./SECURITY.md`](./SECURITY.md) — 脱敏策略
- [`../../docs/DASHBOARD_REGISTRY.md`](../../docs/DASHBOARD_REGISTRY.md) — 模块清单