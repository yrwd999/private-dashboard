#!/usr/bin/env python3
"""
Tests for exporter_lcm.py

运行：python3 -m pytest scripts/tests/test_exporter_lcm.py -v
或： python3 scripts/tests/test_exporter_lcm.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# 让 import 找到 exporter_lcm.py
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from exporter_lcm import (
    build_meta, query_overview, query_agent_distribution,
    query_session_key_patterns, validate_output, scan_for_secrets,
    scan_for_forbidden_fields, sha256_prefix, size_mb, now_iso,
    SecurityError, DataError, ConfigError, FORBIDDEN_FIELD_NAMES,
)

SCRIPT_PATH = Path(__file__).parent.parent / "exporter_lcm.py"


# ─── Fixture：内存 DB ─────────────────────────────────────────────────────

def make_test_db() -> sqlite3.Connection:
    """构造一个最小测试 DB（不含敏感字段，仅用于验证查询逻辑）"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE conversations (
            conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            session_key TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            archived_at TEXT,
            title TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            identity_hash TEXT,
            transcript_entry_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE summaries (
            summary_id TEXT PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            depth INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            earliest_at TEXT,
            latest_at TEXT,
            descendant_count INTEGER NOT NULL DEFAULT 0,
            descendant_token_count INTEGER NOT NULL DEFAULT 0,
            source_message_token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            file_ids TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT 'unknown'
        );
    """)

    # 插入测试数据（注意：绝不写真实 session_key）
    conversations = [
        ("agent:main:dashboard:abc123", 1, None,        "测试会话1"),
        ("agent:main:dashboard:def456", 1, None,        "测试会话2"),
        ("agent:main:main",             1, None,        "测试会话3"),
        ("agent:geek:main",             0, "2026-06-20", "已归档1"),
        ("agent:geek:dashboard:xyz789", 0, "2026-06-22", "已归档2"),
        ("agent:main:web:1780000000",   0, "2026-06-23", "web已归档1"),
        ("agent:main:web:1780000001",   0, "2026-06-24", "web已归档2"),
        ("agent:homelab:main",          1, None,        "homelab"),
        ("agentroom:room1",             1, None,        "agentroom"),
    ]
    for i, (sk, active, archived_at, title) in enumerate(conversations, 1):
        conn.execute(
            "INSERT INTO conversations (session_id, session_key, active, archived_at, title) VALUES (?, ?, ?, ?, ?)",
            (f"sess_{i}", sk, active, archived_at, title),
        )

    # 插入消息
    for cid in range(1, 10):
        for seq in range(3):
            conn.execute(
                "INSERT INTO messages (conversation_id, seq, role, content, token_count, identity_hash, transcript_entry_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, seq, "user" if seq % 2 == 0 else "assistant",
                 f"测试消息内容-{cid}-{seq}", 100, f"hash_{cid}_{seq}", f"entry_{cid}_{seq}"),
            )

    # 插入摘要
    conn.execute(
        "INSERT INTO summaries (summary_id, conversation_id, kind, content, token_count) VALUES (?, ?, ?, ?, ?)",
        ("sum_leaf_1", 1, "leaf", "测试摘要内容", 50),
    )
    conn.execute(
        "INSERT INTO summaries (summary_id, conversation_id, kind, content, token_count) VALUES (?, ?, ?, ?, ?)",
        ("sum_cond_1", 2, "condensed", "测试压缩摘要", 80),
    )

    conn.commit()
    return conn


# ─── 单元测试 ────────────────────────────────────────────────────────────

def test_sha256_prefix():
    """路径哈希应稳定且非空"""
    h = sha256_prefix("/tmp/test.db")
    assert h.startswith("sha256:")
    assert len(h) > 20
    # 同样输入 → 同样输出
    assert sha256_prefix("/tmp/test.db") == h


def test_scan_for_secrets_clean():
    """干净文本不应触发 token 检测"""
    text = json.dumps({"name": "test", "value": 42, "msg": "今天天气不错"})
    assert scan_for_secrets(text) == []


def test_scan_for_secrets_github_pat():
    """检测到 GitHub PAT"""
    text = '{"token": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"}'
    hits = scan_for_secrets(text)
    assert len(hits) > 0


def test_scan_for_forbidden_fields_clean():
    """干净数据无黑名单字段"""
    data = {"overview": {"total": 10}, "agents": [{"name": "main", "count": 5}]}
    assert scan_for_forbidden_fields(data) == []


def test_scan_for_forbidden_fields_top_level():
    """检测顶层 content 字段"""
    data = {"content": "泄漏！"}
    hits = scan_for_forbidden_fields(data)
    assert "content" in hits


def test_scan_for_forbidden_fields_nested():
    """检测嵌套 content 字段"""
    data = {"messages": [{"id": 1, "content": "内部对话"}]}
    hits = scan_for_forbidden_fields(data)
    assert any("content" in h for h in hits)


def test_size_mb_missing():
    """文件不存在返回 0"""
    assert size_mb(Path("/nonexistent/path.db")) == 0.0


def test_now_iso_format():
    """时间戳应为 ISO 8601 格式"""
    ts = now_iso()
    assert "T" in ts
    assert "+" in ts or "Z" in ts


# ─── 集成测试（内存 DB） ──────────────────────────────────────────────────

def test_query_overview_basic():
    conn = make_test_db()
    result = query_overview(conn)
    # 共 9 个会话：active=1 的有 5 个（abc123, def456, main, homelab, agentroom）
    # archived=1 的有 4 个（geek:main, geek:dashboard, 2 个 web）
    assert result["total_conversations"] == 9
    assert result["active_conversations"] == 5
    assert result["archived_conversations"] == 4
    assert result["total_messages"] == 27  # 9 convs × 3 msgs
    assert result["total_summaries"] == 2
    assert result["leaf_summaries"] == 1
    assert result["condensed_summaries"] == 1
    conn.close()


def test_query_agent_distribution_basic():
    conn = make_test_db()
    result = query_agent_distribution(conn)
    assert len(result) >= 3  # main, geek, homelab, agentroom
    # 验证聚合正确
    main = next((r for r in result if r["agent"] == "main"), None)
    assert main is not None
    assert main["active"] == 3
    assert main["archived"] == 2
    conn.close()


def test_query_session_key_patterns_no_full_key():
    """关键：绝不导出完整 session_key"""
    conn = make_test_db()
    result = query_session_key_patterns(conn)
    result_str = json.dumps(result)
    # 原始 ID 不应出现
    assert "abc123" not in result_str
    assert "def456" not in result_str
    assert "xyz789" not in result_str
    assert "1780000000" not in result_str
    # 但 pattern 应该出现
    assert "agent:*:dashboard:*" in result_str
    assert "agent:*:web*" in result_str
    conn.close()


def test_validate_output_clean():
    """正常数据应通过校验"""
    data = {
        "meta": {"schema_version": "1.0"},
        "overview": {"total_conversations": 10},
        "agent_distribution": [{"agent": "main", "count": 5}],
    }
    validate_output(data)  # 不应抛异常


def test_validate_output_blocks_content():
    """包含 content 字段的数据应被拦截"""
    data = {
        "meta": {"schema_version": "1.0"},
        "messages": [{"id": 1, "content": "敏感内容"}],
    }
    try:
        validate_output(data)
        assert False, "应该抛 SecurityError"
    except SecurityError as e:
        assert "content" in str(e)


def test_validate_output_blocks_token():
    """包含 token 的数据应被拦截"""
    data = {
        "meta": {"schema_version": "1.0"},
        "config": {"token": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"},
    }
    try:
        validate_output(data)
        assert False, "应该抛 SecurityError"
    except SecurityError as e:
        assert "token" in str(e).lower() or "pattern" in str(e).lower()


def test_validate_output_blocks_wrong_schema():
    """schema_version 错误应被拦截"""
    data = {"meta": {"schema_version": "2.0"}}
    try:
        validate_output(data)
        assert False, "应该抛 DataError"
    except DataError as e:
        assert "schema_version" in str(e)


# ─── CLI 集成测试（真实流程） ────────────────────────────────────────────

def test_cli_dry_run_on_real_db():
    """对真实 LCM DB 做 dry-run（不写入文件）"""
    db_path = Path("~/.openclaw/lcm.db").expanduser()
    if not db_path.exists():
        print(f"[SKIP] LCM DB 不存在: {db_path}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "test_output"
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                "--db-path", str(db_path),
                "--output-dir", str(out_dir),
                "--no-history",
                "--dry-run",
            ],
            capture_output=True, text=True, timeout=30,
        )
        # dry-run 应成功
        assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        # 输出目录不应被创建（dry-run）
        # stdout 应包含 [DRY-RUN]
        assert "[DRY-RUN]" in result.stdout


def test_cli_real_run_creates_files():
    """完整流程：创建真实输出文件"""
    db_path = Path("~/.openclaw/lcm.db").expanduser()
    if not db_path.exists():
        print(f"[SKIP] LCM DB 不存在: {db_path}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "real_output"
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                "--db-path", str(db_path),
                "--output-dir", str(out_dir),
                "--no-history",  # 简化测试，只写 latest.json
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"

        # latest.json 应存在
        latest = out_dir / "latest.json"
        assert latest.exists()
        # 解析验证
        data = json.loads(latest.read_text())
        assert data["meta"]["schema_version"] == "1.0"
        assert "overview" in data
        assert "agent_distribution" in data
        assert "session_key_patterns" in data
        assert "message_trend_30d" in data
        assert "backup_status" in data
        assert "health_alerts" in data

        # 安全校验：JSON 中不应有 message.content
        assert "content" not in json.dumps(data)
        # 不应有完整 session_key
        assert "abc123def456" not in json.dumps(data)


def test_cli_handles_missing_db():
    """DB 不存在应返回非零退出码"""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "missing_db_test"
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                "--db-path", "/nonexistent/fake.db",
                "--output-dir", str(out_dir),
                "--no-history",
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 2  # ConfigError
        assert "ConfigError" in result.stderr or "不存在" in result.stderr


# ─── 主入口 ──────────────────────────────────────────────────────────────

def run_all():
    """纯 Python 运行所有测试（不依赖 pytest）"""
    import inspect
    tests = [
        (name, fn) for name, fn in globals().items()
        if name.startswith("test_") and callable(fn) and inspect.isfunction(fn)
    ]
    passed, failed, skipped = 0, 0, 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ⚠️  {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)