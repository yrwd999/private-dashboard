# Memory-TDAI Exporter

> 维护者：Ray | 状态：✅ 运行中

## 脚本列表

| 脚本 | 职责 |
|------|------|
| `exporter.py` | 从 `~/.openclaw/memory-tdai/vectors.db` 导出聚合统计数据 |

## 使用

```bash
# Dry-run
python3 scripts/memory-tdai/exporter.py --dry-run --output-dir /tmp/memory-tdai/

# 正式导出
python3 scripts/memory-tdai/exporter.py --output-dir docs/memory-tdai/data
```

## 数据脱敏规则

与 LCM exporter 一致，详见 `docs/memory-tdai/docs/SECURITY.md`。

## 开发

```bash
python3 -m py_compile scripts/memory-tdai/exporter.py
```
