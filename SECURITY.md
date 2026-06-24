# Private Dashboard · Security Policy

> 全仓库强制安全规范 · 适用于所有模块（LCM、memory-tdai 及未来新增）
> 维护者：Ray · 最后更新：2026-06-24

---

## ⚠️ 适用范围

本文档是**全仓库通用安全约束**，所有模块的 Python 脚本、JavaScript、JSON 数据文件均受其约束。

| 模块 | 安全规范文档 | 说明 |
|------|-------------|------|
| **全仓库通用** | 本文件（SECURITY.md） | 绝对路径、会话密钥、凭据、PII |
| LCM Dashboard | [`docs/lcm/docs/SECURITY.md`](docs/lcm/docs/SECURITY.md) | LCM 特定字段黑名单、脱敏映射 |
| memory-tdai Dashboard | [`docs/memory-tdai/docs/SECURITY.md`](docs/memory-tdai/docs/SECURITY.md) | memory-tdai 特定约束 |

如本文件与模块级文档冲突，**以本文件为准**。

---

## 🚫 绝对禁止（Hard Constraints）

违反以下任一规则 → **立即停止，不得 commit**

### 1. 禁止输出绝对文件路径

**规则**：所有 JSON 输出文件中的文件路径字段，必须使用 `~` 表示 home 目录，或使用相对路径。禁止出现 `/home/username/`、`/Users/name/` 等绝对路径。

```python
# ❌ 错误
"db_path": "/home/yrwd999/.openclaw/lcm.db"
"path": "/home/yrwd999/.openclaw/lcm.db-2026-06-01.bak"

# ✅ 正确
"db_path": "~/.openclaw/lcm.db"
"path": "~/.openclaw/lcm.db-2026-06-01.bak"
```

**实现方式**：
```python
from pathlib import Path
home = str(Path.home())
"db_path": str(db_path).replace(home, "~")
# 或
"db_path": str(db_path.relative_to(Path.home()))
```

**受影响字段**：`db_path`、`source`、`path`、`backup_path`、`log_path`

### 2. 禁止输出原始 session_key

**规则**：任何 JSON 输出中不得出现原始 session_key 值。必须使用 SHA256 哈希前缀。

```python
# ❌ 错误
"session_key": "agent:main:dashboard:e3604e28-35c5-4e6e-a3eb-b1d314950402"

# ✅ 正确
"session_key": "sha256:a3f2b8c1d"
```

**实现方式**：
```python
import hashlib
def sha256_prefix(s: str, length: int = 12) -> str:
    h = hashlib.sha256()
    h.update(s.encode("utf-8"))
    return f"sha256:{h.hexdigest()[:length]}"
```

**聚合场景**：如果仅用于统计 pattern（如 `agent:*:web:*` 分布），直接输出聚合结果，不暴露任何 session_key。

### 3. 禁止输出消息内容

**规则**：禁止在 JSON 输出中包含 `message.content`、`message.large_content`、`summary.content` 等任何完整对话内容。

| 禁止字段 | 来源 | 风险 |
|---------|------|------|
| `content` / `large_content` | messages 表 | 完整对话内容 |
| `summary.content` | summaries 表 | 对话摘要 |
| `transcript_entry_id` | messages 表 | 内部引用 ID |
| `identity_hash` | messages 表 | 身份哈希 |

### 4. 禁止包含 API 密钥或凭证

**规则**：JSON、JavaScript、CSS、Python 脚本中禁止出现任何形式的凭据。

| 类型 | 匹配模式 | 示例 |
|------|---------|------|
| GitHub Token | `ghp_`、`github_pat_`、`ghs_` | `ghp_AbCdEfGhIjKlMnOpQrStUvWx` |
| OpenAI / DashScope Key | `sk-` + 20+ 字符 | `sk-ABCD1234...` |
| Home Assistant Token | `ha_`、` Bearer eyJ` | `ha_token: xxx` |
| 数据库连接字符串 | 含明文密码的 URI | `mysql://user:pass@host/` |
| JSON Web Token | `eyJ` + Base64 | `eyJhbGciOiJIUzI1NiJ9...` |

### 5. 禁止包含 PII

| 类型 | 匹配模式 |
|------|---------|
| 中国手机号 | `1[3-9]\d{9}` |
| 邮箱 | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` |
| 身份证号 | `\d{17}[\dXx]` |

### 6. 禁止包含内网地址（生产数据中）

**规则**：JSON 数据文件中禁止出现内网 IP 地址和开发环境 URL。

| 禁止 | 示例 |
|------|------|
| 内网 IP | `10.0.x.x`、`192.168.x.x`、`172.16.x.x` |
| 开发环境 URL | `localhost:18789`、`127.0.0.1`（在数据上下文中） |

> **说明**：文档性 URL（如 README.md 中的 `https://localhost:8000` 调试说明）不受此约束。

