(() => {
  'use strict';
  const data = window.REPLAY_DATA;
  if (!data || !Array.isArray(data.snapshots) || !data.snapshots.length) {
    const error = document.getElementById('analyticsError');
    error.textContent = !data ? 'Historical replay unavailable.' : 'Historical replay contains no snapshots.';
    error.hidden = false;
    return;
  }
  const snapshots = data.snapshots;
  let executionQuality = null;
  const CALMAR_NOTE = [
    'HAI SỐ KHÁC QUY ƯỚC — không so trực tiếp được.',
    'Dashboard KHÔNG so hai ô này: không có gate, không có cảnh báo nào gắn vào chúng.',
    '',
    'Calmar: curve của chính dashboard này — dữ liệu đầy đủ tới hiện tại, CÓ cluster',
    '  stress, metrics() trên _daily_realized.',
    'Backtest fit_A: deploy_sim trên dữ liệu FROZEN, --end 2024-12-31, KHÔNG có stress,',
    '  2 tick/side, n_contracts=1.',
    '',
    'Kể cả khi đưa về cùng quy ước, 1.65 vẫn không phải một vạch sắc. Đo 2026-08-15',
    '(futures/measure_seed_pnl.py): 5 hạt giống ngẫu nhiên của CÙNG một hệ, cùng dữ liệu,',
    'cùng mọi tham số, cho Calmar trải 1.56–1.72 — và 2/5 rơi xuống dưới 1.65. Nguyên nhân',
    'có cấu trúc: mẫu số của Calmar là MaxDD, một ngày duy nhất, chỉ nhận hai giá trị qua',
    'cả 5 lần chạy. PF trải 0.68% và Sharpe 2.42% trong khi Calmar trải 9.47%.',
    '',
    'Nên: một lần Calmar xuống dưới 1.65 KHÔNG đủ để kết luận hệ suy giảm. Chạy',
    'futures/measure_seed_pnl.py xem con số có nằm trong dải nhiễu không rồi mới kết luận.',
    'Chi tiết: docs/futures/CALMAR_PROVENANCE.md §4b, §4c.',
  ].join('\n');
  let selected = Math.max(0, snapshots.length - 1);
  const $ = id => document.getElementById(id);
  const money = value => value == null ? '--' : `${Number(value) >= 0 ? '+' : '-'}$${Math.abs(Number(value)).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  const num = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? '--' : Number(value).toFixed(digits);
  const percent = value => value == null ? '--' : `${(Number(value) * 100).toFixed(2)}%`;
  const cls = value => Number(value) >= 0 ? 'positive' : 'negative';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

  function rankRows(values, formatter = money) {
    const entries = Object.entries(values || {}).sort((a, b) => Math.abs(Number(b[1]) || 0) - Math.abs(Number(a[1]) || 0));
    return entries.length ? entries.map(([key, value]) => `<div class="rank-row"><span>${esc(key)}</span><b class="${cls(value)}">${esc(formatter(value))}</b></div>`).join('') : '<div class="rank-row"><span>No data</span><b>--</b></div>';
  }

  function allClosedThrough(index) {
    const trades = [];
    for (let i = 0; i <= index; i += 1) {
      const snap = snapshots[i];
      (snap.decision?.exits || []).forEach(trade => trades.push({ ...trade, exit_day: trade.exit_day || snap.date }));
    }
    return trades;
  }

  function renderMetrics(snap) {
    const metrics = snap.running_metrics || {};
    $('histEquity').textContent = snap.equity == null ? '--' : `$${Math.round(snap.equity).toLocaleString('en-US')}`;
    $('histReturn').textContent = percent(metrics.total_return);
    $('histReturn').className = cls(metrics.total_return);
    $('histCalmar').textContent = num(metrics.calmar);
    $('histSharpe').textContent = num(metrics.sharpe);
    $('histMaxDd').textContent = money(metrics.max_dd == null ? snap.max_dd_dollars : -Math.abs(metrics.max_dd));
    const baseline = data.meta?.backtest_calmar;
    $('histBaseline').textContent = baseline == null ? 'Missing' : num(baseline);
    $('histBaseline').className = baseline == null ? 'warning' : '';
    $('calmarSource').textContent = metrics.calmar == null ? 'insufficient observations' : 'running through selected day';
    // Hai ô Calmar / Floor fit_A KHÔNG cùng quy ước đo — đừng để cạnh nhau mà không khai.
    // Calmar: curve này, dữ liệu đầy đủ tới hiện tại, CÓ stress.
    // Floor:  deploy_sim, dữ liệu FROZEN, --end 2024-12-31, KHÔNG stress, 2 tick/side, n=1.
    // So đúng cặp thì phải so floor với baseline chạy cùng quy ước (INVARIANTS.md).
    $('histCalmar').title = CALMAR_NOTE;
    $('histBaseline').title = CALMAR_NOTE;
  }

  function renderAttribution(snap) {
    $('clusterPnl').innerHTML = rankRows(snap.per_cluster_pnl);
    $('regimePnl').innerHTML = rankRows(snap.regime_attribution);
    const holds = {};
    Object.entries(snap.holding_distribution || {}).forEach(([cluster, value]) => {
      holds[cluster] = value?.median_hold_days;
    });
    $('holdingProfile').innerHTML = rankRows(holds, value => value == null ? '--' : `${num(value, 1)}d`);
  }

  function renderTrades() {
    const trades = allClosedThrough(selected);
    $('tradeCount').textContent = `${trades.length} trade(s)`;
    $('tradeBody').innerHTML = trades.length ? trades.slice(-100).reverse().map(trade => `<tr>
      <td>${esc(trade.exit_day || '--')}</td><td>${esc(trade.inst || '--')}</td><td>${esc(trade.cluster || '--')}</td><td>${esc(trade.direction || '--')}</td>
      <td class="num">${esc(num(trade.entry_price))}</td><td class="num">${esc(num(trade.exit_price))}</td><td class="num ${cls(trade.pnl)}">${esc(money(trade.pnl))}</td><td>${esc(trade.exit_reason || '--')}</td>
    </tr>`).join('') : '<tr><td colspan="8">No closed trades through selected day.</td></tr>';
  }

  function renderExecutionHistory(selectedDay) {
    const container = $('executionHistoryMetrics');
    if (!executionQuality) {
      container.innerHTML = '<div><span>Paper fills</span><b>--</b><small>source unavailable</small></div>';
      $('executionHistoryNote').textContent = 'Paper execution evidence is unavailable; replay metrics above are unaffected.';
      return;
    }
    const fills = (executionQuality.fills || []).filter(fill => fill.day && fill.day <= selectedDay);
    const evaluable = fills.filter(fill => fill.signed_slippage_ticks != null);
    const opens = evaluable.filter(fill => fill.type === 'OPEN');
    const stops = evaluable.filter(fill => fill.reference_type === 'stop_trigger');
    const mean = rows => rows.length ? rows.reduce((sum,fill)=>sum+Number(fill.signed_slippage_ticks),0)/rows.length : null;
    const fmt = value => value == null ? '--' : `${value>=0?'+':''}${value.toFixed(2)}t`;
    const over = evaluable.filter(fill => Number(fill.signed_slippage_ticks) > Number(executionQuality.assumption_ticks || 2)).length;
    const signalCloseGap = fills.filter(fill => fill.reference_type === 'protective_stop_reference').length;
    container.innerHTML = [
      ['Paper fills',fills.length,'retained through selected date',''],
      ['Evaluable',evaluable.length,'expected entry or stop trigger',''],
      ['Mean slippage',fmt(mean(evaluable)),`${evaluable.filter(fill=>fill.adverse).length} adverse`,mean(evaluable)>2?'warning':''],
      ['Open mean',fmt(mean(opens)),`${opens.length} fills`,mean(opens)>2?'warning':''],
      ['Stop-fill mean',fmt(mean(stops)),`${stops.length} fills`,mean(stops)>2?'warning':''],
      ['Above 2 ticks',over,`${signalCloseGap} signal closes not evaluable`,over?'warning':'']
    ].map(([label,value,note,tone])=>`<div><span>${esc(label)}</span><b class="${tone}">${esc(value)}</b><small>${esc(note)}</small></div>`).join('');
    $('executionHistoryNote').textContent = `Commission ${(executionQuality.coverage?.commission_emitted||0)}/${executionQuality.coverage?.fill_records||0} · route ${(executionQuality.coverage?.route_emitted||0)}/${executionQuality.coverage?.fill_records||0} · signal-close protective-stop distance is excluded from execution slippage.`;
  }

  function drawChart() {
    const canvas = $('historyChart');
    const frame = canvas.parentElement;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, frame.clientWidth);
    const height = Math.max(220, frame.clientHeight);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, width, height);
    const pad = { left: 58, right: 52, top: 20, bottom: 28 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const rows = snapshots.slice(0, selected + 1);
    if (rows.length < 2) return;
    const equities = rows.map(row => Number(row.equity)).filter(Number.isFinite);
    const dds = rows.map(row => Number(row.drawdown_pct || 0) * 100);
    const minEq = Math.min(...equities);
    const maxEq = Math.max(...equities);
    const maxDd = Math.max(1, ...dds);
    const x = index => pad.left + (index / Math.max(1, rows.length - 1)) * plotW;
    const yEq = value => pad.top + (1 - (value - minEq) / Math.max(1, maxEq - minEq)) * plotH;
    const yDd = value => pad.top + (value / maxDd) * plotH;

    ctx.strokeStyle = '#202b34'; ctx.lineWidth = 1; ctx.fillStyle = '#5b6975'; ctx.font = '9px "Cascadia Mono", Consolas, monospace';
    for (let i = 0; i <= 4; i += 1) {
      const y = pad.top + (i / 4) * plotH;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
      const eqLabel = maxEq - (i / 4) * (maxEq - minEq);
      ctx.fillText(`$${Math.round(eqLabel / 1000)}k`, 8, y + 3);
      ctx.fillText(`${((i / 4) * maxDd).toFixed(1)}%`, width - pad.right + 8, y + 3);
    }
    ctx.strokeStyle = '#58a3ff'; ctx.lineWidth = 2; ctx.beginPath();
    rows.forEach((row, index) => { const py = yEq(Number(row.equity)); index ? ctx.lineTo(x(index), py) : ctx.moveTo(x(index), py); }); ctx.stroke();
    ctx.strokeStyle = '#f05b61'; ctx.lineWidth = 1.5; ctx.beginPath();
    dds.forEach((value, index) => { const py = yDd(value); index ? ctx.lineTo(x(index), py) : ctx.moveTo(x(index), py); }); ctx.stroke();
    ctx.strokeStyle = '#8b72ff'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x(rows.length - 1), pad.top); ctx.lineTo(x(rows.length - 1), height - pad.bottom); ctx.stroke(); ctx.setLineDash([]);
  }

  function render() {
    const snap = snapshots[selected];
    if (!snap) return;
    $('selectedDate').textContent = snap.date;
    $('rangeLabel').textContent = `${snapshots[0]?.date || '--'} -> ${snapshots[snapshots.length - 1]?.date || '--'}`;
    $('snapshotCount').textContent = String(data.meta?.total_days ?? snapshots.length);
    $('replayContract').className = 'warning';
    renderMetrics(snap);
    renderAttribution(snap);
    renderTrades();
    renderExecutionHistory(snap.date);
    drawChart();
  }

  const slider = $('daySlider');
  slider.max = Math.max(0, snapshots.length - 1);
  slider.value = selected;
  slider.addEventListener('input', event => { selected = Number(event.target.value); render(); });
  window.addEventListener('resize', drawChart);
  render();
  fetch('/api/v1/execution-quality',{cache:'no-store'})
    .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
    .then(value => { executionQuality=value; renderExecutionHistory(snapshots[selected].date); })
    .catch(() => { executionQuality={fills:[],coverage:{},error:'unavailable'}; renderExecutionHistory(snapshots[selected].date); });
})();
