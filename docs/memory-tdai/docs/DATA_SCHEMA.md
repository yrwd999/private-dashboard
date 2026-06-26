# memory-tdai Dashboard · Data Schema

> `data/latest.json` + `data/history/YYYY-MM-DD.json` 字段定义
> 最后更新：2026-06-26 · 维护者：Ray · Schema v1.1

---

## 📦 文件清单

| 文件 | 生成方式 | 用途 |
|------|----------|------|
| `data/latest.json` | 每 30 分钟覆盖 | Dashboard 直接 fetch |
| `data/history/YYYY-MM-DD.json` | 每日 03:00 新建 | 30 天历史滚动（趋势图数据源） |

---

## 🧬 Schema v1.1

```typescript
interface MemoryTdaiData {
  meta: MetaInfo;
  l0: L0Stats;
  l1: L1Stats;
  l2: L2Stats;
  l3: L3Stats;
  storage: StorageStats;
  recall: RecallConfig;
  api: ApiStats;
  cleaning: CleaningPolicy;
  health_alerts: HealthAlert[];
}

interface MetaInfo {
  generated_at: string;              // ISO 8601, e.g. "2026-06-24T03:00:00+08:00"
  vectors_db_size_mb: number;         // 135.2
  vectors_db_path: string;           // "memory-tdai/vectors.db"（相对路径）
  jsonl_total_size_mb: number;        // 0.135
  jsonl_file_count: number;           // 24
  wal_size_mb: number;               // WAL 文件大小，0 = healthy
  schema_version: string;            // "1.0"
}

interface L0Stats {
  conversations: number;              // l0_conversations 总记录数
  vectors: number;                    // l0_vec 总记录数
  missing: number;                   // 缺失 embedding 的对话数
  completeness_pct: number;           // 向量完整率，0~100
  fts_synced: boolean;               // l0_fts 与 l0_conversations 是否同步
  errors_24h: EmbeddingErrors;       // 过去 24h embedding 错误
  capture_trend_30d: DailyCount[];   // 近 30 天每日新增对话数
}

interface L1Stats {
  records: number;                    // l1_records 总记录数
  vectors: number;                    // l1_vec 总记录数
  missing: number;                    // 缺失 embedding 的记忆数
  completeness_pct: number;           // 向量完整率
  fts_synced: boolean;               // l1_fts 与 l1_records 是否同步
  errors_24h: EmbeddingErrors;
  extraction_failures_24h: number;    // L1 extraction 失败次数
  extraction_latency_ms_p95: number;  // Extraction 延迟 P95
}

interface EmbeddingErrors {
  http_400_batch_size: number;       // batch size > 10 错误（最常见）
  http_429_rate_limit: number;        // 限流错误
  http_500_server: number;            // 服务端错误
  timeout: number;                    // 超时错误
  db_locked: number;                  // database is locked
  total: number;                     // 错误总数
}

interface DailyCount {
  date: string;                       // "2026-06-24"
  count: number;                     // 当日新增数
}

interface L2Stats {
  scene_blocks: number;               // 场景块 .md 文件总数
  last_updated: string | null;       // 最后更新时间 ISO（无则 null）
  last_updated_days_ago: number;     // 距今天数
  file_list: string[];                // 文件名列表（已脱敏，仅保留语义名）
  freshness: "healthy" | "warning" | "stale";
}

interface L3Stats {
  persona_exists: boolean;            // persona.md 是否存在
  last_updated: string | null;       // 最后更新时间 ISO
  last_updated_days_ago: number;     // 距今天数
  file_size_bytes: number;            // 文件大小
  freshness: "healthy" | "warning" | "stale";
}

interface StorageStats {
  vectors_db_mb: number;              // vectors.db 大小
  wal_mb: number;                     // WAL 大小
  wal_oversized: boolean;             // WAL > 5MB = true
  jsonl_total_mb: number;             // conversations/ JSONL 总大小
  jsonl_file_count: number;            // JSONL 文件数
  backup_mb: number;                  // .backup/ 目录大小
  storage_growth_mb_per_day: number;  // 日均增长（估算）
}

interface RecallConfig {
  strategy: "hybrid" | "keyword" | "embedding";
  max_results: number;
  score_threshold: number;
  timeout_ms: number;
  status: "healthy" | "degraded";    // degraded = L0 completeness < 95% OR FTS health < 100%
  fts_health_score: number;           // FTS5 索引健康分：l1_fts / l1_records * 100
  high_priority_retrievable_pct: number;  // priority > 90 且 FTS 命中的记录比例，0~100
}

interface ApiStats {
  embedding: {
    provider: string;                 // "dashscope"
    model: string;                    // "text-embedding-v4"
    dimensions: number;               // 1024
    send_dimensions: boolean;         // 潜在兼容性问题
    availability_24h: number;          // 可用率 0~100
    errors_24h: number;
    p95_latency_ms: number;          // P95 延迟
  };
  llm: {
    provider: string;                 // "dashscope"
    model: string;                    // "qwen3.6-flash"
    availability_24h: number;
    errors_24h: number;
  };
}

interface CleaningPolicy {
  retention_days: number;             // 90
  clean_time: string;                 // "03:00"
  last_run: string | null;           // ISO，最后执行时间
  last_run_days_ago: number;         // 距今天数
  l0_total: number;                  // 清理时 L0 记录总数
  l0_expired: number;                // 清理时过期记录数
  l1_total: number;
  l1_expired: number;
  effectiveness: "healthy" | "low";  // expired > 0 = healthy，= 0 连续 3 天 = low
}

interface HealthAlert {
  level: "info" | "success" | "warning" | "error" | "critical";
  code: string;                      // 告警码
  message: string;                   // 可读描述
  value?: number;                    // 当前值
  threshold?: number;                // 告警阈值
  timestamp: string;                 // ISO 8601
}
```

