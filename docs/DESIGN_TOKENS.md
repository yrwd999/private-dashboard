# Design Tokens

> 全局设计 token 定义 · 遵循 Apple Human Interface Guidelines
> 所有 dashboard 模块必须使用本文件定义的 token，不允许硬编码颜色 / 字体 / 圆角

---

## 🎨 颜色（Color）

### 基础色（Base Colors）

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg-primary` | `#ffffff` | 主背景（纯白） |
| `--bg-secondary` | `#f5f5f7` | 次级背景（Apple 经典灰） |
| `--bg-tertiary` | `#fafafa` | 第三级背景（极淡灰） |
| `--bg-elevated` | `#ffffff` | 悬浮卡片背景 |

### 文本色（Text Colors）

| Token | 值 | 用途 |
|-------|-----|------|
| `--fg-primary` | `#1d1d1f` | 主文本（Apple 经典黑） |
| `--fg-secondary` | `#6e6e73` | 次级文本 |
| `--fg-tertiary` | `#86868b` | 第三级文本（辅助说明） |
| `--fg-quaternary` | `#aeaeb2` | 第四级文本（最弱） |

### 强调色（Accent Colors）

| Token | 值 | 用途 |
|-------|-----|------|
| `--accent-blue` | `#0071e3` | Apple 蓝（主强调） |
| `--accent-green` | `#30d158` | 成功 / 增长 |
| `--accent-orange` | `#ff9f0a` | 警告 |
| `--accent-red` | `#ff3b30` | 危险 / 错误 |
| `--accent-purple` | `#af52de` | 装饰 |
| `--accent-gray` | `#86868b` | 中性 |

### 边框 / 阴影（Border & Shadow）

| Token | 值 | 用途 |
|-------|-----|------|
| `--border-subtle` | `rgba(0, 0, 0, 0.08)` | 极淡边框 |
| `--border-default` | `rgba(0, 0, 0, 0.12)` | 默认边框 |
| `--shadow-sm` | `0 2px 8px rgba(0, 0, 0, 0.04)` | 小阴影 |
| `--shadow-md` | `0 4px 20px rgba(0, 0, 0, 0.06)` | 中阴影（卡片） |
| `--shadow-lg` | `0 8px 32px rgba(0, 0, 0, 0.08)` | 大阴影（悬浮） |

---

## 🔤 字体（Typography）

### 字体族

```css
--font-display: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', sans-serif;
--font-body: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--font-mono: 'SF Mono', Menlo, Consolas, monospace;
```

### 字号（Font Sizes）

| Token | 值 | 用途 |
|-------|-----|------|
| `--text-caption` | `12px` | 辅助说明 |
| `--text-small` | `13px` | 小字 |
| `--text-body` | `15px` | 正文（Apple 默认） |
| `--text-md` | `17px` | 较大正文 |
| `--text-lg` | `20px` | 小标题 |
| `--text-xl` | `28px` | 中标题 |
| `--text-2xl` | `40px` | 大标题 |
| `--text-display` | `56px` | 数字指标（大） |
| `--text-hero` | `72px` | Hero 数字 |

### 字重（Font Weights）

| Token | 值 | 用途 |
|-------|-----|------|
| `--weight-regular` | `400` | 正文 |
| `--weight-medium` | `500` | 强调 |
| `--weight-semibold` | `600` | 小标题 |
| `--weight-bold` | `700` | 大标题 |
| `--weight-black` | `900` | 数字指标 |

---

## 📐 间距（Spacing · 8px 网格）

| Token | 值 | 用途 |
|-------|-----|------|
| `--space-0` | `0` | 无 |
| `--space-1` | `4px` | 极小 |
| `--space-2` | `8px` | 小 |
| `--space-3` | `16px` | 中（默认） |
| `--space-4` | `24px` | 较大 |
| `--space-5` | `32px` | 大 |
| `--space-6` | `48px` | 极大 |
| `--space-8` | `64px` | 节区 |

---

## 🔘 圆角（Border Radius）

| Token | 值 | 用途 |
|-------|-----|------|
| `--radius-sm` | `8px` | 小元素（按钮、标签） |
| `--radius-md` | `12px` | 中元素（输入框） |
| `--radius-lg` | `18px` | 卡片（默认） |
| `--radius-xl` | `24px` | 大卡片 |
| `--radius-full` | `9999px` | 完全圆角（头像、徽章） |

---

## 🌫️ 毛玻璃效果（Frosted Glass · Apple 标志）

```css
.glass {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border: 1px solid rgba(0, 0, 0, 0.08);
}
```

用途：导航栏、悬浮卡片顶部、Modal 背景。

---

## 🎭 动效（Motion）

### 缓动函数（Easing）

| Token | 值 | 用途 |
|-------|-----|------|
| `--ease-default` | `cubic-bezier(0.4, 0, 0.2, 1)` | 默认 |
| `--ease-out` | `cubic-bezier(0.0, 0, 0.2, 1)` | 入场 |
| `--ease-in` | `cubic-bezier(0.4, 0, 1, 1)` | 退场 |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | 弹性 |

### 持续时间（Duration）

| Token | 值 | 用途 |
|-------|-----|------|
| `--duration-fast` | `150ms` | 状态切换 |
| `--duration-normal` | `300ms` | 入场 |
| `--duration-slow` | `500ms` | 强调动画 |

---

## 📊 Chart.js 主题映射

| Token | Chart.js 配置 |
|-------|---------------|
| `--accent-blue` | `borderColor / backgroundColor` 主色 |
| `--accent-green` | 正向数据 |
| `--accent-orange` | 警告 |
| `--accent-red` | 异常 |
| `--fg-tertiary` | 网格线、坐标轴 |
| `--fg-secondary` | 图例、标签 |
| `--font-display` | `Chart.defaults.font.family` |

详见：[`docs/CHARTJS_CONFIG.md`](./CHARTJS_CONFIG.md)（待补）

---

## 🌓 暗色模式（预留，Phase 3 实现）

```css
[data-theme="dark"] {
  --bg-primary: #000000;
  --bg-secondary: #1c1c1e;
  --bg-tertiary: #2c2c2e;
  --fg-primary: #f5f5f7;
  --fg-secondary: #98989d;
  --fg-tertiary: #6e6e73;
  --border-subtle: rgba(255, 255, 255, 0.08);
  --shadow-md: 0 4px 20px rgba(0, 0, 0, 0.3);
}
```

---

## 📚 参考资料

- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [SF Pro Fonts](https://developer.apple.com/fonts/)
- [Apple Design Resources](https://developer.apple.com/design/resources/)

---

> 最后更新：2026-06-24 · 维护者：Ray · 由小虾米起草