#!/usr/bin/env python3
"""
LCM Doctor Scan — 每周只读诊断

职责：
- 只读扫描 LCM SQLite，检测：孤立 summary、DAG 断裂、archived subagent 残留
- 将诊断报告写入 JSON
- 不做任何删除操作

数据来源：~/.openclaw/lcm.db（只读）
输出：docs/lcm/data/history/lcm-doctor-YYYY-MM-DD.json

配置（环境变量优先）：
  LCM_DB_PATH  数据库路径（默认 ~/.openclaw/lcm.db）
  LCM_REPO_DIR 仓库路径（默认 /mnt/github/private-dashboard）
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.resolve()
# 允许通过环境变量覆盖，方便测试
DB_PATH = Path(
    __import__("os").environ.get("LCM_DB_PATH", "~/.openclaw/lcm.db")
).expanduser()

# ── Timezone ──────────────────────────────────────────────────────────────
TZ = timezone(timedelta(hours=8))


def ts() -> str:
    return datetime.now(TZ).isoformat()


# ── Thresholds (magic numbers → named constants) ─────────────────────────
DEPTH_THRESHOLD = 10   # summaries.depth > 10 → 疑似循环
STALE_ARCHIVE_DAYS = 30  # archived conversation 超过 N 天 → stale
BAK_COUNT_THRESHOLD = 10  # .bak 文件超过 N 个 → warning
BAK_AGE_THRESHOLD_DAYS = 30  # .bak 文件超过 N 天 → stale
WAL_RATIO_THRESHOLD = 0.10  # WAL/DB > 10% → warning
WAL_SIZE_WARN_MB = 50.0    # WAL > 50MB → large


def check_summaries(conn: sqlite3.Connection) -> list[dict]:
    """检查 summary 表完整性"""
    cur = conn.cursor()
    checks = []

    # 1. 孤立 summary（conversation_id 不存在）
    cur.execute("""
        SELECT COUNT(*) FROM summaries s
        LEFT JOIN conversations c ON s.conversation_id = c.conversation_id
        WHERE c.conversation_id IS NULL
    """)
    orphaned = cur.fetchone()[0]
    checks.append({
        "check": "orphaned_summaries",
        "passed": orphaned == 0,
        "count": orphaned,
        "message": (
            f"{orphaned} orphaned summaries (no valid conversation)"
            if orphaned else "No orphaned summaries"
        ),
    })

    # 2. 无 conversation 引用但有内容的 summary
    cur.execute("""
        SELECT COUNT(*) FROM summaries
        WHERE conversation_id IS NULL OR conversation_id = ''
    """)
    null_conv = cur.fetchone()[0]
    checks.append({
        "check": "null_conversation_summaries",
        "passed": null_conv == 0,
        "count": null_conv,
        "message": (
            f"{null_conv} summaries with null/empty conversation_id"
            if null_conv else "All summaries have valid conversation_id"
        ),
    })

    # 3. 为空的 condensed summary
    cur.execute("""
        SELECT COUNT(*) FROM summaries
        WHERE (content = '' OR content IS NULL) AND kind = 'condensed'
    """)
    empty_condensed = cur.fetchone()[0]
    checks.append({
        "check": "empty_condensed_summaries",
        "passed": empty_condensed == 0,
        "count": empty_condensed,
        "message": (
            f"{empty_condensed} condensed summaries are empty"
            if empty_condensed else "No empty condensed summaries"
        ),
    })

    # 4. DAG 深度异常（#8: DEPTH_THRESHOLD 替代 magic number 10）
    cur.execute("""
        SELECT COUNT(*) FROM summaries
        WHERE CAST(depth AS INTEGER) > ?
    """, (DEPTH_THRESHOLD,))
    deep_levels = cur.fetchone()[0]
    checks.append({
        "check": "deep_summary_levels",
        "passed": deep_levels == 0,
        "count": deep_levels,
        "message": (
            f"{deep_levels} summaries with depth > {DEPTH_THRESHOLD} (may indicate loop)"
            if deep_levels else "Summary levels are reasonable"
        ),
    })

    # 5. 统计
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT conversation_id) FROM summaries")
    total, distinct_convs = cur.fetchone()
    checks.append({
        "check": "summary_stats",
        "passed": True,
        "total": total,
        "distinct_conversations": distinct_convs,
        "message": f"{total} summaries across {distinct_convs} conversations",
    })

    return checks


def check_conversations(conn: sqlite3.Connection) -> list[dict]:
    """检查 conversations 表"""
    cur = conn.cursor()
    checks = []

    # 1. 统计 active vs archived
    cur.execute("SELECT active, COUNT(*) FROM conversations GROUP BY active")
    rows = cur.fetchall()
    active_count = sum(n for a, n in rows if a == 1)
    archived_count = sum(n for a, n in rows if a == 0)
    total_count = active_count + archived_count

    checks.append({
        "check": "conversation_counts",
        "passed": True,
        "total": total_count,
        "active": active_count,
        "archived": archived_count,
        "message": (
            f"{total_count} conversations ({active_count} active, "
            f"{archived_count} archived)"
        ),
    })

    # 2. 无消息的 conversation
    cur.execute("""
        SELECT COUNT(*) FROM conversations c
        LEFT JOIN messages m ON c.conversation_id = m.conversation_id
        WHERE m.conversation_id IS NULL
    """)
    empty_convs = cur.fetchone()[0]
    checks.append({
        "check": "empty_conversations",
        "passed": empty_convs == 0,
        "count": empty_convs,
        "message": (
            f"{empty_convs} conversations with no messages"
            if empty_convs else "All conversations have messages"
        ),
    })

    # 3. 超过 30 天未更新的 archived conversations
    # #5 fix: 使用 aware datetime → ISO string 传给 SQLite
    stale_threshold = (
        datetime.now(TZ) - timedelta(days=STALE_ARCHIVE_DAYS)
    ).isoformat()
    cur.execute(
        "SELECT COUNT(*) FROM conversations WHERE active = 0 AND updated_at < ?",
        (stale_threshold,),
    )
    stale_archived = cur.fetchone()[0]
    checks.append({
        "check": "stale_archived_conversations",
        "passed": True,
        "count": stale_archived,
        "threshold_days": STALE_ARCHIVE_DAYS,
        "message": (
            f"{stale_archived} archived conversations older than "
            f"{STALE_ARCHIVE_DAYS} days"
        ),
    })

    # 4. 查找 archived subagent sessions
    cur.execute("""
        SELECT COUNT(DISTINCT session_key) FROM conversations
        WHERE session_key LIKE 'agent:%:subagent%' AND active = 0
    """)
    subagent_sessions = cur.fetchone()[0]
    checks.append({
        "check": "archived_subagent_sessions",
        "passed": subagent_sessions == 0,
        "count": subagent_sessions,
        "message": (
            f"{subagent_sessions} archived subagent sessions (may be junk)"
            if subagent_sessions else "No archived subagent sessions"
        ),
    })

    return checks


def check_messages(conn: sqlite3.Connection) -> list[dict]:
    """检查 messages 表"""
    cur = conn.cursor()
    checks = []

    # 1. 无 conversation 关联的 message
    cur.execute("""
        SELECT COUNT(*) FROM messages m
        LEFT JOIN conversations c ON m.conversation_id = c.conversation_id
        WHERE c.conversation_id IS NULL
    """)
    orphan_msgs = cur.fetchone()[0]
    checks.append({
        "check": "orphaned_messages",
        "passed": orphan_msgs == 0,
        "count": orphan_msgs,
        "message": (
            f"{orphan_msgs} orphaned messages"
            if orphan_msgs else "No orphaned messages"
        ),
    })

    # 2. 消息量为 0 的 conversation
    cur.execute("""
        SELECT COUNT(*) FROM conversations
        WHERE conversation_id NOT IN (
            SELECT DISTINCT conversation_id FROM messages
            WHERE conversation_id IS NOT NULL
        )
    """)
    no_msg_convs = cur.fetchone()[0]
    checks.append({
        "check": "zero_message_conversations",
        "passed": no_msg_convs == 0,
        "count": no_msg_convs,
        "message": (
            f"{no_msg_convs} conversations with zero messages"
            if no_msg_convs else "All conversations have messages"
        ),
    })

    # 3. 统计
    cur.execute("""
        SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM messages
    """)
    total, oldest, newest = cur.fetchone()
    checks.append({
        "check": "message_stats",
        "passed": True,
        "total": total,
        "oldest_message": oldest,
        "newest_message": newest,
        "message": f"{total} messages ({oldest} → {newest})",
    })

    return checks


def check_wal(conn: sqlite3.Connection) -> list[dict]:
    """
    检查 WAL 状态。

    #5 fix: 所有 datetime 操作统一使用 aware-datetime（TZ=Asia/Shanghai）。
    #8 fix: WAL_RATIO_THRESHOLD / WAL_SIZE_WARN_MB 替代 magic numbers。
    """
    checks = []
    wal_path = DB_PATH.with_suffix(DB_PATH.suffix + "-wal")

    def _size(p: Path) -> float:
        try:
            return p.stat().st_size / 1024 / 1024
        except FileNotFoundError:
            return 0.0

    db_size_mb = _size(DB_PATH)
    wal_size_mb = _size(wal_path)
    ratio = wal_size_mb / db_size_mb if db_size_mb > 0 else 0.0

    checks.append({
        "check": "wal_ratio",
        "passed": ratio < WAL_RATIO_THRESHOLD,
        "wal_size_mb": round(wal_size_mb, 2),
        "db_size_mb": round(db_size_mb, 2),
        "ratio": round(ratio, 4),
        "message": (
            f"WAL/DB ratio: {ratio*100:.2f}% "
            f"({'OK' if ratio < WAL_RATIO_THRESHOLD else 'HIGH'})"
        ),
    })

    checks.append({
        "check": "wal_absolute_size",
        "passed": wal_size_mb < WAL_SIZE_WARN_MB,
        "wal_size_mb": round(wal_size_mb, 2),
        "message": (
            f"WAL size: {wal_size_mb:.2f} MB "
            f"({'OK' if wal_size_mb < WAL_SIZE_WARN_MB else 'LARGE'})"
        ),
    })

    return checks


def check_backup_files() -> list[dict]:
    """
    检查 .bak 文件积累。

    #3 fix: 使用 aware datetime（统一 TZ 体系）计算文件 age，
           避免与 check_wal / check_conversations 的 naive-aware 混用问题。
    #5 fix: 统一使用 timezone(timedelta(hours=8))。
    #8 fix: BAK_COUNT_THRESHOLD / BAK_AGE_THRESHOLD_DAYS 替代 magic numbers。
    #10 fix: 直接用 Path，不用 os.path.expanduser。
    """
    checks = []
    openclaw_dir = Path("~/.openclaw").expanduser()
    bak_files = sorted(openclaw_dir.glob("lcm.db*.bak"))
    bak_count = len(bak_files)
    total_bak_size_mb = sum(f.stat().st_size for f in bak_files) / 1024 / 1024

    checks.append({
        "check": "backup_file_count",
        "passed": bak_count < BAK_COUNT_THRESHOLD,
        "count": bak_count,
        "total_size_mb": round(total_bak_size_mb, 2),
        "message": f"{bak_count} .bak files ({total_bak_size_mb:.1f} MB)",
    })

    # #3 fix: aware datetime 计算 age_days
    now_aware = datetime.now(TZ)
    old_baks = []
    for f in bak_files:
        mtime_aware = datetime.fromtimestamp(f.stat().st_mtime, tz=TZ)
        age_days = (now_aware - mtime_aware).days
        if age_days > BAK_AGE_THRESHOLD_DAYS:
            old_baks.append({
                "file": f.name,
                "age_days": age_days,
                "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            })

    checks.append({
        "check": "old_backup_files",
        "passed": len(old_baks) == 0,
        "count": len(old_baks),
        "files": old_baks[:10],
        "message": (
            f"{len(old_baks)} .bak files older than {BAK_AGE_THRESHOLD_DAYS} days"
            if old_baks else "No stale .bak files"
        ),
    })

    return checks


def main() -> int:
    today = datetime.now(TZ).date().isoformat()
    output_path = REPO_DIR / "docs" / "lcm" / "data" / "history" / f"lcm-doctor-{today}.json"

    print(f"[{ts()}] LCM Doctor Scan started")

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        return 2

    # 只读连接
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.text_factory = str

    report = {
        "generated_at": ts(),
        "task": "lcm-doctor-scan",
        "db_path": str(DB_PATH),
        "db_size_mb": round(DB_PATH.stat().st_size / 1024 / 1024, 2),
        "summary_checks": [],
        "conversation_checks": [],
        "message_checks": [],
        "wal_checks": [],
        "backup_checks": [],
        "overall": {"passed": True, "warnings": 0, "errors": 0},
    }

    try:
        report["summary_checks"] = check_summaries(conn)
        report["conversation_checks"] = check_conversations(conn)
        report["message_checks"] = check_messages(conn)
        report["wal_checks"] = check_wal(conn)
    finally:
        conn.close()

    report["backup_checks"] = check_backup_files()

    all_checks = (
        report["summary_checks"]
        + report["conversation_checks"]
        + report["message_checks"]
        + report["wal_checks"]
        + report["backup_checks"]
    )
    errors = sum(1 for c in all_checks if not c.get("passed", True))
    # warnings: old_backup_files 失败才算 warning
    warnings = sum(
        1 for c in all_checks
        if c.get("check", "").startswith("old_backup") and not c.get("passed", True)
    )
    report["overall"] = {
        "passed": errors == 0,
        "errors": errors,
        "warnings": warnings,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(output_path)

    print(f"  Wrote {output_path}")
    print(
        f"  Overall: {'PASSED' if report['overall']['passed'] else 'ISSUES FOUND'} "
        f"({errors} errors, {warnings} warnings)"
    )
    for c in all_checks:
        if not c.get("passed", True):
            print(f"  [FAIL] {c['check']}: {c['message']}")

    print(f"[{ts()}] LCM Doctor Scan done")
    # exit(0) = clean, exit(1) = errors found
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
