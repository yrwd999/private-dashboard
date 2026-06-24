#!/usr/bin/env python3
"""
L0 Embedding 修复脚本
修复 memory-tencentdb 因 MAX_BATCH_SIZE=256 vs API limit=10 不匹配导致的 7596 条缺失 embedding。

用法: python3 fix-missing-embeddings.py [--dry-run] [--batch-size N]

--dry-run: 只打印要修复的记录数，不实际调用 API 和写入数据库
"""

import json
import sqlite3
import array
import sys
import time
import argparse
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── 配置 ────────────────────────────────────────────────────────
OPENCLAW_JSON = os.path.expanduser("~/.openclaw/openclaw.json")
VECTORS_DB = os.path.expanduser("~/.openclaw/memory-tdai/vectors.db")
VEC0_SO = os.path.expanduser("~/.openclaw/npm/node_modules/sqlite-vec-linux-x64/vec0.so")

DEFAULT_BATCH_SIZE = 10       # 腾讯 API 上限是 10
MAX_RETRIES = 3
RETRY_BASE_DELAY = 4           # seconds（429/500 重试退避基数）
REQUEST_TIMEOUT = 15           # seconds
COMMIT_EVERY = 50             # 每 N 批次提交一次事务（checkpoint）


def load_embedding_config() -> dict:
    """从 openclaw.json 读取 embedding 配置"""
    with open(OPENCLAW_JSON, "r") as f:
        cfg = json.load(f)
    plugin_cfg = cfg.get("plugins", {}).get("entries", {}).get("memory-tencentdb", {})
    emb = plugin_cfg.get("config", {}).get("embedding", {})
    return {
        "base_url": emb["baseUrl"],
        "api_key": emb["apiKey"],
        "model": emb["model"],
        "dimensions": emb["dimensions"],
        "send_dimensions": emb.get("sendDimensions", True),
    }


def load_vec0_extension(db: sqlite3.Connection):
    """加载 sqlite-vec 扩展"""
    db.enable_load_extension(True)
    db.execute(f"SELECT load_extension('{VEC0_SO}')")


def get_missing_records(db: sqlite3.Connection) -> list:
    """返回所有缺失 embedding 的 L0 记录"""
    rows = db.execute("""
        SELECT record_id, message_text, recorded_at
        FROM l0_conversations
        WHERE record_id NOT IN (SELECT record_id FROM l0_vec)
        ORDER BY recorded_at
    """).fetchall()
    return rows


def embed_batch(base_url: str, api_key: str, model: str, dimensions: int,
                send_dimensions: bool, texts: list[str]) -> list[array.array]:
    """
    调用 Dashscope embedding API（batch），返回 Float32Array 列表。
    texts 数量应 <= 10。
    """
    # Critical: Dashscope 兼容模式要求 input 直接是字符串数组，
    # 不是 OpenAI 标准的 {"texts": [...]} 对象格式。
    payload = {
        "model": model,
        "input": texts,   # 直接数组，不是 {"texts": texts}
    }
    if send_dimensions:
        payload["dimensions"] = dimensions

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    data = json.dumps(payload).encode("utf-8")
    req = Request(f"{base_url}/embeddings", data=data, headers=headers)
    req.add_header("User-Agent", "memory-tencentdb-repair-script/1.0")

    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        result = json.load(resp)

    # Critical: 校验返回数量，防止 zip 对齐静默丢数据
    returned = result.get("data", [])
    if len(returned) != len(texts):
        raise RuntimeError(
            f"Embedding API 返回数量不匹配: 请求 {len(texts)} 条, 返回 {len(returned)} 条"
        )

    embeddings = []
    for item in returned:
        vec = item["embedding"]          # list of float
        arr = array.array('f', vec)
        embeddings.append(arr)
    return embeddings


def embed_with_retry(base_url: str, api_key: str, model: str, dimensions: int,
                     send_dimensions: bool, texts: list[str]) -> list[array.array]:
    """带重试的 embed_batch"""
    for attempt in range(MAX_RETRIES):
        try:
            return embed_batch(base_url, api_key, model, dimensions, send_dimensions, texts)
        except HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"  [WARN] API 429, {delay}s 后重试 ({attempt+1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(delay)
                continue
            # 500/502/503 也值得重试
            if e.code >= 500 and e.code < 600 and attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"  [WARN] API {e.code}, {delay}s 后重试 ({attempt+1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(delay)
                continue
            raise
        except URLError as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"  [WARN] 网络错误: {e.reason}, {delay}s 后重试 ({attempt+1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("重试耗尽")


def write_embedding(db: sqlite3.Connection, record_id: str, embedding: array.array, recorded_at: str):
    """将单条 embedding 写入 l0_vec"""
    blob = embedding.tobytes()          # bytes = Float32Array binary
    db.execute(
        "INSERT OR REPLACE INTO l0_vec (record_id, embedding, recorded_at) VALUES (?, ?, ?)",
        (record_id, blob, recorded_at)
    )


