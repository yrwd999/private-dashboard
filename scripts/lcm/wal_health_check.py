#!/usr/bin/env python3
"""
LCM WAL Health Check — 每日健康诊断

职责：
- 分析 WAL 文件大小、DB 增长率、归档新鲜度
- 对比 history/ 中的历史数据，检测趋势异常
- 将 health_alerts 写入 wal_health.json
- 由 lcm-wal-health cron 每日 03:00 执行

安全约束：只读，不写 lcm.db

配置（环境变量优先，默认值如下）：
  WAL_THRESHOLD_RATIO          WAL/DB 比例阈值（默认 0.10）
  WAL_THRESHOLD_SIZE_MB        WAL 文件大小阈值 MB（默认 50）
  WAL_THRESHOLD_ARCHIVE_DAYS   归档新鲜度阈值（默认 7）
  WAL_THRESHOLD_MSG_DROP       消息量暴跌阈值 0-1（默认 0.80）
  LCM_REPO_DIR                 仓库路径（默认 /mnt/github/private-dashboard）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
REPO_DIR = Path(os.environ.get("LCM_REPO_DIR", "/mnt/github/private-dashboard"))
DATA_DIR = REPO_DIR / "docs" / "lcm" / "data"
WAL_HEALTH_JSON = DATA_DIR / "wal_health.json"
HISTORY_DIR = DATA_DIR / "history"

# ── Thresholds (#7: env var 优先，backwards-compatible) ───────────────────
_THRESHOLD_DEFAULTS = {
    "WAL_THRESHOLD_RATIO": "0.10",
    "WAL_THRESHOLD_DAILY_GB": "0.05",
    "WAL_THRESHOLD_ARCHIVE_DAYS": "7",
    "WAL_THRESHOLD_MSG_DROP": "0.80",
    "WAL_SIZE_MB_WARN": "50",
}


def _get_threshold(name: str) -> float:
    return float(os.environ.get(name, _THRESHOLD_DEFAULTS.get(name, "0")))


# WAL 状态阈值
THRESH_WAL_DB_RATIO = _get_threshold("WAL_THRESHOLD_RATIO")
THRESH_DB_DAILY_GB = _get_threshold("WAL_THRESHOLD_DAILY_GB")
THRESH_ARCHIVE_DAYS = int(_get_threshold("WAL_THRESHOLD_ARCHIVE_DAYS"))
THRESH_MSG_DROP_RATE = _get_threshold("WAL_THRESHOLD_MSG_DROP")
THRESH_WAL_SIZE_MB = _get_threshold("WAL_SIZE_MB_WARN")

# ── WAL 趋势分析 magic numbers (#8: 提取为命名常量) ────────────────────────
WAL_TREND_GROW_FACTOR = 1.5   # wal[0] > wal[1] * 1.5 → growing
WAL_TREND_SHRINK_FACTOR = 0.5  # wal[0] < wal[1] * 0.5 → shrinking
WAL_TREND_MAX_SAMPLES = 7     # 最多取 7 个数据点做趋势分析
WAL_SIZE_MB_WARN = 50        # WAL 文件绝对大小警告阈值

# ── Helpers ───────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_json(path: Path, data: dict) -> None:
    """原子写入：先写 .tmp，再 rename（幂等）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def get_db_sizes() -> dict:
    """读取当前 WAL + DB 大小（不连接 DB，只读文件 stat）"""
    db_path = Path("~/.openclaw/lcm.db").expanduser()  # #6: 直接用 Path，不用 os.path
    wal_path = db_path.with_suffix(db_path.suffix + "-wal")
    shm_path = db_path.with_suffix(db_path.suffix + "-shm")

    def _size(p: Path) -> float:
        try:
            return p.stat().st_size / 1024 / 1024
        except FileNotFoundError:
            return 0.0

    db_mb = _size(db_path)
    wal_mb = _size(wal_path)
    shm_mb = _size(shm_path)
    ratio = wal_mb / db_mb if db_mb > 0 else 0.0
    return {
        "db_size_mb": round(db_mb, 2),
        "wal_size_mb": round(wal_mb, 2),
        "shm_size_mb": round(shm_mb, 2),
        "wal_db_ratio": round(ratio, 4),
    }


def load_history(days: int = 14) -> list[dict]:
    """加载最近 N 天的 history 文件（按日期降序）"""
    snapshots = []
    today = datetime.now(timezone(timedelta(hours=8))).date()
    for i in range(days + 1):
        day = today - timedelta(days=i)
        f = HISTORY_DIR / f"{day.isoformat()}.json"
        d = load_json(f)
        if d:
            snapshots.append({"date": day.isoformat(), "data": d})
    return snapshots