---

## 🔒 SQLite 访问约束

- 所有 Python 脚本连接 SQLite 时必须使用 `mode=ro`（只读模式）
- 禁止 `PRAGMA writeable_schema = 1`
- 禁止直接写入 `~/.openclaw/*.db` 文件（只读分析）

---

## ✅ Commit 前安全检查清单

**每次 commit 前**（尤其涉及 JSON 数据文件或 Python 脚本时）必须执行：

### 自动检查（必须通过）

```bash
# 1. 运行安全扫描器
python3 scripts/security_scan.py

# 扫描覆盖：
# - 绝对路径（/home/, /Users/）
# - session_key 明文
# - API key 模式（ghp_, sk-, eyJ, ha_token）
# - PII（手机号、邮箱）
# - message.content 泄漏

# 2. 检查失败 → abort commit
# 3. 检查通过 → 正常 commit
```

### 手动检查（必要时）

- [ ] 新增的 JSON 字段是否在白名单中？
- [ ] 新增的 Python 脚本是否引入了新的输出字段？
- [ ] 是否有新的第三方依赖被添加？
- [ ] 历史 JSON 文件是否有未脱敏的旧数据？（如有，需修复后 commit）

---

## 🛡️ 预防机制

### Git Pre-commit Hook（推荐）

将以下内容写入 `.git/hooks/pre-commit`（或通过 `chmod +x` 使其可执行）：

```bash
#!/bin/bash
# pre-commit hook: 安全扫描
set -e

echo "[security] Running pre-commit security scan..."

# 扫描所有暂存的 JSON 文件
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(json|py|js|html)$')

if [ -z "$STAGED_FILES" ]; then
    echo "[security] No relevant files staged, skipping."
    exit 0
fi

# 运行扫描器
python3 scripts/security_scan.py --files "$STAGED_FILES"

echo "[security] Scan passed."
```

> **注意**：如果 `scripts/security_scan.py` 不存在，请联系 Ray。

### 扫描器规格

`scripts/security_scan.py` 必须覆盖：

```python
# 必须检测的模式
PATTERNS = {
    "absolute_path":     r"/home/[a-zA-Z0-9_]+/",
    "session_key":       r"agent:[a-z]+:[a-z]+:[a-zA-Z0-9\-]+",
    "github_token":      r"gh[psto]_[a-zA-Z0-9]{36,}",
    "openai_key":        r"sk-[a-zA-Z0-9]{20,}",
    "jwt_token":         r"eyJ[a-zA-Z0-9_-]*\.eyJ",
    "ha_token":          r"ha_[a-zA-Z0-9]{20,}",
    "phone_number":      r"\b1[3-9]\d{9}\b",
    "message_content":   r'"content"\s*:\s*"[^"]{50,}"',
}
```

### 扫描器不存在时的替代方案

如果 `scripts/security_scan.py` 尚未创建，仍可通过以下命令做基础检查：

```bash
# 基础安全检查（无扫描器时使用）
grep -rE "/home/|/Users/|ghp_|ghs_|sk-[a-z]|1[3-9]\d{9}|eyJ[a-zA-Z0-9_-]*\.eyJ" \
  --include="*.json" --include="*.js" --include="*.html" \
  docs/ data/ || { echo "FOUND VIOLATIONS - DO NOT COMMIT"; exit 1; }
```

---

## 🔧 违规处理流程

| 场景 | 处理方式 |
|------|---------|
| **已发现违规内容** | 立即停止，修复后再 commit |
| **已推送违规内容到 main** | 立即回滚（`git revert` 或 `git reset`）+ 重新推送 + 通知 Ray |
| **不确定是否违规** | 暂停 commit，询问 Ray |

---

## 📂 相关文档

- [`README.md`](README.md) — 工程规范总览
- [`docs/DASHBOARD_REGISTRY.md`](docs/DASHBOARD_REGISTRY.md) — 模块注册表
- [`docs/lcm/docs/SECURITY.md`](docs/lcm/docs/SECURITY.md) — LCM 专项安全规范
- [`docs/memory-tdai/docs/SECURITY.md`](docs/memory-tdai/docs/SECURITY.md) — memory-tdai 专项规范
- [`docs/lcm/docs/DATA_SCHEMA.md`](docs/lcm/docs/DATA_SCHEMA.md) — LCM 数据 schema
