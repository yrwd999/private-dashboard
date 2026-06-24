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

配置（环境变量优先）：
  CLEANUP_CUTOFF_DAYS          删除超过 N 天的备份（默认 90）
  CLEANUP_RECENT_PROTECTION_DAYS  最近 N 天内即使满足也保护（默认 30）
  LCM_DB_BACKUP_DIR            备份文件所在目录（默认 ~/.openclaw）
  LCM_REPO_DIR                 仓库路径（默认 /mnt/github/private-dashboard）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path(os.environ.get("LCM_REPO_DIR", "/mnt/github/private-dashboard"))
HISTORY_DIR = REPO_DIR / "docs" / "lcm" / "data" / "history"
OPENCLAW_DIR = Path(
    os.environ.get("LCM_DB_BACKUP_DIR", "~/.openclaw")
).expanduser()

# ── Thresholds (#7: env var 优先) ─────────────────────────────────────────
CUTOFF_DAYS = int(os.environ.get("CLEANUP_CUTOFF_DAYS", "90"))
RECENT_PROTECTION_DAYS = int(
    os.environ.get("CLEANUP_RECENT_PROTECTION_DAYS", "30")
)

# ── Timezone ──────────────────────────────────────────────────────────────
TZ = timezone(timedelta(hours=8))


def ts() -> str:
    return datetime.now(TZ).isoformat()


def find_bak_files() -> list[dict]:
    """
    查找所有 lcm.db*.bak 文件。

    #2 fix: age_days 计算使用 aware datetime 体系（TZ=Asia/Shanghai），
           与 check_conversations / check_wal 保持一致。
           原来 `datetime.fromtimestamp()` 不带 tz 会返回 naive datetime，
           与 now (aware) 相减会抛出 TypeError: can't subtract offset-naive
           and offset-aware datetimes。
    """
    bak_files = sorted(OPENCLAW_DIR.glob("lcm.db*.bak"))
    results = []
    now_aware = datetime.now(TZ)

    for f in bak_files:
        # #2 fix: 给 fromtimestamp 加上 tz=TZ，确保与 now_aware 运算类型一致
        mtime_aware = datetime.fromtimestamp(f.stat().st_mtime, tz=TZ)
        age_days = (now_aware - mtime_aware).days
        size_mb = f.stat().st_size / 1024 / 1024

        results.append({
            "path": str(f).replace(str(Path.home()), "~"),
            "name": f.name,
            "age_days": age_days,
            "size_mb": round(size_mb, 3),
            # mtime 用 aware isoformat，保证与 LCM 其他报告时间戳格式一致
            "mtime": mtime_aware.isoformat(),
            "qualifies": age_days >= CUTOFF_DAYS,
            "protected": age_days < RECENT_PROTECTION_DAYS,
        })

    return results


def cleanup_qualified(files: list[dict]) -> dict:
    """删除符合条件的 .bak 文件。幂等：只删存在的文件。"""
    deleted = []
    failed = []
    total_freed_mb = 0.0

    for f in files:
        if not f["qualifies"]:
            continue
        if f["protected"]:
            continue  # 双重保护

        try:
            os.remove(f["path"])
            deleted.append(f["name"])
            total_freed_mb += f["size_mb"]
            print(
                f"  [DEL] {f['name']} ({f['size_mb']:.2f} MB, "
                f"{f['age_days']}d old)"
            )
        except FileNotFoundError:
            # 文件已被其他进程删除，视为成功
            deleted.append(f["name"])
        except Exception as e:
            failed.append({"name": f["name"], "error": str(e)})
            print(f"  [FAIL] {f['name']}: {e}")

    return {
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "total_freed_mb": round(total_freed_mb, 2),
        "deleted_files": deleted,
        "failed_files": failed,
    }


def main() -> int:
    today = datetime.now(TZ).date().isoformat()
    output_path = HISTORY_DIR / f"lcm-backup-cleanup-{today}.json"

    print(f"[{ts()}] LCM Backup Cleanup started")
    print(f"  Scan: {OPENCLAW_DIR}")
    print(
        f"  Policy: delete .bak files older than {CUTOFF_DAYS} days "
        f"(protect < {RECENT_PROTECTION_DAYS}d)"
    )

    # 1. 扫描
    all_bak = find_bak_files()
    total_size_mb = sum(f["size_mb"] for f in all_bak)
    qualified = [f for f in all_bak if f["qualifies"] and not f["protected"]]
    qualified_size_mb = sum(f["size_mb"] for f in qualified)

    print(f"\n  Found {len(all_bak)} .bak files ({total_size_mb:.2f} MB total)")
    print(
        f"  {len(qualified)} qualify for cleanup ({qualified_size_mb:.2f} MB)"
    )
    for f in all_bak:
        if f["qualifies"] and not f["protected"]:
            status = "DELETE"
        elif f["protected"]:
            status = "PROTECTED"
        else:
            status = "TOO_RECENT"
        print(
            f"    [{status}] {f['name']} | {f['age_days']}d | "
            f"{f['size_mb']:.2f} MB"
        )

    # 2. 清理
    result = cleanup_qualified(qualified)

    # 3. 写报告
    report = {
        "generated_at": ts(),
        "task": "lcm-backup-cleanup",
        "policy": {
            "cutoff_days": CUTOFF_DAYS,
            "recent_protection_days": RECENT_PROTECTION_DAYS,
        },
        "scan_summary": {
            "total_files": len(all_bak),
            "total_size_mb": round(total_size_mb, 2),
            "qualified_count": len(qualified),
            "qualified_size_mb": round(qualified_size_mb, 2),
        },
        "cleanup_result": result,
        "remaining_files": [
            {"name": f["name"], "age_days": f["age_days"], "size_mb": f["size_mb"]}
            for f in all_bak
            if not (f["qualifies"] and not f["protected"])
        ],
    }

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(output_path)
    print(f"\n  Wrote {output_path}")
    print(
        f"  Deleted: {result['deleted_count']} files, "
        f"freed {result['total_freed_mb']:.2f} MB"
    )
    print(f"[{ts()}] LCM Backup Cleanup done")

    if result["failed_count"] > 0:
        return 1  # partial failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
