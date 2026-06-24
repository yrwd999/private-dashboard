# LCM Dashboard · Security

> 数据脱敏 + 访问控制 + 审计策略
> 最后更新：2026-06-24 · 维护者：Ray

---

## 🎯 核心原则

**零信任 + 凭证隔离 + 最小权限**

- exporter.py 只读 SQLite，**永不写入**
- 仓库内**零凭据**（token 在 OpenClaw 本地 secrets.json）
- 数据脱敏在**源头完成**（Python 脚本），不依赖 DB 端

---

## 🚫 永不导出字段（黑名单）

| 字段 | 来源表 | 风险 |
|------|--------|------|
| `message.content` | `messages` | 含完整对话内容 |
| `message.large_content` | `messages` | 大字段原始内容 |
| `summary.content` | `summaries` | 摘要内容 |
| `session_id` | `conversations` | UUID，可关联 session_key |
| `transcript_entry_id` | `messages` | 内部引用 |
| `identity_hash` | `messages` | 身份哈希 |

**强制护栏**：exporter.py 必须显式 SELECT 白名单字段，禁用 `SELECT *`

---

## ✅ 脱敏映射规则

### session_key 脱敏

| 原始 | 导出 |
|------|------|
| `agent:main:web:1780896220022` | `agent:main:web*`（pattern 聚合） |
| `agent:main:dashboard:e3604e28-35c5-4e6e-a3eb-b1d314950402` | `agent:*:dashboard:*`（pattern 聚合） |
| `agent:geek:ha-anomaly` | `agent:geek:ha-anomaly`（保留，已脱敏） |

**规则**：
- 仅在 `session_key_patterns` 字段聚合，不暴露具体 ID
- `agent_distribution` 仅按 role 段聚合
- **永不**导出 `session_key` 原始值

### conversation_id 脱敏

`#0022` 格式：按创建顺序编号，不暴露原始自增 ID

### DB 路径脱敏

`lcm.db_path_hash` = `sha256:` + 前 64 位哈希
- 用于检测 DB 路径变更（监控异常）
- 不暴露绝对路径

---

## 🔒 访问控制

### 仓库层级

| 项 | 值 | 说明 |
|----|-----|------|
| 仓库可见性 | **public** | GitHub Pages Free 要求 |
| 协作者 | 仅 `yrwd999` | 单人维护 |
| 分支保护 | `main` 需 PR review（可选，Phase 4 启用） |

### Pages 层级

| 项 | 值 | 说明 |
|----|-----|------|
| Pages 可见性 | public | GitHub Pages 限制 |
| 数据脱敏 | ✅ 已在源头完成 | 唯一安全屏障 |
| 凭据隔离 | ✅ 仓库无 token | 无外泄风险 |

### 未来升级路径（如需要登录）

- Phase 5+：绑定自定义域名 + Cloudflare Access
- OAuth provider：GitHub
- 访问策略：仅允许 `yrwd999` GitHub 账号
- 会话保持：24 小时

---

## 📋 审计日志

### 推送审计

每次 git commit 必须包含：

```
[LCM] YYYY-MM-DD auto-update

- DB size: 438.2 MB (was 442.4 MB)
- Active: 40 (was 41)
- Archived: 52 (was 51)
- Archived today: 10 web sessions
- Schema: v1.0
```

### 操作审计（cron 报告）

cron 任务执行后输出：

```json
{
  "executed_at": "2026-06-24T02:00:00+08:00",
  "task": "lcm-daily-snapshot",
  "operation": "export",
  "source": "~/.openclaw/lcm.db",
  "output": "data/2026-06-24.json + data/latest.json",
  "size_before_mb": 442.4,
  "size_after_mb": 438.2,
  "records": {
    "conversations": 92,
    "messages_sampled": 0,
    "summaries_sampled": 0
  },
  "result": "success",
  "next_action": "git commit && git push"
}
```

存放在 `~/.openclaw/reports/lcm-daily-YYYYMMDD.md`

---

## ⚠️ 异常熔断

以下情况立即停止推送 + 通知 Ray：

| 触发条件 | 动作 |
|----------|------|
| DB 体积较昨日增长 > 50% | 暂停推送，发送 Signal 告警 |
| 单次导出 > 100MB | 暂停推送（数据膨胀异常） |
| 连续 3 天推送失败 | 自动禁用 cron，发送告警 |
| 检测到 message.content 字段（schema 错误） | 立即停止，紧急通知 |
| session_key 未脱敏出现在 JSON 中 | 立即停止，紧急通知 |

---

## 🧪 脱敏验证脚本（exporter.py 必须通过）

```python
# tests/test_desensitize.py

def test_no_message_content():
    """确认 message.content 不在导出中"""
    with open("data/latest.json") as f:
        data = json.load(f)
    # JSON 应不含 messages 数组
    assert "messages" not in data or all("content" not in m for m in data.get("messages", []))

def test_no_full_session_key():
    """确认 session_key 未完整导出"""
    with open("data/latest.json") as f:
        raw = f.read()
    # 仅在 session_key_patterns 中以 pattern 形式出现
    assert ":1780896220022" not in raw  # 原始 ID 不应出现

def test_no_secrets():
    """确认无 HA token / GitHub token 泄漏"""
    with open("data/latest.json") as f:
        raw = f.read()
    for keyword in ["ghp_", "github_pat_", "eyJ", "ha_token"]:
        assert keyword not in raw, f"发现疑似 token: {keyword}"
```

测试在 cron 任务前运行，失败则中止推送。

---

## 📚 参考资料

- [`./DESIGN.md`](./DESIGN.md) — 视觉规范
- [`./DATA_SCHEMA.md`](./DATA_SCHEMA.md) — 数据 schema
- [`../../docs/DASHBOARD_REGISTRY.md`](../../docs/DASHBOARD_REGISTRY.md) — 模块清单
- [OpenClaw SOUL.md § Boundaries](https://github.com/yrwd999/openclaw) — 隐私规范