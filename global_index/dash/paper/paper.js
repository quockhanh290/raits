(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  let selectedCoverageKey = 'paper_vs_backtest';

  function fmtTicks(value) {
    if (value == null || value === '') return '--';
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)} ticks`;
  }

  function statusClass(status) {
    return String(status || 'unknown').toLowerCase().replace(/_/g, '-');
  }

  function pct(value, target) {
    const n = Number(value);
    const d = Number(target);
    if (!Number.isFinite(n) || !Number.isFinite(d) || d <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((n / d) * 100)));
  }

  function sourceLine(gate) {
    const paths = (gate.sources || []).map(source => source.path).filter(Boolean);
    return paths.length ? `source: ${paths.join(' + ')}` : 'source: unavailable';
  }

  function metricLine(label, value) {
    return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
  }

  function sourceDetail(sources) {
    return (sources || []).map(source => `<li><b>${esc(source.path)}</b><span>${esc(source.process)}</span><small>${esc(source.format)} | ${esc(source.cadence)} | ${esc(source.retention)}</small></li>`).join('');
  }

  function fmtPrice(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : '--';
  }

  function fmtMoney(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : '-'}$${Math.abs(n).toFixed(2)}`;
  }

  function fmtSigned2(value, suffix = '') {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}${suffix}`;
  }

  function fmtPnl(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n === 0) return '-';
    return `${n > 0 ? '+' : '-'}$${Math.abs(n).toFixed(2)}`;
  }

  function tradeRows(samples) {
    const rows = (samples && samples.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No C1 trade rows with slip are available.</p>';
    return `<div class="trade-table"><table><thead><tr><th>scope</th><th>trade</th><th>ref</th><th>fill</th><th>slip</th><th>status</th></tr></thead><tbody>${rows.map(row => `<tr><td>${esc(row.scope || '--')}</td><td><b>${esc(row.inst || '--')} ${esc(row.type || '--')}</b><small>${esc(row.direction || '--')} ${esc(row.cluster || '--')} ${esc(row.entry_day || '--')}${row.exit_day ? ` -> ${esc(row.exit_day)}` : ''}</small></td><td><b>${fmtPrice(row.reference_price)}</b><small>${esc(row.reference_type || '--')}</small></td><td>${fmtPrice(row.fill_price)}</td><td><b>${fmtTicks(row.slip_ticks)}</b><small>${esc(row.slip_points ?? '--')} pts</small></td><td><b>${esc(row.status || '--')}</b><small>${esc(row.exit_reason || row.source || '--')}</small></td></tr>`).join('')}</tbody></table></div>`;
  }

  function stopTradeRows(details) {
    const rows = (details && details.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No stop-linked trade rows are available.</p>';
    return `<div class="trade-table"><table><thead><tr><th>scope</th><th>position/trade</th><th>stop</th><th>fill</th><th>order</th><th>status</th></tr></thead><tbody>${rows.map(row => `<tr><td>${esc(row.scope || '--')}</td><td><b>${esc(row.inst || '--')} ${esc(row.direction || '--')}</b><small>${esc(row.cluster || '--')} ${esc(row.entry_day || '--')}${row.exit_day ? ` -> ${esc(row.exit_day)}` : ''}</small></td><td><b>${fmtPrice(row.stop_price ?? row.expected_stop)}</b><small>${row.entry_price != null ? `entry ${fmtPrice(row.entry_price)}` : esc(row.exit_reason || '--')}</small></td><td><b>${fmtPrice(row.fill_price)}</b><small>${fmtTicks(row.slip_ticks)}</small></td><td><b>${esc(row.stop_order_id ?? row.order_id ?? '--')}</b><small>${esc(row.perm_id ?? '--')}</small></td><td><b>${esc(row.status || '--')}</b><small>${esc(row.source || (row.exit_pending === true ? 'exit pending' : '--'))}</small></td></tr>`).join('')}</tbody></table></div>`;
  }

  function c1Definition() {
    return `<section class="more-section definition-block"><h3>Slippage definition</h3><p>C1 measures execution drift between the runner's decision reference and the broker fill. The raw trade log stores slip in price points; the dashboard converts it to ticks using the instrument tick size.</p><dl class="metric-list">${metricLine('formula', 'slip ticks = slip points / tick size')}${metricLine('positive sign', 'adverse by runner convention')}${metricLine('OPEN reference', 'expected_entry -> fill_price')}${metricLine('STP CLOSE reference', 'expected_stop -> fill_price')}${metricLine('EXCLUDED_CLOSE', 'signal/market close has no clean expected close reference')}</dl></section>`;
  }

  function meanRead(label, mean, n, maxMean) {
    if (!n) return `${label} no samples`;
    if (maxMean == null || !Number.isFinite(Number(maxMean))) return `${label} observed`;
    return Math.abs(Number(mean)) <= Number(maxMean) ? `${label} within limit now` : `${label} over limit now`;
  }

  function c1ReasonChip(text) {
    let cls = 'neutral';
    if (/within limit|scope|accepted|verified|no false|no double|match|persist|proven|complete/.test(text)) cls = 'ok';
    if (/no samples|incomplete|missing|not structured|unverified|pending|required unset|stress missing|normal missing/.test(text)) cls = 'watch';
    if (/over limit|failed|halt|breach|mismatch/.test(text)) cls = 'bad';
    return `<span class="${cls}">${esc(text)}</span>`;
  }

  function c1Metric(label, value, description, cls = '') {
    return `<article class="c1-metric ${cls}"><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(description)}</small></article>`;
  }

  function c1SampleMetric(label, count, target, description, cls = '') {
    const width = pct(count, target);
    return `<article class="c1-metric sample ${cls}"><span>${esc(label)}</span><b>${esc(count)}${target ? ` / ${esc(target)}` : ''}</b><i><em style="width:${width}%"></em></i><small>${esc(description)}</small></article>`;
  }

  function c1SpecPills(spec, target, maxMean) {
    const parts = [
      ['Minimum N', target || '--'],
      ['Mean limit', maxMean != null ? `${maxMean} ticks` : '--'],
      ['Scope', spec.scope || '--'],
      ['Close scope', spec.close_scope || '--'],
      ['Absolute', spec.use_absolute === false ? 'false' : 'true'],
    ];
    return `<span class="c1-spec-label">Active spec</span>${parts.map(([label, value]) => `<span><b>${esc(label)}</b>${esc(value)}</span>`).join('')}`;
  }

  function c1MetricGroup(title, items, note = '') {
    return `<section class="c1-metric-group"><h3>${esc(title)}</h3>${note ? `<p>${esc(note)}</p>` : ''}<div>${items.join('')}</div></section>`;
  }

  function coverageRuleRail() {
    const parts = [
      ['Duration', '60 days'],
      ['Regime', 'Normal + Stress'],
      ['Chandelier', '>= 3'],
      ['MAX_HOLD', '>= 3'],
      ['STP', '>= 3'],
    ];
    return `<span class="c1-spec-label">Active rule</span>${parts.map(([label, value]) => `<span><b>${esc(label)}</b>${esc(value)}</span>`).join('')}`;
  }

  function coverageMoreInfo(durationGate, regimeGate, exitGate) {
    const duration = durationGate.metrics || {};
    const exits = (exitGate.metrics && exitGate.metrics.exits) || {};
    const regimes = (regimeGate.metrics && regimeGate.metrics.regimes) || [];
    const days = duration.days || [];
    const sources = [...(durationGate.sources || []), ...(regimeGate.sources || []), ...(exitGate.sources || [])];
    return `<details class="c1-more-info coverage-more-info"><summary><span>More info</span><small>days, exits, sources</small></summary><div class="c1-more-grid"><section class="more-section"><h3>Observed days</h3><p class="detail-copy">Paper duration is counted from durable paper_history.json days in the active paper epoch. Same-day overwrites count once per date.</p><dl class="metric-list">${metricLine('observed', duration.observed ?? 0)}${metricLine('target', duration.target ?? 60)}${metricLine('days', days.length ? days.join(', ') : '--')}</dl></section><section class="more-section"><h3>Regime and exits</h3><p class="detail-copy">Regime coverage comes from trade_log rows. Exit path coverage counts normalized CLOSE exit reasons; monitor interprets the documented word "several" as three samples per path.</p><dl class="metric-list">${metricLine('regimes', regimes.length ? regimes.join(' + ') : '--')}${metricLine('CHANDELIER', exits.CHANDELIER ?? 0)}${metricLine('MAX_HOLD', exits.MAX_HOLD ?? 0)}${metricLine('STP', exits.STP ?? 0)}${metricLine('target each', exitGate.metrics?.target_each ?? 3)}</dl></section><section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(sources)}</ul></section><p class="detail-note">Coverage progress can remain pending even when the system is healthy. It is sample coverage, not an operational failure by itself.</p></div></details>`;
  }

  function updateCoveragePanel(gates) {
    const durationGate = gates.find(item => item.key === 'paper_duration') || {};
    const regimeGate = gates.find(item => item.key === 'regime_coverage') || {};
    const exitGate = gates.find(item => item.key === 'exit_path_coverage') || {};
    const duration = durationGate.metrics || {};
    const regimes = (regimeGate.metrics && regimeGate.metrics.regimes) || [];
    const exits = (exitGate.metrics && exitGate.metrics.exits) || {};
    const days = duration.observed ?? 0;
    const targetDays = duration.target ?? 60;
    const targetEach = exitGate.metrics?.target_each ?? 3;
    const completePaths = ['CHANDELIER', 'MAX_HOLD', 'STP'].filter(key => (exits[key] ?? 0) >= targetEach).length;
    const statuses = [durationGate.status, regimeGate.status, exitGate.status];
    const status = statuses.every(item => item === 'PASS') ? 'PASS' : 'PENDING';
    const missingRegimes = ['Normal', 'Stress'].filter(item => !regimes.includes(item));
    const reasons = [
      days >= targetDays ? `days complete ${days}/${targetDays}` : `days pending ${days}/${targetDays}`,
      missingRegimes.length ? `${missingRegimes.join(' + ')} missing`.toLowerCase() : 'regimes complete',
      completePaths >= 3 ? 'exit paths complete' : `exit paths pending ${completePaths}/3`,
    ];

    $('coverageProgressTitle').textContent = `days ${days}/${targetDays} | exits ${completePaths}/3`;
    $('coverageProgressReason').innerHTML = reasons.map(c1ReasonChip).join('');
    $('coverageProgressStatus').textContent = status;
    $('coverageProgressStatus').className = `gate-state ${statusClass(status)}`;
    $('coverageStatusEyebrow').className = `eyebrow c1-eyebrow ${statusClass(status)}`;
    $('coverageActiveSpec').innerHTML = coverageRuleRail();
    $('coverageMetricGroups').innerHTML = [
      c1MetricGroup('Observed data', [
        c1SampleMetric('Days', days, targetDays, 'Durable paper days in current epoch.', days >= targetDays ? 'ok' : 'watch'),
        c1Metric('Regimes', regimes.length ? regimes.join(' + ') : '--', 'Need both Normal and Stress.', missingRegimes.length ? 'watch' : 'ok'),
        c1SampleMetric('Chandelier', exits.CHANDELIER ?? 0, targetEach, 'Chandelier exit samples.', (exits.CHANDELIER ?? 0) >= targetEach ? 'ok' : 'watch'),
        c1SampleMetric('MAX_HOLD', exits.MAX_HOLD ?? 0, targetEach, 'MAX_HOLD exit samples.', (exits.MAX_HOLD ?? 0) >= targetEach ? 'ok' : 'watch'),
        c1SampleMetric('STP', exits.STP ?? 0, targetEach, 'Stop exit samples.', (exits.STP ?? 0) >= targetEach ? 'ok' : 'watch'),
        c1Metric('Complete paths', `${completePaths}/3`, 'Exit paths meeting sample target.', completePaths >= 3 ? 'ok' : 'watch'),
      ]),
      coverageMoreInfo(durationGate, regimeGate, exitGate),
    ].join('');
  }

  function c1MoreInfo(gate, openN, openMean, stpN, stpMean) {
    const m = gate.metrics || {};
    const stats = m.slip_stats || {};
    const samples = m.trade_samples || {};
    return `<details class="c1-more-info"><summary><span>More info</span><small>raw stats, trades, definition, sources</small></summary><div class="c1-more-grid"><section class="more-section"><h3>Raw cumulative stats</h3><p class="detail-copy">Purpose: audit the dashboard math. Raw slip_stats is cumulative provenance and may include broader close types; Presented OPEN/STP is the scoped C1 number recomputed from paper-epoch trade_log rows after point-to-tick conversion.</p><dl class="metric-list">${metricLine('Raw OPEN N', stats.open_n ?? '--')}${metricLine('Raw OPEN sum', stats.open_sum ?? '--')}${metricLine('Raw CLOSE N', stats.close_n ?? '--')}${metricLine('Raw CLOSE sum', stats.close_sum ?? '--')}${metricLine('Presented OPEN', `${openN} rows -> ${fmtTicks(openMean)}`)}${metricLine('Presented STP', `${stpN} rows -> ${fmtTicks(stpMean)}`)}</dl></section>${c1Definition()}<section class="more-section trade-detail"><h3>Trade details (${esc(samples.shown ?? 0)} / ${esc(samples.total ?? 0)})</h3>${tradeRows(samples)}</section><section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(gate.sources)}</ul></section><p class="detail-note">Signal/market CLOSE rows are excluded from C1 because the runner does not persist a clean expected close reference. They are covered by Paper P&amp;L vs backtest instead.</p></div></details>`;
  }

  function stpRuleRail() {
    const parts = [
      ['Placement', 'accepted > 0, failed = 0'],
      ['Verify', 'structured checks required'],
      ['False halt', '0'],
      ['Double STP', '0'],
      ['Unverified', '0'],
    ];
    return `<span class="c1-spec-label">Active rule</span>${parts.map(([label, value]) => `<span><b>${esc(label)}</b>${esc(value)}</span>`).join('')}`;
  }

  function stpRecordRows(records) {
    if (!records || !records.length) return '<p class="detail-empty">No structured STP verification records yet.</p>';
    const rows = records.map(row => {
      const status = row.verified && !row.false_halt && !row.double_stp ? 'PASS' : 'REVIEW';
      const flags = [
        row.verified ? 'verified' : 'unverified',
        row.false_halt ? 'false halt' : 'no false halt',
        row.double_stp ? 'double STP' : 'no double STP',
      ].join(' | ');
      return `<tr><td><b>${esc(row.date || '--')}</b><small>${esc(status)}</small></td><td>${esc(flags)}</td><td>${esc(row.evidence || '--')}</td></tr>`;
    }).join('');
    return `<div class="trade-table stp-record-table"><table><thead><tr><th>Date</th><th>Verdict</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function latestStpRecord(records) {
    if (!records || !records.length) return null;
    return records.slice().sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))[0];
  }

  function stpMoreInfo(gate, placement) {
    const m = gate.metrics || {};
    const p = (placement && placement.metrics) || {};
    const details = m.trade_details || {};
    const records = m.records || [];
    return `<details class="c1-more-info stp-more-info"><summary><span>More info</span><small>records, raw logs, trades, rule, sources</small></summary><div class="c1-more-grid"><section class="more-section trade-detail"><h3>Broker reconcile records (${esc(records.length)})</h3><p class="detail-copy">Purpose: show reviewed STP records that can actually move the gate. Current broker reconcile means runner position, IBKR position, and working protective stop were checked together.</p>${stpRecordRows(records)}</section><section class="more-section"><h3>Raw log counters</h3><p class="detail-copy">Purpose: reconcile STP status with read-only log evidence. Placement accepted/failed comes from runner logs; STP-VERIFY, STP EXIT, and B3 HALT are raw counters until structured operator verification exists.</p><dl class="metric-list">${metricLine('placement accepted', m.stp_accepted ?? p.accepted ?? 0)}${metricLine('placement failed', m.stp_failed ?? p.failed ?? 0)}${metricLine('STP-VERIFY lines', m.stp_verify_lines ?? 0)}${metricLine('STP EXIT lines', m.stp_exit_lines ?? 0)}${metricLine('B3 HALT lines', m.b3_halt_lines ?? 0)}${metricLine('structured checks', m.checks ?? 0)}</dl></section><section class="more-section"><h3>Verification rule</h3><p class="detail-copy">STP verification is the paper gate that proves positions are protected without false halt or duplicate stop behavior. Logs expose candidates, but false-halt classification needs structured input in monitor/paper_inputs.json.</p><dl class="metric-list">${metricLine('false halt', m.false_halts ?? '--')}${metricLine('double STP', m.double_stp ?? '--')}${metricLine('unverified', m.unverified ?? '--')}${metricLine('gate evidence', gate.evidence || '--')}</dl></section><section class="more-section trade-detail"><h3>Stop trade details (${esc(details.shown ?? 0)} / ${esc(details.total ?? 0)})</h3>${stopTradeRows(details)}</section><section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(gate.sources)}</ul></section><p class="detail-note">This panel does not infer false halt from raw text alone. Historical placement logs are not the same as a broker-reconciled STP check unless a retained broker statement/snapshot proves it.</p></div></details>`;
  }

  function updateSTPPanel(gates, coverage) {
    const gate = gates.find(item => item.key === 'stp_verification') || {};
    const placement = coverage.find(item => item.key === 'stp_placement') || {};
    const m = gate.metrics || {};
    const p = placement.metrics || {};
    const accepted = m.stp_accepted ?? p.accepted ?? 0;
    const failed = m.stp_failed ?? p.failed ?? 0;
    const verifyLines = m.stp_verify_lines ?? 0;
    const exitLines = m.stp_exit_lines ?? 0;
    const haltLines = m.b3_halt_lines ?? 0;
    const checks = m.checks ?? 0;
    const latestRecord = latestStpRecord(m.records || []);
    const latestPass = latestRecord && latestRecord.verified && !latestRecord.false_halt && !latestRecord.double_stp;
    const status = gate.status || 'UNKNOWN';
    const reasons = [
      failed ? `placement failed ${failed}` : `placement accepted ${accepted}`,
      verifyLines ? `STP-VERIFY ${verifyLines}` : 'STP-VERIFY missing',
      haltLines ? `B3 HALT ${haltLines}` : 'no false halt evidence',
      checks ? `structured checks ${checks}` : 'structured check missing',
    ];

    $('stpProgressTitle').textContent = `accepted ${accepted} | failed ${failed} | verify ${verifyLines}`;
    $('stpProgressReason').innerHTML = reasons.map(c1ReasonChip).join('');
    $('stpProgressStatus').textContent = status;
    $('stpProgressStatus').className = `gate-state ${statusClass(status)}`;
    $('stpStatusEyebrow').className = `eyebrow c1-eyebrow ${statusClass(status)}`;
    $('stpActiveSpec').innerHTML = stpRuleRail();
    $('stpMetricGroups').innerHTML = [
      c1MetricGroup('Observed data', [
        c1Metric('Accepted', accepted, 'place_stop accepted log evidence.', accepted ? 'ok' : 'watch'),
        c1Metric('Failed', failed, 'Failed stop placement must be zero before pass.', failed ? 'bad' : 'ok'),
        c1Metric('STP-VERIFY', verifyLines, 'B3 STP-VERIFY log counter.'),
        c1Metric('STP EXIT', exitLines, 'B3 stop-exit log counter.'),
        c1Metric('B3 HALT', haltLines, 'Raw halt counter; false-halt classification is structured input.', haltLines ? 'bad' : ''),
        c1Metric('Checks', checks, 'Structured operator STP verification records.', checks ? 'ok' : 'watch'),
        c1Metric('Broker reconcile', latestRecord ? `${latestRecord.date || '--'} ${latestPass ? 'PASS' : 'REVIEW'}` : '--', 'Latest reviewed STP record from monitor/paper_inputs.json.', latestPass ? 'ok' : 'watch'),
        c1Metric('Record evidence', latestRecord ? (latestRecord.evidence || '--') : '--', 'Current IBKR/runner reconciliation evidence, when available.', latestPass ? 'ok' : ''),
      ]),
      stpMoreInfo(gate, placement),
    ].join('');
  }

  function b3RuleRail() {
    const parts = [
      ['Cold start', 'broker/file reconcile'],
      ['Mismatch', '0'],
      ['Persisted state', 'positions must match'],
      ['Evidence', 'log-only until structured cold-start rows exist'],
    ];
    return `<span class="c1-spec-label">Active rule</span>${parts.map(([label, value]) => `<span><b>${esc(label)}</b>${esc(value)}</span>`).join('')}`;
  }

  function b3MoreInfo(gate, statePersist, currentProtection) {
    const m = gate.metrics || {};
    const state = (statePersist && statePersist.metrics) || {};
    const protection = (currentProtection && currentProtection.metrics) || {};
    const positions = state.operational_positions || {};
    return `<details class="c1-more-info b3-more-info"><summary><span>More info</span><small>raw logs, persisted state, sources</small></summary><div class="c1-more-grid"><section class="more-section"><h3>Raw log counters</h3><p class="detail-copy">Purpose: separate current dashboard status from raw log evidence. B3 match/mismatch counters are read from scheduler/live-day logs; they are not yet grouped into structured cold-start sessions.</p><dl class="metric-list">${metricLine('matches', m.matches ?? 0)}${metricLine('mismatches', m.mismatches ?? 0)}${metricLine('cold starts', m.cold_starts ?? 0)}${metricLine('gate evidence', gate.evidence || '--')}</dl></section><section class="more-section"><h3>Persisted state</h3><p class="detail-copy">Current persisted state is shown for context only. It can prove current file state has protection, but it does not erase historical B3 mismatch log lines.</p><dl class="metric-list">${metricLine('persist match', positions.persist_match ?? '--')}${metricLine('position count', positions.count ?? protection.positions ?? '--')}${metricLine('protected positions', protection.protected ?? '--')}${metricLine('live_positions error', protection.live_positions_error || state.live_positions_error || '--')}</dl></section><section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(gate.sources)}</ul></section><p class="detail-note">This panel intentionally reports B3 mismatch lines as breach evidence until the logs can be grouped into cold-start sessions or marked as replay/noise by structured monitoring data.</p></div></details>`;
  }

  function updateB3Panel(gates, coverage) {
    const gate = gates.find(item => item.key === 'b3_reconcile') || {};
    const statePersist = coverage.find(item => item.key === 'state_persist') || {};
    const currentProtection = coverage.find(item => item.key === 'current_protection') || {};
    const m = gate.metrics || {};
    const state = statePersist.metrics || {};
    const protection = currentProtection.metrics || {};
    const positions = state.operational_positions || {};
    const matches = m.matches ?? 0;
    const mismatches = m.mismatches ?? 0;
    const coldStarts = m.cold_starts ?? 0;
    const persistMatch = positions.persist_match;
    const protectedCount = protection.protected ?? 0;
    const positionCount = protection.positions ?? positions.count ?? 0;
    const status = gate.status || 'UNKNOWN';
    const reasons = [
      mismatches ? `mismatch ${mismatches}` : `match ${matches}`,
      coldStarts ? `cold starts ${coldStarts}` : 'cold-start rows missing',
      persistMatch === true ? 'persist match true' : persistMatch === false ? 'persist mismatch' : 'persist unknown',
      `${protectedCount}/${positionCount} protected`,
    ];

    $('b3ProgressTitle').textContent = `match ${matches} | mismatch ${mismatches}`;
    $('b3ProgressReason').innerHTML = reasons.map(c1ReasonChip).join('');
    $('b3ProgressStatus').textContent = status;
    $('b3ProgressStatus').className = `gate-state ${statusClass(status)}`;
    $('b3StatusEyebrow').className = `eyebrow c1-eyebrow ${statusClass(status)}`;
    $('b3ActiveSpec').innerHTML = b3RuleRail();
    $('b3MetricGroups').innerHTML = [
      c1MetricGroup('Observed data', [
        c1Metric('Matches', matches, 'B3 broker/file match log observations.', matches ? 'ok' : 'watch'),
        c1Metric('Mismatches', mismatches, 'Any mismatch keeps B3 in breach until classified.', mismatches ? 'bad' : 'ok'),
        c1Metric('Cold starts', coldStarts, 'Runner-start observations from logs.'),
        c1Metric('Persist match', persistMatch == null ? '--' : String(persistMatch), 'Latest runner-state persisted-position match flag.', persistMatch === true ? 'ok' : persistMatch === false ? 'bad' : 'watch'),
        c1Metric('Protected', `${protectedCount}/${positionCount}`, 'Current persisted positions with stop_order_id.', positionCount && protectedCount >= positionCount ? 'ok' : 'watch'),
        c1Metric('Live state', statePersist.status || '--', 'Current state-persist coverage status.', statusClass(statePersist.status || '') === 'observed' ? 'ok' : ''),
      ]),
      b3MoreInfo(gate, statePersist, currentProtection),
    ].join('');
  }

  function twsRuleRail(required) {
    const parts = [
      ['Minimum nights', required ?? '--'],
      ['Restart proven', 'true'],
      ['Runner resumed', 'true'],
      ['Broker verified', 'true'],
      ['Candidate logs', 'not enough alone'],
    ];
    return `<span class="c1-spec-label">Active rule</span>${parts.map(([label, value]) => `<span><b>${esc(label)}</b>${esc(value)}</span>`).join('')}`;
  }

  function twsMoreInfo(gate) {
    const m = gate.metrics || {};
    const days = m.candidate_days || [];
    return `<details class="c1-more-info tws-more-info"><summary><span>More info</span><small>candidate days, input format, sources</small></summary><div class="c1-more-grid"><section class="more-section"><h3>Candidate evidence</h3><p class="detail-copy">Purpose: separate noisy connectivity/restart log candidates from proven restart nights. Candidate lines show that IBKR/TWS connectivity events happened; they do not prove the restart workflow was completed.</p><dl class="metric-list">${metricLine('candidate log lines', m.candidate_log_lines ?? 0)}${metricLine('candidate days', days.length ? days.join(', ') : '--')}${metricLine('structured records', m.records ?? 0)}${metricLine('proven restart nights', m.restart_nights ?? 0)}${metricLine('required nights', m.required_nights ?? '--')}</dl></section><section class="more-section"><h3>Structured input</h3><p class="detail-copy">To turn a candidate day into a proven night, monitor/paper_inputs.json needs a tws_restart_nights record with restart_proven, runner_resumed, and broker_verified all true. A tws_restart_spec.min_nights value is also required before the gate can pass.</p><dl class="metric-list">${metricLine('input path', 'monitor/paper_inputs.json')}${metricLine('required flags', 'restart_proven + runner_resumed + broker_verified')}${metricLine('spec field', 'tws_restart_spec.min_nights')}${metricLine('gate evidence', gate.evidence || '--')}</dl></section><section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(gate.sources)}</ul></section><p class="detail-note">This panel does not count raw reconnect/disconnect text as a successful restart. It remains a SPEC_GAP until a minimum-night threshold exists, then PENDING until enough structured nights are proven.</p></div></details>`;
  }

  function updateTWSPanel(gates) {
    const gate = gates.find(item => item.key === 'tws_restart_nights') || {};
    const m = gate.metrics || {};
    const candidateLines = m.candidate_log_lines ?? 0;
    const candidateDays = (m.candidate_days || []).length;
    const proven = m.restart_nights ?? 0;
    const required = m.required_nights;
    const records = m.records ?? 0;
    const status = gate.status || 'UNKNOWN';
    const reasons = [
      required == null ? 'required unset' : `required ${required}`,
      proven ? `proven ${proven}` : 'proven missing',
      candidateLines ? `candidate lines ${candidateLines}` : 'candidate lines missing',
      records ? `structured records ${records}` : 'structured records missing',
    ];

    $('twsProgressTitle').textContent = `proven ${proven}${required != null ? `/${required}` : ''} | candidates ${candidateDays} day(s)`;
    $('twsProgressReason').innerHTML = reasons.map(c1ReasonChip).join('');
    $('twsProgressStatus').textContent = status;
    $('twsProgressStatus').className = `gate-state ${statusClass(status)}`;
    $('twsStatusEyebrow').className = `eyebrow c1-eyebrow ${statusClass(status)}`;
    $('twsActiveSpec').innerHTML = twsRuleRail(required);
    $('twsMetricGroups').innerHTML = [
      c1MetricGroup('Observed data', [
        c1Metric('Candidate lines', candidateLines, 'Raw connectivity/restart candidate log lines.', candidateLines ? 'watch' : ''),
        c1Metric('Candidate days', candidateDays, 'Distinct days with candidate restart/connectivity logs.', candidateDays ? 'watch' : ''),
        c1Metric('Proven nights', proven, 'Structured nights with restart, runner, and broker proof.', proven ? 'ok' : 'watch'),
        c1Metric('Required nights', required ?? '--', 'Minimum proven nights required by active spec.', required == null ? 'watch' : 'ok'),
        c1Metric('Records', records, 'Structured tws_restart_nights records.', records ? 'ok' : 'watch'),
        c1Metric('Gate status', status, 'Current TWS restart gate status.', status === 'PASS' ? 'ok' : status === 'SPEC_GAP' ? 'watch' : ''),
      ]),
      twsMoreInfo(gate),
    ].join('');
  }

  function updateC1Panel(gates, summary) {
    const gate = gates.find(item => item.key === 'c1_slippage') || {};
    const m = gate.metrics || {};
    const spec = m.spec || {};
    const target = Number(spec.min_n || 0);
    const maxMean = spec.max_mean_ticks;
    const openN = m.open_n ?? summary.c1_open_n ?? 0;
    const stpN = m.stp_close_n ?? m.close_n ?? summary.c1_close_n ?? 0;
    const openMean = m.open_mean ?? summary.c1_open_mean;
    const stpMean = m.stp_close_mean ?? m.close_mean ?? summary.c1_close_mean;
    const scope = spec.scope || 'separate';
    const enough = target > 0 && openN >= target && stpN >= target;
    const currentReads = [meanRead('OPEN', openMean, openN, maxMean), meanRead('STP CLOSE', stpMean, stpN, maxMean)];
    const status = gate.status || 'UNKNOWN';

    $('c1ProgressTitle').textContent = target ? `OPEN ${openN}/${target} | STP ${stpN}/${target}` : `OPEN ${openN} | STP ${stpN}`;
    $('c1ProgressReason').innerHTML = [
      ...currentReads,
      ...(enough ? [] : ['sample gate incomplete']),
      `scope ${scope}`,
    ].map(c1ReasonChip).join('');
    $('c1ProgressStatus').textContent = status;
    $('c1ProgressStatus').className = `gate-state ${statusClass(status)}`;
    $('c1StatusEyebrow').className = `eyebrow c1-eyebrow ${statusClass(status)}`;
    $('c1ActiveSpec').innerHTML = c1SpecPills(spec, target, maxMean);
    $('c1MetricGroups').innerHTML = [
      c1MetricGroup('Observed data', [
        c1Metric('OPEN mean', fmtTicks(openMean), `Spec: abs mean <= ${maxMean ?? '--'} ticks. Current entry drift is ${meanRead('OPEN', openMean, openN, maxMean)}.`, openN && maxMean != null && Math.abs(Number(openMean)) > Number(maxMean) ? 'bad' : ''),
        c1SampleMetric('OPEN samples', openN, target, 'Progress toward required entry sample count.', target && openN >= target ? 'ok' : 'watch'),
        c1Metric('STP CLOSE mean', fmtTicks(stpMean), `Spec: abs mean <= ${maxMean ?? '--'} ticks. Stop-triggered closes only; signal closes are excluded.`),
        c1SampleMetric('STP samples', stpN, target, 'Progress toward required STP close sample count.', target && stpN >= target ? 'ok' : 'watch'),
        c1Metric('Excluded closes', m.signal_close_with_stop_ref ?? 0, 'Signal/market closes shown for diagnosis, not counted in C1 mean.'),
        c1Metric('Unknown tick rows', m.unknown_tick_records ?? 0, 'Rows that could not be converted from points to ticks.'),
      ]),
      c1MoreInfo(gate, openN, openMean, stpN, stpMean),
    ].join('');
    $('slippageCount').textContent = target ? `OPEN ${openN}/${target}` : `${openN} / ${stpN}`;
    $('c1SampleCaption').textContent = target ? `STP ${stpN}/${target} | ${meanRead('OPEN', openMean, openN, maxMean)}` : currentReads.join(' | ');
    $('closeSlippageMean').textContent = `STP ${stpN}${target ? `/${target}` : ''} | mean ${fmtTicks(stpMean)} | limit ${maxMean ?? '--'} ticks`;
  }

  function pnlCompareRows(compare) {
    const rows = (compare && compare.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No trade-by-trade Paper vs backtest comparison is available.</p>';
    return `<div class="trade-table pnl-compare-table"><table><thead><tr><th>class</th><th>trade</th><th>paper</th><th>backtest</th><th>diff</th><th>reason</th></tr></thead><tbody>${rows.map(row => `<tr><td><b>${esc(row.classification || '--')}</b><small>${esc(row.exit_day_delta == null ? '--' : `${row.exit_day_delta} day`)}</small></td><td><b>${esc(row.inst || '--')} ${esc(row.direction || '--')}</b><small>${esc(row.cluster || '--')} entry ${esc(row.entry_day || '--')}</small></td><td><b>${esc(row.paper_exit_day || '--')}</b><small>${fmtMoney(row.paper_pnl)}</small></td><td><b>${esc(row.backtest_exit_day || '--')}</b><small>${fmtMoney(row.backtest_pnl)} ${esc(row.backtest_exit_reason || '')}</small></td><td><b>${fmtMoney(row.pnl_diff)}</b><small>${esc(row.paper_exit_reason || '--')}</small></td><td>${esc(row.reason || '--')}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function pnlCompareDetail(item) {
    const compare = item.metrics && item.metrics.trade_compare;
    if (!compare) return '';
    const counts = compare.counts || {};
    const daily = compare.daily || [];
    const latest = daily.length ? daily[daily.length - 1] : {};
    return `<section class="more-section"><h3>Classification</h3><p class="detail-copy">Purpose: explain Paper P&amp;L differences without treating known live-path exit timing as a strategy mismatch. Same trade identity means instrument, cluster, direction, and entry day match.</p><dl class="metric-list">${metricLine('same dates', counts.MATCHED_SAME_DATES ?? 0)}${metricLine('known timing drift', counts.KNOWN_EXIT_TIMING_DRIFT ?? 0)}${metricLine('paper only', counts.PAPER_ONLY ?? 0)}${metricLine('backtest only', counts.BACKTEST_ONLY ?? 0)}${metricLine('unresolved', compare.unresolved ?? 0)}${metricLine('curve generated', compare.curve_generated || '--')}</dl></section><section class="more-section"><h3>Latest daily row</h3><dl class="metric-list">${metricLine('date', latest.date || '--')}${metricLine('actual equity', fmtMoney(latest.actual_equity))}${metricLine('account-window diff', fmtMoney(latest.account_window_diff))}${metricLine('trade-filter diff', fmtMoney(latest.trade_filter_realized_diff))}${metricLine('curve status', latest.curve_status || '--')}</dl></section><section class="more-section trade-detail"><h3>Trade-by-trade reasons (${esc(compare.shown ?? 0)} / ${esc(compare.total ?? 0)})</h3>${pnlCompareRows(compare)}</section><p class="detail-note">Known exit timing drift is expected when the paper/live path defers a stop/exit after the 14h/EOD decision. Those rows should be explained, not collapsed into paper-only/backtest-only mismatches.</p>`;
  }

  function coverageItem(item) {
    const active = item.key === selectedCoverageKey ? ' active' : '';
    return `<button class="coverage-item${active}" type="button" data-coverage-key="${esc(item.key)}"><b>${esc(item.title)}</b><span class="gate-state ${statusClass(item.status)}">${esc(item.status)}</span><p>${esc(item.evidence)}</p><small>${esc(sourceLine(item))}</small></button>`;
  }

  function coverageMetrics(metrics) {
    const entries = Object.entries(metrics || {}).filter(([, value]) => value == null || ['string', 'number', 'boolean'].includes(typeof value));
    if (!entries.length) return '<p class="detail-empty">No scalar metrics for this item.</p>';
    return `<dl class="metric-list">${entries.slice(0, 12).map(([key, value]) => metricLine(key, value ?? '--')).join('')}</dl>`;
  }

  function ruleClass(text) {
    const head = String(text || '').split(':')[0].toLowerCase();
    if (head === 'pass') return 'ok';
    if (head === 'breach') return 'bad';
    if (head === 'pending') return 'watch';
    return 'neutral';
  }

  function listItems(items) {
    return `<ul class="detail-list">${(items || []).map(item => `<li class="${ruleClass(item)}">${esc(item)}</li>`).join('')}</ul>`;
  }

  function detailProgress(value, target, invert = false) {
    const n = Number(value);
    const d = Number(target);
    if (!Number.isFinite(n) || !Number.isFinite(d) || d < 0) return '';
    const denominator = d === 0 ? Math.max(n, 1) : d;
    const raw = d === 0 ? (n === 0 ? 100 : 100) : (n / denominator) * 100;
    const width = Math.max(0, Math.min(100, Math.round(raw)));
    return `<i class="detail-progress ${invert ? 'invert' : ''}"><em style="width:${width}%"></em></i>`;
  }

  function metricCard(label, value, description, cls, status, specText, progress = '') {
    const progressClass = progress ? '' : ' no-progress';
    return `<article class="detail-metric ${cls}${progressClass}"><span class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(description)}">${esc(label)}</span><div class="detail-metric-readout"><b>${esc(value)}</b>${progress}</div><small><strong>${esc(status)}</strong>${specText ? ` | ${esc(specText)}` : ''}</small></article>`;
  }

  function fillMetricCards(m) {
    const spec = m.spec || {};
    const partialRate = m.partial_rate == null ? '--' : Number(m.partial_rate).toFixed(4);
    const fillsOk = (m.fills ?? 0) >= (spec.min_fills ?? Infinity);
    const partialOk = Number(m.partial_rate || 0) <= Number(spec.max_partial_rate ?? 0);
    const failedOk = (m.failed_or_cancelled ?? 0) <= (spec.max_failed_or_cancelled ?? 0);
    const malformedOk = (m.malformed_trade_log_lines ?? 0) === 0;
    const missingOk = (m.missing_required_field_rows ?? 0) === 0;
    const scaleOk = Number(m.max_contracts_observed || 0) <= Number(m.max_contracts_tested || 0);
    return `<div class="detail-metric-grid">${[
      metricCard('Fills', `${m.fills ?? 0} / ${spec.min_fills ?? '--'}`, 'Count of OPEN/CLOSE fill records in the active paper epoch.', fillsOk ? 'ok' : 'watch', fillsOk ? 'PASS' : 'PENDING', `min ${spec.min_fills ?? '--'}`, detailProgress(m.fills, spec.min_fills)),
      metricCard('Partial rate', partialRate, 'partials / fills; with current quantity=1 this mostly proves single-contract behavior only.', partialOk ? 'ok' : 'bad', partialOk ? 'PASS' : 'BREACH', `max ${spec.max_partial_rate ?? '--'}`),
      metricCard('Failed/cancelled', m.failed_or_cancelled ?? 0, 'Fill records whose status is not FILLED/PARTIAL/blank.', failedOk ? 'ok' : 'bad', failedOk ? 'PASS' : 'BREACH', `max ${spec.max_failed_or_cancelled ?? '--'}`),
      metricCard('Completeness', m.missing_required_field_rows ?? 0, 'Rows missing fields needed for later audit, including identity, size, fill price, timestamp, and exit P&L for CLOSE rows.', missingOk ? 'ok' : 'bad', missingOk ? 'PASS' : 'BREACH', spec.require_complete_fields ? 'required' : 'not required'),
      metricCard('Partials', m.partials ?? 0, 'Records where filled_qty is lower than requested contracts.', (m.partials ?? 0) ? 'bad' : 'ok', (m.partials ?? 0) ? 'BREACH' : 'PASS', 'must be 0'),
      metricCard('Malformed lines', m.malformed_trade_log_lines ?? 0, 'JSONL lines that could not be parsed as retained fill history.', malformedOk ? 'ok' : 'bad', malformedOk ? 'PASS' : 'BREACH', 'must be 0'),
      metricCard('Max contracts', m.max_contracts_observed ?? '--', 'Largest contracts value seen in the paper-epoch fill records.', scaleOk ? 'ok' : 'watch', scaleOk ? 'PASS' : 'RETEST', `tested ${m.max_contracts_tested ?? '--'}`, detailProgress(m.max_contracts_observed ?? 0, m.max_contracts_tested ?? 0)),
      metricCard('Retest scale', m.retest_when_contracts_gt ?? '--', 'Retest fill quality before scaling above the largest contracts value covered by paper trade history.', 'watch', 'WATCH', `when > ${m.retest_when_contracts_gt ?? '--'}`),
    ].join('')}</div>`;
  }

  function fillTradeRows(samples) {
    const rows = (samples && samples.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No fill trade rows are available.</p>';
    return `<p class="detail-copy table-note">For CLOSE rows, entry and exit show the held trade window. Points are raw price movement; ticks = points / instrument tick size, so the conversion differs by instrument.</p><div class="trade-table fill-quality-table"><table><thead><tr><th>result</th><th>type</th><th>trade</th><th>entry/exit</th><th>qty</th><th>fill</th><th>ref</th><th>slip</th><th>pnl</th><th>timestamp</th></tr></thead><tbody>${rows.map(row => {
      const cls = row.failed_or_cancelled ? 'bad' : row.partial || (row.missing_fields || []).length ? 'watch' : 'ok';
      const result = row.failed_or_cancelled ? 'FAILED' : row.partial ? 'PARTIAL' : (row.missing_fields || []).length ? 'INCOMPLETE' : 'CLEAN';
      const missing = (row.missing_fields || []).length ? `missing ${(row.missing_fields || []).join(', ')}` : row.status || '--';
      const ts = String(row.ts || '--').replace('T', ' ').replace('+00:00', 'Z');
      const slipTicks = Number(row.slip_ticks);
      const slipLabel = !Number.isFinite(slipTicks) ? '--' : slipTicks > 0 ? 'adverse' : slipTicks < 0 ? 'favorable' : 'flat';
      const slipClass = slipTicks > 0 ? 'bad' : slipTicks < 0 ? 'ok' : 'neutral';
      const typeClass = String(row.type || '').toLowerCase();
      const directionClass = String(row.direction || '').toLowerCase();
      const pnl = Number(row.pnl_sized);
      const pnlClass = !Number.isFinite(pnl) || pnl === 0 ? 'neutral' : pnl > 0 ? 'ok' : 'bad';
      return `<tr><td><span class="fill-result ${cls}">${esc(result)}</span><small>${esc(missing)}</small></td><td><span class="type-chip ${typeClass}">${esc(row.type || '--')}</span><small>${esc(row.status || '--')}</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.cluster || '--')}</small></td><td><b>${esc(row.entry_day || '--')}</b><small>${row.exit_day ? `exit ${esc(row.exit_day)}` : 'open fill'}</small></td><td><b>${esc(row.filled_qty ?? '--')} / ${esc(row.contracts ?? '--')}</b><small>filled / order</small></td><td><b>${fmtPrice(row.fill_price)}</b><small>broker fill</small></td><td><b>${fmtPrice(row.reference_price)}</b><small>${esc(row.reference_type || '--')}</small></td><td><b>${fmtTicks(row.slip_ticks)}</b><small><span class="slip-label ${slipClass}">${esc(slipLabel)}</span> ${fmtSigned2(row.slip_points, ' pts')}</small></td><td><b class="pnl-value ${pnlClass}">${fmtPnl(row.pnl_sized)}</b><small>CLOSE only</small></td><td><b>${esc(ts.slice(0, 10))}</b><small>${esc(ts.slice(11))}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function fillQualityDetail(item) {
    const m = item.metrics || {};
    return `<section class="more-section trade-detail"><h3>What This Measures</h3><p class="detail-copy">${esc(m.description || 'Fill quality validates retained fill history.')}</p></section><section class="more-section trade-detail"><h3>Metrics</h3>${fillMetricCards(m)}<p class="detail-copy scale-note">${esc(m.scale_note || '')}</p></section><section class="more-section trade-detail"><h3>Fill Trade Details (${esc(m.trade_samples?.shown ?? 0)} / ${esc(m.trade_samples?.total ?? 0)})</h3>${fillTradeRows(m.trade_samples)}</section><section class="more-section trade-detail"><h3>Status Rules</h3>${listItems(m.status_rules || [])}</section>`;
  }

  function stpPlacementMetricCards(m) {
    const acceptedOk = (m.accepted ?? 0) >= (m.min_accepted ?? Infinity);
    const failedOk = (m.failed ?? 0) <= (m.max_failed ?? 0);
    const hasDeferRule = !!(m.spec && m.spec.require_defer_rule);
    return `<div class="detail-metric-grid">${[
      metricCard('Accepted STP', `${m.accepted ?? 0} / ${m.min_accepted ?? '--'}`, m.metric_descriptions?.accepted || 'Broker accepted protective STP orders.', acceptedOk ? 'ok' : 'watch', acceptedOk ? 'PASS' : 'PENDING', `min ${m.min_accepted ?? '--'}`, detailProgress(m.accepted, m.min_accepted)),
      metricCard('Failed STP', m.failed ?? 0, m.metric_descriptions?.failed || 'Stop placement failures after arm attempt.', failedOk ? 'ok' : 'bad', failedOk ? 'PASS' : 'BREACH', `max ${m.max_failed ?? '--'}`),
      metricCard('Deferred opens', m.deferred ?? 0, m.metric_descriptions?.deferred || 'OPEN fills routed into the allowed stop-free window.', (m.deferred ?? 0) ? 'watch' : 'ok', (m.deferred ?? 0) ? 'EXPECTED' : 'NONE', 'not a breach'),
      metricCard('Defer rule', hasDeferRule ? 'ACTIVE' : 'MISSING', m.metric_descriptions?.defer_rule || 'Per-sleeve 14h stop arm rule.', hasDeferRule ? 'ok' : 'bad', hasDeferRule ? 'PASS' : 'SPEC_GAP', 'required'),
    ].join('')}</div>`;
  }

  function stpPlacementRows(samples) {
    const rows = (samples && samples.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No STP placement evidence rows are available.</p>';
    return `<div class="trade-table stp-placement-table"><table><thead><tr><th>result</th><th>trade id</th><th>qty/stop</th><th>order</th><th>evidence</th><th>reconcile</th></tr></thead><tbody>${rows.map(row => {
      const kind = String(row.kind || '--').toUpperCase();
      const cls = kind === 'ACCEPTED' ? 'ok' : kind === 'FAILED' ? 'bad' : 'watch';
      const directionClass = String(row.direction || '').toLowerCase();
      const evidence = `${row.path || '--'}${row.line_no ? `:${row.line_no}` : ''}`;
      const orderText = row.order_id || (kind === 'DEFERRED' ? 'deferred' : kind === 'FAILED' ? 'none' : '--');
      const qty = row.qty ?? row.filled_qty ?? row.contracts;
      return `<tr><td><span class="fill-result ${cls}">${esc(kind)}</span><small>${esc(row.day || '--')}</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.trade_id || row.match_status || '--')}</small></td><td><b>${qty == null ? '--' : `x${esc(qty)}`}</b><small>${fmtPrice(row.stop_price)}</small></td><td><b>${esc(orderText)}</b><small>${esc(row.order_status || row.match_status || '--')}</small></td><td><b class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(row.raw || '')}">${esc(evidence)}</b><small>${esc(row.ts || '--')}</small></td><td><b>${esc(row.match_status || '--')}</b><small>${esc(row.reason || '--')}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function stpOutcomeLabel(outcome) {
    const value = String(outcome || '--');
    if (value === 'ACCEPTED_AFTER_DEFER') return 'ACCEPTED';
    if (value === 'CLOSED_BEFORE_ARM') return 'CLOSED';
    if (value === 'FAILED_AFTER_DEFER') return 'FAILED';
    if (value === 'NO_ACCEPT_FOUND') return 'MISSING';
    return value;
  }

  function fmtHours(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${Math.abs(n).toFixed(2)}h ${n >= 0 ? 'before arm' : 'after arm'}`;
  }

  function shortTs(value) {
    const text = String(value || '--').replace('T', ' ').replace('+00:00', 'Z');
    return text === '--' ? text : text.slice(0, 16).replace(' ', ' ');
  }

  function stpRouteReconcileRows(reconcile) {
    const rows = (reconcile && reconcile.rows) || [];
    const unmatched = (reconcile && reconcile.unmatched_failed) || [];
    if (!rows.length && !unmatched.length) return '<p class="detail-empty">No deferred route reconcile rows are available.</p>';
    const routeRows = rows.map(row => {
      const cls = row.outcome === 'ACCEPTED_AFTER_DEFER' ? 'ok' : row.outcome === 'CLOSED_BEFORE_ARM' ? 'watch' : 'bad';
      const directionClass = String(row.direction || '').toLowerCase();
      const timing = row.outcome === 'CLOSED_BEFORE_ARM'
        ? `<b>${esc(shortTs(row.close_at))}</b><small>${esc(fmtHours(row.hours_before_arm))} | arm ${esc(shortTs(row.arm_at))}</small>`
        : `<b>${esc(row.entry_day || '--')}</b><small>${row.exit_day ? `exit ${esc(row.exit_day)}` : 'still open/no close'}</small>`;
      return `<tr><td><span class="fill-result ${cls}">${esc(stpOutcomeLabel(row.outcome))}</span><small>${esc(row.outcome || '--')}</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(row.trade_id || '')}">${esc(row.entry_day || '--')} / ${esc(row.cluster || '--')}</small></td><td><b>${row.qty == null ? '--' : `x${esc(row.qty)}`}</b><small>${fmtPrice(row.stop_price)}</small></td><td>${timing}</td><td><b>${esc(row.close_reason || '--')}</b><small>${esc(row.detail || '--')}</small></td><td><b>${esc(row.deferred_at || '--')}</b><small>route decision</small></td></tr>`;
    }).join('');
    const failRows = unmatched.map(row => `<tr><td><span class="fill-result bad">UNMATCHED</span><small>failed log</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${String(row.direction || '').toLowerCase()}">${esc(row.direction || '--')}</span></b><small>${esc(row.match_status || '--')}</small></td><td><b>${row.qty == null ? '--' : `x${esc(row.qty)}`}</b><small>${fmtPrice(row.stop_price)}</small></td><td><b>${esc(row.day || '--')}</b><small>${esc(row.ts || '--')}</small></td><td><b>not a paper OPEN</b><small>${esc(row.reason || '--')}</small></td><td><b>${esc(row.path || '--')}:${esc(row.line_no || '--')}</b><small>failed placement</small></td></tr>`).join('');
    return `<div class="trade-table stp-route-table"><table><thead><tr><th>status</th><th>trade</th><th>qty/stop</th><th>close vs arm</th><th>reason</th><th>evidence</th></tr></thead><tbody>${routeRows}${failRows}</tbody></table></div>`;
  }

  function stpPlacementDetail(item) {
    const m = item.metrics || {};
    const divergence = m.backtest_divergence || 'No immediate STP after OPEN is expected for deferred swing/NKD entries; paper/live waits for the 14h per-sleeve arm rule to match backtest stop semantics.';
    const armTimes = (m.arm_times || []).length ? m.arm_times : ['roska4_swing: arm at 14:00 America/New_York; first normal trading slot is 14:05 ET.', 'global_nkd: arm at 14:00 Asia/Tokyo.', 'roska4_stress: not deferred.'];
    return `<section class="more-section trade-detail"><h3>What This Measures</h3><p class="detail-copy">${esc(m.description || 'Stop placement validates accepted, failed, and intentionally deferred STP evidence.')}</p></section><section class="more-section trade-detail"><h3>Metrics</h3>${stpPlacementMetricCards(m)}</section><section class="more-section trade-detail"><h3>Backtest Divergence</h3><p class="detail-copy">${esc(divergence)}</p><ul class="detail-list divergence-list">${armTimes.map(item => `<li class="${String(item).includes('roska4_stress') ? 'neutral' : 'watch'}">${esc(item)}</li>`).join('')}</ul></section><section class="more-section trade-detail"><h3>Route Reconcile</h3>${stpRouteReconcileRows(m.route_reconcile)}</section><section class="more-section trade-detail"><h3>Placement Evidence (${esc(m.placement_samples?.shown ?? 0)} / ${esc(m.placement_samples?.total ?? 0)})</h3>${stpPlacementRows(m.placement_samples)}</section><section class="more-section trade-detail"><h3>Status Rules</h3>${listItems(m.status_rules || [])}</section>`;
  }

  function coverageDetail(item) {
    if (!item) return '<aside class="coverage-detail"><p class="detail-empty">Select a coverage item.</p></aside>';
    const pvb = item.key === 'paper_vs_backtest' ? pnlCompareDetail(item) : '';
    const fill = item.key === 'fill_quality' ? fillQualityDetail(item) : '';
    const stpPlacement = item.key === 'stp_placement' ? stpPlacementDetail(item) : '';
    const evidence = item.key === 'fill_quality' || item.key === 'stp_placement' ? '' : `<p class="coverage-detail-evidence">${esc(item.evidence)}</p>`;
    return `<aside class="coverage-detail"><div class="coverage-detail-head"><h3>${esc(item.title)}</h3><span class="gate-state ${statusClass(item.status)}">${esc(item.status)}</span></div>${evidence}<div class="c1-more-grid">${pvb || fill || stpPlacement || `<section class="more-section"><h3>Metrics</h3>${coverageMetrics(item.metrics)}</section>`}<section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(item.sources)}</ul></section></div></aside>`;
  }

  const coverageGroups = [
    ['Execution health', ['fill_quality', 'stp_placement', 'rejections', 'paper_vs_backtest']],
    ['State and protection', ['state_persist', 'current_protection', 'runner_freshness']],
    ['Data and model', ['data_freshness', 'open_incidents']],
    ['Operator and sample context', ['manual_intervention', 'roll_slippage', 'sample_denominators', 'same_day_multi_day', 'log_hygiene']],
  ];

  function groupedCoverage(items) {
    const byKey = new Map(items.map(item => [item.key, item]));
    const used = new Set();
    if (!byKey.has(selectedCoverageKey)) selectedCoverageKey = byKey.has('paper_vs_backtest') ? 'paper_vs_backtest' : (items[0] && items[0].key) || '';
    const selected = byKey.get(selectedCoverageKey);
    const sections = coverageGroups.map(([title, keys]) => {
      const cards = keys.map(key => byKey.get(key)).filter(Boolean);
      cards.forEach(item => used.add(item.key));
      return cards.length ? `<section class="coverage-group"><h3>${esc(title)}</h3><div>${cards.map(coverageItem).join('')}</div></section>` : '';
    }).join('');
    const remaining = items.filter(item => !used.has(item.key));
    const list = `${sections}${remaining.length ? `<section class="coverage-group"><h3>Other evidence</h3><div>${remaining.map(coverageItem).join('')}</div></section>` : ''}`;
    return `<div class="coverage-master-detail"><div class="coverage-list">${list}</div>${coverageDetail(selected)}</div>`;
  }

  function renderCoverage(items) {
    $('paperCoverage').innerHTML = groupedCoverage(items);
    $('paperCoverage').querySelectorAll('[data-coverage-key]').forEach(button => {
      button.addEventListener('click', () => {
        selectedCoverageKey = button.getAttribute('data-coverage-key') || selectedCoverageKey;
        renderCoverage(items);
      });
    });
  }

  function gapType(item) {
    const text = `${item.title || ''} ${item.detail || ''}`.toLowerCase();
    if (/threshold|required nights|spec|numeric/.test(text)) return 'SPEC';
    if (/structured|ledger|classification/.test(text)) return 'DATA';
    if (/runner|engine|expected close/.test(text)) return 'ENGINE DECISION';
    return 'DATA';
  }

  function gapInput(item) {
    const title = String(item.title || '').toLowerCase();
    if (title.includes('tws')) return 'Set tws_restart_spec.min_nights and add proven tws_restart_nights records.';
    if (title.includes('stp')) return 'Add structured STP verification records with false_halt/double_stp classification.';
    if (title.includes('manual')) return 'Add structured manual intervention records with resolution and post-action verification.';
    if (title.includes('signal close')) return 'No read-only close reference exists; keep excluded from C1 and cover with Paper P&L vs backtest.';
    return 'Define the structured input needed to classify this evidence.';
  }

  function gapItem(item) {
    const type = gapType(item);
    return `<article class="gap-item ${statusClass(type)}"><span>${esc(type)}</span><b>${esc(item.title)}</b><p>${esc(item.detail)}</p><small>${esc(gapInput(item))}</small></article>`;
  }

  function render(data) {
    const payload = data.payload || {};
    const gates = payload.gates || [];
    const coverage = payload.coverage || [];
    const summary = payload.summary || {};
    const statuses = gates.map(gate => gate.status);
    const sourceMissing = !gates.length || data.freshness === 'missing';
    const blocked = statuses.some(status => status === 'SPEC_GAP' || status === 'STRUCTURAL_GAP');
    const breached = statuses.includes('BREACH');
    const complete = !sourceMissing && !blocked && !breached && gates.every(gate => gate.status === 'PASS');
    $('paperDays').textContent = `${summary.days ?? 0} / 60`;
    $('regimesSeen').textContent = (summary.regimes || []).length ? summary.regimes.join(' + ') : 'None';
    $('exitCoverage').textContent = `${summary.exit_paths_complete ?? 0} / 3`;
    $('slippageMean').textContent = fmtTicks(summary.c1_open_mean);
    updateCoveragePanel(gates);
    updateC1Panel(gates, summary);
    updateSTPPanel(gates, coverage);
    updateB3Panel(gates, coverage);
    updateTWSPanel(gates);
    $('paperSource').textContent = `Paper epoch ${payload.epoch || 'missing'} | source ${data.source || 'unknown'} | observed ${data.observed_at || 'unknown'}`;
    renderCoverage(coverage);
    $('evidenceGaps').innerHTML = (payload.gaps || []).map(gapItem).join('');
    const readiness = $('overallStatus').parentElement;
    readiness.classList.toggle('unknown', sourceMissing);
    readiness.classList.toggle('complete', complete);
    $('overallStatus').textContent = sourceMissing ? 'UNKNOWN' : complete ? 'EVIDENCE COMPLETE' : breached ? 'BREACH' : blocked ? 'SPEC BLOCKED' : 'INSUFFICIENT DATA';
    $('overallReason').textContent = sourceMissing ? 'Paper evidence source is unavailable' : complete ? 'All observable gates passed' : breached ? 'At least one observed gate breached' : blocked ? 'At least one gate needs a quantified decision before it can pass' : 'Pending evidence remains';
  }

  async function load() {
    try {
      const response = await fetch('/api/v1/paper-evidence', { cache: 'no-store', signal: AbortSignal.timeout(30000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      const readiness = $('overallStatus').parentElement;
      readiness.classList.add('unknown');
      readiness.classList.remove('complete');
      $('overallStatus').textContent = 'UNKNOWN';
      $('overallReason').textContent = `Paper evidence unavailable: ${error.message}`;
      $('paperSource').textContent = 'Paper evidence source unavailable';
    }
  }

  load();
  window.setInterval(load, 60000);
})();
