# Exporter: memory-tdai

> 规格文档 · 只写规格，不写代码
> 版本：v1.0 | 2026-06-24 | 维护者：Ray

---

## 🎯 目的

每日定时从 `memory-tdai` 插件的数据源提取健康指标，
输出到 `docs/memory-tdai/data/latest.json` + `docs/memory-tdai/data/history/YYYY-MM-DD.json`，
供 Dashboard 可视化使用。

---

## 📡 数据源清单

| 数据源 | 路径 | 用途 |
|--------|------|------|
| vectors.db | `~/.openclaw/memory-tdai/vectors.db` | L0/L1 向量计数、完整性、FTS 同步 |
| JSONL 文件 | `~/.openclaw/memory-tdai/conversations/*.jsonl` | JSONL 总量统计 |
| scene_blocks | `~/.openclaw/memory-tdai/scene_blocks/*.md` | 场景块新鲜度 |
| persona.md | `~/.openclaw/memory-tdai/persona.md` | 用户画像新鲜度 |
| openclaw.json | `~/.openclaw/openclaw.json` | API 配置（provider/model/dimensions，无 key） |
| 日志 | `~/.openclaw/logs/openclaw-YYYY-MM-DD.log` | HTTP 400/429/500 错误率（24h） |

---

## 🔌 输入规格

### 1. vectors.db（只读）

路径：`~/.openclaw/memory-tdai/vectors.db`

**允许读取的表：**

- `l0_conversations`
- `l0_vec`
- `l1_records`
- `l1_vec`
- `l0_fts`（FTS5 虚拟表）
- `l1_fts`（FTS5 虚拟表）

**允许读取的字段（白名单）：**

```sql
-- l0_conversations
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN session_key IS NOT NULL THEN 1 ELSE 0 END)  -- 不导出 session_key，仅计数

-- l0_vec
SELECT COUNT(*) AS vectors

-- l1_records
SELECT COUNT(*) AS total

-- l1_vec
SELECT COUNT(*) AS vectors

-- l0_fts（验证 FTS 同步）
SELECT COUNT(*) AS fts_count

-- l1_fts（验证 FTS 同步）
SELECT COUNT(*) AS fts_count

-- WAL 大小（通过 PRAGMA wal_checkpoint 估算）
PRAGMA database_list;  -- 找 db 路径
-- 然后 stat: wal 文件大小
```

**数据库大小：** `SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size();`

### 2. openclaw.json（只读）

路径：`~/.openclaw/openclaw.json`

**允许读取的字段：**

```json
{
  "plugins": {
    "entries": {
      "memory-tencentdb": {
        "config": {
          "embedding": {
            "provider": "dashscope",
            "model": "text-embedding-v4",
            "dimensions": 1024,
            "sendDimensions": true
            // apiKey 显式排除
          },
          "llm": {
            "provider": "dashscope",
            "model": "qwen3.6-flash"
          },
          "recall": {
            "strategy": "hybrid"
          },
          "cleaner": {
            "retentionDays": 90,
            "cleanTime": "03:00"
          }
        }
      }
    }
  }
}
```

### 3. 日志文件（只读）

路径：`~/.openclaw/logs/openclaw-YYYY-MM-DD.log`（当天）

**解析规则（grep + count）：**

| 错误类型 | 匹配正则 |
|----------|----------|
| HTTP 400 batch_size | `embedding.*HTTP 400\|batch.*size.*exceed\|MAX_BATCH_SIZE` |
| HTTP 429 rate_limit | `embedding.*HTTP 429\|rate.?limit` |
| HTTP 500 server | `embedding.*HTTP 5\d\d` |
| timeout | `embedding.*timeout\|timed out` |
| db_locked | `database is locked\|SQLITE_BUSY` |

**时间范围：** 当天 `00:00:00` ~ `23:59:59`

### 4. 文件系统（只读）

```bash
# JSONL 总大小
du -sm ~/.openclaw/memory-tdai/conversations/

# JSONL 文件数
ls ~/.openclaw/memory-tdai/conversations/*.jsonl | wc -l

# scene_blocks 文件列表（仅文件名，用于新鲜度）
ls -la ~/.openclaw/memory-tdai/scene_blocks/*.md
# 导出格式：["AI-记忆系统升级决策.md", ...]（无 record_id）

# persona.md 元数据
stat ~/.openclaw/memory-tdai/persona.md
```

