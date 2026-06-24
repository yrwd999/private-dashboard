#!/usr/bin/env python3
"""
LCM Data Exporter — Lossless-Claw Memory → JSON Aggregated Stats

⚠️  安全护栏（硬约束，违反即 abort）：
- 永不 SELECT content / large_content / identity_hash / transcript_entry_id
- 永不导出完整 session_key（仅按 pattern 聚合）
- 输出前扫描 JSON 字符串，发现黑名单字段/模式立即 abort
- 连接 SQLite 使用 mode=ro（只读），永不写入源 DB

按规格：./exporter-lcm-spec.md
按 schema：../lcm/docs/DATA_SCHEMA.md
按安全：../lcm/docs/SECURITY.md

Usage:
    python3 exporter_lcm.py --output-dir ./lcm/data
    python3 exporter_lcm.py --db-path ~/.openclaw/lcm.db --output-dir /tmp/test --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# ─── Magic numbers → named constants (#8) ───────────────────────────────────
# token_count * 4 ≈ 消息字节数估算（OpenClaw 平均 token≈4 字节 UTF-8）
TOKEN_BYTES_ESTIMATE = 4


# ─── 硬约束：黑名单（启动时 + 输出前双重校验） ─────────────────────────────

FORBIDDEN_FIELD_NAMES = frozenset({
    "content", "large_content", "identity_hash", "transcript_entry_id",
    "session_id",
})

# 检测疑似 token 的字符串模式（保守，宁可误报）
FORBIDDEN_TOKEN_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),           # GitHub PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),   # GitHub fine-grained PAT
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}"),          # JWT 前缀
    re.compile(r"-----BEGIN .+ PRIVATE KEY-----"),
]


# ─── 异常层级 ────────────────────────────────────────────────────────────

class ExporterError(Exception):
    """基础异常"""


class ConfigError(ExporterError):
    """配置/路径错误（DB 不存在、输出目录无权限等）"""


class SecurityError(ExporterError):
    """安全护栏触发：检测到黑名单字段/token 模式"""


class DataError(ExporterError):
    """数据错误：DB 损坏、SQL 失败、字段类型异常"""


# ─── 工具函数 ────────────────────────────────────────────────────────────

def sha256_prefix(path: str, length: int = 64) -> str:
    """计算文件路径哈希的前 N 位（不读取文件内容）"""
    h = hashlib.sha256()
    h.update(path.encode("utf-8"))
    return f"sha256:{h.hexdigest()[:length]}"


def size_mb(path: Path) -> float:
    """文件大小（MB），文件不存在返回 0"""
    try:
        return path.stat().st_size / 1024 / 1024
    except FileNotFoundError:
        return 0.0


def now_iso(tz_offset_hours: int = 8) -> str:
    """生成 ISO 8601 时间戳（默认 Asia/Shanghai +08:00）"""
    tz = timezone(timedelta(hours=tz_offset_hours))
    return datetime.now(tz).isoformat(timespec="seconds")


def scan_for_secrets(text: str) -> list[str]:
    """扫描文本中的可疑 token 模式，返回命中的描述列表"""
    hits = []
    for pattern in FORBIDDEN_TOKEN_PATTERNS:
        if pattern.search(text):
            hits.append(f"pattern: {pattern.pattern[:30]}...")
    return hits


def scan_for_forbidden_fields(obj: Any, path: str = "") -> list[str]:
    """递归扫描 dict/list 中的黑名单字段名"""
    hits = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            current_path = f"{path}.{key}" if path else key
            if key in FORBIDDEN_FIELD_NAMES:
                hits.append(current_path)
            hits.extend(scan_for_forbidden_fields(val, current_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(scan_for_forbidden_fields(item, f"{path}[{i}]"))
    return hits


# ─── DB 查询（白名单字段，永不 SELECT *） ─────────────────────────────────

def query_overview(conn: sqlite3.Connection) -> dict[str, int]:
    """核心指标"""
    row = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM conversations) AS total_conversations,
            (SELECT COUNT(*) FROM conversations WHERE active=1) AS active_conversations,
            (SELECT COUNT(*) FROM conversations WHERE active=0) AS archived_conversations,
            (SELECT COUNT(*) FROM messages) AS total_messages,
            (SELECT COUNT(*) FROM summaries) AS total_summaries,
            (SELECT COUNT(*) FROM summaries WHERE kind='leaf') AS leaf_summaries,
            (SELECT COUNT(*) FROM summaries WHERE kind='condensed') AS condensed_summaries
    """).fetchone()
    return dict(row)


