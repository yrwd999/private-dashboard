---
name: Bug Report
about: 报告一个 bug 或异常行为
labels: bug
---

## Bug 概述
清晰描述问题。

## 影响的 Dashboard
- [ ] `lcm`（LCM Memory Dashboard）
- [ ] `memory-tdai`（memory-tdai Dashboard）
- [ ] 通用 / 多模块

## 涉及的脚本（如已知）
例如：`scripts/lcm/exporter.py`、`scripts/security_scan.py`

## 复现步骤
1.
2.
3.

## 期望行为
描述期望的结果。

## 实际行为
描述实际发生的情况。

## 错误信息（如有）

```bash
# 相关错误输出或日志
```

## 退出码（如适用）
- [ ] 0（成功）
- [ ] 1（通用错误）
- [ ] 2（ConfigError：DB 不存在、目录无权限）
- [ ] 3（SecurityError：检测到黑名单/token）
- [ ] 4（DataError：SQL 失败、字段异常）

## 安全相关（如涉及敏感数据泄漏）
> ⚠️ 如果 bug 可能涉及敏感数据泄漏（session_key 明文、token 暴露、绝对路径等），
> 请**不要**在此处描述细节，优先联系 Ray。
> 
> 安全问题参考：[SECURITY.md](SECURITY.md)

- [ ] 此问题涉及安全风险（勾选后请私下联系 Ray）

## 环境信息
- OS:
- Python 版本:
- 相关 DB 路径:

## 附加信息
截图、日志或相关文件（如有）。