---

## 📤 输出规格

### 输出文件 1: `data/latest.json`

由 `scripts/exporter_memory_tdai.py` 写入：
```
docs/memory-tdai/data/latest.json
```

### 输出文件 2: `data/history/YYYY-MM-DD.json`

由 `scripts/exporter_memory_tdai.py` 写入：
```
docs/memory-tdai/data/history/YYYY-MM-DD.json
```
每次覆盖 latest 后，复制到 history/YYYY-MM-DD.json。

---

## 🔧 SQL 查询白名单（强制）

```sql
-- Q1: L0 对话总数
SELECT COUNT(*) FROM l0_conversations;

-- Q2: L0 向量总数
SELECT COUNT(*) FROM l0_vec;

-- Q3: L0 缺失 embedding 数（Q1 - Q2）
-- 在 Python 层计算，不查数据库

-- Q4: L0 FTS 计数
SELECT COUNT(*) FROM l0_fts;

-- Q5: L1 记录总数
SELECT COUNT(*) FROM l1_records;

-- Q6: L1 向量总数
SELECT COUNT(*) FROM l1_vec;

-- Q7: L1 缺失 embedding 数（Q5 - Q6）
-- 在 Python 层计算

-- Q8: L1 FTS 计数
SELECT COUNT(*) FROM l1_fts;

-- Q9: vectors.db 大小（字节）
SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size();
```

**禁止的 SQL 模式：**
- `SELECT *` — 全部禁止
- 任何带 `WHERE message_text` / `WHERE content` 的查询
- 任何带 `JOIN` 或 `SUBQUERY` 跨表查询

---

## 🔒 安全约束

