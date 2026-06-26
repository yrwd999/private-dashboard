# Memory-TDAI Exporter

> 维护者：Ray | 状态：✅ 运行中（Schema v1.1 · 2026-06-26 P1-B-1）

## 脚本列表

| 脚本 | 职责 |
|------|------|
| `exporter.py` | 从 `~/.openclaw/memory-tdai/vectors.db` 导出聚合统计数据 |

## 使用

```bash
# Dry-run（OUTPUT_DIR 自动计算为 /tmp/xxx/docs/memory-tdai/data/）
python3 scripts/memory-tdai/exporter.py --dry-run

# 正式导出（OUTPUT_DIR 自动计算，无 CLI 参数）
python3 scripts/memory-tdai/exporter.py
```

> 注意：`exporter.py` **无 `--output-dir` 参数**。输出路径由脚本自身路径硬编码计算：
> `Path(__file__).parent.parent.parent / "docs" / "memory-tdai" / "data"`

## 数据脱敏规则

与 LCM exporter 一致，详见 `docs/memory-tdai/docs/SECURITY.md`。

## P1-B-1 变更记录（2026-06-26）

| 变更 | 说明 |
|------|------|
| Schema v1.0 → v1.1 | 新增 `recall.fts_health_score`、`recall.high_priority_retrievable_pct` |
| `collect_recall_quality()` | 新增函数：计算 FTS 索引健康分和高优先级记录可检索率 |
| Alert Code 新增 | `FTS_INDEX_DESYNC`、`RECALL_HP_RETRIEVE_LOW` |
| SQL 白名单新增 | Q10（高优先级记录数）、Q11（高优先级且 FTS 命中数） |
| UI 更新 | Dashboard recall 卡片新增 inline delta 行 |

## 开发

```bash
# 语法验证
python3 -m py_compile scripts/memory-tdai/exporter.py

# Dry-run
python3 scripts/memory-tdai/exporter.py --dry-run
```
