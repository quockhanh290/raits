(function () {
  'use strict';

  const CL_ORDER = ['roska4_swing', 'roska4_stress', 'global_nkd'];
  const CL_LABELS = {
    roska4_swing: 'R4 Swing',
    roska4_stress: 'R4 Stress',
    global_nkd: 'NKD Global'
  };
  const CL_COLOR = {
    roska4_swing: '#2f7dd3',
    roska4_stress: '#a56a00',
    global_nkd: '#7b61ff'
  };
  const INSTRUMENTS = ['MES', 'MNQ', 'MYM', 'M2K', 'MNKD'];
  const DESIGN_CAPITAL = 50000;
  const BACKTEST_CALMAR_FALLBACK = 1.65;

  const money0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const money2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function data() {
    return window.LIVE_DATA || null;
  }

  function latestSnap() {
    const d = data();
    const snaps = d && Array.isArray(d.snapshots) ? d.snapshots : [];
    return snaps.length ? snaps[snaps.length - 1] : {};
  }

  function meta() {
    const d = data();
    return (d && d.meta) || {};
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function fmtMoney(value, signed) {
    if (value == null || Number.isNaN(Number(value))) return '--';
    const n = Number(value);
    const sign = signed && n > 0 ? '+' : n < 0 ? '-' : '';
    return sign + '$' + money0.format(Math.abs(n));
  }

  function fmtPct(value, digits) {
    if (value == null || Number.isNaN(Number(value))) return '--';
    return (Number(value) * 100).toFixed(digits == null ? 1 : digits) + '%';
  }

  function fmtPctAlready(value, digits) {
    if (value == null || Number.isNaN(Number(value))) return '--';
    return Number(value).toFixed(digits == null ? 2 : digits) + '%';
  }

  function statusClass(value) {
    const v = String(value || '').toLowerCase();
    if (v === 'ok' || v === 'normal' || v === 'true') return 'ok';
    if (v === 'urgent' || v === 'alert' || v === 'halt') return 'bad';
    if (v === 'false') return 'bad';
    return 'warn';
  }

  function stopCell(p) {
    if (p.stop_order_id === undefined && p.stop_deferred === undefined)
      return '<span class="stop-muted">--</span>';
    if (p.stop_order_id)
      return `<span class="stop-live">#${esc(p.stop_order_id)}`
        + (p.stop_price != null ? ` @ ${money2.format(Number(p.stop_price))}` : '')
        + '</span>';
    if (p.stop_deferred)
      return `<span class="stop-deferred" title="Deliberate stop-free window; not an alarm">deferred`
        + (p.stop_price != null ? ` @ ${Number(p.stop_price).toFixed(2)}` : '')
        + '</span>';
    return '<span class="stop-naked">NAKED</span>';
  }

  function clusterRows() {
    const m = meta();
    const snap = latestSnap();
    const exp = snap.cluster_exposure || {};
    const pos = snap.open_positions || [];
    return CL_ORDER.map(cl => {
      const cap = (m.clusters && m.clusters[cl]) || {};
      const gross = (exp[cl] && exp[cl].gross_pct) || 0;
      const net = (exp[cl] && exp[cl].net_pct) || 0;
      const capGross = cap.max_gross_pct;
      const capNet = cap.max_net_pct;
      const usage = capGross ? Math.min(100, (gross / capGross) * 100) : 0;
      const count = pos.filter(p => p.cluster === cl).length;
      return { cl, label: CL_LABELS[cl], color: CL_COLOR[cl], gross, net, capGross, capNet, usage, count };
    });
  }

  function positionRows() {
    return (latestSnap().open_positions || []).map(p => {
      const direction = String(p.direction || '');
      return `<tr>
        <td><b>${esc(p.inst)}</b></td>
        <td><span class="cluster-dot" style="--dot:${CL_COLOR[p.cluster] || '#677483'}"></span>${esc(CL_LABELS[p.cluster] || p.cluster)}</td>
        <td><span class="dir ${direction.toLowerCase()}">${esc(direction)}</span></td>
        <td>${esc(p.entry_day || '--')}</td>
        <td class="num">${p.entry_price != null ? money2.format(Number(p.entry_price)) : '--'}</td>
        <td class="num">${p.days_held != null ? esc(p.days_held) + 'd' : '--'}</td>
        <td class="num">${fmtMoney(p.risk_sized, false)}</td>
        <td>${stopCell(p)}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="8" class="empty">flat</td></tr>';
  }

  function clusterCards() {
    return clusterRows().map(c => `<article class="cluster-block" style="--accent:${c.color}">
      <div class="row spread"><b>${esc(c.label)}</b><span>${c.count} pos</span></div>
      <div class="gauge"><span style="width:${c.usage.toFixed(1)}%"></span></div>
      <div class="row micro"><span>gross ${fmtPct(c.gross, 1)} / ${fmtPct(c.capGross, 1)}</span><span>${c.capNet == null ? 'net uncapped' : 'net ' + fmtPct(c.net, 1) + ' / ' + fmtPct(c.capNet, 1)}</span></div>
    </article>`).join('');
  }

  function decisionsHtml() {
    const dec = latestSnap().decision || {};
    const rows = [];
    (dec.exits || []).forEach(e => rows.push(`<div class="activity exit">
      <b>${esc(e.inst)}</b><span>${esc(e.direction)}</span><span>${esc(CL_LABELS[e.cluster] || e.cluster)}</span>
      <strong class="${(e.pnl || 0) >= 0 ? 'gain' : 'loss'}">${fmtMoney(e.pnl || 0, true)}</strong>
    </div>`));
    (dec.entries || []).forEach(e => rows.push(`<div class="activity entry">
      <b>${esc(e.inst)}</b><span>${esc(e.direction)}</span><span>${esc(CL_LABELS[e.cluster] || e.cluster)}</span>
      <strong>${fmtMoney(e.risk_sized, false)}</strong>
    </div>`));
    (dec.rejected_detail || []).forEach(r => rows.push(`<div class="activity reject">
      <b>${esc(r.inst)}</b><span>${esc(r.direction)}</span><span>${esc(CL_LABELS[r.cluster] || r.cluster)}</span>
      <strong>${esc(r.reason || 'rejected')}</strong>
    </div>`));
    if (dec.halted_today) rows.push(`<div class="activity reject"><b>HALT</b><span></span><span></span><strong>${esc(dec.halted_today)} halted</strong></div>`);
    return rows.join('') || '<div class="empty">no entries, rejects, or halt events today</div>';
  }

  function eventsHtml(limit) {
    const evs = (meta().events || []).slice(-(limit || 5)).reverse();
    return evs.map(e => `<li class="${statusClass(e.level)}"><span>${esc((e.ts || '').replace('T', ' ').slice(0, 16))}</span><b>${esc(e.level || '--')}</b><em>${esc(e.category || '')}</em>${esc(e.message || '')}</li>`).join('') || '<li class="empty">no events</li>';
  }

  function sparklineSvg() {
    const snaps = (data() && data().snapshots) || [];
    const values = snaps.map(s => Number(s.equity)).filter(Number.isFinite);
    if (values.length < 2) return '<div class="chart-fallback">Only one live equity point is available.</div>';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const pts = values.map((v, i) => {
      const x = values.length === 1 ? 0 : (i / (values.length - 1)) * 100;
      const y = 100 - ((v - min) / span) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
    return `<svg class="spark" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Live equity sparkline"><polyline points="${pts}"></polyline></svg>`;
  }

  function barSeriesHtml() {
    const snap = latestSnap();
    const pnl = snap.per_cluster_pnl || {};
    const maxAbs = Math.max(1, ...Object.values(pnl).map(v => Math.abs(Number(v) || 0)));
    return CL_ORDER.map(cl => {
      const v = Number(pnl[cl] || 0);
      return `<div class="bar-row"><span>${esc(CL_LABELS[cl])}</span><i><b class="${v >= 0 ? 'gain-bg' : 'loss-bg'}" style="width:${Math.max(2, Math.abs(v) / maxAbs * 100).toFixed(1)}%"></b></i><strong class="${v >= 0 ? 'gain' : 'loss'}">${fmtMoney(v, true)}</strong></div>`;
    }).join('');
  }

  function healthHtml() {
    const op = meta().operational_status || latestSnap().operational_status || {};
    const items = [
      ['Runner', op.runner && op.runner.alive ? 'alive' : 'down', op.runner && op.runner.pid ? 'pid ' + op.runner.pid : ''],
      ['Breaker', op.breaker && op.breaker.level, op.breaker ? `DD ${fmtPctAlready(op.breaker.dd_pct, 2)} day ${fmtPctAlready(op.breaker.day_dd_pct, 2)}` : ''],
      ['Regime', op.regime_freshness && op.regime_freshness.status, op.regime_freshness && op.regime_freshness.last_spy_date],
      ['Model', op.model_age && op.model_age.status, op.model_age ? `${op.model_age.model_name || ''} ${op.model_age.months_old || '--'}mo` : ''],
      ['Positions', op.positions && op.positions.persist_match, op.positions ? `${op.positions.count || 0} open` : '']
    ];
    return items.map(([k, v, detail]) => `<div class="health ${statusClass(v)}"><span>${esc(k)}</span><b>${esc(v == null ? '--' : v)}</b><em>${esc(detail || '')}</em></div>`).join('');
  }

  function renderBasics() {
    const m = meta();
    const snap = latestSnap();
    const op = m.operational_status || snap.operational_status || {};
    document.querySelectorAll('[data-live-date]').forEach(el => { el.textContent = snap.date || m.system_epoch || '--'; });
    document.querySelectorAll('[data-system-equity]').forEach(el => { el.textContent = fmtMoney(m.final_equity, false); });
    document.querySelectorAll('[data-net-pnl]').forEach(el => {
      el.textContent = fmtMoney(m.net_pnl, true);
      el.className = (m.net_pnl || 0) >= 0 ? 'gain' : 'loss';
    });
    document.querySelectorAll('[data-broker-equity]').forEach(el => { el.textContent = fmtMoney(m.broker_equity, false); });
    document.querySelectorAll('[data-design-capital]').forEach(el => { el.textContent = fmtMoney(DESIGN_CAPITAL, false); });
    document.querySelectorAll('[data-account]').forEach(el => { el.textContent = fmtMoney(m.account, false); });
    document.querySelectorAll('[data-open-count]').forEach(el => { el.textContent = String((snap.open_positions || []).length); });
    document.querySelectorAll('[data-breaker]').forEach(el => { el.textContent = (op.breaker && op.breaker.level) || snap.breaker_level || '--'; el.className = statusClass(el.textContent); });
    document.querySelectorAll('[data-regime]').forEach(el => { el.textContent = snap.regime || '--'; });
    document.querySelectorAll('[data-calmar]').forEach(el => { el.textContent = Number(m.backtest_calmar || BACKTEST_CALMAR_FALLBACK).toFixed(2); });
    document.querySelectorAll('[data-max-dd]').forEach(el => { el.textContent = `${fmtMoney(m.max_dd_dollars, false)} / ${fmtPct(m.max_dd_pct, 2)}`; });
    document.querySelectorAll('[data-instruments]').forEach(el => { el.textContent = INSTRUMENTS.join(' / '); });
  }

  function renderInto(selector, html) {
    document.querySelectorAll(selector).forEach(el => { el.innerHTML = html; });
  }

  function renderCharts() {
    renderInto('[data-sparkline]', sparklineSvg());
    renderInto('[data-cluster-pnl]', barSeriesHtml());
    if (!window.Chart) return;
    document.querySelectorAll('canvas[data-equity-chart]').forEach(canvas => {
      const snaps = (data() && data().snapshots) || [];
      if (!snaps.length || canvas.dataset.rendered) return;
      canvas.dataset.rendered = '1';
      const fallback = canvas.parentElement && canvas.parentElement.querySelector('[data-sparkline]');
      if (fallback) fallback.style.display = 'none';
      new window.Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: snaps.map(s => s.date),
          datasets: [
            { label: 'System equity', data: snaps.map(s => s.equity), borderColor: '#2f7dd3', backgroundColor: 'rgba(47,125,211,.08)', fill: true, tension: .25 },
            { label: 'Drawdown %', data: snaps.map(s => (s.drawdown_pct || 0) * 100), borderColor: '#c64b4b', yAxisID: 'y1', tension: .25 }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { boxWidth: 10 } } },
          scales: { y: { grid: { color: 'rgba(120,130,145,.16)' } }, y1: { position: 'right', grid: { display: false } } }
        }
      });
    });
  }

  function render() {
    if (!data()) {
      renderInto('[data-error]', '<b>Live data missing.</b> Open this page beside live_state_data.js.');
      return;
    }
    renderBasics();
    renderInto('[data-positions]', positionRows());
    renderInto('[data-clusters]', clusterCards());
    renderInto('[data-decisions]', decisionsHtml());
    renderInto('[data-events]', eventsHtml(6));
    renderInto('[data-health]', healthHtml());
    renderCharts();
  }

  window.RaitsLive = { render, stopCell, _test: { latestSnap, meta } };
  window.addEventListener('DOMContentLoaded', render);
  window.addEventListener('load', renderCharts);
}());
