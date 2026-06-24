# Private Dashboard

> Ray's personal dashboard hub · Data is **aggregated statistics only** · No sensitive content exported

---

## 📊 Available Dashboards

| Dashboard | Description | Status |
|----------|-------------|--------|
| [**LCM Memory**](./lcm/) | OpenClaw Lossless Context Management · conversation trends, memory health | ✅ Live |
| Homelab | Home Assistant infrastructure overview | 📋 Planned |
| Network | Network topology and monitoring | 📋 Planned |

---

## 🔒 Data Policy

- **Export scope**: Aggregated statistics only (counts, distributions, time trends)
- **Never exported**: Message content, summary content, full session keys, credentials, tokens
- **Session key handling**: Only `agent:*:role` prefix retained (no suffix ID)
- **Update frequency**: Each dashboard has its own schedule (see individual dashboard)

See each dashboard's `docs/SECURITY.md` for module-specific details.

---

## 🎨 Design System

All dashboards follow the **Apple Human Interface** design language:
- White / light gray background
- SF Pro / system font stack
- 12px border radius, soft shadows
- Chart.js for visualizations (CDN)

Design tokens: [`DESIGN_TOKENS.md`](./DESIGN_TOKENS.md)

---

## 🛠️ Technical Stack

| Layer | Technology |
|-------|-----------|
| Charts | Chart.js (CDN) |
| Fonts | Apple SF Pro via Google Fonts |
| Icons | Inline SVG (no external icon library) |
| Data export | Python stdlib only (no npm / pip dependencies) |
| Hosting | GitHub Pages (public repository) |

---

*Maintained by Ray · Internal engineering docs: [root README.md](../README.md)*
