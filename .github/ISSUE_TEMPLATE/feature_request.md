---
name: Feature Request
about: 提出一个新功能或改进建议
labels: enhancement
---

## 功能概述
简要描述你想要的功能或改进。

## 背景
为什么需要这个功能？解决什么问题？

## 建议的 Dashboard
- [ ] `lcm`（LCM Memory Dashboard）
- [ ] `memory-tdai`（memory-tdai Dashboard）
- [ ] 通用 / 跨模块
- [ ] 新增 Dashboard（需先在 `docs/DASHBOARD_REGISTRY.md` 登记）

## 类型
- [ ] 新功能（新 exporter、新数据卡片）
- [ ] 改进（现有功能的增强）
- [ ] 文档（README、规范更新）
- [ ] CI/CD（自动化改进）
- [ ] 安全（权限、隔离改进）

## 建议的实现方案（如有）
描述你建议的实现方式。
参考现有实现：
- LCM Exporter 规范：`docs/lcm/docs/exporter-lcm-spec.md`
- LCM Exporter 实现：`scripts/lcm/exporter.py`
- 全局设计 Token：`docs/DESIGN_TOKENS.md`

## 安全约束检查
新增 exporter 脚本前，请确认：
- [ ] 不 SELECT `content`/`large_content`（消息原始内容）
- [ ] session_key 仅用 SHA256 哈希前缀，不导出明文
- [ ] 输出不含绝对路径（`/home/yrwd999/` → `~/.openclaw/`）
- [ ] 无 API token（ghp_/sk-/eyJ）
- [ ] SQLite 连接使用 mode=ro

参考：[SECURITY.md](SECURITY.md)

## 附加信息
任何其他上下文或参考链接。