def query_last_archive_days_ago(conn: sqlite3.Connection) -> int:
    """距最后归档天数（无归档则返回 -1）"""
    row = conn.execute("""
        SELECT CAST(julianday('now') - julianday(MAX(archived_at)) AS INTEGER) AS days_ago
        FROM conversations
        WHERE active=0 AND archived_at IS NOT NULL
    """).fetchone()
    return row["days_ago"] if row["days_ago"] is not None else -1


def query_agent_distribution(conn: sqlite3.Connection) -> list[dict]:
    """按 agent role 聚合活跃/归档/消息数"""
    rows = conn.execute("""
        SELECT
            CASE
                WHEN instr(session_key, ':') > 0
                THEN substr(
                    substr(session_key, 7),
                    1,
                    CASE
                        WHEN instr(substr(session_key, 7), ':') > 0
                        THEN instr(substr(session_key, 7), ':') - 1
                        ELSE length(substr(session_key, 7))
                    END
                )
                ELSE 'unknown'
            END AS agent_role,
            SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) AS archived
        FROM conversations
        WHERE session_key LIKE 'agent:%'
        GROUP BY agent_role
    """).fetchall()

    # 消息数单独查询（避免 N+1）
    msg_rows = conn.execute("""
        SELECT
            CASE
                WHEN instr(c.session_key, ':') > 0
                THEN substr(
                    substr(c.session_key, 7),
                    1,
                    CASE
                        WHEN instr(substr(c.session_key, 7), ':') > 0
                        THEN instr(substr(c.session_key, 7), ':') - 1
                        ELSE length(substr(c.session_key, 7))
                    END
                )
                ELSE 'unknown'
            END AS agent_role,
            COUNT(m.message_id) AS messages
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.conversation_id
        WHERE c.session_key LIKE 'agent:%'
        GROUP BY agent_role
    """).fetchall()

    msg_map = {r["agent_role"]: r["messages"] for r in msg_rows}
    result = []
    for r in rows:
        result.append({
            "agent": r["agent_role"],
            "active": r["active"],
            "archived": r["archived"],
            "messages": msg_map.get(r["agent_role"], 0),
        })
    # 按 messages 数倒序
    result.sort(key=lambda x: x["messages"], reverse=True)
    return result


def query_session_key_patterns(conn: sqlite3.Connection) -> list[dict]:
    """session_key pattern 聚合（绝不导出完整 session_key）"""
    patterns = [
        ("agent:*:dashboard:*", "agent:%:dashboard:%"),
        ("agent:*:main",        "agent:%:main"),
        ("agent:*:web*",        "agent:%:web%"),
        ("agent:*:ha-anomaly",  "agent:%:ha-anomaly"),
        ("agentroom:*",         "agentroom:%"),
        ("agent:homelab:*",     "agent:homelab:%"),
    ]
    results = []
    for label, like_pattern in patterns:
        # 排除已计入前一个模式的会话（避免重复计数）
        exclude_clause = ""
        if label == "agent:*:main":
            exclude_clause = "AND session_key NOT LIKE 'agent:%:dashboard:%'"
        elif label == "agent:*:web*":
            exclude_clause = ""  # web 单独算

        row = conn.execute(f"""
            SELECT
                COUNT(*) AS count,
                SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active
            FROM conversations
            WHERE session_key LIKE ?
            {exclude_clause}
        """, (like_pattern,)).fetchone()

        entry = {
            "pattern": label,
            "count": row["count"],
            "active": row["active"],
        }
        if label == "agent:*:web*" and row["active"] == 0 and row["count"] > 0:
            entry["note"] = "全部已归档"
        results.append(entry)
    return results


def query_message_trend_30d(conn: sqlite3.Connection) -> list[dict]:
    """近 30 天每日消息数 + 估算大小"""
    # #8: TOKEN_BYTES_ESTIMATE 注入 SQL（SQLite 不能引用 Python 变量）
    size_expr = f"SUM(token_count) * {TOKEN_BYTES_ESTIMATE} / 1024.0 / 1024.0"
    rows = conn.execute(f"""
        SELECT
            date(created_at) AS date,
            COUNT(*) AS count,
            {size_expr} AS size_mb
        FROM messages
        WHERE created_at >= datetime('now', '-30 days')
        GROUP BY date(created_at)
        ORDER BY date ASC
    """).fetchall()
    return [{"date": r["date"], "count": r["count"], "size_mb": round(r["size_mb"], 2)} for r in rows]


