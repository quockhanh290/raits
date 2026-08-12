(() => {
  'use strict';

  const POLL_MS = 8000;
  const EVENT_JOURNAL_LIMIT = 24;
  const state = { runner: null, runnerPositions: null, broker: null, schedule: null, sessionEvents: null, jobJournal: null, executionQuality: null, openIssues: null, selectedJobId: null, selectedIssueKey: null, selectedMonitorKey: null, selectedEventKey: null, journalView: 'jobs', issuesSectionOpen: null };
  const compactIssueMedia = window.matchMedia('(max-width: 680px)');
  const roots = ['MNKD', 'M2K', 'MNQ', 'MYM', 'MES'];
  const railTips = {
    'State updates': 'Whether runner snapshots are arriving when expected by the trading calendar and scheduler evidence.',
    'Latest job': 'Observed outcome of the latest due scheduler slot.',
    'IBKR feed': 'Whether the read-only IBKR source is connected and fresh enough for operational conclusions.',
    'Stop protection': 'Checks exact contract, opposite stop action, quantity, and a live Submitted or PreSubmitted status.',
    'Position match': 'Compares current IBKR positions with persisted runner intent, including quantity when available.',
    'Risk breaker': 'Current circuit-breaker state. Drawdown magnitude is shown in the gauge above.',
    'Regime data': 'Freshness of the SPY regime input; the active regime is shown in the context row above.',
    'Model health': 'Age and maintenance status of the fitted model. Known debt is separated from new incidents.',
    'HMM fit': 'Grouped daily fit evidence. A convergence warning is diagnostic when the fit still selects a best initialisation and emits its model summary.'
  };

  const $ = id => document.getElementById(id);
  const FONT_KEY = 'raits-dashboard-font';
  const FONT_OPTIONS = new Set(['cascadia', 'consolas', 'jetbrains', 'ibm-plex', 'lucida', 'courier', 'system']);
  const applyFont = value => {
    const font = FONT_OPTIONS.has(value) ? value : 'cascadia';
    document.documentElement.dataset.font = font;
    if ($('fontSelector')) $('fontSelector').value = font;
    return font;
  };
  let savedFont = 'cascadia';
  try { savedFont = localStorage.getItem(FONT_KEY) || savedFont; } catch (_) { /* Browser storage is optional. */ }
  applyFont(savedFont);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[ch]);
  const money = value => value == null || Number.isNaN(Number(value))
    ? '--'
    : `${Number(value) >= 0 ? '+' : '-'}$${Math.abs(Number(value)).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  const dollars = value => value == null || Number.isNaN(Number(value))
    ? '--'
    : `$${Math.abs(Number(value)).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  const tradeMoney = value => {
    if (value == null || Number.isNaN(Number(value))) return '--';
    const amount = Number(value);
    const decimals = Number.isInteger(amount) ? 0 : 2;
    return `${amount >= 0 ? '+' : '-'}$${Math.abs(amount).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: 2 })}`;
  };
  const price = value => value == null ? '--' : Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
  const pct = value => value == null ? '--' : `${(Number(value) * 100).toFixed(2)}%`;
  const age = seconds => {
    if (seconds == null) return 'unknown age';
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    return `${(seconds / 3600).toFixed(1)}h ago`;
  };
  const sessionDate = value => value ? new Date(`${value}T12:00:00Z`).toLocaleDateString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric'
  }) : '--';
  const etClock = iso => iso ? new Date(iso).toLocaleTimeString('en-US', {
    timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false
  }) + ' ET' : '--';
  const localTime = iso => iso ? new Date(iso).toLocaleString('en-CA', {
    timeZone: 'America/New_York', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
  }) + ' ET' : '--';

  // ── Status-rail wall clock ───────────────────────────────────────────────
  // The time it is NOW, which is a different thing from every other timestamp on this page:
  // those describe when data was observed. The backend binds 127.0.0.1, so the only browser
  // that can open this page runs on the machine the scheduler fires on — the browser clock
  // IS the server clock and needs no round-trip. That stops being true the day this is
  // served over the LAN, and then it has to anchor on server_now instead.
  const ET_ZONE = 'America/New_York';
  const CLOCK_ZONES = [
    { label: 'JST', zone: 'Asia/Tokyo' },
    { label: 'HAN', zone: 'Asia/Ho_Chi_Minh' },
    { label: 'YYC', zone: 'America/Edmonton' }
  ];
  const zoneParts = (date, zone, withSeconds) => new Intl.DateTimeFormat('en-CA', {
    timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    ...(withSeconds ? { second: '2-digit' } : {})
  }).formatToParts(date).reduce((acc, part) => { acc[part.type] = part.value; return acc; }, {});
  const zoneDayNumber = parts => Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)) / 86400000;
  // Tokyo at 03:23 sitting beside New York at 14:23 reads as eleven hours earlier the same
  // day unless the date shift is marked — and that is the NKD window, not a corner case.
  // Plain +1/-1 rather than superscript: Courier New and Lucida Console are both in the font
  // picker and neither carries U+207A, which would render as a box.
  const dayShift = diff => diff ? ` <em class="day-shift">${diff > 0 ? '+' : '-'}${Math.abs(diff)}</em>` : '';

  function renderRailClock() {
    if (!$('railClockEt')) return;   // rail not painted yet on first load
    const now = new Date();
    const et = zoneParts(now, ET_ZONE, true);
    const etDay = zoneDayNumber(et);
    const abbrev = new Intl.DateTimeFormat('en-US', { timeZone: ET_ZONE, timeZoneName: 'short' })
      .formatToParts(now).find(part => part.type === 'timeZoneName');
    $('railClockEt').textContent = `ET ${et.hour}:${et.minute}:${et.second} ${abbrev ? abbrev.value : ''}`.trim();
    $('railClockZones').innerHTML = CLOCK_ZONES.map(({ label, zone }) => {
      const parts = zoneParts(now, zone, false);
      return `${label} ${parts.hour}:${parts.minute}${dayShift(zoneDayNumber(parts) - etDay)}`;
    }).join(' · ');
  }
  const rootOf = symbol => {
    const clean = String(symbol || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (clean.startsWith('NKD') || clean.startsWith('MNKD')) return 'MNKD';
    return roots.find(root => clean.startsWith(root)) || clean.replace(/[0-9].*$/, '');
  };
  const contractKey = symbol => String(symbol || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const brokerDirection = position => Number(position) >= 0 ? 'LONG' : 'SHORT';
  const latestSnap = () => {
    const snapshots = state.runner?.payload?.snapshots || [];
    return snapshots.reduce((latest, snap) => {
      if (!snap?.date) return latest;
      return !latest || String(snap.date) > String(latest.date) ? snap : latest;
    }, null);
  };
  const runnerPositions = () => latestSnap()?.open_positions || [];
  const brokerPositions = () => state.broker?.payload?.positions || [];
  const workingOrders = () => state.broker?.payload?.orders || [];
  const brokerUsable = () => !!(state.broker?.connected && state.broker?.freshness === 'fresh');
  const stopOrders = () => workingOrders().filter(order => /^(STP|STOP)/i.test(String(order.type || '')));
  const liveStopStatuses = new Set(['PRESUBMITTED', 'SUBMITTED']);
  const runnerFor = brokerPos => runnerPositions().find(pos =>
    rootOf(pos.inst) === rootOf(brokerPos.inst) && String(pos.direction).toUpperCase() === brokerDirection(brokerPos.position)
  );
  const persistedRunnerFor = pos => (state.runnerPositions?.payload?.positions || []).find(saved => {
    const samePrice = Number.isFinite(Number(pos?.entry_price)) && Number.isFinite(Number(saved?.entry_price))
      && Math.abs(Number(pos.entry_price) - Number(saved.entry_price)) < 1e-8;
    return rootOf(saved.inst) === rootOf(pos?.inst)
      && String(saved.direction || '').toUpperCase() === String(pos?.direction || '').toUpperCase()
      && String(saved.cluster || '') === String(pos?.cluster || '')
      && String(saved.entry_day || '').slice(0, 10) === String(pos?.entry_day || '').slice(0, 10)
      && samePrice
      && String(saved.stop_order_id ?? '') === String(pos?.stop_order_id ?? '');
  });
  const runnerQuantity = pos => {
    for (const value of [pos?.contracts, pos?.qty, pos?.position]) {
      if (value != null && Number.isFinite(Number(value))) return Math.abs(Number(value));
    }
    const persisted = persistedRunnerFor(pos);
    if (persisted?.contracts != null && Number.isFinite(Number(persisted.contracts)) && Number(persisted.contracts) > 0) {
      return Math.abs(Number(persisted.contracts));
    }
    return null;
  };
  const stopsFor = brokerPos => stopOrders().filter(order => contractKey(order.inst) === contractKey(brokerPos.inst));
  const expectedStopAction = brokerPos => Number(brokerPos.position) > 0 ? 'SELL' : 'BUY';
  const stopFieldsKnown = order => order.action != null && order.qty != null && Number.isFinite(Number(order.qty)) && order.status != null && order.status !== '?';
  const validStopsFor = brokerPos => stopsFor(brokerPos).filter(order =>
    stopFieldsKnown(order)
    && String(order.action).toUpperCase() === expectedStopAction(brokerPos)
    && Math.abs(Number(order.qty)) === Math.abs(Number(brokerPos.position))
    && liveStopStatuses.has(String(order.status).toUpperCase())
  );
  const invalidStopsFor = brokerPos => stopsFor(brokerPos).filter(order => stopFieldsKnown(order) && !validStopsFor(brokerPos).includes(order));
  const unknownStopsFor = brokerPos => stopsFor(brokerPos).filter(order => !stopFieldsKnown(order));
  const orphanStops = () => stopOrders().filter(order =>
    !brokerPositions().some(pos => contractKey(pos.inst) === contractKey(order.inst))
  );
  const runnerOnly = () => runnerPositions().filter(pos =>
    !brokerPositions().some(live => rootOf(live.inst) === rootOf(pos.inst) && brokerDirection(live.position) === String(pos.direction).toUpperCase())
  );
  const brokerPositionsMatchNow = () => brokerUsable()
    && runnerOnly().length === 0
    && brokerPositions().every(pos => {
      const runner = runnerFor(pos);
      const qty = runnerQuantity(runner);
      return runner && qty != null && qty === Math.abs(Number(pos.position));
    });

  async function fetchJson(url) {
    const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(6000) });
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
  }

  async function poll() {
    const results = await Promise.allSettled([
      fetchJson('/api/v1/runner-state'),
      fetchJson('/api/v1/broker'),
      fetchJson('/api/v1/schedule-status'),
      fetchJson('/api/v1/open-issues'),
      fetchJson('/api/v1/runner-positions')
    ]);
    if (results[0].status === 'fulfilled') state.runner = results[0].value;
    else state.runner = { ...(state.runner || {}), freshness: 'unknown', error: results[0].reason?.message || 'runner-state request failed' };
    if (results[1].status === 'fulfilled') state.broker = results[1].value;
    else state.broker = { ...(state.broker || {}), connected: false, freshness: 'unknown', error: results[1].reason?.message || 'broker request failed' };
    if (results[2].status === 'fulfilled') state.schedule = results[2].value;
    else state.schedule = { ...(state.schedule || {}), evidence_available: false, evidence: null, incidents: [], unexplained_overdue: [], error: results[2].reason?.message || 'schedule request failed' };
    if (results[3].status === 'fulfilled') state.openIssues = results[3].value;
    else state.openIssues = { ...(state.openIssues || {}), issues: [], error: results[3].reason?.message || 'open-issues request failed' };
    if (results[4].status === 'fulfilled') state.runnerPositions = results[4].value;
    else state.runnerPositions = { ...(state.runnerPositions || {}), payload: null, error: results[4].reason?.message || 'runner-positions request failed' };
    const sessionDay = latestSnap()?.date;
    if (sessionDay) {
      try {
        const [sessionEvents, jobJournal, executionQuality] = await Promise.all([
          fetchJson(`/api/v1/session-events/${encodeURIComponent(sessionDay)}`),
          fetchJson(`/api/v1/job-journal/${encodeURIComponent(sessionDay)}`),
          fetchJson(`/api/v1/execution-quality/${encodeURIComponent(sessionDay)}`)
            .catch(error => ({ source: 'trade_log.jsonl', day: sessionDay, fills: [], exceptions: [], error: error?.message || 'execution-quality request failed' }))
        ]);
        state.sessionEvents = sessionEvents;
        state.jobJournal = jobJournal;
        state.executionQuality = executionQuality;
      } catch (error) {
        state.sessionEvents = { source: 'live_log', day: sessionDay, events: [], error: error?.message || 'session-events request failed' };
        state.jobJournal = { source: 'scheduler_log', day: sessionDay, jobs: [], monitor_events: [], error: error?.message || 'job-journal request failed' };
        state.executionQuality = { source: 'trade_log.jsonl', day: sessionDay, fills: [], exceptions: [], error: error?.message || 'execution-quality request failed' };
      }
    }
    $('fatalBanner').hidden = results.some(result => result.status === 'fulfilled');
    render();
  }

  function setMetric(id, value, numeric) {
    const el = $(id);
    el.textContent = value;
    el.classList.remove('positive', 'negative', 'warning');
    if (numeric != null) el.classList.add(Number(numeric) >= 0 ? 'positive' : 'negative');
  }

  function renderContext(snap) {
    $('sessionDate').textContent = sessionDate(snap?.date);
    const regime = snap?.regime || 'Unknown';
    $('sessionRegime').textContent = regime;
    $('sessionRegime').className = /stress/i.test(regime) ? 'stress' : /unknown/i.test(regime) ? 'unknown' : '';
    const ops = state.runner?.payload?.meta?.operational_status || snap?.operational_status || {};
    const regimeStatus = ops.regime_freshness?.status;
    const regimeDate = ops.regime_freshness?.last_spy_date;
    $('regimeInputDate').textContent = regimeDate
      ? sessionDate(regimeDate).replace(/, \d{4}$/, '')
      : regimeStatus === 'OK' ? 'Current' : 'Unavailable';
    $('regimeInputDate').className = regimeStatus === 'OK' ? 'positive' : 'warning';
    const modelStatus = ops.model_age?.status;
    const modelMonths = ops.model_age?.months_old;
    // Hai dòng phụ dưới Model age / HMM fit đã bỏ khỏi header — chúng lặp lại điều mà
    // giá trị và màu đã nói, và đẩy cả thanh header cao thêm một dòng. Chi tiết không mất:
    // chuyển sang title, hover vẫn đọc được.
    $('modelInputAge').textContent = modelStatus === 'OK' ? 'Current' : `${modelMonths ?? '?'} mo stale`;
    $('modelInputAge').className = modelStatus === 'OK' ? 'positive' : 'warning';
    $('modelInputAge').title = modelStatus === 'OK' ? 'Fit current' : 'Known debt / G2 HARD';
    const fitDiagnostic = [...(state.sessionEvents?.events || [])].reverse()
      .find(event => event.kind === 'hmm_fit_diagnostic');
    $('modelFitStatus').textContent = fitDiagnostic
      ? `${fitDiagnostic.completed_fits}/${fitDiagnostic.attempts} complete` : 'Not observed';
    $('modelFitStatus').className = fitDiagnostic?.completed_fits === fitDiagnostic?.attempts ? 'positive' : 'warning';
    $('modelFitStatus').title = fitDiagnostic
      ? `${fitDiagnostic.non_convergence_count || 0} warnings · no gate failure`
      : 'No retained fit evidence';
    $('modelInputsZone').classList.toggle('watch', regimeStatus !== 'OK' || modelStatus !== 'OK');
    const rf = state.runner?.freshness || 'missing';
    const runnerText = rf === 'fresh' ? `Current · updated ${age(state.runner?.age_seconds)}`
      : rf === 'not_expected_yet' ? `On schedule · next ${etClock(state.runner?.expected_next_at)}`
      : rf === 'late' ? `Late · expected ${etClock(state.runner?.expected_next_at)}`
      : rf === 'missing' ? 'No runner snapshot' : 'Timing cannot be verified';
    $('runnerContext').textContent = runnerText;
    $('runnerContext').className = rf === 'late' || rf === 'missing' ? 'negative' : rf === 'unknown' ? 'warning' : '';
    const connected = state.broker?.connected;
    const usable = brokerUsable();
    $('brokerContext').textContent = state.broker
      ? `${usable ? 'Live' : connected ? 'Stale' : 'Disconnected'} · updated ${age(state.broker.age_seconds)}`
      : 'source unavailable';
    $('brokerContext').className = usable ? 'positive' : connected ? 'warning' : 'negative';
  }

  function renderMetrics(snap) {
    const meta = state.runner?.payload?.meta || {};
    const equity = snap?.equity ?? state.runner?.payload?.meta?.final_equity;
    const unreal = state.broker?.payload?.unrealized_pnl;
    const realized = snap?.decision?.realized_today;
    const drawdown = Number(snap?.drawdown_pct);
    const drawdownDollars = Number(snap?.drawdown_dollars);
    const hardDrawdown = Number(state.runner?.payload?.meta?.hard_dd_pct);
    const gaugePct = Number.isFinite(drawdown) && Number.isFinite(hardDrawdown) && hardDrawdown > 0
      ? Math.min(100, Math.max(0, drawdown / hardDrawdown * 100)) : 0;
    $('metrics').classList.toggle('broker-stale', !brokerUsable());
    $('metrics').classList.toggle('runner-stale', state.runner?.freshness === 'missing' || state.runner?.freshness === 'unknown');
    setMetric('metricEquity', equity == null ? '--' : `$${Number(equity).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`);
    setMetric('metricRealized', money(realized), realized);
    setMetric('metricUnrealized', money(unreal), unreal);
    $('metricDrawdown').textContent = Number.isFinite(drawdown) ? pct(drawdown) : '--';
    $('metricDrawdownAmount').textContent = Number.isFinite(drawdownDollars)
      ? `$${Math.abs(drawdownDollars).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--';
    $('metricDrawdownLimit').textContent = Number.isFinite(hardDrawdown)
      ? `${gaugePct.toFixed(1)}% of ${pct(hardDrawdown)} hard limit` : 'hard limit unavailable';
    $('metricDrawdownFill').style.width = `${gaugePct}%`;
    $('metricDrawdownFill').className = gaugePct >= 100 ? 'bad' : gaugePct >= 66 ? 'watch' : '';
    $('metricDrawdownFill').parentElement.setAttribute('aria-valuenow', gaugePct.toFixed(1));
    $('metricDrawdownFill').parentElement.setAttribute('aria-valuemin', '0');
    $('metricDrawdownFill').parentElement.setAttribute('aria-valuemax', '100');
    $('metricPositions').textContent = state.broker?.payload ? String(brokerPositions().length) : '--';
    $('metricStops').textContent = state.broker?.payload ? String(workingOrders().length) : '--';

    const coveredStops = brokerUsable()
      ? brokerPositions().filter(position => validStopsFor(position).length > 0).length
      : null;
    $('metricStopsCovered').textContent = coveredStops == null ? '--' : `${coveredStops} / ${brokerPositions().length}`;
    const running = snap?.running_metrics || {};
    const performanceValue = (id, value, numeric = null) => {
      const element = $(id);
      element.textContent = value;
      element.classList.remove('positive', 'negative');
      if (numeric != null && Number.isFinite(Number(numeric)) && Number(numeric) !== 0) {
        element.classList.add(Number(numeric) > 0 ? 'positive' : 'negative');
      }
    };
    $('performanceScope').textContent = meta.system_epoch
      ? `since ${sessionDate(meta.system_epoch)}` : '';
    performanceValue('performanceBase', meta.account == null ? '--' : `$${Number(meta.account).toLocaleString('en-US', { maximumFractionDigits: 0 })}`);
    performanceValue('performanceNet', money(meta.net_pnl), meta.net_pnl);
    performanceValue('performanceCalmar', running.calmar == null ? '--' : Number(running.calmar).toFixed(2));
    performanceValue('performanceSharpe', running.sharpe == null ? '--' : Number(running.sharpe).toFixed(2), running.sharpe);
    performanceValue('performanceReturn', running.total_return == null ? '--' : `${Number(running.total_return) >= 0 ? '+' : ''}${pct(running.total_return)}`, running.total_return);
    performanceValue('performanceMaxDd', meta.max_dd_pct == null ? '--' : pct(meta.max_dd_pct), meta.max_dd_pct == null ? null : -Number(meta.max_dd_pct));
  }

  function railItem(label, value, level) {
    return `<div class="status-item ${level}"><span class="status-dot"></span><span class="status-copy"><span class="status-label has-tip" tabindex="0" data-tooltip="${esc(railTips[label] || label)}">${esc(label)}</span><span class="status-value">${esc(value)}</span></span></div>`;
  }

  function runnerFreshnessText(freshness, nextAt) {
    if (freshness === 'fresh') return 'Publishing on time';
    if (freshness === 'not_expected_yet') return `On schedule · next ${etClock(nextAt)}`;
    if (freshness === 'late') return `Late · due ${etClock(nextAt)}`;
    if (freshness === 'missing') return 'No snapshot available';
    return 'Timing unknown';
  }

  function slotLabel(slotId) {
    const match = String(slotId || '').match(/^(NKD_NIGHT|LIVE_DAY)_(\d{2})(\d{2})$/);
    if (!match) return String(slotId || 'No due job').replaceAll('_', ' ');
    return `${match[1] === 'NKD_NIGHT' ? 'NKD' : 'US'} ${match[2]}:${match[3]}`;
  }

  function jobEvidenceText(evidence) {
    if (!evidence) return 'No scheduler evidence';
    const outcome = evidence.state === 'executed' ? 'ran'
      : evidence.state === 'skipped' && evidence.reason === 'mutex' ? 'overlap skipped'
      : evidence.state === 'failed' ? 'failed'
      : evidence.state === 'missing' ? 'not observed' : String(evidence.state || 'unknown').replaceAll('_', ' ');
    return `${slotLabel(evidence.slot_id)} · ${outcome}`;
  }


  function latestObservedJob() {
    return [...(state.jobJournal?.jobs || [])]
      .sort((a, b) => String(b.ended_at || b.started_at).localeCompare(String(a.ended_at || a.started_at)))[0] || null;
  }

  function latestDecisionJob() {
    return [...(state.jobJournal?.jobs || [])]
      .filter(job => /^(NKD_NIGHT_|LIVE_DAY_|MAX_HOLD|PREFLIGHT)/.test(String(job.job_id || '')))
      .sort((a, b) => String(b.ended_at || b.started_at).localeCompare(String(a.ended_at || a.started_at)))[0] || null;
  }

  function pipelineJobTone(job) {
    if (!job) return 'watch';
    if (['failed', 'missed'].includes(job.status)) return 'bad';
    if (job.status === 'completed_with_debt') return 'watch';
    return 'ok';
  }

  function renderScheduleFacts() {
    const schedule = state.schedule;
    const nextScheduled = schedule?.next_scheduled_job;
    const nextDecision = schedule?.next_decision_job;
    const latestScheduled = latestObservedJob();
    const latestDecision = latestDecisionJob();
    // The scheduler's own job id, not a prettier synonym. Whatever this row names, the
    // operator has to be able to grep it straight out of scheduler_MMDD.log — a dashboard
    // vocabulary that exists nowhere else in the system is a translation step under pressure.
    const fact = (label, job, at, tone = 'next') => `<div class="schedule-fact ${tone}">
      <span>${esc(label)}</span><div><b>${esc(job ? job.job_id : 'Not observed')}</b><time>${esc(at ? etClock(at) : '--')}</time></div>
    </div>`;
    $('nowScheduleFacts').innerHTML = [
      fact('Next job', nextScheduled, nextScheduled?.at),
      fact('Next decision', nextDecision, nextDecision?.at),
      fact('Latest job', latestScheduled, latestScheduled?.ended_at || latestScheduled?.started_at, pipelineJobTone(latestScheduled)),
      fact('Latest decision', latestDecision, latestDecision?.ended_at || latestDecision?.started_at, pipelineJobTone(latestDecision)),
    ].join('');
  }

  function renderRail(snap) {
    const stripOps = state.runner?.payload?.meta?.operational_status || snap?.operational_status || {};
    const stripSchedule = state.schedule;
    const stripEvidence = stripSchedule?.evidence;
    const stripBrokerKnown = brokerUsable();
    const stripOrphans = stripBrokerKnown ? orphanStops() : [];
    const stripUnprotected = stripBrokerKnown ? brokerPositions().filter(position => {
      const runner = runnerFor(position);
      return !stopsFor(position).length && runner && !runner.stop_deferred;
    }) : [];
    const stripInvalidStops = stripBrokerKnown
      ? brokerPositions().reduce((count, position) => count + invalidStopsFor(position).length, 0) : 0;
    const stripUnknownStops = stripBrokerKnown
      ? brokerPositions().reduce((count, position) => count + unknownStopsFor(position).length, 0) : 0;
    const stripMatched = stripBrokerKnown ? brokerPositions().filter(runnerFor).length : 0;
    const stripSizeProblem = stripBrokerKnown && brokerPositions().some(position => {
      const runner = runnerFor(position);
      const quantity = runnerQuantity(runner);
      return runner && (quantity == null || quantity !== Math.abs(Number(position.position)));
    });
    const stripFreshness = state.runner?.freshness || 'missing';
    const stripScheduleBad = (stripSchedule?.incidents || []).length > 0
      || (stripSchedule?.unexplained_overdue || []).length > 0
      || stripFreshness === 'late'
      || stripFreshness === 'missing'
      || stripEvidence?.severity === 'incident';
    const stripSafetyCount = stripOrphans.length + stripUnprotected.length + stripInvalidStops + stripUnknownStops;
    const stripReconcileBad = stripBrokerKnown
      && (runnerOnly().length || stripMatched !== brokerPositions().length || stripSizeProblem);
    const stripBreaker = stripOps.breaker?.level || snap?.breaker_level;
    const stripBreakerBad = stripBreaker && stripBreaker !== 'OK';
    const stripUnknown = !stripSchedule?.evidence_available || !stripBrokerKnown;
    const stripLevel = stripScheduleBad || stripSafetyCount || stripReconcileBad || stripBreakerBad
      ? 'bad' : stripUnknown ? 'watch' : 'ok';
    const stripConditions = [];
    if (stripScheduleBad) stripConditions.push('scheduler attention required');
    if (!stripBrokerKnown) stripConditions.push('broker feed cannot be verified');
    if (stripSafetyCount) stripConditions.push(`${stripSafetyCount} protection issue(s)`);
    if (stripReconcileBad) stripConditions.push('position reconcile needs attention');
    if (stripBreakerBad) stripConditions.push(`risk breaker ${stripBreaker}`);
    if (!stripConditions.length && stripUnknown) stripConditions.push('some telemetry is unavailable');
    const stripStatus = stripConditions.length
      ? stripConditions.join(' / ')
      : `systems nominal: feeds live, ${brokerPositions().length ? 'positions protected' : 'no open positions'}`;
    const stripIssueCount = state.openIssues?.issues?.length || 0;
    $('statusRail').innerHTML = `
      <div class="system-conclusion ${stripLevel}">
        <span class="status-dot"></span>
        <b>${esc(stripStatus)}</b>
        <strong>${stripIssueCount} issue${stripIssueCount === 1 ? '' : 's'} open</strong>
      </div>
      <div class="system-facts">
        <span class="rail-clock has-tip tip-bottom" tabindex="0" data-tooltip="Wall-clock time right now, not a data timestamp. ET is the zone every schedule constant in this system is written in; the second line is the same instant elsewhere, marked when that zone is on a different calendar date.">
          <b id="railClockEt">--:--:--</b>
          <span id="railClockZones">--</span>
        </span>
      </div>`;
    // The rail is rebuilt wholesale on every poll, which throws the clock nodes away with it.
    // Repaint immediately or it sits on placeholder dashes until the next one-second tick.
    renderRailClock();

    $('journalSchedule').innerHTML = `
      <span class="fact-scheduler has-tip tip-right ${stripScheduleBad ? 'bad' : stripSchedule?.evidence_available ? 'ok' : 'watch'}" tabindex="0" data-tooltip="ON SCHEDULE means scheduler evidence is available, no due slot is unresolved, and runner state is not late. It does not describe model or trading health."><i class="scheduler-live-dot"></i><small>Scheduler</small><b>${esc(stripScheduleBad ? 'attention' : stripSchedule?.evidence_available ? 'on schedule' : 'unknown')}</b></span>`;
  }

  function renderRailLegacy(snap) {
    const ops = state.runner?.payload?.meta?.operational_status || snap?.operational_status || {};
    const schedule = state.schedule;
    const evidence = schedule?.evidence;
    const brokerKnown = brokerUsable();
    const orphans = brokerKnown ? orphanStops() : [];
    const unprotected = brokerKnown ? brokerPositions().filter(pos => {
      const runner = runnerFor(pos);
      return !stopsFor(pos).length && runner && !runner.stop_deferred;
    }) : [];
    const invalidStops = brokerKnown ? brokerPositions().reduce((count, pos) => count + invalidStopsFor(pos).length, 0) : 0;
    const unknownStops = brokerKnown ? brokerPositions().reduce((count, pos) => count + unknownStopsFor(pos).length, 0) : 0;
    const matched = brokerKnown ? brokerPositions().filter(runnerFor).length : 0;
    const sizeUnknown = brokerKnown ? brokerPositions().filter(pos => runnerFor(pos) && runnerQuantity(runnerFor(pos)) == null).length : 0;
    const sizeMismatch = brokerKnown ? brokerPositions().filter(pos => {
      const qty = runnerQuantity(runnerFor(pos));
      return qty != null && qty !== Math.abs(Number(pos.position));
    }).length : 0;
    const runnerFreshness = state.runner?.freshness || 'missing';
    const runnerLevel = runnerFreshness === 'late' || runnerFreshness === 'missing'
      ? 'bad'
      : runnerFreshness === 'unknown' ? 'watch' : 'ok';
    const protectedCount = brokerKnown ? brokerPositions().filter(pos => {
      const runner = runnerFor(pos);
      return validStopsFor(pos).length > 0 || Boolean(runner?.stop_deferred);
    }).length : 0;
    const regimeDate = ops.regime_freshness?.last_spy_date
      ? sessionDate(ops.regime_freshness.last_spy_date).replace(/, \d{4}$/, '') : null;
    const modelMonths = ops.model_age?.months_old;
    const fitDiagnostic = [...(state.sessionEvents?.events || [])].reverse()
      .find(event => event.kind === 'hmm_fit_diagnostic');
    const groups = [
      ['Pipeline', [
        railItem('State updates', runnerFreshnessText(runnerFreshness, state.runner?.expected_next_at), runnerLevel),
        railItem('Latest job', jobEvidenceText(evidence), evidence?.severity === 'incident' ? 'bad' : evidence?.severity === 'watch' ? 'watch' : 'ok'),
        railItem('IBKR feed', brokerKnown ? `Live · ${age(state.broker?.age_seconds)}` : 'Unavailable', brokerKnown ? 'ok' : 'watch')
      ]],
      ['Position safety', [
        railItem('Stop protection', !brokerKnown ? 'Cannot verify' : orphans.length || unprotected.length || invalidStops || unknownStops ? `${orphans.length + unprotected.length + invalidStops + unknownStops} need attention` : `${protectedCount}/${brokerPositions().length} protected`, !brokerKnown ? 'watch' : orphans.length || unprotected.length || invalidStops ? 'bad' : unknownStops ? 'watch' : 'ok'),
        railItem('Position match', brokerKnown ? `${matched}/${brokerPositions().length} matched${sizeUnknown ? ' · size unknown' : ''}` : 'Cannot verify', !brokerKnown ? 'watch' : runnerOnly().length || matched !== brokerPositions().length || sizeMismatch ? 'bad' : sizeUnknown ? 'watch' : 'ok'),
        railItem('Risk breaker', (ops.breaker?.level || snap?.breaker_level) === 'OK' ? 'Ready · no halt' : `${ops.breaker?.level || snap?.breaker_level || 'Unknown'} · entries blocked`, ops.breaker?.level === 'OK' || snap?.breaker_level === 'OK' ? 'ok' : 'bad')
      ]],
      ['Inputs', [
        railItem('Regime data', ops.regime_freshness?.status === 'OK' ? `Current${regimeDate ? ` · SPY ${regimeDate}` : ''}` : `${ops.regime_freshness?.bday_stale ?? '?'} business days stale`, ops.regime_freshness?.status === 'OK' ? 'ok' : 'watch'),
        railItem('Model health', ops.model_age?.status === 'OK' ? 'Current' : `${modelMonths ?? '?'} months stale · known debt`, ops.model_age?.status === 'OK' ? 'ok' : 'debt'),
        railItem('HMM fit', fitDiagnostic
          ? `${fitDiagnostic.completed_fits}/${fitDiagnostic.attempts} complete · ${fitDiagnostic.non_convergence_count || 0} warnings`
          : 'No retained fit evidence', 'watch')
      ]]
    ];
    $('statusRail').innerHTML = groups.map(([title, items]) => `<section class="status-group"><span class="status-group-title">${esc(title)}</span><div class="status-group-items" style="--status-count:${items.length}">${items.join('')}</div></section>`).join('');
  }

  function renderMonitor(snap) {
    const incidents = [];
    const gaps = [];
    const schedule = state.schedule;
    const openConnectivity = (state.sessionEvents?.events || []).filter(event =>
      event.kind === 'connectivity_outage' && event.status === 'open');
    const openReconcile = (state.sessionEvents?.events || []).filter(event =>
      event.kind === 'broker_reconcile_incident' && event.status === 'open');
    const twsOutageOpen = openConnectivity.some(event =>
      event.service === 'tws' || (event.affected_services || []).includes('tws'));
    const schedulerIncidents = Math.max((schedule?.incidents || []).length, (schedule?.unexplained_overdue || []).length);
    const schedulerHealth = $('schedulerHealth');
    if (schedulerHealth) {
    let schedulerHealthClass = 'ok';
    let schedulerHealthText = schedule?.active_window ? `ACTIVE WINDOW · NEXT ${etClock(schedule?.expected_next_at)}` : `ON SCHEDULE · NEXT ${etClock(schedule?.expected_next_at)}`;
    if (!schedule?.evidence_available) {
      schedulerHealthClass = 'unknown';
      schedulerHealthText = 'EVIDENCE UNKNOWN';
    } else if (schedulerIncidents || schedule?.freshness === 'late') {
      schedulerHealthClass = 'bad';
      schedulerHealthText = `${schedulerIncidents || 1} UNRESOLVED SCHEDULE INCIDENT`;
    }

    openConnectivity.forEach(event => incidents.push({
      key: `broker:connectivity:${(event.affected_services || [event.service]).join(',')}:${event.started_at || event.ts}`,
      status: 'incident', component: 'broker', title: event.title || 'IBKR connectivity unavailable',
      problem: event.problem || event.message,
      impact: event.impact || 'The affected IBKR service may still be unavailable.',
      action: event.action || 'Check IBKR/TWS connectivity and current broker state now.',
      evidence: event.evidence || `IBKR code ${event.down_code || '--'}`
    }));
    if (!brokerPositionsMatchNow()) openReconcile.forEach(event => incidents.push({
      key: `runner:reconcile:${event.started_at || event.ts}`,
      status: 'incident', component: 'runner', title: event.title || 'Broker/runner positions do not reconcile',
      problem: event.problem || event.message,
      impact: event.impact || 'Current broker exposure cannot be inferred safely from runner state alone.',
      action: event.action || 'Reconcile IBKR positions, working stops, and runner persisted positions now.',
      evidence: event.evidence || 'B3 mismatch/orphan with no later match'
    }));
    schedulerHealth.className = `scheduler-health ${schedulerHealthClass}`;
    $('schedulerHealthValue').textContent = schedulerHealthText;
    }

    (schedule?.incidents || []).forEach(item => incidents.push({
      key: `schedule:${item.slot_id}:${item.reason}`, status: 'incident', component: 'scheduler',
      title: `${item.slot_id} ${String(item.state || 'incident').toUpperCase()}`,
      problem: `The expected scheduler slot is unresolved: ${item.reason || item.state}.`,
      impact: 'The intended job or runner-state publication for this slot cannot be confirmed.',
      action: 'Check scheduler health and the latest job evidence; confirm the next expected slot executes.',
      evidence: item.detail || `${item.slot_id} / ${item.reason}`
    }));
    if (state.runner?.freshness === 'late') incidents.push({
      key: 'runner:state-late', status: 'incident', component: 'runner', title: 'Runner state is late',
      problem: 'No fresh runner-state publication explains the latest expected slot.',
      impact: 'Runner intent and decision data on this page may describe an older execution.',
      action: 'Inspect the latest scheduler slot and runner log before relying on runner-derived fields.',
      evidence: (schedule?.unexplained_overdue || []).map(item => item.slot_id).join(', ') || 'Runner freshness classified late'
    });
    if (brokerUsable()) {
      orphanStops().forEach(order => incidents.push({
        key: `broker:orphan:${order.order_id}`, status: 'incident', component: 'broker', title: `${order.inst} orphan stop`,
        problem: `Working ${order.action || ''} STP #${order.order_id ?? '--'} has no matching broker position.`,
        impact: 'If triggered, the order can create an unintended position instead of protecting one.',
        action: 'Verify the order in IBKR and use the approved operational procedure if cancellation is required.',
        evidence: `${order.type || 'STP'} ${order.action || '--'} x${order.qty ?? '--'} / ${order.status || '--'}`
      }));
      brokerPositions().forEach(pos => {
        const runner = runnerFor(pos);
        const invalidStops = invalidStopsFor(pos);
        const validStops = validStopsFor(pos);
        const recordedStopId = runner?.stop_order_id;
        const hasRecordedStopId = runner && Object.prototype.hasOwnProperty.call(runner, 'stop_order_id');
        const stopIdDrift = hasRecordedStopId && !runner.stop_deferred && validStops.length
          && !validStops.some(order => String(order.order_id) === String(recordedStopId));
        if (runner && !runner.stop_deferred && !stopsFor(pos).length) incidents.push({
          key: `broker:unprotected:${pos.inst}`, status: 'incident', component: 'broker', title: `${pos.inst} unprotected`,
          problem: 'The broker position has no working stop and runner intent does not mark protection as deferred.',
          impact: 'The open position is exposed without the expected broker-side protective order.',
          action: 'Reconcile runner intent and IBKR protection immediately using the approved operational workflow.',
          evidence: `${pos.inst} ${brokerDirection(pos.position)} x${Math.abs(Number(pos.position))} / 0 working stops`
        });
        invalidStops.forEach(order => incidents.push({
          key: `broker:invalid-stop:${order.order_id}`, status: 'incident', component: 'broker', title: `${order.inst} invalid stop`,
          problem: `Stop #${order.order_id ?? '--'} does not match the required action, quantity, or live status.`,
          impact: 'The observed order cannot be counted as valid protection for the broker position.',
          action: 'Compare the order with the broker position and follow the approved stop-repair procedure.',
          evidence: `Observed ${order.action || '--'} x${order.qty ?? '--'} / ${order.status || '--'}; expected ${expectedStopAction(pos)} x${Math.abs(Number(pos.position))}`
        }));
        if (stopIdDrift) incidents.push({
          key: `runner:stop-id-drift:${pos.inst}:${recordedStopId ?? 'none'}`, status: 'incident', component: 'runner',
          title: `${pos.inst} stop order ID drift`,
          problem: `Runner state records stop ${recordedStopId == null ? 'ID none' : `#${recordedStopId}`}, but IBKR protection is ${validStops.map(order => `#${order.order_id}`).join(', ')}.`,
          impact: 'The position is protected now, but a later close may cancel a ghost ID and leave the live stop orphaned.',
          action: 'Reconcile the persisted stop ID with the live IBKR order using the approved repair workflow.',
          evidence: `${pos.inst} runner ${recordedStopId == null ? 'ID none' : `#${recordedStopId}`} / IBKR ${validStops.map(order => `#${order.order_id}`).join(', ')}`
        });
        if (!runner) incidents.push({
          key: `broker:only:${pos.inst}`, status: 'incident', component: 'broker', title: `${pos.inst} broker-only position`,
          problem: 'IBKR reports an open position with no matching runner position.',
          impact: 'Runner intent cannot explain or manage the observed broker exposure.',
          action: 'Reconcile the broker position against persisted runner state before taking operational action.',
          evidence: `${pos.inst} ${brokerDirection(pos.position)} x${Math.abs(Number(pos.position))}`
        });
        const expectedQty = runnerQuantity(runner);
        if (runner && expectedQty != null && expectedQty !== Math.abs(Number(pos.position))) incidents.push({
          key: `broker:size:${pos.inst}`, status: 'incident', component: 'broker', title: `${pos.inst} size mismatch`,
          problem: `IBKR holds x${Math.abs(Number(pos.position))}, while runner intent reports x${expectedQty}.`,
          impact: 'Protection and exposure calculations may target the wrong quantity.',
          action: 'Reconcile broker quantity with persisted runner intent and working stop quantity.',
          evidence: `${pos.inst} broker x${Math.abs(Number(pos.position))} / runner x${expectedQty}`
        });
      });
      runnerOnly().forEach(pos => incidents.push({
        key: `runner:only:${pos.inst}`, status: 'incident', component: 'runner', title: `${pos.inst} runner-only position`,
        problem: 'Runner state reports an open position that is absent from IBKR.',
        impact: 'Persisted intent and broker truth disagree; subsequent protection logic may use stale position state.',
        action: 'Reconcile persisted runner position state against the current IBKR account.',
        evidence: `${pos.inst} ${pos.direction} in runner / absent at broker`
      }));
    }

    if (!state.schedule?.evidence_available) gaps.push({ key: 'gap:scheduler', status: 'unknown', component: 'scheduler', title: 'Scheduler evidence unavailable', problem: 'The monitor cannot read enough scheduler evidence to classify expected slots.', impact: 'A missing or failed job cannot be distinguished from absent telemetry.', action: 'Restore scheduler log visibility; do not infer that scheduled jobs succeeded.', evidence: state.schedule?.error || 'schedule evidence unavailable' });
    if (!state.runner || state.runner.freshness === 'missing' || state.runner.freshness === 'unknown') gaps.push({ key: 'gap:runner', status: 'unknown', component: 'runner', title: 'Runner state unknown', problem: 'The latest runner observation cannot be classified as fresh or expected.', impact: 'Runner-derived decisions and intent cannot be treated as current.', action: 'Check runner-state publication and schedule evidence before drawing conclusions.', evidence: state.runner?.error || state.runner?.freshness || 'runner source missing' });
    if (Number(state.runner?.event_history?.malformed_lines || 0) > 0) gaps.push({ key: 'gap:runner-event-log', status: 'unknown', component: 'runner', title: 'Runner event log has an invalid record', problem: 'The append-only JSONL contains one or more malformed records that the monitor cannot parse.', impact: 'Runner event history is incomplete from the malformed record onward; trading state is unaffected.', action: 'Preserve the file for diagnosis and repair or archive the incomplete tail before the next runner slot.', evidence: `${state.runner.event_history.malformed_lines} malformed record(s) / ${state.runner.event_history.error || 'parse failure'}` });
    if (!brokerUsable() && !twsOutageOpen) gaps.push({ key: 'gap:broker', status: 'unknown', component: 'broker', title: 'Broker truth unavailable', problem: 'The read-only IBKR observation is disconnected, stale, or unavailable.', impact: 'Current positions, working stops, and reconciliation cannot be verified.', action: 'Restore the read-only IBKR connection; do not reconstruct broker truth from runner state.', evidence: state.broker?.error || `broker freshness ${state.broker?.freshness || 'unknown'}` });
    if (brokerUsable()) brokerPositions().forEach(pos => {
      if (!runnerFor(pos)) return;
      const runner = runnerFor(pos);
      if (runner.stop_deferred === undefined && !stopsFor(pos).length) gaps.push({ key: `gap:deferred:${pos.inst}`, status: 'unknown', component: 'runner', title: `${pos.inst} stop state unknown`, problem: 'Runner state does not say whether missing protection is deferred or unexpected.', impact: 'The monitor cannot safely classify the position as protected or unprotected.', action: 'Treat protection state as unknown until runner evidence or a broker stop appears.', evidence: `${pos.inst} / no stop / deferred field not emitted` });
      unknownStopsFor(pos).forEach(order => gaps.push({ key: `gap:stop:${order.order_id}`, status: 'unknown', component: 'broker', title: `${order.inst} stop evidence incomplete`, problem: `Broker stop #${order.order_id ?? '--'} is missing action, quantity, or status fields.`, impact: 'The order cannot be validated as position protection.', action: 'Verify the order directly in IBKR before relying on it.', evidence: `${order.inst} #${order.order_id ?? '--'} / ${order.action || '--'} / x${order.qty ?? '--'} / ${order.status || '--'}` }));
      if (runnerQuantity(runner) == null) gaps.push({ key: `gap:size:${pos.inst}`, status: 'unknown', component: 'runner', title: `${pos.inst} runner quantity missing`, problem: 'Runner state does not emit contract quantity for this position.', impact: 'The monitor can reconcile symbol and side, but not position size.', action: 'Keep size reconciliation unknown; do not infer quantity from another field.', evidence: `${pos.inst} broker x${Math.abs(Number(pos.position))} / runner quantity absent` });
    });

    const items = [...incidents, ...gaps];
    if (state.selectedMonitorKey && !items.some(item => item.key === state.selectedMonitorKey)) state.selectedMonitorKey = null;
    if (!state.selectedMonitorKey && items.length && !compactIssueMedia.matches) state.selectedMonitorKey = items[0].key;
    $('nowMonitorLayout').hidden = !items.length;
    $('nowMonitorList').innerHTML = items.length ? items.map(item => {
      const selected = item.key === state.selectedMonitorKey;
      return `<div class="issue-list-item"><button class="issue-list-row ${esc(item.status)} ${selected ? 'selected' : ''}" type="button" role="option" aria-selected="${selected}" aria-expanded="${selected}" data-monitor-key="${esc(item.key)}">
        <span class="issue-badges"><span class="issue-origin ${esc(item.component)}">${esc(item.component)}</span><span class="issue-status">${esc(issueStatus(item.status))}</span></span>
        <span class="issue-list-copy"><b>${esc(item.title)}</b><small>${esc(item.problem)}</small></span>
      </button>${selected ? `<div class="now-mobile-detail ${esc(item.status)}">${monitorDetail(item)}</div>` : ''}</div>`;
    }).join('') : '';
    const selected = items.find(item => item.key === state.selectedMonitorKey);
    $('nowMonitorDetail').innerHTML = selected ? `<article class="issue-detail-panel ${esc(selected.status)}">${monitorDetail(selected, true)}</article>` : '';
    document.querySelectorAll('[data-monitor-key]').forEach(button => button.addEventListener('click', () => {
      state.selectedMonitorKey = compactIssueMedia.matches && state.selectedMonitorKey === button.dataset.monitorKey ? null : button.dataset.monitorKey;
      renderMonitor(latestSnap());
    }));
    const incidentSummary = $('incidentSummary');
    const clear = incidents.length === 0 && gaps.length === 0;
    $('monitorClearIndicator').hidden = !clear;
    incidentSummary.className = `summary incident-summary ${clear ? 'clear' : 'attention'}`;
    incidentSummary.textContent = `${incidents.length} incident / ${gaps.length} telemetry gap`;
  }

  function monitorDetail(item, withHeader = false) {
    return `${withHeader ? `<div class="issue-detail-head"><div><span class="issue-origin ${esc(item.component)}">${esc(item.component)}</span><span class="issue-status">${esc(issueStatus(item.status))}</span><h3>${esc(item.title)}</h3></div></div>` : ''}
      <div class="issue-problem"><span>Problem</span><p>${esc(item.problem)}</p></div>
      <div class="issue-assessment"><div><span>Impact</span><p>${esc(item.impact)}</p></div><div><span>Action</span><p>${esc(item.action)}</p></div></div>
      <div class="issue-evidence"><span>Evidence</span><p>${esc(item.evidence)}</p></div>`;
  }

  function issueStatus(status) {
    return ({ incident: 'OPEN', known_debt: 'KNOWN DEBT', unknown: 'UNKNOWN' })[status] || 'OPEN';
  }

  function renderOpenIssues() {
    const data = state.openIssues;
    const issues = data?.issues || [];
    const coverage = data?.coverage;
    $('openIssuesSource').textContent = coverage
      ? `${issues.length} open / evidence ${coverage.from} to ${coverage.to}`
      : data?.error || 'Evidence coverage unavailable';
    $('openIssuesToggle').textContent = `${issues.length} open issue${issues.length === 1 ? '' : 's'} / show list`;
    if (state.issuesSectionOpen === null) state.issuesSectionOpen = !compactIssueMedia.matches;
    $('openIssuesShell').open = state.issuesSectionOpen;
    if (state.selectedIssueKey && !issues.some(issue => issue.key === state.selectedIssueKey)) state.selectedIssueKey = null;
    if (!state.selectedIssueKey && issues.length && !compactIssueMedia.matches) state.selectedIssueKey = issues[0].key;
    $('openIssueList').innerHTML = issues.length ? issues.map(issue => {
      const selected = issue.key === state.selectedIssueKey;
      return `<div class="issue-list-item">
        <button class="issue-list-row ${esc(issue.status)} ${selected ? 'selected' : ''}" type="button" role="option" aria-selected="${selected}" aria-expanded="${selected}" data-issue-key="${esc(issue.key)}">
          <span class="issue-badges"><span class="issue-origin ${esc(issue.component)}">${esc(issue.component || 'unknown')}</span><span class="issue-status">${esc(issueStatus(issue.status))}</span></span>
          <span class="issue-list-copy"><b>${esc(issue.title)}</b><small>${esc(issue.problem)}</small><em>Last ${esc(localTime(issue.last_seen))}</em></span>
          <span class="issue-count">${esc(issue.occurrences)}x</span>
        </button>
        ${selected ? `<div class="issue-mobile-detail ${esc(issue.status)}">
          <div class="issue-problem"><span>Problem</span><p>${esc(issue.problem)}</p></div>
          <div class="issue-timing"><span>First ${esc(localTime(issue.first_seen))}</span><span>Last ${esc(localTime(issue.last_seen))}</span></div>
          <div class="issue-assessment"><div><span>Impact</span><p>${esc(issue.impact)}</p></div><div><span>Action</span><p>${esc(issue.action)}</p></div></div>
          <div class="issue-evidence"><span>Evidence</span><p>${esc(issue.evidence)}</p><p><b>Closes when:</b> ${esc(issue.resolution_evidence)}</p></div>
        </div>` : ''}
      </div>`;
    }).join('') : '<div class="clear-state"><span class="status-dot"></span><b>Clear</b><span>No unresolved issue found in retained evidence</span></div>';
    const selected = issues.find(issue => issue.key === state.selectedIssueKey);
    $('openIssueDetail').innerHTML = selected ? `
      <article class="issue-detail-panel ${esc(selected.status)}">
        <div class="issue-detail-head"><div><span class="issue-origin ${esc(selected.component)}">${esc(selected.component || 'unknown')}</span><span class="issue-status">${esc(issueStatus(selected.status))}</span><h3>${esc(selected.title)}</h3></div><b>${esc(selected.occurrences)} occurrences</b></div>
        <div class="issue-problem"><span>Problem</span><p>${esc(selected.problem)}</p></div>
        <div class="issue-timing"><span>First ${esc(localTime(selected.first_seen))}</span><span>Last ${esc(localTime(selected.last_seen))}</span></div>
        <div class="issue-assessment"><div><span>Impact</span><p>${esc(selected.impact)}</p></div><div><span>Action</span><p>${esc(selected.action)}</p></div></div>
        <div class="issue-evidence"><span>Evidence</span><p>${esc(selected.evidence)}</p><p><b>Closes when:</b> ${esc(selected.resolution_evidence)}</p></div>
      </article>` : '';
    document.querySelectorAll('.issue-list-row').forEach(button => button.addEventListener('click', () => {
      state.selectedIssueKey = compactIssueMedia.matches && state.selectedIssueKey === button.dataset.issueKey
        ? null : button.dataset.issueKey;
      renderOpenIssues();
    }));
  }

  // Caption under the entry day. Each branch names a different reason the clock reading
  // is absent, because "not emitted" was covering all of them and taught the reader that
  // the field is simply dead. day_only is the honest one: a record exists but was
  // reconstructed from the date after the fact (see entry_time_reader), so there is no
  // fill time to show and midnight must not be presented as one.
  function entryTimeCaption(runner) {
    if (runner?.entry_time) return localTime(runner.entry_time);
    switch (runner?.entry_time_precision) {
      case 'day_only':       return 'fill time not recorded';
      case 'price_mismatch': return 'trade log record does not match';
      case 'no_record':      return 'no trade log record';
      default:               return 'entry time not emitted';
    }
  }

  function renderPositions() {
    const grid = $('positionGrid');
    if (!brokerUsable()) {
      grid.innerHTML = '<div class="empty-state">Broker truth unavailable. Positions are intentionally not reconstructed from runner state.</div>';
      $('positionSource').textContent = state.broker?.payload ? `IBKR snapshot stale / ${age(state.broker.age_seconds)}` : 'IBKR source unknown';
      return;
    }
    const persistedMatches = runnerPositions().filter(pos => runnerQuantity(pos) != null).length;
    $('positionSource').textContent = `${brokerPositions().length} IBKR position(s) / ${persistedMatches} runner qty from persisted state / ${age(state.broker.age_seconds)}`;
    if (!brokerPositions().length) {
      grid.innerHTML = '<div class="empty-state">No broker positions.</div>';
      return;
    }
    grid.innerHTML = brokerPositions().map(pos => {
      const runner = runnerFor(pos);
      const stops = stopsFor(pos);
      const validStops = validStopsFor(pos);
      const liveStop = (validStops[0] || stops[0])?.aux_price;
      const direction = brokerDirection(pos.position);
      const entryPrice = Number(runner?.entry_price);
      const lastPrice = Number(pos.market_price);
      const stopPrice = Number(liveStop ?? runner?.stop_price);
      const knownPrices = [entryPrice, lastPrice, stopPrice].filter(Number.isFinite);
      const low = knownPrices.length ? Math.min(...knownPrices) : 0;
      const high = knownPrices.length ? Math.max(...knownPrices) : 1;
      const priceSpan = Math.max(high - low, Math.abs(entryPrice || lastPrice || 1) * 0.001);
      const paddedLow = low - priceSpan * 0.08;
      const paddedSpan = priceSpan * 1.16;
      const markerAt = value => Number.isFinite(value) ? Math.max(0, Math.min(100, ((value - paddedLow) / paddedSpan) * 100)) : 50;
      const entryAt = markerAt(entryPrice);
      const lastAt = markerAt(lastPrice);
      const stopAt = markerAt(stopPrice);
      const movePct = Number.isFinite(entryPrice) && Number.isFinite(lastPrice) && entryPrice !== 0
        ? ((direction === 'LONG' ? lastPrice - entryPrice : entryPrice - lastPrice) / entryPrice) * 100
        : null;
      const stopPct = Number.isFinite(entryPrice) && Number.isFinite(stopPrice) && entryPrice !== 0
        ? ((direction === 'LONG' ? stopPrice - entryPrice : entryPrice - stopPrice) / entryPrice) * 100
        : null;
      const progressLeft = Math.min(entryAt, lastAt);
      const progressWidth = Math.abs(lastAt - entryAt);
      let protection = { cls: 'unknown', text: 'Unknown' };
      const recordedStopId = runner?.stop_order_id;
      const hasRecordedStopId = runner && Object.prototype.hasOwnProperty.call(runner, 'stop_order_id');
      const stopIdDrift = hasRecordedStopId && !runner.stop_deferred && validStops.length
        && !validStops.some(order => String(order.order_id) === String(recordedStopId));
      if (stopIdDrift) protection = { cls: 'expected', text: 'Protected / ID drift' };
      else if (validStops.length) protection = { cls: 'ok', text: `Protected #${validStops[0].order_id ?? '--'}` };
      else if (runner?.stop_deferred) protection = { cls: 'expected', text: 'Deferred by rule' };
      else if (stops.length) protection = { cls: 'bad', text: 'Invalid stop' };
      else if (runner) protection = { cls: 'bad', text: 'No valid stop' };
      const order = validStops[0] || stops[0];
      return `<article class="position-card">
        <div class="position-card-head">
          <div class="position-identity"><span class="position-symbol">${esc(pos.inst)}</span><span class="position-contract-meta">FUT · <strong class="position-direction ${direction.toLowerCase()}">${direction}</strong> · x${Math.abs(Number(pos.position))} · <strong class="position-cluster">${esc(runner?.cluster || 'runner unmatched')}</strong></span><span class="protection ${protection.cls}">${esc(protection.text)}</span></div>
          <div class="position-live"><span class="position-upl ${Number(pos.unrealized_pnl) >= 0 ? 'positive' : 'negative'}">${money(pos.unrealized_pnl)}</span><span class="position-move">${movePct == null ? 'price move --' : `${movePct >= 0 ? '+' : ''}${movePct.toFixed(2)}% price move`}</span></div>
        </div>
        <div class="price-track">
          <div class="price-track-line"><span class="price-track-progress ${Number(pos.unrealized_pnl) >= 0 ? 'positive' : 'negative'}" style="left:${progressLeft.toFixed(2)}%;width:${progressWidth.toFixed(2)}%"></span><span class="price-marker stop" style="left:${stopAt.toFixed(2)}%"></span><span class="price-marker entry" style="left:${entryAt.toFixed(2)}%"></span><span class="price-marker last" style="left:${lastAt.toFixed(2)}%"></span></div>
          <div class="price-track-labels"><span>stop ${price(liveStop ?? runner?.stop_price)}${runner?.stop_price != null && liveStop != null ? ` · plan ${price(runner.stop_price)}` : ''}${stopPct == null ? '' : ` · ${stopPct >= 0 ? '+' : ''}${stopPct.toFixed(2)}%`}</span><span>entry ${price(runner?.entry_price)}</span><span>last ${price(pos.market_price)}</span></div>
        </div>
        <div class="position-facts">
          <div class="fact-opened"><span class="has-tip" tabindex="0" data-tooltip="Entry day from runner state. The fill time is recovered from the runner's own trade log, matched on instrument, cluster, entry day and fill price. IBKR cannot supply it: reqPositions carries no timestamp and reqExecutions serves the current day only.">Opened</span><b>${esc(runner?.entry_day || '--')}</b><small>${esc(entryTimeCaption(runner))}</small></div>
          <div class="fact-held"><span class="has-tip" tabindex="0" data-tooltip="Trading-day holding age recorded by the runner.">Held</span><b>${runner?.days_held ?? '--'}d</b></div>
          <div class="fact-risk"><span class="has-tip" tabindex="0" data-tooltip="Risk allocation recorded by the runner. This is not current profit or market value.">Risk budget</span><b>${dollars(runner?.risk_sized)}</b></div>
          <div class="fact-stop ${protection.cls}"><span class="has-tip tip-right" tabindex="0" data-tooltip="Observed IBKR stop type, action, quantity, order ID, status, and time in force.">Stop order</span><b>${order ? `${esc(order.type || '--')} ${esc(order.action || '--')} x${esc(order.qty ?? '--')}` : '--'}</b><small>${order ? `#${esc(order.order_id ?? '--')} · ${esc(order.status || '--')} · ${esc(order.tif || 'TIF not emitted')}` : 'No broker stop observed'}</small></div>
        </div>
      </article>`;
    }).join('');
  }

  function renderOrders() {
    $('ordersSource').textContent = state.broker?.payload ? `${workingOrders().length} working / ${age(state.broker.age_seconds)}` : 'IBKR source unknown';
    $('ordersBody').innerHTML = workingOrders().length ? workingOrders().map(order => {
      const action = String(order.action || '').toUpperCase();
      const status = String(order.status || '').toUpperCase();
      const statusClass = liveStopStatuses.has(status) ? 'order-live' : /CANCEL|INACTIVE/i.test(status) ? 'order-dead' : 'order-watch';
      return `<tr>
        <td class="order-contract">${esc(order.inst)}</td>
        <td class="order-type">${esc(order.type)}</td>
        <td class="order-action ${action === 'BUY' ? 'buy' : action === 'SELL' ? 'sell' : ''}">${esc(order.action)}</td>
        <td class="num order-qty">${esc(order.qty ?? '--')}</td>
        <td class="num order-stop">${price(order.aux_price)}</td>
        <td class="order-status ${statusClass}">${esc(order.status)}</td>
        <td class="num order-id">#${esc(order.order_id ?? '--')}</td>
      </tr>`;
    }).join('') : '<tr><td class="order-empty" colspan="7">No working orders observed.</td></tr>';
  }

  function mapCount(value) {
    return Object.values(value || {}).reduce((total, count) => total + Number(count || 0), 0);
  }

  function exitType(reason, fallback = null) {
    if (!reason && fallback === 'SIGNAL') return { label: 'EXIT: SIGNAL', unknown: false };
    if (!reason) return { label: 'EXIT: NOT EMITTED', unknown: true };
    const labels = {
      CHANDELIER: 'CHANDELIER', MAX_HOLD: 'MAX HOLD', GAP: 'GAP', STRESS_MID: 'STRESS MID',
      STOP: 'STOP', TARGET: 'TARGET', EOD: 'EOD'
    };
    const key = String(reason).toUpperCase();
    return { label: `EXIT: ${labels[key] || key}`, unknown: false };
  }

  function decisionRow({ symbol, direction, value, valueClass = '', detail, kind = '', tag = null }) {
    const side = String(direction || '').toUpperCase();
    return `<article class="decision-row ${esc(kind)}"><div class="decision-row-main"><span>${esc(symbol || '--')}</span>${side ? `<span class="side ${side.toLowerCase()}">${esc(side)}</span>` : ''}${tag ? `<span class="decision-tag ${tag.unknown ? 'unknown' : ''}">${esc(tag.label)}</span>` : ''}<span class="decision-value ${esc(valueClass)}">${esc(value || '')}</span></div><div class="decision-row-detail">${esc(detail || '--')}</div></article>`;
  }

  function renderDecisions(snap) {
    const decision = snap?.decision;
    if (!decision) {
      $('decisionSource').textContent = 'Decision unavailable';
      $('decisionSummary').innerHTML = '<div><span>Evidence</span><b class="warning">Unknown</b></div>';
      ['decisionEntries', 'decisionCloses', 'decisionRejected'].forEach(id => { $(id).innerHTML = '<div class="decision-empty">No decision evidence emitted.</div>'; });
      ['decisionEntryCount', 'decisionCloseCount', 'decisionRejectedCount'].forEach(id => { $(id).textContent = '--'; });
      $('executionExceptions').hidden = true;
      $('executionExceptions').innerHTML = '';
      return;
    }

    const entries = (decision.entries || []).filter(entry => !entry.is_same_day);
    const sameDayCloses = (decision.entries || []).filter(entry => entry.is_same_day);
    const exits = decision.exits || [];
    const rejected = decision.rejected_detail || [];
    const halted = Number(decision.halted_today || 0);
    const takenCount = mapCount(decision.taken_today);
    const rejectedCount = mapCount(decision.rejected_today);

    $('decisionSource').textContent = `${snap.date} / runner ${localTime(state.runner?.observed_at)}`;
    $('decisionSummary').innerHTML = [
      ['Regime', snap.regime || 'Unknown', ''],
      ['Realized', tradeMoney(decision.realized_today), Number(decision.realized_today || 0) >= 0 ? 'positive' : 'negative'],
      ['Taken', takenCount, ''],
      ['Rejected', rejectedCount, rejectedCount ? 'warning' : ''],
      ['Halted', halted, halted ? 'negative' : '']
    ].map(([label, value, cls]) => `<div><span>${esc(label)}</span><b class="${cls}">${esc(value)}</b></div>`).join('');

    $('decisionEntryCount').textContent = String(entries.length);
    $('decisionEntries').innerHTML = entries.length ? entries.map(entry => decisionRow({
      symbol: entry.inst,
      direction: entry.direction,
      value: entry.entry_price == null ? '' : `@ ${price(entry.entry_price)}`,
      detail: [entry.cluster, entry.risk_sized == null ? '' : `risk ${dollars(entry.risk_sized)}`].filter(Boolean).join(' / ')
    })).join('') : '<div class="decision-empty">No open entries in this decision.</div>';

    const closeRows = [
      ...exits.map(exit => ({
        symbol: exit.inst,
        direction: exit.direction,
        tag: exitType(exit.exit_reason, 'SIGNAL'),
        value: tradeMoney(exit.pnl),
        valueClass: Number(exit.pnl || 0) >= 0 ? 'positive' : 'negative',
        detail: [exit.cluster, exit.entry_day ? `from ${exit.entry_day}` : 'entry date not emitted'].filter(Boolean).join(' / ')
      })),
      ...sameDayCloses.map(close => ({
        symbol: close.inst,
        direction: close.direction,
        tag: exitType(close.exit_reason),
        value: tradeMoney(close.pnl_sized),
        valueClass: Number(close.pnl_sized || 0) >= 0 ? 'positive' : 'negative',
        detail: [close.cluster, 'same-day close'].filter(Boolean).join(' / ')
      }))
    ];
    $('decisionCloseCount').textContent = String(closeRows.length);
    $('decisionCloses').innerHTML = closeRows.length ? closeRows.map(decisionRow).join('') : '<div class="decision-empty">No closes in this decision.</div>';

    const rejectedRows = rejected.map(item => ({
      symbol: item.inst,
      direction: item.direction,
      value: item.risk_sized == null ? '' : dollars(item.risk_sized),
      valueClass: 'warning',
      detail: [item.cluster, item.reason].filter(Boolean).join(' / '),
      kind: item.reason === 'breaker_halt' ? 'halted' : 'rejected'
    }));
    if (halted) rejectedRows.push({ symbol: 'ENTRY GUARD', value: `${halted} halted`, valueClass: 'negative', detail: 'Circuit breaker prevented entry signals.', kind: 'halted' });
    $('decisionRejectedCount').textContent = String(rejectedRows.length);
    $('decisionRejected').innerHTML = rejectedRows.length ? rejectedRows.map(decisionRow).join('') : '<div class="decision-empty">No rejected or halted entries.</div>';
    const execution = state.executionQuality;
    const exceptions = execution?.day === snap?.date ? execution.exceptions || [] : [];
    const executionBox = $('executionExceptions');
    executionBox.hidden = exceptions.length === 0;
    executionBox.innerHTML = exceptions.length ? `<div class="execution-exception-head"><span>Execution exceptions</span><b>${exceptions.length}</b></div>${exceptions.map(fill => {
      const ticks = fill.signed_slippage_ticks == null ? 'not evaluable' : `${Number(fill.signed_slippage_ticks).toFixed(2)} ticks adverse`;
      return `<div class="execution-exception-row"><strong>${esc(fill.inst)} ${esc(fill.type)}</strong><span>${esc(ticks)}</span><p>${esc((fill.exception_reasons || []).join(' / '))}</p></div>`;
    }).join('')}` : '';
  }

  function easternDate(iso) {
    if (!iso) return null;
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(parsed).reduce((out, part) => ({ ...out, [part.type]: part.value }), {});
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function decisionTime(value, day) {
    return value ? localTime(value) : `14:05 ET`;
  }

  function journalRows(snap) {
    const day = snap?.date;
    if (!day) return [];
    const rows = [];
    const decision = snap.decision || {};
    const exitsByInst = new Map((decision.exits || []).map(exit => [rootOf(exit.inst), exit]));
    const operational = state.sessionEvents?.day === day ? state.sessionEvents.events || [] : [];
    const loggedExitSymbols = new Set();
    operational.forEach(event => {
      const exit = exitsByInst.get(rootOf(event.inst));
      let message = event.message || '';
      if (event.kind === 'market_close_filled') {
        loggedExitSymbols.add(rootOf(event.inst));
        if (exit) message = `${message} / ${tradeMoney(exit.pnl)} / ${exitType(exit.exit_reason, 'SIGNAL').label}`;
      }
      const lifecycle = ['connectivity_outage', 'broker_reconcile_incident', 'stop_repaired', 'stop_id_drift', 'stop_naked', 'hmm_fit_diagnostic'].includes(event.kind);
      const reconciledNow = event.kind === 'broker_reconcile_incident'
        && event.status === 'open' && brokerPositionsMatchNow();
      const eventStatus = reconciledNow ? 'recovered' : lifecycle ? event.status || 'open' : 'info';
      rows.push({
        key: `operational:${event.kind}:${event.ts}:${event.sequence || 0}`,
        sortKey: event.ts || '', sequence: Number(event.sequence || 0), level: String(event.level || 'INFO').toLowerCase(),
        tone: event.kind === 'hmm_fit_diagnostic' ? 'deferred'
          : lifecycle ? (eventStatus === 'recovered' ? 'success' : 'incident')
          : event.kind === 'stop_deferred' ? 'deferred'
          : event.kind === 'stop_armed' || event.kind === 'stop_armed_after_deferral' || event.kind === 'market_close_filled' || event.kind === 'stop_filled' ? 'success'
          : event.kind === 'stop_cancelled_after_close' ? 'cleanup'
          : event.kind === 'market_close_submitted' ? 'action'
          : 'system',
        category: event.kind === 'connectivity_outage' ? 'IBKR / CONNECTIVITY'
          : event.kind === 'broker_reconcile_incident' ? 'BROKER / RECONCILE'
          : `${event.category || 'LOG'} / ${String(event.kind || 'EVENT').replaceAll('_', ' ')}`,
        time: localTime(event.ts), message, status: eventStatus,
        component: lifecycle ? (event.component || 'runner') : String(event.category || 'runner').toLowerCase(),
        title: reconciledNow ? 'Broker/runner position mismatch recovered' : event.title,
        incurredAt: event.started_at || event.incurred_at,
        recoveredAt: reconciledNow ? state.broker?.observed_at : event.recovered_at,
        problem: event.problem, impact: event.impact,
        action: reconciledNow ? 'No immediate action. Review if the mismatch recurs.' : event.action,
        evidence: event.evidence,
        resolution: reconciledNow
          ? `Recovered by current read-only IBKR reconciliation at ${localTime(state.broker?.observed_at)}.`
          : event.resolution
      });
    });
    const monitorEvents = state.jobJournal?.monitor_events || [];
    const visibleStalls = new Set(monitorEvents.filter(event => event.kind === 'scheduler_stalled').map(event => event.ts));
    monitorEvents.forEach(event => {
      if (event.kind === 'scheduler_recovered') {
        if (visibleStalls.has(event.stalled_at)) return;
        rows.push({
          key: `monitor:scheduler_recovered:${event.ts}`, sortKey: event.ts || '', sequence: 0,
          level: 'info', tone: 'success', category: 'STALL RECOVERY', time: localTime(event.ts),
          incurredAt: event.stalled_at || event.ts, recoveredAt: event.ts, component: 'scheduler', status: 'recovered',
          title: 'Scheduler heartbeat recovered', message: 'Heartbeat resumed after a previously observed scheduler stall.',
          problem: 'The scheduler heartbeat had stopped advancing.', impact: 'The scheduler is responsive again; any separately confirmed missed slots remain historical facts.',
          action: 'No immediate action. Review Windows sleep history if stalls recur.', evidence: event.message || 'Scheduler heartbeat resumed',
          resolution: `Recovered: heartbeat reported alive at ${localTime(event.ts)}.`
        });
        return;
      }
      if (event.kind !== 'scheduler_stalled') {
        rows.push({ key: `monitor:${event.kind}:${event.ts}`, sortKey: event.ts || '', sequence: 0,
          level: String(event.level || 'INFO').toLowerCase(),
          tone: event.level === 'critical' ? 'incident' : event.level === 'warn' ? 'deferred'
            : /completed|passed/.test(event.kind) ? 'success' : 'system',
          category: event.category ? `${event.category} / ${eventLabel(event.kind)}` : `MONITOR / ${eventLabel(event.kind)}`,
          time: localTime(event.ts), message: event.message || '',
          status: event.level === 'critical' ? 'open' : 'info', component: event.component || 'scheduler' });
        return;
      }
      const at = new Date(event.ts).getTime();
      const stallSeconds = Number(String(event.message || '').match(/STALLED\s+(\d+)s/i)?.[1] || 0);
      const heartbeatRecovery = monitorEvents.find(candidate => candidate.kind === 'scheduler_recovered' && candidate.stalled_at === event.ts);
      const later = (state.jobJournal?.jobs || []).find(job =>
        new Date(job.ended_at || job.started_at).getTime() > at && ['completed', 'completed_with_debt'].includes(job.status));
      const missed = (state.jobJournal?.jobs || []).filter(job => job.status === 'missed'
        && new Date(job.started_at).getTime() >= at - stallSeconds * 1000
        && new Date(job.started_at).getTime() <= at);
      const recovered = Boolean(heartbeatRecovery || later);
      const recoveredAt = heartbeatRecovery?.ts || later?.ended_at || null;
      rows.push({
        key: `monitor:scheduler_stalled:${event.ts}`, sortKey: event.ts || '', sequence: 0,
        level: recovered ? 'warn' : 'critical', tone: recovered ? 'cleanup' : 'incident',
        category: 'STALL', time: localTime(event.ts), incurredAt: event.ts, recoveredAt, component: 'scheduler',
        status: recovered ? 'recovered' : 'open', title: `Scheduler heartbeat stalled ${stallSeconds}s`,
        message: recovered ? `Heartbeat stalled ${stallSeconds}s; scheduler later resumed.` : `Heartbeat stalled ${stallSeconds}s with no later successful job evidence.`,
        problem: `The scheduler heartbeat stopped advancing for ${stallSeconds}s, consistent with the machine sleeping or pausing its wait timer.`,
        impact: missed.length ? `Confirmed missed slot(s): ${missed.map(job => job.job_id).join(', ')}.` : 'No missed slot is confirmed inside this stall interval from retained evidence.',
        action: recovered ? 'No immediate action. Check Windows sleep history and power settings if another stall occurs.' : 'Check scheduler process health and Windows sleep state now.',
        evidence: event.message || '', resolution: heartbeatRecovery
          ? `Recovered: heartbeat reported alive at ${localTime(heartbeatRecovery.ts)}.`
          : later ? `Recovered: ${later.job_id} later completed at ${localTime(later.ended_at)}.` : 'Open: no later recovery evidence observed.'
      });
    });
    (state.jobJournal?.jobs || []).filter(job => ['missed', 'failed'].includes(job.status)).forEach(job => {
      const diagnostics = (job.diagnostics || []).filter(message => !String(message).includes('G2 HARD'));
      const runnerError = diagnostics[diagnostics.length - 1];
      const recovered = job.lifecycle_status === 'recovered' || /Publication resumed at/i.test(job.impact || '');
      const recoveryJob = recovered ? (state.jobJournal?.jobs || []).find(candidate =>
        String(candidate.started_at) > String(job.ended_at || job.started_at)
        && candidate.job_type === job.job_type
        && ['completed', 'completed_with_debt'].includes(candidate.status)
        && !(candidate.diagnostics || []).some(message => !String(message).includes('G2 HARD'))) : null;
      const component = runnerError ? 'runner' : 'scheduler';
      const isDumpState = /dump_state|live_state_data/i.test(runnerError || '');
      const title = isDumpState ? 'Runner-state publication failed'
        : job.status === 'missed' ? `${job.job_id} slot missed` : `${job.job_id} failed`;
      const problem = isDumpState
        ? 'Windows denied the atomic replacement of live_state_data.js for this runner slot.'
        : job.status === 'missed'
          ? `The scheduled ${job.job_type.replaceAll('_', ' ')} job did not run: ${job.reason}.`
          : `The job emitted an unresolved error: ${runnerError || job.reason || 'no detail emitted'}.`;
      rows.push({
        key: `job:${job.id}`, sortKey: job.ended_at || job.started_at || '', sequence: 0,
        level: recovered ? 'warn' : 'critical', tone: recovered ? 'cleanup' : 'incident',
        category: isDumpState ? 'STATE PUBLISH' : job.status === 'missed' ? 'MISSED SLOT' : 'JOB FAILURE',
        time: localTime(job.started_at), incurredAt: job.started_at, recoveredAt: job.recovered_at || recoveryJob?.ended_at || null,
        component, status: recovered ? 'recovered' : 'open', title,
        message: problem, problem, impact: job.impact, action: job.action,
        evidence: runnerError || job.reason || 'No detailed evidence emitted',
        resolution: recovered ? job.impact.split('. ').slice(-1)[0] : 'Open: no positive resolution evidence observed.'
      });
    });
    const loggedRunnerEvents = state.runner?.event_history?.events || [];
    const events = loggedRunnerEvents.length ? loggedRunnerEvents : state.runner?.payload?.meta?.events || [];
    const sessionRunnerEvents = events.filter(event => easternDate(event.ts) === day)
      .filter(event => !/^(Runner started:|Day started:)/.test(String(event.message || '')))
    const latestG2 = [...sessionRunnerEvents].reverse().find(event => /G2: model age/i.test(event.message || ''));
    sessionRunnerEvents.filter(event => !/G2: model age/i.test(event.message || '') || event === latestG2)
      .forEach(event => {
      const isG2 = /G2: model age/i.test(event.message || '');
      const debt = isG2 ? (state.openIssues?.issues || []).find(issue => issue.key === 'known_debt:model_age') : null;
      rows.push({
        key: `runner:${event.category}:${event.ts}`, sortKey: event.ts || '',
        level: isG2 ? 'warn' : String(event.level || 'INFO').toLowerCase(),
        tone: isG2 ? 'cleanup' : ['CRITICAL', 'ALERT'].includes(String(event.level || '').toUpperCase()) ? 'incident'
          : String(event.level || '').toUpperCase() === 'WARN' ? 'deferred'
          : String(event.category || '').toUpperCase() === 'STATE' ? 'system' : 'action',
        category: isG2 ? 'MODEL AGE' : `${event.level || 'INFO'} / ${event.category || 'EVENT'}`,
        time: localTime(event.ts), incurredAt: isG2 ? event.ts : null, component: 'runner', status: isG2 ? 'known_debt' : 'info',
        title: isG2 ? 'Model age exceeds hard limit' : null,
        message: isG2 ? (debt?.problem || event.message) : event.message || '',
        problem: isG2 ? (debt?.problem || event.message) : null,
        impact: isG2 ? debt?.impact : null, action: isG2 ? debt?.action : null,
        evidence: isG2 ? (debt?.evidence || event.message) : null,
        resolution: isG2 ? `Open known debt. Closes when: ${debt?.resolution_evidence || 'runner reports model age OK.'}` : null
      });
    });

    (decision.entries || []).forEach(entry => rows.push({
      key: `decision:entry:${entry.inst}:${entry.entry_time || day}`,
      sortKey: entry.entry_time || `${day}T14:05:00`,
      level: entry.is_same_day ? 'warn' : 'info',
      tone: entry.is_same_day ? 'deferred' : 'success',
      category: 'TRADE / ENTRY',
      time: decisionTime(entry.entry_time, day),
      message: [`Entered ${entry.inst || '--'} ${entry.direction || ''}`.trim(), entry.cluster, entry.risk_sized == null ? '' : `risk ${dollars(entry.risk_sized)}`].filter(Boolean).join(' / ')
    }));
    (decision.exits || []).filter(exit => !loggedExitSymbols.has(rootOf(exit.inst))).forEach(exit => rows.push({
      key: `decision:exit:${exit.inst}:${exit.exit_time || day}`,
      sortKey: exit.exit_time || `${day}T14:05:00`,
      level: Number(exit.pnl || 0) < 0 ? 'warn' : 'info',
      tone: 'success',
      category: 'TRADE / EXIT',
      time: decisionTime(exit.exit_time, day),
      message: [`Exited ${exit.inst || '--'} ${exit.direction || ''}`.trim(), tradeMoney(exit.pnl), exitType(exit.exit_reason, 'SIGNAL').label].filter(Boolean).join(' / ')
    }));
    (decision.rejected_detail || []).forEach(rejected => rows.push({
      key: `decision:rejected:${rejected.inst}:${rejected.cluster}:${rejected.reason}`,
      sortKey: `${day}T14:05:00`,
      level: 'warn',
      tone: 'deferred',
      category: 'SIGNAL / REJECTED',
      time: '14:05 ET',
      message: [`Rejected ${rejected.inst || '--'} ${rejected.direction || ''}`.trim(), rejected.cluster, rejected.reason].filter(Boolean).join(' / ')
    }));
    if (Number(decision.halted_today || 0) > 0) rows.push({
      key: `decision:halted:${day}`,
      sortKey: `${day}T14:05:00`,
      level: 'alert',
      tone: 'incident',
      category: 'GUARD / HALTED',
      time: '14:05 ET',
      message: `${decision.halted_today} entry signal(s) halted by guard`
    });
    return rows.sort((a, b) => String(b.sortKey).localeCompare(String(a.sortKey)) || Number(b.sequence || 0) - Number(a.sequence || 0));
  }

  function jobTone(status) {
    return ({ failed: 'incident', missed: 'incident', skipped: 'deferred', running: 'action', completed_with_debt: 'cleanup', completed: 'success' })[status] || 'system';
  }

  function jobStatus(status) {
    return ({ failed: 'FAILED', missed: 'MISSED', skipped: 'SKIPPED', running: 'RUNNING', completed_with_debt: 'DONE + DEBT', completed: 'COMPLETED' })[status] || 'UNKNOWN';
  }

  function duration(seconds) {
    if (seconds == null) return '--';
    const mins = Math.floor(Number(seconds) / 60);
    const secs = Number(seconds) % 60;
    return mins ? `${mins}m ${secs}s` : `${secs}s`;
  }

  function eventLabel(kind) {
    return String(kind || 'event').replaceAll('_', ' ').toUpperCase();
  }

  function eventStatus(status) {
    return ({ open: 'OPEN', recovered: 'RECOVERED', known_debt: 'KNOWN DEBT', diagnostic: 'DIAGNOSTIC', info: 'INFO' })[status] || 'INFO';
  }

  function eventTone(kind) {
    if (kind === 'stop_deferred') return 'deferred';
    if (['stop_armed', 'market_close_filled', 'stop_filled', 'preflight_ibkr_completed', 'preflight_spy_completed', 'preflight_passed'].includes(kind)) return 'success';
    if (kind === 'preflight_failed' || /preflight_.*_failed/.test(kind)) return 'incident';
    if (kind === 'stop_cancelled_after_close') return 'cleanup';
    return 'action';
  }

  function jobSummary(job) {
    const counts = job.event_counts || {};
    const parts = [];
    if (counts.market_close_filled) parts.push(`${counts.market_close_filled} exit fill`);
    if (counts.stop_filled) parts.push(`${counts.stop_filled} stop fill`);
    if (counts.stop_armed) parts.push(`${counts.stop_armed} stop armed`);
    if (counts.stop_repaired) parts.push(`${counts.stop_repaired} stop repaired`);
    if (counts.stop_armed_after_deferral) parts.push(`${counts.stop_armed_after_deferral} stop armed after deferral`);
    if (counts.stop_deferred) parts.push(`${counts.stop_deferred} deferred`);
    if (counts.market_close_submitted) parts.push(`${counts.market_close_submitted} close submitted`);
    if (counts.preflight_passed) parts.push('input gate passed');
    if (job.diagnostics?.length) parts.push(`${job.diagnostics.length} diagnostic`);
    return parts.join(' · ') || (job.status === 'completed' ? 'No operational changes' : job.reason || 'No detail emitted');
  }

  function journalJobs() {
    return [...(state.jobJournal?.jobs || [])]
      .sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  }

  function jobPresentation(job) {
    const diagnostics = job.diagnostics || [];
    const nonG2 = diagnostics.filter(message => !String(message).includes('G2 HARD'));
    const g2Only = diagnostics.length > 0 && nonG2.length === 0;
    const recovered = job.lifecycle_status === 'recovered' || /Publication resumed at/i.test(job.impact || '');
    const dumpState = nonG2.find(message => /dump_state|live_state_data/i.test(message));
    const component = job.status === 'missed' || job.status === 'skipped' || ['stop_repair', 'preflight', 'session_report', 'other'].includes(job.job_type) ? 'scheduler' : 'runner';
    let status = job.status;
    let problem;
    let resolution;
    if (recovered) {
      status = 'recovered';
      problem = 'Windows denied the runner-state publication for this slot.';
      resolution = job.impact.split('. ').slice(-1)[0];
    } else if (g2Only || job.status === 'completed_with_debt') {
      status = 'known_debt';
      problem = 'The runner completed, but the HMM model-age guard remains HARD stale.';
      resolution = 'Open known debt: closes when a later runner observation reports model age OK.';
    } else if (job.status === 'missed') {
      status = 'missed';
      problem = `The scheduled ${job.job_type.replaceAll('_', ' ')} execution did not run: ${job.reason}.`;
      resolution = 'The slot remains missed; scheduler recovery does not recreate this execution.';
    } else if (job.status === 'failed') {
      status = 'open';
      problem = job.job_type === 'preflight'
        ? `The input gate failed: ${nonG2[0] || job.reason || 'no detail emitted'}.`
        : dumpState ? 'The runner could not publish live_state_data.js.' : `The execution failed: ${nonG2[0] || job.reason || 'no detail emitted'}.`;
      resolution = 'Open: no positive recovery evidence is attached to this execution.';
    } else if (job.status === 'skipped') {
      problem = job.reason === 'mutex' ? 'The slot was skipped because the previous execution still held the mutex.' : `The scheduler skipped this slot: ${job.reason || 'reason not emitted'}.`;
      resolution = job.reason === 'mutex' ? 'Expected skip; the next scheduled slot carries execution forward.' : 'Review the next expected scheduler slot.';
    } else if (job.status === 'running') {
      problem = 'The execution has started and completion evidence has not arrived yet.';
      resolution = 'Waiting for completion evidence.';
    } else {
      const summary = jobSummary(job);
      problem = summary === 'No operational changes' ? 'The execution completed without trade or protection changes.' : `The execution completed: ${summary}.`;
      resolution = `Completed at ${localTime(job.ended_at)}.`;
    }
    const statusLabel = ({ recovered: 'RECOVERED', known_debt: 'KNOWN DEBT', missed: 'MISSED', open: 'OPEN', completed: 'COMPLETED', skipped: 'SKIPPED', running: 'RUNNING' })[status] || jobStatus(job.status);
    return {
      component, status, statusLabel, problem, resolution,
      impact: job.impact || (job.status === 'completed' ? 'No operational failure is present in scheduler evidence.' : 'Impact not classified from available evidence.'),
      action: job.action || (job.status === 'completed' ? 'No action.' : 'Review the execution evidence.'),
      evidence: nonG2[nonG2.length - 1] || diagnostics[diagnostics.length - 1] || job.reason || jobSummary(job)
    };
  }

  function renderJobDetails(job, snap, presentation) {
    const exits = new Map((snap?.decision?.exits || []).map(exit => [rootOf(exit.inst), exit]));
    const evidence = (job.events || []).map(event => {
      let message = event.message || '';
      const exit = exits.get(rootOf(event.inst));
      if (event.kind === 'market_close_filled' && exit) message += ` / ${tradeMoney(exit.pnl)} / ${exitType(exit.exit_reason, 'SIGNAL').label}`;
      return `<div class="job-evidence tone-${esc(eventTone(event.kind))}"><time>${esc(localTime(event.ts))}</time><div><b>${esc(eventLabel(event.kind))}</b><p>${esc(message)}</p></div></div>`;
    }).join('');
    const diagnostics = (job.diagnostics || []).map(message => {
      const knownDebt = String(message).includes('G2 HARD');
      return `<div class="job-diagnostic ${knownDebt ? 'known-debt' : 'incident-diagnostic'}"><b>${knownDebt ? 'KNOWN DEBT' : 'ERROR EVIDENCE'}</b><p>${esc(message)}</p></div>`;
    }).join('');
    return `<div class="job-detail">
      <dl><div><dt>Started</dt><dd>${esc(localTime(job.started_at))}</dd></div><div><dt>Completed</dt><dd>${esc(localTime(job.ended_at))}</dd></div><div><dt>Duration</dt><dd>${esc(duration(job.duration_seconds))}</dd></div><div><dt>Outcome</dt><dd>${esc(presentation.statusLabel)}</dd></div></dl>
      <div class="issue-problem"><span>Problem</span><p>${esc(presentation.problem)}</p></div>
      <div class="job-assessment"><div class="job-impact"><b>IMPACT</b><p>${esc(presentation.impact)}</p></div><div class="job-action"><b>ACTION</b><p>${esc(presentation.action)}</p></div></div>
      <div class="job-evidence-list">${evidence || '<p class="job-empty">No trade or protection changes emitted by this run.</p>'}${diagnostics}</div>
      <div class="job-resolution"><b>EVIDENCE / RESOLUTION</b><p>${esc(presentation.evidence)}</p><p>${esc(presentation.resolution)}</p></div>
    </div>`;
  }

  function renderJobJournal(snap) {
    const jobs = journalJobs();
    if (state.selectedJobId && !jobs.some(job => job.id === state.selectedJobId)) state.selectedJobId = null;
    $('journalSource').textContent = snap?.date
      ? `${state.jobJournal?.jobs?.length || 0} jobs / ${snap.date}`
      : 'session unavailable';
    $('journalSource').dataset.tooltip = `Scheduler evidence observed ${localTime(state.jobJournal?.observed_at)}. One row per execution; click a job to inspect its operational evidence.`;
    const jobRows = jobs.map(job => {
      const selected = job.id === state.selectedJobId;
      const presentation = jobPresentation(job);
      const tone = presentation.status === 'recovered' ? 'success' : presentation.status === 'known_debt' ? 'cleanup' : jobTone(job.status);
      return `<li class="job-row tone-${esc(tone)} status-${esc(presentation.status)} ${selected ? 'selected' : ''}">
        <button class="job-trigger" type="button" data-job-id="${esc(job.id)}" aria-expanded="${selected}">
          <span class="job-time">${esc(localTime(job.started_at))}</span><span class="job-duration">${esc(duration(job.duration_seconds))}</span><span class="job-chevron" aria-hidden="true">${selected ? '−' : '+'}</span>
          <span class="job-badges"><span class="issue-origin ${esc(presentation.component)}">${esc(presentation.component)}</span><span class="event-status ${esc(presentation.status)}">${esc(presentation.statusLabel)}</span></span>
          <span class="job-name">${esc(job.job_id)}</span><span class="job-summary">${esc(presentation.problem)}</span>
        </button>${selected ? renderJobDetails(job, snap, presentation) : ''}
      </li>`;
    }).join('');
    $('journal').innerHTML = jobRows || '<li><div class="journal-message">No scheduler jobs observed for this session.</div></li>';
    document.querySelectorAll('.job-trigger').forEach(button => button.addEventListener('click', () => {
      state.selectedJobId = state.selectedJobId === button.dataset.jobId ? null : button.dataset.jobId;
      renderJournal(snap);
    }));
  }

  function renderEventJournal(snap) {
    const rows = journalRows(snap);
    const shown = rows.slice(0, EVENT_JOURNAL_LIMIT);
    const coverage = state.runner?.event_history?.coverage_started_at;
    $('journalSource').textContent = snap?.date
      ? `${rows.length} events / ${snap.date}`
      : 'session unavailable';
    $('journalSource').dataset.tooltip = `Combines retained scheduler and runner evidence. Runner JSONL coverage ${coverage ? `starts ${localTime(coverage)}` : 'is unavailable'}.`;
    if (state.selectedEventKey && !shown.some(row => row.key === state.selectedEventKey)) state.selectedEventKey = null;
    $('journal').innerHTML = shown.length
      ? shown.map(row => {
        const actionable = Boolean(row.problem || row.impact || row.action || row.evidence);
        const selected = actionable && row.key === state.selectedEventKey;
        return `<li class="event-row ${esc(row.level)} tone-${esc(row.tone || 'system')} status-${esc(row.status || 'info')} ${selected ? 'selected' : ''}">
          ${actionable ? `<button class="event-trigger" type="button" data-event-key="${esc(row.key)}" aria-expanded="${selected}">` : '<div class="event-static">'}
          <div class="journal-meta"><span>${esc(row.category)}</span><time>${esc(row.time)}</time></div>
          ${actionable ? `<div class="event-badges"><span class="issue-origin ${esc(row.component)}">${esc(row.component)}</span><span class="event-status ${esc(row.status)}">${esc(eventStatus(row.status))}</span></div>` : ''}
          ${actionable ? `<div class="event-times"><span><b>INCURRED</b>${esc(localTime(row.incurredAt || row.sortKey))}</span>${row.recoveredAt ? `<span><b>RECOVERED</b>${esc(localTime(row.recoveredAt))}</span>` : ''}</div>` : ''}
          <div class="journal-message">${esc(row.title || row.message)}</div>${row.title ? `<div class="event-summary">${esc(row.message)}</div>` : ''}
          ${actionable ? '</button>' : '</div>'}
          ${selected ? `<div class="event-detail"><div><b>PROBLEM</b><p>${esc(row.problem || row.message)}</p></div><div><b>IMPACT</b><p>${esc(row.impact || 'No impact classification emitted.')}</p></div><div><b>ACTION</b><p>${esc(row.action || 'No action required.')}</p></div><div><b>EVIDENCE / RESOLUTION</b><p>${esc(row.evidence || row.message)}</p><p>${esc(row.resolution || 'Resolution not emitted.')}</p></div></div>` : ''}
        </li>`;
      }).join('')
      : '<li><div class="journal-message">No operational events observed for this session.</div></li>';
    document.querySelectorAll('.event-trigger').forEach(button => button.addEventListener('click', () => {
      state.selectedEventKey = state.selectedEventKey === button.dataset.eventKey ? null : button.dataset.eventKey;
      renderEventJournal(snap);
    }));
  }

  function renderJournal(snap) {
    const jobs = state.journalView === 'jobs';
    $('journalTitle').textContent = jobs ? 'Job journal' : 'Event journal';
    document.querySelectorAll('[data-journal-view]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.journalView === state.journalView));
    });
    if (jobs) renderJobJournal(snap);
    else renderEventJournal(snap);
  }

  function renderClocks() {
    const entries = [
      ['Runner observed', localTime(state.runner?.observed_at)],
      ['Runner freshness', state.runner?.freshness || 'missing'],
      ['Expected next', localTime(state.schedule?.expected_next_at)],
      ['Schedule evidence', state.schedule?.evidence ? `${state.schedule.evidence.state} / ${state.schedule.evidence.reason}` : 'missing'],
      ['Broker observed', localTime(state.broker?.observed_at)],
      ['Browser poll', `${POLL_MS / 1000}s`]
    ];
    $('sourceClocks').innerHTML = entries.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  }

  function render() {
    const snap = latestSnap();
    renderContext(snap);
    renderMetrics(snap);
    renderRail(snap);
    renderScheduleFacts();
    renderMonitor(snap);
    renderOpenIssues();
    renderPositions();
    renderDecisions(snap);
    renderOrders();
    renderJournal(snap);
    renderClocks();
  }

  document.querySelectorAll('[data-journal-view]').forEach(button => button.addEventListener('click', () => {
    state.journalView = button.dataset.journalView;
    renderJournal(latestSnap());
  }));
  $('fontSelector').addEventListener('change', event => {
    const font = applyFont(event.target.value);
    try { localStorage.setItem(FONT_KEY, font); } catch (_) { /* Keep the live choice when storage is unavailable. */ }
  });
  compactIssueMedia.addEventListener('change', event => {
    state.issuesSectionOpen = !event.matches;
    state.selectedIssueKey = event.matches ? null : (state.openIssues?.issues?.[0]?.key || null);
    state.selectedMonitorKey = null;
    renderMonitor(latestSnap());
    renderOpenIssues();
  });
  $('openIssuesShell').addEventListener('toggle', event => { state.issuesSectionOpen = event.currentTarget.open; });

  window.setInterval(renderRailClock, 1000);

  poll();
  window.setInterval(poll, POLL_MS);
})();
