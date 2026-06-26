#!/usr/bin/env python3
"""
memory-tdai Exporter — 每日健康快照
======================================
数据源: ~/.openclaw/memory-tdai/vectors.db
         ~/.openclaw/openclaw.json
         ~/.openclaw/logs/openclaw-YYYY-MM-DD.log
输出:   docs/memory-tdai/data/latest.json
         docs/memory-tdai/data/history/YYYY-MM-DD.json

安全约束:
- 只读操作（vectors.db 仅 SELECT）
- 黑名单字段永不导出
- 无外部依赖（仅标准库）
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 1. Configuration (fail-fast)
# ---------------------------------------------------------------------------

OPENCLAW_DIR = Path(os.environ.get("OPENCLAW_DIR", Path.home() / ".openclaw"))
MEMORY_TDAI_DIR = OPENCLAW_DIR / "memory-tdai"
VECTORS_DB = MEMORY_TDAI_DIR / "vectors.db"
OPENCLAW_JSON = OPENCLAW_DIR / "openclaw.json"
LOG_DIR = OPENCLAW_DIR / "logs"
OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "memory-tdai" / "data"
HISTORY_DIR = OUTPUT_DIR / "history"

# 黑名单字段（永不导出）
BLACKLIST_PATTERNS = [
    "message_text",
    "session_key",
    "content",  # l1_records.content
    "metadata_json",
    "apiKey",
    "password",
    "token",
    "secret",
]

# 告警阈值
THRESHOLDS = {
    "l0_completeness_critical": 95.0,
    "l1_completeness_critical": 95.0,
    "wal_size_error_mb": 20.0,
    "wal_size_warning_mb": 5.0,
    "db_size_error_mb": 1024.0,
    "db_size_warning_mb": 500.0,
    "scene_block_stale_days": 30,
    "scene_block_warning_days": 7,
    "persona_stale_days": 90,
    "persona_warning_days": 30,
    "api_errors_critical": 50,
    "api_errors_warning": 5,
    "fts_health_score_error": 100.0,      # FTS health must be 100% for healthy
    "fts_health_score_warning": 95.0,
    "hp_retrievable_warning": 80.0,       # High-priority retrievable % floor
}

# ---------------------------------------------------------------------------
# 2. Typed Error Hierarchy
# ---------------------------------------------------------------------------


class ExporterError(Exception):
    """Base error for exporter failures."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class ConfigError(ExporterError):
    """Missing required config or file."""

    def __init__(self, message: str):
        super().__init__(message, "CONFIG_ERROR")


class DatabaseError(ExporterError):
    """SQLite read error."""

    def __init__(self, message: str):
        super().__init__(message, "DATABASE_ERROR")


class SecurityError(ExporterError):
    """Blacklisted field detected in output."""

    def __init__(self, field: str):
        super().__init__(f"黑名单字段泄漏: {field}", "SECURITY_ERROR")
        self.field = field


# ---------------------------------------------------------------------------
# 3. Structured Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("memory-tdai-exporter")
logger.setLevel(logging.INFO)