def analyze_wal_trend(snapshots: list, current: dict) -> dict:
    """
    基于 history 分析 WAL/DB 增长趋势。

    #8: WAL_TREND_GROW_FACTOR / WAL_TREND_SHRINK_FACTOR / WAL_TREND_MAX_SAMPLES
    替代原来的 magic numbers 1.5 / 0.5 / 7。
    """
    if len(snapshots) < 2:
        return {"trend": "unknown", "samples": len(snapshots)}

    recent = snapshots[: WAL_TREND_MAX_SAMPLES]
    wal_sizes = [
        s["data"].get("overview", {}).get("wal_size_mb", 0)
        for s in recent
        if s["data"].get("overview")
    ]
    db_sizes = [
        s["data"].get("overview", {}).get("storage_size_mb", 0)
        for s in recent
        if s["data"].get("overview")
    ]

    # 计算 WAL 增长趋势（相比上一个数据点）
    trend = "stable"
    if len(wal_sizes) >= 2:
        if wal_sizes[0] > wal_sizes[1] * WAL_TREND_GROW_FACTOR:
            trend = "growing"
        elif wal_sizes[0] < wal_sizes[1] * WAL_TREND_SHRINK_FACTOR:
            trend = "shrinking"

    # 计算 DB 日均增长
    daily_growth = 0.0
    if len(db_sizes) >= 2 and db_sizes[0] > 0:
        daily_growth = (db_sizes[0] - db_sizes[-1]) / max(len(db_sizes) - 1, 1)

    return {
        "trend": trend,
        "daily_growth_mb": round(daily_growth, 3),
        "samples": len(snapshots),
        "wal_history": wal_sizes[:5],
        "db_history": db_sizes[:5],
    }


def check_archive_freshness(snapshots: list) -> dict:
    """检查最近归档是否及时"""
    if not snapshots:
        return {"fresh": None, "days_since_archive": None, "alert": "unknown"}

    latest = snapshots[0]
    overview = latest.get("data", {}).get("overview", {})
    days_ago = overview.get("last_archive_days_ago")

    if days_ago is None:
        return {"fresh": None, "days_since_archive": None, "alert": "unknown"}

    if days_ago == 0:
        return {"fresh": True, "days_since_archive": 0, "alert": "ok"}
    elif days_ago <= THRESH_ARCHIVE_DAYS:
        return {"fresh": True, "days_since_archive": days_ago, "alert": "ok"}
    else:
        return {"fresh": False, "days_since_archive": days_ago, "alert": "warning"}


def check_message_volume(snapshots: list) -> dict:
    """检查消息量是否有异常（突然暴跌可能意味着 LCM rotate 截断）"""
    if len(snapshots) < 2:
        return {"alert": "unknown", "samples": len(snapshots)}

    today_msg = snapshots[0]["data"].get("overview", {}).get("total_messages", 0)
    yesterday_msg = snapshots[1]["data"].get("overview", {}).get("total_messages", 0)

    if yesterday_msg == 0:
        return {"alert": "unknown", "samples": len(snapshots)}

    drop_rate = today_msg / yesterday_msg if yesterday_msg > 0 else 0

    if drop_rate < THRESH_MSG_DROP_RATE:
        return {
            "alert": "warning",
            "drop_rate": round(drop_rate, 3),
            "today": today_msg,
            "yesterday": yesterday_msg,
        }
    return {
        "alert": "ok",
        "drop_rate": round(drop_rate, 3),
        "today": today_msg,
        "yesterday": yesterday_msg,
    }