def query_backup_status(backup_dir: Path) -> dict:
    """扫描 LCM 备份目录"""
    files = []
    total_size = 0.0
    if backup_dir.exists():
        for f in sorted(backup_dir.glob("lcm.db.*.bak")):
            stat = f.stat()
            age_days = (datetime.now().timestamp() - stat.st_mtime) / 86400
            size = stat.st_size / 1024 / 1024
            total_size += size
            # 保留策略：rotate-latest 永保留；其他按 age 决定
            keep = f.name == "lcm.db.rotate-latest.bak"
            files.append({
                "name": f.name,
                "size_mb": round(size, 2),
                "age_days": int(age_days),
                "keep": keep,
            })
    return {"total_size_mb": round(total_size, 2), "files": files}


def generate_health_alerts(overview: dict, wal_size: float, last_archive_days: int) -> list[dict]:
    """基于当前状态生成告警"""
    alerts = []
    ts = now_iso()

    # WAL 状态
    if wal_size > 500:
        alerts.append({
            "level": "error", "code": "WAL_CRITICAL",
            "message": f"WAL 文件异常膨胀: {wal_size:.1f} MB，需立即 checkpoint",
            "timestamp": ts,
        })
    elif wal_size > 200:
        alerts.append({
            "level": "warning", "code": "WAL_OVERSIZE",
            "message": f"WAL 文件偏大: {wal_size:.1f} MB，建议 checkpoint",
            "timestamp": ts,
        })
    else:
        alerts.append({
            "level": "info", "code": "WAL_OK",
            "message": f"WAL 文件大小正常 ({wal_size:.1f} MB)",
            "timestamp": ts,
        })

    # DB 体积告警
    db_size = overview.get("storage_size_mb", 0)
    if db_size > 1000:
        alerts.append({
            "level": "warning", "code": "DB_LARGE",
            "message": f"LCM DB 超过 1GB: {db_size:.1f} MB，建议归档清理",
            "timestamp": ts,
        })

    # 归档新鲜度
    if last_archive_days == 0:
        alerts.append({
            "level": "success", "code": "ARCHIVE_FRESH",
            "message": "今日已有归档记录",
            "timestamp": ts,
        })
    elif last_archive_days > 30:
        alerts.append({
            "level": "warning", "code": "ARCHIVE_STALE",
            "message": f"超过 30 天未归档会话（{last_archive_days} 天）",
            "timestamp": ts,
        })

    return alerts


# ─── 主流程 ──────────────────────────────────────────────────────────────

def build_meta(db_path: Path) -> dict:
    return {
        "generated_at": now_iso(),
        "lcm_db_size_mb": round(size_mb(db_path), 2),
        "lcm_db_path_hash": sha256_prefix(str(db_path)),
        "schema_version": "1.0",
    }


def collect_data(db_path: Path, backup_dir: Path) -> dict:
    """连接 DB 并聚合所有数据"""
    if not db_path.exists():
        raise ConfigError(f"DB 不存在: {db_path}")

    # 只读连接 + URI 模式
    db_uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(db_uri, uri=True)
    except sqlite3.OperationalError as e:
        raise ConfigError(f"无法打开 DB（只读模式）: {e}") from e

    conn.row_factory = sqlite3.Row
    try:
        overview = query_overview(conn)
        overview["storage_size_mb"] = round(size_mb(db_path), 2)
        overview["last_archive_days_ago"] = query_last_archive_days_ago(conn)

        wal_path = db_path.with_suffix(db_path.suffix + "-wal")
        overview["wal_size_mb"] = round(size_mb(wal_path), 2)

        agent_dist = query_agent_distribution(conn)
        sk_patterns = query_session_key_patterns(conn)
        msg_trend = query_message_trend_30d(conn)
    except sqlite3.DatabaseError as e:
        raise DataError(f"SQL 查询失败: {e}") from e
    finally:
        conn.close()

    backup_status = query_backup_status(backup_dir)
    health_alerts = generate_health_alerts(overview, overview["wal_size_mb"], overview["last_archive_days_ago"])

    return {
        "meta": build_meta(db_path),
        "overview": overview,
        "agent_distribution": agent_dist,
        "session_key_patterns": sk_patterns,
        "message_trend_30d": msg_trend,
        "backup_status": backup_status,
        "health_alerts": health_alerts,
    }


