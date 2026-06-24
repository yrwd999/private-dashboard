# memory-tdai Dashboard · Security

> 数据脱敏 + 访问控制 + 审计策略
> 最后更新：2026-06-24 · 维护者：Ray

---

## 🎯 核心原则

**零信任 + 凭证隔离 + 最小权限**

- exporter.py **只读** vectors.db 和 JSONL 文件，**永不写入**
- 仓库内**零凭据**（API key 在 OpenClaw 本地 `openclaw.json`）
- 数据脱敏在**源头完成**（Python 脚本），Dashboard 层无感知
- 场景块（scene_blocks）和用户画像（persona.md）**永不导出原始内容**

---

## 🚫 永不导出字段（黑名单）

### SQL 层（vectors.db）

| 字段 | 表 | 风险 |
|------|----|------|
| `message_text` | `l0_conversations` | 完整对话原文，高敏感 |
| `session_key` | `l0_conversations` / `l1_records` | 完整 session key，含 agent/渠道 ID |
| `content` | `l1_records` | LLM 提取的记忆内容 |
| `metadata_json` | `l0_conversations` / `l1_records` | 可能含 agent 内部数据 |
| `session_id` | `l0_conversations` / `l1_records` | UUID，可关联 session_key |
| `embedding` | `l0_vec` / `l1_vec` | 向量数据，不导出 |

**强制护栏**：exporter 脚本必须显式 SELECT 白名单字段，禁用 `SELECT *`

### 文件系统层

| 文件 | 原因 |
|------|------|
| `scene_blocks/*.md` body | 场景块含对话摘要和决策，高敏感 |
| `persona.md` body | 用户画像含个人偏好和习惯，高敏感 |
| `conversations/*.jsonl` | 原始对话流，完整消息内容 |

### openclaw.json 配置层

| 字段 | 处理方式 |
|------|----------|
| `plugins.entries.memory-tencentdb.config.embedding.apiKey` | **不导出**，仅读取 provider/model/dimensions |
| `plugins.entries.memory-tencentdb.config.llm.apiKey` | **不导出** |
| `plugins.entries.memory-tencentdb.config.tcvdb.apiKey` | **不导出** |

---

## ✅ 脱敏映射规则

### vectors.db 路径

导出为相对路径，不暴露用户 home 目录：
```
# 导出
"vectors_db_path": "memory-tdai/vectors.db"
# 不导出 ~/.openclaw/memory-tdai/vectors.db
```

### JSONL 文件列表

仅导出文件数，不导出文件名列表（文件名可能含 session key 片段）：
```json
"jsonl_file_count": 24
# 不导出 ["2026-05-26.jsonl", "agent:main:web:xxx.jsonl", ...]
```

### scene_block 文件名

场景块文件名含中文语义，仅导出文件名（不含 body）：
```json
"file_list": [
  "AI-记忆系统升级决策.md",
  "OpenClaw-系统治理与规范约束.md"
]
# 不导出文件内容
# 不导出 record_id
```

### persona.md

仅导出元数据，不导出内容：
```json
{
  "persona_exists": true,
  "last_updated": "2026-06-24T10:31:00+08:00",
  "last_updated_days_ago": 0,
  "file_size_bytes": 8571
}
```

### API 配置

```json
"api": {
  "embedding": {
    "provider": "dashscope",
    "model": "text-embedding-v4",
    "dimensions": 1024,
    "send_dimensions": true
    // apiKey 不导出
  }
}
```

---

## 🔒 访问控制

### 仓库层级

| 项 | 值 | 说明 |
|----|-----|------|
| 仓库可见性 | **public** | GitHub Pages Free 要求 |
| 协作者 | 仅 `yrwd999` | 单人维护 |
| 分支保护 | `main` 需 PR review | — |

### GitHub Pages 层级

| 项 | 值 | 说明 |
|----|-----|------|
| Pages 可见性 | public | GitHub Pages 限制 |
| 数据脱敏 | ✅ 已在源头完成 | 唯一安全屏障 |
| 凭据隔离 | ✅ 仓库无 API key | 无外泄风险 |

