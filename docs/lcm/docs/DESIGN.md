# LCM Dashboard · Design Spec

> Apple Human Interface 风格设计规范 · LCM Memory Dashboard
> 最后更新：2026-06-24 · 维护者：Ray · 起草：小虾米

---

## 🎯 设计目标

1. **一眼看懂**：核心指标（DB 体积 / 会话数 / 消息数 / 摘要数）2 秒内识别
2. **趋势可读**：30 天消息增长趋势支持快速对比
3. **异常显眼**：WAL 告警、备份膨胀等问题用 Apple 红高亮
4. **零学习成本**：用户（Ray）每天看一次，无需查阅文档

---

## 🖼️ 布局结构

```
┌─────────────────────────────────────────────────────────────────┐
│  🌐 Header (sticky, frosted glass)                              │
│  LCM Memory Dashboard      最后更新: 2026-06-24 02:00  [设置]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📊 核心指标卡（4 个，桌面 4 列 / 移动 2 列 / 平板 2 列）        │
│  ┌──────────┬──────────┬──────────┬──────────┐                  │
│  │ DB 体积  │ 会话总数 │ 消息总数 │ 摘要数   │                  │
│  │ 438 MB   │ 92       │ 41,210   │ 763      │                  │
│  │ ↓ 4.2%   │ ↑ 1.1%   │ ↑ 0.8%   │ → 0%     │                  │
│  │ 较昨日   │ 较上周   │ 较上周   │ 较上周   │                  │
│  └──────────┴──────────┴──────────┴──────────┘                  │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────┬───────────────────────────┐    │
│  │ 📈 30 天消息增长趋势         │ 🎯 会话分布（按 agent）    │    │
│  │ Chart.js 折线图              │ Chart.js 环形图            │    │
│  │ Apple 蓝主色 + 浅灰网格     │ Apple 蓝/绿/橙/紫/灰       │    │
│  │ 高 280px                    │ 高 280px                   │    │
│  └─────────────────────────────┴───────────────────────────┘    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────┬───────────────────────────┐    │
│  │ 💾 备份文件占用              │ ⚠️ 健康状态                │    │
│  │ 横向条形图                   │ 状态卡（绿/黄/红）         │    │
│  │ 显示文件名 + 大小 + 年龄     │ WAL / 备份 / 异常告警     │    │
│  └─────────────────────────────┴───────────────────────────┘    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📋 最近 7 天操作记录                                           │
│  ┌──────┬────────┬──────┬─────────┬──────────┐                  │
│  │ 日期 │ 类型    │ 数量 │ 释放空间│ 操作人   │                  │
│  ├──────┼────────┼──────┼─────────┼──────────┤                  │
│  │ 06-24│ ARCHIVE│  10  │ 4.2 MB  │ cron     │                  │
│  │ 06-23│ CHECKPT│  -   │ 4.0 MB  │ manual   │                  │
│  └──────┴────────┴──────┴─────────┴──────────┘                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎨 视觉规范

### 卡片样式

```css
.metric-card {
  background: var(--bg-elevated);
  border-radius: var(--radius-lg);           /* 18px */
  padding: var(--space-5);                   /* 32px */
  box-shadow: var(--shadow-md);
  border: 1px solid var(--border-subtle);
  transition: transform var(--duration-normal) var(--ease-out);
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}
```

### 数字指标（大字号）

```css
.metric-value {
  font-family: var(--font-display);
  font-size: var(--text-display);            /* 56px */
  font-weight: var(--weight-bold);
  color: var(--fg-primary);
  line-height: 1;
  letter-spacing: -0.02em;
}
.metric-label {
  font-size: var(--text-caption);            /* 12px */
  color: var(--fg-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: var(--space-2);
}
.metric-delta {
  font-size: var(--text-small);              /* 13px */
  font-weight: var(--weight-medium);
  margin-top: var(--space-2);
}
.metric-delta.up { color: var(--accent-green); }
.metric-delta.down { color: var(--accent-green); }  /* DB 体积下降 = 好 */
.metric-delta.warning { color: var(--accent-orange); }
```

### 图表配色（Chart.js）

```javascript
const appleColors = {
  blue: '#0071e3',      // 主色（消息数趋势）
  green: '#30d158',     // 增长 / 成功
  orange: '#ff9f0a',    // 警告
  red: '#ff3b30',       // 错误 / 异常
  purple: '#af52de',    // agent 分布之一
  gray: '#86868b'       // 中性
};

Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "SF Pro Display"';
Chart.defaults.color = '#6e6e73';
Chart.defaults.borderColor = 'rgba(0, 0, 0, 0.04)';
```

### 响应式断点

| 设备 | 宽度 | 布局 |
|------|------|------|
| 桌面 | > 1024px | 核心指标 4 列，图表 2 列 |
| 平板 | 768-1024px | 核心指标 2 列，图表 1 列 |
| 移动 | < 768px | 全部单列堆叠 |

---

## 🎬 动效规范

### 入场动画

```css
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.fade-in-up {
  animation: fadeInUp var(--duration-slow) var(--ease-out) both;
}
```

### 加载状态

- 数据加载中：显示骨架屏（与卡片同尺寸，浅灰渐变）
- 数据加载失败：显示错误提示（红边框 + 重新加载按钮）

### 数字滚动

- 核心指标数字首次显示时，从 0 滚动到目标值（1.5s）
- 使用 `requestAnimationFrame`，缓动 `easeOutQuart`

---

## 📦 组件清单

| 组件 | 用途 | 复用 |
|------|------|------|
| `<MetricCard>` | 显示数值 + 标签 + 趋势 | 所有核心指标 |
| `<TrendChart>` | Chart.js 折线图包装 | 30 天趋势 |
| `<DistributionChart>` | Chart.js 环形图包装 | 会话分布 |
| `<HealthBadge>` | 健康状态徽章 | 告警区 |
| `<HistoryTable>` | 历史记录表格 | 最近 7 天操作 |

---

## 🚫 禁止事项

| 行为 | 原因 |
|------|------|
| ❌ 引入 Tailwind / Bootstrap | 与 Apple 风格冲突，体积过大 |
| ❌ 使用 emoji 作为图标（除文档示例） | 视觉不一致 |
| ❌ 显示完整 session_key | 隐私泄漏 |
| ❌ 显示消息内容摘要 | 隐私泄漏 |
| ❌ 显示具体用户名 / token | 凭据泄漏 |

---

## 📚 参考资料

- [`/docs/DESIGN_TOKENS.md`](../../docs/DESIGN_TOKENS.md) — 全局设计 token
- [Apple HIG](https://developer.apple.com/design/human-interface-guidelines/) — 设计规范
- [`./DATA_SCHEMA.md`](./DATA_SCHEMA.md) — 数据格式
- [`./SECURITY.md`](./SECURITY.md) — 安全护栏