| 约束 | 说明 |
|------|------|
| **只读** | 禁止对 vectors.db 执行写操作（INSERT/UPDATE/DELETE） |
| **黑名单字段** | message_text、session_key、content、metadata_json 永不 SELECT |
| **API Key** | 不导出任何 key（ Dashscope / LLM / HA ） |
| **凭据** | 不导出 openclaw.json 中的 password / token / apiKey |
| **JSONL 内容** | 不读取 conversations/*.jsonl 文件内容，仅统计大小和数量 |
| **scene_blocks** | 仅读取文件名，不读取文件内容 |
| **persona.md** | 仅读取 stat 元数据，不读取文件内容 |
| **session_key** | 仅保留 `agent:*` 前缀 pattern 聚合（不导出原始值） |

---

## 🐍 环境依赖

```
Python 3.10+
sqlite3（标准库）
json（标准库）
re（标准库）
stat / os / pathlib（标准库）
hashlib（标准库）
```

**禁止使用：**
- `psycopg2` / `pymysql` — 非 SQLite
- `requests` — 不需要 HTTP 调用（纯本地读取）
- `openai` / `dashscope` SDK — 不导出 embedding 内容

---

## ⏱️ Cron 任务配置

### Daily Snapshot（每日 03:00）

```json
{
  "name": "memory-tdai-daily-snapshot",
  "schedule": { "kind": "cron", "expr": "0 3 * * *", "tz": "Asia/Shanghai" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 memory-tdai 每日健康快照 exporter。\n\n参考规格：scripts/exporter-memory-tdai-spec.md\n参考代码：scripts/exporter_memory_tdai.py（待实现）\n\n如果 exporter 还不存在，先实现它（dry-run 验证），然后执行导出。\n\n输出路径：\n  - docs/memory-tdai/data/latest.json\n  - docs/memory-tdai/data/history/YYYY-MM-DD.json\n\ngit commit 信息：[memory-tdai] YYYY-MM-DD auto-update\n\n⚠️ 禁止导出：message_text、session_key、content、metadata_json、scene_block 内容、persona 内容、任何 API key"
  },
  "delivery": { "mode": "announce" },
  "failureAlert": { "after": 3, "mode": "announce" }
}
```

### Hourly Incremental Repair（每小时半点）

```json
{
  "name": "memory-tdai-hourly-repair",
  "schedule": { "kind": "cron", "expr": "30 * * * *", "tz": "Asia/Shanghai" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 memory-tdai 增量修复（修复新产生的缺失 embedding）。\n\n参考代码：scripts/fix-missing-embeddings.py\n\n参数：--limit 500（每小时最多处理 500 条新增缺失）\n参数：--checkpoint 50（每 50 批 checkpoint）\n\n⚠️ 不要修改已有的 embedding，仅处理 missing=True 的新记录"
  },
  "delivery": { "mode": "none" },
  "failureAlert": { "after": 3, "mode": "announce" }
}
```

---

## 🧪 测试用例（dry-run 必须通过）

### T1: 基本导出

```bash
python3 scripts/exporter_memory_tdai.py --dry-run
```

**预期输出：**
```
[memory-tdai] dry-run: meta.generated_at=2026-06-24T03:00:00+08:00
[memory-tdai] dry-run: l0.conversations=16928, vectors=16826, missing=102
[memory-tdai] dry-run: l1.records=199, vectors=194, missing=5
[memory-tdai] dry-run: storage.vectors_db_mb=135.2
[memory-tdai] dry-run: health_alerts=2 (warning)
[memory-tdai] dry-run: PASS - 无黑名单字段，无 API key
```

### T2: 黑名单字段检查

```bash
python3 scripts/exporter_memory_tdai.py --dry-run
# 检查输出 JSON 中不包含以下字段：
grep -E "message_text|session_key|content|metadata_json|apiKey" data/latest.json
# 预期：无输出（PASS）
```

### T3: JSON Schema 验证

```bash
python3 scripts/exporter_memory_tdai.py --dry-run --validate-schema
# 预期：exit code 0
```

### T4: 历史数据完整性

```bash
# 验证 history/ 目录有且仅有 30 天数据
ls scripts/memory-tdai/data/history/ | wc -l  # 预期：30
# 验证 latest.json 和最新 history/ 内容一致
diff data/latest.json data/history/$(date +%Y-%m-%d).json  # 预期：无差异
```

### T5: 告警阈值触发

```python
# 模拟 WAL > 20MB，验证 health_alerts 包含 error
# 模拟 L0 completeness < 95%，验证 health_alerts 包含 critical
```

---

## 📊 性能预算

| 指标 | 预算 | 说明 |
|------|------|------|
| 执行时间 | ≤ 10 秒 | 纯本地 SQLite 读取 |
| 内存占用 | ≤ 50 MB | Python 进程 |
| 输出文件大小 | ≤ 50 KB | JSON（无原始内容） |
| CPU 使用 | ≤ 10% | 单线程顺序读取 |

---

## 🔄 增量修复脚本（fix-missing-embeddings.py）

此脚本由 Exporter cron 调度器调用，不属于 exporter 本身。

**规格约束：**

| 约束 | 说明 |
|------|------|
| 读取 vectors.db | 只读查询 `SELECT record_id FROM l0_conversations WHERE record_id NOT IN (SELECT record_id FROM l0_vec)` |
| 写入 vectors.db | 仅 INSERT INTO l0_vec（向量写入） |
| 读取 openclaw.json | 仅读取 embedding 配置（provider/model/dimensions/apiKey） |
| 调用 embedding API | 批量大小 ≤ 10（API 限制） |
| 重试策略 | 429 → 指数退避（4s base），500 → 指数退避，timeout → 重试 3 次 |
| Checkpoint | 每 50 批执行一次 `PRAGMA wal_checkpoint(TRUNCATE)` |
| 报告 | 输出 JSON 格式：`{"processed": 500, "failed": 0, "remaining": 6086}` |

---

## 📚 参考资料

- [Dashboard Registry](../docs/DASHBOARD_REGISTRY.md)
- [memory-tdai DATA_SCHEMA](../docs/memory-tdai/docs/DATA_SCHEMA.md)
- [memory-tdai SECURITY](../docs/memory-tdai/docs/SECURITY.md)
- [memory-tdai DESIGN](../docs/memory-tdai/docs/DESIGN.md)