---

## 📋 审计日志

### 推送审计

每次 git commit 信息：
```
[memory-tdai] YYYY-MM-DD auto-update

- vectors.db: 135.2 MB (WAL: 2.7 MB)
- L0: 16928 conversations, 16826 vectors (99.4%)
- L1: 199 records, 194 vectors (97.5%)
- L0 errors 24h: 26 (HTTP 400 batch size)
- Cleaner: 0 expired (retention=90d)
- Schema: v1.0
```

### 操作审计（cron 报告）

```json
{
  "executed_at": "2026-06-24T03:00:00+08:00",
  "task": "memory-tdai-daily-snapshot",
  "operation": "export",
  "source": "~/.openclaw/memory-tdai/vectors.db",
  "output": "memory-tdai/data/2026-06-24.json + latest.json",
  "vectors_db_size_mb": 135.2,
  "l0_completeness_pct": 99.4,
  "l1_completeness_pct": 97.5,
  "health_alerts_count": 2,
  "result": "success"
}
```

---

## ⚠️ 异常熔断

以下情况**立即停止推送** + 通知 Ray：

| 触发条件 | 级别 | 动作 |
|----------|------|------|
| `vectors.db` > 1 GB | critical | 停止推送，紧急通知 |
| L0 向量完整率 < 95% | critical | 停止推送，紧急通知 |
| WAL > 50 MB | error | 停止推送，通知 |
| 检测到黑名单字段（message_text / content）| critical | 立即停止，紧急通知 |
| scene_blocks 或 persona.md 内容被导出 | critical | 立即停止，紧急通知 |
| 连续 3 天推送失败 | error | 自动禁用 cron，通知 |
| DB 体积较昨日增长 > 30% | warning | 通知，不停止推送 |

---

## 🧪 脱敏验证测试

```python
# tests/test_memory_tdai_sanitization.py

def test_no_message_text():
    """确认 message_text 不在导出中"""
    with open("data/latest.json") as f:
        raw = f.read()
    assert "message_text" not in raw
    assert "对话内容" not in raw

def test_no_session_key():
    """确认 session_key 原始值不在导出中"""
    with open("data/latest.json") as f:
        raw = f.read()
    # session_key 完整值不应出现
    assert "agent:main:web:" not in raw

def test_no_scene_block_content():
    """确认 scene_blocks 文件内容不在导出中"""
    with open("data/latest.json") as f:
        raw = f.read()
    assert "OpenClaw-系统治理" not in raw  # 文件名可能还在元数据中，但 body 不在

def test_no_persona_content():
    """确认 persona.md 内容不在导出中"""
    with open("data/latest.json") as f:
        raw = f.read()
    data = json.load(f)
    assert "persona_exists" in data["l3"]
    assert "last_updated" in data["l3"]
    # body 内容不应出现
    assert len(raw) < 10000  # 整个 JSON 应很小（无大文本）

def test_no_api_keys():
    """确认无 API key 泄漏"""
    with open("data/latest.json") as f:
        raw = f.read()
    for pattern in ["sk-", "sk_", "eyJ", "apiKey", "password"]:
        assert pattern not in raw, f"发现疑似凭据: {pattern}"

def test_no_jsonl_content():
    """确认 JSONL 文件内容不在导出中"""
    with open("data/latest.json") as f:
        raw = f.read()
    assert "role" not in raw or "user" not in raw  # JSONL 中有 role 字段
```

---

## 📚 参考资料

- [`./DESIGN.md`](./DESIGN.md) — 视觉规范
- [`./DATA_SCHEMA.md`](./DATA_SCHEMA.md) — 数据 schema
- [`../../DASHBOARD_REGISTRY.md`](../../DASHBOARD_REGISTRY.md) — 模块清单
- [`../../../scripts/exporter-memory-tdai-spec.md`](../../../scripts/exporter-memory-tdai-spec.md) — Exporter 规格
