#!/usr/bin/env python3
"""
LCM Doctor Scan — 每周只读诊断

职责：
- 只读扫描 LCM SQLite，检测：孤立 summary、DAG 断裂、archived subagent 残留
- 将诊断报告写入 JSON
- 不做任何删除操作

数据来源：~/.openclaw/lcm.db（只读）
输出：docs/lcm/data/history/lcm-doctor-YYYY-MM-DD.json
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


def ts():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def load_history(days=30):
    """加载最近 N 天的 doctor 报告（用于趋势比对）"""
    reports = []
    today = datetime.now(timezone(timedelta(hours=8))).date()
    for i in range(1, days + 1):
        day = today - timedelta(days=i)
        f = HISTORY_DIR / f"lcm-doctor-{day.isoformat()}.json"
        if f.exists():
            try:
                with open(f) as fh:
                    reports.append(json.load(fh))
            except Exception:
                pass
    return reports


def check_summaries(conn):
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
        'check': 'orphaned_summaries',
        'passed': orphaned == 0,
        'count': orphaned,
        'message': f'{orphaned} orphaned summaries (no valid conversation)' if orphaned else 'No orphaned summaries',
    })

    # 2. 无 conversation 引用但有内容的 summary
    cur.execute("""
        SELECT COUNT(*) FROM summaries
        WHERE conversation_id IS NULL OR conversation_id = ''
    """)
    null_conv = cur.fetchone()[0]
    checks.append({
        'check': 'null_conversation_summaries',
        'passed': null_conv == 0,
        'count': null_conv,
        'message': f'{null_conv} summaries with null/empty conversation_id' if null_conv else 'All summaries have valid conversation_id',
    })

    # 3. 为空的 summary（content = '' 或 NULL 且 level = condensed）
    cur.execute("SELECT COUNT(*) FROM summaries WHERE (content = '' OR content IS NULL) AND kind = 'condensed'")
    empty_condensed = cur.fetchone()[0]
    checks.append({
        'check': 'empty_condensed_summaries',
        'passed': empty_condensed == 0,
        'count': empty_condensed,
        'message': f'{empty_condensed} condensed summaries are empty' if empty_condensed else 'No empty condensed summaries',
    })

    # 4. DAG 深度异常（depth > 10 认为是异常）
    cur.execute("SELECT COUNT(*) FROM summaries WHERE CAST(depth AS INTEGER) > 10")
    deep_levels = cur.fetchone()[0]
    checks.append({
        'check': 'deep_summary_levels',
        'passed': deep_levels == 0,
        'count': deep_levels,
        'message': f'{deep_levels} summaries with level > 10 (may indicate loop)' if deep_levels else 'Summary levels are reasonable',
    })

    # 5. 统计
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT conversation_id) FROM summaries")
    total, distinct_convs = cur.fetchone()
    checks.append({
        'check': 'summary_stats',
        'passed': True,
        'total': total,
        'distinct_conversations': distinct_convs,
        'message': f'{total} summaries across {distinct_convs} conversations',
    })

    return checks


def check_conversations(conn):
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
        'check': 'conversation_counts',
        'passed': True,
        'total': total_count,
        'active': active_count,
        'archived': archived_count,
        'message': f'{total_count} conversations ({active_count} active, {archived_count} archived)',
    })

    # 2. 无消息的 conversation
    cur.execute("""
        SELECT COUNT(*) FROM conversations c
        LEFT JOIN messages m ON c.conversation_id = m.conversation_id
        WHERE m.conversation_id IS NULL
    """)
    empty_convs = cur.fetchone()[0]
    checks.append({
        'check': 'empty_conversations',
        'passed': empty_convs == 0,
        'count': empty_convs,
        'message': f'{empty_convs} conversations with no messages' if empty_convs else 'All conversations have messages',
    })

    # 3. 超过 30 天未更新的 archived conversations
    thirty_days_ago = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=30)).isoformat()
    cur.execute("SELECT COUNT(*) FROM conversations WHERE active = 0 AND updated_at < ?", (thirty_days_ago,))
    stale_archived = cur.fetchone()[0]
    checks.append({
        'check': 'stale_archived_conversations',
        'passed': True,
        'count': stale_archived,
        'threshold_days': 30,
        'message': f'{stale_archived} archived conversations older than 30 days',
    })

    # 4. 查找可能的 agent subagent sessions（来自历史）
    cur.execute("""
        SELECT COUNT(DISTINCT session_key) FROM conversations
        WHERE session_key LIKE 'agent:%:subagent%' AND active = 0
    """)
    subagent_sessions = cur.fetchone()[0]
    checks.append({
        'check': 'archived_subagent_sessions',
        'passed': subagent_sessions == 0,
        'count': subagent_sessions,
        'message': f'{subagent_sessions} archived subagent sessions (may be junk)' if subagent_sessions else 'No archived subagent sessions',
    })

    return checks


def check_messages(conn):
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
        'check': 'orphaned_messages',
        'passed': orphan_msgs == 0,
        'count': orphan_msgs,
        'message': f'{orphan_msgs} orphaned messages' if orphan_msgs else 'No orphaned messages',
    })

    # 2. 消息量为 0 的 conversation（再次确认）
    cur.execute("SELECT COUNT(*) FROM conversations WHERE conversation_id NOT IN (SELECT DISTINCT conversation_id FROM messages WHERE conversation_id IS NOT NULL)")
    no_msg_convs = cur.fetchone()[0]
    checks.append({
        'check': 'zero_message_conversations',
        'passed': no_msg_convs == 0,
        'count': no_msg_convs,
        'message': f'{no_msg_convs} conversations with zero messages' if no_msg_convs else 'All conversations have messages',
    })

    # 3. 统计
    cur.execute("SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM messages")
    total, oldest, newest = cur.fetchone()
    checks.append({
        'check': 'message_stats',
        'passed': True,
        'total': total,
        'oldest_message': oldest,
        'newest_message': newest,
        'message': f'{total} messages ({oldest} → {newest})',
    })

    return checks


def check_wal(conn):
    """检查 WAL 状态"""
    checks = []
    wal_path = str(DB_PATH) + '-wal'
    db_size_mb = DB_PATH.stat().st_size / 1024 / 1024 if DB_PATH.exists() else 0
    wal_size_mb = os.path.getsize(wal_path) / 1024 / 1024 if os.path.exists(wal_path) else 0
    ratio = wal_size_mb / db_size_mb if db_size_mb > 0 else 0

    checks.append({
        'check': 'wal_ratio',
        'passed': ratio < 0.10,
        'wal_size_mb': round(wal_size_mb, 2),
        'db_size_mb': round(db_size_mb, 2),
        'ratio': round(ratio, 4),
        'message': f'WAL/DB ratio: {ratio*100:.2f}% ({"OK" if ratio < 0.10 else "HIGH"})',
    })

    # WAL 文件大小绝对值
    checks.append({
        'check': 'wal_absolute_size',
        'passed': wal_size_mb < 50,
        'wal_size_mb': round(wal_size_mb, 2),
        'message': f'WAL size: {wal_size_mb:.2f} MB ({"OK" if wal_size_mb < 50 else "LARGE"})',
    })

    return checks


def check_backup_files():
    """检查 .bak 文件积累"""
    checks = []
    openclaw_dir = Path(os.path.expanduser("~/.openclaw"))
    bak_files = sorted(openclaw_dir.glob("lcm.db*.bak"))
    bak_count = len(bak_files)
    total_bak_size_mb = sum(f.stat().st_size for f in bak_files) / 1024 / 1024

    checks.append({
        'check': 'backup_file_count',
        'passed': bak_count < 10,
        'count': bak_count,
        'total_size_mb': round(total_bak_size_mb, 2),
        'message': f'{bak_count} .bak files ({total_bak_size_mb:.1f} MB)',
    })

    # 超过 30 天的 .bak 文件
    thirty_days_ago = datetime.now() - timedelta(days=30)
    old_baks = []
    for f in bak_files:
        age_days = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).days
        if age_days > 30:
            old_baks.append({'file': f.name, 'age_days': age_days, 'size_mb': round(f.stat().st_size / 1024 / 1024, 2)})

    checks.append({
        'check': 'old_backup_files',
        'passed': len(old_baks) == 0,
        'count': len(old_baks),
        'files': old_baks[:10],  # 最多显示 10 个
        'message': f'{len(old_baks)} .bak files older than 30 days' if old_baks else 'No stale .bak files',
    })

    return checks


def main():
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    output_path = HISTORY_DIR / f"lcm-doctor-{today}.json"

    print(f"[{ts()}] LCM Doctor Scan started")

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        sys.exit(1)

    # 只读连接
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.text_factory = str

    report = {
        'generated_at': ts(),
        'task': 'lcm-doctor-scan',
        'db_path': str(DB_PATH),
        'db_size_mb': round(DB_PATH.stat().st_size / 1024 / 1024, 2),
        'summary_checks': [],
        'conversation_checks': [],
        'message_checks': [],
        'wal_checks': [],
        'backup_checks': [],
        'overall': {'passed': True, 'warnings': 0, 'errors': 0},
    }

    try:
        report['summary_checks'] = check_summaries(conn)
        report['conversation_checks'] = check_conversations(conn)
        report['message_checks'] = check_messages(conn)
        report['wal_checks'] = check_wal(conn)
    finally:
        conn.close()

    report['backup_checks'] = check_backup_files()

    # 统计
    all_checks = (
        report['summary_checks'] +
        report['conversation_checks'] +
        report['message_checks'] +
        report['wal_checks'] +
        report['backup_checks']
    )
    errors = sum(1 for c in all_checks if not c.get('passed', True))
    warnings = sum(1 for c in all_checks if c.get('check', '').startswith('old_backup') and not c.get('passed', True))
    report['overall'] = {'passed': errors == 0, 'errors': errors, 'warnings': warnings}

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(output_path)

    print(f"  Wrote {output_path}")
    print(f"  Overall: {'PASSED' if report['overall']['passed'] else 'ISSUES FOUND'} ({errors} errors, {warnings} warnings)")
    for c in all_checks:
        if not c.get('passed', True):
            print(f"  [FAIL] {c['check']}: {c['message']}")

    print(f"[{ts()}] LCM Doctor Scan done")
    sys.exit(0 if errors == 0 else 1)


if __name__ == '__main__':
    main()