class JsonFormatter(logging.Formatter):
    """Structured JSON log output."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra"):
            entry.update(record.extra)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(verbose: bool = False) -> None:
    """Configure structured JSON logging to stderr."""
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)


# ---------------------------------------------------------------------------
# 4. SQL Whitelist（白名单查询，仅允许这些语句）
# ---------------------------------------------------------------------------

ALLOWED_SQL_QUERIES = {
    "l0_count": "SELECT COUNT(*) FROM l0_conversations",
    "l0_vec_count": "SELECT COUNT(*) FROM l0_vec",
    "l1_count": "SELECT COUNT(*) FROM l1_records",
    "l1_vec_count": "SELECT COUNT(*) FROM l1_vec",
    "l0_fts_count": "SELECT COUNT(*) FROM l0_fts",
    "l1_fts_count": "SELECT COUNT(*) FROM l1_fts",
    "l1_hp_count": "SELECT COUNT(*) FROM l1_records WHERE priority > 90",
    "l1_hp_fts_count": "SELECT COUNT(*) FROM l1_records WHERE priority > 90 AND EXISTS (SELECT 1 FROM l1_fts WHERE l1_fts.record_id = l1_records.record_id)",
    "db_size": """
        SELECT page_count * page_size AS size_bytes
        FROM pragma_page_count(), pragma_page_size()
    """,
}

_SQL_PATTERN = re.compile(
    # This pattern is used by validate_sql which ALSO does a direct dict lookup.
    # Here we match only the db_size query (balanced parens). COUNT queries are
    # validated purely via ALLOWED_SQL_QUERIES dict lookup in validate_sql.
    r"SELECT\\s+page_count\\s*\\*\\s*page_size\\s+AS\\s+size_bytes"
    r"\\s+FROM\\s+pragma_page_count\\(\\) \\s*,\\s*pragma_page_size\\(\\) ",
    re.IGNORECASE,
)



def validate_sql(sql: str) -> bool:
    """
    Verify SQL is in the allowed whitelist (no SELECT *, no joins).
    All queries are validated via ALLOWED_SQL_QUERIES dict values.
    """
    normalized = " ".join(sql.split())
    # Normalize stored values the same way for comparison
    allowed_normalized = {" ".join(v.split()) for v in ALLOWED_SQL_QUERIES.values()}
    return normalized in allowed_normalized


def guarded_query(conn: sqlite3.Connection, sql: str) -> Any:
    """Execute a whitelisted SQL query with security check."""
    if not validate_sql(sql):
        raise SecurityError(f"非法 SQL 查询: {sql[:80]}")
    cur = conn.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    return row[0] if row is not None else 0


# ---------------------------------------------------------------------------
# 5. Blacklist Scanner
# ---------------------------------------------------------------------------

_BLACKLIST_RE = re.compile(
    "|".join(re.escape(p) for p in BLACKLIST_PATTERNS),
    re.IGNORECASE,
)


def scan_blacklist(data: Any, path: str = "root") -> list[str]:
    """
    Recursively scan output data for blacklisted field names.
    Returns list of found violations.
    """
    violations = []
    if isinstance(data, dict):
        for k, v in data.items():
            if _BLACKLIST_RE.search(k):
                violations.append(f"{path}.{k}")
            violations.extend(scan_blacklist(v, f"{path}.{k}"))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            violations.extend(scan_blacklist(item, f"{path}[{i}]"))
    elif isinstance(data, str):
        if _BLACKLIST_RE.search(data):
            violations.append(f"{path} (string value)")
    return violations


# ---------------------------------------------------------------------------
# 6. Schema Validation
# ---------------------------------------------------------------------------

_REQUIRED_TOP_KEYS = frozenset([
    "meta", "l0", "l1", "l2", "l3",
    "storage", "recall", "api", "cleaning", "health_alerts",
])

_REQUIRED_META_KEYS = frozenset([
    "generated_at", "vectors_db_size_mb", "vectors_db_path",
    "jsonl_total_mb", "jsonl_file_count", "wal_size_mb", "schema_version",
])


def _validate_schema(data: dict) -> list[str]:
    """Validate output schema. Returns list of error messages (empty = OK)."""
    errors = []

    # Top-level keys
    missing = _REQUIRED_TOP_KEYS - frozenset(data.keys())
    if missing:
        errors.append(f"缺少顶层键: {missing}")

    # Meta sub-schema
    if "meta" in data:
        meta_missing = _REQUIRED_META_KEYS - frozenset(data["meta"].keys())
        if meta_missing:
            errors.append(f"缺少 meta 键: {meta_missing}")

    # health_alerts must be a list
    if "health_alerts" in data and not isinstance(data["health_alerts"], list):
        errors.append("health_alerts 必须是 list")

    return errors


# ---------------------------------------------------------------------------
# 7. Data Collectors
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _days_ago(ts: float | None) -> int:
    if ts is None:
        return 9999
    return (datetime.now().timestamp() - ts) / 86400


def _vec0_extension_path() -> Path | None:
    """Locate vec0.so under the openclaw npm tree."""
    npm_root = OPENCLAW_DIR / "npm" / "node_modules"
    candidates = list(npm_root.glob("sqlite-vec-linux-x64/vec0.so"))
    return candidates[0] if candidates else None


def collect_vectors_db_stats() -> dict[str, Any]:
    """Read vectors.db (read-only). Returns L0/L1/FTS counts and DB size.

    Requires vec0 extension for sqlite-vec virtual tables.
    Fails fast with ConfigError if the extension is not available.
    """
    if not VECTORS_DB.exists():
        raise ConfigError(f"vectors.db not found: {VECTORS_DB}")

    vec0_path = _vec0_extension_path()
    if vec0_path is None:
        raise ConfigError(
            f"vec0.so not found under {OPENCLAW_DIR}/npm/node_modules/"
        )

    conn = sqlite3.connect(f"file:{VECTORS_DB}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.enable_load_extension(True)
    conn.load_extension(str(vec0_path))

    try:
        l0_conversations = guarded_query(conn, ALLOWED_SQL_QUERIES["l0_count"])
        l0_vectors = guarded_query(conn, ALLOWED_SQL_QUERIES["l0_vec_count"])
        l1_records = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_count"])
        l1_vectors = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_vec_count"])
        l0_fts_count = guarded_query(conn, ALLOWED_SQL_QUERIES["l0_fts_count"])
        l1_fts_count = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_fts_count"])
        db_size_bytes = guarded_query(conn, ALLOWED_SQL_QUERIES["db_size"])

        return {
            "l0_conversations": l0_conversations,
            "l0_vectors": l0_vectors,
            "l1_records": l1_records,
            "l1_vectors": l1_vectors,
            "l0_fts_count": l0_fts_count,
            "l1_fts_count": l1_fts_count,
            "db_size_bytes": db_size_bytes,
        }
    finally:
        conn.close()


def collect_wal_size() -> float:
    """Return WAL file size in MB, or 0 if no WAL exists."""
    wal_path = Path(str(VECTORS_DB) + "-wal")
    if wal_path.exists():
        return wal_path.stat().st_size / (1024 * 1024)
    return 0.0


def collect_jsonl_stats() -> dict[str, Any]:
    """Return JSONL file count and total size (MB)."""
    conversations_dir = MEMORY_TDAI_DIR / "conversations"
    if not conversations_dir.exists():
        return {"file_count": 0, "total_mb": 0.0}

    jsonl_files = list(conversations_dir.glob("*.jsonl"))
    total_bytes = sum(f.stat().st_size for f in jsonl_files)
    return {
        "file_count": len(jsonl_files),
        "total_mb": round(total_bytes / (1024 * 1024), 3),
    }


def collect_scene_blocks() -> dict[str, Any]:
    """Return scene_blocks file list and freshness metadata."""
    scene_dir = MEMORY_TDAI_DIR / "scene_blocks"
    if not scene_dir.exists():
        return {
            "count": 0,
            "last_updated": None,
            "last_updated_days_ago": 9999,
            "file_list": [],
            "freshness": "stale",
        }

    md_files = sorted(scene_dir.glob("*.md"))
    file_list = [f.name for f in md_files]

    # Find most recently modified
    latest_mtime = max(f.stat().st_mtime for f in md_files) if md_files else None
    days_ago = _days_ago(latest_mtime)

    if days_ago <= THRESHOLDS["scene_block_warning_days"]:
        freshness = "healthy"
    elif days_ago <= THRESHOLDS["scene_block_stale_days"]:
        freshness = "warning"
    else:
        freshness = "stale"

    last_updated = (
        datetime.fromtimestamp(latest_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if latest_mtime else None
    )

    return {
        "count": len(md_files),
        "last_updated": last_updated,
        "last_updated_days_ago": round(days_ago, 1),
        "file_list": file_list,
        "freshness": freshness,
    }


def collect_persona() -> dict[str, Any]:
    """Return persona.md metadata (no content)."""
    persona_path = MEMORY_TDAI_DIR / "persona.md"
    if not persona_path.exists():
        return {
            "exists": False,
            "last_updated": None,
            "last_updated_days_ago": 9999,
            "file_size_bytes": 0,
            "freshness": "stale",
        }

    st = persona_path.stat()
    days_ago = _days_ago(st.st_mtime)

    if days_ago <= THRESHOLDS["persona_warning_days"]:
        freshness = "healthy"
    elif days_ago <= THRESHOLDS["persona_stale_days"]:
        freshness = "warning"
    else:
        freshness = "stale"

    return {
        "exists": True,
        "last_updated": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_updated_days_ago": round(days_ago, 1),
        "file_size_bytes": st.st_size,
        "freshness": freshness,

    }


def collect_recall_quality() -> dict[str, Any]:
    """
    Compute recall quality metrics from vectors.db (read-only).
    Returns fts_health_score and high_priority_retrievable_pct.
    """
    if not VECTORS_DB.exists():
        return {
            "fts_health_score": 100.0,
            "l1_fts_count": 0,
            "l1_records_count": 0,
            "hp_count": 0,
            "hp_fts_count": 0,
            "high_priority_retrievable_pct": 100.0,
        }

    vec0_path = _vec0_extension_path()
    if vec0_path is None:
        # vec0 not available — return safe defaults
        return {
            "fts_health_score": 0.0,
            "l1_fts_count": 0,
            "l1_records_count": 0,
            "hp_count": 0,
            "hp_fts_count": 0,
            "high_priority_retrievable_pct": 0.0,
        }

    conn = sqlite3.connect(f"file:{VECTORS_DB}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.enable_load_extension(True)
    conn.load_extension(str(vec0_path))

    try:
        l1_records_count = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_count"])
        l1_fts_count = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_fts_count"])
        hp_count = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_hp_count"])
        hp_fts_count = guarded_query(conn, ALLOWED_SQL_QUERIES["l1_hp_fts_count"])

        # fts_health_score: % of L1 records that have FTS entries
        if l1_records_count > 0:
            fts_health_score = round(l1_fts_count / l1_records_count * 100, 1)
        else:
            fts_health_score = 100.0

        # high_priority_retrievable_pct: % of hp records that have FTS
        if hp_count > 0:
            high_priority_retrievable_pct = round(hp_fts_count / hp_count * 100, 1)
        else:
            high_priority_retrievable_pct = 100.0  # no hp records = trivially healthy

        return {
            "fts_health_score": fts_health_score,
            "l1_fts_count": l1_fts_count,
            "l1_records_count": l1_records_count,
            "hp_count": hp_count,
            "hp_fts_count": hp_fts_count,
            "high_priority_retrievable_pct": high_priority_retrievable_pct,
        }
    finally:
        conn.close()


def collect_openclaw_config() -> dict[str, Any]:
    """Read openclaw.json, extract embedding/llm/recall/cleaner config (no keys)."""
    if not OPENCLAW_JSON.exists():
        raise ConfigError(f"openclaw.json not found: {OPENCLAW_JSON}")

    with open(OPENCLAW_JSON) as fh:
        raw = json.load(fh)

    try:
        plugin_cfg = (
            raw.get("plugins", {})
            .get("entries", {})
            .get("memory-tencentdb", {})
            .get("config", {})
        )
    except Exception as e:
        raise ConfigError(f"Failed to parse openclaw.json: {e}")

    embedding_cfg = plugin_cfg.get("embedding", {})
    llm_cfg = plugin_cfg.get("llm", {})
    recall_cfg = plugin_cfg.get("recall", {})
    cleaner_cfg = plugin_cfg.get("cleaner", {})

    return {
        "embedding": {
            "provider": embedding_cfg.get("provider"),
            "model": embedding_cfg.get("model"),
            "dimensions": embedding_cfg.get("dimensions"),
            "send_dimensions": embedding_cfg.get("sendDimensions"),
            # apiKey deliberately excluded
        },
        "llm": {
            "provider": llm_cfg.get("provider"),
            "model": llm_cfg.get("model"),
        },
        "recall": {
            "strategy": recall_cfg.get("strategy", "keyword"),
            "max_results": recall_cfg.get("maxResults", 5),
            "score_threshold": recall_cfg.get("scoreThreshold", 0.3),
            "timeout_ms": recall_cfg.get("timeoutMs", 10000),
        },
        "cleaning": {
            "retention_days": cleaner_cfg.get("retentionDays", 90),
            "clean_time": cleaner_cfg.get("cleanTime", "03:00"),
        },
    }


def collect_log_errors() -> dict[str, int]:
    """Parse today's log file for embedding error counts."""
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"openclaw-{today}.log"

    if not log_path.exists():
        logger.warning(f"Log file not found: {log_path}, returning zero errors")
        return {
            "http_400_batch_size": 0,
            "http_429_rate_limit": 0,
            "http_500_server": 0,
            "timeout": 0,
            "db_locked": 0,
            "total": 0,
        }

    error_counts: dict[str, int] = {
        "http_400_batch_size": 0,
        "http_429_rate_limit": 0,
        "http_500_server": 0,
        "timeout": 0,
        "db_locked": 0,
    }

    # Regex patterns from spec
    patterns = {
        "http_400_batch_size": re.compile(
            r"embedding.*HTTP 400|batch.*size.*exceed|MAX_BATCH_SIZE",
            re.IGNORECASE,
        ),
        "http_429_rate_limit": re.compile(
            r"embedding.*HTTP 429|rate.?limit", re.IGNORECASE
        ),
        "http_500_server": re.compile(r"embedding.*HTTP 5\d\d", re.IGNORECASE),
        "timeout": re.compile(r"embedding.*timeout|timed out", re.IGNORECASE),
        "db_locked": re.compile(r"database is locked|SQLITE_BUSY", re.IGNORECASE),
    }

    try:
        with open(log_path, errors="replace") as fh:
            for line in fh:
                for error_type, pattern in patterns.items():
                    if pattern.search(line):
                        error_counts[error_type] += 1
    except Exception as e:
        logger.warning(f"Failed to parse log {log_path}: {e}")

    error_counts["total"] = sum(error_counts.values())
    return error_counts


