/**
 * LCM Dashboard — Frontend Logic
 * Version: 1.0 | 2026-06-24
 * Spec: ../docs/DESIGN.md + ../../docs/DESIGN_TOKENS.md
 *
 * Dependencies: Chart.js v4 (loaded globally via CDN in index.html)
 * Data source: ./data/latest.json (written by exporter_lcm.py)
 */

'use strict';

/* ── App State ──────────────────────────────────────────── */
const state = {
  data: null,
  charts: {},
  loading: true,
  error: null,
};

/* ── Chart.js Theme (Apple HIG) ───────────────────────── */
const CHART_COLORS = {
  blue:   '#0071e3',
  green:  '#30d158',
  orange: '#ff9f0a',
  red:    '#ff3b30',
  purple: '#af52de',
  gray:   '#86868b',
};

const AGENT_COLOR_MAP = {
  main:    '#0071e3',
  geek:    '#30d158',
  coding:  '#af52de',
  netops:  '#ff9f0a',
  homelab: '#ff3b30',
  agentroom:'#86868b',
  default: '#aeaeb2',
};

Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif';
Chart.defaults.color = '#6e6e73';
Chart.defaults.borderColor = 'rgba(0, 0, 0, 0.04)';

/* ── Utilities ──────────────────────────────────────────── */
function fmt(n) {
  if (n === undefined || n === null) return '—';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000)     return n.toLocaleString('zh-CN');
  return String(n);
}

function fmtMB(n) {
  if (n === undefined || n === null) return '—';
  if (n < 0.01) return '0 MB';
  return n.toFixed(1) + ' MB';
}