---

## 📊 示例数据

```json
{
  "meta": {
    "generated_at": "2026-06-26T03:00:00+08:00",
    "vectors_db_size_mb": 135.2,
    "vectors_db_path": "memory-tdai/vectors.db",
    "jsonl_total_size_mb": 14.893,
    "jsonl_file_count": 24,
    "wal_size_mb": 4.11,
    "schema_version": "1.1"
  },
  "l0": {
    "conversations": 16928,
    "vectors": 16826,
    "missing": 102,
    "completeness_pct": 99.4,
    "fts_synced": true,
    "errors_24h": {
      "http_400_batch_size": 26,
      "http_429_rate_limit": 0,
      "http_500_server": 0,
      "timeout": 0,
      "db_locked": 0,
      "total": 26
    },
    "capture_trend_30d": [
      { "date": "2026-05-26", "count": 420 },
      { "date": "2026-05-27", "count": 380 }
    ]
  },
  "l1": {
    "records": 199,
    "vectors": 194,
    "missing": 5,
    "completeness_pct": 97.5,
    "fts_synced": true,
    "errors_24h": {
      "http_400_batch_size": 0,
      "http_429_rate_limit": 0,
      "http_500_server": 0,
      "timeout": 0,
      "db_locked": 1,
      "total": 1
    },
    "extraction_failures_24h": 0,
    "extraction_latency_ms_p95": 3200
  },
  "l2": {
    "scene_blocks": 10,
    "last_updated": "2026-06-24T09:30:00+08:00",
    "last_updated_days_ago": 0,
    "file_list": [
      "AI-记忆系统升级决策.md",
      "OpenClaw-系统治理与规范约束.md",
      "智能家居设备与环境配置.md"
    ],
    "freshness": "healthy"
  },
  "l3": {
    "persona_exists": true,
    "last_updated": "2026-06-24T10:31:00+08:00",
    "last_updated_days_ago": 0,
    "file_size_bytes": 8571,
    "freshness": "healthy"
  },
  "storage": {
    "vectors_db_mb": 135.2,
    "wal_mb": 2.7,
    "wal_oversized": false,
    "jsonl_total_mb": 0.135,
    "jsonl_file_count": 24,
    "backup_mb": 0,
    "storage_growth_mb_per_day": 3.2
  },
  "recall": {
    "strategy": "hybrid",
    "max_results": 5,
    "score_threshold": 0.3,
    "timeout_ms": 10000,
    "status": "healthy",
    "fts_health_score": 100.0,
    "high_priority_retrievable_pct": 100.0
  },
  "api": {
    "embedding": {
      "provider": "dashscope",
      "model": "text-embedding-v4",
      "dimensions": 1024,
      "send_dimensions": true,
      "availability_24h": 99.8,
      "errors_24h": 26,
      "p95_latency_ms": 850
    },
    "llm": {
      "provider": "dashscope",
      "model": "qwen3.6-flash",
      "availability_24h": 100,
      "errors_24h": 0
    }
  },
  "cleaning": {
    "retention_days": 90,
    "clean_time": "03:00",
    "last_run": "2026-06-24T03:00:00+08:00",
    "last_run_days_ago": 0,
    "l0_total": 16533,
    "l0_expired": 0,
    "l1_total": 193,
    "l1_expired": 0,
    "effectiveness": "low"
  },
  "health_alerts": [
    {
      "level": "warning",
      "code": "L0_EMBEDDING_INCOMPLETE",
      "message": "L0 向量完整率 99.4%（缺失 102 条），根因：MAX_BATCH_SIZE=256 vs API limit=10",
      "value": 99.4,
      "threshold": 99.0,
      "timestamp": "2026-06-24T03:00:00+08:00"
    },
    {
      "level": "warning",
      "code": "CLEAN_EFFECTIVENESS_LOW",
      "message": "Cleaner 连续 0 条过期记录（retention=90天，可能过长）",
      "value": 0,
      "timestamp": "2026-06-24T03:00:00+08:00"
    }
  ]
}
```

