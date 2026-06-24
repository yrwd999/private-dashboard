#!/usr/bin/env python3
"""
LCM Web Session Archive — 每月归档孤立 Web Sessions

职责：
- 识别超过 N 天未活跃的 web sessions（agent:*:web-* 模式）
- 将会话 active=0，写入归档记录
- 产出：归档报告 JSON

数据来源：~/.openclaw/lcm.db（读写）
输出：docs/lcm/data/history/lcm-web-archive-YYYY-MM-DD.json

配置（环境变量优先，默认值如下）：
  WEB_ARCHIVE_THRESHOLD_DAYS  超过 N 天未更新 → 归档（默认 3）
  LCM_REPO_DIR                仓库路径（默认 /mnt/github/private-dashboard）
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path(os.environ.get("LCM_REPO_DIR", "/mnt/github/private-dashboard"))
HISTORY_DIR = REPO_DIR / "docs" / "lcm" / "data" / "history"
DB_PATH = Path(os.environ.get("LCM_DB_PATH", "~/.openclaw/lcm.db")).expanduser()


def sha256_prefix(s: str, length: int = 12) -> str:
    """Hash a string and return the first N chars with sha256: prefix."""
    import hashlib
    h = hashlib.sha256()
    h.update(s.encode("utf-8"))
    return f"sha256:{h.hexdigest()[:length]}"


# ── Threshold (#7: env var 优先) ─────────────────────────────────────────
ARCHIVE_THRESHOLD_DAYS = int(os.environ.get("WEB_ARCHIVE_THRESHOLD_DAYS", "3"))

# ── Timezone ──────────────────────────────────────────────────────────────
TZ = timezone(timedelta(hours=8))


def ts() -> str:
    return datetime.now(TZ).isoformat()


def _now_aware() -> datetime:
    """返回当前 UTC+8 aware datetime。"""
    return datetime.now(TZ)


def _make_aware_naive(dt: datetime) -> datetime:
    """
    将 naive datetime 转为 aware datetime（UTC+8）。

    LCM SQLite 的 updated_at / created_at 存储为 naive datetime（无时区信息），
    与 aware datetime 直接相减会抛出 TypeError。
    本函数确保算术安全。

    #1 fix: 统一使用 aware-datetime 体系，与 wal_health_check.py / backup_cleanup.py 一致。
    """
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=TZ)


def get_web_sessions(conn: sqlite3.Connection, threshold_days: int) -> list[dict]:
    """
    查找符合归档条件的 web sessions。

    #11 fix: 移除冗余的 `if row[4]` 检查——SQL 条件 c.updated_at < ?
    已排除 NULL 行（NULL < ? 在 SQLite 中为 NULL/False），因此 row[4] 永不为 NULL。
    """
    cur = conn.cursor()
    # threshold_datetime 是 aware，SQL 比较时 SQLite 会将其转 text（'2026-06-21T02:16:24'）
    # 与 DB 中的 naive ISO 字符串比较，行为正确（字典序比较）。
    threshold = (_now_aware() - timedelta(days=threshold_days)).isoformat()

    cur.execute("""
        SELECT
            conversation_id,
            session_key,
            title,
            active,
            updated_at,
            created_at,
            (SELECT COUNT(*) FROM messages m
             WHERE m.conversation_id = c.conversation_id) AS msg_count
        FROM conversations c
        WHERE c.session_key LIKE 'agent:%:web-%'
          AND c.active = 1
          AND c.updated_at < ?
        ORDER BY updated_at ASC
    """, (threshold,))

    rows = cur.fetchall()
    results = []
    for row in rows:
        updated_at_str = row[4]
        # #1 fix: aware-naive datetime 算术安全
        updated_at_aware = _make_aware_naive(datetime.fromisoformat(updated_at_str))
        days_inactive = (_now_aware() - updated_at_aware).days

        results.append({
            "conversation_id": row[0],
            "session_key": sha256_prefix(row[1]),  # sanitized — never raw
            "title": row[2],
            "active": row[3],
            "updated_at": updated_at_str,
            "created_at": row[5],
            "message_count": row[6],
            "days_inactive": days_inactive,
        })
    return results


def get_web_session_stats(conn: sqlite3.Connection) -> dict:
    """获取 web sessions 统计（用于归档前后的对比）"""
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM conversations
        WHERE session_key LIKE 'agent:%:web-%' AND active = 1
    """)
    active_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM conversations
        WHERE session_key LIKE 'agent:%:web-%' AND active = 0
    """)
    archived_count = cur.fetchone()[0]

    cur.execute("""
        SELECT MAX(archived_at) FROM conversations
        WHERE session_key LIKE 'agent:%:web-%'
          AND active = 0 AND archived_at IS NOT NULL
    """)
    last_archive = cur.fetchone()[0]

    return {
        "active_web_sessions": active_count,
        "archived_web_sessions": archived_count,
        "last_archive_at": last_archive,
    }


def archive_sessions(sessions: list[dict], conn: sqlite3.Connection) -> dict:
    """执行归档，返回归档结果。幂等：只更新 active=1 的行。"""
    cur = conn.cursor()
    now = _now_aware().isoformat()
    archived_ids = []

    for session in sessions:
        try:
            cur.execute("""
                UPDATE conversations
                SET active = 0, archived_at = ?
                WHERE conversation_id = ? AND active = 1
            """, (now, session["conversation_id"]))
            if cur.rowcount > 0:
                archived_ids.append(session["conversation_id"])
        except Exception as e:
            print(f"  [WARN] Failed to archive {session['conversation_id']}: {e}")

    return {
        "requested": len(sessions),
        "archived": len(archived_ids),
        "archived_ids": archived_ids,
    }


def main() -> int:
    today = _now_aware().date().isoformat()
    output_path = HISTORY_DIR / f"lcm-web-archive-{today}.json"

    print(f"[{ts()}] LCM Web Archive started")
    print(f"  Threshold: {ARCHIVE_THRESHOLD_DAYS} days inactive")

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        return 2  # ConfigError

    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str

    try:
        stats_before = get_web_session_stats(conn)
        print(
            f"  Before: {stats_before['active_web_sessions']} active, "
            f"{stats_before['archived_web_sessions']} archived"
        )

        sessions = get_web_sessions(conn, ARCHIVE_THRESHOLD_DAYS)
        print(f"  Found {len(sessions)} sessions eligible for archive")

        for s in sessions:
            print(
                f"    - {s['session_key']} | inactive {s['days_inactive']}d | "
                f"{s['message_count']} msgs"
            )

        if not sessions:
            result = {"requested": 0, "archived": 0, "archived_ids": []}
        else:
            result = archive_sessions(sessions, conn)
            print(f"  Archived {result['archived']} sessions")

        stats_after = get_web_session_stats(conn)

        report = {
            "generated_at": ts(),
            "task": "lcm-web-archive",
            "threshold_days": ARCHIVE_THRESHOLD_DAYS,
            "stats_before": stats_before,
            "sessions_found": len(sessions),
            "archive_result": result,
            "stats_after": stats_after,
            "sessions": sessions,
        }

        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        tmp.replace(output_path)
        print(f"  Wrote {output_path}")

        print(f"[{ts()}] LCM Web Archive done")
        return 0

    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return 4  # DataError
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