def compute_completeness_pct(total: int, vectors: int) -> float:
    if total == 0:
        return 100.0
    return round(vectors / total * 100, 1)


def build_health_alerts(
    l0_missing: int,
    l0_total: int,
    l1_missing: int,
    l1_total: int,
    wal_mb: float,
    log_errors: dict[str, int],
    scene_freshness: str,
    persona_freshness: str,
    recall_status: str,
    cleaner_l0_expired: int,
    ts: str,
    fts_health_score: float = 100.0,
    hp_retrievable_pct: float = 100.0,
) -> list[dict[str, Any]]:
    """Generate health alert list based on thresholds."""
    alerts = []

    l0_pct = compute_completeness_pct(l0_total, l0_total - l0_missing)
    l1_pct = compute_completeness_pct(l1_total, l1_total - l1_missing)

    # L0 vector completeness
    if l0_pct < THRESHOLDS["l0_completeness_critical"]:
        alerts.append({
            "level": "critical",
            "code": "L0_EMBEDDING_INCOMPLETE",
            "message": (
                f"L0 向量完整率 {l0_pct}%（缺失 {l0_missing} 条），"
                "根因：MAX_BATCH_SIZE=256 vs API limit=10"
            ),
            "value": l0_pct,
            "threshold": THRESHOLDS["l0_completeness_critical"],
            "timestamp": ts,
        })
    elif l0_missing > 0:
        alerts.append({
            "level": "warning",
            "code": "L0_EMBEDDING_INCOMPLETE",
            "message": f"L0 向量完整率 {l0_pct}%（缺失 {l0_missing} 条）",
            "value": l0_pct,
            "threshold": 99.0,
            "timestamp": ts,
        })

    # L1 vector completeness
    if l1_total > 0:
        if l1_pct < THRESHOLDS["l1_completeness_critical"]:
            alerts.append({
                "level": "warning",
                "code": "L1_EMBEDDING_INCOMPLETE",
                "message": f"L1 向量完整率 {l1_pct}%（缺失 {l1_missing} 条）",
                "value": l1_pct,
                "threshold": THRESHOLDS["l1_completeness_critical"],
                "timestamp": ts,
            })

    # WAL size
    if wal_mb > THRESHOLDS["wal_size_error_mb"]:
        alerts.append({
            "level": "error",
            "code": "WAL_OVERSIZED",
            "message": f"WAL 文件 {wal_mb:.1f}MB 超过阈值 {THRESHOLDS['wal_size_error_mb']}MB，可能有写入异常",
            "value": round(wal_mb, 2),
            "threshold": THRESHOLDS["wal_size_error_mb"],
            "timestamp": ts,
        })
    elif wal_mb > THRESHOLDS["wal_size_warning_mb"]:
        alerts.append({
            "level": "warning",
            "code": "WAL_LARGE",
            "message": f"WAL 文件 {wal_mb:.1f}MB（正常 < {THRESHOLDS['wal_size_warning_mb']}MB）",
            "value": round(wal_mb, 2),
            "threshold": THRESHOLDS["wal_size_warning_mb"],
            "timestamp": ts,
        })

    # HTTP 400 errors (batch size = most common issue)
    if log_errors["http_400_batch_size"] > THRESHOLDS["api_errors_critical"]:
        alerts.append({
            "level": "error",
            "code": "EMBEDDING_HTTP_400_BATCH",
            "message": f"过去 24h 产生 {log_errors['http_400_batch_size']} 次 HTTP 400 错误",
            "value": log_errors["http_400_batch_size"],
            "threshold": THRESHOLDS["api_errors_critical"],
            "timestamp": ts,
        })
    elif log_errors["http_400_batch_size"] > THRESHOLDS["api_errors_warning"]:
        alerts.append({
            "level": "warning",
            "code": "EMBEDDING_HTTP_400_BATCH",
            "message": f"过去 24h 产生 {log_errors['http_400_batch_size']} 次 HTTP 400 错误（batch size bug）",
            "value": log_errors["http_400_batch_size"],
            "threshold": THRESHOLDS["api_errors_warning"],
            "timestamp": ts,
        })

    # DB locked
    if log_errors["db_locked"] > 0:
        alerts.append({
            "level": "warning",
            "code": "DB_LOCKED",
            "message": f"过去 24h 产生 {log_errors['db_locked']} 次 database locked 错误",
            "value": log_errors["db_locked"],
            "timestamp": ts,
        })

    # Scene block freshness
    if scene_freshness == "stale":
        alerts.append({
            "level": "warning",
            "code": "SCENE_BLOCKS_STALE",
            "message": "Scene blocks 超过 30 天未更新",
            "timestamp": ts,
        })
    elif scene_freshness == "warning":
        alerts.append({
            "level": "info",
            "code": "SCENE_BLOCKS_AGED",
            "message": "Scene blocks 超过 7 天未更新",
            "timestamp": ts,
        })

    # Recall degraded
    if recall_status == "degraded":
        alerts.append({
            "level": "warning",
            "code": "RECALL_DEGRADED",
            "message": "Recall 降级为 keyword-only（向量完整率 < 95%）",
            "timestamp": ts,
        })

    # FTS index desync — fts_health_score < 100 means some L1 records not in FTS
    if fts_health_score < THRESHOLDS["fts_health_score_error"]:
        alerts.append({
            "level": "error",
            "code": "FTS_INDEX_DESYNC",
            "message": f"FTS5 索引不完整：健康分 {fts_health_score}%（应 = 100%）",
            "value": round(fts_health_score, 1),
            "threshold": THRESHOLDS["fts_health_score_error"],
            "timestamp": ts,
        })
    elif fts_health_score < THRESHOLDS["fts_health_score_warning"]:
        alerts.append({
            "level": "warning",
            "code": "FTS_INDEX_DESYNC",
            "message": f"FTS5 索引健康分 {fts_health_score}%（应 = 100%）",
            "value": round(fts_health_score, 1),
            "threshold": THRESHOLDS["fts_health_score_warning"],
            "timestamp": ts,
        })

    # High-priority retrievability low
    if hp_retrievable_pct < THRESHOLDS["hp_retrievable_warning"]:
        alerts.append({
            "level": "warning",
            "code": "RECALL_HP_RETRIEVE_LOW",
            "message": f"高优先级可检索率 {hp_retrievable_pct}%（priority > 90 且 FTS 命中），低于阈值 {THRESHOLDS['hp_retrievable_warning']}%",
            "value": round(hp_retrievable_pct, 1),
            "threshold": THRESHOLDS["hp_retrievable_warning"],
            "timestamp": ts,
        })

    # Cleaner effectiveness
    if cleaner_l0_expired == 0:
        alerts.append({
            "level": "warning",
            "code": "CLEAN_EFFECTIVENESS_LOW",
            "message": "Cleaner 连续 0 条过期记录（retention=90d 可能过长）",
            "timestamp": ts,
        })

    # Sort: critical > error > warning > info > success
    LEVEL_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3, "success": 4}
    alerts.sort(key=lambda a: (LEVEL_ORDER.get(a["level"], 5), a["timestamp"]))
    return alerts[:20]  # Cap at 20