def validate_output(data: dict) -> None:
    """输出前最后一道防线：扫描黑名单字段 + token 模式"""
    json_str = json.dumps(data, ensure_ascii=False)

    # 1. 黑名单字段名
    forbidden_hits = scan_for_forbidden_fields(data)
    if forbidden_hits:
        raise SecurityError(
            f"检测到黑名单字段: {forbidden_hits[:5]}{'...' if len(forbidden_hits) > 5 else ''}"
        )

    # 2. token 模式
    secret_hits = scan_for_secrets(json_str)
    if secret_hits:
        raise SecurityError(f"检测到疑似 token 模式: {secret_hits}")

    # 3. schema_version 校验
    if data.get("meta", {}).get("schema_version") != "1.0":
        raise DataError(f"schema_version 异常: {data.get('meta', {}).get('schema_version')}")


def write_outputs(data: dict, output_dir: Path, history: bool, dry_run: bool) -> list[Path]:
    """写入 latest.json + 可选 history"""
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    targets = [output_dir / "latest.json"]
    if history:
        history_dir = output_dir / "history"
        if not dry_run:
            history_dir.mkdir(parents=True, exist_ok=True)
        targets.append(history_dir / f"{today_str}.json")

    for target in targets:
        if dry_run:
            print(f"[DRY-RUN] would write: {target} ({len(json.dumps(data))} bytes)")
        else:
            # 原子写入：先写 .tmp，再 rename
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(target)
        written.append(target)

    return written


# ─── CLI ─────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LCM Data Exporter")
    p.add_argument(
        "--db-path",
        type=Path,
        default=Path("~/.openclaw/lcm.db").expanduser(),
        help="LCM SQLite 数据库路径（默认: ~/.openclaw/lcm.db）",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="JSON 输出目录",
    )
    p.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("~/.openclaw").expanduser(),
        help="LCM 备份所在目录（默认: ~/.openclaw）",
    )
    p.add_argument(
        "--no-history",
        action="store_true",
        help="不写 history/YYYY-MM-DD.json（只写 latest.json）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行：只打印将写入的文件，不实际写入",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="详细输出",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    start = datetime.now()

    try:
        if args.verbose:
            print(f"[INFO] DB path: {args.db_path}")
            print(f"[INFO] Output dir: {args.output_dir}")
            print(f"[INFO] Backup dir: {args.backup_dir}")
            print(f"[INFO] History: {not args.no_history}")
            print(f"[INFO] Dry-run: {args.dry_run}")

        data = collect_data(args.db_path, args.backup_dir)

        # 输出前校验
        validate_output(data)

        written = write_outputs(data, args.output_dir, history=not args.no_history, dry_run=args.dry_run)

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        result = {
            "executed_at": now_iso(),
            "task": "lcm-daily-snapshot",
            "operation": "export",
            "source": str(args.db_path).replace(str(Path.home()), "~"),  # sanitized
            "output": [str(p) for p in written],
            "result": "success",
            "duration_ms": duration_ms,
            "records": {
                "conversations": data["overview"]["total_conversations"],
                "active": data["overview"]["active_conversations"],
                "archived": data["overview"]["archived_conversations"],
                "messages_sampled": 0,  # 不导出消息内容
                "summaries_sampled": 0,
            },
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    except ConfigError as e:
        print(json.dumps({
            "executed_at": now_iso(), "task": "lcm-daily-snapshot",
            "operation": "export", "result": "error",
            "error_type": "ConfigError", "error_message": str(e),
        }, ensure_ascii=False), file=sys.stderr)
        return 2

    except SecurityError as e:
        # 安全告警：发到 stderr 并返回非零
        print(json.dumps({
            "executed_at": now_iso(), "task": "lcm-daily-snapshot",
            "operation": "export", "result": "security_abort",
            "error_type": "SecurityError", "error_message": str(e),
            "alert": "立即停止推送并人工审查",
        }, ensure_ascii=False), file=sys.stderr)
        return 3

    except DataError as e:
        print(json.dumps({
            "executed_at": now_iso(), "task": "lcm-daily-snapshot",
            "operation": "export", "result": "error",
            "error_type": "DataError", "error_message": str(e),
        }, ensure_ascii=False), file=sys.stderr)
        return 4

    except ExporterError as e:
        print(json.dumps({
            "executed_at": now_iso(), "task": "lcm-daily-snapshot",
            "operation": "export", "result": "error",
            "error_type": type(e).__name__, "error_message": str(e),
        }, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())