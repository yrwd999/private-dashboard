#!/usr/bin/env python3
"""
LCM WAL Health Check — 每日健康诊断

职责：
- 分析 WAL 文件大小、DB 增长率、归档新鲜度
- 对比 history/ 中的历史数据，检测趋势异常
- 将 health_alerts 写入 wal_health.json
- 由 lcm-wal-health cron 每日 03:00 执行

安全约束：只读，不写 lcm.db
"""

import json
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────
REPO_DIR = Path("/mnt/github/private-dashboard")
DATA_DIR = REPO_DIR / "docs" / "lcm" / "data"
LATEST_JSON = DATA_DIR / "latest.json"
WAL_HEALTH_JSON = DATA_DIR / "wal_health.json"
HISTORY_DIR = DATA_DIR / "history"

# ── Thresholds ──────────────────────────────────────────────────
THRESH_WAL_DB_RATIO = 0.10       # WAL/DB > 10% → warning
THRESH_DB_DAILY_GB = 0.05        # DB 日增长 > 50MB → warning
THRESH_ARCHIVE_DAYS = 7          # 超过 7 天无归档 → warning
THRESH_MSG_DROP_RATE = 0.80      # 消息量比前一天跌 80% → warning（可能截断）

# ── Helpers ─────────────────────────────────────────────────────
def ts():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def get_db_sizes() -> dict:
    """读取当前 WAL + DB 大小（不连接 DB，只读文件）"""
    db_path = Path(os.path.expanduser('~/.openclaw/lcm.db'))
    wal_path = Path(str(db_path) + '-wal')
    shm_path = Path(str(db_path) + '-shm')

    db_mb = db_path.stat().st_size / 1024 / 1024 if db_path.exists() else 0
    wal_mb = wal_path.stat().st_size / 1024 / 1024 if wal_path.exists() else 0
    shm_mb = shm_path.stat().st_size / 1024 / 1024 if shm_path.exists() else 0

    ratio = wal_mb / db_mb if db_mb > 0 else 0
    return {
        'db_size_mb': round(db_mb, 2),
        'wal_size_mb': round(wal_mb, 2),
        'shm_size_mb': round(shm_mb, 2),
        'wal_db_ratio': round(ratio, 4),
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
            snapshots.append({'date': day.isoformat(), 'data': d})
    return snapshots  # 降序（最新在前）


def analyze_wal_trend(snapshots: list, current: dict) -> dict:
    """基于 history 分析 WAL/DB 增长趋势"""
    if len(snapshots) < 2:
        return {'trend': 'unknown', 'samples': len(snapshots)}

    # 取最近 7 个数据点
    recent = snapshots[:7]
    wal_sizes = [s['data'].get('overview', {}).get('wal_size_mb', 0) for s in recent if s['data'].get('overview')]
    db_sizes = [s['data'].get('overview', {}).get('storage_size_mb', 0) for s in recent if s['data'].get('overview')]

    # 计算 WAL 增长率（相比上一个数据点）
    trend = 'stable'
    if len(wal_sizes) >= 2:
        if wal_sizes[0] > wal_sizes[1] * 1.5:
            trend = 'growing'
        elif wal_sizes[0] < wal_sizes[1] * 0.5:
            trend = 'shrinking'

    # 计算 DB 日均增长
    daily_growth = 0.0
    if len(db_sizes) >= 2 and db_sizes[0] > 0:
        daily_growth = (db_sizes[0] - db_sizes[-1]) / max(len(db_sizes) - 1, 1)

    return {
        'trend': trend,
        'daily_growth_mb': round(daily_growth, 3),
        'samples': len(snapshots),
        'wal_history': wal_sizes[:5],
        'db_history': db_sizes[:5],
    }


def check_archive_freshness(snapshots: list) -> dict:
    """检查最近归档是否及时"""
    if not snapshots:
        return {'fresh': None, 'days_since_archive': None, 'alert': 'unknown'}

    latest = snapshots[0]
    overview = latest.get('data', {}).get('overview', {})
    days_ago = overview.get('last_archive_days_ago')

    if days_ago is None:
        return {'fresh': None, 'days_since_archive': None, 'alert': 'unknown'}

    if days_ago == 0:
        return {'fresh': True, 'days_since_archive': 0, 'alert': 'ok'}
    elif days_ago <= THRESH_ARCHIVE_DAYS:
        return {'fresh': True, 'days_since_archive': days_ago, 'alert': 'ok'}
    else:
        return {'fresh': False, 'days_since_archive': days_ago, 'alert': 'warning'}


def check_message_volume(snapshots: list) -> dict:
    """检查消息量是否有异常（突然暴跌可能意味着 LCM rotate 截断）"""
    if len(snapshots) < 2:
        return {'alert': 'unknown', 'samples': len(snapshots)}

    today_msg = snapshots[0]['data'].get('overview', {}).get('total_messages', 0)
    yesterday_msg = snapshots[1]['data'].get('overview', {}).get('total_messages', 0)

    if yesterday_msg == 0:
        return {'alert': 'unknown', 'samples': len(snapshots)}

    drop_rate = today_msg / yesterday_msg if yesterday_msg > 0 else 0

    if drop_rate < THRESH_MSG_DROP_RATE:
        return {'alert': 'warning', 'drop_rate': round(drop_rate, 3), 'today': today_msg, 'yesterday': yesterday_msg}
    return {'alert': 'ok', 'drop_rate': round(drop_rate, 3), 'today': today_msg, 'yesterday': yesterday_msg}


def build_health_report(current_sizes: dict, wal_trend: dict, archive: dict, msg_vol: dict) -> dict:
    """构建 health_alerts 列表"""
    alerts = []
    generated_at = ts()

    # 1. WAL/DB 比例
    ratio = current_sizes['wal_db_ratio']
    if ratio > THRESH_WAL_DB_RATIO:
        alerts.append({
            'level': 'warning',
            'code': 'WAL_RATIO_HIGH',
            'message': f'WAL/DB 比例过高：{ratio*100:.1f}%（阈值 {THRESH_WAL_DB_RATIO*100:.0f}%）',
            'value': ratio,
            'threshold': THRESH_WAL_DB_RATIO,
            'timestamp': generated_at,
        })
    else:
        alerts.append({
            'level': 'info',
            'code': 'WAL_RATIO_OK',
            'message': f'WAL/DB 比例正常：{ratio*100:.2f}%',
            'value': ratio,
            'threshold': THRESH_WAL_DB_RATIO,
            'timestamp': generated_at,
        })

    # 2. WAL 大小
    wal_mb = current_sizes['wal_size_mb']
    if wal_mb > 50:
        alerts.append({
            'level': 'warning',
            'code': 'WAL_SIZE_LARGE',
            'message': f'WAL 文件较大：{wal_mb:.1f} MB，建议手动 checkpoint',
            'value': wal_mb,
            'threshold': 50,
            'timestamp': generated_at,
        })
    else:
        alerts.append({
            'level': 'info',
            'code': 'WAL_SIZE_NORMAL',
            'message': f'WAL 文件大小正常：{wal_mb:.2f} MB',
            'value': wal_mb,
            'threshold': 50,
            'timestamp': generated_at,
        })

    # 3. WAL 增长趋势
    trend = wal_trend['trend']
    if trend == 'growing':
        alerts.append({
            'level': 'warning',
            'code': 'WAL_TREND_GROWING',
            'message': f'WAL 持续增长（{wal_trend.get("daily_growth_mb", 0):.2f} MB/天），建议检查点',
            'trend': trend,
            'daily_growth_mb': wal_trend.get('daily_growth_mb', 0),
            'timestamp': generated_at,
        })
    elif trend == 'stable':
        alerts.append({
            'level': 'info',
            'code': 'WAL_TREND_STABLE',
            'message': 'WAL 增长趋势平稳',
            'trend': trend,
            'timestamp': generated_at,
        })

    # 4. 归档新鲜度
    archive_fresh = archive['alert']
    if archive_fresh == 'warning':
        alerts.append({
            'level': 'warning',
            'code': 'ARCHIVE_STALE',
            'message': f'已有 {archive["days_since_archive"]} 天无归档（阈值 {THRESH_ARCHIVE_DAYS} 天）',
            'days_since_archive': archive['days_since_archive'],
            'threshold': THRESH_ARCHIVE_DAYS,
            'timestamp': generated_at,
        })
    elif archive_fresh == 'ok':
        days = archive.get('days_since_archive', 0)
        alerts.append({
            'level': 'success',
            'code': 'ARCHIVE_FRESH',
            'message': f'归档新鲜（最近 {days} 天前）' if days > 0 else '今日已有归档记录',
            'days_since_archive': days,
            'timestamp': generated_at,
        })

    # 5. 消息量异常
    msg_alert = msg_vol['alert']
    if msg_alert == 'warning':
        alerts.append({
            'level': 'warning',
            'code': 'MSG_VOLUME_DROP',
            'message': f'消息量比昨日下跌 {(1-msg_vol["drop_rate"])*100:.0f}%，可能存在 LCM rotate 截断',
            'drop_rate': msg_vol['drop_rate'],
            'today': msg_vol['today'],
            'yesterday': msg_vol['yesterday'],
            'timestamp': generated_at,
        })
    elif msg_alert == 'ok':
        alerts.append({
            'level': 'info',
            'code': 'MSG_VOLUME_NORMAL',
            'message': '消息量正常',
            'timestamp': generated_at,
        })

    # 6. DB 增长率
    daily_gb = wal_trend.get('daily_growth_mb', 0) / 1024
    if daily_gb > THRESH_DB_DAILY_GB:
        alerts.append({
            'level': 'warning',
            'code': 'DB_GROWTH_HIGH',
            'message': f'DB 日增长率较高：{daily_gb*1024:.1f} MB/天（阈值 {THRESH_DB_DAILY_GB*1024:.0f} MB）',
            'daily_growth_mb': round(wal_trend.get('daily_growth_mb', 0), 2),
            'threshold_mb': THRESH_DB_DAILY_GB * 1024,
            'timestamp': generated_at,
        })

    return alerts


def main():
    print(f"[{ts()}] LCM WAL Health Check started")

    # 1. 获取当前 DB/WAL 尺寸
    try:
        current_sizes = get_db_sizes()
        print(f"  DB: {current_sizes['db_size_mb']} MB | WAL: {current_sizes['wal_size_mb']} MB | ratio: {current_sizes['wal_db_ratio']*100:.2f}%")
    except Exception as e:
        print(f"[ERROR] Cannot read DB files: {e}")
        sys.exit(2)

    # 2. 加载历史数据（最近 14 天）
    snapshots = load_history(days=14)
    print(f"  Loaded {len(snapshots)} history snapshots")

    # 3. 分析趋势
    wal_trend = analyze_wal_trend(snapshots, current_sizes)
    archive = check_archive_freshness(snapshots)
    msg_vol = check_message_volume(snapshots)
    print(f"  WAL trend: {wal_trend['trend']} | Archive: {archive['alert']} | Msg: {msg_vol['alert']}")

    # 4. 构建 health_alerts
    alerts = build_health_report(current_sizes, wal_trend, archive, msg_vol)

    # 5. 写入 wal_health.json
    report = {
        'generated_at': ts(),
        'db_size_mb': current_sizes['db_size_mb'],
        'wal_size_mb': current_sizes['wal_size_mb'],
        'wal_db_ratio': current_sizes['wal_db_ratio'],
        'wal_trend': wal_trend,
        'archive_status': archive,
        'message_volume': msg_vol,
        'health_alerts': alerts,
    }

    save_json(WAL_HEALTH_JSON, report)
    print(f"  Wrote {WAL_HEALTH_JSON}")

    # 6. 统计
    warn_count = sum(1 for a in alerts if a['level'] == 'warning')
    ok_count = sum(1 for a in alerts if a['level'] in ('info', 'success'))
    print(f"  Alerts: {ok_count} ok, {warn_count} warning")
    print(f"[{ts()}] LCM WAL Health Check done")

    if warn_count > 0:
        print(f"[WARN] {warn_count} warning(s) detected")
        sys.exit(1)  # 让 cron failureAlert 感知
    sys.exit(0)


if __name__ == '__main__':
    main()