def assemble_output(
    db_stats: dict[str, Any],
    config: dict[str, Any],
    log_errors: dict[str, int],
    scene_data: dict[str, Any],
    persona_data: dict[str, Any],
    jsonl_data: dict[str, Any],
    wal_mb: float,
    recall_quality: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the complete output JSON."""
    ts = _ts()

    l0_total = db_stats["l0_conversations"]
    l0_vectors = db_stats["l0_vectors"]
    l0_missing = max(0, l0_total - l0_vectors)
    l0_pct = compute_completeness_pct(l0_total, l0_vectors)

    l1_total = db_stats["l1_records"]
    l1_vectors = db_stats["l1_vectors"]
    l1_missing = max(0, l1_total - l1_vectors)
    l1_pct = compute_completeness_pct(l1_total, l1_vectors)

    db_size_mb = round(db_stats["db_size_bytes"] / (1024 * 1024), 1)
    recall_cfg = config.get("recall", {})
    recall_strategy = recall_cfg.get("strategy", "keyword")
    # Recall healthy only when both L0 completeness >= 95% AND FTS health = 100%
    recall_status = (
        "healthy"
        if l0_pct >= 95.0 and recall_quality["fts_health_score"] == 100.0
        else "degraded"
    )

    cleaning_cfg = config.get("cleaning", {})
    cleaning_retention = cleaning_cfg.get("retention_days", 90)

    # Estimate storage growth (placeholder — real calc needs history)
    storage_growth_per_day = 0.0

    alerts = build_health_alerts(
        l0_missing=l0_missing,
        l0_total=l0_total,
        l1_missing=l1_missing,
        l1_total=l1_total,
        wal_mb=wal_mb,
        log_errors=log_errors,
        scene_freshness=scene_data["freshness"],
        persona_freshness=persona_data["freshness"],
        recall_status=recall_status,
        cleaner_l0_expired=0,  # Cleaner hasn't run in this context — placeholder
        ts=ts,
        fts_health_score=recall_quality["fts_health_score"],
        hp_retrievable_pct=recall_quality["high_priority_retrievable_pct"],
    )

    output = {
        "meta": {
            "generated_at": ts,
            "vectors_db_size_mb": db_size_mb,
            "vectors_db_path": "memory-tdai/vectors.db",
            "jsonl_total_mb": jsonl_data["total_mb"],
            "jsonl_file_count": jsonl_data["file_count"],
            "wal_size_mb": round(wal_mb, 2),
            "schema_version": "1.1",
        },
        "l0": {
            "conversations": l0_total,
            "vectors": l0_vectors,
            "missing": l0_missing,
            "completeness_pct": l0_pct,
            "fts_synced": db_stats["l0_fts_count"] == l0_total,
            "errors_24h": {
                "http_400_batch_size": log_errors["http_400_batch_size"],
                "http_429_rate_limit": log_errors["http_429_rate_limit"],
                "http_500_server": log_errors["http_500_server"],
                "timeout": log_errors["timeout"],
                "db_locked": log_errors["db_locked"],
                "total": log_errors["total"],
            },
            "capture_trend_30d": [],  # Filled by history aggregation (Phase 2)
        },
        "l1": {
            "records": l1_total,
            "vectors": l1_vectors,
            "missing": l1_missing,
            "completeness_pct": l1_pct,
            "fts_synced": db_stats["l1_fts_count"] == l1_total if l1_total > 0 else True,
            "errors_24h": {
                "http_400_batch_size": 0,
                "http_429_rate_limit": 0,
                "http_500_server": 0,
                "timeout": 0,
                "db_locked": 0,
                "total": 0,
            },
            "extraction_failures_24h": 0,
            "extraction_latency_ms_p95": 0,
        },
        "l2": {
            "scene_blocks": scene_data["count"],
            "last_updated": scene_data["last_updated"],
            "last_updated_days_ago": scene_data["last_updated_days_ago"],
            "file_list": scene_data["file_list"],
            "freshness": scene_data["freshness"],
        },
        "l3": {
            "persona_exists": persona_data["exists"],
            "last_updated": persona_data["last_updated"],
            "last_updated_days_ago": persona_data["last_updated_days_ago"],
            "file_size_bytes": persona_data["file_size_bytes"],
            "freshness": persona_data["freshness"],
        },
        "storage": {
            "vectors_db_mb": db_size_mb,
            "wal_mb": round(wal_mb, 2),
            "wal_oversized": wal_mb > THRESHOLDS["wal_size_warning_mb"],
            "jsonl_total_mb": jsonl_data["total_mb"],
            "jsonl_file_count": jsonl_data["file_count"],
            "backup_mb": 0.0,
            "storage_growth_mb_per_day": storage_growth_per_day,
        },
        "recall": {
            "strategy": recall_strategy,
            "max_results": recall_cfg.get("max_results", 5),
            "score_threshold": recall_cfg.get("score_threshold", 0.3),
            "timeout_ms": recall_cfg.get("timeout_ms", 10000),
            "status": recall_status,
            "fts_health_score": recall_quality["fts_health_score"],
            "high_priority_retrievable_pct": recall_quality["high_priority_retrievable_pct"],
        },
        "api": {
            "embedding": {
                "provider": config.get("embedding", {}).get("provider"),
                "model": config.get("embedding", {}).get("model"),
                "dimensions": config.get("embedding", {}).get("dimensions"),
                "send_dimensions": config.get("embedding", {}).get("send_dimensions"),
                "availability_24h": max(0.0, 100.0 - log_errors["total"] * 0.1),
                "errors_24h": log_errors["total"],
                "p95_latency_ms": 0,
            },
            "llm": {
                "provider": config.get("llm", {}).get("provider"),
                "model": config.get("llm", {}).get("model"),
                "availability_24h": 100.0,
                "errors_24h": 0,
            },
        },
        "cleaning": {
            "retention_days": cleaning_retention,
            "clean_time": cleaning_cfg.get("clean_time", "03:00"),
            "last_run": None,
            "last_run_days_ago": 9999,
            "l0_total": l0_total,
            "l0_expired": 0,
            "l1_total": l1_total,
            "l1_expired": 0,
            "effectiveness": "low",  # Placeholder — cleaner hasn't reported here
        },
        "health_alerts": alerts,
    }

    return output


# ---------------------------------------------------------------------------
# 8. Main Pipeline
# ---------------------------------------------------------------------------


def run(dry_run: bool = False, validate_schema_flag: bool = False) -> None:
    """Execute the full export pipeline."""
    logger.info(
        "Starting memory-tdai export",
        extra={
            "extra": {
                "dry_run": dry_run,
                "validate_schema": validate_schema_flag,
                "start_ts": _ts(),
            }
        },
    )

    # Step 1: Collect data (all read-only)
    db_stats = collect_vectors_db_stats()
    logger.info(f"DB stats collected: l0={db_stats['l0_conversations']}, "
                f"l1={db_stats['l1_records']}")

    config = collect_openclaw_config()
    logger.info(f"Config extracted: embedding={config.get('embedding', {}).get('model')}, "
                f"recall={config.get('recall', {}).get('strategy')}")

    log_errors = collect_log_errors()
    logger.info(f"Log errors 24h: {log_errors}")

    scene_data = collect_scene_blocks()
    logger.info(f"Scene blocks: {scene_data['count']} files, freshness={scene_data['freshness']}")

    persona_data = collect_persona()
    logger.info(f"Persona: exists={persona_data['exists']}, "
                f"freshness={persona_data['freshness']}")

    jsonl_data = collect_jsonl_stats()
    logger.info(f"JSONL: {jsonl_data['file_count']} files, {jsonl_data['total_mb']} MB")

    wal_mb = collect_wal_size()
    logger.info(f"WAL: {wal_mb:.2f} MB")

    recall_quality = collect_recall_quality()
    logger.info(
        f"Recall quality: fts_health={recall_quality['fts_health_score']}%, "
        f"hp_retrievable={recall_quality['high_priority_retrievable_pct']}%"
    )

    # Step 2: Assemble
    output = assemble_output(
        db_stats=db_stats,
        config=config,
        log_errors=log_errors,
        scene_data=scene_data,
        persona_data=persona_data,
        jsonl_data=jsonl_data,
        wal_mb=wal_mb,
        recall_quality=recall_quality,
    )

    # Step 3: Blacklist scan (fail on any violation)
    violations = scan_blacklist(output)
    if violations:
        raise SecurityError(f"黑名单字段泄漏: {violations}")

    # Step 4: Schema validation
    if validate_schema_flag:
        schema_errors = _validate_schema(output)
        if schema_errors:
            raise ExporterError(
                f"Schema validation failed: {schema_errors}", "SCHEMA_ERROR"
            )
        logger.info("Schema validation passed")

    # Step 5: Print dry-run summary
    if dry_run:
        l0 = output["l0"]
        l1 = output["l1"]
        print(
            f"[memory-tdai] dry-run: meta.generated_at={output['meta']['generated_at']}",
            file=sys.stderr,
        )
        print(
            f"[memory-tdai] dry-run: l0.conversations={l0['conversations']}, "
            f"vectors={l0['vectors']}, missing={l0['missing']}",
            file=sys.stderr,
        )
        print(
            f"[memory-tdai] dry-run: l1.records={l1['records']}, "
            f"vectors={l1['vectors']}, missing={l1['missing']}",
            file=sys.stderr,
        )
        print(
            f"[memory-tdai] dry-run: storage.vectors_db_mb={output['meta']['vectors_db_size_mb']}",
            file=sys.stderr,
        )
        print(
            f"[memory-tdai] dry-run: health_alerts={len(output['health_alerts'])} "
            f"({output['health_alerts'][0]['level'] if output['health_alerts'] else 'none'})",
            file=sys.stderr,
        )
        print(
            "[memory-tdai] dry-run: PASS - 无黑名单字段，无 API key",
            file=sys.stderr,
        )
        return

    # Step 6: Write output files
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    latest_path = OUTPUT_DIR / "latest.json"
    history_path = HISTORY_DIR / f"{today_str}.json"

    json_bytes = json.dumps(output, ensure_ascii=False, indent=2).encode("utf-8")

    with open(latest_path, "wb") as fh:
        fh.write(json_bytes)

    with open(history_path, "wb") as fh:
        fh.write(json_bytes)

    logger.info(f"Wrote {latest_path} ({len(json_bytes):,} bytes)")
    logger.info(f"Wrote {history_path}")

    # Step 7: Git commit
    commit_message = (
        f"[memory-tdai] {today_str} auto-update\n\n"
        f"- vectors.db: {output['meta']['vectors_db_size_mb']} MB "
        f"(WAL: {output['meta']['wal_size_mb']} MB)\n"
        f"- L0: {output['l0']['conversations']} conversations, "
        f"{output['l0']['vectors']} vectors ({output['l0']['completeness_pct']}%)\n"
        f"- L1: {output['l1']['records']} records, "
        f"{output['l1']['vectors']} vectors ({output['l1']['completeness_pct']}%)\n"
        f"- L0 errors 24h: {output['l0']['errors_24h']['total']} "
        f"(HTTP 400: {output['l0']['errors_24h']['http_400_batch_size']})\n"
        f"- Health alerts: {len(output['health_alerts'])}\n"
        f"- Schema: {output['meta']['schema_version']}"
    )

    repo = OUTPUT_DIR.parent.parent.parent
    if (repo / ".git").exists():
        import subprocess

        subprocess.run(
            ["git", "-C", str(repo), "add", f"docs/memory-tdai/data/history/{today_str}.json", "docs/memory-tdai/data/latest.json"],
            check=True,
        )
        result = subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", commit_message],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info(f"Git commit: {commit_message.splitlines()[0]}")
        else:
            logger.warning(f"Git commit failed: {result.stderr.strip()}")

    logger.info(f"Export complete in {(datetime.now().timestamp() - __import__('time').time()):.1f}s")


# ---------------------------------------------------------------------------
# 9. CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="memory-tdai daily health exporter")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print summary to stderr, do not write files")
    parser.add_argument("--validate-schema", action="store_true",
                        help="Run JSON schema validation before writing")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    try:
        run(dry_run=args.dry_run, validate_schema_flag=args.validate_schema)
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        sys.exit(2)
    except SecurityError as e:
        logger.error(f"SECURITY VIOLATION: {e}")
        sys.exit(3)
    except ExporterError as e:
        logger.error(f"Exporter error: {e}")
        sys.exit(4)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(99)


if __name__ == "__main__":
    main()
