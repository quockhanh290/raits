(() => {
  'use strict';

  const POLL_MS = 8000;
  const MIN_METRIC_DAYS = 20;
  const EVENT_JOURNAL_LIMIT = 24;
  const state = { runner: null, runnerPositions: null, broker: null, schedule: null, sessionEvents: null, jobJournal: null, executionQuality: null, openIssues: null, selectedJobId: null, selectedIssueKey: null, selectedMonitorKey: null, selectedEventKey: null, journalView: 'jobs', issuesSectionOpen: null, marketView: null, mvTab: null, mvInner: null, 
    // Stage 5ZZZ-BQ. null means the live session. A date string means the operator 
    // opened a past one, and only the market-view band follows it.
    mvDay: null };
  const compactIssueMedia = window.matchMedia('(max-width: 680px)');
  const roots = ['MNKD', 'M2K', 'MNQ', 'MYM', 'MES'];

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
  const etDateTime = iso => iso ? new Date(iso).toLocaleString('en-CA', {
    timeZone: 'America/New_York', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
  }) + ' ET' : '--';

  // ── Status-rail wall clock ───────────────────────────────────────────────
  // The time it is NOW, which is a different thing from every other timestamp on this page:
  // those describe when data was observed. The backend binds 127.0.0.1, so the only browser
  // that can open this page runs on the machine the scheduler fires on — the browser clock
  // IS the server clock and needs no round-trip. That stops being true the day this is
  // served over the LAN, and then it has to anchor on server_now instead.
  const ET_ZONE = 'America/New_York';
  const etInstant = naiveIso => {
    const asUtc = Date.parse(`${naiveIso}Z`);
    if (Number.isNaN(asUtc)) return 0;
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: ET_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
    }).formatToParts(new Date(asUtc)).reduce((acc, part) => {
      acc[part.type] = part.value;
      return acc;
    }, {});
    const shownInEt = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day),
      Number(parts.hour), Number(parts.minute), Number(parts.second));
    return asUtc + (asUtc - shownInEt);
  };
  const sortInstant = value => {
    if (!value) return 0;
    const text = String(value);
    const parsed = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(text) ? Date.parse(text) : etInstant(text);
    return Number.isNaN(parsed) ? 0 : parsed;
  };
  // Today's calendar day in ET, read off the SERVER's clock when we have it.
  //
  // The zone conversion is safe from anywhere — Intl does that correctly whatever the
  // viewer's timezone. What is not safe is assuming the viewer's clock reads the same
  // INSTANT as the machine writing the scheduler log, and the comment above etInstant
  // already flags that the two stop being one machine the day this is served over the
  // LAN. server_now is in the broker payload on every poll and costs nothing extra, so
  // it is the anchor; the browser clock is only the fallback for the first poll, before
  // any payload has arrived.
  const etToday = () => {
    const stamped = Date.parse(state.broker?.server_now || '');
    const instant = Number.isNaN(stamped) ? new Date() : new Date(stamped);
    return new Intl.DateTimeFormat('en-CA', { timeZone: ET_ZONE }).format(instant);
  };
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
  const runnersFor = brokerPos => runnerPositions().filter(pos =>
    rootOf(pos.inst) === rootOf(brokerPos.inst) && String(pos.direction).toUpperCase() === brokerDirection(brokerPos.position)
  );
  const runnerFor = brokerPos => runnersFor(brokerPos)[0] || null;
  const positionKey = pos => [
    rootOf(pos?.inst),
    String(pos?.cluster || ''),
    String(pos?.direction || '').toUpperCase(),
    String(pos?.entry_day || '').slice(0, 10)
  ].join('|');
  const persistedRunnerFor = pos => (state.runnerPositions?.payload?.positions || [])
    .find(saved => positionKey(saved) === positionKey(pos));
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
  const expectedQuantity = brokerPos => {
    const quantities = runnersFor(brokerPos).map(runnerQuantity);
    if (!quantities.length || quantities.some(value => value == null)) return null;
    return quantities.reduce((total, value) => total + value, 0);
  };
  const stopsFor = brokerPos => stopOrders().filter(order => contractKey(order.inst) === contractKey(brokerPos.inst));
  const expectedStopAction = brokerPos => Number(brokerPos.position) > 0 ? 'SELL' : 'BUY';
  const stopFieldsKnown = order => order.action != null && order.qty != null && Number.isFinite(Number(order.qty)) && order.status != null && order.status !== '?';
  const tickFor = brokerPos => {
    const spec = (state.broker?.payload?.contract_specs || {})[rootOf(brokerPos.inst)];
    const tick = Number(spec?.tick);
    return Number.isFinite(tick) && tick > 0 ? tick : null;
  };
  const STOP_TICK_TOLERANCE = 4;
  const stopPriceAgrees = (order, brokerPos) => {
    const aux = Number(order.aux_price);
    if (!Number.isFinite(aux)) return false;
    const last = Number(brokerPos.market_price);
    if (Number.isFinite(last)) {
      const long = Number(brokerPos.position) > 0;
      if (long ? aux >= last : aux <= last) return false;
    }
    const plans = runnersFor(brokerPos).map(pos => Number(pos.stop_price)).filter(Number.isFinite);
    if (!plans.length) return true;
    const tick = tickFor(brokerPos);
    if (tick == null) return true;
    return plans.some(plan => Math.abs(aux - plan) <= STOP_TICK_TOLERANCE * tick);
  };
  const validStopsFor = brokerPos => {
    const candidates = stopsFor(brokerPos).filter(order =>
      stopFieldsKnown(order)
      && String(order.action).toUpperCase() === expectedStopAction(brokerPos)
      && liveStopStatuses.has(String(order.status).toUpperCase())
      && stopPriceAgrees(order, brokerPos)
    );
    const needed = Math.abs(Number(brokerPos.position));
    const covered = candidates.reduce((total, order) => total + Math.abs(Number(order.qty)), 0);
    return covered >= needed ? candidates : [];
  };
  const invalidStopsFor = brokerPos => {
    const valid = validStopsFor(brokerPos);
    return stopsFor(brokerPos).filter(order => stopFieldsKnown(order) && !valid.includes(order));
  };
  const unknownStopsFor = brokerPos => stopsFor(brokerPos).filter(order => !stopFieldsKnown(order));
  const orphanStops = () => stopOrders().filter(order =>
    !brokerPositions().some(pos => contractKey(pos.inst) === contractKey(order.inst))
  );
  // "What does the runner hold RIGHT NOW" — read off live_positions.json, not the
  // snapshot.
  //
  // The snapshot is published by dump_state, which only runs inside run_day. The
  // 09:31 max-hold exit and the stop-repair sweeps close positions in their own
  // processes and write live_positions.json without republishing a snapshot, so
  // between them and the next 14:05 slot the snapshot describes a book that no longer
  // exists. Measured 2026-08-17: max-hold closed M2K at 09:31, the file went to zero
  // positions and IBKR showed zero, and this raised a `runner-only position` INCIDENT
  // for four and a half hours — saying protection logic may be running on stale state,
  // about a position that had been closed on time.
  //
  // Only this check moves. runnersFor() stays on the snapshot because protectionSummary
  // reads stop_deferred from it, and the persisted projection does not carry that field
  // — swapping wholesale would count every deliberately deferred stop as naked, trading
  // one false alarm for a worse one.
  const persistedPositions = () => state.runnerPositions?.payload?.positions || [];
  const persistedUsable = () => !!state.runnerPositions?.payload && !state.runnerPositions?.error;
  const runnerOnly = () => (persistedUsable() ? persistedPositions() : []).filter(pos =>
    !brokerPositions().some(live => rootOf(live.inst) === rootOf(pos.inst) && brokerDirection(live.position) === String(pos.direction).toUpperCase())
  );
  const protectionSummary = () => brokerPositions().reduce((acc, pos) => {
    acc.total += 1;
    if (validStopsFor(pos).length) acc.covered += 1;
    else if (runnersFor(pos).some(runner => runner.stop_deferred)) acc.deferred += 1;
    else acc.naked += 1;
    return acc;
  }, { covered: 0, deferred: 0, naked: 0, total: 0 });
  const brokerPositionsMatchNow = () => brokerUsable()
    && runnerOnly().length === 0
    && brokerPositions().every(pos => {
      const quantity = expectedQuantity(pos);
      return quantity != null && quantity === Math.abs(Number(pos.position));
    });

  //: One timeout for seven endpoints was one endpoint's budget imposed on all of them.
  //: Measured on 2026-08-30, same machine, same backend process:
  //:
  //:   runner-state 57-66ms · broker 3ms · schedule-status 41-93ms · open-issues 24-33ms
  //:   runner-positions 3ms · track1-market-view 13-90ms
  //:   track1-runtime  0.67-1.68s under load, 7.09s and 9.04s on the first call after an
  //:                   idle gap (it globs and re-reads the whole window_coverage /
  //:                   explanations evidence tree, so a cold OS file cache is the cost)
  //:
  //: At a flat 6000ms the slow one fails on exactly the load a person is looking at — the
  //: first one — and the panel then says the endpoint "did not answer" about a backend that
  //: answered correctly two seconds later. Same defect the paper dashboard already paid for
  //: when its 30s timeout sat under a 41.7s cold evidence scan.
  const DEFAULT_TIMEOUT_MS = 6000;
  const TRACK1_RUNTIME_TIMEOUT_MS = 20000;

  async function fetchJson(url, timeoutMs = DEFAULT_TIMEOUT_MS) {
    const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
  }

  //: Track 1's own budget is longer than the poll interval, so without this a slow call
  //: would still be in flight when the next poll starts one more, and three overlapping
  //: reads of the same evidence tree could land out of order — an older payload overwriting
  //: a newer one. One in flight at a time; a skipped poll leaves the last good state alone.
  let track1InFlight = false;
  //: Stage 5ZZZ-AN. Track 1 may draw itself, but it may not draw the page FIRST.
  //
  // `pollTrack1` awaits ONE request; the batch awaits six, and then a second round of three
  // for the journals, before it renders. So on a fresh load Track 1 nearly always won, and
  // its `render()` painted a whole page out of empty state — a status rail with no runner
  // behind it and every metric reading "--".
  //
  // It showed up as three DOM tests failing on one run and a different one on the next:
  // they wait for the status rail to appear and then read a metric, and the rail was being
  // created by that premature pass. A race reads as flakiness, and flaky red is red that
  // gets ignored.
  //
  // Nothing is lost by waiting: before the batch lands there is nothing else to draw, and
  // the batch's own render already includes whatever Track 1 has stored by then. This only
  // suppresses a paint that could never have been correct.
  let firstBatchRendered = false;

  async function pollTrack1() {
    if (track1InFlight) return;
    track1InFlight = true;
    try {
      state.track1 = await fetchJson('/api/v1/track1-runtime', TRACK1_RUNTIME_TIMEOUT_MS);
    } catch (err) {
      state.track1 = { ...(state.track1 || {}), payload: null,
                       error: err?.message || 'track1-runtime request failed' };
    } finally {
      track1InFlight = false;
    }
    if (firstBatchRendered) render();
  }

  async function poll() {
    // Track 1 runtime is NOT in this batch. It was, and because the batch is awaited as a
    // whole before the first render, its 7-9s cold read held back every other panel: on a
    // fresh load the Market View summary sat at "--" and the Regime block was empty for
    // between 9.06s and 12.05s (measured 2026-08-30), while the market-view endpoint that
    // fills both had already answered in 41ms. A slow panel may keep itself waiting; it may
    // not decide when the rest of the page is allowed to appear.
    pollTrack1();
    const results = await Promise.allSettled([
      fetchJson('/api/v1/runner-state'),
      fetchJson('/api/v1/broker'),
      fetchJson('/api/v1/schedule-status'),
      fetchJson('/api/v1/open-issues'),
      fetchJson('/api/v1/runner-positions'),
      // Stage 5ZZL. Its own endpoint, and its own failure: this one slices instrument
      // stores, so a backend that has not been restarted since it was added must leave the
      // rest of the page untouched rather than taking the poll down with it.
      fetchJson('/api/v1/track1-market-view'
                + (() => {
                    const q = [];
                    if (state.mvDay) q.push('day=' + encodeURIComponent(state.mvDay));
                    if (state.mvInst) q.push('inst=' + encodeURIComponent(state.mvInst));
                    return q.length ? '?' + q.join('&') : '';
                  })())
    ]);
    // Named bindings rather than results[5] / results[6]: the numeric index has to be
    // re-counted by hand every time the list changes, and the one panel most likely to be
    // added or removed sits at the end where a miscount is silent.
    const [rRunner, rBroker, rSchedule, rIssues, rPositions, rMarketView] = results;
    if (rRunner.status === 'fulfilled') state.runner = rRunner.value;
    else state.runner = { ...(state.runner || {}), freshness: 'unknown', error: rRunner.reason?.message || 'runner-state request failed' };
    if (rBroker.status === 'fulfilled') state.broker = rBroker.value;
    else state.broker = { ...(state.broker || {}), connected: false, freshness: 'unknown', error: rBroker.reason?.message || 'broker request failed' };
    if (rSchedule.status === 'fulfilled') state.schedule = rSchedule.value;
    else state.schedule = { ...(state.schedule || {}), evidence_available: false, evidence: null, incidents: [], unexplained_overdue: [], error: rSchedule.reason?.message || 'schedule request failed' };
    if (rIssues.status === 'fulfilled') state.openIssues = rIssues.value;
    else state.openIssues = { ...(state.openIssues || {}), issues: [], error: rIssues.reason?.message || 'open-issues request failed' };
    if (rPositions.status === 'fulfilled') state.runnerPositions = rPositions.value;
    else state.runnerPositions = { ...(state.runnerPositions || {}), payload: null, error: rPositions.reason?.message || 'runner-positions request failed' };
    if (rMarketView.status === 'fulfilled') state.marketView = rMarketView.value;
    else state.marketView = { market_view: null, regime: null,
      error: rMarketView.reason?.message || 'market view request failed' };
    // TWO days, not one. Session events and execution quality belong to a trading
    // SESSION; scheduled jobs belong to a CALENDAR day, and the two part company
    // exactly when it matters most.
    //
    // Both used to be anchored on the latest snapshot's date, and snapshots are only
    // written by run_live_day. So on any day the runner does not hold a session there
    // is no snapshot, the anchor does not move, and the job panel keeps showing the
    // previous trading day. That is not a weekend inconvenience:
    //
    //   * the Sunday 18:30 ET stop sweep is filed under a Sunday, and no snapshot ever
    //     bears a Sunday date, so it could never have appeared here at all;
    //   * and when the 13:45 pre-flight fails, both skip branches return before
    //     launching the child — no run_live_day, no snapshot. The day the whole
    //     session is skipped is the day the panel silently shows yesterday, while the
    //     SKIPPED rows that explain it sit under a date nothing asks for. That has
    //     happened twice already (2026-08-03, 2026-08-04).
    //
    // allSettled per endpoint rather than one Promise.all: the job journal must not go
    // blank because a session-scoped request failed, which is the same independence
    // the two days above are about.
    const sessionDay = latestSnap()?.date;
    const journalDay = etToday();
    const journalResults = await Promise.allSettled([
      fetchJson(`/api/v1/job-journal/${encodeURIComponent(journalDay)}`),
      sessionDay ? fetchJson(`/api/v1/session-events/${encodeURIComponent(sessionDay)}`) : Promise.resolve(undefined),
      sessionDay ? fetchJson(`/api/v1/execution-quality/${encodeURIComponent(sessionDay)}`) : Promise.resolve(undefined)
    ]);
    if (journalResults[0].status === 'fulfilled') state.jobJournal = journalResults[0].value;
    else state.jobJournal = { source: 'scheduler_log', day: journalDay, jobs: [], monitor_events: [], error: journalResults[0].reason?.message || 'job-journal request failed' };
    if (sessionDay) {
      if (journalResults[1].status === 'fulfilled') state.sessionEvents = journalResults[1].value;
      else state.sessionEvents = { source: 'live_log', day: sessionDay, events: [], error: journalResults[1].reason?.message || 'session-events request failed' };
      if (journalResults[2].status === 'fulfilled') state.executionQuality = journalResults[2].value;
      else state.executionQuality = { source: 'trade_log.jsonl', day: sessionDay, fills: [], exceptions: [], error: journalResults[2].reason?.message || 'execution-quality request failed' };
    }
    // "Backend unavailable" now means the whole core batch failed. Track 1 runtime used to
    // count here and no longer does: it is polled on its own clock, so a poll that arrives
    // while it is still in flight would have had no vote either way, and one panel's slow
    // read is not evidence that the backend is up.
    $('fatalBanner').hidden = results.some(result => result.status === 'fulfilled');
    // Set BEFORE the render, so a Track 1 read that lands during it is free to draw itself
    // on the next poll rather than being suppressed for a whole cycle.
    firstBatchRendered = true;
    render();
  }

  function setMetric(id, value, numeric) {
    const el = $(id);
    el.textContent = value;
    el.classList.remove('positive', 'negative', 'warning');
    if (numeric != null) el.classList.add(Number(numeric) >= 0 ? 'positive' : 'negative');
  }

  function renderContext(snap) {
    // Stage 5ZZZ-AH. Track 1's session day first, exactly as the regime cell two lines below
    // already does - and for the same reason it had to. This read the LEGACY runner's last
    // snapshot date, and in Track 1-only shadow nothing writes that file: measured on
    // 2026-08-30 the page header read "Aug 24, 2026" while the route's own last session was
    // 2026-08-28. The date at the top of a monitor is the frame every panel under it is read
    // in, so a stale one mislabels the whole page.
    //
    // The legacy date stays as the fallback for a machine with no Track 1 record, and the
    // legacy panels keep stamping their own day beside their own numbers - the decision panel
    // prints "<its date> / runner <time>" - so the two frames stay told apart rather than
    // merged.
    const t1SessionDay = state.marketView?.market_view?.session_date;
    $('sessionDate').textContent = sessionDate(t1SessionDay || snap?.date);
    // Stage 5ZZW. The Track 1 regime record first. This read `snap?.regime` - the LEGACY
    // runner's snapshot - so in track1-only shadow, where nothing writes that file, the panel
    // was showing a label from whenever legacy last ran, presented as today's. The legacy
    // reading stays as a fallback for a machine with no Track 1 record.
    // Stage 5ZZZ-CM. Ô `Regime` trong hàng Model inputs đã bỏ: nó là ĐẦU RA của mô hình,
    // không phải đầu vào, và nó đã hiện to hơn ngay dòng dưới kèm "held N days".
    //
    // Khối ghi vào nó bị GỠ HẲN chứ không canh `null`. Bản canh null làm hai phép kiểm hợp
    // đồng đỏ, và chúng đúng: đọc một id mà không trang nào dựng thì mọi nhánh dựa vào nó là
    // mã chết, và một `if` bọc ngoài chỉ khiến mã chết trông như mã phòng xa.
    const ops = state.runner?.payload?.meta?.operational_status || snap?.operational_status || {};
    const regimeStatus = ops.regime_freshness?.status;
    // Stage 5ZZW. The SPY date this panel shows is the one the TRACK 1 regime record was
    // labelled from, not the legacy runner's view of its own inputs. The two are different
    // questions and this panel is asked the Track 1 one: `label_date` is the session the
    // published label belongs to, and the record carries its own status and age.
    //
    // The legacy reading stays as a fallback rather than being deleted, so a machine with no
    // Track 1 record yet reads exactly as it did before. When neither is available the panel
    // says so in Track 1 terms rather than reporting a stale legacy value as current.
    const t1Regime = state.marketView?.regime || null;
    const regimeDate = t1Regime?.label_date || ops.regime_freshness?.last_spy_date;
    const t1RegimeOk = t1Regime ? t1Regime.status === 'PASS' : null;
    $('regimeInputDate').textContent = regimeDate
      ? sessionDate(regimeDate).replace(/, \d{4}$/, '')
      : t1Regime ? 'Track 1 record unavailable'
      : regimeStatus === 'OK' ? 'Current' : 'Unavailable';
    $('regimeInputDate').className = (t1RegimeOk ?? (regimeStatus === 'OK')) ? 'positive' : 'warning';
    $('regimeInputDate').title = t1Regime
      ? `Track 1 regime record — ${t1Regime.status || 'unknown'}, checked ${t1Regime.age_hours ?? '?'}h ago`
      : 'no Track 1 regime record; showing the legacy runner reading';
    const modelStatus = ops.model_age?.status;
    // Stage 5ZZY. The month count is derived from the Track 1 record's own `fit_end`, not
    // read from the legacy runner's `months_old`. That field stops advancing the day legacy
    // stops running — measured 2026-09-03, the snapshot carrying it was 10.9 days old — so a
    // fit that keeps ageing would keep reporting the age it had when legacy last wrote.
    // Same arithmetic as `runner.py`, on a date the live route owns.
    //
    // The OK / WARN / URGENT state is deliberately NOT derived. It comes from the stale
    // guard's own notification flags, not from any month threshold, and Track 1 publishes
    // no equivalent — so it is still the legacy status, and the title says whose it is.
    const t1FitEnd = t1Regime?.inputs?.fit_end;
    const monthsSinceFit = iso => {
      const fit = new Date(`${iso}T00:00:00`);
      if (Number.isNaN(fit.getTime())) return null;
      const now = new Date();
      return Math.max(0, (now.getFullYear() - fit.getFullYear()) * 12 + (now.getMonth() - fit.getMonth()));
    };
    const modelMonths = (t1FitEnd ? monthsSinceFit(t1FitEnd) : null) ?? ops.model_age?.months_old;
    // Hai dòng phụ dưới Model age / HMM fit đã bỏ khỏi header — chúng lặp lại điều mà
    // giá trị và màu đã nói, và đẩy cả thanh header cao thêm một dòng. Chi tiết không mất:
    // chuyển sang title, hover vẫn đọc được.
    $('modelInputAge').textContent = modelStatus === 'OK' ? 'Current' : `${modelMonths ?? '?'} mo stale`;
    $('modelInputAge').className = modelStatus === 'OK' ? 'positive' : 'warning';
    // Stage 5ZZZ-CM. Câu về việc ĐÓNG BĂNG LẠI nhập vào đây. Nó từng chiếm một cột riêng
    // để nói "none" gần như mọi ngày, và nó cùng chủ đề với tuổi mô hình: mô hình cũ bao
    // nhiêu, và có ai đang chờ quyết định đóng băng lại không.
    const refreeze = state.runner?.payload?.meta?.operational_status?.refreeze?.pending;
    $('modelInputAge').title = (modelStatus === 'OK' ? 'Fit current' : 'Known debt / G2 HARD')
      + (t1FitEnd
          ? ` — age measured from the Track 1 fit end ${t1FitEnd}; the gate state is the legacy runner's own.`
          : " — no Track 1 fit end; both the age and the gate state are the legacy runner's.")
      + (refreeze === true
          ? ' A re-freeze decision is outstanding.'
          : refreeze === false
            ? ' No re-freeze decision is outstanding.'
            : ' Whether a re-freeze is outstanding was not reported.');
    // Stage 5ZZY. HMM fit, from the Track 1 regime record rather than from the legacy
    // runner's session log. `hmm_fit_diagnostic` is grouped out of `live_day_MMDD.log`, a
    // file only `run_live_day.py` writes — Track 1 lists that file's siblings among the
    // paths it must never touch. So in track1-only shadow this tile reported whatever day
    // legacy last ran, presented as today's: measured 2026-09-03, it was printing a fit
    // from the 24 August log, eleven days stale, and today's own log does not exist.
    //
    // The count itself does not survive the move either. `22/22 complete / 22 warn` is the
    // legacy runner refitting once per slot across one day. Track 1 does not refit per
    // session at all — it reads one frozen fit — so there is no per-session convergence
    // count to report, and inventing one would be worse than the stale number. What the
    // record does own is the shape of that fit, which is what this tile now says. Its
    // health check is on `Fit end` beside it, coloured by the same record's verification.
    //
    // The legacy reading stays as a fallback for a machine with no Track 1 record, the
    // same shape as `Regime`, `SPY data` and `Fit end` above.
    const fitDiagnostic = [...(state.sessionEvents?.events || [])].reverse()
      .find(event => event.kind === 'hmm_fit_diagnostic');
    const fitWarnings = Number(fitDiagnostic?.non_convergence_count || 0);
    const t1States = t1Regime?.inputs?.n_states;
    const t1Labels = t1Regime?.inputs?.labels;
    if (t1States != null) {
      $('modelFitStatus').textContent = `${t1States} states`
        + (t1Labels != null ? ` / ${Number(t1Labels).toLocaleString('en-US')} labels` : '');
      $('modelFitStatus').className = t1RegimeOk ? 'positive' : 'warning';
      $('modelFitStatus').title = `Track 1 reads one frozen fit (fit end ${t1Regime?.inputs?.fit_end || 'unknown'}), `
        + 'so there is no per-session refit and no per-session convergence count. '
        + 'The label check for that fit is on Fit end.';
    } else if (t1Regime) {
      $('modelFitStatus').textContent = 'Track 1 unavailable';
      $('modelFitStatus').className = 'warning';
      $('modelFitStatus').title = 'the Track 1 regime record carries no fit inputs';
    } else {
      $('modelFitStatus').textContent = fitDiagnostic
        ? `${fitDiagnostic.completed_fits}/${fitDiagnostic.attempts} complete${fitWarnings ? ` / ${fitWarnings} warn` : ''}`
        : 'Not observed';
      $('modelFitStatus').className = fitDiagnostic?.completed_fits === fitDiagnostic?.attempts && fitWarnings === 0 ? 'positive' : 'warning';
      $('modelFitStatus').title = fitDiagnostic
        ? `no Track 1 regime record; legacy runner log — ${fitWarnings} convergence warning(s) / no documented gate failure`
        : 'No retained fit evidence';
    }
    // Stage 5ZZW. HMM fit end and the label check, from the Track 1 regime record rather than
    // from runner session events. `inputs.fit_end` is the end of the fitted window the label
    // was produced with, and `verification` is the route's own label check.
    const fitEndEl = document.getElementById('modelFitEnd');
    if (fitEndEl) {
      const fitEnd = t1Regime?.inputs?.fit_end;
      fitEndEl.textContent = fitEnd ? sessionDate(fitEnd).replace(/, \d{4}$/, '')
        : t1Regime ? 'Track 1 unavailable' : (fitEndEl.textContent || '--');
      const verify = t1Regime?.verification || null;
      fitEndEl.className = !verify ? '' : verify.status === 'PASS' ? 'positive' : 'warning';
      fitEndEl.title = verify
        ? `Track 1 label check ${verify.status}: ${verify.detail || ''}`
        : 'no Track 1 label check available';
    }
    $('modelInputsZone').classList.toggle('watch',
      (t1RegimeOk === null ? regimeStatus !== 'OK' : !t1RegimeOk) || modelStatus !== 'OK');
    // Một nguồn duy nhất cho câu chữ về độ tươi runner, dùng chung với rail. Bản cũ
    // vừa nhân đôi logic vừa nằm trong một <b hidden> không bao giờ được bỏ hidden,
    // nên tuổi snapshot không hiện ở đâu ngoài Source Clocks cuối sidebar.
    const rf = state.runner?.freshness || 'missing';
    $('runnerContext').textContent = runnerFreshnessText(rf, state.runner?.expected_next_at, state.runner?.age_seconds);
    $('runnerContext').className = ['stale', 'late', 'missing'].includes(rf) ? 'negative'
      : rf === 'unknown' ? 'warning' : '';
    // Scheduler age, and the only reading of it that means anything: is this process
    // older than the cron table it is running. Measured 2026-08-16 — the scheduler had
    // been up since 13/8 while its cron was rewritten 15/8, so the Sunday sweep
    // committed that day did not exist in the running instance. Twenty-one restarts
    // went past unnoticed because every indicator said "running".
    // age() renders everything above an hour as "84.0h ago", and the case this
    // indicator exists for is a scheduler that has been up for DAYS. 84 hours does not
    // read as "three days" at a glance, which is the only glance this gets.
    const uptime = seconds => {
      if (seconds == null) return 'unknown age';
      const d = Math.floor(seconds / 86400);
      const h = Math.floor((seconds % 86400) / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      if (d) return `${d}d${String(h).padStart(2, '0')}h`;
      if (h) return `${h}h${String(m).padStart(2, '0')}m`;
      return `${m}m`;
    };
    const sp = state.schedule?.scheduler_process;
    const spEl = $('schedulerContext');
    if (spEl) {
      if (!sp) {
        spEl.textContent = 'Scheduler unknown';
        spEl.className = 'warning';
      } else if (!sp.running) {
        spEl.textContent = 'Scheduler DOWN';
        spEl.className = 'negative';
      } else if (sp.process_count > 1) {
        // Two schedulers fire every slot twice and both write live_positions.json.
        spEl.textContent = `Scheduler ×${sp.process_count} RUNNING`;
        spEl.className = 'negative';
      } else if (sp.stale_code) {
        spEl.textContent = `Scheduler ${uptime(sp.age_seconds)} old · RUNNING OLD CRON`;
        spEl.className = 'negative';
      } else {
        spEl.textContent = `Scheduler up ${uptime(sp.age_seconds)}`;
        spEl.className = '';
      }
    }
    const connected = state.broker?.connected;
    const usable = brokerUsable();
    $('brokerContext').textContent = state.broker
      ? `${usable ? 'Live' : connected ? 'Stale' : 'Disconnected'} · updated ${age(state.broker.age_seconds)}`
      : 'source unavailable';
    $('brokerContext').className = usable ? 'positive' : connected ? 'warning' : 'negative';
  }

  function renderMetrics(snap) {
    // Khi nguồn runner-state chết, poll() cố ý GIỮ payload cũ để những phần khác
    // của trang còn tham chiếu được và để lane reconcile không báo động giả. Nhưng
    // CON SỐ thì không được hiện như đang sống: người vận hành đọc một giá trị
    // trông sống động từ một nguồn đã tắt, và mờ 42% không phải là một câu nói.
    // Chỉ chặn phần runner-derived; số của broker là nguồn riêng, vẫn đúng.
    const runnerDead = Boolean(state.runner?.error);
    const meta = runnerDead ? {} : (state.runner?.payload?.meta || {});
    const snapshot = runnerDead ? null : snap;
    const equity = snapshot?.equity ?? meta.final_equity;
    const unreal = state.broker?.payload?.unrealized_pnl;
    const realized = snapshot?.decision?.realized_today;
    // Stage 5ZZZ-CG. Rủi ro đọc sổ của Track 1, không đọc ảnh chụp của tuyến đã nghỉ hưu.
    //
    // Đo được 2026-09-05: ba con số của ô Risk và con số Gross đều lấy từ ảnh chụp cuối cùng
    // của runner cũ, 289,8 giờ — 12,1 ngày — trước đó. Cả bốn đều là SỐ KHÔNG:
    //
    //     drawdown_pct 0.0 · drawdown_dollars 0.0 · max_dd_pct 0.0 · hard_dd_pct 0.15
    //
    // Một số không từ nguồn đã chết không phân biệt được với một ngày yên bình, và cái đọc
    // được từ màn hình là "chúng ta còn xa giới hạn rủi ro" trong khi sự thật là "12 ngày rồi
    // không ai đo rủi ro".
    //
    // Track 1 giữ sổ riêng và sổ ấy đang sống — chốt 2026-09-04 15:55 ET. Nhưng nội dung là
    // `equity 0.0 · peak_equity 0.0 · positions []`, vì tuyến này chưa từng gửi lệnh nào. Nên
    // chuyển nguồn KHÔNG làm ô nào sáng lên: nó đổi một số không mượn thành một câu đúng.
    // Đó là điều đáng đổi — đỉnh bằng 0 nghĩa là mức sụt KHÔNG XÁC ĐỊNH, không phải bằng 0.
    //
    // Không có đường lui về legacy khi Track 1 lỗi: quay về một con số 12 ngày tuổi lúc nguồn
    // mới im lặng chính là cơ chế đã tạo ra sự nhầm lẫn này ngay từ đầu.
    //
    // CÔNG TẮC là `legacyRunnerStale()`, không phải "endpoint Track 1 có trả lời". Bản đầu
    // dùng vế sau và ba phép kiểm sẵn có đỏ ngay — đúng: khi runner cũ còn SỐNG thì Sharpe,
    // Calmar và mức sụt của nó là của chính nó và được phép hiện. Trang đã có sẵn một khái
    // niệm "tuyến cũ đã nghỉ" và các khối khác đều dùng nó; dựng thêm một khái niệm thứ hai
    // là tạo ra hai câu trả lời cho cùng một câu hỏi, rồi chúng sẽ lệch nhau.
    // Và điều kiện là CHỈ "tuyến cũ đã nghỉ" — không kèm "Track 1 đã trả lời".
    //
    // Bản trước đòi cả hai, và ảnh chụp trang thật bắt được hậu quả: `track1-runtime` là
    // lời gọi chậm nhất trang (đo được 0,67–9,04s, lâu nhất ở lần gọi đầu sau khi khởi
    // động), nên trong suốt khoảng đó ô Risk vẫn in `0.0% of 15.00% hard limit` của tuyến
    // đã im 12 ngày. Mỗi lần tải nguội là một lần nháy con số sai.
    //
    // Không cần chờ: một tuyến đã nghỉ thì con số của nó không dùng được, bất kể nguồn thay
    // thế đã kịp trả lời hay chưa. Nhánh "sổ chưa về" bên dưới đã nói đúng câu cần nói.
    const t1mode = legacyRunnerStale();
    const t1book = (!state.track1?.error && state.track1?.book?.present)
      ? (state.track1.book.payload || null) : null;
    const t1peak = t1book ? Number(t1book.peak_equity) : NaN;
    const t1equity = t1book ? Number(t1book.equity) : NaN;
    const t1curve = Number.isFinite(t1peak) && t1peak > 0 && Number.isFinite(t1equity);
    const drawdown = t1mode
      ? (t1curve ? (t1peak - t1equity) / t1peak : NaN)
      : Number(snapshot?.drawdown_pct);
    const drawdownDollars = t1mode
      ? (t1curve ? t1peak - t1equity : NaN)
      : Number(snapshot?.drawdown_dollars);
    // Track 1 không công bố trần rút vốn ở đâu cả — đã quét `safety`, `gates`, `route`,
    // `checkpoint`. Con số 15% là `RISK["max_drawdown_pct"]` của cấu hình rủi ro futures mà
    // runner cũ đọc; chưa đo được rằng nó áp cho tuyến này, nên không gán bừa cho nó.
    const hardDrawdown = t1mode ? NaN : Number(meta.hard_dd_pct);
    const gaugePct = Number.isFinite(drawdown) && Number.isFinite(hardDrawdown) && hardDrawdown > 0
      ? Math.min(100, Math.max(0, drawdown / hardDrawdown * 100)) : 0;
    $('metrics').classList.toggle('broker-stale', !brokerUsable());
    // Stage 5ZZH. Stale by AGE, not by the label.
    //
    // `/api/v1/runner-state` reported `freshness: "fresh"` for a payload 288,670 seconds —
    // 80.2 hours — old, because the freshness model asks the SCHEDULE whether a publish was
    // due, and in track1-only mode the legacy runner is never due. So the zone never dimmed
    // and the whole runner-derived block read as live. The envelope's own `age_seconds` is
    // honest, and that is what this asks. The label is left alone: it is legacy contract and
    // other panels read it.
    const legacyStale = legacyRunnerStale();
    $('metrics').classList.toggle('runner-stale', legacyStale);
    // Stage 5ZZZ-BK. The SAME staleness, applied to the other block that carries the same
    // marker.
    //
    // `runner-derived` is on the metrics row AND on the decision section, and only the metrics
    // row was being dimmed. Measured 2026-08-31: the metrics read `--` while the section
    // headed "Today's Decision" printed REGIME Calm, TAKEN 0, ENTERED 0, CLOSED 0 -- all of it
    // from the legacy runner's last snapshot, 2026-08-24, 7.4 days old. An operator reads that
    // as "the system looked today and took nothing", on a day when Calm recorded two setups
    // and NKD walked 22 slots.
    //
    // Dimming is not enough here, and the note beside the metrics row says why: 42% opacity is
    // not a sentence. So the counters are hidden and replaced by the reading Track 1 already
    // publishes for itself, which is a fact rather than a blank.
    const decisionSection = $('decisionSection');
    if (decisionSection) {
      decisionSection.classList.toggle('runner-stale', legacyStale);
      const retired = $('decisionRetired');
      const t1line = state.track1?.reporting?.headline;
      const t1detail = state.track1?.reporting?.headline_detail || '';
      if (retired) {
        retired.hidden = !legacyStale;
        retired.textContent = legacyStale
          ? (t1line || 'The legacy runner snapshot is retired; Track 1 publishes its own state.')
          : '';
        // Stage 5ZZZ-CM. Kiểm kê chứng minh câu trên đứng ngay sau nó, một cú rê chuột —
        // không chiếm chỗ của câu, và không biến mất.
        retired.title = legacyStale ? t1detail : '';
      }
      // Everything else here is done by the CLASS, not by touching nodes. A first attempt
      // set `hidden`, cleared the summary text and rewrote the source note; all three came
      // back, because the decision renderer runs after this and rewrites the same nodes. A
      // rule keyed on the section's class cannot be undone by a later render, which is the
      // difference between a guard and a race. The heading's qualifier is a CSS `::after` for
      // the same reason, and the source note is left alone: the date it prints is the truth.
    }

    // Stage 5ZZH. In Track 1 mode the big number is Track 1's, or it is nothing.
    //
    // For three days this card read `$50,408  +408  since base $50,000`. Every part of that
    // was legacy: the equity from the legacy runner's last snapshot, dated 2026-08-24; the
    // base from its own `meta.account`. Meanwhile the account this route would actually start
    // from held USD 250,818, proven against the broker that morning — and appeared only as
    // small print underneath. The largest figure on the page was the least current one.
    //
    // The rule, and the reason for each half:
    //   the baseline is usable  -> it is the headline, WITH its currency spelled out, because
    //                              this page has already shown one figure whose currency was
    //                              a guess
    //   it is not usable        -> say which, and STOP. Falling back to the legacy figure is
    //                              what produced the confusion in the first place, and a
    //                              fallback that fires silently is worse than a blank.
    const t1acct = state.track1?.paper_account || null;
    // Stage 5ZZH. A field the backend does not serve is NOT a field the backend said no to.
    //
    // The endpoint imports its reader inside the view function, which looks like it picks up
    // a code change per request — but Python caches the module, so a backend started before
    // this stage keeps serving the old block forever. Measured against the running process:
    // `headline_usable` came back null on an account whose status was PASS. Read as false,
    // that renders a funded, reconciled account as "baseline FAIL" — a worse lie than the one
    // this stage set out to fix, and it would appear the moment the page shipped ahead of a
    // restart. So: ABSENT means derive it here from what the old block does carry; FALSE
    // means the backend decided, and its decision stands.
    const declared = t1acct && t1acct.headline_usable !== undefined
                             && t1acct.headline_usable !== null;
    const t1Headline = Boolean(t1acct && Number.isFinite(Number(t1acct.equity))
      && (declared ? t1acct.headline_usable
                   : ['PASS', 'WARN'].includes(t1acct.status)));
    const money0 = n => Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });

    if (t1Headline) {
      setMetric('metricEquity', `${esc(t1acct.currency || '')} ${money0(t1acct.equity)}`.trim());
    } else if (t1acct) {
      // Named refusal, not a blank and not somebody else's number.
      setMetric('metricEquity', t1acct.status === 'UNKNOWN' || !t1acct.status
        ? 'not measured' : `baseline ${esc(t1acct.status)}`);
    } else {
      setMetric('metricEquity', equity == null ? '--' : `$${Number(equity).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`);
    }
    /* Bậc 30px của thang chữ được hợp đồng dành cho "số paper equity" — một CON SỐ.
       Khi không có số, ô này giữ một lời từ chối có tên ("not measured", "baseline
       UNKNOWN"), và lời từ chối ấy là đúng: không để trống, không mượn số của tuyến khác.
       Nhưng đo được 2026-09-04, nó trở thành CHỮ TO NHẤT TOÀN TRANG — 30px cho một sự
       vắng mặt, trong khi câu trả lời "hệ thống có khoẻ không" là 15px và dòng
       "ORDERS POSSIBLE: no" là 11px. Hệ thống phân cấp đang tiêu hai chỗ đắt nhất cho một
       giá trị vắng mặt và một số không.
       Nhận diện theo NỘI DUNG chứ không theo nhánh nào vừa chạy: có chữ số thì là con số,
       không có thì là câu — nên thêm một nhánh mới cũng không cần sửa chỗ này. */
    const eqEl = $('metricEquity');
    if (eqEl) eqEl.classList.toggle('is-refusal', !/\d/.test(eqEl.textContent || ''));
    // Realised P&L belongs to whoever traded. In Track 1 mode that is nobody — the route has
    // sent no orders — so the legacy runner's realised figure must not sit beside a Track 1
    // headline wearing the same styling as if it were this route's day.
    setMetric('metricRealized', t1acct ? '--' : money(realized), t1acct ? null : realized);
    setMetric('metricUnrealized', money(unreal), unreal);
    $('metricDrawdown').textContent = Number.isFinite(drawdown) ? pct(drawdown) : '--';
    $('metricDrawdownAmount').textContent = Number.isFinite(drawdownDollars)
      ? `$${Math.abs(drawdownDollars).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--';
    $('metricDrawdownLimit').textContent = Number.isFinite(hardDrawdown)
      ? `${gaugePct.toFixed(1)}% of ${pct(hardDrawdown)} hard limit` : 'hard limit unavailable';
    // Sự vắng mặt phải có TÊN. `--` cạnh một thanh đo bằng 0 vẫn đọc như "trong hạn".
    //
    // NHÃN NGẮN, LÝ DO ĐẦY ĐỦ Ở TOOLTIP. Bản đầu đổ nguyên câu giải thích vào ô nhãn và đo
    // được nó tràn 231–462px sang ô Performance ở cả ba bề rộng — đúng cái lỗi mà bản sửa
    // ngay phía trên vừa dọn cho thẻ Paper equity, tôi lặp lại nó ở thẻ bên cạnh trong cùng
    // một lượt. Ô này là NHÃN: bản thiết kế dành cho nó chuỗi `of 15.00% limit`, 25 ký tự.
    if (t1mode) {
      const why = !t1book
        ? ['unavailable', 'book unavailable',
           "Track 1's own book did not answer, and the legacy figure is not substituted"
           + ' for it.']
        : !t1curve
          ? ['not traded', 'no equity booked yet',
             'Track 1 has booked no equity, so there is no curve to draw down from.'
             + ' A zero peak means undefined, not zero.']
          : [null, 'no published limit',
             "Measured against Track 1's own booked equity. This route publishes no"
             + ' drawdown limit, so there is no scale to gauge against.'];
      if (why[0]) $('metricDrawdown').textContent = why[0];
      $('metricDrawdownLimit').textContent = why[1];
      $('metricDrawdown').title = why[2];
      $('metricDrawdownLimit').title = why[2];
    } else {
      $('metricDrawdown').title = '';
      $('metricDrawdownLimit').title = '';
    }
    $('metricDrawdown').classList.toggle('is-refusal',
      !/\d/.test($('metricDrawdown').textContent || ''));
    $('metricDrawdownFill').style.width = `${gaugePct}%`;
    $('metricDrawdownFill').className = gaugePct >= 100 ? 'bad' : gaugePct >= 66 ? 'watch' : '';
    $('metricDrawdownFill').parentElement.setAttribute('aria-valuenow', gaugePct.toFixed(1));
    $('metricDrawdownFill').parentElement.setAttribute('aria-valuemin', '0');
    $('metricDrawdownFill').parentElement.setAttribute('aria-valuemax', '100');
    $('metricPositions').textContent = state.broker?.payload ? String(brokerPositions().length) : '--';
    $('metricStops').textContent = state.broker?.payload ? String(workingOrders().length) : '--';

    // Stage 5ZZZ-CG. Ô Gross được viết Ở ĐÂY, và trước đây không ai viết nó trên trang này.
    //
    // Người viết duy nhất của nó nằm trong lớp phủ giao diện của bản thiết kế lại, nên trên
    // `/realtime` ô này in `--` vĩnh viễn, còn trên `/realtime-next` nó đọc `cluster_exposure`
    // của ảnh chụp runner đã nghỉ hưu — 289,8 giờ tuổi, và khoá theo ĐÚNG TÊN ba sleeve của
    // Track 1: `global_nkd`, `roska4_stress`, `roska4_swing`, mỗi cái `gross_pct: 0.0`. Nên
    // nó in "0.0%" trông như đang báo cáo Track 1, và sẽ còn in thế mãi kể cả sau khi Track 1
    // bắt đầu giao dịch, vì ảnh chụp ấy đã đóng băng.
    //
    // Chuyển về đây vì `state.track1` sống ở đây, và vì chính file kia đã ghi lại bài học của
    // nó: hai nơi cùng viết một ô thì nơi chạy sau thắng, và không gì trên màn hình cho thấy
    // có xung đột.
    //
    // Phần trăm cần một mẫu số. Khi có vị thế mà sổ chưa ghi vốn nào, ô này in số ĐẾM chứ
    // không in phần trăm: một tỉ lệ chia cho không là một con số bịa.
    const grossEl = $('metricGrossExposure');
    if (grossEl) {
      const held = t1book && Array.isArray(t1book.positions) ? t1book.positions.length : null;
      if (!t1mode) {
        // Tuyến cũ còn sống: con số của nó là của chính nó. Nhánh này giữ lại đúng phép
        // tính mà lớp phủ giao diện từng làm, để bản sửa không lặng lẽ xoá một số đang đúng
        // — nó chỉ thôi được dùng khi tuyến ấy đã nghỉ.
        const byCluster = snapshot?.cluster_exposure;
        let total = 0, seen = 0;
        if (byCluster && typeof byCluster === 'object') {
          for (const entry of Object.values(byCluster)) {
            const g = Number(entry?.gross_pct);
            if (Number.isFinite(g)) { total += g; seen += 1; }
          }
        }
        grossEl.textContent = seen ? `${total.toFixed(1)}%` : '--';
        grossEl.title = seen ? "the legacy runner's own per-cluster figures" : '';
      } else if (held === null) {
        grossEl.textContent = 'n/a';
        grossEl.title = "Track 1's own book did not answer; the legacy figure is not"
          + ' substituted for it';
      } else if (!held) {
        grossEl.textContent = '0.0%';
        grossEl.title = 'Track 1 holds nothing, read from its own book';
      } else if (!t1curve) {
        grossEl.textContent = `${held} held`;
        grossEl.title = 'Track 1 holds positions but has booked no equity to express them as'
          + ' a percentage of';
      } else {
        let gross = 0;
        for (const pos of t1book.positions) {
          const v = Math.abs(Number(pos?.notional ?? pos?.market_value ?? NaN));
          if (Number.isFinite(v)) gross += v;
        }
        grossEl.textContent = gross ? `${(gross / t1equity * 100).toFixed(1)}%` : `${held} held`;
        grossEl.title = "against Track 1's own booked equity";
      }
    }

    const protection = brokerUsable() ? protectionSummary() : null;
    $('metricStopsCovered').textContent = protection == null ? '--'
      : protection.total === 0 ? 'no positions'
      : [`${protection.covered} covered`,
         protection.deferred ? `${protection.deferred} deferred` : null,
         protection.naked ? `${protection.naked} naked` : null].filter(Boolean).join(' / ');
    const running = snapshot?.running_metrics || {};
    const sampleDays = runnerDead ? 0 : (state.runner?.payload?.snapshots || []).length;
    const enoughSample = sampleDays >= MIN_METRIC_DAYS;
    const sampleNote = `n=${sampleDays} trading day(s); needs ${MIN_METRIC_DAYS}`;
    const performanceValue = (id, value, numeric = null) => {
      const element = $(id);
      element.textContent = value;
      element.classList.remove('positive', 'negative');
      if (numeric != null && Number.isFinite(Number(numeric)) && Number(numeric) !== 0) {
        element.classList.add(Number(numeric) > 0 ? 'positive' : 'negative');
      }
    };
    if (t1acct) {
      // Stage 5ZZH. What this route funded to, and NOT a profit.
      //
      // The tempting line here is `+818 since 250,000`, and it would be read as Track 1
      // making money. Track 1 has sent no orders; the difference is whatever the paper
      // account happened to hold when it was funded. A number that will be misread as P&L is
      // not improved by being arithmetically correct, so the slot says why it is empty.
      $('performanceScope').textContent = t1Headline
        ? `baseline ${t1acct.status}${t1acct.age_hours != null ? ` · read ${t1acct.age_hours}h ago` : ''}`
        : (t1acct.headline_reason || '');
      performanceValue('performanceBase', t1Headline && t1acct.expected_equity != null
        ? `${esc(t1acct.expected_currency || '')} ${money0(t1acct.expected_equity)}`.trim() : '--');
      performanceValue('performanceNet', '--');
      $('performanceNet').title = 'Track 1 has sent no orders, so this route has no realised P&L. '
        + 'The gap between the account and its funded baseline is not profit.';
      performanceValue('performanceReturn', '--');
    } else {
      $('performanceScope').textContent = meta.system_epoch
        ? `since ${sessionDate(meta.system_epoch)}` : '';
      performanceValue('performanceBase', meta.account == null ? '--' : `$${Number(meta.account).toLocaleString('en-US', { maximumFractionDigits: 0 })}`);
      performanceValue('performanceNet', money(meta.net_pnl), meta.net_pnl);
    }
    performanceValue('performanceCalmar', enoughSample && running.calmar != null ? Number(running.calmar).toFixed(2) : '--');
    performanceValue('performanceSharpe', enoughSample && running.sharpe != null ? Number(running.sharpe).toFixed(2) : '--', enoughSample ? running.sharpe : null);
    // Stage 5ZZZ-CG. `n=11 trading day(s); needs 20` đếm ngày của RUNNER CŨ. Ở chế độ Track 1
    // câu đó trả lời một câu hỏi không ai hỏi: vấn đề không phải mẫu còn ngắn, mà là tuyến
    // này chưa có đường cong vốn nào để lấy mẫu. (Ảnh chụp ấy còn giữ Sharpe 8.52 trên 11
    // ngày với tổng lợi nhuận +0,8% — cổng cỡ mẫu đang giữ đúng một con số vô nghĩa.)
    const perfNote = t1mode
      ? 'Track 1 has sent no orders, so it has no equity curve to measure a ratio on'
      : sampleNote;
    $('performanceCalmar').title = (t1mode || !enoughSample) ? perfNote : '';
    $('performanceSharpe').title = (t1mode || !enoughSample) ? perfNote : '';
    if (t1mode) {
      performanceValue('performanceCalmar', '--');
      performanceValue('performanceSharpe', '--');
    }
    // Stage 5ZZH. Guarded: without the branch this line runs AFTER the Track 1 block above
    // and puts the legacy runner's return straight back onto a Track 1 card. The bug the
    // whole stage is about, one assignment further down the same function.
    if (!t1acct) {
      performanceValue('performanceReturn', running.total_return == null ? '--' : `${Number(running.total_return) >= 0 ? '+' : ''}${pct(running.total_return)}`, running.total_return);
    }
    performanceValue('performanceMaxDd',
      t1mode || meta.max_dd_pct == null ? '--' : pct(meta.max_dd_pct),
      t1mode || meta.max_dd_pct == null ? null : -Number(meta.max_dd_pct));
    $('performanceMaxDd').title = t1mode ? perfNote : '';
    // Stage 5ZZF. This line said "Broker acct $996,731 / -$3,749 since 2026-07-08" for three
    // days after the paper account was reset to USD 250,817.91. Two separate faults, both
    // measured before this was rewritten:
    //
    //   1. THE SUBTRACTION CROSSED A CURRENCY BOUNDARY. `meta.paper_start` carries its own
    //      note — "connect_test_paper.py, DUR125337, CAD" — and `meta.broker_equity` carries
    //      no currency at all. The difference between them was rendered with a dollar sign on
    //      a page where every other money figure is USD, for an account that now holds USD.
    //   2. IT WAS 76.8 HOURS OLD AND THE PAGE COULD NOT TELL. The runner-state envelope
    //      reported `freshness: not_expected_yet`, not `stale`, because in track1-only mode
    //      the legacy runner is never scheduled — so `expected_next_at` keeps sliding forward
    //      and nothing ever calls the payload old. A freshness model that assumes its producer
    //      still runs cannot report a producer that has stopped.
    //
    // So the account this route actually starts from is read from the place that proves it,
    // and the legacy figure is shown as what it is: a runner's last view, with its age.
    const acct = state.track1?.paper_account || null;
    const brokerNow = Number(state.broker?.payload?.equity);
    const brokerFresh = brokerUsable();
    const legacyEquity = Number(meta.broker_equity);
    const legacyAgeS = Number(state.runner?.age_seconds);
    const el = $('brokerAccountContext');

    let text = '', tone = '';
    if (acct && Number.isFinite(Number(acct.equity))) {
      // The baseline, from the record that proves it against the broker.
      text = `Paper account ${acct.currency || ''} ${Number(acct.equity).toLocaleString('en-US',
        { maximumFractionDigits: 0 })} · baseline ${esc(acct.status || '')}`;
      if (acct.status !== 'PASS') tone = 'negative';
      // A fresh broker read is a different fact from the baseline and is allowed to differ by
      // live drift. Labelled, never merged into the number above.
      if (brokerFresh && Number.isFinite(brokerNow)) {
        text += ` · broker now ${brokerNow.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
      }
      // The defensive part: if the legacy runner's last view is materially different, say so
      // rather than letting two numbers sit on one page with nothing between them.
      if (Number.isFinite(legacyEquity) && Number(acct.equity) > 0
          && Math.abs(legacyEquity - Number(acct.equity)) / Number(acct.equity) > 0.10) {
        text += ` · Legacy runner state ${legacyStale ? 'stale: ' : ''}${legacyEquity.toLocaleString('en-US',
          { maximumFractionDigits: 0 })} from ${age(legacyAgeS)}`;
        tone = 'negative';
      }
    } else if (brokerFresh && Number.isFinite(brokerNow)) {
      text = `Broker now ${brokerNow.toLocaleString('en-US', { maximumFractionDigits: 0 })} · `
           + `no paper baseline recorded`;
      tone = 'negative';
    } else if (Number.isFinite(legacyEquity)) {
      // Nothing current to show. The legacy number may appear ONLY under its own name and
      // only with its age attached — never as "Broker acct".
      text = `Legacy runner state ${legacyEquity.toLocaleString('en-US',
        { maximumFractionDigits: 0 })} from ${age(legacyAgeS)} · not the current account`;
      tone = 'negative';
    } else {
      text = 'Paper account not measured';
      tone = 'negative';
    }
    el.textContent = text;
    el.className = tone;
  }

  function runnerFreshnessText(freshness, nextAt, ageSeconds) {
    if (freshness === 'fresh') return `Current · updated ${age(ageSeconds)}`;
    if (freshness === 'stale') return `Stale · last published ${age(ageSeconds)}`;
    if (freshness === 'not_expected_yet') return `On schedule · next ${etClock(nextAt)}`;
    if (freshness === 'late') return `Late · due ${etClock(nextAt)}`;
    if (freshness === 'missing') return 'No snapshot available';
    return `Timing unknown · last seen ${age(ageSeconds)}`;
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

  // Giờ trần đủ dùng khi mọi thứ trong cùng một ngày, và gây hiểu nhầm khi không.
  // Tối thứ Sáu, "NEXT JOB 00:20 ET" đọc như còn vài tiếng, thực ra là thứ Hai —
  // cách 46 tiếng. Chỉ thêm ngày khi nó KHÁC hôm nay, để dòng thường ngày không dài ra.
  const etClockWithDay = iso => {
    if (!iso) return '--';
    const when = new Date(iso);
    const dayOf = value => new Intl.DateTimeFormat('en-CA', { timeZone: ET_ZONE }).format(value);
    if (dayOf(when) === dayOf(new Date())) return etClock(iso);
    const label = new Intl.DateTimeFormat('en-US', { timeZone: ET_ZONE, weekday: 'short' }).format(when);
    return `${label} ${etClock(iso)}`;
  };

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
      <span>${esc(label)}</span><div><b>${esc(job ? job.job_id : 'Not observed')}</b><time>${esc(etClockWithDay(at))}</time></div>
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
    const stripUnprotected = stripBrokerKnown ? brokerPositions().filter(position =>
      !stopsFor(position).length
      && runnersFor(position).length
      && !runnersFor(position).some(runner => runner.stop_deferred)) : [];
    const stripInvalidStops = stripBrokerKnown
      ? brokerPositions().reduce((count, position) => count + invalidStopsFor(position).length, 0) : 0;
    const stripUnknownStops = stripBrokerKnown
      ? brokerPositions().reduce((count, position) => count + unknownStopsFor(position).length, 0) : 0;
    const stripMatched = stripBrokerKnown ? brokerPositions().filter(runnerFor).length : 0;
    const stripSizeProblem = stripBrokerKnown && brokerPositions().some(position => {
      const quantity = expectedQuantity(position);
      return runnersFor(position).length && quantity !== Math.abs(Number(position.position));
    });
    const stripFreshness = state.runner?.freshness || 'missing';
    // Open incidents only. A slot that failed while IB Gateway was restarting, with the
    // stream running cleanly since, belongs in the day's record — not in a banner that
    // still says "attention required" six hours later. An alarm that never clears is one
    // the operator stops reading.
    // Stage 5ZF. `missing` and `stale` no longer raise the rail when the legacy runner is
    // inactive by design. In track1-only shadow nothing writes the legacy state file, so its
    // absence and its age are both expected — and a rail that reads "attention required" for
    // an entire shadow period is a rail nobody reads by the time something real happens.
    // The fact itself is not hidden: it is shown as its own line below.
    const legacyInactive = stripSchedule?.legacy_runner?.inactive_by_design === true;
    // Stage 5ZZW. Which mode the SCHEDULER is in, and whether that could be read at all.
    //
    // The suppression above was built in Stage 5ZF and was correct; it simply never fired,
    // because the backend answered `legacy` while the scheduler was running track1-only. The
    // backend now resolves the mode from the scheduler's own command line and says so here.
    // `routeModeKnown === false` is the third answer: nobody could look. It must not read as
    // a fault, and it must not read as legacy either.
    const routeModeKnown = stripSchedule?.route_mode_known !== false;
    const trackOnly = stripSchedule?.route_mode === 'track1_only_shadow';
    // A legacy snapshot that is stale BY DESIGN is not this route's health. It is reported as
    // its own line below, in words, rather than as a page-level alarm nobody can clear.
    const legacyStaleByDesign = legacyInactive
      && stripSchedule?.legacy_runner?.state_stale === true;
    const stripScheduleBad = routeModeKnown && ((stripSchedule?.open_incidents ?? stripSchedule?.incidents ?? []).length > 0
      || (stripSchedule?.unexplained_overdue || []).length > 0
      || stripFreshness === 'late'
      || (stripFreshness === 'stale' && !legacyInactive)
      || (stripFreshness === 'missing' && !legacyInactive)
      || stripEvidence?.severity === 'incident');
    const stripSafetyCount = stripOrphans.length + stripUnprotected.length + stripInvalidStops + stripUnknownStops;
    const stripReconcileBad = stripBrokerKnown
      && (runnerOnly().length || stripMatched !== brokerPositions().length || stripSizeProblem);
    const stripBreaker = stripOps.breaker?.level || snap?.breaker_level;
    const stripBreakerBad = stripBreaker && stripBreaker !== 'OK';
    // Runner phát cờ này khi HMM stale guard G1 HARD bật (SPY cũ quá 5 ngày làm
    // việc) và nó CHẶN MỌI ENTRY, exit vẫn chạy. Trước đây frontend không đọc nó ở
    // đâu cả: trang hiện độ tươi SPY nhưng im lặng về hệ quả — hệ thống đã ngừng
    // vào lệnh mà màn hình vẫn nói nominal.
    const stripEntriesBlocked = Boolean(stripOps.regime_unreliable);
    const stripUnknown = !stripSchedule?.evidence_available || !stripBrokerKnown;
    const stripDeadSources = [
      ['runner-state', state.runner?.error],
      ['broker', state.broker?.error],
      ['schedule', state.schedule?.error],
      ['open-issues', state.openIssues?.error],
      ['runner-positions', state.runnerPositions?.error]
    ].filter(([, error]) => error).map(([name]) => name);
    const stripLevel = stripScheduleBad || stripSafetyCount || stripReconcileBad || stripBreakerBad
      || stripEntriesBlocked || stripDeadSources.length
      ? 'bad' : stripUnknown ? 'watch' : 'ok';
    const stripConditions = [];
    if (!routeModeKnown) stripConditions.push('scheduler mode unknown — could not read the scheduler');
    if (stripScheduleBad) stripConditions.push(trackOnly ? 'Track 1 scheduler needs attention'
      : 'scheduler attention required');
    // Gọi tên riêng: "scheduler attention required" không nói được rằng CHÍNH snapshot
    // runner đã cũ — mà mọi con số runner-derived trên trang đều đến từ nó.
    // Stage 5ZZW. The same fact, said two different ways depending on whether it means
    // anything. When legacy is retired its snapshot is stale because nothing writes it any
    // more, and calling that "runner state stale" put a fault-shaped line on the rail for a
    // condition that is the intended steady state.
    if (legacyStaleByDesign) {
      stripConditions.push('Legacy runner snapshot is stale because legacy entries are retired');
    } else if (['stale', 'late', 'missing'].includes(stripFreshness)) {
      stripConditions.push(`runner state ${stripFreshness} (${age(state.runner?.age_seconds)})`);
    }
    if (!stripBrokerKnown) stripConditions.push('broker feed cannot be verified');
    if (stripSafetyCount) stripConditions.push(`${stripSafetyCount} protection issue(s)`);
    if (stripReconcileBad) stripConditions.push('position reconcile needs attention');
    if (stripBreakerBad) stripConditions.push(`risk breaker ${stripBreaker}`);
    if (stripEntriesBlocked) stripConditions.push('entries blocked: regime input unreliable');
    if (stripDeadSources.length) stripConditions.push(`${stripDeadSources.join(', ')} unreachable`);
    /* Sự thật vận hành lớn nhất của trang, và nó vốn nằm ở 11px cách đầu trang 400px:
       tuyến CÓ đặt được lệnh hay không, và cổng nào đang chặn. Một bản rà độc lập đọc
       trang này bằng mắt mới gọi đây là việc số một, và phép đo đồng ý — năm thứ to nhất
       trong màn hình đầu đều là TÊN KHUNG CHỨA, không cái nào là trạng thái.
       Chỉ thêm dòng khi câu trả lời là KHÔNG. Ngày bình thường dải đầu giữ nguyên sự tiết
       chế mà bản thiết kế cố ý để lại; ngày không đặt được lệnh thì người đọc biết ngay
       ở dòng đầu tiên thay vì phải cuộn.
       Tên cổng lấy qua `GATE_NAMES` — cùng bảng dịch mà panel Track 1 dùng, để hai chỗ
       không thể gọi một cổng bằng hai tên. */
    const stripGates = state.track1?.gates || {};
    if (stripGates.orders_possible === false) {
      const names = (stripGates.blocking_now || []).map(id => GATE_NAMES[id] || id);
      stripConditions.push(
        'no orders possible' + (names.length ? ` — ${names.slice(0, 3).join(' · ')}` : ''));
    }
    if (!stripConditions.length && stripUnknown) stripConditions.push('some telemetry is unavailable');
    const stripStatus = stripConditions.length
      ? stripConditions.join(' / ')
      : `systems nominal: feeds live, ${brokerPositions().length ? 'positions protected' : 'no open positions'}`;
    // Stage 5ZZW. The count an operator reads at the top of the page is the ACTIVE one: it
    // leaves out issues that read only legacy artefacts, and only once the backend has
    // measured that legacy is actually retired on this login. Nothing is deleted — the
    // remainder is grouped under a retired history below, with its own count.
    const stripIssueCount = state.openIssues?.active_count
      ?? (state.openIssues?.issues?.length || 0);
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
      <span class="fact-scheduler has-tip tip-right ${!routeModeKnown ? 'watch' : stripScheduleBad ? 'bad' : stripSchedule?.evidence_available ? 'ok' : 'watch'}" tabindex="0" data-tooltip="ON SCHEDULE means scheduler evidence is available, no due slot is unresolved, and runner state is not late. It does not describe model or trading health."><i class="scheduler-live-dot"></i><small>${esc(trackOnly ? 'Track 1 scheduler' : 'Scheduler')}</small><b>${esc(!routeModeKnown ? 'unknown' : stripScheduleBad ? 'attention' : stripSchedule?.evidence_available ? 'on schedule' : 'unknown')}</b></span>`;
  }

  function renderMonitor(snap) {
    const incidents = [];
    const gaps = [];
    const schedule = state.schedule;
    const monitorOps = state.runner?.payload?.meta?.operational_status || snap?.operational_status || {};
    // Guard chặn entry là điều kiện vận hành, không phải chỉ số đầu vào. Độ tươi
    // SPY đã hiện ở header từ trước, nhưng người vận hành cần biết HỆ QUẢ: hệ
    // thống đã ngừng vào lệnh, và exit thì vẫn chạy.
    if (monitorOps.regime_unreliable) incidents.push({
      key: 'runner:entries-blocked',
      status: 'incident', component: 'runner', title: 'Entries blocked: regime input unreliable',
      problem: `The HMM stale guard is hard-tripped, so the runner is refusing every new entry.${
        monitorOps.regime_freshness?.bday_stale != null
          ? ` SPY input is ${monitorOps.regime_freshness.bday_stale} business day(s) stale.` : ''}`,
      impact: 'No new position will be opened while this holds. Exits still run, so open positions continue to be managed.',
      action: 'Refresh the SPY regime input, then confirm the next runner slot clears the guard.',
      evidence: `regime_unreliable=true${
        monitorOps.regime_freshness?.last_spy_date ? ` / last SPY ${monitorOps.regime_freshness.last_spy_date}` : ''}`
    });
    const openConnectivity = (state.sessionEvents?.events || []).filter(event =>
      event.kind === 'connectivity_outage' && event.status === 'open');
    const openReconcile = (state.sessionEvents?.events || []).filter(event =>
      event.kind === 'broker_reconcile_incident' && event.status === 'open');
    // Hai vòng dưới từng bị bọc trong `if ($('schedulerHealth'))`. Element đó đã bị xóa
    // khỏi index.html khi rail được rút gọn, và JS không dọn theo — nên hai alarm quan
    // trọng nhất của trang (mất kết nối IBKR, lệch position broker/runner) im lặng
    // vĩnh viễn. Không có điều kiện nào ở đây là đúng: chúng phải luôn được xét.
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

    (schedule?.open_incidents ?? schedule?.incidents ?? []).forEach(item => incidents.push({
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
        if (runnersFor(pos).length && !runnersFor(pos).some(item => item.stop_deferred) && !stopsFor(pos).length) incidents.push({
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
        const expectedQty = expectedQuantity(pos);
        if (expectedQty != null && expectedQty !== Math.abs(Number(pos.position))) incidents.push({
          key: `broker:size:${pos.inst}`, status: 'incident', component: 'broker', title: `${pos.inst} size mismatch`,
          problem: `IBKR holds x${Math.abs(Number(pos.position))}, while runner intent totals x${expectedQty} across ${runnersFor(pos).length} cluster(s).`,
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

    // The runner-only check above reads live_positions.json. If that file cannot be
    // read the check finds nothing and stays quiet, which is indistinguishable from
    // "the runner holds nothing" — the one reading that is certainly unearned. Say so
    // instead, the same way every other missing input is reported here.
    if (!persistedUsable()) gaps.push({ key: 'gap:runner-positions', status: 'unknown', component: 'runner', title: 'Persisted runner positions unreadable', problem: 'live_positions.json could not be read, so what the runner currently holds is unknown.', impact: 'A position the runner holds but the broker does not would not be reported; silence here is not evidence of agreement.', action: 'Restore the position file before treating broker/runner agreement as checked.', evidence: state.runnerPositions?.error || 'runner-positions payload missing' });

    if (!state.schedule?.evidence_available) gaps.push({ key: 'gap:scheduler', status: 'unknown', component: 'scheduler', title: 'Scheduler evidence unavailable', problem: 'The monitor cannot read enough scheduler evidence to classify expected slots.', impact: 'A missing or failed job cannot be distinguished from absent telemetry.', action: 'Restore scheduler log visibility; do not infer that scheduled jobs succeeded.', evidence: state.schedule?.error || 'schedule evidence unavailable' });
    if (!state.runner || state.runner.freshness === 'missing' || state.runner.freshness === 'unknown') gaps.push({ key: 'gap:runner', status: 'unknown', component: 'runner', title: 'Runner state unknown', problem: 'The latest runner observation cannot be classified as fresh or expected.', impact: 'Runner-derived decisions and intent cannot be treated as current.', action: 'Check runner-state publication and schedule evidence before drawing conclusions.', evidence: state.runner?.error || state.runner?.freshness || 'runner source missing' });
    if (Number(state.runner?.event_history?.malformed_lines || 0) > 0) gaps.push({ key: 'gap:runner-event-log', status: 'unknown', component: 'runner', title: 'Runner event log has an invalid record', problem: 'The append-only JSONL contains one or more malformed records that the monitor cannot parse.', impact: 'Runner event history is incomplete from the malformed record onward; trading state is unaffected.', action: 'Preserve the file for diagnosis and repair or archive the incomplete tail before the next runner slot.', evidence: `${state.runner.event_history.malformed_lines} malformed record(s) / ${state.runner.event_history.error || 'parse failure'}` });
    // Trước đây gap này bị nén khi có TWS outage đang mở, với lý do "đã có incident riêng
    // rồi". Lý do đó chỉ đúng nếu incident kia thực sự được push — điều đã sai suốt thời
    // gian khối trên nằm trong nhánh chết. Nén dựa trên incident CÓ THẬT trong mảng, không
    // dựa trên một cờ suy diễn.
    const connectivityIncidentShown = incidents.some(item => String(item.key).startsWith('broker:connectivity:'));
    if (!brokerUsable() && !connectivityIncidentShown) gaps.push({ key: 'gap:broker', status: 'unknown', component: 'broker', title: 'Broker truth unavailable', problem: 'The read-only IBKR observation is disconnected, stale, or unavailable.', impact: 'Current positions, working stops, and reconciliation cannot be verified.', action: 'Restore the read-only IBKR connection; do not reconstruct broker truth from runner state.', evidence: state.broker?.error || `broker freshness ${state.broker?.freshness || 'unknown'}` });
    if (brokerUsable()) brokerPositions().forEach(pos => {
      if (!runnerFor(pos)) return;
      const runner = runnerFor(pos);
      if (runner.stop_deferred === undefined && !stopsFor(pos).length) gaps.push({ key: `gap:deferred:${pos.inst}`, status: 'unknown', component: 'runner', title: `${pos.inst} stop state unknown`, problem: 'Runner state does not say whether missing protection is deferred or unexpected.', impact: 'The monitor cannot safely classify the position as protected or unprotected.', action: 'Treat protection state as unknown until runner evidence or a broker stop appears.', evidence: `${pos.inst} / no stop / deferred field not emitted` });
      unknownStopsFor(pos).forEach(order => gaps.push({ key: `gap:stop:${order.order_id}`, status: 'unknown', component: 'broker', title: `${order.inst} stop evidence incomplete`, problem: `Broker stop #${order.order_id ?? '--'} is missing action, quantity, or status fields.`, impact: 'The order cannot be validated as position protection.', action: 'Verify the order directly in IBKR before relying on it.', evidence: `${order.inst} #${order.order_id ?? '--'} / ${order.action || '--'} / x${order.qty ?? '--'} / ${order.status || '--'}` }));
      if (expectedQuantity(pos) == null) gaps.push({ key: `gap:size:${pos.inst}`, status: 'unknown', component: 'runner', title: `${pos.inst} runner quantity missing`, problem: 'Runner state does not emit contract quantity for this position.', impact: 'The monitor can reconcile symbol and side, but not position size.', action: 'Keep size reconciliation unknown; do not infer quantity from another field.', evidence: `${pos.inst} broker x${Math.abs(Number(pos.position))} / runner quantity absent` });
    });

    // Slot đã phục hồi không còn là báo động — đó là lý do chúng rời khỏi lane
    // incident. Nhưng "sáu slot quyết định mất trong đêm" vẫn là một sự thật về
    // đêm đó: mọi tín hiệu đáng lẽ fire trong cửa sổ ấy đều không có cơ hội.
    // Trước dòng này, sự thật ấy chỉ còn tồn tại dưới dạng vài dòng lẫn trong
    // hàng chục dòng Job Journal, không đếm được ở đâu.
    const streamLabel = stream => stream === 'NKD_NIGHT' ? 'NKD' : stream === 'LIVE_DAY' ? 'US' : stream.replaceAll('_', ' ');
    const recoveredGroups = new Map();
    (schedule?.incidents || []).filter(item => item.lifecycle === 'recovered').forEach(item => {
      const stream = String(item.slot_id || '').replace(/_\d+$/, '');
      if (!recoveredGroups.has(stream)) recoveredGroups.set(stream, []);
      recoveredGroups.get(stream).push(item);
    });
    const recoveredSlotCount = [...recoveredGroups.values()].reduce((total, slots) => total + slots.length, 0);
    const recovered = [...recoveredGroups.entries()].map(([stream, slots]) => {
      const sorted = [...slots].sort((a, b) => String(a.slot_at).localeCompare(String(b.slot_at)));
      const first = sorted[0];
      const last = sorted[sorted.length - 1];
      const by = sorted.map(slot => slot.recovered_by).find(Boolean);
      return {
        key: `recovered:${stream}:${first.slot_at}`,
        status: 'recovered', component: 'scheduler',
        title: `${sorted.length} ${streamLabel(stream)} decision slot${sorted.length === 1 ? '' : 's'} lost`,
        problem: `${first.slot_id}${sorted.length > 1 ? ` through ${last.slot_id}` : ''} did not run: ${first.reason || first.state}.`,
        impact: 'Any entry signal due inside that window never had a chance to fire. The stream itself is healthy again, so this is a record of the night, not a live alarm.',
        action: by
          ? 'No action now. Review power, network, or IB Gateway restart timing if the same window fails again.'
          : 'Confirm the stream is running before the next scheduled slot.',
        evidence: `${sorted.length} slot(s) ${etClock(first.slot_at)}–${etClock(last.slot_at)}${by ? ` / recovered by ${by}` : ''}`
      };
    });

    // Bucket thứ tư: debt đã biết. Nó phải hiện ra nhưng KHÔNG được kêu như sự cố
    // mới — cùng cách đối xử với model age. Re-freeze thất bại nghĩa là model cũ
    // vẫn đang dùng và giao dịch vẫn chạy; runner đã re-alert mỗi lần chạy rồi.
    const debts = [];
    if (monitorOps.refreeze?.pending) debts.push({
      key: 'runner:refreeze-pending',
      status: 'known_debt', component: 'runner', title: 'Model re-freeze still pending',
      problem: `A re-freeze attempt did not complete${
        monitorOps.refreeze.fail_type ? ` (${monitorOps.refreeze.fail_type})` : ''}, so the previously frozen model is still in use.`,
      impact: 'Trading continues on the older model. This is debt, not a halt — no entry is blocked by it.',
      action: 'Complete the re-freeze out of band; the runner re-alerts on every slot until the pending flag clears.',
      evidence: `refreeze.pending=true${
        monitorOps.refreeze.attempts != null ? ` / ${monitorOps.refreeze.attempts} attempt(s)` : ''}`
    });

    const items = [...incidents, ...gaps, ...recovered, ...debts];
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
    incidentSummary.textContent = `${incidents.length} incident / ${gaps.length} telemetry gap`
      + (recoveredSlotCount ? ` / ${recoveredSlotCount} slot(s) lost, recovered` : '')
      + (debts.length ? ` / ${debts.length} known debt` : '');
  }

  function monitorDetail(item, withHeader = false) {
    return `${withHeader ? `<div class="issue-detail-head"><div><span class="issue-origin ${esc(item.component)}">${esc(item.component)}</span><span class="issue-status">${esc(issueStatus(item.status))}</span><h3>${esc(item.title)}</h3></div></div>` : ''}
      <div class="issue-problem"><span>Problem</span><p>${esc(item.problem)}</p></div>
      <div class="issue-assessment"><div><span>Impact</span><p>${esc(item.impact)}</p></div><div><span>Action</span><p>${esc(item.action)}</p></div></div>
      <div class="issue-evidence"><span>Evidence</span><p>${esc(item.evidence)}</p></div>`;
  }

  function issueStatus(status) {
    return ({ incident: 'OPEN', known_debt: 'KNOWN DEBT', unknown: 'UNKNOWN', recovered: 'RECOVERED' })[status] || 'OPEN';
  }

  // Stage 5ZZF. Whose problem this is, as a chip in the badge lane that already exists — no new
  // section, no new card. Three legacy paper-reconciliation issues were sitting beside the
  // Track 1 panel with nothing to say they were about a different route, and a reader glancing
  // at the page had no way to tell them from Track 1's own blockers.
  function issueScope(scope) {
    // Stage 5ZZH. `scheduler` reads as a component, and this chip answers a different
    // question: WHOSE PROBLEM IS THIS. The scheduler and the contract calendar serve both
    // routes, so the honest word for that column is the one that says so.
    // Stage 5ZZW: `DEBT` said what KIND of entry it is; it did not say what it is about, and
    // the row sat under a heading that said "Legacy". It is a model fact.
    // Stage 5ZZZ-CM. `SHARED` không nói gì với người đọc — nó là từ của người viết mã, và
    // nghĩa thật ("bộ lập lịch và lịch hợp đồng phục vụ CẢ HAI tuyến") chỉ nằm trong tooltip.
    // Nhãn phải tự nói được nghĩa của nó khi không ai rê chuột.
    return ({ track1: 'TRACK 1', legacy: 'LEGACY', scheduler: 'BOTH ROUTES',
              known_debt: 'MODEL' })[scope] || '';
  }

  // Stage 5ZZH. Three groups, and every issue lands in exactly one of them.
  //
  // The chips alone were not enough. Five issues sat in one flat list beside the Track 1
  // panel, four of them about a route that is not this one, and an operator scanning down
  // the column had to read five tooltips to learn that none of them blocks Track 1. Grouping
  // answers that before the first click.
  //
  // Nothing is hidden and nothing is dropped: DEBT joins the legacy group rather than getting
  // a fourth heading, and an unrecognised scope falls into the shared group, where it is
  // visible, rather than vanishing from all three.
  const ISSUE_GROUPS = [
    { key: 'track1', label: 'Track 1',
      note: 'affects Track 1 paper readiness',
      has: sc => sc === 'track1' },
    { key: 'shared', label: 'Shared',
      note: 'the scheduler and the contract calendar serve both routes',
      has: sc => sc === 'scheduler' || !['track1', 'legacy', 'known_debt'].includes(sc) },
    // Stage 5ZZW. Carried debt gets its OWN group. It was sitting inside `Legacy`, which was
    // survivable while both were shown — and became a real hazard the moment the legacy group
    // stopped counting toward the active total, because the HMM model-age debt would have
    // gone quiet with it. It is a MODEL fact and applies to Track 1 whatever legacy is doing.
    { key: 'model', label: 'Model / Regime',
      note: 'carried model and regime debt — applies to Track 1 regardless of the legacy route',
      has: sc => sc === 'known_debt' },
    { key: 'legacy', label: 'Legacy / retired history',
      note: 'reads legacy artefacts only — does not block Track 1 paper readiness',
      has: sc => sc === 'legacy' }
  ];

  function groupIssues(issues) {
    return ISSUE_GROUPS
      .map(g => ({ ...g, items: issues.filter(i => g.has(String(i.route_scope || ''))) }))
      .filter(g => g.items.length);
  }

  // ══════════════════════════════════════════════════════════════════════════════════════
  // Stage 5ZZL — Track 1 Market View and Regime Monitor
  //
  // WHY THIS DRAWS ITS OWN CANDLES INSTEAD OF LOADING A CHART LIBRARY
  //
  // The stage asked for TradingView Lightweight Charts, and the first thing that had to be
  // measured was whether this repo can take a frontend dependency. It cannot, in the sense
  // that matters here:
  //
  //   there is no package.json, no node_modules and no build step anywhere in the tree
  //   this page loads exactly two scripts, both first-party
  //   the ONE page that uses an external library (chart-forward.html, Chart.js from a CDN)
  //     is also the one whose consumer guards `if (!window.Chart) return` and falls back to
  //     an inline SVG — the codebase already treats an external chart lib as optional
  //
  // Adding a CDN <script> to THIS page is a different proposition from adding it to a report
  // page: this is the page an operator watches a live trading route on, and a blocking script
  // tag against a third-party host is a dependency on that host being reachable at the moment
  // something is going wrong. Vendoring the library instead means committing a third-party
  // blob into a repo that currently has none, which is a supply-chain decision for the owner
  // rather than for this stage.
  //
  // So: first-party SVG, in the same style as the sparkline already in shared/live.js. The
  // tradeoff is real and is written down in the deliverable — crosshair, tooltip, price scale
  // and time axis are hand-drawn here rather than inherited, and this is ~200 lines that a
  // library would have provided. What it buys is a page with no third-party runtime on it.
  //
  // NOTHING here computes a strategy value. Bars, slot verdicts, levels and the regime label
  // all arrive from the backend already decided. Where the strategy publishes nothing — which
  // today is every price level — this says so instead of drawing a line.
  // ══════════════════════════════════════════════════════════════════════════════════════

  const MV_ORDER = ['global_nkd', 'roska4_stress', 'roska4_swing'];
  //: Marker colours, and each one names a distinct fact. `future` is hollow because a slot
  //: that has not fired is not a result, and `missed` is its own colour because a slot nobody
  //: recorded is not a slot that found nothing.
  const MV_MARK = {
    no_signal: { fill: 'var(--dim, #6a7284)', hollow: false, word: 'no signal' },
    signal:    { fill: 'var(--green, #3f9e6b)', hollow: false, word: 'signal' },
    rejected:  { fill: 'var(--red, #c64b4b)', hollow: false, word: 'rejected' },
    refused:   { fill: 'var(--amber, #c9a227)', hollow: false, word: 'refused' },
    missed:    { fill: 'var(--red, #c64b4b)', hollow: true, word: 'no record' },
    future:    { fill: 'var(--muted, #8a94a6)', hollow: true, word: 'not yet' },
    unknown:   { fill: 'var(--muted, #8a94a6)', hollow: true, word: 'unknown' }
  };

  // Stage 5ZZU. A job's name as an operator would say it, derived from its TYPE rather than
  // from the spelling of its id. `TRACK1_STOP_REPAIR_0620` is an identifier, not a label, and
  // it was appearing as the primary text on both the issue row and the journal row.
  //
  // The exact id is not thrown away — it goes in the tooltip, which is where an identifier
  // belongs. Anything this map does not know falls back to the id, so a job type added
  // tomorrow reads exactly as it does today rather than rendering blank.
  //
  // Scoped to the three job types THIS stage gives a type to, and no further. Every other row
  // keeps its id, because the id is how the operator view built in Stage 5ZE addresses a row:
  // relabelling the strategy slots broke five of its tests, and relabelling the legacy sweep
  // broke a sixth that finds a row by looking for STOP_REPAIR in its name. Renaming a taxonomy
  // is a design change of its own, and it was not what was asked for here.
  const MV_JOB_NAMES = {
    track1_safety_stop_repair: 'Track 1 stop-repair sweep',
    track1_safety_max_hold: 'Track 1 max-hold exit check',
    track1_window_audit: 'Track 1 window audit'
  };

  /* Tuyến của một job, SUY từ tiền tố loại chứ không viết cứng danh sách.
     Đo được 2026-09-04: bốn cặp job chạy cùng một phút — `STOP_REPAIR_0420` (12s) và
     `TRACK1_STOP_REPAIR_0420` (14s), rồi ba cặp nữa. Đó là HAI job thật của hai tuyến,
     không phải một job ghi hai lần; nhưng trên màn hình chúng đọc như bản sao, vì không
     dòng nào nói tuyến.
     55 trên 65 hàng đã mang tiền tố `TRACK1_` ngay trong job id nên tự nói được. Mười hàng
     legacy thì không, và đúng chúng là những hàng ghép đôi. Chỉ đánh dấu mười hàng ấy.
     KHÔNG đổi tên job: comment ở `renderScheduleFacts` đã dặn giữ nguyên job id của
     scheduler, vì "một từ vựng dashboard không tồn tại ở đâu khác trong hệ thống là một
     bước dịch dưới áp lực". Thêm một sự thật, không thay một cái tên. */
  /* Stage 5ZZZ-CV. Ô chip tuyến trên thẻ job đã được GỠ, có chủ đích.

     Nó ra đời khi hai tuyến còn chạy song song: các lượt quét bảo trì bắn theo cặp, cùng
     một phút, nên hai hàng cùng giờ đọc như một hàng ghi đôi nếu không có gì nói tuyến.

     Điều kiện ấy đã hết. Đo ngày 2026-09-06: 45 slot chiến lược của tuyến cũ KHÔNG còn được
     đăng ký ở chế độ chỉ-Track-1 — bỏ hẳn chứ không phải chỉ bị hãm — và cuốn sổ của tuyến
     cũ giữ 0 vị thế, không đổi từ 04/09. Không còn tuyến thứ hai để phân biệt với.

     Và cái việc chip từng làm thì nay tên job tự làm: hàng của tuyến cũ hiện tên thô
     `STOP_REPAIR_SUN_1830`, hàng Track 1 hiện "Track 1 stop-repair sweep 18:30". Hai tên đã
     tự nói, nên một ô nữa nói lại chỉ là một ô nữa để đọc.

     Dữ liệu thì GIỮ: bộ đọc nhật ký vẫn ghi tuyến của từng job vào payload, và một phép kiểm
     ghim nó vào chính danh sách bộ lập lịch bỏ đi. Bỏ một ô khỏi màn hình khác với bỏ một sự
     thật khỏi hồ sơ — nếu có ngày cần vẽ lại, con số đã nằm sẵn đó. */

  function jobLabel(job) {
    const base = MV_JOB_NAMES[job && job.job_type];
    if (!base) return String((job && job.job_id) || 'Unknown job');
    const at = /_(\d{2})(\d{2})$/.exec(String(job.job_id || ''));
    return at ? `${base} ${at[1]}:${at[2]}` : base;
  }

  function mvEsc(v) { return esc(v == null ? '' : String(v)); }

  //: A rule value for a panel. Small fractions read as percentages because that is
  //: how a gap is discussed; counts stay counts. No rounding that could change which
  //: side of a threshold a number appears to fall on.
  function mvNum(v) {
    if (v == null) return '--';
    const n = Number(v);
    if (!Number.isFinite(n)) return String(v);
    if (Number.isInteger(n)) return String(n);
    return Math.abs(n) < 0.1 ? `${(n * 100).toFixed(2)}%` : n.toFixed(2);
  }

  // Stage 5ZZM. Internal names, translated once, in one place.
  //
  // These strings travel from the route's own records straight into a marker tooltip or a
  // reason line. They are names for the code — a reader deciding whether to trust the panel
  // should not have to know that "splice" is what this project calls joining today's bars
  // onto history.
  const MV_WORDS = {
    splice_result: 'Data join', not_exposed_by_sleeve: 'Not published',
    provider_lag: 'Data delayed', gate_refused: 'Gate refused',
    nothing_new: 'No new bars', no_setup: 'No setup', decided: 'Decided',
    ok: 'OK', unknown: 'Unknown'
  };
  function mvPhrase(v) {
    const k = String(v == null ? '' : v).trim();
    if (!k) return '';
    if (MV_WORDS[k]) return MV_WORDS[k];
    // An unmapped internal token still reads better with its underscores gone than as a
    // variable name. Deliberately not hidden: a phrase nobody has translated yet should be
    // visible so somebody translates it, not swallowed into "unknown".
    return /^[a-z0-9_]+$/.test(k) ? k.replace(/_/g, ' ') : k;
  }

  // The status chip vocabulary, in precedence order. A data refusal outranks everything: if
  // the feed did not answer, what the slots did is a smaller fact than why.
  // Stage 5ZZZ-BX. Where the session IS, kept apart from what it FOUND.
  //
  // One chip was carrying two different questions and the second one won. Measured on the page
  // 2026-09-01 at 21:39 ET, all three sleeves finished:
  //
  //     NKD     NO SIGNAL   22/22 slots
  //     Stress  NO SIGNAL   24/24 slots
  //     Swing   NO SIGNAL   23/23 slots
  //
  // Nothing on the page said any of them had finished. `waiting` and `live` were visible
  // because no outcome exists yet at those moments; the instant a sleeve completed, the
  // outcome branch fired and the progress word was gone for the rest of the day. The slot
  // count implies it -- 22/22 -- but that is arithmetic the reader has to do, and it says
  // nothing on the day a window closes short.
  //
  // Progress first, because it changes what the outcome MEANS: "no signal" on a live sleeve is
  // an interim reading, and on a complete one it is the session's answer.
  function mvProgressChip(s) {
    const map = {
      waiting: { word: 'WAITING', tone: 'muted',
                 tip: 'The window has not opened yet, so nothing has been evaluated.' },
      live: { word: 'LIVE', tone: 'live',
              tip: 'Inside the window. Slots are still to come, so the reading below is interim.' },
      complete: { word: 'COMPLETE', tone: 'muted',
                  tip: 'The window closed and every scheduled slot was recorded.' },
      incomplete: { word: 'INCOMPLETE', tone: 'warn',
                    tip: 'The window closed with fewer slots recorded than were scheduled.' },
      refused: { word: 'REFUSED', tone: 'bad',
                 tip: 'Every slot in this window was refused before it could be evaluated.' },
      not_started: { word: 'NOT STARTED', tone: 'muted',
                     tip: 'The window has opened and no slot has been recorded yet.' },
      // Named on the WINDOW, because that is what is missing. Printing "unobserved" beside
      // "9/23 slots" reads as a contradiction -- nine of them plainly were observed.
      unobserved: { word: 'WINDOW NOT CLOSED', tone: 'warn',
                    tip: (s.coverage || {}).reason
                      || 'No window_closed record exists for this session, so the slot coverage '
                         + 'cannot be vouched for. Slots that did run are still shown.' }
    };
    return map[s.status] || { word: 'UNKNOWN', tone: 'warn',
                              tip: 'The route recorded a state this panel has no name for.' };
  }

  function mvStatusChip(s) {
    const d = s.data_status || {};
    const signals = (s.slots || []).filter(x => x.status === 'signal').length;
    // `outranks` puts this AHEAD of the progress chip. Stage 5ZZZ-BX split the two axes and
    // placed progress first unconditionally, which buried this one behind the word COMPLETE --
    // and a sleeve whose feed never answered is not meaningfully complete. The commit that
    // made the split claimed a data refusal still outranked both; the code did not do it, and
    // a DOM test written three stages earlier caught the difference.
    if (d.ok === false && d.provider_reason) {
      return { word: 'DATA REFUSED', tone: 'bad', outranks: true };
    }
    // Stage 5ZZZ-BX. The progress words moved to their own chip. What is left here answers one
    // question: what did the sleeve FIND. A sleeve with nothing decided yet has no answer, and
    // says nothing rather than borrowing the progress word back.
    if (s.status === 'waiting' || s.status === 'not_started') return null;
    if (signals) return { word: signals === 1 ? 'SIGNAL' : `${signals} SIGNALS`, tone: 'good' };
    // Stage 5ZZY. A slot the gate REJECTED is not "no signal": the sleeve produced a
    // candidate and something downstream refused it, which sends an operator somewhere
    // else entirely. This branch was missing, and it showed once the verdict line began
    // printing its own reason underneath the word — the pill read `NO SIGNAL · gate
    // refused at 02:25 ET`, contradicting itself in six words.
    const rejected = (s.slots || []).filter(x => x.status === 'rejected').length;
    if (rejected) {
      return { word: rejected === 1 ? 'REJECTED' : `${rejected} REJECTED`, tone: 'bad' };
    }
    if (s.status === 'refused') return null;      // the progress chip already says it
    if (s.status === 'incomplete' || s.status === 'unobserved') {
      // The window is short or unvouched; what the slots that DID run found is still a fact,
      // and the progress chip beside this one carries the caveat.
      const decided = (s.slots || []).filter(
        x => x.status === 'no_signal' || x.status === 'signal').length;
      return decided ? { word: 'NO SIGNAL', tone: 'muted' } : null;
    }
    if (s.status === 'complete') return { word: 'NO SIGNAL', tone: 'muted' };
    return null;                                   // the progress chip owns the unnamed case
  }

  function mvChip(word, tone, tip) {
    return `<span class="mv-chip${tone ? ' ' + tone : ''}${tip ? ' has-tip tip-bottom' : ''}"` +
           (tip ? ` tabindex="0" data-tooltip="${mvEsc(tip)}"` : '') +
           `>${mvEsc(word)}</span>`;
  }

  /* How this sleeve decides, in words. Hoisted out of mvChips because the verdict
     meta row now names the same thing: two copies of this table would be two copies
     to keep true, and the second one goes stale first. */
  const MV_BOUNDARY_WORD = {
    metric_boundary: 'Basket gate then price trigger',
    entry_after_setup_only: 'Entry after setup bar',
    price_boundary: 'Price trigger',
    two_phase: 'Two-phase decision'
  };

  function mvChips(s) {
    const out = [];
    // FIRST, before the status word, because it changes what the status word means. The panel
    // now anchors on the last TRADING day rather than on the calendar day, so on a Saturday,
    // a Sunday or a market holiday everything below describes a session that closed days ago.
    // Silence here would be the same failure in reverse: the page would look live, and a
    // "Complete · no signal" from Friday would be read as this morning's verdict.
    const mv = state.marketView?.market_view || {};
    if (mv.session_is_today === false && mv.session_date) {
      // Stage 5ZZZ-BQ. Two different reasons this band is not showing today, and only one of
      // them is "the market is closed". Since a past session can now be opened deliberately,
      // saying the market is shut would be a fact about the world that is simply untrue.
      out.push(state.mvDay
        ? mvChip(`Reviewing ${mv.session_date}`, 'muted',
                 `You opened this session from the bar above. The panels in this band `
                 + `describe ${mv.session_date}; everything outside it stays on the live day.`)
        : mvChip(`Closed today — session ${mv.session_date}`, 'muted',
                 mv.session_anchor_reason
                 || `The market is closed on ${mv.today_et || 'today'}; every panel below `
                    + `describes ${mv.session_date}, the last trading day.`));
    }
    // Progress first, because it changes what the outcome MEANS -- unless the outcome is that
    // the feed did not answer, in which case nothing below it can be read at all.
    const pr = mvProgressChip(s);
    const st = mvStatusChip(s);
    if (st && st.outranks) out.push(mvChip(st.word, st.tone, st.tip));
    out.push(mvChip(pr.word, pr.tone, pr.tip));
    if (st && !st.outranks) out.push(mvChip(st.word, st.tone, st.tip));

    const cov = s.coverage || {};
    if (cov.observed_slots != null && cov.expected_slots != null) {
      out.push(mvChip(`${cov.observed_slots}/${cov.expected_slots} slots`, '',
                      'Slots the window ledger recorded as observed, out of the slots ' +
                      'scheduled for this sleeve.'));
    } else if ((s.slots || []).length) {
      out.push(mvChip(`${s.slots.length} slots`, ''));
    }

    // The data chip, and each branch is a DIFFERENT fact rather than three ways of saying
    // "fine". Nobody-looked is not the same as looked-and-got-nothing.
    const d = s.data_status || {};
    if (d.ok === false && d.provider_reason) {
      out.push(mvChip('No live bars', 'bad', mvPhrase(d.provider_reason)));
    } else if (d.latest_bar_et) {
      out.push(mvChip(`Latest ${mvClock(d.latest_bar_et)} ET`, '',
                      `Data join: ${mvPhrase(d.splice_result)}`));
    } else if (d.ok == null) {
      out.push(mvChip('No reading', 'muted',
                      'This sleeve has not recorded a data observation for this session yet.'));
    }

    if (s.levels_note) {
      out.push(mvChip(s.levels_note, 'muted', s.levels_detail || ''));
    }
    // Stage 5ZZR. HOW this sleeve decides, in words. `metric_boundary` and
    // `entry_after_setup_only` are names for the code; an operator needs the shape of the
    // rule, because it is what makes the rest of the panel make sense.
    const kindWord = MV_BOUNDARY_WORD[(s.setup_boundary || {}).boundary_type];
    if (kindWord) {
      out.push(mvChip(kindWord, 'muted', (s.setup_boundary || {}).boundary_proof || ''));
    }
    // Stage 5ZZP. WHY there is no signal, from the sleeve's own rule values. This is the chip
    // the panel existed to be able to show: "no signal" with nothing behind it sends an
    // operator to look for a data problem that is not there.
    const strat = s.strategy || {};
    const failed = (strat.rules || []).filter(r => r.passed === false);
    if (failed.length) {
      const first = failed[0];
      // "Regime → Calm", not "Regime Calm": with a space the two words read as one
      // phrase and the reader has to know which half is the rule and which is what
      // was observed. The arrow says the rule got that value.
      out.push(mvChip(`${first.label} → ${mvNum(first.value)}`, 'warn',
        `Needs ${first.comparator} ${mvNum(first.threshold)}. ` +
        (failed.length > 1 ? `${failed.length} conditions unmet.` : 'The only unmet condition.')));
    }
    // Stage 5ZZZ-S. The rule values are computed off the request path now, so for a window
    // after a backend restart they are not there yet. Say which it is: an empty rules list
    // renders exactly like a session with nothing unmet, and those are different facts. The
    // backend already sends the reason — this only displays it, and decides nothing.
    else if (strat.status === 'not_available' && strat.detail) {
      out.push(mvChip('Rule values pending', 'muted', strat.detail));
    }
    // The stored-session note is METADATA, not a warning: on an ordinary day the store simply
    // has not been appended yet, and painting that amber would cry wolf every morning.
    if (s.bars_session_date && s.bars_session_date !== (
        state.marketView?.market_view?.session_date)) {
      out.push(mvChip(`Stored session ${s.bars_session_date}`, 'muted',
                      'Today\u2019s bars are not written to the store until the daily append, ' +
                      'so this shows the most recent stored session.'));
    }
    return out.join('');
  }

  const MV_LEGEND = [
    { k: 'no_signal', word: 'No signal' }, { k: 'signal', word: 'Signal' },
    { k: 'refused', word: 'Refused' }, { k: 'missed', word: 'No record' },
    { k: 'future', word: 'Not yet' }
  ];

  function mvLegend() {
    return `<div class="mv-legend">` + MV_LEGEND.map(l => {
      const m = MV_MARK[l.k];
      return `<span class="mv-legend-item"><i class="mv-key" style="border-color:${m.fill};` +
             `background:${m.hollow ? 'transparent' : m.fill}"></i>${mvEsc(l.word)}</span>`;
    }).join('') + `</div>`;
  }


  function mvTabs() {
    const host = $('marketViewTabs');
    if (!host) return;
    const sleeves = state.marketView?.market_view?.sleeves || {};
    host.innerHTML = MV_ORDER.filter(k => sleeves[k]).map(k => {
      const on = state.mvTab === k;
      return `<button class="mv-tab${on ? ' on' : ''}" type="button" role="tab"
        aria-selected="${on}" data-mv-tab="${mvEsc(k)}">${mvEsc(sleeves[k].label)}</button>`;
    }).join('');
    host.querySelectorAll('[data-mv-tab]').forEach(b => b.addEventListener('click', () => {
      const next = b.dataset.mvTab;
      // Stage 5ZZZ-CO. Công cụ đã chọn thuộc về SLEEVE đã chọn nó. MYM là của rổ Swing;
      // mang nó sang NKD thì backend lùi về công cụ ghi được của NKD — đúng, nhưng chip
      // vẫn nhớ một lựa chọn không còn nghĩa gì, và lần quay lại sẽ không phải lựa chọn cũ.
      // Quên nó ở ranh giới sleeve, chỗ nó thôi có nghĩa.
      if (next !== state.mvTab) state.mvInst = null;
      state.mvTab = next;
      renderMarketView();
    }));
  }

  //: A time string the backend emitted, reduced to hh:mm for the axis. Parsed by splitting
  //: rather than by `new Date`: these stamps are wall-clock on the sleeve's own exchange
  //: clock, and handing them to a Date would reinterpret them in the viewer's zone — which
  //: is exactly the thirteen-hour class of error this project already paid for once.
  /* Cắt 'HH:MM' ra khỏi một chuỗi thời gian — nhưng chỉ khi chuỗi ấy KHÔNG mang offset.
     Đo được 2026-09-04: `data_status.latest_bar_et` trả về "2026-09-04 15:54:00+09:00" —
     giờ Tokyo, offset ghi rõ — và bản cũ cắt thẳng "15:54" rồi panel nối thêm chữ " ET".
     Kết quả: "Latest bar 15:54 ET" nằm trong một panel khai "window 01:10–02:55 ET", tức
     một mốc rơi ngoài hẳn cửa sổ của chính nó. Mốc thì ĐÚNG (15:54 Tokyo = 02:54 ET, nằm
     gọn trong cửa sổ); chỉ có cách trình bày là sai.
     Cùng lớp lỗi với chuyện biểu đồ vẽ nến tương lai vì lẫn UTC/ET đã sửa trước đó — chart
     được sửa, dòng data-health thì không.
     Chuỗi KHÔNG offset đi đúng đường cũ: nó vốn đã ở đồng hồ mà người gọi muốn hiển thị. */
  function mvClock(t) {
    const s = String(t || '');
    if (/[+-]\d{2}:\d{2}$|Z$/.test(s)) {
      const when = new Date(s.replace(' ', 'T'));
      if (!Number.isNaN(when.getTime())) {
        return new Intl.DateTimeFormat('en-GB', {
          timeZone: ET_ZONE, hour: '2-digit', minute: '2-digit', hour12: false }).format(when);
      }
    }
    const i = s.indexOf(' ');
    return i < 0 ? s : s.slice(i + 1, i + 6);
  }

  function mvEmpty(message, detail) {
    return `<div class="mv-empty"><b>${mvEsc(message)}</b>` +
           (detail ? `<span>${mvEsc(detail)}</span>` : '') + `</div>`;
  }

  /* Where the slots sit horizontally in the price chart, so the series chart below
     can use the same span. Written by the price renderer, read by the series one.
     Null until a chart carrying slots has been drawn — the series then falls back to
     its own full width rather than guessing a span it was not given. */
  //: One padding for the plot and for the hover that reads it. Two copies drifted once.
  const MV_PAD = { L: 34, R: 68 };
  let mvSlotSpan = null;
  //: Where each slot MINUTE sits in the price chart, for the series chart to reuse.
  let mvSlotX = null;

  function mvChartSvg(sleeve) {
    /* Xoá khi VÀO, không chỉ ghi khi thành công. Nhánh thoát sớm ngay dưới đây làm một
       sleeve không có bar không vẽ chart nào cả, và bản đồ của sleeve vẽ TRƯỚC nó vẫn
       sống sót — nên pane chuỗi bên dưới đặt slot của mã NÀY lên các phút của nến mã
       KHÁC, trên một trục mà nó có mọi lý do để tin là đang dùng chung. */
    mvSlotSpan = null;
    mvSlotX = null;
    const bars = sleeve.bars || [];
    if (!bars.length) {
      /* "Latest stored session <date>" used to be the second half of this: the backend
         substituted the newest session it had when the day asked for was missing. It no
         longer substitutes, so `bars_session_date` is either the day on screen or nothing,
         and the only thing left worth saying is WHY the day on screen has none. */
      return mvEmpty(`No bars recorded yet for this session`,
        mvPhrase(sleeve.bars_note) || 'The bar store holds nothing for this window.');
    }
    // Stage 5ZZM. Room on every side, and a LANE for the markers.
    //
    // The first version used 8px of left padding and dropped the slot dots onto the plot
    // floor, so candles ran into the edge and the markers read as stray ink on the chart
    // rather than as a row of outcomes. `padB` now carries a marker lane above the time
    // axis: the dots sit on their own baseline, which is what makes them a row instead of
    // noise.
    const W = 1000, H = 420, padL = MV_PAD.L, padR = MV_PAD.R, padT = 16, padB = 46;
    const laneH = 16;
    // Stage 5ZZP. The volume pane takes its height from the SAME box, so adding it
    // cannot move the panel — the property the tab-switch test pins.
    const hasVol = bars.some(b => typeof b.volume === 'number');
    /* Tall enough to draw the real range instead of cutting it.
       At 58px the scale had to stop at the ninetieth percentile, and then 110, 37 and 33
       all rendered at exactly the same height -- three different sessions of trading drawn
       as one. Height is what buys the difference back: at 120 the true peak fits, every
       value is distinct, and the median minute still stands 9.2px tall. */
    const volH = hasVol ? 120 : 0;
    const iw = W - padL - padR, ih = H - padT - padB - volH;
    /* Luật 5 của hợp đồng: KHÔNG vẽ <text> trong một SVG có preserveAspectRatio="none".
       Bản design không có một thẻ <text> nào trong toàn bộ file — trục của nó là HTML bên
       cạnh, nến và dot là <div> định vị tuyệt đối — nên không chỗ nào méo được, và luật
       cấm thẳng CẤU TRÚC thay vì đặt một mức méo cho phép.
       Bản trước chống méo bằng cách phản-co từng nhãn theo tỉ lệ đo được. Nó chữa được
       triệu chứng nhưng phải chạy lại mỗi lần khung đổi kích thước, và vẫn để lại đúng
       cấu trúc mà luật cấm.
       Giờ chữ ra một lớp HTML phủ lên SVG. SVG kéo giãn lấp đầy khung, nên toạ độ viewBox
       quy sang phần trăm là ánh xạ CHÍNH XÁC — không phải xấp xỉ. Chữ HTML thì không bao
       giờ bị kéo, vì nó không nằm trong hệ toạ độ bị kéo.
       `y` của SVG là ĐƯỜNG CƠ SỞ của chữ, còn `top` của HTML là mép trên hộp; -0.75em đưa
       hộp lên cho đường cơ sở rơi đúng chỗ cũ. */
    const axisText = [];
    const ANCHOR = { start: '0', middle: '-50%', end: '-100%' };
    /* Stage 5ZZZ-CN. MỘT cách viết số cho cả hai biểu đồ chồng nhau.
       Đo được trên trang: pane nến in `65204.20`, pane slot ngay dưới in `65,043.54` — cùng
       một loại giá, cùng một cột, hai cách viết. Ở mức năm chữ số, thiếu dấu phân cách là
       thiếu đúng thứ giúp đọc bậc độ lớn trong một liếc. */
    const axPrice = v => Number(v).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const axCount = v => Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
    const mvLab = (px, py, cls, txt, anchor) => {
      axisText.push(`<span class="mv-lab ${cls}" style="left:${(px / W * 100).toFixed(3)}%;`
        + `top:${(py / H * 100).toFixed(3)}%;--ax:${ANCHOR[anchor || 'start']}">`
        + `${txt}</span>`);
      return '';
    };
    const laneY = padT + ih + volH + 13;
    let lo = Infinity, hi = -Infinity;
    bars.forEach(b => { lo = Math.min(lo, b.low); hi = Math.max(hi, b.high); });
    if (!(hi > lo)) { hi = lo + 1; lo -= 1; }
    /* Stage 5ZZZ-CQ. Thang giá phải chứa được những gì sẽ vẽ lên nó.

       Thang tính từ NẾN thôi, rồi các mức giá được vẽ chồng lên — nên một mức nằm ngoài
       khoảng nến bị cắt ở mép. Đo trên trang, sleeve Stress 2026-09-04:

           khoảng nến     29.477,75 → 29.692,00
           Planned stop   29.715,69   cao hơn đỉnh 23,69 điểm

       Đường và nhãn của nó rơi nửa trong nửa ngoài mép trên, đọc như một lỗi vẽ. Mà khoảng
       cách từ giá tới mức dừng lỗ chính là thứ người đọc muốn thấy — giấu nó đi hay cắt nó
       đôi đều tệ hơn là nới thang.

       NỚI CÓ HẠN. Một mức ở xa gấp mấy lần khoảng nến sẽ nén toàn bộ cây nến thành một
       vạch, và lúc đó biểu đồ mất đúng việc nó sinh ra để làm. Trần 40% khoảng nến: trong
       hạn thì nới, ngoài hạn thì mức ấy không vẽ và được nói ra bằng chữ ở dòng dưới. */
    const _span = hi - lo;
    const _room = _span * 0.40;
    const _lv = ((sleeve.setup_boundary || {}).price_levels || [])
      .map(l => Number(l.price)).filter(Number.isFinite);
    const outOfRange = [];
    ((sleeve.setup_boundary || {}).price_levels || []).forEach(l => {
      const v = Number(l.price);
      if (!Number.isFinite(v)) return;
      if (v > hi + _room || v < lo - _room) outOfRange.push(l);
    });
    _lv.forEach(v => {
      if (v <= hi + _room && v >= lo - _room) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    });
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    const x = i => padL + (bars.length === 1 ? iw / 2 : (i / (bars.length - 1)) * iw);
    const y = v => padT + (1 - (v - lo) / (hi - lo)) * ih;
    // Wide enough to read as a candle at 1440px, narrow enough not to merge at 375px.
    const bw = Math.max(2.5, Math.min(9, iw / Math.max(bars.length, 1) * 0.58));

    // The window band, drawn from the sleeve's declared window rather than guessed from the
    // bars: an operator reads "was price doing this while the sleeve was allowed to act".
    const ws = sleeve.range?.window_start_et, we = sleeve.range?.window_end_et;
    const inWin = i => {
      const c = mvClock(bars[i].time);
      return ws && we && c >= ws && c <= we;
    };
    let band = '';
    const first = bars.findIndex((_, i) => inWin(i));
    if (first >= 0) {
      let last = first;
      bars.forEach((_, i) => { if (inWin(i)) last = i; });
      const bx = x(first), bwid = Math.max(1, x(last) - x(first));
      band = `<rect class="mv-band" x="${bx.toFixed(1)}" y="${padT}"
        width="${bwid.toFixed(1)}" height="${ih}"></rect>`
        // Labelled only when the band is wide enough to hold the word without sitting on a
        // candle. Below that it stays an unlabelled tint, which still reads as "this part".
        + (bwid > 90 ? mvLab(bx + 5, padT + 12, 'mv-band-label', 'Window', 'start') : '');
    }

    const candles = bars.map((b, i) => {
      const up = b.close >= b.open;
      const top = y(Math.max(b.open, b.close)), bot = y(Math.min(b.open, b.close));
      const cls = up ? 'mv-up' : 'mv-down';
      return `<line class="${cls} mv-wick" x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}"
                y1="${y(b.high).toFixed(1)}" y2="${y(b.low).toFixed(1)}"></line>
              <rect class="${cls} mv-body" x="${(x(i) - bw / 2).toFixed(1)}"
                y="${top.toFixed(1)}" width="${bw.toFixed(1)}"
                height="${Math.max(1, bot - top).toFixed(1)}"></rect>`;
    }).join('');

    // Price scale on the right, five ticks. Times along the bottom, thinned so labels never
    // collide at narrow widths.
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => {
      const v = lo + (hi - lo) * f;
      mvLab(W - 6, y(v) + 3.5, '', mvEsc(axPrice(v)), 'end');
      return `<line class="mv-grid" x1="${padL}" x2="${W - padR}"
                y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"></line>`;
    }).join('');
    const every = Math.max(1, Math.ceil(bars.length / 8));
    const times = bars.map((b, i) => (i % every ? '' :
      mvLab(x(i), H - 8, 'mv-time', mvEsc(mvClock(b.time)), 'middle'))).join('');

    // Slot markers along the foot of the plot, positioned by their own time against the bar
    // clock. A slot outside the drawn range is dropped rather than clamped to the edge: a
    // marker pinned to the wrong minute is worse than a marker that is not there.
    const clocks = bars.map(b => mvClock(b.time));
    /* The x-range the slots actually occupy in THIS chart, recorded for the series
       chart below to reuse. The two panes are read as one picture — a reader follows a
       minute down from a candle to the close line — and that only works if the same
       slot sits at the same horizontal place in both. Measured before this: a slot at
       47% of the price chart sat at 5% of the series chart, so the two lined up
       nowhere and the series looked stretched across width the candles never used. */
    let _slotSpan = null;
    const _slotX = {};
    const marks = (sleeve.slots || []).map(s => {
      const t = String(s.time_et || '');
      let idx = clocks.findIndex(c => c >= t);
      if (idx < 0) return '';
      const m = MV_MARK[s.status] || MV_MARK.unknown;
      const cx = x(idx);
      _slotX[t] = cx;
      _slotSpan = _slotSpan
        ? { from: Math.min(_slotSpan.from, cx), to: Math.max(_slotSpan.to, cx),
            count: _slotSpan.count + 1 }
        : { from: cx, to: cx, count: 1 };
      /* An ELLIPSE, not a circle. The plot uses preserveAspectRatio="none", so x is
         stretched ~1.6x while y is not — every circle rendered as a flattened oval
         10.9px wide by 6.8px tall. rx is corrected to the measured scale by next.js;
         the authored value here is the radius we want to SEE. */
      return `<ellipse class="mv-mark" cx="${cx.toFixed(1)}" cy="${laneY.toFixed(1)}" rx="3.4" ry="3.4"
        fill="${m.hollow ? 'none' : m.fill}" stroke="${m.fill}"
        data-slot="${mvEsc(s.slot_id)}" data-time="${mvEsc(t)}"
        data-word="${mvEsc(m.word)}" data-reason="${mvEsc(mvPhrase(s.reason))}"
        ><title>${mvEsc(t)} · ${mvEsc(m.word)}${s.reason ? ' · ' + mvEsc(mvPhrase(s.reason)) : ''}</title></ellipse>`;
    }).join('');
    // Published only once the row is complete, so a half-built span is never read.
    mvSlotSpan = _slotSpan;
    /* Đóng dấu nó được dựng TỪ đâu. Pane chuỗi kiểm dấu này trước khi nhận, nên một bản
       đồ không bao giờ bị đọc nhầm sang mã khác hoặc phiên khác — đúng hai kiểu hỏng làm
       cho câu "chung trục" trở thành một lời khai sai. */
    mvSlotX = { key: `${sleeve.instrument || ''}|${sleeve.bars_session_date || ''}`, x: _slotX };
    // The lane's own baseline. Without it the dots float; with it they read as a row of
    // outcomes running under the session.
    const laneRule = `<line class="mv-lane" x1="${padL}" x2="${W - padR}"
      y1="${laneY.toFixed(1)}" y2="${laneY.toFixed(1)}"></line>`;

    // Stage 5ZZR. Price lines, and the three states they can be in.
    //
    //   no levels published        nothing is drawn
    //   published but NOT armed    drawn muted and labelled, because the number is real and
    //                              the operator wants to read it — but the gate did not pass,
    //                              so it is not a level anything is waiting at
    //   armed                      drawn solid, because a candidate is live
    //
    // The middle state is the one this stage exists for. Stress computes its trigger from the
    // pre-session low at 10:30 whether or not the basket gate passes, so withholding it hides
    // a real number while drawing it solid would put a tradable line on a day nothing is
    // trading. Every value comes from the payload; none is derived here.
    const bnd = sleeve.setup_boundary || {};
    const armed = bnd.levels_armed === true;
    const levels = (bnd.price_levels || [])
      .filter(l => Number.isFinite(Number(l.price)))
      .filter(l => !outOfRange.includes(l))
      .map(l => ({ l, yy: y(Number(l.price)) }))
      .sort((a, b) => a.yy - b.yy);

    /* Stage 5ZZZ-CQ. Đường ở đúng giá của nó; CHỮ thì nhường nhau.

       Mỗi nhãn được đặt tại toạ độ giá của chính nó và không có bước nào hỏi xem chỗ ấy đã
       có ai đứng chưa. Đo trên trang, sleeve Stress 2026-09-04: "Trigger (pre-session low) ·
       not armed" ở y=1163 và "Session open · not armed" ở y=1157 — cách nhau 6px trong khi
       mỗi nhãn cao 11px, nên hai câu in chồng lên nhau và không câu nào đọc được.

       Chỉ nhãn dịch. Đường phải ở đúng giá, vì đó là thứ người đọc so với cây nến; một nhãn
       lệch vài pixel khỏi đường của nó vẫn đọc được, một đường lệch khỏi giá của nó thì sai.
       Đẩy xuống chứ không đẩy lên: thứ tự trên-dưới của các mức giá được giữ nguyên. */
    /* Chiều cao một nhãn — tính bằng ĐƠN VỊ viewBox, không phải pixel màn hình.
       Đây là chỗ hai bản trước cùng trượt. Nhãn là một <span> HTML phủ lên SVG, định vị
       bằng phần trăm của khung `.mv2-plot` cao 320px; còn `yy` ở dòng dưới là toạ độ trong
       viewBox cao 420. Hai hệ đo khác nhau, tỉ lệ 320/420. Một hằng số "16" đặt ở đây thật
       ra chỉ giữ được 16 × 320/420 ≈ 12px trên màn hình — nên khi ô chữ cao 18px thì hai
       nhãn cách nhau đúng 16px vẫn in đè lên nhau, đo được ở cổng CQ.
       Quy đổi một lần, ở đây, thay vì đoán:
         ô chữ = 11.5px chữ (line-height 1) + 2×2px đệm + 2×1px vành ≈ 17.5px
         đổi sang đơn vị viewBox: 17.5 × 420/320 ≈ 23  →  cộng 3 cho một khoảng thở
       PHỤ THUỘC vào `.mv-lab.mv-level-label` trong next.css và vào chiều cao `.mv2-plot`
       trong realtime.css. Đổi đệm, vành, cỡ chữ hay chiều cao khung thì phải sửa hai con số
       dưới đây — và cổng CQ đo hình học thật trên trang sẽ đỏ nếu quên. */
    const LAB_PX = 17.5, PLOT_PX = 320;
    const LAB_H = Math.ceil(LAB_PX * H / PLOT_PX) + 3;
    let _prevLab = -Infinity;
    const levelLines = levels.map(({ l, yy }) => {
      const line = yy.toFixed(1);
      const cls = (l.armed === true && armed) ? 'mv-level armed' : 'mv-level muted';
      const suffix = (l.armed === true && armed) ? '' : ' · not armed';
      const labY = Math.max(yy - 4, _prevLab + LAB_H);
      _prevLab = labY;
      // Nhãn mang theo LOẠI của mức, không chỉ mang trạng thái. Không có nó thì ba nhãn
      // cùng một màu xám và người đọc phải dò xem chữ nào thuộc đường nào.
      mvLab(padL + 4, labY,
        `mv-level-label mv-level-${mvEsc(l.kind)} `
        + `${cls.includes('armed') ? 'armed' : 'muted'}`,
        mvEsc(l.label) + suffix, 'start');
      return `<line class="${cls} mv-level-${mvEsc(l.kind)}" x1="${padL}" x2="${W - padR}"
          y1="${line}" y2="${line}"></line>`;
    }).join('');

    // Volume bars, drawn only where the store actually carried the column. Never
    // synthesised: a zero-height bar for a missing reading and a zero-height bar for a quiet
    // minute would draw identically, and one of those is a fact about the market.
    let vol = '';
    if (hasVol) {
      /* Scaled to a ROBUST ceiling, not the tallest bar.
         Measured on MNKD, 2026-09-03: thirty-six bars reading
         26 18 33 9 9 24 ... 110 ... 37 ... 1 -- a peak of 110 against a median of 9, twelve
         times over. Divided by the peak, eighteen of the thirty-six came out under a tenth of
         a forty-four pixel pane: under four pixels, which on screen is nothing. The pane read
         as one column and a flat line, and the flat line was a session that traded on
         thirty-five of its thirty-six minutes.
         So the ceiling is the ninetieth percentile of the bars that traded, and anything above
         it is drawn full height with a cap on top rather than being allowed to set the scale
         for everyone else. Two bars clip here; the other thirty-four become legible.
         The floor is 1.5px rather than 0.5px for the same reason in the other direction: a
         minute that traded must never draw as a minute that did not. Zero keeps its own
         height of zero -- that distinction is the whole point of the volume pane. */
      const vols = bars.map(b => (typeof b.volume === 'number' ? b.volume : null));
      const vpeak = Math.max(...vols.map(v => v || 0), 1);
      const vTop = padT + ih + 6;
      const usable = volH - 8;
      vol = bars.map((b, i) => {
        if (typeof b.volume !== 'number') return '';
        /* Tuyến tính, vì cột cao gấp mười hai lần thì phải TRÔNG gấp mười hai lần.
           Đường vòng qua đây dài và đáng ghi lại: cột trông như chỉ có một là do KHUNG
           chứa bị ghim 320px trong khi svg đã 420px, nên 101px cuối — đúng pane volume —
           bị cắt đáy. Chữa triệu chứng bằng cách cắt trần ở phân vị 90 thì 110, 37 và 33
           vẽ bằng nhau; chữa bằng căn bậc hai thì cột 110 chỉ còn cao gấp 3,4 lần trung vị
           thay vì 12. Sửa đúng chỗ là khung, rồi thang trả về đúng tỉ lệ. */
        const h = b.volume <= 0 ? 0
          : Math.max(2, (b.volume / vpeak) * usable);
        const y = vTop + usable - h;
        return `<rect class="mv-vol ${b.close >= b.open ? 'mv-up' : 'mv-down'}"
          x="${(x(i) - bw / 2).toFixed(1)}" y="${y.toFixed(1)}"
          width="${bw.toFixed(1)}" height="${h.toFixed(1)}"><title>volume ${
            b.volume}</title></rect>`;
      }).join('') +
      mvLab(padL, vTop + 8, 'mv-vol-label', 'Volume', 'start')
      /* The ceiling label sits BELOW the price axis's last one. Both want the right
         column and the price plot ends exactly where this pane starts, so at the top of
         the pane they land on the same line: measured, "32  peak 110" printed straight
         through "64127.80". Twenty units down clears it and still reads as the top of
         this pane rather than the bottom of the one above. */
      /* Căn PHẢI. Căn trái làm cột khối lượng so le với cột giá ngay trên nó: đo được
         mép phải 1410 · 1433 · 1439 cho "0" · "6,905" · "13,810" trong khi cột giá đứng ở
         1455. Số trong một cột thì phải thẳng ở hàng đơn vị, không thẳng ở chữ số đầu. */
      + mvLab(W - 6, vTop + 20, 'mv-vol-ax', mvEsc(axCount(vpeak)), 'end')
      + mvLab(W - 6, vTop + usable / 2 + 3, 'mv-vol-ax',
              mvEsc(axCount(Math.round(vpeak / 2))), 'end')
      + mvLab(W - 6, vTop + usable, 'mv-vol-ax', '0', 'end')
      /* A floor to stand on. Without it the columns hang in the gap between two panes and
         the eye has nothing to read their height against. */
      + `<line class="mv-vol-base" x1="${padL}" x2="${W - padR}" y1="${
          (vTop + usable).toFixed(1)}" y2="${(vTop + usable).toFixed(1)}"></line>`;
    }

    return `<svg class="mv-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
              data-bars='${mvEsc(JSON.stringify(bars.map(b => [mvClock(b.time), b.open, b.high, b.low,
                b.close, (typeof b.volume === 'number' ? b.volume : null)])))}'>
        ${ticks}${band}${candles}${levelLines}${vol}${laneRule}${marks}${times}
        <line class="mv-cross" x1="0" x2="0" y1="${padT}" y2="${padT + ih}" style="display:none"></line>
      </svg>
      <div class="mv-labels">${axisText.join('')}</div>
      <div class="mv-tip" hidden></div>`;
  }

  //: Crosshair and tooltip. Bound after each render because the SVG is replaced wholesale;
  //: the listener lives on the container, so there is exactly one regardless of how many
  //: times this runs.
  function mvBindHover(host) {
    const svg = host.querySelector('.mv-svg');
    const tip = host.querySelector('.mv-tip');
    const cross = host.querySelector('.mv-cross');
    if (!svg || !tip || !cross) return;
    let bars = [];
    try { bars = JSON.parse(svg.dataset.bars || '[]'); } catch (_e) { bars = []; }
    /* The SAME padding the plot is drawn with. It was 8 and 62 here against 34 and 68
       there, so every hover resolved to a bar the crosshair was not standing on: measured
       2026-09-03, the line landed at x=592.6 while candle centres ran 341.9, 367.5, ... on a
       25.66 pitch — between two bars, and the O/H/L/C printed beside it belonged to a third.
       Read from the plot rather than restated, so the two cannot drift apart again. */
    const W = 1000, padL = MV_PAD.L, padR = MV_PAD.R;
    const move = ev => {
      const r = svg.getBoundingClientRect();
      if (!r.width || !bars.length) return;
      const vx = ((ev.clientX - r.left) / r.width) * W;
      const iw = W - padL - padR;
      let i = Math.round(((vx - padL) / iw) * (bars.length - 1));
      i = Math.max(0, Math.min(bars.length - 1, i));
      const b = bars[i];
      cross.setAttribute('x1', String(padL + (bars.length === 1 ? iw / 2 : (i / (bars.length - 1)) * iw)));
      cross.setAttribute('x2', cross.getAttribute('x1'));
      cross.style.display = '';
      tip.hidden = false;
      tip.textContent = `${b[0]}  O ${b[1]}  H ${b[2]}  L ${b[3]}  C ${b[4]}`;
      const left = Math.max(0, Math.min(r.width - tip.offsetWidth - 4, ev.clientX - r.left + 12));
      tip.style.left = `${left}px`;
    };
    host.addEventListener('mousemove', move);
    host.addEventListener('mouseleave', () => {
      tip.hidden = true;
      cross.style.display = 'none';
    });
  }


  // ── Stage 5ZZY. Verdict, inner tabs and the setup lanes ──────────────────────────────
  //
  // The verdict is ONE word plus the fact that word rests on, and the fact is always a
  // measured one: a slot time, a bar time, a count from the ledger. It is never a summary of
  // the cards below, because a reader who takes in only this line must not be told something
  // those cards would contradict.
  function mvVerdictDetail(s) {
    const d = s.data_status || {};
    const cov = s.coverage || {};
    const slots = s.slots || [];
    const first = slots[0];
    // The last slot that actually SAW data, not merely the last one with a row: a refused
    // slot leaves a record without an observation, so pointing "no live bars since" at one
    // names a minute when there were already no bars.
    const last = slots.slice().reverse().find(
      x => x.status === 'no_signal' || x.status === 'signal' || x.status === 'rejected');
    const sig = slots.find(x => x.status === 'signal');
    const rej = slots.find(x => x.status === 'rejected');
    if (d.ok === false && d.provider_reason) {
      return last ? `no live bars since ${last.time_et} ET` : 'no live bars recorded';
    }
    if (s.status === 'waiting') {
      return first ? `first slot ${first.time_et} ET` : 'window has not opened';
    }
    if (sig) return `candidate at ${sig.time_et} ET`;
    if (rej) return `gate refused at ${rej.time_et} ET`;
    /* "N / M slots observed" trả về RỖNG chứ không bị xoá khỏi chuỗi. Nó nói đúng hai
       con số mà câu tóm tắt của panel đã nói, dưới đúng điều kiện câu ấy chạy, nên ô chip
       bị `.filter(c => c.txt)` loại bỏ.
       Phải là `return ''` chứ không phải bỏ hẳn nhánh: bỏ hẳn thì hàm rơi xuống nhánh dự
       phòng ngay dưới và in "gate allow failed 19 of 22" — đúng nửa SAU của cùng câu ấy.
       Đo được: xoá nhánh xong, chip cũ biến mất và một chip trùng khác hiện ra thế chỗ.
       Nhánh dự phòng đó tồn tại cho trường hợp sổ không ghi gì, và nó phải ở nguyên đó. */
    if (cov.observed_slots != null && cov.expected_slots != null) return '';
    // Nothing fired and the ledger said nothing: name the unmet rule rather than leaving the
    // operator to guess which of nine conditions was the blocker.
    const lane = (s.rule_lanes || []).find(L => L.failed > 0);
    if (lane) return `${lane.label} failed ${lane.failed} of ${lane.slots_decided}`;
    return 'nothing recorded for this session';
  }

  /* Which lane actually blocked, named, with its own tally.
     Not a judgement made here: it is read from the cells the detector wrote. When
     more than one lane failed the one that failed most is named; when none did,
     this returns null rather than nominating a culprit so a clean session cannot
     be given a blame line it did not earn. */
  function mvBlockingLane(s) {
    let worst = null;
    (s.rule_lanes || []).forEach(L => {
      const cells = L.cells || [];
      const fails = cells.filter(c => c.state === 'fail').length;
      const decided = cells.filter(c => c.state === 'pass' || c.state === 'fail').length;
      if (fails && (!worst || fails > worst.fails)) {
        worst = { label: L.label, fails, decided };
      }
    });
    return worst;
  }

  /* The verdict as a sentence, under the chips.
     The chips say COMPLETE and NO SIGNAL; they do not say why nothing fired, and
     that is the question the panel exists to answer. Every clause is conditional
     on the field behind it: a session that decided 18 of 22 says so rather than
     claiming "every", and a session with no failing lane gets no blame clause. */
  function mvReasonSentence(s) {
    const cov = s.coverage || {};
    const expected = Number(cov.expected_slots);
    const observed = Number(cov.observed_slots);
    const parts = [];
    if (Number.isFinite(expected) && Number.isFinite(observed) && expected > 0) {
      /* "observed", không phải "decided". `coverage.observed_slots` là số slot THẬT SỰ
         BÁO CÁO — docstring của `record_window_observation` nói đúng chữ đó, và nó đếm
         `len(slot_ids)` với slot_ids là "the list of slots that actually reported".
         Số slot đã QUYẾT nằm ở chỗ khác: `rule_lanes[].slots_decided`, hôm nay là 22.
         Dùng nhầm chữ làm câu này tự mâu thuẫn trong chính nó — đo được 2026-09-04 nó in
         "3 of 22 slots decided ... gate allow failed on 19 of 22 decided slots": ba slot
         đã quyết, mà mười chín trên hai mươi hai slot đã quyết lại trượt. */
      parts.push(observed >= expected
        ? 'Every slot reported'
        : `${observed} of ${expected} slots reported`);
    }
    if (cov.signal === 'no_signal') parts.push('none fired');
    let out = parts.length ? parts.join(' and ') + '.' : '';
    const blocked = mvBlockingLane(s);
    if (blocked) {
      out += ` ${blocked.label} failed on ${blocked.fails} of ${blocked.decided} decided slots.`;
    }
    return out.trim();
  }

  /* Where the evidence came from — recorded live, or replayed afterwards.
     A reader deciding whether to act on this panel needs to know whether the
     verdicts were written by the slots as they ran or reconstructed from bars on
     disk. The answer is the session row's own `has_diagnostics`; it is never
     inferred from the presence of lanes, because a replay produces lanes too. */
  function mvEvidenceProvenance(s) {
    const day = s.bars_session_date || state.mvDay;
    const rows = (state.marketView || {}).sessions || [];
    const row = day ? rows.find(r => r && r.day === day) : null;
    if (!row) return '';
    return row.has_diagnostics ? 'recorded while the slots ran' : 'replayed over stored bars';
  }

  function mvVerdict(s) {
    const host = $('marketViewVerdict');
    if (!host) return;
    // Stage 5ZZZ-BX. The outcome when there is one, the progress when there is not.
    //
    // `mvStatusChip` now answers only "what did it find", and returns nothing while a sleeve
    // has decided nothing -- so this line, the second caller, had to be found rather than
    // assumed. Without the fallback it would have thrown on every waiting sleeve, which is
    // the state the page opens in every morning.
    const st = mvStatusChip(s) || mvProgressChip(s);
    /* The design shows TWO chips here, not one: progress ("COMPLETE") and outcome
       ("NO SIGNAL"). They answer different questions -- how far the window got, and
       what it found -- and collapsing them loses the first. Ordered the same way
       mvChips orders them, so the two rows never disagree about which comes first. */
    const _prog = mvProgressChip(s);
    const _stat = mvStatusChip(s);
    const pills = [];
    if (_stat && _stat.outranks) pills.push(_stat);
    if (_prog && _prog.word) pills.push(_prog);
    if (_stat && !_stat.outranks) pills.push(_stat);
    if (!pills.length) pills.push(st);
    const reason = mvReasonSentence(s);
    const blocked = mvBlockingLane(s);
    const provenance = mvEvidenceProvenance(s);
    /* G4/G5. The pill states the OUTCOME and nothing else; everything that qualifies it
       moves to one meta row underneath. Before this the pill carried a clause of its own
       and a second column sat to the right, so the same qualification was read in two
       places at two sizes.

       Each cell is dropped entirely when its source is missing — never a dash. A row of
       placeholders reads as data that failed to arrive, and on this panel that is a
       different and more alarming statement than a shorter row. */
    const slots = s.slots || [];
    const lastSlot = slots.length ? slots[slots.length - 1] : null;
    const kindWord = MV_BOUNDARY_WORD[(s.setup_boundary || {}).boundary_type];
    const nearest = (s.setup_boundary || {}).nearest_failed_condition || {};
    const ruleValue = nearest.value == null ? '' : String(nearest.value);
    /* Which session these numbers describe closes the metadata row in the design.
       It is the one item that says whether the row is about today at all, so a row
       that ends without it reads as live whatever day it came from. */
    const _mv = (state.marketView && state.marketView.market_view) || {};
    const sessionWord = _mv.session_date
      ? (_mv.session_is_today === false
          ? `reviewing ${_mv.session_date}` : `live session ${_mv.session_date}`)
      : '';
    const cells = [
      { txt: mvVerdictDetail(s), cls: 'mv2-vm-num' },
      { txt: lastSlot && lastSlot.time_et ? `latest ${lastSlot.time_et} ET` : '',
        cls: 'mv2-vm-num' },
      { txt: kindWord || '', cls: '' },
      { txt: blocked && ruleValue ? `${blocked.label} → ${ruleValue}` : '',
        cls: 'mv2-vm-rule' },
      { txt: sessionWord, cls: 'mv2-vm-prov' }
    ].filter(c => c.txt);
    const meta = cells.length
      ? `<div class="mv2-verdict-meta">` + cells.map(c =>
          `<span${c.cls ? ` class="${c.cls}"` : ''}>${mvEsc(c.txt)}</span>`).join('')
        + `</div>`
      : '';
    /* The right column the design keeps: the blocking lane WITH its tally, and where
       the evidence came from. The metadata row names the lane and the value it wanted;
       this says how often it missed. Same two facts at two grains, and the design puts
       the coarse one where the eye lands last. Dropped entirely when either is absent
       -- never a dash. */
    /* Dòng đếm của làn chặn đã bỏ khỏi cột phải. Câu tóm tắt ngay TRÊN nó nói đúng
       điều đó bằng nhiều chữ hơn — "gate allow failed on 19 of 22 decided slots" — và đo
       được hai dòng cách nhau 3px. Comment cũ ở đây tự nhận là "same two facts at two
       grains"; ở khoảng cách 3px thì hai độ mịn không còn là hai thứ nữa.
       Xuất xứ bằng chứng thì giữ: "recorded while the slots ran" không có ở đâu khác, và
       nó trả lời một câu hỏi khác hẳn — số liệu này do slot ghi lúc chạy hay dựng lại từ
       bar trên đĩa. */
    const sideLines = [];
    if (provenance) sideLines.push(provenance);
    const side = sideLines.length
      ? `<div class="mv2-verdict-side">` + sideLines.map((l, i) =>
          `<div class="${i ? 'mv2-vs-prov' : 'mv2-vs-detail'}">${mvEsc(l)}</div>`).join('')
        + `</div>`
      : '';
    host.innerHTML = pills.map(p =>
        `<span class="mv2-pill ${mvEsc(p.tone || 'muted')}"><i></i><b>${mvEsc(p.word)}</b></span>`
      ).join('')
      + (reason ? `<p class="mv2-reason">${mvEsc(reason)}</p>` : '') + side + meta;
  }

  //: The inner tabs exist only where the sleeve HAS two things to show. A sleeve whose route
  //: recorded rule diagnostics has a setup story and, separately, price context; a sleeve
  //: with no diagnostics has one story, and offering a second tab there would promise a view
  //: that is the same view.
  function mvInnerTabs(s) {
    const host = $('marketViewInnerTabs');
    if (!host) return false;
    // Stage 5ZZZ-AS. The strip used to depend on the LANES alone, and that stopped being
    // right the moment the grid became a tab of its own: early on a trading day the replay can
    // have scanned bars while no slot has written a record yet, so there are per-bar verdicts
    // and no lanes -- and the whole strip vanished, taking the only way to reach them with it.
    const hasLanes = (s.rule_lanes || []).length > 0;
    const hasGrid = (((s.bar_grid || {}).rows) || []).length > 0;
    if (!hasLanes && !hasGrid) {
      host.innerHTML = '';
      host.hidden = true;
      state.mvInner = null;
      return false;
    }
    host.hidden = false;
    // Stage 5ZZZ-AS. A third tab rather than a third band down the page: the grid answers a
    // different question from the lanes, not a longer version of the same one, and stacking
    // them made the panel scroll past the thing most sessions are actually asking about.
    //
    // Offered ALWAYS, including on a session with no bars. An absent tab reads as a feature
    // that does not exist; a tab that says why it is empty reads as a session that had nothing
    // to scan -- and on a Calm day for a Normal-only sleeve, that is the answer.
    const tabs = ['Setup rules', 'Detector rules', 'Price context'];
    if (!tabs.includes(state.mvInner)) state.mvInner = tabs[0];
    const armed = (s.setup_boundary || {}).levels_armed === true;
    const bars = ((s.bar_grid || {}).bars || []).length;
    const note = state.mvInner === 'Setup rules'
      ? 'What each rule did, slot by slot — open Detector rules for the per-bar verdicts.'
      : state.mvInner === 'Detector rules'
        ? (bars
            ? `One cell per bar, not per slot — ${bars} bars in this session's window.`
            : 'No bar was evaluated in this session, so the detector answered nothing per bar.')
      : (armed
          ? 'Levels published for this candidate.'
          : 'No candidate in this session, so no levels are published — price context only.');
    host.innerHTML =
      `<div class="mv2-tabset" role="tablist" aria-label="Market view detail">` +
      tabs.map(t => `<button class="mv2-tab${state.mvInner === t ? ' on' : ''}" type="button" ` +
        `role="tab" aria-selected="${state.mvInner === t}" ` +
        `data-mv-inner="${mvEsc(t)}">${mvEsc(t)}</button>`).join('') +
      `</div><span class="mv2-tabnote">${mvEsc(note)}</span>`;
    host.querySelectorAll('[data-mv-inner]').forEach(b => b.addEventListener('click', () => {
      state.mvInner = b.dataset.mvInner;
      renderMarketView();
    }));
    return true;
  }

  //: Cell vocabulary for the lanes. It deliberately reuses the slot-marker palette: a reader
  //: who has learned the dots under the chart already knows these.
  const MV_CELL = {
    pass:          { cls: 'ok',     word: 'passed' },
    fail:          { cls: 'bad',    word: 'failed' },
    not_reached:   { cls: 'hollow', word: 'not reached — the gate stopped the slot first' },
    not_published: { cls: 'muted',  word: 'the detector returned no verdict for this slot' },
    no_record:     { cls: 'norec',  word: 'no record was written for this slot' },
    future:        { cls: 'future', word: 'has not run yet' }
  };

  //: Short forms for the lane's right-hand column. The long sentence the backend sends is
  //: kept verbatim on hover and counted once in the card head; only the column is shortened.
  const MV_LANE_SHORT = {
    'value not published by the detector': 'no verdict',
    'not reached — the gate stopped the slot first': 'not reached',
    'no record was written for these slots': 'no record',
    'has not run yet': 'not yet run',
    'no verdict recorded': 'no verdict'
  };

  /* Chú giải cho hàng SLOT DECISIONS, tách khỏi chú giải làn luật.
     Đo được 2026-09-04: chú giải in ngay dưới mô tả sáu ô của LÀN LUẬT — pass/fail/
     not-reached/no-verdict/no-record/not-yet — trong khi hàng slot bên trên vẽ 19 chấm
     hổ phách và 3 chấm xám, hai màu KHÔNG có trong chú giải ấy. Một chú giải, hai hệ
     nghĩa: `MV_MARK` là kết quả của SLOT, còn ô làn là kết quả của LUẬT.
     Chỉ liệt kê trạng thái thật sự có mặt trong phiên, và suy thẳng từ `MV_MARK` để hai
     bên không thể trôi khỏi nhau. */
  function mvSlotLegend(slots) {
    const seen = [];
    (slots || []).forEach(sl => {
      const key = MV_MARK[sl.status] ? sl.status : 'unknown';
      if (!seen.includes(key)) seen.push(key);
    });
    if (!seen.length) return '';
    return `<div class="mv2-legend mv2-legend-slots">`
      + `<span class="mv2-legend-lead">slot decisions</span>`
      + seen.map(k => {
          const m = MV_MARK[k];
          return `<span class="mv2-legend-item"><i class="mv2-slot-key" style="`
            + `background:${m.hollow ? 'transparent' : m.fill};border-color:${m.fill}"></i>`
            + `${mvEsc(m.word)}</span>`;
        }).join('')
      + `</div>`;
  }

  function mvLaneLegend(tail) {
    const items = [
      ['ok', 'Passed'], ['bad', 'Failed'], ['hollow', 'Not reached'],
      ['muted', 'No verdict published'], ['norec', 'No record'], ['future', 'Not yet run']
    ];
    return `<div class="mv2-legend">` + items.map(pair =>
      `<span class="mv2-legend-item"><i class="mv2-cell ${pair[0]}"></i>${mvEsc(pair[1])}</span>`
    ).join('') + `${tail || ''}</div>`;
  }

  //: One row per rule, one cell per slot. This is the panel's centre, and what it draws is
  //: VERDICTS rather than values.
  //
  // Measured across every stored session (2026-08-25 to 2026-08-28, all sleeves): every
  // strategy rule carries a null value and `source: not_exposed_by_sleeve`. The thresholds
  // ARE published and are shown on the left; the values are not, and a lane of numbers here
  // would have to invent every point on it. An invented number on this page would be read as
  // the strategy's own, so the lane says what it does not have in its own right-hand column.
  function mvLanes(s) {
    const lanes = s.rule_lanes || [];
    const slots = s.slots || [];
    if (!lanes.length) {
      const firstTime = (slots[0] || {}).time_et;
      return `<div class="mv2-card"><div class="mv2-card-head">` +
        `<span class="mv2-kicker">${mvEsc(s.label)} setup rules</span></div>` +
        mvEmpty('No rule evidence for this session',
          s.status === 'waiting' && firstTime
            ? `The first slot runs at ${firstTime} ET. Nothing is inferred before then.`
            : 'The route wrote no rule diagnostics for this sleeve today.') +
        `</div>`;
    }
    const w = 100 / Math.max(slots.length, 1);
    const rows = lanes.map(L => {
      const cells = (L.cells || []).map((c, i) => {
        const m = MV_CELL[c.state] || MV_CELL.not_published;
        const val = c.value == null ? '' : ' · ' + String(c.value);
        // Muc 4.5 dựng track bằng flex với gap 2px, nên cell chiếm gần trọn bước
        // slot. Ở đây cell là position:absolute nên bước slot phải trừ tay: 0.62
        // để lại 38% khoảng trống và lưới đọc thành những vạch rời, không phải
        // một dải liên tục.
        return `<i class="mv2-cell ${m.cls}" style="left:${(i * w).toFixed(3)}%;` +
          `width:calc(${w.toFixed(3)}% - 2px)" title="${mvEsc(c.time_et)} · ` +
          `${mvEsc(L.label)} · ${mvEsc(m.word + val)}"></i>`;
      }).join('');
      const tone = L.failed > 0 ? 'bad' : L.passed > 0 ? 'ok' : 'muted';
      // Six rules with nothing to report printed the same twenty-nine-word sentence six
      // times down the right edge, which is noise rather than information. The lane keeps
      // the short form, the full sentence stays on hover, and the card head says it once
      // with a count — so the fact is still on the page, stated where it means something.
      const short = MV_LANE_SHORT[L.state_display] || L.state_display;
      return `<div class="mv2-lane">
        <div class="mv2-lane-name">
          <span class="mv2-dot ${tone}"></span>
          <div>
            <div class="mv2-lane-label">${mvEsc(L.label)}</div>
            ${L.threshold_display
              ? `<div class="mv2-lane-thr">needs ${mvEsc(L.threshold_display)}</div>`
              : `<div class="mv2-lane-thr dim">no threshold published</div>`}
          </div>
        </div>
        <div class="mv2-lane-track">${cells}</div>
        <div class="mv2-lane-value ${tone}" title="${mvEsc(L.state_display)}">${mvEsc(short)}</div>
      </div>`;
    }).join('');

    // The slot-decision strip runs under the lanes on the SAME horizontal scale, so a cell
    // and the slot outcome beneath it are the same moment.
    const strip = slots.map((sl, i) => {
      const m = MV_MARK[sl.status] || MV_MARK.unknown;
      const why = sl.reason ? ' · ' + mvPhrase(sl.reason) : '';
      return `<i class="mv2-slot" style="left:${(i * w + w / 2).toFixed(3)}%;` +
        `background:${m.hollow ? 'transparent' : m.fill};border-color:${m.fill}" ` +
        `title="${mvEsc(sl.time_et)} · ${mvEsc(m.word + why)}"></i>`;
    }).join('');
    const axisIdx = [0, Math.floor(slots.length * 0.25), Math.floor(slots.length * 0.5),
                     Math.floor(slots.length * 0.75), slots.length - 1]
      .filter((v, i, a) => v >= 0 && a.indexOf(v) === i && slots[v]);
    const axis = axisIdx.map(i =>
      `<span class="mv2-axis-t" style="left:${Math.min(i * w + w * 0.31, 94).toFixed(2)}%">` +
      `${mvEsc(slots[i].time_et)}</span>`).join('');
    const silent = lanes.filter(L => !L.slots_decided).length;
    const cov = s.coverage || {};
    const tally = (cov.observed_slots != null && cov.expected_slots != null)
      ? `${cov.observed_slots} / ${cov.expected_slots}` : String(slots.length);
    const span = slots.length
      ? `${slots[0].time_et}–${slots[slots.length - 1].time_et} ET` : '';

    return `<div class="mv2-card">
      <div class="mv2-card-head">
        <span class="mv2-kicker">${mvEsc(s.label)} setup rules</span>
        <span class="mv2-mono">one cell per slot · ${mvEsc(span)}</span>
        ${silent ? `<span class="mv2-mono mv2-head-right" title="The detectors return a
          decision rather than the numbers behind it, so these rules have a threshold but no
          published reading.">${silent} of ${lanes.length} rules publish no verdict</span>` : ''}
      </div>
      <div class="mv2-lanes">${rows}</div>
      <div class="mv2-lane mv2-lane-slots">
        <div class="mv2-lane-name"><div>
          <div class="mv2-lane-label">Slot decisions</div>
          <div class="mv2-lane-thr">${mvEsc(
            s.status === 'waiting' ? 'not started' : 'aligned to slot times')}</div>
        </div></div>
        <div class="mv2-lane-track slots">${strip}</div>
        <div class="mv2-lane-value muted">${mvEsc(tally)}</div>
      </div>
      <div class="mv2-lane mv2-lane-axis">
        <div class="mv2-lane-name"></div>
        <div class="mv2-lane-track">${axis}</div>
        <div class="mv2-lane-value"></div>
      </div>
      ${mvSlotLegend(slots)}
      ${mvLaneLegend(mvDeclaredInline(s))}
    </div>`;
  }

  //: Stage 5ZZZ-AM. The detector's rules, one cell per BAR — a different axis from the lanes
  //: above, and kept visibly separate because merging them is what made the lanes unreadable.
  //
  // A lane cell is a SLOT. A grid cell is a BAR. Measured on a real session: within ONE slot
  // the volume rule is answered twelve times pass and ten times fail, so a slot cell has no
  // single value and never had one — which is why every detector rule has read "value not
  // published" on all 291 slot records ever written. A bar cell has exactly one value and it
  // never changes: cutting the window at every five-minute mark and re-asking produced 865
  // verdicts, 80 distinct, and not one that differed between cuts.
  //
  // The three characters come from the backend and are not re-interpreted here. `-` is the
  // one that matters: the gates are ordered and the first refusal returns, so a bar blocked
  // on the EMA never reaches the volume test. "Did not run" is not "ran and passed".
  const MV_GRID_CELL = { P: ['ok', 'passed'], F: ['bad', 'failed'],
                         '-': ['muted', 'an earlier gate returned first'] };

  //: Stage 5ZZZ-AS. The grid's own card, for its own tab.
  //
  // Drawn even with nothing in it. An empty tab is a tab people stop opening, and the reason
  // it is empty is itself the answer: on a Calm day a Normal-only sleeve stops at the regime
  // gate having scanned zero bars, and the slot-level lanes next door already name that.
  function mvBarGridCard(s) {
    const inner = mvBarGrid(s);
    if (inner) return `<div class="mv2-card">${inner}</div>`;
    const st = s.strategy || {};
    const why = (((st.diagnostics || {}).gates || [])
      .find(g => g && g.passed === false) || {}).detail || st.detail || '';
    /* Stage 5ZZZ-DB. `why` được tính từ lâu và chưa bao giờ được vẽ ra.
       Câu thay thế nó bảo người đọc đi tìm: "Setup rules nói nó dừng ở đâu; các chỉ số nó
       dừng trên nằm ở Conditions bên dưới." Nhưng lý do đã nằm ngay trong tay — đọc từ
       chính cổng đầu tiên không đạt, hoặc từ câu chẩn đoán của chiến lược. Ngày 07/09 nó
       chứa:

           global_nkd      "regime 'Calm'; this sleeve trades Normal"
           roska4_stress   "Instruments below open and VWAP 3 (needs >= 4); ..."

       Câu đầu trả lời trong một dòng vì sao sleeve Nikkei không quét bar nào — thứ mà bản
       cũ bắt người đọc suy ra bằng cách mở tab khác. Một ô nói "câu trả lời ở chỗ khác"
       trong khi đang cầm câu trả lời là một ô đang giấu việc của chính nó.

       Câu trỏ vẫn giữ khi KHÔNG có lý do nào đọc được: lúc ấy nó là hướng dẫn thật, không
       phải lời thoái thác. */
    /* Hai loại thông tin, hai dòng — không gộp thành một đoạn văn.
       Câu đầu luôn giống nhau ở mọi sleeve, mọi ngày; câu sau là thứ DUY NHẤT thay đổi và
       là thứ người đọc mở ô này để tìm. Nối chúng lại thì 195 ký tự cuốn thành ba dòng
       trong một ô rộng hơn hai nghìn điểm ảnh, và thứ đáng đọc nhất nằm lẫn ở giữa dòng
       thứ hai.
       Lý do đi cùng một nhãn, theo đúng ngôn ngữ nhãn-rồi-giá-trị mà mọi hàng khác trong
       panel này đã dùng — nên nó đọc như một phép đo chứ không như phần đuôi của một câu. */
    const lead = 'The detector returned before it scanned the window, so there is no '
               + 'per-bar verdict to show.';
    const body = why
      ? `<div class="mv-empty mv-empty-wide"><b>No bar was evaluated</b>` +
        `<span>${mvEsc(lead)}</span>` +
        `<span class="mv2-stopped"><i>Stopped at</i>${mvEsc(why)}</span></div>`
      : mvEmpty('No bar was evaluated',
          `${lead} Setup rules says where it stopped; the readings it stopped on are `
          + `in Conditions below.`);
    return `<div class="mv2-card"><div class="mv2-card-head">
        <span class="mv2-kicker">Detector rules, per bar</span>
        <span class="mv2-mono">no bar evaluated</span>
      </div>${body}</div>`;
  }

  function mvBarGrid(s) {
    const g = s.bar_grid;
    if (!g || !(g.rows || []).length || !(g.bars || []).length) return '';
    const bars = g.bars;
    const w = 100 / bars.length;
    const rows = g.rows.map(r => {
      const cells = String(r.cells || '').split('').map((ch, i) => {
        const [cls, word] = MV_GRID_CELL[ch] || MV_GRID_CELL['-'];
        return `<i class="mv2-cell ${cls}" style="left:${(i * w).toFixed(3)}%;` +
          `width:${(w * 0.62).toFixed(3)}%" title="${mvEsc(String(bars[i] || ''))} · ` +
          `${mvEsc(r.gate)} · ${mvEsc(word)}"></i>`;
      }).join('');
      const tone = r.passed > 0 ? (r.passed === r.reached ? 'ok' : 'warn') : 'bad';
      return `<div class="mv2-lane">
        <div class="mv2-lane-name">
          <span class="mv2-dot ${tone}"></span>
          <div>
            <div class="mv2-lane-label">${mvEsc(String(r.gate).replace(/_/g, ' '))}</div>
            ${r.threshold != null
              ? `<div class="mv2-lane-thr">needs ${mvEsc(_threshWord(r))}</div>`
              : `<div class="mv2-lane-thr dim">no threshold published</div>`}
          </div>
        </div>
        <div class="mv2-lane-track">${cells}</div>
        <div class="mv2-lane-value ${tone}" title="bars that passed, out of the bars that
          reached this rule at all">${r.passed}/${r.reached}</div>
      </div>`;
    }).join('');
    const first = String(bars[0] || '').slice(11, 16);
    const last = String(bars[bars.length - 1] || '').slice(11, 16);
    return `<div class="mv2-bargrid">
      <div class="mv2-card-head">
        <span class="mv2-kicker">Detector rules, per bar</span>
        <span class="mv2-mono">${bars.length} bars · ${mvEsc(first)}–${mvEsc(last)}
          on the sleeve&rsquo;s own clock</span>
        <span class="mv2-mono mv2-head-right" title="A rule is answered once per BAR, not
          once per slot. These verdicts are fixed when the bar closes and do not change when
          a later slot rescans the window.">one cell per bar, not per slot</span>
      </div>
      ${rows}
    </div>`;
  }

  //: The threshold as the sleeve published it — a scalar, or the one-key object the
  //: detectors use. Never re-derived, and never invented when there is none.
  function _threshWord(r) {
    const t = r.threshold;
    if (t == null) return '';
    if (Array.isArray(t)) return t.join(', ');
    if (typeof t === 'object') {
      return Object.entries(t).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ');
    }
    return `${r.comparator ? r.comparator + ' ' : ''}${t}`;
  }

  //: Stage 5ZZZ-AJ. What the sleeve is CONFIGURED to do, under the lanes and visibly apart
  //: from them.
  //
  // These three names — the Japan session window, the max-hold days, the stop-arming rule —
  // sat in the lanes above and reported "value not published" on every slot of every stored
  // session. Correctly, and permanently: the window is applied by slicing the bars before the
  // detector runs, so no bar can fail it, and the other two govern a position that does not
  // exist at the moment of entry. There is no verdict for them to wait for.
  //
  // A lane that must stay empty forever is a lane an operator learns to skip past — and it
  // takes the lanes beside it, the ones that CAN fill, along with it. So they are stated as
  // configuration instead, with the reason on hover. The backend decides which names these
  // are, from the table that declares the rules; this only draws what it is handed.
  /* Muc 4.5 đặt phần này ở CUỐI hàng legend, không phải thành một hàng lane nữa.
     Dời nguyên các node — mỗi item vẫn giữ data-tooltip mang lý do, thứ mà comment
     dưới đây nói rõ là cố ý — chứ không thay bằng một dòng chữ trần. */
  function mvDeclaredInline(s) {
    const cfg = s.declared_config || [];
    if (!cfg.length) return '';
    return `<span class="mv2-legend-declared">declared · ` + cfg.map(c =>
      `<span class="mv2-config-item has-tip tip-top" tabindex="0" ` +
      `data-tooltip="${mvEsc(c.reason)}">${mvEsc(c.label)}` +
      (c.threshold_display ? ` <b>${mvEsc(c.threshold_display)}</b>` : '') +
      `</span>`).join('') + `</span>`;
  }


  //: The price card's own header: the last bar the store carried, and the change from the one
  //: before it. Both come from the payload's bars; neither is a quote. When the sleeve
  //: reported no live bars the numbers are shown dimmed and named `frozen`, because a stale
  //: OHLC printed in the live colour is the one thing this card must never do.
  /* Stage 5ZZZ-CO. Công cụ nào của sleeve đang được vẽ.

     Cần vì bảng cấu hình của panel gán mỗi sleeve đúng MỘT công cụ, và với hai trong bốn
     sleeve điều đó sai: Calm chạy hai, Swing chạy bốn, ngày nào cũng vậy. Hậu quả đo được
     trên trang 2026-09-04: nến MES ~7.724 xếp chồng lên đường M2K ~2.979, chung một trục
     và một con trỏ chữ thập, không dòng nào nói ra.

     Một chip khi sleeve chỉ chạy một công cụ — không có gì để chọn, và chính điều đó là
     thông tin: nó nói sleeve này chỉ đọc một thị trường. Không chip nào khi ngày ấy không
     có bằng chứng per-slot (Stress không ghi diagnostics), và lúc đó dòng nói rõ rằng công
     cụ đang vẽ đến từ bảng cấu hình chứ không từ quan sát. */
  function mvInstBar(s) {
    /* BA trạng thái, và bản đầu gộp mất hai.

       Stage 5ZZZ-CP. `instruments` VẮNG MẶT không phải `instruments` RỖNG. Bản đầu viết
       `s.instruments || []` nên một backend chưa khởi động lại kể từ khi trường này ra đời
       rơi thẳng vào nhánh "phiên này không ghi bằng chứng nào" — một câu sai, nói chắc
       nịch, về một sleeve đã ghi bốn công cụ. Đo được trên máy chủ đang chạy: payload
       không có trường ấy, còn cây bằng chứng có đủ MES · MNQ · MYM · M2K.

       Chính tệp này đã ghi lại cái bẫy đó ở Stage 5ZZH cho `headline_usable`: Python giữ
       module trong bộ nhớ, nên một backend khởi động trước bản sửa cứ thế phục vụ khối cũ
       mãi mãi. Đọc xong rồi vẫn mắc lại. */
    const all = Array.isArray(s.instruments) ? s.instruments : null;
    const cur = s.instrument || '';
    if (all === null) {
      return `<div class="mv2-instbar"><span class="mv2-inst-label">Instrument</span>`
        + `<span class="mv2-inst on">${mvEsc(cur)}</span>`
        + `<span class="mv2-inst-note">the backend has not been restarted since instrument `
        + `selection was added, so it cannot say which instruments this sleeve read</span>`
        + `</div>`;
    }
    if (!all.length) {
      return `<div class="mv2-instbar"><span class="mv2-inst-label">Instrument</span>`
        + `<span class="mv2-inst on">${mvEsc(cur)}</span>`
        + `<span class="mv2-inst-note">from the panel's configuration — this session `
        + `recorded no per-slot evidence to read it from</span></div>`;
    }
    const chips = all.map(i =>
      `<button type="button" class="mv2-inst${i === cur ? ' on' : ''}" `
      + `data-mvinst="${mvEsc(i)}">${mvEsc(i)}</button>`).join('');
    return `<div class="mv2-instbar"><span class="mv2-inst-label">Instrument</span>${chips}`
      + (all.length === 1
          ? `<span class="mv2-inst-note">the only one this sleeve read today</span>`
          : `<span class="mv2-inst-note">${all.length} read today · both charts follow `
            + `this choice</span>`)
      + `</div>`;
  }

  function mvPriceHead(s) {
    const bars = s.bars || [];
    const d = s.data_status || {};
    const stale = d.ok === false && !!d.provider_reason;
    /* Which session these candles are. Same class as the series pane's chip so the
       two read as one pair rather than two unrelated labels. Omitted entirely when the
       field is empty — "bars · --" states a day nobody recorded. */
    const barsDay = s.bars_session_date || '';
    const dayChip = barsDay
      ? `<span class="mv2-sc-day">bars · ${mvEsc(barsDay)}</span>` : '';
    if (!bars.length) {
      return `<div class="mv2-card-head">
        <span class="mv2-kicker">Price</span>${dayChip}
        <span class="mv2-mono dim">${mvEsc(
          mvPhrase(s.bars_note) || 'no bars for this window')}</span></div>`;
    }
    const b = bars[bars.length - 1];
    const p = bars.length > 1 ? bars[bars.length - 2] : null;
    const fmt = v => Number(v).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    let chg = '';
    let chgCls = 'dim';
    if (p) {
      const dv = b.close - p.close;
      const pct = p.close ? (dv / p.close) * 100 : 0;
      chgCls = stale ? 'warn' : dv >= 0 ? 'up' : 'down';
      chg = stale ? 'frozen'
        : `${dv >= 0 ? '+' : ''}${fmt(dv)} (${dv >= 0 ? '+' : ''}${pct.toFixed(2)}%)`;
    }
    /* Stage 5ZZZ-CM. Đầu thẻ nói CÁCH ĐỌC, không đọc hộ một cây nến.

       Bản cũ in O/H/L/C của cây nến CUỐI và không đổi khi rê chuột qua các cây khác — đọc
       lên như một ô giá đang sống, và nó đứng yên. Cùng chỗ ấy còn có dòng
       "no levels published — lines omitted": người đọc không biết "levels" là gì, cũng
       không biết "lines" nào bị bỏ.

       Không mất gì: bốn con số của cây cuối và tình trạng đường vào lệnh chuyển vào tooltip
       của chính chữ "Price", còn giá theo từng phút thì rê chuột đọc được.

       Câu "hover a slot to read both charts at the same minute" KHÔNG đặt ở đây: nó đã là
       nội dung mặc định của dòng đọc-slot ngay dưới hai biểu đồ, và dòng ấy còn biến thành
       số đọc thật khi rê chuột. Đặt cả hai chỗ thì cùng một câu hiện hai lần cách nhau
       100px — đo được trên trang sau bản sửa đầu, và đó là lỗi tôi tự tạo ra. */
    const levels = (s.setup_boundary || {}).levels_armed === true
      ? 'Entry and stop levels are published for this candidate, so they are drawn on the '
        + 'chart.'
      : 'No entry or stop levels were published for this candidate, so none are drawn.';
    const tip = `Last candle on the chart — open ${fmt(b.open)}, high ${fmt(b.high)}, `
      + `low ${fmt(b.low)}, close ${fmt(b.close)}`
      + (chg ? ` (${chg === 'frozen' ? 'the feed was stale when this was read' : chg} `
             + `against the candle before it)` : '')
      + `. ${levels}`;
    return `<div class="mv2-card-head">
      <span class="mv2-kicker has-tip tip-bottom" tabindex="0"
            data-tooltip="${mvEsc(tip)}">Price</span>${dayChip}
    </div>`;
  }

  //: The data-health row, one item per fact, each with its own dot. Four facts and not one
  //: verdict: "provider OK" beside "no bars in the window" is a real and common combination,
  //: and collapsing them into a single green tick loses the half an operator needs.
  function mvDataHealth(s) {
    const d = s.data_status || {};
    const cov = s.coverage || {};
    const stale = d.ok === false && !!d.provider_reason;
    const rows = [
      { label: 'Provider', value: d.provider ? `${d.provider} ${s.bar_interval || ''}`.trim()
                                             : 'not recorded',
        tone: d.provider ? (stale ? 'warn' : 'ok') : 'muted' },
      { label: 'Latest bar', value: d.latest_bar_et ? `${mvClock(d.latest_bar_et)} ET` : 'none stored',
        tone: d.latest_bar_et ? (stale ? 'warn' : 'ok') : 'muted' },
      { label: 'Data join', value: stale ? mvPhrase(d.provider_reason) : mvPhrase(d.splice_result),
        tone: stale ? 'warn' : d.splice_result === 'ok' ? 'ok' : 'muted' },
      { label: 'Slots', value: (cov.observed_slots != null && cov.expected_slots != null)
          ? `${cov.observed_slots} of ${cov.expected_slots}` : `${(s.slots || []).length} declared`,
        tone: (cov.observed_slots != null && cov.observed_slots === cov.expected_slots)
          ? 'ok' : 'muted' }
    ];
    return `<div class="mv2-health"><span class="mv2-kicker">Data health</span>` +
      rows.map(r => `<span class="mv2-health-item">
        <i class="mv2-dot ${r.tone}"></i><span>${mvEsc(r.label)}</span>
        <b class="${r.tone}">${mvEsc(String(r.value))}</b></span>`).join('') + `</div>`;
  }

  //: Stage 5ZZY. The setup card: what this sleeve was waiting for, what came nearest, and
  //: what it would trade at if anything were armed. Three columns where the sleeve publishes
  //: conditions, two where it does not — the grid is set from the data rather than left with
  //: an empty column that reads as a panel that failed to load.
  // Stage 5ZZZ-B. WHERE a panel's numbers came from, said quietly and said always.
  //
  // Three answers, and they are not interchangeable. `Recorded` is what the slot wrote while it
  // was deciding. `Reconstructed` is the same detector replayed afterwards over the bars on
  // disk — a fair answer to "what would it see", and not evidence of what it saw. `Not yet` is
  // a slot whose time has not come, which is never reconstructed.
  //
  // The words come from the payload's own vocabulary. The page maps them to labels; it does not
  // decide which one applies, and it computes no strategy value of its own.
  const MV_SOURCE_WORDS = {
    recorded_runtime: ['RECORDED', 'written by the slot while it was deciding'],
    reconstructed_today: ['RECONSTRUCTED', 'the same detector replayed over the bars on disk '
      + 'after the fact - not official runtime evidence'],
    not_yet_run: ['NOT YET', 'this slot has not run yet'],
    not_reported_by_detector: ['NOT REPORTED', 'the detector does not return this value'],
    // Stage 5ZZZ-F. The fourth word, and the only one the page may show when it has nothing:
    // the BACKEND said it could not read this. It is never inferred from an empty payload -
    // "I could not check" and "I checked and there was nothing" are different answers, and a
    // page that renders them identically has thrown away the difference.
    unavailable: ['UNAVAILABLE', 'the backend reported it could not read this']
  };

  function mvSourceBadge(b) {
    const key = (b && b.diagnostics_source) || '';
    const words = MV_SOURCE_WORDS[key];
    if (!words) return '';
    const extra = [b.last_bar_ts ? 'last bar ' + b.last_bar_ts : '',
                   b.reconstructed_through ? 'through ' + b.reconstructed_through : '']
      .filter(Boolean).join(' · ');
    return `<span class="mv2-src ${mvEsc(key)} has-tip" tabindex="0" data-tooltip="${
      mvEsc(words[1] + (extra ? ' · ' + extra : ''))}">${mvEsc(words[0])}</span>`;
  }

  // Stage 5ZZZ-E. Calm, as two cards that cannot be collapsed into one.
  //
  // DECIDE shows what was fixed by 09:31 and OBSERVE what the 10:00 bar added. The page decides
  // NOTHING about which values belong where — it prints the rows the backend put in each phase,
  // and the backend takes that split from the two dataclasses the detector itself is built on.
  //: Stage 5ZZZ-AS. Calm's own rule verdicts, on the card for the phase that decided them.
  //
  // The sleeve had no reporter at all until this stage: its six declared entry conditions had
  // never carried a verdict anywhere, and what the card showed were measured VALUES -- an ATR,
  // a stop distance -- which are a different thing from a rule that was tested. So a Calm day
  // that did not set up said "did not set up" and stopped there.
  //
  // The verdicts arrive through the diagnostics stream, merged on read; the recorded intent
  // row stays the authority on status and rows. When no diagnostics block exists -- every day
  // before the writer landed -- this draws nothing and the card is exactly what it was.
  function mvCalmGates(b) {
    const gates = (b && b.gates) || [];
    if (!gates.length) return '';
    return `<div class="mv2-calm-gates">` + gates.map(g => {
      const tone = g.passed === true ? 'ok' : g.passed === false ? 'bad' : 'muted';
      // Stage 5ZZZ-BS. The backend formats; this prints. `String(g.value)` put sixteen
      // significant digits on the card next to rows carrying two. The raw value is still the
      // fallback, for a record read by a backend that does not publish the string yet.
      const val = g.display_value || (g.value == null ? '' : String(g.value));
      const thr = _threshWord({
        threshold: g.display_threshold || g.threshold,
        comparator: g.comparator || '' });
      return `<div class="mv2-cond">
        <div><div class="mv2-cond-label"><i class="mv2-dot ${tone}"></i>` +
        `${mvEsc(String(g.gate).replace(/_/g, ' '))}</div>` +
        (thr ? `<div class="mv2-lane-thr">needs ${mvEsc(thr)}</div>` : '') + `</div>
        <div class="mv2-cond-val ${tone}"><b>${mvEsc(val || (g.passed ? 'met' : 'not met'))}</b></div>
      </div>`;
    }).join('') + `</div>`;
  }

  // Stage 5ZZZ-CE. Pair the two phases INSIDE each instrument, instead of giving each
  // phase its own card.
  //
  // The sleeve decides at 09:32 and prices at 10:02, and the only things that change
  // between them are the entry reference and the stop. Split by phase, those two live in
  // different cards more than a screen apart, so answering "what actually moved?" meant
  // holding MES's 09:32 stop in your head while scrolling to its 10:02 one. Split by
  // instrument, DECIDE and OBSERVE sit in adjacent columns and the answer is the two rows
  // that carry a value in both.
  //
  // Rows are the UNION of the two phases in phase order, not just DECIDE's: a row the
  // observe pass introduces would otherwise be dropped silently. A row missing from a
  // phase prints an em dash rather than an empty cell, because "not applicable here" and
  // "we have no value" look identical when both are blank.
  //
  // Gates hang off the instrument and are recorded at DECIDE, so the tally is read from
  // whichever phase carries them and counted from the array — never written as a literal,
  // or it would keep saying 4 after the rule set changed.
  //
  // Only for a basket. One instrument still takes the original per-phase path below,
  // unchanged: the extra structure exists to tell two things apart, and with one thing it
  // is just nesting.
  function mvCalmByInstrument(phases, order) {
    const present = order.filter(([k]) => phases[k]);
    const DROP = new Set(['instrument', 'direction']);
    const forName = (b, name) => {
      const hit = ((b && b.instruments) || []).find(i => i && i.instrument === name);
      if (!hit) return { rows: [], gates: [], direction: '' };
      return {
        rows: (hit.rows || []).filter(r => r && (r.display_value || r.label)
                                           && !DROP.has(String(r.label || '').toLowerCase())),
        gates: hit.gates || [],
        direction: hit.direction || ''
      };
    };

    const names = [];
    present.forEach(([k]) => ((phases[k] || {}).instruments || []).forEach(iv => {
      if (iv && iv.instrument && !names.includes(iv.instrument)) names.push(iv.instrument);
    }));
    /* Stage 5ZZZ-DA. MỘT mã cũng đi đường này. Trước đây ngưỡng là hai, và một mã rơi
       xuống đường vẽ cũ — nên cùng một panel có hai hình dạng không liên quan gì nhau.

       Ý định cũ đúng ở phần nó nói: khi chỉ có một mã thì không cần tiêu đề để phân biệt
       với cái thứ hai. Nhưng nó lấy đi nhiều hơn thế. Đường cũ tách hai pha thành HAI THẺ
       rời, nên bảng hai cột DECIDE | OBSERVE biến mất, và cùng với nó là:

           số cổng đã đạt      "4 / 4 gates met"
           hình dạng bảng      "2 instruments · 7 rows · 4 gates each"
           câu nói cái gì đổi  "chỉ hai hàng có giá thay đổi; phần còn lại chốt trước phiên"
           dấu — ở cột sau     nghĩa "giống hệt cột trước", thứ chỉ nói được khi có hai cột

       Người vận hành mở panel lúc 09:32 thấy một hình, mở lại lúc 10:02 thấy một hình khác
       — và hình đầu ít thông tin hơn, không chỉ khác. Hai pha là một câu chuyện: quyết định
       trước phiên, rồi đọc giá lúc 10:00. Kể nó bằng hai thẻ rời là kể mất mối nối.

       Không có mã nào thì vẫn nhường đường cũ, vì lúc ấy không có gì để dựng bảng. */
    if (!names.length) return '';

    const head = present.map(([k, title, at]) =>
      `<span class="mv2-calm-phase"><b class="mv2-kicker">${mvEsc(title)}</b>` +
      `<span class="mv2-mono">${mvEsc(at)}</span>${mvSourceBadge(phases[k])}</span>`
    ).join('<i class="mv2-calm-sep"></i>');

    /* Panel một mã, cạnh nhau — đúng bản design, đọc từ chính file .dc.html.
       Tôi đã đi vòng qua một bảng chung để bỏ nhãn lặp, và đó là chữa sai bệnh: thứ làm
       khối này dài không phải nhãn lặp mà là CHIỀU CAO HÀNG. Design đặt nhãn và câu phụ
       trên CÙNG một dòng, câu phụ cắt bằng ellipsis, nên mỗi hàng cao một dòng và năm
       hàng vẫn gọn. Nhãn lặp giữa hai panel là cái giá design chấp nhận để mỗi panel tự
       đứng một mình. */
    const panels = names.map(name => {
      const cols = present.map(([k]) => forName(phases[k], name));
      const labels = [];
      const detail = {};
      cols.forEach(c => (c.rows || []).forEach(r => {
        const label = r.label || '';
        if (!labels.includes(label)) labels.push(label);
        if (!detail[label] && r.detail) detail[label] = r.detail;
      }));
      const valueAt = (c, label) => {
        const hit = (c.rows || []).find(r => (r.label || '') === label);
        return hit ? (hit.display_value || '') : '';
      };
      const direction = cols.reduce((a, c) => a || c.direction, '');
      const gates = cols.reduce((a, c) => (a.length ? a : (c.gates || [])), []);
      const met = gates.filter(g => g && g.passed === true).length;

      const colHead = present.map(([, title]) =>
        `<div class="mv2-calm-colhead">${mvEsc(title)}</div>`).join('');

      const body = labels.map(label => {
        /* Hàng không đổi giữa hai pha thì cột sau mang dấu void. Muc 4.8, và lý do nằm
           trong chính chữ của nó: dấu ấy không phải "chưa có giá trị", nó là "cùng giá
           trị với cột bên trái, và nói lại là nói dư". */
        let prev = null;
        const cells = cols.map(c => {
          const v = valueAt(c, label);
          const same = prev !== null && v !== '' && v === prev;
          prev = v === '' ? prev : v;
          return same
            ? `<div class="mv2-calm-cell empty" title="unchanged from ${
                mvEsc(String(present[0][1]))}: ${mvEsc(v)}">—</div>`
            : `<div class="mv2-calm-cell${v ? '' : ' empty'}">${mvEsc(v || '—')}</div>`;
        }).join('');
        return `<div class="mv2-calm-rowlabel">` +
          `<div class="mv2-cond-label">${mvEsc(label)}</div>` +
          (detail[label]
            ? `<div class="mv2-calm-sub" title="${mvEsc(detail[label])}">${
                mvEsc(detail[label])}</div>` : '') +
          `</div>${cells}`;
      }).join('');

      /* GATES là MỘT hàng chip cuốn dòng, không phải một bảng nữa: chấm 4px, nhãn, giá
         trị. Bốn cổng nằm gọn trên một hai dòng thay vì bốn hàng bảng. */
      const gateRow = gates.length
        ? `<div class="mv2-calm-gaterow"><span class="mv2-calm-gateshead">GATES</span>` +
          gates.map(g => {
            const tone = g.passed === true ? 'ok' : g.passed === false ? 'bad' : 'muted';
            const val = g.display_value || (g.value == null ? '' : String(g.value));
            const thr = _threshWord({ threshold: g.display_threshold || g.threshold,
                                      comparator: g.comparator || '' });
            return `<span class="mv2-calm-gate"${thr ? ` title="needs ${mvEsc(thr)}"` : ''}>` +
              `<i class="mv2-dot ${tone}"></i>` +
              `<span class="mv2-calm-gate-name">${
                mvEsc(String(g.gate).replace(/_/g, ' '))}</span>` +
              `<b>${mvEsc(val || (g.passed ? 'met' : 'not met'))}</b></span>`;
          }).join('') + `</div>`
        : '';

      /* Tên mã chỉ in khi có cái thứ hai để phân biệt — giữ nguyên ý định của bản cũ, và
         nó đúng: một tiêu đề chỉ nói "MES" khi MES là thứ duy nhất trên màn hình là một
         dòng không mang tin. CHIỀU cũng vậy thì vẫn in, vì LONG hay SHORT không suy ra
         được từ chỗ khác trong khối này.
         Số cổng đã đạt thì LUÔN in: nó tóm tắt bốn dòng ở dưới thành một con số, và điều
         đó đúng với một mã y như với hai. */
      const soleName = names.length < 2;
      const headBits =
        (soleName ? '' : `<b>${mvEsc(name)}</b>`) +
        (direction ? `<span class="mv2-mono">${mvEsc(direction)}</span>` : '') +
        (gates.length
          ? `<span class="mv2-calm-tally">${met} / ${gates.length} gates met</span>` : '');

      return `<div class="mv2-calm-inst">` +
        (headBits ? `<div class="mv2-calm-inst-head">${headBits}</div>` : '') +
        `<div class="mv2-calm-grid" style="--calm-cols:${present.length}">
          <div></div>${colHead}${body}
        </div>${gateRow}</div>`;
    }).join('');

    const warn = present.map(([k]) => {
      const b = phases[k];
      return b && b.warning ? `<p class="mv-setup-note mv2-warn">${mvEsc(b.warning)}</p>` : '';
    }).join('');

    /* What the card is made of, counted from what was just built rather than
       written down: "2 instruments · 5 rows · 4 gates each". A reader who sees
       five rows on MES wants to know whether MNQ carries the same five before
       comparing the two side by side.
       Only stated when every instrument really does carry the same shape. If one
       recorded a row the other did not, "each" would be false, and a subtitle
       that quietly lies about the table under it is worse than no subtitle. */
    const shape = names.map(name => {
      const cols = present.map(([k]) => forName(phases[k], name));
      const labels = new Set();
      cols.forEach(c => c.rows.forEach(r => labels.add(r.label || '')));
      return labels.size + '/' + cols.reduce((a, c) => (a.length ? a : (c.gates || [])), []).length;
    });
    const uniform = shape.every(s => s === shape[0]);
    const [rowCount, gateCount] = (shape[0] || '0/0').split('/');
    /* "1 instruments · 7 rows · 4 gates each" sai ngữ pháp ở cả hai chỗ: số nhiều, và chữ
       "each" chỉ có nghĩa khi có nhiều hơn một. Một mã thì câu này rút lại còn hình dạng
       bảng, thứ vẫn đáng nói — người đọc muốn biết bảng dài bao nhiêu trước khi cuộn. */
    const meta = uniform && names.length
      ? `<span class="mv2-calm-shape">` +
        (names.length > 1 ? `${names.length} instruments · ` : '') +
        `${rowCount} rows` +
        (Number(gateCount)
          ? ` · ${gateCount} gates${names.length > 1 ? ' each' : ''}` : '') + `</span>`
      : '';

    return `<div class="mv2-calm"><div class="mv2-calm-cards">
      <div class="mv2-card mv2-calm-card mv2-calm-paired">
        <div class="mv2-card-head mv2-calm-phases">${head}${meta}</div>
        <p class="mv-setup-note">Only the two priced rows change; the rest was fixed before the open.</p>
        <div class="mv2-calm-ivs">${panels}</div>${warn}
      </div></div></div>`;
  }

  function mvCalmCards(calm) {
    const phases = (calm && calm.phases) || {};
    const order = [['decide', 'DECIDE', '09:32 ET'], ['observe', 'OBSERVE', '10:02 ET']];
    // Stage 5ZZZ-F. An explicit backend error is shown AS one. Falling through to the empty
    // return below would render the same blank space as "this sleeve has nothing today", and
    // those are opposite facts about whether the panel can be trusted.
    if (calm && calm.error) {
      return `<div class="mv2-card mv2-calm-card"><div class="mv2-card-head">
        <span class="mv2-kicker">Calm</span>
        <span class="mv2-src unavailable">UNAVAILABLE</span></div>
        <p class="mv-setup-note">${mvEsc(calm.error)}</p></div>`;
    }
    if (!order.some(([k]) => phases[k])) return '';
    // A basket day pairs the phases per instrument; anything else falls through to the
    // original per-phase cards below, byte for byte.
    const paired = mvCalmByInstrument(phases, order);
    if (paired) return paired;
    const cards = order.map(([key, title, at]) => {
      const b = phases[key];
      if (!b) return '';
      // Stage 5ZZZ-BJ. One section per INSTRUMENT, because this sleeve trades a basket.
      //
      // The card used to draw `b.rows`, which is the block built from the last recorded row.
      // On 2026-08-31 the sleeve recorded two setups and the card showed one of them, headed
      // MNQ, with no sign the other existed -- MES's stop of 7,600 appeared nowhere on the
      // page, and the four condition values underneath were MNQ's while MES's own were
      // 0.1555 and -0.0030.
      //
      // One instrument still renders exactly as before: no header, no nesting. The extra
      // structure appears only when there is a second thing to tell apart.
      const condRows = list => `<div class="mv2-conds">${list.map(r => `<div class="mv2-cond">
             <div><div class="mv2-cond-label">${mvEsc(r.label || '')}</div>
               ${r.detail ? `<div class="mv2-lane-thr">${mvEsc(r.detail)}</div>` : ''}</div>
             <div class="mv2-cond-val"><b>${mvEsc(r.display_value || '--')}</b></div>
           </div>`).join('')}</div>`;
      const ivs = (b.instruments || []).filter(i => i && (i.rows || []).length);
      const rows = (b.rows || []).filter(r => r && (r.display_value || r.label));
      let body;
      if (ivs.length > 1) {
        body = ivs.map(iv => {
          // The section header already names the instrument and the direction, so the rows
          // that repeat them are dropped here rather than in the payload -- a reader with
          // only the JSON still wants them.
          const said = new Set(['instrument', 'direction']);
          const r2 = (iv.rows || []).filter(r => r && (r.display_value || r.label)
                                                 && !said.has(String(r.label || '').toLowerCase()));
          return `<div class="mv2-calm-inst">
            <div class="mv2-calm-inst-head">
              <b>${mvEsc(iv.instrument || '')}</b>
              ${iv.direction ? `<span class="mv2-mono">${mvEsc(iv.direction)}</span>` : ''}
            </div>
            ${condRows(r2)}${mvCalmGates(iv)}
          </div>`;
        }).join('');
      } else {
        body = rows.length ? condRows(rows)
                           : `<p class="mv-setup-note">${mvEsc(b.summary || '')}</p>`;
      }
      const warn = b.warning
        ? `<p class="mv-setup-note mv2-warn">${mvEsc(b.warning)}</p>` : '';
      return `<div class="mv2-card mv2-calm-card">
        <div class="mv2-card-head">
          <span class="mv2-kicker">${mvEsc(title)}</span>
          <span class="mv2-mono">${mvEsc(at)}</span>${mvSourceBadge(b)}
        </div>
        ${(rows.length || ivs.length > 1)
          ? `<p class="mv-setup-note">${mvEsc(b.summary || '')}</p>` : ''}
        ${body}${ivs.length > 1 ? '' : mvCalmGates(b)}${warn}
      </div>`;
    }).join('');
    return `<div class="mv2-calm"><div class="mv2-calm-cards">${cards}</div></div>`;
  }

  //: Stage 5ZZZ-BA. The SESSION as a line, beside the snapshot the card already shows.
  //:
  //: A snapshot of this sleeve is actively misleading and the numbers say why: slots fire on
  //: the five-minute boundary, so the bar the detector last evaluated is seconds old. Measured
  //: across 2026-08-31, the thirteen slots that carried numbers read
  //:
  //:    bar volume    0  0  0  0  5  0  6  14  0  0  4  1  0
  //:    ten-bar avg   5.8 .................................. 32.0
  //:
  //: -- a column of zeros beside a baseline that grew five-fold. So the volume pane draws the
  //: TEN-BAR AVERAGE as the line, because that is measured on closed bars, and the slot's own
  //: reading as dots, because it is a bar still forming. Drawing the dots as a line would
  //: assert a shape the data does not have.
  // Stage 5ZZZ-BQ. The sessions that exist, from the backend's own listing of what is on
  // disk. Never a calendar range: a picker offering days nothing ever wrote hands back an
  // empty panel for a day that was never recorded, which is the absence-with-no-reason this
  // band has spent several stages removing.
  //
  // Two kinds of session, and the difference is stated rather than left to be discovered.
  // Measured 2026-09-01: signals reach back to 25/08, per-slot diagnostics begin 31/08. A day
  // without the second still shows its condition rows -- the detector is replayed over the
  // bars on disk, which took about eighty seconds on the first request for 26/08 -- but the
  // session chart stays empty, because no per-slot record exists to draw.
  function mvDayBar() {
    const el = $('marketViewDays');
    if (!el) return;
    const sessions = (state.marketView || {}).sessions || [];
    if (!sessions.length) { el.innerHTML = ''; return; }
    const sel = state.mvDay;
    const chips = sessions.map(row => {
      const on = sel ? row.day === sel : row.is_today;
      const cls = ['mv2-day', on ? 'on' : '', row.has_diagnostics ? '' : 'thin']
        .filter(Boolean).join(' ');
      const tip = row.has_diagnostics
        ? 'Per-slot diagnostics were recorded for this session: conditions and the session '
          + 'chart both come from what the slots wrote while they ran.'
        : 'No per-slot diagnostics were recorded for this session. The conditions are '
          + 'replayed over the bars on disk and labelled RECONSTRUCTED; the session chart '
          + 'stays empty, because there is no per-slot record to draw.';
      return `<button type="button" class="${cls}" data-mvday="${mvEsc(row.day)}" `
           + `title="${mvEsc(tip)}">${mvEsc(row.day.slice(5))}`
           + `${row.is_today ? '<i>today</i>' : ''}</button>`;
    }).join('');
    const past = sel && !sessions.some(r => r.day === sel && r.is_today);
    /* Why some chips are dim. The tooltip on each thin chip already says it, but a
       tooltip is only read by someone who already suspected something — the row
       otherwise looks like four days rendered wrong. Shown only when a thin day is
       actually on the row, so the line never explains a state nobody can see, and
       only when the past-session notice is not already occupying the same slot. */
    const thin = sessions.some(row => !row.has_diagnostics);
    /* Stage 5ZZZ-CM. Câu về ngày mờ chuyển vào tooltip của chính chữ "Session".

       Nó từng chiếm cả một dòng bên phải hàng chip để giải thích một chi tiết mà người đọc
       chỉ cần khi họ đã để ý thấy vài chip mờ. Lo ngại ghi ở chú thích cũ vẫn đúng — "tooltip
       chỉ được đọc bởi người đã nghi ngờ điều gì" — nên chỗ đặt mới là chữ ĐẦU HÀNG, thứ mắt
       đi qua trước khi tới các chip, và nó có gạch chân chấm để lộ ra là hover được.

       Thông báo "đang xem phiên cũ" thì Ở LẠI trên dòng: đó không phải chú thích, đó là
       trạng thái của thứ đang hiện — bỏ nó đi thì cả băng nói về một ngày khác mà không
       nói ra. */
    const label = thin
      ? `<span class="mv2-day-label has-tip tip-bottom" tabindex="0" data-tooltip="`
        + mvEsc('These are the sessions on disk. A dimmed day recorded no per-slot '
                + 'diagnostics: its condition rows are replayed from the bars on disk and '
                + 'labelled RECONSTRUCTED, and its session chart stays empty because there '
                + 'is no per-slot record to draw.') + `">Session</span>`
      : `<span class="mv2-day-label">Session</span>`;
    el.innerHTML = label + chips
      + (past ? `<span class="mv2-day-note">Reviewing a past session — this band only. `
              + `The job list and open issues below stay on the live day.</span>` : '');
    el.querySelectorAll('[data-mvday]').forEach(b => {
      b.onclick = () => {
        const d = b.getAttribute('data-mvday');
        const isToday = sessions.some(r => r.day === d && r.is_today);
        state.mvDay = isToday ? null : d;
        el.classList.add('loading');
        poll();
      };
    });
    el.classList.remove('loading');
  }

  function mvSlotChart(s) {
    const series = ((s.strategy || {}).slot_series) || [];
    /* `p.close != null` FIRST. `Number(null)` is 0 and `Number.isFinite(0)` is true, so a
       bare Number() counts a slot that recorded nothing as one that closed at zero -- the
       same trap this file already names thirty lines further down, and the guard here was
       written without it.
       Measured on the Stress sleeve, 2026-09-03: eighteen slots, every reading null, and all
       eighteen passed this filter. The pane then drew a chart of nothing -- no line, no dot,
       and a price axis running from -Infinity to Infinity -- instead of saying that no slot
       has carried a number yet. */
    const withPrice = series.filter(
      p => p && p.close != null && Number.isFinite(Number(p.close)));
    if (withPrice.length < 2) {
      const ran = series.length;
      // Stage 5ZZZ-BQ. On a session opened from the bar, an empty chart usually means the
      // per-slot store does not reach back that far -- not that the sleeve did nothing. The
      // conditions above it are real, replayed from the bars; only the per-slot line is
      // missing. Two very different facts behind one empty box.
      const sess = ((state.marketView || {}).sessions || [])
        .find(r => r.day === ((s.strategy || {}).slot_series_session || state.mvDay));
      const noStore = sess && sess.has_diagnostics === false;
      /* Stage 5ZZZ-CU. Không có slot nào, và cũng không có lý do nào để nêu → không dựng gì.
         Câu cũ ở đây là 'No slot has recorded a reading for this session yet.' — nó chỉ nói
         lại điều mà một ô trống đã nói, và nó chiếm một khối 250px ngay dưới biểu đồ giá để
         nói điều đó. Ba nhánh còn lại ở dưới thì giữ: mỗi nhánh mang một sự thật KHÁC nhau
         về cùng một ô trống (kho slot chưa với tới ngày này / bộ dò không đo giá đóng cửa /
         cửa vào chưa mở), và những sự thật ấy không có ở chỗ nào khác trên trang. */
      if (!ran && !noStore) return '';
      return `<div class="mv2-slotchart-empty">${mvEsc(
        noStore ? `No per-slot record exists for this session — the per-slot store begins `
                  + `2026-08-31. The conditions above were replayed over the bars on disk, `
                  + `which is why they are there and this line is not.`
        /* Two different silences, and the old sentence gave the same reason for both.
           "The line starts when the entry window opens" is true only while the window is
           shut. Measured on the Stress sleeve at 11:53 ET, an hour into a window that opens
           at 10:35 with sixteen of twenty-four slots already run: it recorded on every one
           of them and published no price on any, because its detector does not measure one.
           It answers in basket counts -- how many instruments sit below open and VWAP, how
           many gapped down -- and this pane only knows how to read a close. Blaming the
           window there sends the reader to wait for something that has already happened. */
        : ran && withPrice.length === 0
            ? `${ran} slot${ran === 1 ? '' : 's'} recorded and none published a close price. `
              + `What this sleeve's detector does publish is in the Detector rules tab.`
        : `${ran} slot${ran === 1 ? '' : 's'} recorded, ${withPrice.length} carrying `
              + `numbers — the line starts when the entry window opens and the detector has `
              + `bars to walk.`)}</div>`;
    }
    /* Stage 5ZZZ-CR. CÙNG lề với biểu đồ nến ngay trên, không phải lề riêng.
       Lề riêng (52 trái / 12 phải) buộc trục phải nằm bên TRÁI, vì 12 đơn vị không đủ chỗ
       cho "7,727.02" — nên hai biểu đồ xếp chồng đọc trục ở hai phía đối nhau. Dùng chung
       MV_PAD thì hai khung vẽ trùng nhau, và đó cũng là điều kiện để con trỏ chữ thập dóng
       hai pane theo cùng một phút. */
    const W = 1000, H = 250, padL = MV_PAD.L, padR = MV_PAD.R, padT = 14, padB = 24;
    /* Cùng lý do và cùng cách với biểu đồ nến ở trên: luật 5 cấm <text> trong một SVG
       kéo lệch, nên chữ ra một lớp HTML phủ lên, định vị bằng phần trăm của viewBox. */
    const scText = [];
    const SC_ANCHOR = { start: '0', middle: '-50%', end: '-100%' };
    const scLab = (px, py, txt, anchor) => {
      scText.push(`<span class="mv2-sc-lab" style="left:${(px / W * 100).toFixed(3)}%;`
        + `top:${(py / H * 100).toFixed(3)}%;--ax:${SC_ANCHOR[anchor || 'start']}">`
        + `${txt}</span>`);
      return '';
    };
    const priceH = 104, gap = 18;
    const volTop = padT + priceH + gap, volH = H - padB - volTop;
    const n = series.length;
    /* The same horizontal span the price chart gave its slots, when it published one
       for the same number of slots. The two panes are read as one picture: a reader
       follows a minute down from a candle to the close line. Before this the series
       ran 52 → 988 while the candles kept their slots between 342 → 881, so nothing
       lined up and the line looked stretched across width the candles never used.

       Only adopted when the counts match. A span from a chart with a different number
       of slots would line the two up by index onto different minutes, which is worse
       than not lining them up at all. */
    /* ...and only when the two panes are the SAME SESSION. Counting slots is not enough:
       the candle store is appended once a day, so during a live window its newest bars are
       the previous day's while the slot series is today's. The counts still match — 22 slots
       either way — so the old test adopted the span and lined today's slots up against
       yesterday's candles, on one axis, with one synced crosshair. The note printed under
       the head said "the crosshair matches within each pane, not across them" while the
       panes were in fact matched: the sentence was true about the intent and false about
       the picture. Sharing is now refused when the sessions differ, which is what makes
       that sentence true and what rule 8 asks for. */
    const _barsDay = s.bars_session_date || '';
    const _seriesDay = ((s.strategy || {}).slot_series_session) || '';
    const sameSession = !_barsDay || !_seriesDay || _barsDay === _seriesDay;
    /* Matched by the slot's own MINUTE, not by counting slots.
       Counting was the first rule and it refuses too often to be useful: the price chart
       marks every slot the session has while the series carries only the slots that recorded
       a reading, so an ordinary morning — twenty of twenty-two decided — had 22 against 20
       and the panes fell apart, on a day they describe the same session at the same minutes.
       Reading the minute is both safer and looser: every point lands where the candle above
       it stands, and a point whose minute the price chart never drew makes the whole pane
       fall back rather than putting one dot in a place it does not belong. */
    const _wantKey = `${s.instrument || ''}|${_barsDay}`;
    const _slotMap = (mvSlotX && mvSlotX.key === _wantKey) ? mvSlotX.x : null;
    const mapped = (sameSession && _slotMap && n > 1)
      ? series.map(p => _slotMap[String(p.slot_time || '')]) : null;
    /* Một phút thiếu từng làm mất cả trục. `every` nghĩa là chỉ cần MỘT slot mà biểu đồ
       nến không vẽ là cả pane quay về trải đều các điểm ra hết chiều ngang — nên những
       slot ĐÃ chạy bị đẩy khỏi cây nến ngay trên đầu chúng, và hai pane thôi dóng được
       với nhau đúng vào lúc người đọc cần đối chiếu nhất.
       Lời từ chối ấy nhắm đúng mối nguy (một điểm vẽ vào chỗ nó không thuộc về) nhưng trả
       giá bằng mọi điểm còn lại. Giờ giữ trục và bỏ đúng slot không đặt được: một phút
       biểu đồ nến không vẽ thì ở đây cũng là một chỗ trống, còn mọi điểm còn lại vẫn nằm
       dưới cây nến của nó. Sàn là hai điểm đặt được — một điểm không mô tả nổi một span. */
    const placedCount = mapped ? mapped.filter(v => typeof v === 'number').length : 0;
    const shared = (mapped && placedCount >= 2) ? mapped : null;
    const unplaced = i => shared !== null && typeof shared[i] !== 'number';
    const droppedSlots = shared ? series.filter((_, i) => unplaced(i)) : [];
    const x = i => shared
      ? shared[i]
      : padL + (n < 2 ? 0 : i * (W - padL - padR) / (n - 1));

    // `Number(null)` is 0 and `Number.isFinite(0)` is true, so a bare Number() turns every
    // slot that has not run yet into a real zero. Measured on the first render: nine empty
    // slots dragged the price axis to -7,975.88 for an instrument trading at 66,000, and the
    // close line ran flat along the floor before jumping. An impossible axis value is the
    // cheapest way this class of bug ever announces itself.
    const num = v => {
      if (v === null || v === undefined || v === '') return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    // Một slot mà trục chung không có chỗ cho nó là một CHỖ TRỐNG trong mọi chuỗi, chứ
    // không phải một điểm ở một x bịa ra: đường gãy ở đó đúng như nó gãy ở một slot không
    // có giá.
    const pick = k => series.map((p, i) => unplaced(i) ? null : num(p[k]));
    const close = pick('close'), ema = pick('ema');
    const avgv = pick('avg_volume'), vol = pick('volume');
    const thr = pick('surge_threshold');

    const finite = a => a.filter(v => v !== null);
    const pAll = finite(close).concat(finite(ema));
    let pLo = Math.min(...pAll), pHi = Math.max(...pAll);
    if (pHi === pLo) { pHi = pLo + 1; pLo = pLo - 1; }
    const padY = (pHi - pLo) * 0.12;
    pLo -= padY; pHi += padY;
    const py = v => padT + priceH - ((v - pLo) / (pHi - pLo)) * priceH;

    const vAll = finite(avgv).concat(finite(vol)).concat(finite(thr));
    const vHi = Math.max(1, ...vAll);
    const vy = v => volTop + volH - (v / vHi) * volH;

    // A gap in the data is a fact about the session -- the line breaks rather than jumping
    // across it, which would draw a slope nobody measured.
    const path = (arr, cls) => {
      const runs = [];
      let cur = [];
      arr.forEach((v, i) => {
        if (v === null) { if (cur.length > 1) runs.push(cur); cur = []; return; }
        cur.push(`${x(i).toFixed(1)},${py(v).toFixed(1)}`);
      });
      if (cur.length > 1) runs.push(cur);
      return runs.map(r => `<polyline class="${cls}" points="${r.join(' ')}"></polyline>`).join('');
    };
    // Stage 5ZZZ-BO. The bar-volume readings are JOINED now, and the gate's own threshold is
    // drawn beside them.
    //
    // They were dots on the argument that a line would assert a shape the data does not have.
    // That was weaker than it sounded: slots fire on the five-minute boundary, so every point
    // is sampled at the SAME phase of its bar, and a consistently sampled series is a series.
    // The gaps are what needed care, and `volLine` breaks at them like every other line here.
    //
    // Without a reference the readings said little -- measured on 2026-08-31, 1 of 13 cleared
    // the gate's threshold and the chart gave no way to see which. The threshold comes from
    // the gate's own report, per slot, so it is absent on a day the gate was never reached.
    const volLine = (arr, cls) => {
      const runs = [];
      let cur = [];
      arr.forEach((v, i) => {
        if (v === null) { if (cur.length > 1) runs.push(cur); cur = []; return; }
        cur.push(`${x(i).toFixed(1)},${vy(v).toFixed(1)}`);
      });
      if (cur.length > 1) runs.push(cur);
      return runs.map(r => `<polyline class="${cls}" points="${r.join(' ')}"></polyline>`).join('');
    };
    const volPath = () => volLine(avgv, 'mv2-sc-avgv') + volLine(thr, 'mv2-sc-thr')
      + volLine(vol, 'mv2-sc-volline');
    // The dot stays on top of its line: a reading that clears the threshold should be findable
    // at a glance, and a line alone hides where the samples actually are.
    /* Ellipses, not circles: this svg is preserveAspectRatio="none" too, so a circle
       here renders as a flattened oval exactly as the slot dots did. next.js corrects
       rx to the measured x-scale. */
    const volDots = vol.map((v, i) => v === null ? '' :
      `<ellipse class="mv2-sc-vol${thr[i] !== null && v > thr[i] ? ' over' : ''}" `
      + `cx="${x(i).toFixed(1)}" cy="${vy(v).toFixed(1)}" rx="2.6" ry="2.6"></ellipse>`
    ).join('');

    /* A marker on every reading, on all four lines — the design puts one on each.
       A line alone says where the value went; the dots say where it was MEASURED, and
       with 22 slots across a wide pane those are not the same question. Close and bar
       volume are filled; the trend filter and the ten-bar average are hollow, matching
       the design's split between a reading and a derived line. */
    const dotsFor = (arr, cls, r, plot) => arr.map((v, i) => v === null ? '' :
      `<ellipse class="${cls}" cx="${x(i).toFixed(1)}" `
      + `cy="${plot(v).toFixed(1)}" rx="${r}" ry="${r}"></ellipse>`).join('');
    const closeDots = dotsFor(close, 'mv2-sc-dot mv2-sc-dot-close', 2.6, py);
    const emaDots   = dotsFor(ema,   'mv2-sc-dot mv2-sc-dot-ema',   2.4, py);
    const avgvDots  = dotsFor(avgv,  'mv2-sc-dot mv2-sc-dot-avgv',  2.4, vy);

    const fmtP = v => Number(v).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const ticks = [
      // Bên PHẢI và căn PHẢI, giống biểu đồ nến ngay trên. Căn phải là điều kiện để hai
      // cột số thẳng hàng: căn trái thì "0" và "13,810" lệch nhau đúng bằng hiệu số chữ số.
      scLab(W - 6, padT + 8, mvEsc(fmtP(pHi)), 'end'),
      scLab(W - 6, padT + priceH, mvEsc(fmtP(pLo)), 'end'),
      scLab(W - 6, volTop + 8,
            mvEsc(Number(Math.round(vHi)).toLocaleString('en-US')), 'end'),
      scLab(W - 6, volTop + volH, '0', 'end'),
    ].join('');
    const drawn = series.map((_, i) => i).filter(i => !unplaced(i));
    /* Nhãn thời gian mô tả TRỤC, không mô tả chuỗi.
       Khi trục là của biểu đồ nến, các điểm của chuỗi có thể chỉ chiếm một góc của nó.
       Đo được trên phiên đang chạy: 22 slot trải hết bề ngang, nhưng chỉ 3 slot ghi được
       số liệu và cả ba nằm ở cuối cửa sổ — khoảng 10% chiều ngang. Lấy mốc từ chúng thì
       ba nhãn dồn vào mép phải, đè nhau 13,3px, và không ai đọc được trục bắt đầu từ đâu.
       Lấy từ chính trục thì nhãn trải đúng bề ngang mà cây nến ở trên đang trải.
       Khi KHÔNG chung trục, trục là của riêng pane này nên mốc vẫn lấy từ chuỗi. */
    const tickPts = (shared && _slotMap)
      ? Object.keys(_slotMap).map(t => ({ t, cx: _slotMap[t] }))
          .filter(q => typeof q.cx === 'number').sort((a, b) => a.cx - b.cx)
      : drawn.map(i => ({ t: String((series[i] || {}).slot_time || ''), cx: x(i) }));
    /* Ba mốc, rồi lọc. Hai chuyện phải lọc, cả hai đã đo được trên trang thật:
       - Trùng chỉ số thì trùng nhãn. Với hai điểm, [đầu, giữa, cuối] là [0, 0, 1] nên nhãn
         đầu được vẽ HAI lần khít lên nhau — đo được 41,7px đè nhau.
       - Hai mốc quá gần nhau thì chữ đè nhau dù chỉ số khác. Nhãn "02:45" đo được rộng
         28px trong một pane 1013px với viewBox 1000, tức ~28 đơn vị viewBox. 70 là hai
         nửa nhãn cộng một khoảng thở, không phải một con số chọn cho vừa mắt.
       Bỏ mốc GIỮA trước, giữ hai đầu: hai đầu là thứ nói trục chạy từ đâu đến đâu. */
    const MIN_TICK_GAP = 70;
    const three = tickPts.length < 2 ? tickPts.slice(0, 1)
      : [tickPts[0], tickPts[Math.floor((tickPts.length - 1) / 2)], tickPts[tickPts.length - 1]];
    const at = [];
    three.forEach(q => {
      if (!q.t) return;
      const prev = at[at.length - 1];
      if (prev && Math.abs(q.cx - prev.cx) < MIN_TICK_GAP) return;
      at.push(q);
    });
    const times = at.map((q, k) => scLab(q.cx, H - 6, mvEsc(q.t),
      k === 0 ? 'start' : k === at.length - 1 ? 'end' : 'middle')).join('');

    const forming = series.some(p => p.last_bar_complete === false);

    // Stage 5ZZZ-BP. Two charts, two days, one of them labelled.
    //
    // The candle chart above prints "Stored session 2026-08-28" when its bars are older than
    // the panel's day; this chart draws TODAY's slots and printed no date at all. On
    // 2026-09-01 the two sat side by side -- candles from the 28th, line from the 1st -- and
    // nothing on the page said they were different days. The date is stated unconditionally
    // here: a label that appears only when something is wrong cannot be used to check that
    // nothing is.
    // Read from the SAME object the points came out of. The first version reached for
    // `s.slot_series_session` while the series is at `s.strategy.slot_series`, so the chip
    // silently rendered nothing -- the payload check passed and only the page showed it. A
    // date that is absent when the field moves is the defect this chip exists to prevent.
    const chartDay = ((s.strategy || {}).slot_series_session) || '';

    // Whether any rule consumed these readings. The verdict is copied from the slot's own
    // regime gate; slots that recorded no verdict are not counted either way, so an
    // unanswered session never produces the sentence.
    const judged = series.filter(p => p.regime_passed === true || p.regime_passed === false);
    const refused = judged.length > 0 && judged.every(p => p.regime_passed === false);
    const refusedLabel = refused ? String(judged[judged.length - 1].regime || '') : '';
    const thrSeen = finite(thr).length > 0;

    /* The soft wash under the close line, as the design draws it. Built from the SAME
       runs the line uses, so a gap in the data leaves a gap in the fill — a continuous
       wash under a broken line would quietly claim the missing minutes were measured.
       The baseline is the volume rule, not the bottom of the box, so it cannot spill
       into the volume pane below. */
    const closeArea = (arr) => {
      const base = (volTop - gap / 2).toFixed(1);
      const runs = [];
      let cur = [];
      arr.forEach((v, i) => {
        if (v === null) { if (cur.length > 1) runs.push(cur); cur = []; return; }
        cur.push([x(i), py(v)]);
      });
      if (cur.length > 1) runs.push(cur);
      return runs.map(r => {
        const pts = r.map(q => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' ');
        return `<polygon class="mv2-sc-closefill" points="`
             + `${r[0][0].toFixed(1)},${base} ${pts} `
             + `${r[r.length - 1][0].toFixed(1)},${base}"></polygon>`;
      }).join('');
    };
    /* G2. The candles and the slot series can be two different sessions: the bars come
       from the instrument store, the slot series from what the slots recorded. When they
       differ the panes are not two views of one day, and a crosshair that lines them up
       would be lining up two different afternoons.

       Said out loud rather than normalised to one day: picking one would silently throw
       away the other, and which one is right is not this renderer's call. */
    const barsDay = s.bars_session_date || '';
    const dayMismatch = barsDay && chartDay && barsDay !== chartDay
      ? `<div class="mv2-tabnote">Candles are ${mvEsc(barsDay)}; the slot series is `
        + `${mvEsc(chartDay)}. The crosshair matches within each pane, not across them.`
        + `</div>` : '';

    /* Bản sửa làm BỚT hiển thị thì phải nói thứ bị bớt đi đâu. Không có dòng này, một
       slot biến mất khỏi chart trông y hệt một slot chưa chạy. */
    const droppedNote = droppedSlots.length
      ? `<div class="mv2-tabnote">${droppedSlots.length} slot`
        + `${droppedSlots.length === 1 ? '' : 's'} not drawn here — `
        + mvEsc(droppedSlots.map(p => String(p.slot_time || '?')).join(', '))
        + ` ${droppedSlots.length === 1 ? 'has' : 'have'} no candle above `
        + `${droppedSlots.length === 1 ? 'it' : 'them'}. Every other slot keeps the price `
        + `chart's axis, so the two panes still line up minute for minute.</div>`
      : '';
    return `<div class="mv2-slotchart">
      ${dayMismatch}${droppedNote}
      <div class="mv2-sc-head">
        <span class="mv2-kicker">Across the session</span>
        ${chartDay ? `<span class="mv2-sc-day">slots · ${mvEsc(chartDay)}</span>` : ''}
        <span class="mv2-sc-key"><i class="mv2-sc-k-close"></i>close</span>
        <span class="mv2-sc-key"><i class="mv2-sc-k-ema"></i>trend filter</span>
        <span class="mv2-sc-key"><i class="mv2-sc-k-avgv"></i>10-bar volume</span>
        <span class="mv2-sc-key"><i class="mv2-sc-k-vol"></i>bar volume</span>
        ${thrSeen
          ? `<span class="mv2-sc-key"><i class="mv2-sc-k-thr"></i>surge threshold</span>`
          : `<span class="mv2-sc-key mv2-sc-key-off">surge threshold — not compared</span>`}
      </div>
      <!-- data-xspan says whether this pane adopted the price chart's slot span.
           Stated rather than left to be inferred: a reader of the DOM cannot tell a
           shared axis from a coincidence, and the crosshair layer must not guess. -->
      <div class="mv2-sc-frame">
      <svg class="mv2-sc-svg" data-xspan="${shared ? 'shared' : 'own'}"
           viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <line class="mv2-sc-rule" x1="${padL}" x2="${W - padR}" y1="${(volTop - gap / 2).toFixed(1)}" y2="${(volTop - gap / 2).toFixed(1)}"></line>
        <defs><linearGradient id="mv2CloseFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#8dc0f7" stop-opacity=".20"></stop>
          <stop offset="100%" stop-color="#8dc0f7" stop-opacity="0"></stop>
        </linearGradient></defs>
        ${closeArea(close)}${path(ema, 'mv2-sc-ema')}${path(close, 'mv2-sc-close')}${volPath()}${avgvDots}${emaDots}${closeDots}${volDots}${ticks}${times}
      </svg>
      <div class="mv2-sc-labels">${scText.join('')}</div>
      </div>
      ${refused ? `<div class="mv2-tabnote">The market was in ${mvEsc(refusedLabel)}, and `
        + `that is the first thing every slot checks. All ${judged.length} slot`
        + `${judged.length === 1 ? '' : 's'} that reached a verdict stopped right there, so no `
        + `rule after it ever read these numbers. What the chart shows is what the session `
        + `did — not the path to a decision. Nothing was measured against a threshold, so no `
        + `threshold line is drawn.</div>` : ''}
      ${forming ? `<div class="mv2-tabnote">Each dot is the bar the slot was looking at, and `
        + `that bar had only just opened. The line above it is the average of the ten bars `
        + `before it, all of which had closed.</div>` : ''}
    </div>`;
  }

  function mvSetupCard(s, opts) {
    const b = s.setup_boundary || {};
    const metrics = (b.metrics || []).filter(m => m && (m.display_value || m.label));
    const levels = (b.price_levels || []).filter(l => Number.isFinite(Number(l.price)));
    const armed = b.levels_armed === true;
    const kind = {
      metric_boundary: 'Metric setup',
      entry_after_setup_only: 'Price setup after setup bar',
      price_boundary: 'Price trigger',
      two_phase: 'Two-phase decision'
    }[b.boundary_type] || 'Setup';

    const bars = s.bars || [];
    const lastBar = bars.length ? bars[bars.length - 1] : null;
    const fmt = v => Number(v).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const lastSlot = (s.slots || []).slice().reverse().find(x => x.status !== 'future');

    // Nearest miss. Comes from the payload's own nearest-failed-condition where the sleeve
    // publishes one; otherwise from the rule lanes, which is the only other place a real
    // "this is what did not pass" exists. Never synthesised from the two.
    const near = b.nearest_failed_condition || null;
    const failedLane = (s.rule_lanes || []).find(L => L.failed > 0);
    let miss;
    if (near && near.label) {
      miss = `${near.label} ${near.display_value || ''}`.trim() +
             (near.display_threshold ? ` · needs ${near.display_threshold}` : '') +
             (near.display_distance ? ` · ${near.display_distance}` : '');
    } else if (failedLane) {
      miss = `${failedLane.label} failed on ${failedLane.failed} of ` +
             `${failedLane.slots_decided} decided slots` +
             (failedLane.threshold_display ? ` · needs ${failedLane.threshold_display}` : '');
    } else if (s.status === 'waiting') {
      miss = 'No evaluation yet, so there is no distance to report.';
    } else {
      // The honest answer, and the one this panel exists to be able to give: the rules were
      // evaluated inside the detector and it returned no numbers, so nothing can be measured
      // as "nearest". Saying "all conditions met" here would be a claim nobody made.
      miss = 'No condition reported a value, so there is no nearest miss to measure.';
    }

    const cols = metrics.length ? 'mv2-setup-3' : 'mv2-setup-2';
    // Stage 5ZZZ-AW. TWO groups, because these rows are two different kinds of thing.
    //
    // Seven of the eight carry no verdict on purpose -- the detector reports a reading and
    // never a pass/fail for them, and the one stage that did stamp verdicts on them measured
    // 52.7% agreement with the gate it was read as reporting. Printing "NOT REPORTED" beside
    // each one put a verdict-shaped hole where no verdict can ever go, and the page then read
    // as eight broken conditions rather than seven readings and one condition.
    const decided = metrics.filter(m => m.passed === true || m.passed === false);
    const readings = metrics.filter(m => m.passed !== true && m.passed !== false);
    const condRow = (m, verdict) => {
      const tone = m.passed === true ? 'ok' : m.passed === false ? 'bad' : 'muted';
      return `<div class="mv2-cond">
        <div>
          <div class="mv2-cond-label"><i class="mv2-dot ${verdict ? tone : 'muted'}"></i>${mvEsc(m.label || '')}</div>
          ${m.display_threshold
            ? `<div class="mv2-lane-thr">needs ${mvEsc(m.display_threshold)}</div>` : ''}
        </div>
        <div class="mv2-cond-val">
          <b>${mvEsc(m.display_value || '--')}</b>
          ${verdict ? `<em class="${tone}">${m.passed === true ? 'PASS' : 'FAIL'}</em>` : ''}
        </div>
      </div>`;
    };
    // The newest bar is normally still forming: slots fire on the five-minute boundary, so a
    // volume of 0 against a ten-bar average is a bar seconds old, not a dead market. Only
    // said when the payload actually measured it -- `null` means nobody looked.
    const forming = b.last_bar_complete === false
      ? `<div class="mv2-tabnote">Newest bar still forming${b.last_bar_ts
          ? ` — ${mvEsc(String(b.last_bar_ts))}` : ''}, so its volume is partial.</div>` : '';
    const conditions = metrics.length ? `<div class="mv2-setup-col">
      ${decided.length ? `<div class="mv2-kicker">Conditions</div>
        <div class="mv2-conds">${decided.map(m => condRow(m, true)).join('')}</div>` : ''}
      ${readings.length ? `<div class="mv2-kicker">Readings — measured, not a pass/fail</div>
        <div class="mv2-conds">${readings.map(m => condRow(m, false)).join('')}</div>
        ${forming}` : ''}
    </div>` : '';

    const levelsCol = `<div class="mv2-setup-col">
      <div class="mv2-kicker">Trade levels</div>
      ${levels.length ? `<div class="mv2-levels">${levels.map(l =>
        `<div class="mv2-level${l.armed === true && armed ? '' : ' muted'}">
          <i class="mv2-level-key mv2-level-${mvEsc(l.kind || 'reference')}"></i>
          <span>${mvEsc(l.label || l.kind || '')}</span>
          <b>${mvEsc(fmt(l.price))}</b>
          ${l.armed === true && armed ? '' : '<em>not armed</em>'}
        </div>`).join('')}</div>`
        : `<div class="mv2-nolevels"><i class="mv2-dot muted"></i>` +
          `${mvEsc(s.levels_note || 'No price trigger published')}</div>
           <p class="mv2-why">${mvEsc(s.levels_detail || b.boundary_proof || '')}</p>`}
    </div>`;

    return `<div class="mv2-card">
      <div class="mv2-card-head">
        <span class="mv2-kicker">${mvEsc(
          b.boundary_type === 'metric_boundary' ? 'Setup gate'
          : b.boundary_type === 'entry_after_setup_only' ? 'Setup prerequisites'
          : 'Setup')}</span>
        <span class="mv2-mono">${mvEsc(kind)}</span>${mvSourceBadge(b)}
        ${b.decided_at_et
          ? `<span class="mv2-mono">decided ${mvEsc(b.decided_at_et)} ET</span>` : ''}
        <span class="mv2-mono mv2-head-right">market ref <b>${
          lastBar ? mvEsc(fmt(lastBar.close)) : '--'}</b> · ${
          mvEsc(lastSlot ? lastSlot.time_et + ' ET' : 'no reference yet')}</span>
      </div>
      <div class="mv2-setup ${cols}">
        <div class="mv2-setup-col">
          <p class="mv2-summary-text">${mvEsc(b.summary || s.summary || '')}</p>
          <div class="mv2-miss">
            <i class="mv2-dot ${failedLane || near ? 'bad' : 'muted'}"></i>
            <div>
              <div class="mv2-kicker">Nearest miss</div>
              <div class="mv2-miss-text">${mvEsc(miss)}</div>
            </div>
          </div>
        </div>
        ${conditions}
        ${levelsCol}
      </div>
      ${(opts && opts.withChart === false) ? '' : mvSlotChart(s)}
    </div>`;
  }

  //: Stage 5ZZY. How long the current label has held, counted from the context strip.
  //
  // Returned with a `capped` flag rather than as a bare number: the strip is 60 days long, so
  // a run that reaches its start is at LEAST that long and the true figure is not in the
  // payload. Printing "held 60 days" for a run that began earlier would be a measurement
  // reported to a precision the data does not carry.
  function regimeHeld(r) {
    const ctx = (r.context || []).slice();
    if (!ctx.length || !r.label) return null;
    let n = 0;
    for (let i = ctx.length - 1; i >= 0; i--) {
      if (String(ctx[i].label) !== String(r.label)) break;
      n++;
    }
    if (!n) return null;
    return { days: n, capped: n === ctx.length };
  }

  //: The context strip collapsed into runs, so 60 cells read as "Normal for a month, then
  //: Calm" instead of as sixty squares.
  function regimeRuns(r) {
    const ctx = r.context || [];
    const runs = [];
    ctx.forEach(d => {
      const last = runs[runs.length - 1];
      if (last && last.label === d.label) { last.days++; last.to = d.date; }
      else runs.push({ label: d.label, days: 1, from: d.date, to: d.date });
    });
    return runs;
  }

  function renderMarketView() {
    const host = $('marketViewChart');
    if (!host) return;
    const payload = state.marketView?.market_view;
    mvDayBar();
    const src = $('marketViewSource');
    const sum = $('marketViewSummary');
    const note = $('marketViewNote');

    // Every card this renderer owns is cleared on the failure paths below. Leaving a card
    // populated from the previous poll while the header says "unavailable" is how a dead
    // source comes to be read as a live one.
    const lanesHost = $('marketViewLanes');
    const verdictHost = $('marketViewVerdict');
    const innerHost = $('marketViewInnerTabs');
    const setupHost = $('marketViewSetup');
    const calmHost = $('marketViewCalm');
    const calmSection = $('calmSection');
    // Stage 5ZZZ-F. Calm is rendered here, once, whichever sleeve tab is selected - it is not
    // a sleeve and does not change with the tabs. Before this it was written at the end of the
    // sleeve renderer, so it sat under the selected sleeve's own setup card and read as part
    // of it: on the NKD tab the page showed NKD's chart, NKD's setup, then two Calm cards with
    // nothing between them saying the subject had changed.
    //
    // `state.marketView` holds the whole response `{market_view, regime}`, so the payload sits
    // one level down - the same shape `market_view.sleeves` is read through below.
    const calmHtml = mvCalmCards(state.marketView?.market_view?.calm);
    if (calmHost) calmHost.innerHTML = calmHtml;
    // The band is hidden rather than left standing empty: an empty headed band reads as a
    // panel that failed, and Calm having nothing to say is not a failure.
    if (calmSection) calmSection.hidden = !calmHtml;
    const clearCards = () => {
      if (lanesHost) lanesHost.innerHTML = '';
      if (verdictHost) verdictHost.innerHTML = '';
      if (setupHost) setupHost.innerHTML = '';
      if (innerHost) { innerHost.innerHTML = ''; innerHost.hidden = true; }
      if (note) note.textContent = '';
    };

    if (state.marketView?.error) {
      if (src) { src.textContent = 'Market view unavailable'; src.className = 'source-note warning'; }
      if (sum) sum.textContent = state.marketView.error;
      clearCards();
      host.innerHTML = mvEmpty('Market view unavailable', state.marketView.error);
      return;
    }
    if (!payload) {
      if (src) src.textContent = 'Market view not yet read';
      clearCards();
      host.innerHTML = mvEmpty('Not yet read', 'The market view has not been fetched yet.');
      return;
    }
    const sleeves = payload.sleeves || {};
    if (!state.mvTab || !sleeves[state.mvTab]) state.mvTab = MV_ORDER.find(k => sleeves[k]) || null;
    mvTabs();
    const s = state.mvTab ? sleeves[state.mvTab] : null;
    if (!s) {
      clearCards();
      host.innerHTML = mvEmpty('No sleeve to show', 'The payload declared no sleeves.');
      return;
    }
    if (src) {
      src.textContent = `${s.instrument} · ${s.bar_interval} · window ` +
        `${s.range?.window_start_et}–${s.range?.window_end_et} ET`;
      src.className = 'source-note mv2-meta';
    }
    // Chips, not a sentence. The same facts, but an operator scanning the page reads a row
    // of chips in one glance and a comma-joined line word by word.
    if (sum) {
      sum.innerHTML = mvChips(s);
      sum.className = 'mv-summary';
    }
    mvVerdict(s);
    // Two views, and which one is showing decides which card is built. Both are built from
    // the same payload; neither recomputes anything the other one showed.
    // With rule evidence the two views are tabbed. Without it there is nothing to tab
    // between, so the lanes card still appears — carrying its own reason for being empty,
    // which is a fact about the session — and the price card appears under it.
    const hasInner = mvInnerTabs(s);
    const showLanes = hasInner ? state.mvInner === 'Setup rules' : true;
    const showGrid = hasInner && state.mvInner === 'Detector rules';
    if (lanesHost) {
      lanesHost.innerHTML = showLanes ? mvLanes(s) : showGrid ? mvBarGridCard(s) : '';
    }
    // The chart yields to either detail tab. Two tabs now hide it rather than one, and the
    // condition says which rather than testing the chart's own tab by elimination.
    host.hidden = hasInner && (showLanes || showGrid);
    if (!host.hidden) {
      // Stage 5ZZZ-F. The plot sits in a FIXED box, and the empty state sits in the same one.
      //
      // The height was being set by the content: an svg with `height:100%` inside a card with
      // no height of its own, so a populated tab measured 437px and a tab whose session had no
      // bars measured 116px. Switching between them moved every panel below the chart. The CSS
      // that was meant to prevent this says so in its own comment - "a panel that resizes under
      // the pointer is a panel an operator misclicks" - and it was pinned to the outer host,
      // which the redesign stopped being the element that holds the plot.
      /* Stage 5ZZZ-CF. "Across the session" belongs to THIS tab and no other.
         Measured on the design, tab by tab: the series chart appears only under
         Price context, the Conditions/Readings/Nearest-miss/Trade-levels block only
         under Detector rules. Both were rendering on all three, so whichever tab was
         chosen the reader got the same two panels underneath and the tabs looked
         decorative. */
      host.innerHTML = mvInstBar(s) + `<div class="mv2-card">` + mvPriceHead(s) + mvDataHealth(s) +
        `<div class="mv2-plot">` + mvChartSvg(s) +
          ((s.bars || []).length ? mvLegend() : '') + `</div>` + `</div>`
        + (hasInner ? mvSlotChart(s) : '');
      host.querySelectorAll('[data-mvinst]').forEach(b => {
        b.onclick = () => {
          state.mvInst = b.getAttribute('data-mvinst');
          host.classList.add('loading');
          poll();
        };
      });
      mvBindHover(host);
    }
    // Outside the chart's fixed box, so the panel keeps its pinned height.
    /* Without the tab strip there is nothing to choose between, so the panel keeps its
       old shape and carries everything. With it, this block is the Detector tab's. */
    if (setupHost) {
      setupHost.innerHTML = !hasInner ? mvSetupCard(s)
        : showGrid ? mvSetupCard(s, { withChart: false }) : '';
    }
    // ONE line at most, and only what the chips did not already say. The footer used to
    // repeat the levels note the chips now carry, so the same sentence appeared twice on
    // one panel.
    if (note) {
      const d = s.data_status || {};
      const sd = s.strategy || {};
      note.textContent = (d.ok === false && d.provider_reason)
        ? mvPhrase(d.provider_reason)
        : (sd.detail && (sd.rules || []).length ? sd.detail : '');
    }
  }

  //: Stage 5ZZM. The regime panel, written for somebody deciding whether to trust the label.
  //
  // It used to print the verification record's own sentence — "1761 label(s) compared through
  // 2024-12-31, none changed" — which is precise and reads like a log line. The facts are the
  // same; the words are now the ones an operator would use.
  function regimeCheckLine(v) {
    const st = String(v?.status || '').toUpperCase();
    const c = v?.counts || {};
    const compared = Number(c.compared), changed = Number(c.changed);
    const n = Number.isFinite(compared) ? compared.toLocaleString('en-US') : null;
    if (st === 'PASS') {
      return `Label check passed${n ? ` · ${n} days compared` : ''}` +
             (Number.isFinite(changed) ? (changed ? ` · ${changed} changed` : ' · no drift') : '');
    }
    if (st === 'UNKNOWN' || !st) return 'Label check has not run';
    if (Number.isFinite(changed) && changed) {
      return `Label check found drift · ${changed} of ${n || '?'} days changed`;
    }
    return `Label check ${st.toLowerCase()}`;
  }

  const REGIME_LEGEND = ['Calm', 'Normal', 'Stress', 'Crisis'];

  function renderRegime() {
    const host = $('regimeFacts');
    if (!host) return;
    const r = state.marketView?.regime;
    const src = $('regimeSource');
    const strip = $('regimeStrip');
    const note = $('regimeNote');
    if (!r) {
      host.innerHTML = t1Fact('Regime', 'not yet read');
      if (strip) strip.innerHTML = '';
      if (note) note.textContent = '';
      return;
    }
    const v = r.verification || {};

    // The label is the anchor, and it is NEVER shown alone. "Calm" from a reading nobody has
    // refreshed in three days is a different statement from "Calm" from this morning, and a
    // panel that prints only the word invites the first to be read as the second.
    /* Stage 5ZZZ-CU. Mốc kiểm gần nhất, theo đồng hồ chứ không chỉ theo khoảng cách.
       'checked 43.61h ago' trả lời 'cũ bao nhiêu' nhưng không trả lời 'lúc nào' — và
       'lúc nào' mới là thứ đối chiếu được với nhật ký job. Hai vế đi cùng nhau: giờ tuyệt
       đối để tra, khoảng cách để đọc nhanh. Số giờ làm tròn: hai chữ số thập phân trên một
       phép đo tính bằng ngày là độ chính xác giả.
       Nó nằm TRONG khối nhãn chứ không nhân đôi ở dòng nguồn: đây là thuộc tính của bản
       đọc, và luật 5ZZY chỉ đòi nó được nói MỘT lần, không đòi nói ở đâu. Dòng nguồn giữ
       phần xuất xứ — nhãn ngày nào — đúng vai nó đang giữ cho mọi section khác. */
    const age = r.checked_at
      ? `last checked ${etDateTime(r.checked_at)}`
        + (r.age_hours == null ? '' : ` · ${Math.round(r.age_hours)}h ago`)
      : (r.age_hours == null ? '' : `last checked ${Math.round(r.age_hours)}h ago`);
    const held = regimeHeld(r);
    const cls = mvEsc(String(r.label || '').toLowerCase());
    const checkPass = String(v.status || '').toUpperCase() === 'PASS';
    /* Stage 5ZZZ-CN. Độ bất định về TRONG khối nhãn.

       Nó là một tính chất CỦA CHÍNH cái nhãn — "Calm, và mô hình chắc đến mức nào" — chứ
       không phải một số đo thứ tư đứng ngang hàng với Confidence / Runner-up / Lead. Đứng
       riêng một ô, nó đọc như một chỉ số độc lập; đứng trong khối nhãn, nó nói đúng điều
       nó nói. */
    const uncertain = r.entropy_bits == null ? null
      : (r.entropy_bits < 0.2 ? 'low' : r.entropy_bits < 0.8 ? 'moderate' : 'high');
    const uncertainNote = r.entropy_bits == null ? 'Spread of the model\'s opinion was not published.'
      : `Spread of the model's opinion: ${r.entropy_bits.toFixed(3)} of a possible `
        + `${Number(r.max_entropy_bits).toFixed(3)}, where 0 means completely sure and the `
        + `maximum means it cannot tell the states apart.`;
    // Stage 5ZZY. The label, how long it has held, and whether the check behind it passed —
    // one block, because those three are read together or the first one is misread.
    host.innerHTML = r.label
      ? `<div class="rg2-anchor">
           <div class="rg2-label-row">
             <i class="rg2-dot regime-${cls}"></i>
             <b class="rg2-label regime-${cls}">${mvEsc(r.label)}</b>
             <span class="rg2-held">${held
               ? `held ${held.capped ? 'at least ' : ''}${held.days} day${held.days === 1 ? '' : 's'}`
               : ''}</span>
           </div>
           ${uncertain ? `<div class="rg2-uncertain rg2-unc-${uncertain} has-tip tip-bottom"
                tabindex="0" data-tooltip="${mvEsc(uncertainNote)}">
                <i class="mv2-dot ${uncertain === 'low' ? 'ok' : uncertain === 'moderate'
                  ? 'warn' : 'bad'}"></i>
                <span>${mvEsc(uncertain)} uncertainty</span></div>` : ''}
           <div class="rg2-check ${checkPass ? 'ok' : 'warn'}">
             <i class="mv2-dot ${checkPass ? 'ok' : 'warn'}"></i>
             <span>${mvEsc(regimeCheckLine(v))}</span>
           </div>
           <!-- Mốc kiểm ở ĐÁY khối, dưới cả dòng kiểm nhãn. Ba dòng trên đều nói về
                bản đọc — nhãn gì, mô hình chắc tới đâu, phép kiểm có qua không — còn
                dòng này nói về chính lượt đọc ấy đã chạy lúc nào. Xuất xứ đứng cuối,
                đúng như dòng nguồn đứng cuối ở mọi section khác của trang. -->
           ${age ? `<div class="rg2-asof">${mvEsc(age)}</div>` : ''}
           <!-- Dòng "as of <ngày> · checked <n>h ago" đã bỏ khỏi đây. Dòng nguồn của
                section, ngay đầu thẻ, in ĐÚNG câu ấy: "daily label · <ngày> · checked <n>h
                ago". Đo được hai câu cách nhau 176px, cùng ngày cùng số giờ. Giữ bản ở dòng
                nguồn vì đó là chỗ mọi section khác của trang đặt xuất xứ của mình. -->
         </div>`
      : `<div class="rg2-anchor warn"><div class="rg2-label-row">
           <b class="rg2-label">Not measured</b></div>
           <div class="rg2-asof">${mvEsc(r.detail || r.code || '')}</div></div>`;

    // The four readings that qualify the label, in their own cells beside it.
    const metricsHost = $('regimeMetrics');
    if (metricsHost) {
      const pct = x => `${(x * 100).toFixed(1)}%`;
      metricsHost.innerHTML = [
        { label: 'Confidence',
          value: r.score == null ? '--' : pct(r.score),
          note: r.score == null ? (r.score_note || 'Score not published')
                                : `Posterior mass on ${r.label}.` },
        { label: 'Runner-up',
          value: r.runner_up ? `${r.runner_up} ${
            r.state_probabilities && r.state_probabilities[r.runner_up] != null
              ? pct(r.state_probabilities[r.runner_up]) : ''}`.trim() : '--',
          note: 'Closest competing state.' },
        { label: 'Lead',
          value: r.margin == null ? '--' : `${(r.margin * 100).toFixed(1)} pp`,
          note: r.margin_name || 'Lead over the runner-up, not a distance to a threshold.' },
        // Stage 5ZZZ-F. The absent threshold, named again.
        //
        // Stage 5ZZP moved this invariant off the score and onto the threshold, and the
        // redesign then dropped the row: the only surviving mention was a FALLBACK on the Lead
        // note, which never renders because the record always supplies `margin_name`. So the
        // page had a lead, a confidence and a runner-up, and nothing anywhere saying that the
        // number an operator goes looking for - "how close is it to flipping" - does not exist.
        //
        // The words are the record's own. It explains WHY there is no threshold (a Viterbi
        // decode compares states against each other, not against a cut), which is the part
        // that stops the absence reading as a gap in the panel.
        { label: 'Shift threshold',
          value: r.shift_threshold == null ? 'None published' : String(r.shift_threshold),
          note: r.shift_threshold == null
            ? (r.threshold_note || 'No published shift threshold.')
            : 'Published by the model record.' },
      ].map(m => `<div class="rg2-metric">
          <div class="mv2-kicker">${mvEsc(m.label)}</div>
          <div class="rg2-metric-val">${mvEsc(m.value)}</div>
          <div class="rg2-metric-note">${mvEsc(m.note)}</div>
        </div>`).join('');
    }


    if (src) {
      // Tuổi bản đọc đã về khối nhãn (5ZZZ-CU). Để lại ở đây nữa là dựng lại đúng cặp câu
      // trùng nhau cách 176px mà 5ZZY đã gỡ đi. Dòng nguồn giữ xuất xứ: nhãn của ngày nào.
      src.textContent = r.label ? `daily label · ${r.label_date}` : 'not measured';
      src.className = 'source-note mv2-meta';
    }

    // Stage 5ZZQ. The whole posterior, not one number, and the two features behind it.
    const post = $('regimePosterior');
    if (post) {
      const sp = r.state_probabilities || {};
      const names = Object.keys(sp);
      /* Một chữ số thập phân, GIỐNG ô chỉ số ngay trên. Trước đây bảng in `91.07%` còn ô
         CONFIDENCE in `91.1%` — cùng một xác suất, hai cách làm tròn, cách nhau 12px, và
         người đọc phải dừng lại tự hỏi hai con số ấy có phải một không. Quyết định của chủ
         dự án 2026-09-05: thống nhất một chữ số.
         Ngưỡng "dưới mức in được" đi theo: 0,005 → 0,05, và dấu hiệu đổi từ `<0.01` sang
         `<0.1`. Nguyên tắc giữ nguyên — không bao giờ in một số 0 do làm tròn, vì đó là
         một lời khai khác hẳn về mô hình. */
      // A state at three parts in a million rounds to `0.00%`, which reads as exactly zero
      // — a different claim about the model. Below the printable resolution it says so.
      // The bar is drawn to a FLOOR of 0.4% so a state at three parts in a million is still
      // visible as a row that exists and reads as ~0. A zero-width bar and an absent state
      // draw identically, and this model has three states, not four.
      /* Bốn chế độ là từ vựng của HỆ THỐNG — Calm / Normal / Stress / Crisis. Mô hình
         đang chạy trên tuyến này chỉ fit BA: `inputs.n_states` là 3 và posterior chưa
         bao giờ mang Crisis. Dòng Crisis vẫn hiện, để người đọc thấy đủ bốn tên và biết
         cái thứ tư đang ở đâu — nhưng KHÔNG in phần trăm cho nó.
         In "0.00%" là khai rằng mô hình đã tính ra một xác suất và nó bằng không. Mô hình
         không tính gì cả: trạng thái đó không nằm trong bản fit. Hai câu đó dẫn tới hai
         quyết định vận hành khác hẳn nhau, nên dòng này nói ra câu đúng.
         Danh sách suy từ posterior chứ không viết cứng thứ tự: mô hình nào fit đủ bốn
         trạng thái thì dòng thứ tư tự thành một dòng bình thường, không phải sửa gì. */
      const SYSTEM_STATES = ['Calm', 'Normal', 'Stress', 'Crisis'];
      const absent = SYSTEM_STATES.filter(nm => !(nm in sp));
      const bar = n => {
        const v = Math.max(0, Math.min(1, Number(sp[n]) || 0));
        const faint = v < 0.01;
        return `<div class="regime-post-row${faint ? ' faint' : ''}">
              <span><i class="rg2-key regime-${mvEsc(n.toLowerCase())}"></i>${mvEsc(n)}</span>
              <span class="regime-post-track"><i class="regime-${mvEsc(n.toLowerCase())}"
                 style="width:${Math.max(v * 100, 0.4).toFixed(2)}%"></i></span>
              <b>${v > 0 && v * 100 < 0.05 ? '&lt;0.1' : (v * 100).toFixed(1)}%</b>
            </div>`;
      };
      const noState = n => `<div class="regime-post-row regime-post-absent"
              title="${mvEsc(n)} is part of the system's regime vocabulary but not of the
 model running here, which is fitted on ${mvEsc(String(r.inputs?.n_states ?? '?'))} states.
 No probability is published for it — that is different from a probability of zero.">
              <span><i class="rg2-key regime-${mvEsc(n.toLowerCase())}"></i>${mvEsc(n)}</span>
              <span class="regime-post-nostate">not in this model</span>
              <b>&mdash;</b>
            </div>`;
      post.innerHTML = names.length
        ? `<div class="mv2-kicker">State probabilities</div><div class="regime-post">`
          + names.map(bar).join('') + absent.map(noState).join('') + `</div>`
        : '';
    }
    const feats = $('regimeFeatures');
    if (feats) {
      const rows = r.features || [];
      // The count is stated. The model is fitted on these inputs and no others, so "2" is
      // the whole set rather than the first page of a longer one — and a reader who has seen
      // a nine-feature model elsewhere must not assume seven are being withheld.
      feats.innerHTML = rows.length
        ? `<div class="rg2-feat-head">
             <span class="mv2-kicker">Why this label?</span>
             <span class="mv2-mono">${rows.length} input${rows.length === 1 ? '' : 's'} ` +
               `behind the ${mvEsc(r.label_date || '')} label — the model is fitted on these</span>
           </div>
           <div class="rg2-feats">` +
          rows.map(f => {
            const mixed = f.leans === 'mixed';
            const tip = mixed
              ? 'No state is meaningfully nearest for this input, so no lean is claimed.'
              : "Nearest state mean, measured in that state's own standard deviations.";
            return `<div class="rg2-feat">
              <div class="rg2-feat-label">${mvEsc(f.label)}</div>
              <div class="rg2-feat-val">${mvEsc(f.display_value)}</div>
              <div class="rg2-feat-rank">
                <span>${Number(f.percentile_60d).toFixed(0)}th pct</span>
                <i></i>
                <span class="${mixed ? 'dim' : 'regime-' + mvEsc(String(f.leans).toLowerCase())}"
                      title="${mvEsc(tip)}">${mvEsc(mixed ? 'no lean' : 'leans ' + f.leans)}</span>
              </div>
            </div>`;
          }).join('') + `</div>`
        : '';
    }

    if (strip) {
      const ctx = r.context || [];
      const recent = r.recent || [];
      // The legend names the states THIS model can produce, read from the posterior rather
      // than from a fixed list of four. The fitted model has three; printing a fourth key
      // would show a state the label can never take.
      const legend = Object.keys(r.state_probabilities || {});
      const names = legend.length ? legend : REGIME_LEGEND;
      // Sixty cells read as sixty squares. Collapsed into runs they read as "Normal for a
      // month, then Calm", which is the sentence somebody is trying to get out of this row.
      const runs = regimeRuns(r);
      strip.innerHTML = ctx.length
        ? `<div class="regime-rowhead"><span class="mv2-kicker">Last ${ctx.length} trading days</span>` +
          `<div class="regime-legend">` + names.map(l =>
            `<span class="regime-legend-item"><i class="regime-key regime-${mvEsc(String(l).toLowerCase())}"></i>` +
            `${mvEsc(l)}</span>`).join('') + `</div></div>` +
          `<div class="regime-run">` + runs.map(run =>
            `<div class="regime-runseg" style="flex:${run.days}"
                  title="${mvEsc(run.from)} to ${mvEsc(run.to)} · ${mvEsc(run.label)} · ${run.days} day${run.days === 1 ? '' : 's'}">
               <i class="regime-${mvEsc(String(run.label).toLowerCase())}"></i>
               <span>${run.days >= 8 ? mvEsc(run.label) + ' · ' : ''}${run.days}d</span>
             </div>`).join('') + `</div>` +
          (recent.length
            ? `<div class="regime-recent"><span class="regime-recent-head">Last ` +
              `${recent.length}</span>` + recent.map(d =>
                `<span class="regime-day"><i class="rg2-key regime-${mvEsc(String(d.label).toLowerCase())}"></i>` +
                `<b>${mvEsc(String(d.date).slice(5))}</b>` +
                `<em class="regime-${mvEsc(String(d.label).toLowerCase())}">` +
                `${mvEsc(d.label)}</em></span>`).join('') + `</div>`
            : '')
        : '';
    }

    if (note) {
      // Said once, under the panel, rather than repeated beside both empty fields.
      // One sentence, and it changes with what the model actually gave us.
      /* Stage 5ZZY thêm vào đây một câu nữa: "Today <nhãn> leads <á quân> by <n>
         percentage points", có chủ đích — để trả lời câu "còn cách một lần đổi chế độ bao
         xa?" mà người đọc mang sẵn tới. Từ đó tới nay bốn ô chỉ số đã lên ngay phía trên
         và trả lời đúng câu ấy bằng đúng những con số ấy: ô LEAD in "82.1 pp — probability
         margin over the next most likely state", ô RUNNER-UP in "Normal 8.9% — closest
         competing state". Đo được cùng số 82.1 ở hai chỗ cách nhau 361px, và cặp trạng
         thái cũng đã được gọi tên ở trên. Nên câu ấy bỏ.
         Nửa còn lại — "không có ngưỡng cố định để vượt" — KHÔNG có ở đâu khác trên trang,
         và nó là thứ trả lời một câu hỏi khác hẳn: người đọc đi tìm một con số ngưỡng sẽ
         không tìm thấy, và cần biết là vì không có, chứ không phải vì thiếu. Giữ. */
      note.innerHTML = r.score == null
        ? `<b>The regime confidence could not be read.</b>` +
          `<span>The label itself is unaffected.</span>`
        // Stage 5ZZZ-CM. Viết lại cho người không có nền. Bản cũ dùng "posteriors" — từ
        // của người dựng mô hình — và nói cùng một điều hai lần bằng hai cách trừu tượng:
        //   "No fixed shift threshold: the model selects the most likely state by comparing
        //    posteriors. A shift is recorded when a different state takes the lead, so there
        //    is no cutoff number to breach."
        // Cái người đọc cần biết là: đừng đi tìm một con số, vì không có con số nào.
        : `<b>There is no level for the market to cross.</b>` +
          `<span>Each day the model gives all three states a score and the highest score ` +
          `becomes the label. So the label changes when a different state scores highest — ` +
          `not when some number is breached.` +
          (r.posterior_agrees_with_label === false
            ? ' Today the highest-scoring state is not the one on the label.' : '') +
          `</span>`;
    }
  }

  function renderOpenIssues() {
    const data = state.openIssues;
    const issues = data?.issues || [];
    const coverage = data?.coverage;
    const staleDays = Number(coverage?.stale_days || 0);
    // Stage 5ZZZ-BL. ONE count, used by both labels on this panel.
    //
    // The toggle below has said "3 open issues / 3 retired legacy" since the payload started
    // separating them. This line went on saying `issues.length`, so the same panel carried
    // "6 open" above "3 open issues" -- measured 2026-08-31, where the three extra are the
    // legacy paper reconciliations, which the backend marks `counts_as_active: false` and
    // explains in words: they compare the LEGACY ledger against broker statements and read no
    // Track 1 artefact. Six is a true count of ROWS and a false count of problems, and this
    // label says "open".
    const activeCount = data?.active_count ?? issues.length;
    const retiredCount = data?.retired_history_count ?? 0;
    $('openIssuesSource').textContent = coverage
      ? `${activeCount} open${retiredCount ? ` / ${retiredCount} retired legacy` : ''}`
        + ` / evidence ${coverage.from} to ${coverage.evidence_ends || coverage.to}`
        + `${staleDays > 0 ? ` (ends ${staleDays} day${staleDays === 1 ? '' : 's'} ago)` : ''}`
      : data?.error || 'Evidence coverage unavailable';
    $('openIssuesSource').className = `source-note has-tip tip-right${staleDays > 0 ? ' warning' : ''}`;
    $('openIssuesToggle').textContent =
      `${activeCount} open issue${activeCount === 1 ? '' : 's'}`
      + (retiredCount ? ` / ${retiredCount} retired legacy` : '')
      + ' / show list';
    if (state.issuesSectionOpen === null) state.issuesSectionOpen = issues.length > 0 || !compactIssueMedia.matches;
    // Opening the panel because three retired legacy rows exist would defeat the point of
    // retiring them, so the auto-open follows the active count.
    $('openIssuesShell').open = state.issuesSectionOpen || activeCount > 0;
    if (state.selectedIssueKey && !issues.some(issue => issue.key === state.selectedIssueKey)) state.selectedIssueKey = null;
    if (!state.selectedIssueKey && issues.length && !compactIssueMedia.matches) state.selectedIssueKey = issues[0].key;
    const issueRow = issue => {
      const selected = issue.key === state.selectedIssueKey;
      return `<div class="issue-list-item">
        <button class="issue-list-row ${esc(issue.status)} ${selected ? 'selected' : ''}" type="button" role="option" aria-selected="${selected}" aria-expanded="${selected}" data-issue-key="${esc(issue.key)}">
          <span class="issue-badges"><span class="issue-origin ${esc(issue.component)}">${esc(issue.component || 'unknown')}</span><span class="issue-status">${esc(issueStatus(issue.status))}</span></span>
          <span class="issue-list-copy"><b>${esc(issue.title)}</b><small>${esc(issue.problem)}</small><em>Last ${esc(etDateTime(issue.last_seen))}</em></span>
          <span class="issue-count">${esc(issue.occurrences)}x</span>
        </button>
        ${selected ? `<div class="issue-mobile-detail ${esc(issue.status)}">
          <div class="issue-problem"><span>Problem</span><p>${esc(issue.problem)}</p></div>
          <div class="issue-timing"><span>First ${esc(etDateTime(issue.first_seen))}</span><span>Last ${esc(etDateTime(issue.last_seen))}</span></div>
          <div class="issue-assessment"><div><span>Impact</span><p>${esc(issue.impact)}</p></div><div><span>Action</span><p>${esc(issue.action)}</p></div></div>
          <div class="issue-evidence"><span>Evidence</span><p>${esc(issue.evidence)}</p><p><b>Closes when:</b> ${esc(issue.resolution_evidence)}</p></div>
        </div>` : ''}
      </div>`;
    };
    // Stage 5ZZZ-BN. A group whose every member is retired opens CLOSED.
    //
    // Grouping sorted the list and never shortened it, so a panel headed "Open Issues" kept
    // three rows the backend marks `counts_as_active: false` -- the legacy paper
    // reconciliations, which compare the LEGACY ledger against broker statements and read no
    // Track 1 artefact. The legacy route is formally retired: B1 signed, zero legacy entry
    // jobs. Retired history under a heading that says "open" is the panel disagreeing with
    // itself, and the count above already says "3 open / 3 retired legacy".
    //
    // Collapsed, not dropped. Nothing is deleted and nothing is filtered out of the payload:
    // the group is still there, still counted, one click away. An issue that vanishes is an
    // issue nobody can go back to.
    const groupOpensClosed = g => g.items.length > 0
      && g.items.every(it => it.counts_as_active === false);
    // Stage 5ZZZ-CM. Tiêu đề nhóm chỉ còn ở phần THU LẠI ĐƯỢC.
    //
    // Bốn nhóm sinh ra bốn dải phân cách kèm số đếm, mà mỗi nhóm thường chỉ có MỘT mục —
    // nên người đọc phải bước qua một tiêu đề để tới một dòng. Tệ hơn, hai trong bốn nhãn
    // ("Shared", "Model / Regime") là từ của người viết mã: nghĩa của chúng nằm trong
    // tooltip, tức không tồn tại với người không rê chuột.
    //
    // Cái KHÔNG bỏ: nhóm nào mà mọi mục đều đã nghỉ hưu vẫn mở ra ở trạng thái ĐÓNG. Đó là
    // cơ chế có chủ đích (xem chú thích ngay trên), và nó cần một tiêu đề để bấm vào. Phần
    // còn lại thành danh sách phẳng.
    //
    // Không mất thông tin nào: phạm vi của từng mục vẫn nằm trên chip của chính dòng đó,
    // ngay chỗ mắt đang đọc, thay vì trên một tiêu đề cách đó vài dòng.
    $('openIssueList').innerHTML = issues.length
      ? groupIssues(issues).map(g => {
          const body = g.items.map(issueRow).join('');
          if (!groupOpensClosed(g)) return body;
          const head = `<b>${esc(g.label)}</b><span>${g.items.length}</span>`;
          return `<details class="issue-group issue-group-${esc(g.key)} issue-group-retired">`
            + `<summary class="issue-group-head has-tip tip-right" tabindex="0" `
            + `data-tooltip="${esc(g.note)}">${head}</summary>${body}</details>`;
        }).join('')
      : '<div class="clear-state"><span class="status-dot"></span><b>Clear</b><span>No unresolved issue found in retained evidence</span></div>';
    const selected = issues.find(issue => issue.key === state.selectedIssueKey);
    $('openIssueDetail').innerHTML = selected ? `
      <article class="issue-detail-panel ${esc(selected.status)}">
        <div class="issue-detail-head"><div><span class="issue-origin ${esc(selected.component)}">${esc(selected.component || 'unknown')}</span><span class="issue-status">${esc(issueStatus(selected.status))}</span><h3>${esc(selected.title)}</h3></div><b>${esc(selected.occurrences)} occurrences</b></div>
        <div class="issue-problem"><span>Problem</span><p>${esc(selected.problem)}</p></div>
        <div class="issue-timing"><span>First ${esc(etDateTime(selected.first_seen))}</span><span>Last ${esc(etDateTime(selected.last_seen))}</span></div>
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
    if (runner?.entry_time) return etDateTime(runner.entry_time);
    switch (runner?.entry_time_precision) {
      case 'day_only':       return 'fill time not recorded';
      case 'price_mismatch': return 'trade log record does not match';
      case 'no_record':      return 'no trade log record';
      default:               return 'entry time not emitted';
    }
  }

  // Stage 5ZP. A gate id is a name for the code, not for the person reading the panel.
  // `B1_broker_account_or_legacy_retirement` is precise and unreadable; the plain name goes on
  // the chip and the id stays in the tooltip, so nothing is hidden and nothing has to be
  // decoded at a glance. Rendered as wrapping chips rather than a comma-joined string, because
  // a third gate used to push the value past its column.
  // Stage 5ZZH. Past this, the legacy runner's payload is context, never a current reading.
  // Twelve hours because the legacy runner published daily: one missed publication is a
  // producer that has stopped, not a producer running late.
  const LEGACY_STALE_HOURS = 12;

  const GATE_NAMES = {
    B1_broker_account_or_legacy_retirement: 'Account / legacy retirement gate',
    PAPER_SHADOW_EVIDENCE: 'Shadow evidence gate',
    REGIME_LABEL_VERIFICATION: 'Regime label verification gate',
    LIVE_FRAME_ADAPTER_VERIFICATION: 'Live frame adapter gate'
  };

  function gateChips(ids) {
    return `<span class="t1-gates">` + ids.map(id =>
      `<span class="t1-gate has-tip" tabindex="0" data-tooltip="${esc(id)}">`
      + `${esc(GATE_NAMES[id] || id)}</span>`).join('') + `</span>`;
  }

  function t1Fact(label, value, tone = '', tip = '') {
    // Stage 5ZZM: an optional tooltip on the VALUE, so a row can explain an absence without
    // spending a line of the panel on it.
    return `<div class="fact${tone ? ' ' + tone : ''}"><span class="fact-label">${label}</span>`
         + `<span class="fact-value${tip ? ' has-tip tip-bottom' : ''}"`
         + (tip ? ` tabindex="0" data-tooltip="${esc(tip)}"` : '')
         + `>${value}</span></div>`;
  }

  function renderTrack1() {
    const host = $('track1Facts');
    if (!host) return;
    const t1 = state.track1;
    const src = $('track1Source');

    // Three states, never two. A backend that does not serve the endpoint is a DIFFERENT
    // fact from a route that has not run a slot yet, and both are different from a route
    // that is running. Collapsing them is how "nothing shown" comes to mean "nothing wrong".
    //: FOUR states now, because the page no longer waits for this endpoint before it draws
    //: anything. Track 1 runtime is the slowest read on the page (it walks the whole
    //: evidence tree; 0.7s warm, 9.0s on a cold file cache), and it used to hold the first
    //: paint of every other panel hostage. Now it is polled on its own clock — which means
    //: there is a real moment, on every load, when the answer has simply not arrived yet.
    //: That moment is NOT a failure, and printing "the endpoint did not answer" during it
    //: would be the same lie in the opposite direction.
    if (!t1) {
      if (src) src.textContent = 'Track 1 runtime — reading';
      host.innerHTML = `<div class="empty-state">Reading the Track 1 evidence tree. This is`
        + ` the slowest read on the page and takes a few seconds on the first load.</div>`;
      return;
    }
    if (t1.error) {
      if (src) src.textContent = 'Track 1 runtime unavailable';
      host.innerHTML = `<div class="empty-state">Track 1 runtime endpoint did not answer`
        + ` (${t1.error}). This says nothing about whether the route is`
        + ` running — it says this dashboard could not ask. The page keeps asking every`
        + ` ${POLL_MS / 1000}s and this clears itself on the next answer.</div>`;
      return;
    }
    const cov = t1.window_coverage || {};
    const tim = t1.slot_timing || {};
    const gates = t1.gates || {};
    const safety = t1.safety || {};
    const covDays = Array.isArray(cov.days) ? cov.days.length : 0;
    const timDays = tim.days ? Object.keys(tim.days).length : 0;
    const observed = covDays > 0 || timDays > 0;

    if (src) {
      src.textContent = observed
        ? `${t1.route || 'track1'} / ${covDays} coverage day(s)`
        : `${t1.route || 'track1'} / not yet observed`;
    }

    // `latest` is keyed BY SLEEVE — {roska4_calm: {...}, ...} — not an object with a
    // `.date`. The first version read `cov.latest?.date`, a field that does not exist, so
    // the row printed "latest --" on every day including a fully covered one. A summary of
    // the sleeves is what the operator is actually asking for here.
    const latestDay = covDays ? cov.days[cov.days.length - 1] : '--';
    const sleeves = cov.latest && typeof cov.latest === 'object' ? Object.entries(cov.latest) : [];
    /* MỘT mẫu số cho cả khối. Ba hàng dưới đây đếm ba TẬP CON khác nhau của cùng một
       nhóm sleeve — đã báo tín hiệu / đã ghi giải thích / đã phủ hết cửa sổ — nhưng cả ba
       chỉ ghi "N sleeve(s)". Đo được 2026-09-04: cùng một ngày, cùng một trang, ba con số
       3 · 2 · 4, và không có gì trên màn hình nói chúng là ba tập khác nhau chứ không
       phải ba lần đếm sai. Người đọc không dựng nổi một mô hình.
       Mẫu số suy từ HỢP của mọi tập mà payload biết, chứ không viết cứng: thêm một sleeve
       thì con số tự đi theo. */
    const sleeveNames = new Set([
      ...Object.keys((cov.latest && typeof cov.latest === 'object') ? cov.latest : {}),
      ...Object.keys(((t1.signals || {}).sleeves) || {}),
    ]);
    const sleeveTotal = sleeveNames.size;
    const ofAll = n => sleeveTotal ? `${n} of ${sleeveTotal} sleeves` : `${n} sleeve(s)`;
    const complete = sleeves.filter(([, st]) => st && st.outcome === 'complete').length;
    const coverageSummary = sleeves.length
      ? `${ofAll(complete)} complete`
      : 'no sleeve status yet';
    const timingDayKeys = tim.days ? Object.keys(tim.days) : [];
    const lastTiming = timingDayKeys.length ? tim.days[timingDayKeys[timingDayKeys.length - 1]] : null;
    const latestTiming = lastTiming && lastTiming.runtime_p95_s != null
      ? `, p95 ${lastTiming.runtime_p95_s}s over ${lastTiming.records} record(s)`
      : (lastTiming ? `, ${lastTiming.records} record(s)` : '');

    // Stage 5Q-2 — rows, not just days, and who wrote them. Each live slot now owns its own
    // file, so "12 rows across 3 sleeves / 12 slots" is a fact the page can state; before the
    // fix every slot truncated the day's single shared file and the count was whatever the
    // last slot happened to write.
    function explRow() {
      const ex = t1.explanations || {};
      if (!ex.present) return 'absent (none written yet)';
      const days = Object.keys(ex.days || {});
      if (!days.length) return 'directory present, no day recorded yet';
      const latest = days[days.length - 1];
      const n = ex.days[latest];
      const a = (ex.attribution || {})[latest];
      const who = a ? ` — ${ofAll(a.sleeves.length)} wrote rows, ${a.slots} slot(s)` : '';
      return `${days.length} day(s), latest ${latest}: ${n} row(s)${who}`;
    }

    // Stage 5ZZE — the paper account the route would start from. Its own row, apart from the
    // shadow evidence and apart from the slot verdicts: the account being right and the route
    // having watched enough mornings are different claims.
    function acctRow() {
      const a = t1.paper_account || {};
      if (!a.line) return 'not measured';
      return esc(a.line);
    }
    function acctTone() {
      const st = (t1.paper_account || {}).status;
      return st === 'PASS' ? '' : 'warn';
    }

    // Stage 5ZZC — the daily regime file. Its own row, next to the others and NOT folded into
    // the audit verdict: on 2026-08-27 the overnight window passed all twenty-two slots while
    // this file was a day short, and showing the second as the first would send a reader to
    // inspect a window that worked.
    function spyRow() {
      const s = t1.spy_daily || {};
      if (!s.line) return 'not measured';
      return esc(s.line);
    }
    function spyTone() {
      const st = (t1.spy_daily || {}).state;
      if (st === 'covers_required_day') return '';
      if (st === 'provider_did_not_return_required_day') return 'warn';
      return 'warn';
    }

    // Stage 5ZX — Calm's two shadow phases. Three states, and the same reason as every other
    // row here: a day with no intent rows is not a quiet day, it is a day nobody recorded.
    // The wording carries the limit with the count, because "3 judgeable" read alone becomes
    // "3 executions proven" in the mind of whoever reads it next.
    function calmRow() {
      const c = t1.calm_phases || {};
      if (!c.present) return esc(c.note || 'absent (the two Calm phases have not run)');
      const days = Object.keys(c.days || {});
      if (!days.length) return 'directory present, no day recorded yet';
      const WORDS = { decision_judgeable: 'decision present', no_setup: 'no setup',
                      incomplete: 'incomplete', pre_shadow_intent_schema: 'missing',
                      unreadable: 'unreadable' };
      const latest = c.latest || days[days.length - 1];
      const lab = (c.days[latest] || {}).label;
      const judged = days.filter(d => c.days[d].label === 'decision_judgeable').length;
      return `${days.length} day(s), latest ${esc(latest)}: ${esc(WORDS[lab] || lab)}`
           + ` — ${judged} decision-judgeable (decision only, never a fill)`;
    }

    // Stage 5Q — the post-window audit. Three states, and the middle one is the whole
    // point: an audit that has not run is NOT a pass. Before this row existed the page
    // showed coverage and timing and said nothing about whether anyone had ever judged
    // them, so a day nobody audited looked exactly like a day that passed.
    const aud = t1.audits || {};
    const audLatest = aud.latest || null;
    const audDayVerdict = audLatest && audLatest.day ? audLatest.day.verdict : null;
    const notAudited = Array.isArray(aud.not_audited_yet) ? aud.not_audited_yet : [];
    function auditRow() {
      if (!aud.present) return 'audit not run yet (no audit directory)';
      if (!aud.latest_day) return 'audit not run yet (no record written)';
      const head = `${aud.latest_day}: ${audDayVerdict || 'day roll-up not run yet'}`;
      const per = audLatest && audLatest.sleeves
        ? Object.entries(audLatest.sleeves).map(([s, v]) => `${s}=${v.verdict}`).join(', ')
        : '';
      const gap = notAudited.length ? ` — not audited yet: ${notAudited.join(', ')}` : '';
      return `${head}${per ? ' — ' + per : ''}${gap}`;
    }
    // The reason codes, not just the verdict. A WARN or a FAIL with no reason beside it is a
    // colour, and a colour is what an operator learns to stop reading. `observed_window_shut`
    // and `slot_could_not_evaluate` are different nights and must not look the same.
    function auditReasons() {
      if (!aud.present || !audLatest) return '';
      const seen = [];
      const push = r => { if (r && seen.indexOf(r) < 0) seen.push(r); };
      (audLatest.day?.reasons || []).forEach(push);
      Object.values(audLatest.sleeves || {}).forEach(v => (v.reasons || []).forEach(push));
      return seen.join(', ');
    }
    // Tone is set by the verdict, and "no audit" is never green. FAIL is the only one that
    // reads as an alarm; a pending window is deliberately neutral so the operator does not
    // learn to ignore the colour.
    const auditTone = audDayVerdict === 'FAIL' ? 'negative' : '';

    // Stage 5ZD — signal diagnostics, ONE compact row. Per-slot rule checks live on the
    // expanded job row and are deliberately not repeated here: two places showing the same
    // thing is two places for them to disagree, and the panel is meant to stay scannable.
    //
    // "not yet observed" is not an error and never renders as one. Before the day's first
    // slot there is no file, and a panel that shouted about that would teach the operator to
    // stop reading it.
    const sig = t1.signals || {};
    function signalsRow() {
      // Stage 5ZE — COUNTS only. The earlier version printed a per-sleeve latest status, slot
      // time and a trailing "latest accepted" clause, which grew with the day and turned a
      // one-line fact row into a paragraph. Per-slot detail belongs to the job view; this row
      // exists so an operator can see at a glance whether anything happened at all.
      if (sig.channel_disabled) return `channel disabled — ${sig.channel_error || 'write failed'}`;
      if (!sig.present) return 'not yet observed';
      const totals = {};
      Object.values(sig.sleeves || {}).forEach(v => {
        Object.entries((v && v.counts) || {}).forEach(([st, n]) => {
          totals[st] = (totals[st] || 0) + n;
        });
      });
      const order = ['SIGNAL_ACCEPTED_SHADOW', 'SIGNAL_REJECTED', 'RAW_SIGNAL_FOUND',
                     'NO_SIGNAL', 'SLOT_REFUSED'];
      const words = { SIGNAL_ACCEPTED_SHADOW: 'accepted', SIGNAL_REJECTED: 'rejected',
                      RAW_SIGNAL_FOUND: 'raw', NO_SIGNAL: 'no signal',
                      SLOT_REFUSED: 'refused' };
      const parts = order.filter(k => totals[k]).map(k => `${words[k]} ${totals[k]}`);
      if (!parts.length) return 'file present, no sleeve has reported yet';
      const n = Object.values(sig.sleeves || {}).filter(v => v && v.observed).length;
      return `${parts.join(' · ')} — ${ofAll(n)} reported`;
    }

    function signalsTone() {
      if (sig.channel_disabled) return 'negative';
      if (sig.invalid) return 'negative';
      return '';
    }

    /* Stage 5ZZZ-DD. VÌ SAO bị từ chối, không chỉ BAO NHIÊU.
       Hàng trên đếm "refused 23" và dừng ở đó. Ngày 07/09 cả 23 slot ấy bị từ chối vì CME
       đóng cửa lúc 13:00 vào Labor Day trong khi cửa sổ swing là 14:00-15:55 — không có gì
       hỏng, không ai phải làm gì. Cùng con số ấy vào một ngày thường lại nghĩa là job dữ
       liệu không chạy. Một con số, hai tình huống trái ngược, và màn hình nói y hệt nhau.
       Con số dẫn đầu là SỐ CẦN NGƯỜI, không phải tổng: đó là câu hỏi người vận hành đang
       hỏi. Gộp chúng lại là quay về chỗ một ngày lễ trông như một ngày hỏng. */
    const REFUSAL_WORDS = {
      market_closed: 'thị trường đóng',
      data_not_yet: 'dữ liệu chưa tới',
      unknown: 'chưa rõ nguyên nhân',
      'system_fault/data_join': 'hai nửa dữ liệu bất đồng',
      'system_fault/session_absent': 'phiên mở mà không có bar',
      'system_fault/partial_coverage': 'bar thủng giữa cửa sổ',
      'system_fault/stale_frame': 'khung dữ liệu cũ',
      'system_fault/no_provider': 'slot chạy không có nguồn bar',
      system_fault: 'lỗi hệ thống'
    };
    function refusalRow() {
      const r = sig.refusals || {};
      if (!r.present) return r.reading || '--';
      if (!r.total) return 'không slot nào bị từ chối';
      const groups = (r.groups || []).slice().sort((a, b) => b.count - a.count);
      const chips = groups.map(g => {
        const key = g.fault ? `${g.cause}/${g.fault}` : g.cause;
        const word = REFUSAL_WORDS[key] || REFUSAL_WORDS[g.cause] || key;
        const tip = [g.detail, g.action].filter(Boolean).join('  •  ');
        return `<span class="t1-refusal${g.needs_a_person ? ' needs-person' : ''}` +
          `${tip ? ' has-tip' : ''}"${tip ? ` tabindex="0" data-tooltip="${esc(tip)}"` : ''}>` +
          `${esc(word)} <b>${g.count}</b></span>`;
      }).join('');
      const lead = r.needs_a_person
        ? `<b>${r.needs_a_person} cần người</b> trên ${r.total}`
        : `${r.total}, không cái nào cần người`;
      return `<span class="t1-refusals">${lead}${chips}</span>`;
    }

    const blocking = gates.blocking_now || [];
    const rows = [
      t1Fact('Route', t1.route || '--'),
      t1Fact('Orders possible', gates.orders_possible ? 'YES' : 'no',
             gates.orders_possible ? 'negative' : ''),
      t1Fact('Blocking gates', blocking.length ? gateChips(blocking) : 'none',
             blocking.length ? '' : 'negative'),
      // Stage 5ZZH. Where the row above comes from, and where it does NOT.
      //
      // The open-issue list sits directly beside this panel, and four of its five entries are
      // about the legacy route. Nothing said so at panel level, so the natural reading was
      // that Track 1 was blocked by five things. It is blocked by the two named above, and
      // those come from the gate registry — never from issue prose, which cannot open or
      // close a gate and has twice been written as if it could.
      t1Fact('Blockers come from', esc(state.openIssues?.track1_readiness_blockers_come_from
             || 'the gate registry') + ' — open issues scoped LEGACY or DEBT do not block '
             + 'Track 1 paper readiness'),
      t1Fact('Window coverage', cov.present
             ? (covDays ? `${covDays} day(s), latest ${latestDay} — ${coverageSummary}`
                        : 'directory present, no day recorded yet')
             : 'absent'),
      t1Fact('Slot timing', tim.present
             ? (timDays ? `${timDays} day(s)${latestTiming}` : 'directory present, no day recorded yet')
             : 'absent'),
      t1Fact('Explanations', explRow()),
      t1Fact('Paper account', acctRow(), acctTone()),
      t1Fact('SPY daily', spyRow(), spyTone()),
      t1Fact('Calm phases', calmRow()),
      t1Fact('Book', t1.book?.present ? 'present' : 'absent (expected in shadow — no orders)'),
      t1Fact('Checkpoint', t1.checkpoint?.present ? 'present' : 'absent'),
      t1Fact('Signals today', signalsRow(), signalsTone()),
      // Ngay dưới hàng đếm, vì nó trả lời câu hỏi hàng ấy vừa đặt ra.
      t1Fact('Refusals', refusalRow(),
             (sig.refusals || {}).needs_a_person ? 'negative' : ''),
      t1Fact('Audit verdict', auditRow(), auditTone),
      t1Fact('Audit reasons', auditReasons() || (aud.present ? 'none recorded' : 'no audit has run')),
      // Stage 5ZZZ-CM. Ô này từng in TÊN TỆP, và câu giải thích nó thì trôi ở đáy panel
      // không gắn vào đâu — đọc lên không biết đang nói về cái gì. Giờ ô nói việc, và cả
      // câu giải thích lẫn đường dẫn thật nằm trong tooltip của chính nó: người vận hành
      // vẫn lấy được đường dẫn khi cần, người đọc không phải bước qua nó khi không cần.
      t1Fact('Safety positions',
             safety.positions_path ? 'kept separate from the retired route' : '--',
             '',
             safety.positions_path
               ? `${safety.note || ''} File: ${safety.positions_path}`.trim() : ''),
      t1Fact('Safety client id', safety.client_id != null ? String(safety.client_id) : '--',
             '', 'The broker connection id these protective jobs use. It is theirs alone, so '
                 + 'a job can never be mistaken for the trading route on the broker side.')
    ];
    host.innerHTML = rows.join('');

    const note = $('track1Note');
    if (note) {
      // Dòng chân panel giờ CHỈ nói khi có điều gì đúng ở cấp panel. Câu về vị thế an toàn
      // đã về đúng ô của nó ở trên; để lại đây thì nó là một chú thích không có chủ ngữ.
      note.textContent = observed
        ? ''
        : 'Track 1 runtime not yet observed — no slot has written coverage or timing yet. '
          + 'This is the expected state before the first slot of a shadow period fires.';
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
    // "runner qty" here is the LEGACY book (live_positions.json). Track 1 keeps its own at
    // live_positions.track1.json and is never merged in. Labelled rather than assumed: during
    // a track1-only period the legacy book is DRAINING, and an unlabelled row invites the
    // reader to take it for Track 1 state.
    $('positionSource').textContent = `${brokerPositions().length} IBKR position(s) / ${persistedMatches} legacy(drain) runner qty from persisted state / ${age(state.broker.age_seconds)}`;
    if (!brokerPositions().length) {
      // Stage 5ZZZ-CF. Menh de thu hai la menh de quan trong, va SECTION_ANATOMY
      // (## Open Positions) ghi ro dieu do: o trong khong noi duoc vi sao no trong.
      // "Khong co vi the" va "co vi the ma khong ai bao ve" doc giong nhau khi bang
      // rong, va o che do bong thi cai thu hai moi la cai dang so.
      grid.innerHTML = '<div class="empty-state">No broker positions. '
        + 'Nothing to protect, so no protection is asserted.</div>';
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

    $('decisionSource').textContent = `${snap.date} / runner ${etDateTime(state.runner?.observed_at)}`;
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

  function decisionTime(value) {
    return value ? { text: etDateTime(value), exact: true }
                 : { text: 'time not recorded', exact: false };
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
        time: etDateTime(event.ts), message, status: eventStatus,
        component: lifecycle ? (event.component || 'runner') : String(event.category || 'runner').toLowerCase(),
        title: reconciledNow ? 'Broker/runner position mismatch recovered' : event.title,
        incurredAt: event.started_at || event.incurred_at,
        recoveredAt: reconciledNow ? state.broker?.observed_at : event.recovered_at,
        problem: event.problem, impact: event.impact,
        action: reconciledNow ? 'No immediate action. Review if the mismatch recurs.' : event.action,
        evidence: event.evidence,
        resolution: reconciledNow
          ? `Recovered by current read-only IBKR reconciliation at ${etDateTime(state.broker?.observed_at)}.`
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
          level: 'info', tone: 'success', category: 'STALL RECOVERY', time: etDateTime(event.ts),
          incurredAt: event.stalled_at || event.ts, recoveredAt: event.ts, component: 'scheduler', status: 'recovered',
          title: 'Scheduler heartbeat recovered', message: 'Heartbeat resumed after a previously observed scheduler stall.',
          problem: 'The scheduler heartbeat had stopped advancing.', impact: 'The scheduler is responsive again; any separately confirmed missed slots remain historical facts.',
          action: 'No immediate action. Review Windows sleep history if stalls recur.', evidence: event.message || 'Scheduler heartbeat resumed',
          resolution: `Recovered: heartbeat reported alive at ${etDateTime(event.ts)}.`
        });
        return;
      }
      if (event.kind !== 'scheduler_stalled') {
        rows.push({ key: `monitor:${event.kind}:${event.ts}`, sortKey: event.ts || '', sequence: 0,
          level: String(event.level || 'INFO').toLowerCase(),
          tone: event.level === 'critical' ? 'incident' : event.level === 'warn' ? 'deferred'
            : /completed|passed/.test(event.kind) ? 'success' : 'system',
          category: event.category ? `${event.category} / ${eventLabel(event.kind)}` : `MONITOR / ${eventLabel(event.kind)}`,
          time: etDateTime(event.ts), title: event.title, message: event.message || '',
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
        category: 'STALL', time: etDateTime(event.ts), incurredAt: event.ts, recoveredAt, component: 'scheduler',
        status: recovered ? 'recovered' : 'open', title: `Scheduler heartbeat stalled ${stallSeconds}s`,
        message: recovered ? `Heartbeat stalled ${stallSeconds}s; scheduler later resumed.` : `Heartbeat stalled ${stallSeconds}s with no later successful job evidence.`,
        problem: `The scheduler heartbeat stopped advancing for ${stallSeconds}s, consistent with the machine sleeping or pausing its wait timer.`,
        impact: missed.length ? `Confirmed missed slot(s): ${missed.map(job => job.job_id).join(', ')}.` : 'No missed slot is confirmed inside this stall interval from retained evidence.',
        action: recovered ? 'No immediate action. Check Windows sleep history and power settings if another stall occurs.' : 'Check scheduler process health and Windows sleep state now.',
        evidence: event.message || '', resolution: heartbeatRecovery
          ? `Recovered: heartbeat reported alive at ${etDateTime(heartbeatRecovery.ts)}.`
          : later ? `Recovered: ${later.job_id} later completed at ${etDateTime(later.ended_at)}.` : 'Open: no later recovery evidence observed.'
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
        : job.status === 'missed' ? `${jobLabel(job)} slot missed` : `${jobLabel(job)} failed`;
      const problem = isDumpState
        ? 'Windows denied the atomic replacement of live_state_data.js for this runner slot.'
        : job.status === 'missed'
          ? `The scheduled ${job.job_type.replaceAll('_', ' ')} job did not run: ${job.reason}.`
          : `The job emitted an unresolved error: ${runnerError || job.reason || 'no detail emitted'}.`;
      rows.push({
        key: `job:${job.id}`, sortKey: job.ended_at || job.started_at || '', sequence: 0,
        level: recovered ? 'warn' : 'critical', tone: recovered ? 'cleanup' : 'incident',
        category: isDumpState ? 'STATE PUBLISH' : job.status === 'missed' ? 'MISSED SLOT' : 'JOB FAILURE',
        time: etDateTime(job.started_at), incurredAt: job.started_at, recoveredAt: job.recovered_at || recoveryJob?.ended_at || null,
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
        time: etDateTime(event.ts), incurredAt: isG2 ? event.ts : null, component: 'runner', status: isG2 ? 'known_debt' : 'info',
        title: isG2 ? 'Model age exceeds hard limit' : null,
        message: isG2 ? (debt?.problem || event.message) : event.message || '',
        problem: isG2 ? (debt?.problem || event.message) : null,
        impact: isG2 ? debt?.impact : null, action: isG2 ? debt?.action : null,
        evidence: isG2 ? (debt?.evidence || event.message) : null,
        resolution: isG2 ? `Open known debt. Closes when: ${debt?.resolution_evidence || 'runner reports model age OK.'}` : null
      });
    });

    (decision.entries || []).forEach(entry => {
      const stamp = decisionTime(entry.entry_time);
      rows.push({
        key: `decision:entry:${entry.inst}:${entry.entry_time || day}`,
        sortKey: entry.entry_time || `${day}T14:05:00`,
        level: entry.is_same_day ? 'warn' : 'info',
        tone: entry.is_same_day ? 'deferred' : 'success',
        category: 'TRADE / ENTRY',
        time: stamp.text, inexactTime: !stamp.exact,
        message: [`Entered ${entry.inst || '--'} ${entry.direction || ''}`.trim(), entry.cluster, entry.risk_sized == null ? '' : `risk ${dollars(entry.risk_sized)}`].filter(Boolean).join(' / ')
      });
    });
    (decision.exits || []).filter(exit => !loggedExitSymbols.has(rootOf(exit.inst))).forEach(exit => {
      const stamp = decisionTime(exit.exit_time);
      rows.push({
        key: `decision:exit:${exit.inst}:${exit.exit_time || day}`,
        sortKey: exit.exit_time || `${day}T14:05:00`,
        level: Number(exit.pnl || 0) < 0 ? 'warn' : 'info',
        tone: 'success',
        category: 'TRADE / EXIT',
        time: stamp.text, inexactTime: !stamp.exact,
        message: [`Exited ${exit.inst || '--'} ${exit.direction || ''}`.trim(), tradeMoney(exit.pnl), exitType(exit.exit_reason, 'SIGNAL').label].filter(Boolean).join(' / ')
      });
    });
    (decision.rejected_detail || []).forEach(rejected => rows.push({
      key: `decision:rejected:${rejected.inst}:${rejected.cluster}:${rejected.reason}`,
      sortKey: `${day}T14:05:00`,
      level: 'warn',
      tone: 'deferred',
      category: 'SIGNAL / REJECTED',
      time: 'time not recorded', inexactTime: true,
      message: [`Rejected ${rejected.inst || '--'} ${rejected.direction || ''}`.trim(), rejected.cluster, rejected.reason].filter(Boolean).join(' / ')
    }));
    if (Number(decision.halted_today || 0) > 0) rows.push({
      key: `decision:halted:${day}`,
      sortKey: `${day}T14:05:00`,
      level: 'alert',
      tone: 'incident',
      category: 'GUARD / HALTED',
      time: 'time not recorded', inexactTime: true,
      message: `${decision.halted_today} entry signal(s) halted by guard`
    });
    return rows.sort((a, b) => sortInstant(b.sortKey) - sortInstant(a.sortKey)
      || Number(b.sequence || 0) - Number(a.sequence || 0));
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
    // Stage 5ZZU. The three Track 1 maintenance types are named here explicitly. They reached
    // this list through `other` before they had types of their own, so giving them types would
    // have silently moved them to `runner` — a missed sweep blamed on the runner that never ran.
    // A type change is not free at the call sites that read the type.
    const SCHEDULER_OWNED = ['stop_repair', 'preflight', 'session_report', 'other',
      'track1_safety_stop_repair', 'track1_safety_max_hold', 'track1_window_audit'];
    const component = job.status === 'missed' || job.status === 'skipped' || SCHEDULER_OWNED.includes(job.job_type) ? 'scheduler' : 'runner';
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
      resolution = `Completed at ${etDateTime(job.ended_at)}.`;
    }
    const statusLabel = ({ recovered: 'RECOVERED', known_debt: 'KNOWN DEBT', missed: 'MISSED', open: 'OPEN', completed: 'COMPLETED', skipped: 'SKIPPED', running: 'RUNNING' })[status] || jobStatus(job.status);
    return {
      component, status, statusLabel, problem, resolution,
      impact: job.impact || (job.status === 'completed' ? 'No operational failure is present in scheduler evidence.' : 'Impact not classified from available evidence.'),
      action: job.action || (job.status === 'completed' ? 'No action.' : 'Review the execution evidence.'),
      evidence: nonG2[nonG2.length - 1] || diagnostics[diagnostics.length - 1] || job.reason || jobSummary(job)
    };
  }

  /* `rowShowsProblem` — hàng đang mở ở ngay trên có in sẵn câu vấn đề hay không. Không
     suy ở đây được: nó phụ thuộc việc DANH SÁCH có gộp câu hằng số hay không, mà đó là
     quyết định của cả danh sách chứ không của một hàng. Truyền vào thay vì đoán lại. */
  function renderJobDetails(job, snap, presentation, rowShowsProblem) {
    const exits = new Map((snap?.decision?.exits || []).map(exit => [rootOf(exit.inst), exit]));
    const evidence = (job.events || []).map(event => {
      let message = event.message || '';
      const exit = exits.get(rootOf(event.inst));
      if (event.kind === 'market_close_filled' && exit) message += ` / ${tradeMoney(exit.pnl)} / ${exitType(exit.exit_reason, 'SIGNAL').label}`;
      return `<div class="job-evidence tone-${esc(eventTone(event.kind))}"><time>${esc(etDateTime(event.ts))}</time><div><b>${esc(eventLabel(event.kind))}</b><p>${esc(message)}</p></div></div>`;
    }).join('');
    const diagnostics = (job.diagnostics || []).map(message => {
      const knownDebt = String(message).includes('G2 HARD');
      return `<div class="job-diagnostic ${knownDebt ? 'known-debt' : 'incident-diagnostic'}"><b>${knownDebt ? 'KNOWN DEBT' : 'ERROR EVIDENCE'}</b><p>${esc(message)}</p></div>`;
    }).join('');
    /* Ba trường của bảng thời gian đã bỏ, vì hàng ĐANG MỞ ở ngay trên nó in đúng ba
       biểu thức đó: `.job-time` là `etDateTime(job.started_at)`, `.job-duration` là
       `duration(job.duration_seconds)`, và chip trạng thái là `presentation.statusLabel`.
       Không phải so chuỗi để đoán trùng — cùng một biểu thức, hai chỗ. Đo được trong MỘT
       hàng đang mở: giờ in 3 lần, "12s" 2 lần, "COMPLETED" 2 lần.
       Giờ kết thúc thì GIỮ, vì hàng trên không có nó và nó là thứ duy nhất trong bảng ấy
       mà người đọc không suy ra được. */
    const startedAt = etDateTime(job.started_at);
    const endedAt = job.ended_at ? etDateTime(job.ended_at) : '';
    /* ...và chỉ in khi nó KHÁC giờ bắt đầu ở hàng trên. Cả hai in tới phút, nên một lượt
       chạy 12 giây hiển thị hai giờ giống hệt nhau — đo được `09-04, 06:20 ET` hai lần
       trong cùng một hàng. Giống nhau thì hàng trên đã nói rồi. */
    const times = endedAt && endedAt !== startedAt
      ? `<dl><div><dt>Ended</dt><dd>${esc(endedAt)}</dd></div></dl>` : '';
    /* Hợp đồng năm phần — vấn đề / tác động / hành động / bằng chứng / cách đóng — được
       viết cho một SỰ CỐ. Một lượt chạy xong sạch không phải sự cố, và khi ấy cả năm phần
       cùng nói một điều: không có gì xảy ra. Đo được trên một hàng như vậy: khối chi tiết
       cao 490px để nói đúng câu ấy bốn lần.
       Điều kiện gộp là điều kiện CẤU TRÚC, không phải so chuỗi: chạy xong, không sự kiện
       nào, không chẩn đoán nào. Bất kỳ hàng nào khác — hỏng, bỏ lỡ, bỏ qua, đang chạy, nợ
       tuổi mô hình, hay chạy xong mà CÓ sự kiện — giữ nguyên đủ năm phần. */
    const settled = job.status === 'completed' && !evidence && !diagnostics;
    /* Câu vấn đề chỉ in ở ĐÚNG MỘT chỗ. Hàng in nó khi danh sách không gộp; khối chi
       tiết in nó khi hàng không in. Đo được trước bản sửa: hàng RECOVERED in
       "Windows denied the runner-state publication for this slot." rồi khối ngay dưới in
       lại nguyên câu ấy. */
    const problemBlock = rowShowsProblem ? ''
      : `<div class="issue-problem"><span>Problem</span><p>${esc(presentation.problem)}</p></div>`;
    const body = settled
      ? problemBlock
      : problemBlock + `
      <div class="job-assessment"><div class="job-impact"><b>IMPACT</b><p>${esc(presentation.impact)}</p></div><div class="job-action"><b>ACTION</b><p>${esc(presentation.action)}</p></div></div>
      <div class="job-evidence-list">${evidence || '<p class="job-empty">No events were recorded for this execution.</p>'}${diagnostics}</div>
      <div class="job-resolution"><b>EVIDENCE / RESOLUTION</b><p>${esc(presentation.evidence)}</p><p>${esc(presentation.resolution)}</p></div>`;
    return `<div class="job-detail${settled ? ' job-detail-settled' : ''}">
      ${times}
      ${body}
      ${operationalDetails(job)}${signalDetails(job)}
    </div>`;
  }

  // One row per execution, always. The collapse that used to live here hid every
  // known-debt run but the newest whenever more than three shared a debt, and replaced
  // them with a single summary line. It cost more than it saved:
  //
  //   * the header counts state.jobJournal.jobs.length, so it read "14 jobs" above a
  //     list of two, with nothing on the page reconciling the two numbers. The night's
  //     slots looked lost rather than folded;
  //   * the summary said `debtJobs.length` while one of those rows was already being
  //     rendered directly above it — 2 shown plus 13 "remaining" against a total of 14,
  //     a count that cannot be right whichever way it is read;
  //   * and it named ONE cause, "G2 model age", for a status the backend assigns purely
  //     on "the child exited OK but logged an error" (DEBT_EXIT_TOKENS). Tonight all
  //     thirteen genuinely were G2, but nothing checked that, so the first debt from a
  //     different diagnostic would be filed under a cause that is not its own — and
  //     hidden behind it.
  //
  // The tooltip has promised "one row per execution" all along; now it is true.
  // Stage 5ZD. One sentence under the existing status line, and ONLY on Track 1 strategy
  // slots — the backend omits the key entirely for safety, max-hold, stop-repair, audit and
  // pre-flight jobs, so there is nothing here to accidentally render for them.
  //
  // The sentence is composed by the backend (`track1_signals.one_line`), not here. One owner
  // for the phrasing means a test can assert it and the browser cannot drift from the journal.
  function signalLine(job) {
    const sg = job && job.signal;
    const chip = sg && sg.chip;
    if (!chip) return '';
    // Stage 5ZE. A CHIP, in the existing `.event-status` language, not a sentence. The
    // sentence is still composed by the backend and still asserted by tests, but an operator
    // scanning thirty rows reads a label, not a paragraph — and the paragraph pushed the row
    // to two lines on every slot whether or not anything had happened.
    //
    // The tooltip is required, not decorative: a seven-state chip with no explanation is
    // seven colours nobody can act on. Its text is the backend's, so the page and the journal
    // cannot drift apart.
    // Stage 5ZP. Three things were wrong and all three were visual rather than factual.
    //
    //   * it read "Signal NO SIGNAL" — the word "Signal" was already implied by the chip's
    //     position beside RUNNER and COMPLETED, and doubling it made the longest chip on the
    //     row the least informative;
    //   * it was a bordered pill of its own invention while every other chip on the page is
    //     `.event-status`, so it read as a different KIND of thing;
    //   * `grid-column: 1 / -1` put it on its own line under the badges, which is what made
    //     every Track 1 row two lines tall whether or not anything had happened.
    //
    // It is now a chip in the same language, in the same group, carrying only its label. The
    // tooltip is unchanged and still comes from the backend, so the page and the journal
    // cannot drift.
    return `<span class="event-status signal-${esc(chip.tone)} has-tip" tabindex="0"`
      + ` data-tooltip="${esc(chip.tooltip)}">${esc(chip.label)}</span>`;
  }

  // The expanded row, and only the expanded row, carries the rule checks. Three outcomes are
  // rendered distinctly on purpose: a rule the sleeve never reported has NOT been shown to be
  // fine, and showing it as a tick would be the exact false comfort this journal exists to
  // remove.
  // Stage 5ZE. Two questions, kept apart on the page because they have different owners and
  // different fixes:
  //
  //   Operational  did the slot RUN correctly?
  //   Signal       if it reached the strategy, what did the strategy see?
  //
  // The audit that opened this stage found the first question unanswered: the panel showed
  // started/completed/duration/outcome, an impact, an action and an event list that is always
  // empty for a shadow slot. Nothing about freshness, the live frame, whether the evidence row
  // was written, or whether the duration was anywhere near its budget.
  function operationalDetails(job) {
    const op = job && job.operational;
    if (!op) return '';
    const lines = (op.lines || []).map(l => `<li>${esc(l)}</li>`).join('');
    const tone = op.ran === 'missed' ? 'bad' : op.refused ? 'warn'
      : op.over_budget ? 'warn' : op.ran === 'failed' ? 'bad' : '';
    return `<div class="job-section job-operational ${esc(tone)}">
      <b class="has-tip" tabindex="0" data-tooltip="Whether the slot ran correctly: scheduling, runtime budget, evidence row, and the runtime gates. Separate from what the strategy then saw.">OPERATIONAL</b>
      <ul class="job-lines">${lines}</ul></div>`;
  }

  // Operator language only. `breadth_down_count`, `gate_allow` and the raw JSON thresholds
  // still travel on the payload under `signal.debug`, and there is no code path here that
  // renders them — deliberately. After Stage 5ZD every setup rule comes back unmeasured, so
  // printing them would be thirty rows of UNKNOWN burying the two lines that carry meaning.
  function signalDetails(job) {
    const sg = job && job.signal;
    if (!sg) return '';
    const lines = (sg.operator || []).map(l => `<li>${esc(l)}</li>`).join('');
    const d = sg.details;
    const cands = d && d.candidates && d.candidates.length
      ? `<ul class="signal-candidates">` + d.candidates.map(c => {
          const bits = [`${esc(c.instrument || '?')} ${esc(String(c.direction || '').toUpperCase())}`];
          if (c.qty != null) bits.push(`x${esc(String(c.qty))}`);
          if (c.entry != null) bits.push(`entry ${esc(String(c.entry))}`);
          if (c.stop != null) bits.push(`stop ${esc(String(c.stop))}`);
          if (c.target != null) bits.push(`target ${esc(String(c.target))}`);
          if (c.risk != null) bits.push(`risk ${esc(String(c.risk))}`);
          return `<li>${bits.join(' · ')}</li>`;
        }).join('') + `</ul>`
      : '';
    const chip = sg.chip || {};
    return `<div class="job-section job-signal-detail">
      <b class="has-tip" tabindex="0" data-tooltip="${esc(chip.tooltip || '')}">SIGNAL</b>
      <ul class="job-lines">${lines}</ul>${cands}</div>`;
  }

  function renderJobJournal(snap) {
    const jobs = journalJobs();
    if (state.selectedJobId && !jobs.some(job => job.id === state.selectedJobId)) state.selectedJobId = null;
    // The day is read back off the payload rather than from the session snapshot, so
    // the label always names the day the rows actually came from. Taking it from the
    // snapshot is how the header came to read "14 jobs / 2026-08-17" while the rows
    // underneath belonged to a different anchor entirely.
    /* Stage 5ZZZ-CA. Một câu giống hệt nhau trên mọi hàng thì không phân biệt được hàng
       nào với hàng nào. Đo được 2026-09-04: 29 hàng, ĐÚNG HAI câu khác nhau — 28 hàng nói
       "không có gì thay đổi", và một hàng nói Windows chặn ghi runner-state. Hàng có sự cố
       duy nhất của ngày đang nằm lẫn giữa 28 dòng chữ giống nhau; riêng câu ấy chiếm
       1.008px trên một trang cao 3.734px.
       Chỉ gộp ĐÚNG câu hằng số đó. Chín câu còn lại — hỏng, bỏ lỡ, bỏ qua, đang chạy, nợ
       tuổi mô hình, xong-mà-có-thay-đổi — nằm nguyên trên hàng của chúng. Nên một slot có
       vấn đề trở thành hàng DUY NHẤT còn mang chữ, thay vì một dòng giống hệt 28 dòng kia.
       Dòng gộp nói RÕ nó phủ bao nhiêu hàng, chứ không nói trống: một ngày 12 im lặng /
       17 có chuyện phải đọc ra được tỉ lệ, không được dẫn sang kết luận "hôm nay êm".
       Dưới hai hàng thì không gộp — gộp một hàng không tiết kiệm gì mà lại đẩy câu ra xa
       hàng nó mô tả. */
    const QUIET_ROW = 'The execution completed without trade or protection changes.';
    const presented = jobs.map(job => ({ job, presentation: jobPresentation(job) }));
    const quietCount = presented.filter(o => o.presentation.problem === QUIET_ROW).length;
    const foldQuiet = quietCount >= 2;
    /* Câu gộp KHÔNG đặt ở dòng nguồn. Đo được: dòng ấy có 208px, còn câu đầy đủ cần
       387px — gần một nửa bị cắt ở mọi khổ, và người đọc chỉ thấy "30 with …". Một dòng
       gộp mà không đọc được nó phủ bao nhiêu hàng thì đúng bằng không gộp gì.
       Chỗ đúng của nó là đầu DANH SÁCH, nơi có trọn chiều ngang cột và nơi nó đứng cạnh
       chính những hàng nó nói về. */
    $('journalSource').textContent = state.jobJournal?.day
      ? `${jobs.length} jobs / ${state.jobJournal.day}`
      : 'scheduler evidence unavailable';
    $('journalSource').dataset.tooltip = `Scheduler evidence observed ${etDateTime(state.jobJournal?.observed_at)}. One row per execution; click a job to inspect its operational evidence.`
      + (foldQuiet ? ` ${quietCount} of ${jobs.length} executions completed without changing a trade or a protective order; that sentence is stated here once instead of on each of those rows. Every row that says anything else is a row where something else happened.` : '');
    const jobRows = presented.map(({ job, presentation }) => {
      const selected = job.id === state.selectedJobId;
      const rowProblem = foldQuiet && presentation.problem === QUIET_ROW ? '' : presentation.problem;
      const tone = presentation.status === 'recovered' ? 'success' : presentation.status === 'known_debt' ? 'cleanup' : jobTone(job.status);
      /* Stage 5ZZZ-DC. Hàng KHÔNG im lặng được đánh dấu, không chỉ hàng có trạng thái lạ.
         Câu gộp ở đầu danh sách hứa: "mọi hàng nói điều gì khác là hàng có chuyện khác xảy
         ra". Nhưng cơ chế đánh dấu duy nhất bám vào `status`, và đo trên phiên 07/09 thì
         48 trên 48 thẻ đều `completed` — kể cả thẻ duy nhất có nội dung riêng, lượt SPY
         04:45 báo "nothing to do — the daily series covers 2026-09-04". Nên hàng mà câu gộp
         vừa hứa sẽ nổi lên lại trông y hệt 47 hàng nó vừa gộp đi, và người đọc phải tự quét
         tìm hàng nào có thêm một dòng chữ xám.
         Dấu nhạt có chủ đích: nó nói "đọc dòng này", không nói "có lỗi". Trạng thái lạ đã
         có màu riêng và những màu ấy vẫn thắng, vì chúng nói mạnh hơn. */
      const speaks = Boolean(rowProblem);
      return `<li class="job-row tone-${esc(tone)} status-${esc(presentation.status)}${
        speaks ? ' says-something' : ''} ${selected ? 'selected' : ''}">
        <button class="job-trigger" type="button" data-job-id="${esc(job.id)}" aria-expanded="${selected}">
          <span class="job-time">${esc(etDateTime(job.started_at))}</span><span class="job-duration">${esc(duration(job.duration_seconds))}</span><span class="job-chevron" aria-hidden="true">${selected ? '−' : '+'}</span>
          <span class="job-badges"><span class="issue-origin ${esc(presentation.component)}">${esc(presentation.component)}</span><span class="event-status ${esc(presentation.status)}">${esc(presentation.statusLabel)}</span>${signalLine(job)}</span>
          <span class="job-name" title="${esc(job.job_id)}">${esc(jobLabel(job))}</span><span class="job-summary">${esc(rowProblem)}</span>
        </button>${selected ? renderJobDetails(job, snap, presentation, Boolean(rowProblem)) : ''}
      </li>`;
    }).join('');
    const foldNote = foldQuiet
      ? `<li class="journal-fold-note">${quietCount} of ${jobs.length} execution`
        + `${jobs.length === 1 ? '' : 's'} completed with no trade or protection change. `
        + `Every row that says anything else is a row where something else happened.</li>`
      : '';
    $('journal').innerHTML = jobRows
      ? foldNote + jobRows
      : '<li><div class="journal-message">No scheduler jobs observed for this session.</div></li>';
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
    $('journalSource').dataset.tooltip = `Combines retained scheduler and runner evidence. Runner JSONL coverage ${coverage ? `starts ${etDateTime(coverage)}` : 'is unavailable'}.`;
    if (state.selectedEventKey && !shown.some(row => row.key === state.selectedEventKey)) state.selectedEventKey = null;
    $('journal').innerHTML = shown.length
      ? shown.map(row => {
        const actionable = Boolean(row.problem || row.impact || row.action || row.evidence);
        const selected = actionable && row.key === state.selectedEventKey;
        return `<li class="event-row ${esc(row.level)} tone-${esc(row.tone || 'system')} status-${esc(row.status || 'info')} ${selected ? 'selected' : ''}">
          ${actionable ? `<button class="event-trigger" type="button" data-event-key="${esc(row.key)}" aria-expanded="${selected}">` : '<div class="event-static">'}
          <div class="journal-meta"><span>${esc(row.category)}</span><time class="${row.inexactTime ? 'inexact' : ''}">${esc(row.time)}</time></div>
          ${actionable ? `<div class="event-badges"><span class="issue-origin ${esc(row.component)}">${esc(row.component)}</span><span class="event-status ${esc(row.status)}">${esc(eventStatus(row.status))}</span></div>` : ''}
          ${actionable ? `<div class="event-times"><span><b>INCURRED</b>${esc(row.incurredAt ? etDateTime(row.incurredAt) : row.time)}</span>${row.recoveredAt ? `<span><b>RECOVERED</b>${esc(etDateTime(row.recoveredAt))}</span>` : ''}</div>` : ''}
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

  // Stage 5ZZZ-BU. ONE definition, because three blocks now have to answer the same question.
  //
  // Stale by AGE, not by the label -- the reasoning is Stage 5ZZH's and is unchanged: the
  // freshness model asks the SCHEDULE whether a publish was due, and in track1-only mode the
  // legacy runner is never due, so the label says `fresh` for a snapshot of any age. Measured
  // 2026-09-01: 724,658 seconds, 201.3 hours, eight and a half days.
  function legacyRunnerStale() {
    const hours = Number(state.runner?.age_seconds) / 3600;
    return ['missing', 'unknown', 'stale'].includes(state.runner?.freshness)
      || (Number.isFinite(hours) && hours > LEGACY_STALE_HOURS);
  }

  /* Stage 5ZZZ-CS. Mã máy không được lên màn hình.

     Bảng Source Clocks in thẳng `not_expected_yet` và `not_scheduled / none` — đó là từ
     của người viết bộ lập lịch, và người đọc bảng ấy không có cách nào đoán ra nghĩa. Tệ
     hơn `not_scheduled / none`: hai mã ghép bằng dấu gạch chéo trông như một tỉ số.

     Dịch ở TẦNG HIỂN THỊ. Bản ghi giữ nguyên mã của nó — mã là thứ máy đọc và là thứ đối
     soát về sau; chỉ câu người đọc thấy là đổi. Cùng khuôn với `MISSING_WORDS` đã dùng cho
     những sự vắng mặt khác trên trang này.

     Mã LẠ thì in nguyên, không đoán. Một bộ dịch im lặng nuốt mã nó chưa biết sẽ biến một
     trạng thái mới thành một ô trống, và ô trống là thứ không ai đi tìm. */
  const MV_FRESHNESS_WORDS = {
    fresh:            'another slot is due today',
    not_expected_yet: 'no slot is due right now',
    late:             'a slot was due and has not run',
    stale:            'the newest snapshot is older than the last slot that ran',
    missing:          'nothing has been published',
    unknown:          'the scheduler log could not be read, so this cannot be judged'
  };

  function mvFreshnessWords(code) {
    const key = String(code || 'missing');
    return MV_FRESHNESS_WORDS[key] || key;
  }

  const MV_EVIDENCE_WORDS = {
    executed:       'the last slot ran',
    failed:         'the last slot raised an error',
    skipped:        'the last slot was skipped',
    interrupted:    'the last slot was cut off by a scheduler restart',
    not_scheduled:  'no slot was scheduled in this window',
    not_observed:   'no record of the last slot',
    not_applicable: 'this window is before the scheduler started'
  };

  //: Lý do chỉ được nói khi nó THÊM điều gì. `none` và `unknown` là chỗ giữ chỗ, và ghép
  //: chúng vào câu bằng dấu gạch chéo là cách "not_scheduled / none" ra đời.
  const MV_EVIDENCE_MUTE = ['none', 'unknown', '', null, undefined];

  function mvEvidenceWords(ev) {
    if (!ev) return 'no scheduler evidence';
    const st = String(ev.state || '');
    const words = MV_EVIDENCE_WORDS[st] || st || 'no scheduler evidence';
    const why = ev.reason;
    if (MV_EVIDENCE_MUTE.includes(why)) return words;
    return `${words} — ${String(why).replace(/_/g, ' ')}`;
  }

  function renderClocks() {
    // Stage 5ZZZ-BU. Two rows that read as a contradiction, and both numbers were right.
    //
    // Measured on the page 2026-09-01:
    //
    //     Runner observed    08-24, 02:58 ET
    //     Runner freshness   fresh
    //
    // -- the runner is healthy, and last spoke eight days ago. The freshness value is not
    // about the runner at all: `fresh` is set when the schedule has another slot later today.
    // The module computing it says so in its own first line, "schedule-relative runner
    // freshness"; the row label had dropped the half that made it true.
    //
    // Nothing is recomputed and the legacy contract is untouched -- other panels read that
    // field and Stage 5ZZH deliberately left it alone. What changes is that the row says what
    // it measures, and the observation beside it says which route it belongs to.
    const stale = legacyRunnerStale();
    const observed = etDateTime(state.runner?.observed_at);
    /* Stage 5ZZZ-CY. Đồng hồ của tuyến ĐANG CHẠY, không phải của tuyến đã nghỉ.

       Ô này đọc trạng thái mà runner cũ ghi ra. Tuyến ấy ngừng giao dịch, nên tệp ấy đứng
       yên ở 24/08 và sẽ đứng yên mãi — một panel tên "Source Clocks" mà dòng trên cùng là
       một cái đồng hồ đã chết. Chữ "legacy route, retired" nói thật, nhưng nó trả lời câu
       "runner quan sát lần cuối khi nào" bằng số của runner KHÔNG chạy, trong khi runner
       đang chạy thì không có dòng nào.

       Ngày cuối Track 1 ghi đo thời gian slot là câu trả lời tương đương: nó chỉ được viết
       khi một slot thật sự chạy xong, đúng như tệp trạng thái cũ chỉ được viết khi runner
       cũ chạy xong.

       Đồng hồ cũ KHÔNG bị bỏ đi — nó xuống một dòng riêng, giữ nhãn, và chỉ hiện khi thật
       sự đã cũ. Bỏ hẳn thì mất mất khả năng thấy tuyến cũ có bất ngờ sống lại hay không. */
    const t1Days = Object.keys(state.track1?.slot_timing?.days || {}).sort();
    const t1Last = t1Days.length ? t1Days[t1Days.length - 1] : '';
    const t1Observed = t1Last
      ? sessionDate(`${t1Last.slice(0, 4)}-${t1Last.slice(4, 6)}-${t1Last.slice(6, 8)}`)
      : '--';
    const entries = [
      ['Track 1 observed', t1Observed],
      ...(stale ? [['Legacy runner observed', `${observed} · route retired`]] : []),
      ['Schedule freshness', mvFreshnessWords(state.runner?.freshness)
        // Nửa "whether another slot is due today" đã bỏ: chính GIÁ TRỊ nói câu ấy rồi, kể
        // từ khi mã máy được dịch ra. Nửa còn lại thì giữ — nó phân biệt hàng này với sức
        // khoẻ của runner, và đó là chỗ người đọc dễ nhầm nhất.
        + ' · not the runner\'s health'],
      ['Expected next', etDateTime(state.schedule?.expected_next_at)],
      ['Schedule evidence', mvEvidenceWords(state.schedule?.evidence)],
      ['Broker observed', etDateTime(state.broker?.observed_at)],
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
    renderTrack1();
    // Stage 5ZZL. Beside the Track 1 panel, in the same pass: these three
    // read the same route and an operator scans them together.
    renderMarketView();
    renderRegime();
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
    state.issuesSectionOpen = !event.matches || (state.openIssues?.issues?.length || 0) > 0;
    state.selectedIssueKey = event.matches ? null : (state.openIssues?.issues?.[0]?.key || null);
    state.selectedMonitorKey = null;
    renderMonitor(latestSnap());
    renderOpenIssues();
  });
  $('openIssuesShell').addEventListener('toggle', event => { state.issuesSectionOpen = event.currentTarget.open; });

  // Stage 5ZZZ-CE/CI. Mỗi mục dashboard trỏ tới một neo trong trang trợ giúp qua chính
  // dòng `source-note` của nó. Không thêm pixel nào: không icon `?`, không hàng mới.
  //
  // KHÔNG bám vào một lớp CSS, và đó mới là bản sửa. Bản đầu gắn `help-link` vào từng phần
  // tử lúc khởi tạo và tô kiểu theo lớp đó. Đo trên trang thật: 2 trong 11 —
  // `openIssuesSource` và `marketViewSource` — mất lớp ngay sau lượt vẽ đầu, vì bộ dựng của
  // chúng gán đè `el.className = '...'`.
  //
  // Chính xác chúng mất gì: chúng vẫn BẤM ĐƯỢC (bộ nghe gắn vào phần tử không bị `className`
  // xoá), nhưng mất gạch chân và con trỏ tay — không còn gì trên màn hình nói rằng bấm được.
  // Một lối vào không ai nhìn thấy là một lối vào không ai dùng. Đột biến bắt tôi ở chỗ này:
  // tôi đã viết "hai liên kết chết", và nó không đúng.
  //
  // Nên bản sửa thật nằm ở CSS: tô theo `[data-help]`, thuộc tính thì `className` không xoá
  // được. Bộ nghe uỷ quyền bên dưới là phòng xa cho một bộ dựng nào đó dựng lại cả phần tử —
  // hôm nay chưa có cái nào làm thế, đo được, nên nó chưa sửa cái gì cả.
  //
  // Thuộc tính thì không bị `className` xoá, nên: CSS tô theo `[data-help]`, và một bộ
  // nghe DUY NHẤT trên document lo mọi cú bấm. Không còn gì để mất.
  //
  // Mở tab mới: dashboard đang poll, điều hướng khỏi nó là mất mạch dữ liệu đang chạy.
  const openHelp = anchor => window.open('/realtime/help#' + anchor, '_blank', 'noopener');
  document.querySelectorAll('[data-help]').forEach(el => {
    el.setAttribute('role', 'link');
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
  });
  document.addEventListener('click', event => {
    const el = event.target.closest?.('[data-help]');
    if (el) openHelp(el.dataset.help);
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const el = event.target.closest?.('[data-help]');
    if (el) { event.preventDefault(); openHelp(el.dataset.help); }
  });

  window.setInterval(renderRailClock, 1000);

  poll();
  window.setInterval(poll, POLL_MS);
})();