---

## 🔢 字段计算逻辑

| 字段 | 计算方式 |
|------|----------|
| `l0.completeness_pct` | `l0_vec / l0_conversations * 100`，保留 1 位小数 |
| `l1.completeness_pct` | `l1_vec / l1_records * 100`，保留 1 位小数 |
| `l2.freshness` | days_ago ≤ 7 = healthy / ≤ 30 = warning / > 30 = stale |
| `l3.freshness` | days_ago ≤ 30 = healthy / ≤ 90 = warning / > 90 = stale |
| `wal_oversized` | wal_mb > 5 |
| `recall.status` | `l0.completeness_pct >= 95 AND recall.fts_health_score == 100 ? "healthy" : "degraded"` |
| `recall.fts_health_score` | `l1_fts_count / l1_records * 100`，保留 1 位小数 |
| `recall.high_priority_retrievable_pct` | `COUNT(priority>90 AND exists_in_fts) / COUNT(priority>90) * 100`；无高优先级记录时 = 100 |
| `cleaning.effectiveness` | `l0_expired + l1_expired > 0 ? "healthy" : "low"` |
| `storage.storage_growth_mb_per_day` | 从 history 推算近 7 天平均 |

---

## ⚠️ 字段约束

| 字段 | 约束 |
|------|------|
| `meta.schema_version` | 升级时 bump（1.1 → 1.2），HTML 端按版本兼容 |
| `l0.capture_trend_30d` | 必须恰好 30 项（不够补 0） |
| `health_alerts` | 上限 20 项（按 level + timestamp 排序：critical > error > warning > info > success） |
| `l2.file_list` | 仅导出文件名（语义名），不含路径和 record_id |

---

## 🚫 导出黑名单（永不 SELECT）

| 字段 | 表 | 风险 |
|------|----|------|
| `message_text` | `l0_conversations` | 完整对话内容 |
| `session_key` | `l0_conversations / l1_records` | 完整 session key |
| `content` | `l1_records` | 记忆内容原文 |
| `metadata_json` | `l0_conversations / l1_records` | 可能含敏感数据 |
| `scene_blocks/*.md` body | 文件系统 | 场景块原文 |
| `persona.md` body | 文件系统 | 用户画像原文 |

---

## 📚 参考资料

- [`./DESIGN.md`](./DESIGN.md) — 视觉规范
- [`./SECURITY.md`](./SECURITY.md) — 脱敏策略
- [`../../DASHBOARD_REGISTRY.md`](../../DASHBOARD_REGISTRY.md) — 模块清单
- [`../../../scripts/exporter-memory-tdai-spec.md`](../../../scripts/exporter-memory-tdai-spec.md) — Exporter 规格
