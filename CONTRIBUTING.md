# Contributing to Private Dashboard

## 开发设置

```bash
# 克隆仓库
git clone https://github.com/yrwd999/private-dashboard.git
cd private-dashboard

# Python 环境（建议 venv）
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/lcm/requirements.txt  # 如有
```

## 分支规范

- `main` — 生产分支，所有变更通过 PR 合并
- `feat/*` — 新功能分支
- `fix/*` — 修复分支
- `docs/*` — 文档更新

## 提交流程

1. Fork 仓库，创建功能分支
2. 进行开发，确保代码通过 lint 检查
3. 提交时使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

   ```
   feat(lcm): add new exporter for memory analytics
   fix(doctor): handle missing config gracefully
   docs: update dashboard deployment guide
   ```

4. 发起 Pull Request，描述清楚变更内容
5. 通过 CI 检查后，由维护者合并

## 脚本规范（Python）

- 使用 `black` 格式化代码
- 使用 `ruff` 进行 lint 检查
- 所有新增脚本须附 docstring

## 文档规范

- Dashboard 文档放在 `docs/` 目录
- 遵循 Markdown 规范，中英文之间留空格
