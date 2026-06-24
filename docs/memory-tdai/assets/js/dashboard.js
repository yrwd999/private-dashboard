/**
 * memory-tdai Dashboard — Frontend Logic
 * Version: 1.0 | 2026-06-24
 * Spec: ../docs/DESIGN.md + ../../docs/DESIGN_TOKENS.md
 *
 * Dependencies: Chart.js v4 (CDN), no other libraries
 * Data source: ./data/latest.json (written by exporter_memory_tdai.py)
 */

'use strict';

/* ─────────────────────────────────────────────────────────
   DashboardMemoryTdai — Root Namespace
   ───────────────────────────────────────────────────────── */
class DashboardMemoryTdai {
  constructor() {
    this.data = null;
    this.charts = {};
    this.loading = true;
    this.error = null;
  }

  /* ── Boot ────────────────────────────────────────────── */
  async init() {
    this._renderSkeletons();
    await this.loadData();
  }

  /* ── Data Loading ────────────────────────────────────── */
  async loadData() {
    this.loading = true;
    this._renderSkeletons();

    try {
      const res = await fetch('./data/latest.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();

      // Minimal schema guard
      if (!data.meta || !data.l0 || !data.l1) {
        throw new Error('Schema v1.0 不匹配（缺少必需字段）');
      }

      this.data = data;
      this.loading = false;
      this._render(data);

    } catch (err) {
      this.loading = false;
      this.error = err.message;
      this._renderError(err.message);
    }
  }

  /* ── Skeleton ────────────────────────────────────────── */
  _renderSkeletons() {
    const main = document.getElementById('app-main');
    main.innerHTML = `
      <p class="section-label">系统状态</p>
      <div class="db-mtd-metrics-grid">
        ${[0,1,2,3,4].map(() => `
          <div class="db-mtd-card">
            <div class="skeleton" style="height:12px;width:55%;margin-bottom:12px"></div>
            <div class="skeleton" style="height:48px;width:70%;margin-bottom:10px"></div>
            <div class="skeleton" style="height:12px;width:45%"></div>
          </div>`).join('')}
      </div>
      <p class="section-label" style="margin-top:8px">向量完整性</p>
      <div class="db-mtd-charts-row">
        <div class="db-mtd-card">
          <div class="skeleton" style="height:220px;width:100%"></div>
        </div>
        <div class="db-mtd-card">
          <div class="skeleton" style="height:220px;width:100%"></div>
        </div>
      </div>
      <p class="section-label" style="margin-top:8px">告警</p>
      <div class="db-mtd-card" style="height:120px"></div>
    `;
  }

  /* ── Error State ──────────────────────────────────────── */
  _renderError(msg) {
    const main = document.getElementById('app-main');
    main.innerHTML = `
      <div class="db-mtd-error">
        <div class="db-mtd-error-icon">⚠️</div>
        <div class="db-mtd-error-title">数据加载失败</div>
        <div class="db-mtd-error-msg">${this._escHtml(msg)}</div>
        <button class="db-mtd-btn-retry" onclick="dashboard.loadData()">🔄 重新加载</button>
      </div>
    `;
  }

  /* ── Header ───────────────────────────────────────────── */
  _updateHeader(meta) {
    const elUpdated = document.getElementById('header-updated');
    const elDbsize  = document.getElementById('header-dbsize');
    if (elUpdated) elUpdated.textContent = '更新: ' + this._fmtRelTime(meta.generated_at);
    if (elDbsize)  elDbsize.textContent  = meta.vectors_db_size_mb + ' MB DB';
  }

  /* ── Metrics Grid ────────────────────────────────────── */
  _renderMetrics(l0, l1, storage, recall) {
    const grid = document.getElementById('metrics-grid');
    if (!grid) return;

    const l0pct = l0.completeness_pct;
    const l1pct = l1.completeness_pct;
    const l0Color = l0pct >= 99 ? 'green' : l0pct >= 95 ? 'orange' : 'red';
    const l1Color = l1pct >= 99 ? 'green' : l1pct >= 95 ? 'orange' : 'red';
    const walOversized = storage.wal_oversized;
    const walColor = walOversized ? 'red' : storage.wal_mb > 2 ? 'orange' : 'green';

    const cards = [
      {
        label: 'L0 向量完整率',
        icon: '💾',
        value: l0pct.toFixed(1) + '%',
        delta: `${l0.vectors.toLocaleString()} / ${l0.conversations.toLocaleString()} 条`,
        deltaColor: l0Color,
      },
      {
        label: 'L1 向量完整率',
        icon: '🧠',
        value: l1pct.toFixed(1) + '%',
        delta: `${l1.vectors.toLocaleString()} / ${l1.records.toLocaleString()} 条`,
        deltaColor: l1Color,
      },
      {
        label: 'HTTP 400 错误（24h）',
        icon: '🚨',
        value: l0.errors_24h.http_400_batch_size.toLocaleString(),
        delta: 'batch size bug',
        deltaColor: l0.errors_24h.http_400_batch_size > 0 ? 'orange' : 'green',
      },
      {
        label: 'WAL 文件大小',
        icon: '📦',
        value: storage.wal_mb.toFixed(1) + ' MB',
        delta: walOversized ? '⚠️ 过大' : '正常',
        deltaColor: walColor,
      },
      {
        label: 'vectors.db 大小',
        icon: '💽',
        value: storage.vectors_db_mb.toFixed(1) + ' MB',
        delta: 'JSONL ' + storage.jsonl_file_count + ' 文件',
        deltaColor: 'flat',
      },
    ];

    grid.innerHTML = cards.map(c => `
      <div class="db-mtd-card">
        <div class="db-mtd-card-label">
          <span>${c.icon}</span>
          ${c.label}
        </div>
        <div class="db-mtd-card-value db-mtd-color-${c.deltaColor}">${c.value}</div>
        <div class="db-mtd-card-delta db-mtd-color-${c.deltaColor}">${c.delta}</div>
      </div>
    `).join('');
  }

  /* ── L0/L1 Completeness Donut Charts ─────────────────── */
  _renderCompletenessCharts(l0, l1) {
    this._renderDonut(
      'chart-l0-wrap', 'chart-l0',
      l0.completeness_pct,
      `L0 完整率`,
      `${l0.missing.toLocaleString()} 条缺失`
    );
    this._renderDonut(
      'chart-l1-wrap', 'chart-l1',
      l1.completeness_pct,
      `L1 完整率`,
      `${l1.missing.toLocaleString()} 条缺失`
    );
  }

  _renderDonut(canvasId, chartId, pct, label, missingLabel) {
    const wrap = document.getElementById(canvasId);
    if (!wrap) return;

    if (this.charts[chartId]) {
      this.charts[chartId].destroy();
      this.charts[chartId] = null;
    }

    const canvas = document.getElementById(chartId);
    if (!canvas) return;

    const color = pct >= 99 ? '#30d158' : pct >= 95 ? '#ff9f0a' : '#ff3b30';
    const remaining = 100 - pct;

    this.charts[chartId] = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: [label, '缺失'],
        datasets: [{
          data: [pct, remaining],
          backgroundColor: [color, 'rgba(0,0,0,0.06)'],
          borderWidth: 0,
          hoverOffset: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '72%',
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
              label: (item) => {
                if (item.dataIndex === 0) {
                  return ` ${pct.toFixed(1)}% 完整`;
                }
                return ` ${remaining.toFixed(1)}% 缺失 (${missingLabel})`;
              },
            },
          },
        },
      },
    });
  }

  /* ── Error Distribution Bar Chart ─────────────────────── */
  _renderErrorChart(errors24h) {
    const wrap = document.getElementById('chart-errors-wrap');
    if (!wrap) return;

    if (this.charts.errors) {
      this.charts.errors.destroy();
      this.charts.errors = null;
    }

    const canvas = document.getElementById('chart-errors');
    if (!canvas) return;

    const labels = ['HTTP 400\n(batch)', 'HTTP 429\n(rate)', 'HTTP 5xx', 'Timeout', 'DB Locked'];
    const data   = [
      errors24h.http_400_batch_size,
      errors24h.http_429_rate_limit,
      errors24h.http_500_server,
      errors24h.timeout,
      errors24h.db_locked,
    ];
    const colors = data.map(v => v > 0 ? '#ff3b30' : '#86868b');

    this.charts.errors = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: '错误次数',
          data,
          backgroundColor: colors.map(c => c + '22'),
          borderColor: colors,
          borderWidth: 2,
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
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
              label: (item) => ` ${item.raw} 次`,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { font: { size: 11 }, color: '#6e6e73' },
          },
          y: {
            grid: { color: 'rgba(0,0,0,0.04)' },
            border: { dash: [4, 4] },
            ticks: {
              font: { size: 11 },
              color: '#6e6e73',
              precision: 0,
            },
          },
        },
      },
    });
  }

  /* ── Health Alerts ──────────────────────────────────── */
  _renderAlerts(alerts) {
    const list = document.getElementById('alerts-list');
    if (!list) return;

    if (!alerts || alerts.length === 0) {
      list.innerHTML = '<div class="db-mtd-alert db-mtd-alert-success">✅ 系统健康，无告警</div>';
      return;
    }

    const ICONS = { success: '✅', info: 'ℹ️', warning: '⚠️', error: '🚨', critical: '🔴' };
    const MAX = 8;

    list.innerHTML = alerts.slice(0, MAX).map(a => `
      <div class="db-mtd-alert db-mtd-alert-${a.level}">
        <span class="db-mtd-alert-icon">${ICONS[a.level] || 'ℹ️'}</span>
        <div class="db-mtd-alert-body">
          <div class="db-mtd-alert-msg">${this._escHtml(a.message)}</div>
          ${a.value !== undefined ? `<div class="db-mtd-alert-meta">值: ${a.value} | 阈值: ${a.threshold}</div>` : ''}
        </div>
        <span class="db-mtd-alert-code">${this._escHtml(a.code)}</span>
      </div>
    `).join('');
  }

  /* ── Secondary Status Row ────────────────────────────── */
  _renderSecondary(l2, l3, recall, cleaning, api) {
    // L2 scene blocks
    const l2El = document.getElementById('l2-status');
    if (l2El) {
      const freshnessColor = { healthy: 'green', warning: 'orange', stale: 'red' }[l2.freshness] || 'gray';
      const freshnessLabel = { healthy: '✅ 正常', warning: '⚠️ 较旧', stale: '🔴 过期' }[l2.freshness] || '—';
      l2El.innerHTML = `
        <div class="db-mtd-secondary-item">
          <div class="db-mtd-secondary-label">💡 场景块（L2）</div>
          <div class="db-mtd-secondary-value">${l2.scene_blocks} 块</div>
          <div class="db-mtd-secondary-delta db-mtd-color-${freshnessColor}">${freshnessLabel}</div>
        </div>
      `;
    }

    // L3 persona
    const l3El = document.getElementById('l3-status');
    if (l3El) {
      const freshnessColor = { healthy: 'green', warning: 'orange', stale: 'red' }[l3.freshness] || 'gray';
      const freshnessLabel = { healthy: '✅ 正常', warning: '⚠️ 较旧', stale: '🔴 过期' }[l3.freshness] || '—';
      l3El.innerHTML = `
        <div class="db-mtd-secondary-item">
          <div class="db-mtd-secondary-label">👤 用户画像（L3）</div>
          <div class="db-mtd-secondary-value">${l3.persona_exists ? '已配置' : '未配置'}</div>
          <div class="db-mtd-secondary-delta db-mtd-color-${freshnessColor}">${freshnessLabel}</div>
        </div>
      `;
    }

    // Recall
    const recallEl = document.getElementById('recall-status');
    if (recallEl) {
      const recallColor = recall.status === 'healthy' ? 'green' : 'orange';
      const recallIcon = recall.status === 'healthy' ? '✅' : '⚠️';
      recallEl.innerHTML = `
        <div class="db-mtd-secondary-item">
          <div class="db-mtd-secondary-label">🔍 Recall 策略</div>
          <div class="db-mtd-secondary-value">${recall.strategy}</div>
          <div class="db-mtd-secondary-delta db-mtd-color-${recallColor}">${recallIcon} ${recall.status}</div>
        </div>
      `;
    }

    // Cleaner
    const cleanEl = document.getElementById('clean-status');
    if (cleanEl) {
      const cleanColor = cleaning.effectiveness === 'healthy' ? 'green' : 'orange';
      cleanEl.innerHTML = `
        <div class="db-mtd-secondary-item">
          <div class="db-mtd-secondary-label">🧹 Cleaner</div>
          <div class="db-mtd-secondary-value">保留 ${cleaning.retention_days} 天</div>
          <div class="db-mtd-secondary-delta db-mtd-color-${cleanColor}">
            ${cleaning.l0_expired > 0 ? '✅ 有过期' : '⚠️ 0 过期（可能过长）'}
          </div>
        </div>
      `;
    }

    // API
    const apiEl = document.getElementById('api-status');
    if (apiEl) {
      const emb = api.embedding;
      const availColor = emb.availability_24h >= 99.5 ? 'green' : emb.availability_24h >= 95 ? 'orange' : 'red';
      apiEl.innerHTML = `
        <div class="db-mtd-secondary-item">
          <div class="db-mtd-secondary-label">☁️ Embedding API</div>
          <div class="db-mtd-secondary-value">${emb.model}</div>
          <div class="db-mtd-secondary-delta db-mtd-color-${availColor}">
            可用率 ${emb.availability_24h.toFixed(1)}%
          </div>
        </div>
      `;
    }
  }

  /* ── Full Render ─────────────────────────────────────── */
  _render(data) {
    const main = document.getElementById('app-main');
    const l0 = data.l0;
    const l1 = data.l1;
    const storage = data.storage;
    const l2 = data.l2;
    const l3 = data.l3;
    const recall = data.recall;
    const api = data.api;
    const cleaning = data.cleaning;

    main.innerHTML = `
      <!-- Metrics Grid -->
      <p class="db-mtd-section-label">系统状态</p>
      <div class="db-mtd-metrics-grid" id="metrics-grid"></div>

      <!-- Charts Row -->
      <p class="db-mtd-section-label" style="margin-top:4px">向量完整性</p>
      <div class="db-mtd-charts-row">
        <div class="db-mtd-card">
          <div class="db-mtd-chart-header">
            <div class="db-mtd-chart-title">L0 对话层</div>
            <div class="db-mtd-chart-sub">${l0.conversations.toLocaleString()} 对话 · ${l0.vectors.toLocaleString()} 向量</div>
          </div>
          <div class="db-mtd-chart-wrap" id="chart-l0-wrap">
            <canvas id="chart-l0"></canvas>
          </div>
        </div>

        <div class="db-mtd-card">
          <div class="db-mtd-chart-header">
            <div class="db-mtd-chart-title">L1 记忆层</div>
            <div class="db-mtd-chart-sub">${l1.records.toLocaleString()} 记忆 · ${l1.vectors.toLocaleString()} 向量</div>
          </div>
          <div class="db-mtd-chart-wrap" id="chart-l1-wrap">
            <canvas id="chart-l1"></canvas>
          </div>
        </div>
      </div>

      <!-- Error Distribution -->
      <p class="db-mtd-section-label" style="margin-top:4px">错误分布（24 小时）</p>
      <div class="db-mtd-card">
        <div class="db-mtd-chart-header">
          <div class="db-mtd-chart-title">Embedding 错误</div>
          <div class="db-mtd-chart-sub">HTTP 400 batch_size 是已知问题（MAX_BATCH_SIZE=256 vs API limit=10）</div>
        </div>
        <div class="db-mtd-chart-wrap" style="height:180px" id="chart-errors-wrap">
          <canvas id="chart-errors"></canvas>
        </div>
      </div>

      <!-- Alerts -->
      <p class="db-mtd-section-label" style="margin-top:4px">健康告警</p>
      <div class="db-mtd-card" id="alerts-card">
        <div class="db-mtd-alerts-list" id="alerts-list"></div>
      </div>

      <!-- Secondary Status Row -->
      <p class="db-mtd-section-label" style="margin-top:4px">子系统状态</p>
      <div class="db-mtd-secondary-grid">
        <div id="l2-status"></div>
        <div id="l3-status"></div>
        <div id="recall-status"></div>
        <div id="clean-status"></div>
        <div id="api-status"></div>
      </div>
    `;

    // Populate
    this._updateHeader(data.meta);
    this._renderMetrics(l0, l1, storage, recall);
    this._renderCompletenessCharts(l0, l1);
    this._renderErrorChart(l0.errors_24h);
    this._renderAlerts(data.health_alerts);
    this._renderSecondary(l2, l3, recall, cleaning, api);
  }

  /* ── Utilities ──────────────────────────────────────── */
  _escHtml(str) {
    if (str === undefined || str === null) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
  }

  _fmtRelTime(isoString) {
    try {
      const d = new Date(isoString);
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const hh  = String(d.getHours()).padStart(2, '0');
      const mm  = String(d.getMinutes()).padStart(2, '0');
      return `${m}-${day} ${hh}:${mm}`;
    } catch {
      return String(isoString);
    }
  }
}

/* ── Boot ───────────────────────────────────────────────── */
let dashboard;
document.addEventListener('DOMContentLoaded', () => {
  dashboard = new DashboardMemoryTdai();
  dashboard.init();

  // Auto-refresh every 60 seconds
  setInterval(() => { dashboard.loadData(); }, 60_000);
});