def main():
    parser = argparse.ArgumentParser(description="修复 memory-tencentdb L0 缺失 embedding")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"每批 API 调用条数（默认 {DEFAULT_BATCH_SIZE}）")
    parser.add_argument("--db", default=VECTORS_DB, help=f"vectors.db 路径（默认 {VECTORS_DB}）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条记录（0=不限）")
    args = parser.parse_args()

    print("=" * 60)
    print("L0 Embedding 修复脚本")
    print("=" * 60)

    # 1. 读取配置
    print("\n[1/5] 读取 embedding 配置 ...")
    emb_cfg = load_embedding_config()
    print(f"  provider : {emb_cfg['base_url']}")
    print(f"  model    : {emb_cfg['model']}")
    print(f"  dimensions: {emb_cfg['dimensions']}")

    # 2. 连接数据库
    print(f"\n[2/5] 连接 {args.db} ...")
    db = sqlite3.connect(args.db)
    load_vec0_extension(db)
    print("  vec0 扩展加载成功")

    # 3. 统计缺失记录
    print("\n[3/5] 查询缺失 embedding 的 L0 记录 ...")
    missing = get_missing_records(db)
    if args.limit > 0:
        missing = missing[:args.limit]
    total_missing = len(missing)
    print(f"  待修复记录数: {total_missing}{' (limit)' if args.limit > 0 else ''}")

    if total_missing == 0:
        print("  无需修复，退出。")
        db.close()
        return

    if args.dry_run:
        print("\n[DRY RUN] 以下记录将修复（显示前 5 条）:")
        for row in missing[:5]:
            print(f"  {row[0][:60]}... | {row[2]}")
        print(f"\n  共 {total_missing} 条。退出（dry-run）。")
        db.close()
        return

    # 写入确认
    confirm = input(f"\n即将写入 {total_missing} 条 embedding，确认请输入 'yes': ")
    if confirm.strip().lower() != 'yes':
        print("已取消。")
        db.close()
        return

    # 4. 分批处理
    print(f"\n[4/5] 分批修复（每批 {args.batch_size} 条）...")
    n_batches = (total_missing + args.batch_size - 1) // args.batch_size
    done = 0
    errors = 0

    db.execute("BEGIN")        # 事务内批量写入，加速

    try:
        for batch_idx in range(n_batches):
            batch = missing[batch_idx * args.batch_size : (batch_idx + 1) * args.batch_size]
            recorded_ats = {r[0]: r[2] for r in batch}

            # 过滤空文本和仅空白字符的记录
            valid_batch = [(rid, txt, rat) for rid, txt, rat in batch if txt and txt.strip()]
            invalid_count = len(batch) - len(valid_batch)
            if invalid_count:
                print(f"\n  [WARN] Batch {batch_idx+1} 跳过 {invalid_count} 条空文本", file=sys.stderr)
                done += invalid_count   # 空文本算已处理，不算错误

            if not valid_batch:
                continue

            record_ids = [r[0] for r in valid_batch]
            texts_to_embed = [t[:5000] for _, t, _ in valid_batch]   # 截断超长文本

            try:
                embeddings = embed_with_retry(
                    emb_cfg["base_url"], emb_cfg["api_key"], emb_cfg["model"],
                    emb_cfg["dimensions"], emb_cfg["send_dimensions"],
                    texts_to_embed
                )

                for record_id, emb_arr in zip(record_ids, embeddings):
                    write_embedding(db, record_id, emb_arr, recorded_ats[record_id])
                    done += 1

            except HTTPError as e:
                body = e.read().decode("utf-8") if e.fp else ""
                print(f"\n  [ERROR] Batch {batch_idx+1}/{n_batches} HTTP {e.code}: {body[:500]}", file=sys.stderr)
                errors += len(batch)
            except Exception as e:
                print(f"\n  [ERROR] Batch {batch_idx+1}/{n_batches} 失败: {e}", file=sys.stderr)
                errors += len(batch)
                # 该批次全部跳过，继续下一批次

            # 进度报告
            pct = (batch_idx + 1) / n_batches * 100
            print(f"\r  进度: {batch_idx+1}/{n_batches} 批次 ({pct:.1f}%) | 已修复: {done} | 失败: {errors}    ", end="", flush=True)

            # 分批提交 checkpoint（防止全量回滚）
            if (batch_idx + 1) % COMMIT_EVERY == 0:
                db.commit()
                db.execute("BEGIN")

            # 避免 API 过载
            time.sleep(0.3)

        db.commit()   # 最后一批提交
        print(f"\n\n  写入完成（{done} 条）")

    except KeyboardInterrupt:
        db.rollback()
        print("\n\n[ABORT] 用户中断，已回滚未提交的更改。")
        db.close()
        sys.exit(1)

    # 5. 验证
    print("\n[5/5] 验证修复结果 ...")
    remaining = get_missing_records(db)
    remaining_count = len(remaining)
    print(f"  修复前缺失: {total_missing}")
    print(f"  本次修复:   {done - errors}")
    print(f"  剩余缺失:   {remaining_count}")

    if remaining_count == 0:
        print("\n✅ 全部修复完成！")
    else:
        print(f"\n⚠️  还有 {remaining_count} 条未修复（见上方错误日志）")

    db.close()


if __name__ == "__main__":
    main()
