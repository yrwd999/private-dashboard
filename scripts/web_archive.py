#!/usr/bin/env python3
"""
LCM Web Session Archive — 每月归档孤立 Web Sessions

职责：
- 识别超过 3 天未活跃的 web sessions（agent:*:web-* 模式）
- 将会话 active=0，写入归档记录
- 产出：归档报告 JSON

阈值：
- 超过 3 天未更新的 web session → 归档
- 单次使用（消息数 ≤ 2）→ 低优先级归档

数据来源：~/.openclaw/lcm.db（读写）
输出：docs/lcm/data/history/lcm-web-archive-YYYY-MM-DD.json
"""

import json
import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path("/mnt/github/private-dashboard")
HISTORY_DIR = REPO_DIR / "docs" / "lcm" / "data" / "history"
DB_PATH = Path(os.path.expanduser("~/.openclaw/lcm.db"))
ARCHIVE_THRESHOLD_DAYS = 3  # 超过 3 天未更新


def ts():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def get_web_sessions(conn, threshold_days: int) -> list[dict]:
    """查找符合归档条件的 web sessions"""
    cur = conn.cursor()
    threshold = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=threshold_days)).isoformat()

    # 查找：web sessions + 超过阈值未更新
    cur.execute("""
        SELECT
            conversation_id,
            session_key,
            title,
            active,
            updated_at,
            created_at,
            (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.conversation_id) AS msg_count
        FROM conversations c
        WHERE c.session_key LIKE 'agent:%:web-%'
          AND c.active = 1
          AND c.updated_at < ?
        ORDER BY updated_at ASC
    """, (threshold,))

    rows = cur.fetchall()
    return [
        {
            'conversation_id': row[0],
            'session_key': row[1],
            'title': row[2],
            'active': row[3],
            'updated_at': row[4],
            'created_at': row[5],
            'message_count': row[6],
            'days_inactive': (datetime.now(timezone(timedelta(hours=8))) - datetime.fromisoformat(row[4])).days if row[4] else None,
        }
        for row in rows
    ]


def get_web_session_stats(conn) -> dict:
    """获取 web sessions 统计（用于归档前后的对比）"""
    cur = conn.cursor()

    # 当前活跃 web sessions 总数
    cur.execute("SELECT COUNT(*) FROM conversations WHERE session_key LIKE 'agent:%:web-%' AND active = 1")
    active_count = cur.fetchone()[0]

    # 当前 archived web sessions 总数
    cur.execute("SELECT COUNT(*) FROM conversations WHERE session_key LIKE 'agent:%:web-%' AND active = 0")
    archived_count = cur.fetchone()[0]

    # 最后归档时间
    cur.execute("""
        SELECT MAX(archived_at) FROM conversations
        WHERE session_key LIKE 'agent:%:web-%' AND active = 0 AND archived_at IS NOT NULL
    """)
    last_archive = cur.fetchone()[0]

    return {
        'active_web_sessions': active_count,
        'archived_web_sessions': archived_count,
        'last_archive_at': last_archive,
    }


def archive_sessions(sessions: list[dict], conn) -> dict:
    """执行归档，返回归档结果"""
    cur = conn.cursor()
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    archived_ids = []

    for session in sessions:
        try:
            cur.execute("""
                UPDATE conversations
                SET active = 0, archived_at = ?
                WHERE conversation_id = ? AND active = 1
            """, (now, session['conversation_id']))
            if cur.rowcount > 0:
                archived_ids.append(session['conversation_id'])
        except Exception as e:
            print(f"  [WARN] Failed to archive conversation {session['conversation_id']}: {e}")

    return {
        'requested': len(sessions),
        'archived': len(archived_ids),
        'archived_ids': archived_ids,
    }


def main():
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    output_path = HISTORY_DIR / f"lcm-web-archive-{today}.json"

    print(f"[{ts()}] LCM Web Archive started")
    print(f"  Threshold: {ARCHIVE_THRESHOLD_DAYS} days inactive")

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str

    # 归档前统计
    stats_before = get_web_session_stats(conn)
    print(f"  Before: {stats_before['active_web_sessions']} active web sessions, "
          f"{stats_before['archived_web_sessions']} archived")

    # 查找符合归档条件的 sessions
    sessions = get_web_sessions(conn, ARCHIVE_THRESHOLD_DAYS)
    print(f"  Found {len(sessions)} sessions eligible for archive")

    for s in sessions:
        print(f"    - {s['session_key']} | inactive {s['days_inactive']}d | {s['message_count']} msgs")

    if not sessions:
        result = {'requested': 0, 'archived': 0, 'archived_ids': []}
    else:
        result = archive_sessions(sessions, conn)
        print(f"  Archived {result['archived']} sessions")

    # 归档后统计
    stats_after = get_web_session_stats(conn)

    # 写报告
    report = {
        'generated_at': ts(),
        'task': 'lcm-web-archive',
        'threshold_days': ARCHIVE_THRESHOLD_DAYS,
        'stats_before': stats_before,
        'sessions_found': len(sessions),
        'archive_result': result,
        'stats_after': stats_after,
        'sessions': sessions,
    }

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(output_path)
    print(f"  Wrote {output_path}")

    print(f"[{ts()}] LCM Web Archive done")
    sys.exit(0)


if __name__ == '__main__':
    main()