def build_health_report(
    current_sizes: dict, wal_trend: dict, archive: dict, msg_vol: dict
) -> list[dict]:
    """
    构建 health_alerts 列表。

    #8: THRESH_WAL_SIZE_MB 替代 magic number 50。
    """
    alerts = []
    generated_at = ts()

    # 1. WAL/DB 比例
    ratio = current_sizes["wal_db_ratio"]
    if ratio > THRESH_WAL_DB_RATIO:
        alerts.append({
            "level": "warning",
            "code": "WAL_RATIO_HIGH",
            "message": f"WAL/DB 比例过高：{ratio*100:.1f}%（阈值 {THRESH_WAL_DB_RATIO*100:.0f}%）",
            "value": ratio,
            "threshold": THRESH_WAL_DB_RATIO,
            "timestamp": generated_at,
        })
    else:
        alerts.append({
            "level": "info",
            "code": "WAL_RATIO_OK",
            "message": f"WAL/DB 比例正常：{ratio*100:.2f}%",
            "value": ratio,
            "threshold": THRESH_WAL_DB_RATIO,
            "timestamp": generated_at,
        })

    # 2. WAL 大小（#8: THRESH_WAL_SIZE_MB 替代 magic number 50）
    wal_mb = current_sizes["wal_size_mb"]
    if wal_mb > THRESH_WAL_SIZE_MB:
        alerts.append({
            "level": "warning",
            "code": "WAL_SIZE_LARGE",
            "message": f"WAL 文件较大：{wal_mb:.1f} MB，建议手动 checkpoint",
            "value": wal_mb,
            "threshold": THRESH_WAL_SIZE_MB,
            "timestamp": generated_at,
        })
    else:
        alerts.append({
            "level": "info",
            "code": "WAL_SIZE_NORMAL",
            "message": f"WAL 文件大小正常：{wal_mb:.2f} MB",
            "value": wal_mb,
            "threshold": THRESH_WAL_SIZE_MB,
            "timestamp": generated_at,
        })

    # 3. WAL 增长趋势
    trend = wal_trend["trend"]
    if trend == "growing":
        alerts.append({
            "level": "warning",
            "code": "WAL_TREND_GROWING",
            "message": f"WAL 持续增长（{wal_trend.get('daily_growth_mb', 0):.2f} MB/天），建议检查点",
            "trend": trend,
            "daily_growth_mb": wal_trend.get("daily_growth_mb", 0),
            "timestamp": generated_at,
        })
    elif trend == "stable":
        alerts.append({
            "level": "info",
            "code": "WAL_TREND_STABLE",
            "message": "WAL 增长趋势平稳",
            "trend": trend,
            "timestamp": generated_at,
        })

    # 4. 归档新鲜度
    archive_fresh = archive["alert"]
    if archive_fresh == "warning":
        alerts.append({
            "level": "warning",
            "code": "ARCHIVE_STALE",
            "message": f"已有 {archive['days_since_archive']} 天无归档（阈值 {THRESH_ARCHIVE_DAYS} 天）",
            "days_since_archive": archive["days_since_archive"],
            "threshold": THRESH_ARCHIVE_DAYS,
            "timestamp": generated_at,
        })
    elif archive_fresh == "ok":
        days = archive.get("days_since_archive", 0)
        alerts.append({
            "level": "success",
            "code": "ARCHIVE_FRESH",
            "message": f"归档新鲜（最近 {days} 天前）" if days > 0 else "今日已有归档记录",
            "days_since_archive": days,
            "timestamp": generated_at,
        })

    # 5. 消息量异常
    msg_alert = msg_vol["alert"]
    if msg_alert == "warning":
        alerts.append({
            "level": "warning",
            "code": "MSG_VOLUME_DROP",
            "message": f"消息量比昨日下跌 {(1-msg_vol['drop_rate'])*100:.0f}%，可能存在 LCM rotate 截断",
            "drop_rate": msg_vol["drop_rate"],
            "today": msg_vol["today"],
            "yesterday": msg_vol["yesterday"],
            "timestamp": generated_at,
        })
    elif msg_alert == "ok":
        alerts.append({
            "level": "info",
            "code": "MSG_VOLUME_NORMAL",
            "message": "消息量正常",
            "timestamp": generated_at,
        })

    # 6. DB 增长率
    daily_mb = wal_trend.get("daily_growth_mb", 0)
    daily_gb = daily_mb / 1024
    if daily_gb > THRESH_DB_DAILY_GB:
        alerts.append({
            "level": "warning",
            "code": "DB_GROWTH_HIGH",
            "message": f"DB 日增长率较高：{daily_mb:.1f} MB/天（阈值 {THRESH_DB_DAILY_GB*1024:.0f} MB）",
            "daily_growth_mb": round(daily_mb, 2),
            "threshold_mb": THRESH_DB_DAILY_GB * 1024,
            "timestamp": generated_at,
        })

    return alerts


def main() -> int:
    print(f"[{ts()}] LCM WAL Health Check started")

    # 1. 获取当前 DB/WAL 尺寸
    try:
        current_sizes = get_db_sizes()
        print(
            f"  DB: {current_sizes['db_size_mb']} MB | "
            f"WAL: {current_sizes['wal_size_mb']} MB | "
            f"ratio: {current_sizes['wal_db_ratio']*100:.2f}%"
        )
    except Exception as e:
        print(f"[ERROR] Cannot read DB files: {e}")
        return 2  # exit(2) = ConfigError / file-not-found

    # 2. 加载历史数据（最近 14 天）
    snapshots = load_history(days=14)
    print(f"  Loaded {len(snapshots)} history snapshots")

    # 3. 分析趋势
    wal_trend = analyze_wal_trend(snapshots, current_sizes)
    archive = check_archive_freshness(snapshots)
    msg_vol = check_message_volume(snapshots)
    print(
        f"  WAL trend: {wal_trend['trend']} | "
        f"Archive: {archive['alert']} | "
        f"Msg: {msg_vol['alert']}"
    )

    # 4. 构建 health_alerts
    alerts = build_health_report(current_sizes, wal_trend, archive, msg_vol)

    # 5. 写入 wal_health.json（原子写入）
    report = {
        "generated_at": ts(),
        "db_size_mb": current_sizes["db_size_mb"],
        "wal_size_mb": current_sizes["wal_size_mb"],
        "wal_db_ratio": current_sizes["wal_db_ratio"],
        "wal_trend": wal_trend,
        "archive_status": archive,
        "message_volume": msg_vol,
        "health_alerts": alerts,
    }
    save_json(WAL_HEALTH_JSON, report)
    print(f"  Wrote {WAL_HEALTH_JSON}")

    # 6. 统计
    warn_count = sum(1 for a in alerts if a["level"] == "warning")
    ok_count = sum(1 for a in alerts if a["level"] in ("info", "success"))
    print(f"  Alerts: {ok_count} ok, {warn_count} warning")
    print(f"[{ts()}] LCM WAL Health Check done")

    # Exit code: 0 = success, 1 = warnings
    if warn_count > 0:
        print(f"[WARN] {warn_count} warning(s) detected")
    return 1 if warn_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
