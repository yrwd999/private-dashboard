#!/usr/bin/env python3
"""
LCM Backup Cleanup — 每季度清理历史 .bak 文件

职责：
- 扫描 ~/.openclaw 下的 lcm.db*.bak 文件
- 删除超过 90 天的 .bak 文件（安全清理）
- 产出：清理报告 JSON

安全约束：
- 只删 lcm.db*.bak，不删其他文件
- 只删超过 90 天的（季度末清理）
- 不删除最近 30 天内的（防止误删）

数据来源：文件系统
输出：docs/lcm/data/history/lcm-backup-cleanup-YYYY-MM-DD.json
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path("/mnt/github/private-dashboard")
HISTORY_DIR = REPO_DIR / "docs" / "lcm" / "data" / "history"
OPENCLAW_DIR = Path(os.path.expanduser("~/.openclaw"))
CUTOFF_DAYS = 90  # 超过 90 天才删
RECENT_PROTECTION_DAYS = 30  # 30 天内的即使满足也保护（双重保险）


def ts():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def find_bak_files() -> list[dict]:
    """查找所有 lcm.db*.bak 文件"""
    bak_files = sorted(OPENCLAW_DIR.glob("lcm.db*.bak"))
    results = []
    now = datetime.now(timezone(timedelta(hours=8)))

    for f in bak_files:
        age_days = (now - datetime.fromtimestamp(f.stat().st_mtime)).days
        size_mb = f.stat().st_size / 1024 / 1024
        results.append({
            'path': str(f),
            'name': f.name,
            'age_days': age_days,
            'size_mb': round(size_mb, 3),
            'mtime': datetime.fromtimestamp(f.stat().st_mtime, tz=timezone(timedelta(hours=8))).isoformat(),
            'qualifies': age_days >= CUTOFF_DAYS,
            'protected': age_days < RECENT_PROTECTION_DAYS,
        })

    return results


def cleanup_qualified(files: list[dict]) -> dict:
    """删除符合条件的 .bak 文件"""
    deleted = []
    failed = []
    total_freed_mb = 0.0

    for f in files:
        if not f['qualifies']:
            continue
        if f['protected']:
            continue  # 双重保护

        try:
            os.remove(f['path'])
            deleted.append(f['name'])
            total_freed_mb += f['size_mb']
            print(f"  [DEL] {f['name']} ({f['size_mb']:.2f} MB, {f['age_days']}d old)")
        except Exception as e:
            failed.append({'name': f['name'], 'error': str(e)})
            print(f"  [FAIL] {f['name']}: {e}")

    return {
        'deleted_count': len(deleted),
        'failed_count': len(failed),
        'total_freed_mb': round(total_freed_mb, 2),
        'deleted_files': deleted,
        'failed_files': failed,
    }


def main():
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    output_path = HISTORY_DIR / f"lcm-backup-cleanup-{today}.json"

    print(f"[{ts()}] LCM Backup Cleanup started")
    print(f"  Scan: {OPENCLAW_DIR}")
    print(f"  Policy: delete .bak files older than {CUTOFF_DAYS} days (protect < {RECENT_PROTECTION_DAYS}d)")

    # 1. 扫描
    all_bak = find_bak_files()
    total_size_mb = sum(f['size_mb'] for f in all_bak)
    qualified = [f for f in all_bak if f['qualifies'] and not f['protected']]
    qualified_size_mb = sum(f['size_mb'] for f in qualified)

    print(f"\n  Found {len(all_bak)} .bak files ({total_size_mb:.2f} MB total)")
    print(f"  {len(qualified)} qualify for cleanup ({qualified_size_mb:.2f} MB)")
    for f in all_bak:
        status = "DELETE" if f['qualifies'] and not f['protected'] else ("PROTECTED" if f['protected'] else "TOO_RECENT")
        print(f"    [{status}] {f['name']} | {f['age_days']}d | {f['size_mb']:.2f} MB")

    # 2. 清理
    result = cleanup_qualified(qualified)

    # 3. 写报告
    report = {
        'generated_at': ts(),
        'task': 'lcm-backup-cleanup',
        'policy': {
            'cutoff_days': CUTOFF_DAYS,
            'recent_protection_days': RECENT_PROTECTION_DAYS,
        },
        'scan_summary': {
            'total_files': len(all_bak),
            'total_size_mb': round(total_size_mb, 2),
            'qualified_count': len(qualified),
            'qualified_size_mb': round(qualified_size_mb, 2),
        },
        'cleanup_result': result,
        'remaining_files': [
            {'name': f['name'], 'age_days': f['age_days'], 'size_mb': f['size_mb']}
            for f in all_bak if not (f['qualifies'] and not f['protected'])
        ],
    }

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(output_path)
    print(f"\n  Wrote {output_path}")
    print(f"  Deleted: {result['deleted_count']} files, freed {result['total_freed_mb']:.2f} MB")
    print(f"[{ts()}] LCM Backup Cleanup done")
    sys.exit(0)


if __name__ == '__main__':
    main()