function fmtRelTime(isoString) {
  // e.g. "2026-06-24T02:00:00+08:00" → "06-24 02:00"
  try {
    const d = new Date(isoString);
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${m}-${day} ${hh}:${mm}`;
  } catch {
    return isoString;
  }
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

/* ── Number Animation (countUp) ────────────────────────── */
function animateCount(el, target, durationMs, formatter) {
  if (!el || target === undefined) return;
  const start = performance.now();
  const startVal = 0;

  function easeOutQuart(t) {
    return 1 - Math.pow(1 - t, 4);
  }

  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / durationMs, 1);
    const value = startVal + (target - startVal) * easeOutQuart(progress);
    el.textContent = formatter(Math.round(value));
    if (progress < 1) {
      requestAnimationFrame(tick);
    } else {
      el.textContent = formatter(target);
    }
  }

  requestAnimationFrame(tick);
}

/* ── Skeleton Rendering ─────────────────────────────────── */
function renderSkeletons() {
  const main = document.getElementById('app-main');
  main.innerHTML = `
    <p class="section-label">核心指标</p>
    <div class="metrics-grid" id="skeleton-metrics">
      ${[0,1,2,3].map(() => `
        <div class="skeleton-card">
          <div class="skeleton skeleton-label"></div>
          <div class="skeleton skeleton-value" style="margin-top:8px"></div>
          <div class="skeleton skeleton-delta" style="margin-top:8px"></div>
        </div>`).join('')}
    </div>
    <p class="section-label" style="margin-top:24px">趋势与分布</p>
    <div class="charts-grid">
      <div class="skeleton-card"><div class="skeleton skeleton-chart"></div></div>
      <div class="skeleton-card"><div class="skeleton skeleton-chart"></div></div>
    </div>
    <p class="section-label" style="margin-top:24px">状态与历史</p>
    <div class="bottom-grid">
      <div class="skeleton-card" style="height:200px"></div>
      <div class="skeleton-card" style="height:200px"></div>
    </div>
  `;
}

/* ── Error Rendering ────────────────────────────────────── */
function renderError(msg) {
  const main = document.getElementById('app-main');
  main.innerHTML = `
    <div class="error-state">
      <div class="error-icon">⚠️</div>
      <div class="error-title">数据加载失败</div>
      <div class="error-message">${escHtml(msg)}</div>
      <button class="error-retry" onclick="loadData()">
        🔄 重新加载
      </button>
    </div>
  `;
}

function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

/* ── Update Header ──────────────────────────────────────── */
function updateHeader(meta) {
  const elUpdated = document.getElementById('header-updated');
  const elDbSize  = document.getElementById('header-dbsize');
  if (elUpdated) elUpdated.textContent = '更新: ' + fmtRelTime(meta.generated_at);
  if (elDbSize)  elDbSize.textContent  = fmtMB(meta.lcm_db_size_mb) + ' DB';
}

/* ── Render Metric Cards ────────────────────────────────── */
function renderMetrics(overview) {
  const grid = document.getElementById('metrics-grid');
  if (!grid) return;

  const cards = [
    {
      label: '会话总数',
      icon:  '💬',
      value: overview.total_conversations,
      delta: overview.active_conversations + ' 活跃 / ' + overview.archived_conversations + ' 归档',
      deltaClass: 'flat',
    },
    {
      label: '消息总数',
      icon:  '📨',
      value: overview.total_messages,
      delta: overview.total_summaries + ' 摘要',
      deltaClass: 'flat',
    },
    {
      label: '摘要数量',
      icon:  '🗂️',
      value: overview.total_summaries,
      delta: overview.leaf_summaries + ' 叶 + ' + overview.condensed_summaries + ' 压缩',
      deltaClass: 'flat',
    },
    {
      label: '存储占用',
      icon:  '💾',
      value: overview.storage_size_mb,
      delta: fmtMB(overview.wal_size_mb) + ' WAL',
      deltaClass: overview.storage_size_mb > 500 ? 'warn' : 'flat',
      suffix: ' MB',
      isFloat: true,
    },
  ];

  grid.innerHTML = cards.map(c => `
    <div class="metric-card">
      <div class="metric-label">
        <span class="label-icon">${c.icon}</span>
        ${c.label}
      </div>
      <div class="metric-value" data-target="${c.isFloat ? c.value.toFixed(1) : c.value}" data-suffix="${c.suffix || ''}">
        ${fmt(c.value)}${c.suffix || ''}
      </div>
      <div class="metric-delta ${c.deltaClass}">
        <span class="delta-arrow">${c.deltaClass === 'flat' ? '—' : c.deltaClass === 'warn' ? '⚠️' : ''}</span>
        ${c.delta}
      </div>
    </div>
  `).join('');
}

/* ── Render 30-Day Trend Chart ──────────────────────────── */
function renderTrendChart(messageTrend30d) {
  const wrap = document.getElementById('trend-chart-wrap');
  if (!wrap) return;

  // Destroy existing chart
  if (state.charts.trend) {
    state.charts.trend.destroy();
    state.charts.trend = null;
  }

  const canvas = document.getElementById('trend-chart');
  if (!canvas) return;

  // Prepare labels (last 30 days)
  const labels = messageTrend30d.map(d => {
    const dt = new Date(d.date);
    return `${dt.getMonth()+1}/${dt.getDate()}`;
  });

  const data = messageTrend30d.map(d => d.count);

  // Fill gaps in data with null (Chart.js handles gracefully)
  // Grouped by date already from exporter, so just use as-is

  state.charts.trend = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: '消息数',
        data,
        borderColor: CHART_COLORS.blue,
        backgroundColor: 'rgba(0, 113, 227, 0.06)',
        borderWidth: 2.5,
        pointRadius: 3,
        pointHoverRadius: 6,
        pointBackgroundColor: CHART_COLORS.blue,
        fill: true,
        tension: 0.35,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(255,255,255,0.95)',
          titleColor: '#1d1d1f',
          bodyColor: '#6e6e73',
          borderColor: 'rgba(0,0,0,0.08)',
          borderWidth: 1,
          padding: 12,
          callbacks: {
            title: (items) => {
              const idx = items[0].dataIndex;
              return messageTrend30d[idx] ? messageTrend30d[idx].date : items[0].label;
            },
            label: (item) => ` ${item.raw.toLocaleString()} 条消息`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxTicksLimit: 10, font: { size: 11 } },
        },
        y: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          border: { dash: [4, 4] },
          ticks: {
            font: { size: 11 },
            callback: (v) => v >= 1000 ? (v/1000).toFixed(0) + 'k' : v,
          },
        },
      },
    },
  });
}

/* ── Render Agent Distribution Chart ─────────────────────── */
function renderAgentChart(agentDistribution) {
  const wrap = document.getElementById('agent-chart-wrap');
  if (!wrap) return;

  if (state.charts.agent) {
    state.charts.agent.destroy();
    state.charts.agent = null;
  }

  const canvas = document.getElementById('agent-chart');
  if (!canvas) return;

  const sorted = [...agentDistribution].sort((a, b) => b.messages - a.messages);
  const labels  = sorted.map(a => a.agent);
  const data    = sorted.map(a => a.messages);
  const colors  = sorted.map(a => AGENT_COLOR_MAP[a.agent] || AGENT_COLOR_MAP.default);

  state.charts.agent = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors,
        borderWidth: 3,
        borderColor: '#ffffff',
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(255,255,255,0.95)',
          titleColor: '#1d1d1f',
          bodyColor: '#6e6e73',
          borderColor: 'rgba(0,0,0,0.08)',
          borderWidth: 1,
          padding: 12,
          callbacks: {
            label: (item) => ` ${item.raw.toLocaleString()} 条消息`,
          },
        },
      },
    },
  });

  // Render custom legend
  const legendEl = document.getElementById('agent-legend');
  if (legendEl) {
    legendEl.innerHTML = sorted.map(a => `
      <div class="agent-legend-item">
        <div class="agent-legend-dot" style="background:${AGENT_COLOR_MAP[a.agent] || AGENT_COLOR_MAP.default}"></div>
        <span class="agent-legend-name">${escHtml(a.agent)}</span>
        <span class="agent-legend-msg">${a.messages.toLocaleString()}</span>
      </div>
    `).join('');
  }
}

/* ── Render Session Key Patterns ──────────────────────────── */
function renderSessionPatterns(patterns) {
  const container = document.getElementById('session-patterns');
  if (!container) return;

  if (!patterns || patterns.length === 0) {
    container.innerHTML = '<p class="backup-empty">无会话匹配记录</p>';
    return;
  }

  container.innerHTML = `
    <div class="patterns-grid">
      ${patterns.map(p => `
        <div class="pattern-chip">
          <span class="pattern-name" title="${escHtml(p.pattern)}">${escHtml(p.pattern)}</span>
          <span class="pattern-count">${p.count}</span>
          ${p.note ? `<span class="pattern-note">${escHtml(p.note)}</span>` : ''}
        </div>
      `).join('')}
    </div>
  `;
}

/* ── Render Health Alerts ───────────────────────────────── */
function renderHealthAlerts(healthAlerts) {
  const list = document.getElementById('alerts-list');
  if (!list) return;

  if (!healthAlerts || healthAlerts.length === 0) {
    list.innerHTML = '<p class="backup-empty">无告警</p>';
    return;
  }

  const ICONS = { success: '✅', info: 'ℹ️', warning: '⚠️', error: '🚨' };

  list.innerHTML = healthAlerts.slice(0, 10).map(a => `
    <div class="alert-badge ${a.level}">
      <span class="alert-icon">${ICONS[a.level] || 'ℹ️'}</span>
      <div class="alert-body">
        <div class="alert-msg">${escHtml(a.message)}</div>
        <div class="alert-time">${fmtRelTime(a.timestamp)}</div>
      </div>
      <span class="alert-code">${escHtml(a.code)}</span>
    </div>
  `).join('');
}

/* ── Render Backup Status ───────────────────────────────── */
function renderBackupStatus(backupStatus) {
  const list = document.getElementById('backup-list');
  if (!list) return;

  if (!backupStatus || !backupStatus.files || backupStatus.files.length === 0) {
    list.innerHTML = '<p class="backup-empty">无备份文件</p>';
    return;
  }

  list.innerHTML = backupStatus.files.map(f => `
    <div class="backup-item">
      <span class="backup-name" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
      <div class="backup-meta">
        <span class="backup-size">${fmtMB(f.size_mb)}</span>
        ${f.keep ? '<span class="keep-badge">保留</span>' : `<span style="color:var(--fg-tertiary);font-size:11px">${f.age_days}d ago</span>`}
      </div>
    </div>
  `).join('');
}

/* ── Render History Table ───────────────────────────────── */
function renderHistoryTable(messageTrend30d) {
  const tbody = document.getElementById('history-tbody');
  if (!tbody) return;

  if (!messageTrend30d || messageTrend30d.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--fg-tertiary);padding:24px">暂无历史数据</td></tr>';
    return;
  }

  // Show last 7 days from trend data
  const recent = messageTrend30d.slice(-7).reverse();

  tbody.innerHTML = recent.map((d, i) => {
    const typeClass = d.count > 0 ? 'type-archive' : 'type-unknown';
    const typeName  = d.count > 0 ? '📈 记录' : '—';
    return `
      <tr>
        <td class="cell-date">${d.date}</td>
        <td><span class="cell-type ${typeClass}">${typeName}</span></td>
        <td class="cell-count">${d.count > 0 ? d.count.toLocaleString() : '—'}</td>
        <td class="cell-size">${fmtMB(d.size_mb)}</td>
        <td class="cell-actor">LCM cron</td>
      </tr>
    `;
  }).join('');
}

/* ── Render Full Dashboard ──────────────────────────────── */
function renderDashboard(data) {
  const main = document.getElementById('app-main');
  main.innerHTML = `
    <!-- Metric Cards -->
    <p class="section-label">核心指标</p>
    <div class="metrics-grid" id="metrics-grid"></div>

    <!-- Charts Row -->
    <p class="section-label" style="margin-top:8px">趋势与分布</p>
    <div class="charts-grid">
      <div class="chart-card">
        <div class="chart-header">
          <div>
            <div class="chart-title">📈 30 天消息增长</div>
            <div class="chart-subtitle">每日新增消息数</div>
          </div>
        </div>
        <div class="chart-canvas-wrap" id="trend-chart-wrap">
          <canvas id="trend-chart"></canvas>
        </div>
      </div>

      <div class="chart-card">
        <div class="chart-header">
          <div>
            <div class="chart-title">🎯 会话分布</div>
            <div class="chart-subtitle">按 agent 消息量统计</div>
          </div>
        </div>
        <div class="agent-dist-wrap">
          <div id="agent-chart-wrap" class="agent-chart-wrap">
            <canvas id="agent-chart"></canvas>
          </div>
          <div class="agent-legend" id="agent-legend"></div>
        </div>
      </div>
    </div>

    <!-- Session Key Patterns -->
    <p class="section-label" style="margin-top:8px">会话类型分布</p>
    <div class="info-card" style="animation-delay:360ms">
      <div id="session-patterns"></div>
    </div>

    <!-- Bottom Row -->
    <p class="section-label" style="margin-top:8px">状态与历史</p>
    <div class="bottom-grid">
      <div class="info-card">
        <div class="card-title">
          <span class="title-icon">💾</span>
          备份文件状态
        </div>
        <div class="backup-list" id="backup-list"></div>
      </div>

      <div class="info-card">
        <div class="card-title">
          <span class="title-icon">⚠️</span>
          健康状态
        </div>
        <div class="alerts-list" id="alerts-list"></div>
      </div>
    </div>

    <!-- History Table -->
    <p class="section-label" style="margin-top:8px">最近 7 天记录</p>
    <div class="history-card">
      <table class="history-table">
        <thead>
          <tr>
            <th>日期</th>
            <th>类型</th>
            <th>消息数</th>
            <th>数据量</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="history-tbody"></tbody>
      </table>
    </div>
  `;

  // Populate sections
  updateHeader(data.meta);
  renderMetrics(data.overview);
  renderTrendChart(data.message_trend_30d || []);
  renderAgentChart(data.agent_distribution || []);
  renderSessionPatterns(data.session_key_patterns || []);
  renderHealthAlerts(data.health_alerts || []);
  renderBackupStatus(data.backup_status || { files: [] });
  renderHistoryTable(data.message_trend_30d || []);

  // Animate metric numbers after a brief delay
  setTimeout(() => {
    document.querySelectorAll('.metric-value[data-target]').forEach(el => {
      const target = parseFloat(el.dataset.target);
      const suffix = el.dataset.suffix || '';
      animateCount(el, target, 1200, v => fmt(v) + suffix);
    });
  }, 100);
}

/* ── Data Loading ───────────────────────────────────────── */
async function loadData() {
  state.loading = true;
  state.error = null;
  renderSkeletons();

  try {
    const res = await fetch('./data/latest.json', { cache: 'no-cache' });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();

    // Validate minimal schema
    if (!data.meta || !data.overview || !data.agent_distribution) {
      throw new Error('JSON 格式不符合 schema v1.0（缺少必需字段）');
    }

    state.data = data;
    state.loading = false;
    renderDashboard(data);

  } catch (err) {
    state.loading = false;
    state.error = err.message;
    console.error('[LCM Dashboard] loadData failed:', err);
    renderError(
      '无法加载数据：' + err.message + '。请检查 exporter 是否正常运行，或等待下次 cron 刷新。'
    );
  }
}

/* ── Boot ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', loadData);
