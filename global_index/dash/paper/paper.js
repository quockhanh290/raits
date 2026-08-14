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
    if (value == null || value === '') return '--';
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--';
  }

  function fmtMoney(value) {
    if (value == null || value === '') return '--';
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : '-'}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function fmtDollar(value) {
    if (value == null || value === '') return '--';
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function fmtEquity(value) {
    if (value == null || value === '') return '--';
    const n = Number(value);
    return Number.isFinite(n) ? `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--';
  }

  function fmtSigned2(value, suffix = '') {
    if (value == null || value === '') return '--';
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}${suffix}`;
  }

  function fmtPnl(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n === 0) return '-';
    return `${n > 0 ? '+' : '-'}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function sumField(rows, key) {
    return (rows || []).reduce((total, row) => {
      const n = Number(row && row[key]);
      return Number.isFinite(n) ? total + n : total;
    }, 0);
  }

  function moneyClass(value) {
    const n = Number(value);
    return !Number.isFinite(n) || n === 0 ? 'neutral' : n > 0 ? 'ok' : 'bad';
  }

  function reconcileStatus(left, right) {
    const a = Number(left);
    const b = Number(right);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return { label: 'CHECK', cls: 'watch' };
    return Math.abs(a - b) < 0.005 ? { label: 'RECONCILED', cls: 'ok' } : { label: 'CHECK', cls: 'bad' };
  }

  function verdictClass(status) {
    const value = String(status || '').toUpperCase();
    if (value === 'PASS' || value === 'RECONCILED') return 'ok';
    if (value === 'BREACH' || value === 'FAIL') return 'bad';
    if (value === 'EXPLAINED' || value === 'WATCH' || value === 'PENDING') return 'watch';
    return 'neutral';
  }

  function tableVerdict(status, title, summary, facts = []) {
    const statusText = status || 'CHECK';
    const factItems = (facts || []).filter(Boolean).map(item => `<span>${esc(item)}</span>`).join('');
    return `<div class="table-verdict ${verdictClass(statusText)}"><div><span class="fill-result ${verdictClass(statusText)}">${esc(statusText)}</span><b>${esc(title || 'Table verdict')}</b><p>${esc(summary || '--')}</p></div>${factItems ? `<aside>${factItems}</aside>` : ''}</div>`;
  }

  function backendVerdict(compare, key) {
    const verdict = compare && compare.verdicts && compare.verdicts[key];
    return verdict && typeof verdict === 'object' ? verdict : null;
  }

  function renderVerdict(verdict, fallbackStatus, fallbackTitle, fallbackSummary, fallbackFacts = []) {
    if (verdict) return tableVerdict(verdict.status, verdict.title, verdict.summary, verdict.facts || fallbackFacts);
    return tableVerdict(fallbackStatus, fallbackTitle, fallbackSummary, fallbackFacts);
  }

  function brokerIdentity(value) {
    const text = String(value || '');
    if (!text) return '--';
    const match = text.match(/TradeID:([^|]+)/);
    return match ? `TradeID:${match[1].trim()}` : text;
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
    const pl = (compare && compare.statement_pnl_compare) || {};
    const paperTotal = sumField(rows, 'paper_pnl');
    const backtestTotal = sumField(rows, 'backtest_pnl');
    const diffTotal = sumField(rows, 'pnl_diff');
    const gridDiff = pl.paper_minus_backtest_realized;
    const reconciled = reconcileStatus(diffTotal, gridDiff);
    const unresolved = rows.filter(row => String(row.classification || '').includes('ONLY') || String(row.classification || '').includes('UNRESOLVED')).length;
    const known = rows.filter(row => String(row.classification || '').includes('KNOWN') || String(row.reason || '').toLowerCase().includes('defer')).length;
    const verdict = reconciled.cls === 'bad' ? 'BREACH' : unresolved ? 'BREACH' : known || Math.abs(Number(diffTotal || 0)) > 0.005 ? 'EXPLAINED' : 'PASS';
    const verdictText = verdict === 'PASS'
      ? 'Paper and backtest trade totals match with no row-level exceptions.'
      : verdict === 'EXPLAINED'
        ? 'Paper and backtest differ, but the table total reconciles to the grid and row reasons classify the divergence.'
        : 'Paper/backtest trade reasons need attention because totals do not reconcile or unresolved rows remain.';
    return `${tableVerdict(verdict, 'Trade-by-trade Paper vs Backtest', verdictText, [`rows ${rows.length}`, `unresolved ${unresolved}`, `known/explained ${known}`, `grid ${reconciled.label}`])}<div class="trade-table pnl-compare-table"><table><thead><tr><th>class</th><th>trade</th><th>paper</th><th>backtest</th><th>diff</th><th>reason</th></tr></thead><tbody>${rows.map(row => `<tr><td><b>${esc(row.classification || '--')}</b><small>${esc(row.exit_day_delta == null ? '--' : `${row.exit_day_delta} day`)}</small></td><td><b>${esc(row.inst || '--')} ${esc(row.direction || '--')}</b><small>${esc(row.entry_day || '--')}</small></td><td><b>${esc(row.paper_exit_day || '--')}</b><small>${fmtMoney(row.paper_pnl)}</small></td><td><b>${esc(row.backtest_exit_day || '--')}</b><small>${fmtMoney(row.backtest_pnl)} ${esc(row.backtest_exit_reason || '')}</small></td><td><b class="pnl-value ${moneyClass(row.pnl_diff)}">${fmtMoney(row.pnl_diff)}</b><small>${esc(row.paper_exit_reason || '--')}</small></td><td>${esc(row.reason || '--')}</td></tr>`).join('')}</tbody><tfoot><tr class="total-row"><td><span class="fill-result ${reconciled.cls}">TOTAL</span></td><td><b>${esc(rows.length)} row(s)</b><small>trade table sum</small></td><td><b>${fmtMoney(paperTotal)}</b><small>paper total</small></td><td><b>${fmtMoney(backtestTotal)}</b><small>backtest total</small></td><td><b class="pnl-value ${moneyClass(diffTotal)}">${fmtMoney(diffTotal)}</b><small>grid Paper - backtest ${fmtMoney(gridDiff)}</small></td><td><span class="fill-result ${reconciled.cls}">${reconciled.label}</span><small>footer total ties back to P&amp;L Compare metric</small></td></tr></tfoot></table></div>`;
  }

  function signalCompareRows(signalCompare) {
    const rows = (signalCompare && signalCompare.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No signal-level comparison is available.</p>';
    const mismatches = rows.filter(row => String(row.classification || '') !== 'MATCHED_SIGNAL' || row.price_compare_status === 'DIFF' || row.risk_compare_status === 'DIFF').length;
    const verdict = mismatches ? 'BREACH' : 'PASS';
    return `${tableVerdict(verdict, 'Signal parity', mismatches ? 'Paper and backtest signal decisions are not identical; inspect mismatch rows before treating P&L drift as execution-only.' : 'Paper and backtest emitted matching signal decisions for the displayed rows.', [`rows ${rows.length}`, `mismatch ${mismatches}`])}<div class="trade-table signal-compare-table"><table><thead><tr><th>class</th><th>signal</th><th>paper</th><th>backtest</th><th>price</th><th>risk</th><th>reason</th></tr></thead><tbody>${rows.map(row => {
      const classification = String(row.classification || '--');
      const cls = classification === 'MATCHED_SIGNAL' ? 'ok' : 'bad';
      const paper = row.paper_sample || {};
      const backtest = row.backtest_sample || {};
      const directionClass = String(row.direction || '').toLowerCase();
      const priceCls = row.price_compare_status === 'MATCH' ? 'ok' : row.price_compare_status === 'DIFF' ? 'bad' : 'watch';
      const riskCls = row.risk_compare_status === 'MATCH' ? 'ok' : row.risk_compare_status === 'DIFF' ? 'bad' : 'watch';
      return `<tr><td><span class="fill-result ${cls}">${esc(classification)}</span><small>${esc(row.date || '--')}</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.cluster || '--')} ${esc(row.action || '--')}</small></td><td><b>${esc(row.paper_count ?? 0)} event(s)</b><small>${fmtMoney(paper.risk_sized)} ${paper.price == null ? '' : `@ ${fmtPrice(paper.price)}`}</small></td><td><b>${esc(row.backtest_count ?? 0)} event(s)</b><small>${fmtMoney(backtest.risk_sized)} ${backtest.price == null ? '' : `@ ${fmtPrice(backtest.price)}`}</small></td><td><span class="fill-result ${priceCls}">${esc(row.price_compare_status || '--')}</span><small>${fmtSigned2(row.price_diff)}</small></td><td><span class="fill-result ${riskCls}">${esc(row.risk_compare_status || '--')}</span><small>${fmtMoney(row.risk_diff)}</small></td><td><b>${esc(row.reason_code || '--')}</b><small>${esc(row.reason || paper.source || backtest.source || '--')}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function entryCompareRows(entryCompare) {
    const rows = (entryCompare && entryCompare.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No entry-level comparison is available.</p>';
    const mismatches = rows.filter(row => String(row.classification || '') !== 'MATCHED_ENTRY').length;
    const missingBroker = rows.filter(row => !row.broker_verified).length;
    const verdict = mismatches ? 'BREACH' : missingBroker ? 'PENDING' : 'PASS';
    const summary = mismatches
      ? 'At least one admitted/filled entry differs between paper and backtest.'
      : missingBroker
        ? 'Paper/backtest entries match, but one or more rows still need Flex verification.'
        : 'Paper entries match backtest admitted entries and are broker-verified where expected.';
    return `${tableVerdict(verdict, 'Entry parity', summary, [`rows ${rows.length}`, `mismatch ${mismatches}`, `broker missing ${missingBroker}`])}<div class="trade-table entry-compare-table"><table><thead><tr><th>class</th><th>trade</th><th>paper fill</th><th>backtest</th><th>Flex</th><th>diffs</th><th>reason</th></tr></thead><tbody>${rows.map(row => {
      const classification = String(row.classification || '--');
      const cls = classification === 'MATCHED_ENTRY' ? 'ok' : 'bad';
      const directionClass = String(row.direction || '').toLowerCase();
      const brokerCls = row.broker_verified ? 'ok' : 'watch';
      const audit = row.audit_ref ? `<a class="audit-link" href="#${esc(row.audit_ref)}" title="${esc(row.audit_label || 'open audit log')}">*</a>` : '';
      return `<tr><td><span class="fill-result ${cls}">${esc(classification)}</span><small>${esc(row.date || '--')}</small></td><td><b>${audit}${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b></td><td><b>${fmtPrice(row.paper_fill_price)}</b><small>expected ${fmtPrice(row.paper_expected_entry)}</small></td><td><b>${fmtPrice(row.backtest_entry_price)}</b><small>${esc(row.backtest_sample?.source || 'replay admitted entry')}</small></td><td><span class="fill-result ${brokerCls}">${row.broker_verified ? 'VERIFIED' : 'MISSING'}</span><small>${fmtPrice(row.broker_statement_price)}</small></td><td><b>${fmtSigned2(row.paper_fill_vs_backtest)}</b><small>fill-vs-bt | fill-vs-exp ${fmtSigned2(row.paper_fill_vs_expected)}</small></td><td><b>${esc(row.reason || '--')}</b><small>Flex-vs-fill ${fmtSigned2(row.broker_vs_paper_fill)}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function lifecycleSideCell(side, label) {
    const status = String((side && side.status) || 'MISSING');
    const cls = status === 'CLOSED' || status === 'OPEN' || status === 'ENTRY' ? 'ok' : 'watch';
    const entry = side && side.entry_price != null ? fmtPrice(side.entry_price) : '--';
    const exit = side && side.exit_day ? `${esc(side.exit_day)} @ ${fmtPrice(side.exit_price)}` : status === 'OPEN' ? 'still open' : '--';
    const pnl = side && side.pnl != null ? fmtMoney(side.pnl) : status === 'OPEN' ? 'open P&L not realised' : '--';
    const fee = side?.fee == null ? '--' : fmtMoney(side.fee);
    const brokerId = side?.broker_trade_id ? `<small>${esc(brokerIdentity(side.broker_trade_id))}</small>` : '';
    return `<td><span class="fill-result ${cls}">${esc(status)}</span><small>${esc(label)} qty ${esc(side?.qty ?? '--')}</small><b>open ${entry}</b><small>exit ${exit}</small><b class="pnl-value ${Number(side?.pnl) > 0 ? 'ok' : Number(side?.pnl) < 0 ? 'bad' : 'neutral'}">${pnl}</b><small>fee ${fee}</small>${brokerId}${side?.reason ? `<small>${esc(side.reason)}</small>` : ''}</td>`;
  }

  function lifecycleCompareRows(lifecycleCompare, pl = {}) {
    const rows = (lifecycleCompare && lifecycleCompare.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No lifecycle comparison rows are available.</p>';
    const paperBacktestTotal = Number.isFinite(Number(lifecycleCompare.paper_minus_backtest_sum)) ? Number(lifecycleCompare.paper_minus_backtest_sum) : sumField(rows, 'paper_minus_backtest_pnl');
    const paperFlexTotal = Number.isFinite(Number(lifecycleCompare.paper_minus_flex_sum)) ? Number(lifecycleCompare.paper_minus_flex_sum) : sumField(rows, 'paper_minus_flex_pnl');
    const paperBacktestRecon = reconcileStatus(paperBacktestTotal, pl.paper_minus_backtest_realized);
    const paperFlexRecon = reconcileStatus(paperFlexTotal, pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized);
    const mismatches = rows.filter(row => row.classification !== 'MATCHED_LIFECYCLE').length;
    const missing = rows.filter(row => [row.paper, row.backtest, row.flex].some(side => String(side?.status || '') === 'MISSING')).length;
    const verdict = paperBacktestRecon.cls === 'bad' || paperFlexRecon.cls === 'bad' || missing ? 'BREACH' : mismatches ? 'EXPLAINED' : 'PASS';
    const summary = verdict === 'PASS'
      ? 'Paper, backtest, and Flex lifecycle rows match and totals reconcile to the P&L grid.'
      : verdict === 'EXPLAINED'
        ? 'Lifecycle differences remain, but table totals reconcile and row reasons classify the differences.'
        : 'Lifecycle parity needs attention because totals do not reconcile or a source is missing for a trade.';
    return `${tableVerdict(verdict, 'Lifecycle parity', summary, [`rows ${rows.length}`, `diff rows ${mismatches}`, `missing source ${missing}`, `P-B ${paperBacktestRecon.label}`, `P-F ${paperFlexRecon.label}`])}<div class="trade-table lifecycle-compare-table"><table><thead><tr><th>class</th><th>trade</th><th>paper actual</th><th>backtest</th><th>Flex</th><th>diff/reason</th></tr></thead><tbody>${rows.map(row => {
      const cls = row.classification === 'MATCHED_LIFECYCLE' ? 'ok' : row.classification === 'THREE_WAY_DIFF' ? 'watch' : 'bad';
      const directionClass = String(row.direction || '').toLowerCase();
      const audit = row.audit_ref ? `<a class="audit-link" href="#${esc(row.audit_ref)}" title="${esc(row.audit_label || 'open audit log')}">*</a>` : '';
      return `<tr><td><span class="fill-result ${cls}">${esc(row.classification || '--')}</span></td><td><b>${audit}${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.entry_day || '--')}</small></td>${lifecycleSideCell(row.paper, 'paper')}${lifecycleSideCell(row.backtest, 'backtest')}${lifecycleSideCell(row.flex, 'Flex')}<td><b>${fmtMoney(row.paper_minus_backtest_pnl)}</b><small>paper-bt | paper-Flex ${fmtMoney(row.paper_minus_flex_pnl)}</small><small>${esc(row.reason || '--')}</small></td></tr>`;
    }).join('')}</tbody><tfoot><tr class="total-row"><td><span class="fill-result ${paperBacktestRecon.cls}">TOTAL</span></td><td><b>${esc(rows.length)} lifecycle row(s)</b><small>closed/open parity rows</small></td><td><b>${fmtMoney(pl.paper_epoch_closed_realized)}</b><small>paper realised grid</small></td><td><b>${fmtMoney(pl.backtest_epoch_closed_realized)}</b><small>backtest realised grid</small></td><td><b>${fmtMoney(pl.flex_epoch_rebased_realized ?? pl.statement_entry_epoch_realized)}</b><small>Flex zero-base grid</small></td><td><b class="pnl-value ${moneyClass(paperBacktestTotal)}">paper-bt ${fmtMoney(paperBacktestTotal)}</b><small><span class="fill-result ${paperBacktestRecon.cls}">${paperBacktestRecon.label}</span> vs grid ${fmtMoney(pl.paper_minus_backtest_realized)}</small><small><span class="fill-result ${paperFlexRecon.cls}">${paperFlexRecon.label}</span> paper-Flex ${fmtMoney(paperFlexTotal)} vs grid ${fmtMoney(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized)}</small></td></tr></tfoot></table></div>`;
  }

  function compactLifecycleCell(side, label) {
    const status = String((side && side.status) || 'MISSING');
    const cls = status === 'MISSING' ? 'bad' : status === 'OPEN' ? 'watch' : 'ok';
    const entry = side?.entry_price == null ? '--' : fmtPrice(side.entry_price);
    const exit = side?.exit_day ? `${side.exit_day} @ ${fmtPrice(side.exit_price)}` : status === 'OPEN' ? 'OPEN' : '--';
    const pnl = side?.pnl == null ? status === 'OPEN' ? 'open' : '--' : fmtMoney(side.pnl);
    const fee = side?.fee == null ? '' : ` | fee ${fmtMoney(side.fee)}`;
    const brokerId = side?.broker_trade_id ? `<small>${esc(brokerIdentity(side.broker_trade_id))}</small>` : '';
    return `<td><span class="fill-result ${cls}">${esc(status)}</span><small>${esc(label)} qty ${esc(side?.qty ?? '--')}</small><b>${entry} -> ${esc(exit)}</b><small>${esc(pnl)}${esc(fee)}</small>${brokerId}</td>`;
  }

  function tradeMasterReconcileRows(compare, pl = {}) {
    const lifecycle = (compare && compare.lifecycle_compare) || {};
    const rows = lifecycle.rows || [];
    if (!rows.length) return '<p class="detail-empty">No trade master reconcile rows are available.</p>';
    const reasonRows = (compare && compare.rows) || [];
    const reasonByKey = new Map(reasonRows.map(row => [`${row.inst}|${row.direction}|${row.entry_day}`, row]));
    const pbTotal = Number.isFinite(Number(lifecycle.paper_minus_backtest_sum)) ? Number(lifecycle.paper_minus_backtest_sum) : sumField(rows, 'paper_minus_backtest_pnl');
    const pfTotal = Number.isFinite(Number(lifecycle.paper_minus_flex_sum)) ? Number(lifecycle.paper_minus_flex_sum) : sumField(rows, 'paper_minus_flex_pnl');
    const pbRecon = reconcileStatus(pbTotal, pl.paper_minus_backtest_realized);
    const pfRecon = reconcileStatus(pfTotal, pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized);
    const unresolved = rows.filter(row => [row.paper, row.backtest, row.flex].some(side => String(side?.status || '') === 'MISSING')).length;
    const diffRows = rows.filter(row => Math.abs(Number(row.paper_minus_backtest_pnl || 0)) > 0.005 || Math.abs(Number(row.paper_minus_flex_pnl || 0)) > 0.005).length;
    const verdict = pbRecon.cls === 'bad' || pfRecon.cls === 'bad' || unresolved ? 'BREACH' : diffRows ? 'EXPLAINED' : 'PASS';
    const summary = verdict === 'PASS'
      ? 'Every displayed trade reconciles across Paper, Backtest, and Flex with matching totals.'
      : verdict === 'EXPLAINED'
        ? 'Trade-level P&L differences exist, but they reconcile to headline totals and carry row-level reasons.'
        : 'Trade master reconciliation is not clean; missing source rows or footer totals need investigation.';
    return `${renderVerdict(backendVerdict(compare, 'trade_master'), verdict, 'Trade master reconcile', summary, [`rows ${rows.length}`, `delta rows ${diffRows}`, `missing ${unresolved}`, `P-B ${pbRecon.label}`, `P-F ${pfRecon.label}`])}<div class="trade-table trade-master-table"><table><thead><tr><th>verdict / trade</th><th>paper actual</th><th>backtest</th><th>Flex</th><th>variance</th><th>reason</th></tr></thead><tbody>${rows.map(row => {
      const key = `${row.inst}|${row.direction}|${row.entry_day}`;
      const reason = reasonByKey.get(key) || {};
      const missing = [row.paper, row.backtest, row.flex].some(side => String(side?.status || '') === 'MISSING');
      const hasDelta = Math.abs(Number(row.paper_minus_backtest_pnl || 0)) > 0.005 || Math.abs(Number(row.paper_minus_flex_pnl || 0)) > 0.005;
      const rowVerdict = missing ? 'BREACH' : hasDelta ? 'EXPLAINED' : 'PASS';
      const directionClass = String(row.direction || '').toLowerCase();
      const audit = row.audit_ref ? `<a class="audit-link" href="#${esc(row.audit_ref)}" title="${esc(row.audit_label || 'open audit log')}">*</a>` : '';
      return `<tr><td><span class="fill-result ${verdictClass(rowVerdict)}">${esc(rowVerdict)}</span><b>${audit}${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.entry_day || '--')} | ${esc(row.classification || '--')}</small></td>${compactLifecycleCell(row.paper, 'paper')}${compactLifecycleCell(row.backtest, 'backtest')}${compactLifecycleCell(row.flex, 'Flex')}<td><b class="pnl-value ${moneyClass(row.paper_minus_backtest_pnl)}">P-B ${fmtMoney(row.paper_minus_backtest_pnl)}</b><small>P-F ${fmtMoney(row.paper_minus_flex_pnl)}</small></td><td><b>${esc(reason.reason_code || row.reason || '--')}</b><small>${esc(reason.reason || row.reason || '--')}</small></td></tr>`;
    }).join('')}</tbody><tfoot><tr class="total-row"><td><span class="fill-result ${verdictClass(verdict)}">TOTAL</span></td><td><b>${fmtMoney(pl.paper_epoch_closed_realized)}</b><small>paper grid</small></td><td><b>${fmtMoney(pl.backtest_epoch_closed_realized)}</b><small>backtest grid</small></td><td><b>${fmtMoney(pl.flex_epoch_rebased_realized ?? pl.statement_entry_epoch_realized)}</b><small>Flex grid</small></td><td><b class="pnl-value ${moneyClass(pbTotal)}">P-B ${fmtMoney(pbTotal)}</b><small>P-F ${fmtMoney(pfTotal)}</small></td><td><span class="fill-result ${pbRecon.cls}">${pbRecon.label}</span><small>P-F ${pfRecon.label}</small></td></tr></tfoot></table></div>`;
  }

  function compactSourceCell(side) {
    const status = String((side && side.status) || 'MISSING');
    const entry = side?.entry_price == null ? '--' : fmtPrice(side.entry_price);
    const exit = side?.exit_price == null ? (status === 'OPEN' ? 'OPEN' : '--') : fmtPrice(side.exit_price);
    return `<span class="fill-result ${status === 'MISSING' ? 'watch' : 'ok'}">${esc(status)}</span><b>${entry} -> ${exit}</b>`;
  }

  const contractPointValues = { MES: 5, MNQ: 2, MYM: 0.5, M2K: 5, MNKD: 0.5 };

  function pointValueFor(inst, ...sources) {
    for (const source of sources) {
      const pv = Number(source?.components?.cost_model?.point_value ?? source?.cost_model?.point_value);
      if (Number.isFinite(pv)) return pv;
    }
    const pv = contractPointValues[String(inst || '').toUpperCase()];
    return Number.isFinite(pv) ? pv : null;
  }

  function qtyFor(...sources) {
    for (const source of sources) {
      const qty = Number(source?.qty ?? source?.contracts);
      if (Number.isFinite(qty) && qty > 0) return qty;
    }
    return 1;
  }

  function priceUsd(price, pointValue, qty) {
    const p = Number(price);
    const pv = Number(pointValue);
    const q = Number(qty || 1);
    return Number.isFinite(p) && Number.isFinite(pv) && Number.isFinite(q) ? p * pv * q : null;
  }

  function refMoneyCell(ref, money, moneyKind = 'money') {
    const moneyCls = moneyKind === 'text' ? 'component-text' : moneyClass(money);
    const moneyText = moneyKind === 'text' ? esc(money ?? '--') : fmtMoney(money);
    const refText = ref == null || ref === '' ? '--' : esc(ref);
    return `<span class="component-ref">${refText}</span><span class="${moneyCls}">${moneyText}</span>`;
  }

  function componentAmount(value, label = null) {
    if (label != null) return `<span class="component-text">${esc(label)}</span>`;
    return `<span class="${moneyClass(value)}">${fmtMoney(value)}</span>`;
  }

  function fmtDelta(value, decimals = 2) {
    if (value == null || value === '') return '--';
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}`;
  }

  function deltaNumber(left, right) {
    const a = Number(left);
    const b = Number(right);
    return Number.isFinite(a) && Number.isFinite(b) ? a - b : null;
  }

  function modelSlippageHalf(components = {}) {
    const n = Number(components.model_slippage);
    return Number.isFinite(n) ? n / 2 : null;
  }

  function slipDisplay(value, points = null) {
    if (value == null && points == null) return '<span class="component-text">--</span>';
    const ref = points == null ? 'slip pts --' : `${fmtDelta(points)} pts`;
    return refMoneyCell(ref, value);
  }

  function priceRefCell(price, pointValue, qty, openLabel = '--') {
    if (price == null || price === '') return `<span class="component-ref">pts --</span><span class="component-text">${esc(openLabel)}</span>`;
    return `<span class="component-ref">${esc(`${fmtPrice(price)} pts`)}</span><span class="component-text">${fmtDollar(priceUsd(price, pointValue, qty))}</span>`;
  }

  function componentCompareGrid(row = {}) {
    const paper = row.paper || {};
    const backtest = row.backtest || {};
    const flex = row.flex || {};
    const paperC = paper.components || {};
    const backtestC = backtest.components || {};
    const flexC = flex.components || {};
    const paperEntryRef = paper.expected_entry ?? paperC.entry_expected_price ?? paper.entry_price;
    const paperExitRef = paper.expected_exit ?? paperC.exit_expected_price ?? paper.exit_price;
    const btEntrySlip = modelSlippageHalf(backtestC);
    const btExitSlip = modelSlippageHalf(backtestC);
    const pointValue = pointValueFor(row.inst, paper, backtest, flex, backtestC);
    const qty = qtyFor(paper, backtest, flex, row);
    const rows = [
      ['Entry Ref Value', priceRefCell(paperEntryRef, pointValue, qty), priceRefCell(backtest.entry_price, pointValue, qty), priceRefCell(flex.entry_price, pointValue, qty), 'custom'],
      ['Exit Ref Value', priceRefCell(paperExitRef, pointValue, qty, paper.status === 'OPEN' ? 'OPEN' : '--'), priceRefCell(backtest.exit_price, pointValue, qty, backtest.status === 'OPEN' ? 'OPEN' : '--'), priceRefCell(flex.exit_price, pointValue, qty, flex.status === 'OPEN' ? 'OPEN' : '--'), 'custom'],
      ['Entry Slippage', slipDisplay(paper.entry_slippage_pnl, paper.entry_slip), btEntrySlip, null, 'slip'],
      ['Exit Slippage', slipDisplay(paper.exit_slippage_pnl, paper.exit_slip), btExitSlip, null, 'slip'],
      ['Gross P&L', paperC.gross_pnl, backtestC.gross_pnl, flexC.gross_pnl],
      ['Commission / Fee', paperC.fee, backtestC.model_commission, flexC.fee],
      ['Profit/Loss', paperC.net_with_fee ?? paperC.net_pnl, backtestC.net_pnl, flexC.net_with_fee ?? flexC.net_pnl],
    ];
    return `<div class="component-compare-grid"><div class="component-head"></div><div class="component-head">Paper actual</div><div class="component-head">Backtest model</div><div class="component-head">Flex</div>${rows.map(([label, paperValue, backtestValue, flexValue, kind]) => {
      const paperCell = kind === 'custom' ? paperValue : kind === 'slip' ? paperValue : componentAmount(paperValue);
      const backtestCell = kind === 'custom' ? backtestValue : componentAmount(backtestValue);
      const flexCell = kind === 'custom' ? flexValue : kind === 'slip' ? componentAmount(null, '--') : componentAmount(flexValue);
      return `<div class="component-label">${esc(label)}</div><div>${paperCell}</div><div>${backtestCell}</div><div>${flexCell}</div>`;
    }).join('')}</div>`;
  }

  function varianceCompareGrid(row = {}) {
    const paper = row.paper || {};
    const backtest = row.backtest || {};
    const flex = row.flex || {};
    const paperC = paper.components || {};
    const backtestC = backtest.components || {};
    const flexC = flex.components || {};
    const paperEntryRef = paper.expected_entry ?? paperC.entry_expected_price ?? paper.entry_price;
    const paperExitRef = paper.expected_exit ?? paperC.exit_expected_price ?? paper.exit_price;
    const btEntrySlip = modelSlippageHalf(backtestC);
    const btExitSlip = modelSlippageHalf(backtestC);
    const pointValue = pointValueFor(row.inst, paper, backtest, flex, backtestC);
    const qty = qtyFor(paper, backtest, flex, row);
    const priceDeltaMoney = value => priceUsd(value, pointValue, qty);
    const rows = [
      ['Entry Ref Value', deltaNumber(paperEntryRef, backtest.entry_price), deltaNumber(paperEntryRef, flex.entry_price), 'price'],
      ['Exit Ref Value', deltaNumber(paperExitRef, backtest.exit_price), deltaNumber(paperExitRef, flex.exit_price), 'price'],
      ['Entry Slippage', deltaNumber(paper.entry_slippage_pnl, btEntrySlip), null, 'money'],
      ['Exit Slippage', deltaNumber(paper.exit_slippage_pnl, btExitSlip), null, 'money'],
      ['Gross P&L', deltaNumber(paperC.gross_pnl, backtestC.gross_pnl), deltaNumber(paperC.gross_pnl, flexC.gross_pnl), 'money'],
      ['Commission / Fee', deltaNumber(paperC.fee, backtestC.model_commission), deltaNumber(paperC.fee, flexC.fee), 'money'],
      ['Profit/Loss', deltaNumber(paperC.net_with_fee ?? paperC.net_pnl, backtestC.net_pnl), deltaNumber(paperC.net_with_fee ?? paperC.net_pnl, flexC.net_with_fee ?? flexC.net_pnl), 'money'],
    ];
    return `<div class="variance-compare-grid"><div class="component-head">Metric</div><div class="component-head">Paper - Backtest</div><div class="component-head">Paper - Flex</div>${rows.map(([label, pb, pf, kind]) => {
      const cell = value => kind === 'price'
        ? refMoneyCell(value == null ? '--' : `${fmtDelta(value)} pts`, priceDeltaMoney(value))
        : `<span class="${moneyClass(value)}">${fmtMoney(value)}</span>`;
      return `<div class="component-label">${esc(label)}</div><div>${cell(pb)}</div><div>${cell(pf)}</div>`;
    }).join('')}</div>`;
  }

  function costModelHint(components = {}) {
    const cm = components.cost_model || {};
    if (!Object.keys(cm).length) return '';
    return `<small>cost model: model cost = commission + entry/exit modeled slippage; comm ${fmtMoney(cm.commission_rt)} RT | slip ${esc(cm.slippage_ticks_per_side ?? '--')} ticks/side | tick ${fmtMoney(cm.tick_value)}</small>`;
  }

  function avgField(rows, getter) {
    const values = (rows || []).map(getter).map(Number).filter(Number.isFinite);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }

  function sourceDiffStatsStrip(rows, pl = {}) {
    const entrySlipAvg = avgField(rows, row => row.paper?.entry_slippage_pnl);
    const exitSlipAvg = avgField(rows, row => row.paper?.exit_slippage_pnl);
    const pbAvg = avgField(rows, row => row.paper_minus_backtest_pnl);
    const pfAvg = avgField(rows, row => row.paper_minus_flex_pnl);
    const pbTotal = sumField(rows, 'paper_minus_backtest_pnl');
    const pfTotal = sumField(rows, 'paper_minus_flex_pnl');
    const pbRecon = reconcileStatus(pbTotal, pl.paper_minus_backtest_realized);
    const pfRecon = reconcileStatus(pfTotal, pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized);
    return `<div class="source-diff-stats">${[
      metricCard('Avg entry slip', fmtMoney(entrySlipAvg), 'Average paper entry slippage P&L impact across source-diff rows.', moneyClass(entrySlipAvg), 'PAPER', 'net impact'),
      metricCard('Avg exit slip', fmtMoney(exitSlipAvg), 'Average paper exit slippage P&L impact across source-diff rows.', moneyClass(exitSlipAvg), 'PAPER', 'net impact'),
      metricCard('Avg P-B delta', fmtMoney(pbAvg), 'Average Paper minus Backtest profit/loss delta per source-diff row.', moneyClass(pbAvg), 'DELTA', 'row avg'),
      metricCard('Avg P-F delta', fmtMoney(pfAvg), 'Average Paper minus Flex profit/loss delta per source-diff row.', moneyClass(pfAvg), 'DELTA', 'row avg'),
      metricCard('Total P-B', fmtMoney(pbTotal), 'Source-diff row total reconciled against the P&L grid Paper - Backtest metric.', pbRecon.cls, pbRecon.label, `grid ${fmtMoney(pl.paper_minus_backtest_realized)}`),
      metricCard('Total P-F', fmtMoney(pfTotal), 'Source-diff row total reconciled against the P&L grid Paper - Flex metric.', pfRecon.cls, pfRecon.label, `grid ${fmtMoney(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized)}`),
    ].join('')}</div>`;
  }

  function sourceDiffAnalyzerRows(lifecycleCompare, pl = {}) {
    const rows = (lifecycleCompare && lifecycleCompare.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No source diff rows are available.</p>';
    const pbTotal = Number.isFinite(Number(lifecycleCompare.paper_minus_backtest_sum)) ? Number(lifecycleCompare.paper_minus_backtest_sum) : sumField(rows, 'paper_minus_backtest_pnl');
    const pfTotal = Number.isFinite(Number(lifecycleCompare.paper_minus_flex_sum)) ? Number(lifecycleCompare.paper_minus_flex_sum) : sumField(rows, 'paper_minus_flex_pnl');
    const pbRecon = reconcileStatus(pbTotal, pl.paper_minus_backtest_realized);
    const pfRecon = reconcileStatus(pfTotal, pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized);
    const nonZero = rows.filter(row => Math.abs(Number(row.paper_minus_backtest_pnl || 0)) > 0.005 || Math.abs(Number(row.paper_minus_flex_pnl || 0)) > 0.005).length;
    const verdict = pbRecon.cls === 'bad' || pfRecon.cls === 'bad' ? 'BREACH' : nonZero ? 'EXPLAINED' : 'PASS';
    const summary = verdict === 'PASS'
      ? 'Component totals match across sources for the displayed rows.'
      : verdict === 'EXPLAINED'
        ? 'Component-level deltas exist, but the totals reconcile to the headline P&L grid.'
        : 'Component totals do not reconcile to the headline grid; this needs audit before trusting the variance.';
    return `${tableVerdict(verdict, 'Component variance', summary, [`rows ${rows.length}`, `non-zero delta ${nonZero}`, `P-B ${pbRecon.label}`, `P-F ${pfRecon.label}`])}<div class="trade-table source-diff-table"><table><thead><tr><th>trade</th><th>side-by-side P&amp;L components</th><th>variance</th></tr></thead><tbody>${rows.map(row => {
      const paper = row.paper || {};
      const backtest = row.backtest || {};
      const flex = row.flex || {};
      const pnlPb = row.paper_minus_backtest_pnl;
      const pnlPf = row.paper_minus_flex_pnl;
      const paperC = paper.components || {};
      const backtestC = backtest.components || {};
      const flexC = flex.components || {};
      const directionClass = String(row.direction || '').toLowerCase();
      return `<tr><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.entry_day || '--')}</small><small>${esc(brokerIdentity(flex.broker_trade_id))}</small></td><td>${componentCompareGrid(row)}${costModelHint(backtestC)}</td><td>${varianceCompareGrid(row)}<b>net P-B ${fmtMoney(pnlPb)}</b><small>net P-F ${fmtMoney(pnlPf)}</small></td></tr>`;
    }).join('')}</tbody><tfoot><tr class="total-row"><td><span class="fill-result ${pbRecon.cls}">TOTAL DELTA</span><small>${esc(rows.length)} source row(s)</small></td><td><b>Reconcile vs P&amp;L grid</b><small><span class="fill-result ${pbRecon.cls}">${pbRecon.label}</span> P-B grid ${fmtMoney(pl.paper_minus_backtest_realized)}</small><small><span class="fill-result ${pfRecon.cls}">${pfRecon.label}</span> P-F grid ${fmtMoney(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized)}</small></td><td><b class="pnl-value ${moneyClass(pbTotal)}">P-B ${fmtMoney(pbTotal)}</b><small>P-F ${fmtMoney(pfTotal)}</small></td></tr></tfoot></table></div>`;
  }

  function signalPathAuditBlock(compare) {
    const audit = (compare && compare.signal_path_audit) || {};
    const statement = (compare && compare.ibkr_statement) || {};
    const evidence = audit.evidence || [];
    const status = audit.status === 'BREACH' ? 'BREACH' : evidence.length ? 'EXPLAINED' : 'PENDING';
    return `${tableVerdict(status, 'Signal path audit', evidence.length ? 'Focused evidence is attached for the audited signal/path mismatch.' : 'No focused evidence lines are attached yet.', [`evidence ${evidence.length}`, `Flex fills ${statement.fills_count ?? 0}`])}<dl class="metric-list reconcile-list">${metricLine('audit status', audit.status || '--')}${metricLine('focus', audit.focus || '--')}${metricLine('path classification', audit.classification || '--')}${metricLine('dependency', audit.dependency_note || '--')}${metricLine('Flex statement', `${statement.status || '--'} | ${statement.path || '--'} | fills ${statement.fills_count ?? 0}, closed ${statement.closed_count ?? 0}, open ${statement.open_lot_count ?? 0}`)}</dl>${evidence.length ? `<div class="trade-table audit-evidence-table"><table><thead><tr><th>source</th><th>evidence</th></tr></thead><tbody>${evidence.slice(0, 18).map(row => `<tr><td><b>${esc(row.source || '--')}</b></td><td>${esc(row.line || '--')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="detail-empty">No focused signal-path evidence lines are available.</p>'}`;
  }

  function backtestArtifactAuditBlock(compare) {
    const audit = (compare && compare.backtest_artifact_audit) || {};
    if (!Object.keys(audit).length) return '<p class="detail-empty">No backtest artifact audit is available.</p>';
    const checkpoint = audit.current_checkpoint_m2k || {};
    const pos = checkpoint.pos || {};
    const parquet = audit.parquet || {};
    const cls = audit.status === 'BREACH' ? 'bad' : 'ok';
    const status = audit.status === 'BREACH' ? 'BREACH' : audit.status === 'PASS' ? 'PASS' : 'EXPLAINED';
    return `${tableVerdict(status, 'Backtest artifact audit', audit.reason || 'Replay artifact audit result for the focused entry.', [`classification ${audit.classification || '--'}`, `replay entry ${audit.replay_snapshot_has_m2k_entry ? 'YES' : 'NO'}`])}<div id="audit-m2k-entry" class="audit-anchor"><dl class="metric-list reconcile-list">${metricLine('status', audit.status || '--')}${metricLine('focus', audit.focus || '--')}${metricLine('classification', audit.classification || '--')}${metricLine('replay has M2K entry', audit.replay_snapshot_has_m2k_entry ? 'YES' : 'NO')}${metricLine('checkpoint has M2K long', audit.current_checkpoint_has_m2k_long ? 'YES' : 'NO')}${metricLine('checkpoint entry', `${fmtPrice(pos.entry)} | ${esc(pos.entry_time || pos.entry_day || '--')}`)}${metricLine('parquet focus day', `${parquet.status || '--'} | bars ${parquet.focus_day_bars ?? '--'} | max ${parquet.max || '--'}`)}</dl><p class="detail-note ${cls}">${esc(audit.reason || '--')}</p></div>`;
  }

  function statementTradeRows(rows, empty) {
    if (!rows || !rows.length) return `<p class="detail-empty">${esc(empty)}</p>`;
    return `<div class="trade-table pnl-statement-table"><table><thead><tr><th>trade</th><th>window</th><th>prices</th><th>P&amp;L</th><th>fees</th></tr></thead><tbody>${rows.map(row => {
      const pnl = Number(row.pnl);
      const pnlClass = !Number.isFinite(pnl) || pnl === 0 ? 'neutral' : pnl > 0 ? 'ok' : 'bad';
      const signed = Number(row.signed);
      const direction = row.direction || (Number.isFinite(signed) ? (signed > 0 ? 'LONG' : signed < 0 ? 'SHORT' : '--') : '--');
      const qty = row.contracts ?? (Number.isFinite(signed) ? Math.abs(signed) : '--');
      const directionClass = String(direction || '').toLowerCase();
      return `<tr><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(direction)}</span></b><small>${esc(qty)} contract(s)</small></td><td><b>${esc(row.entry_day || row.date || '--')}</b><small>${row.exit_day ? `exit ${esc(row.exit_day)}` : 'open lot'}</small></td><td><b>${fmtPrice(row.entry_price ?? row.price)}</b><small>${row.exit_price == null ? 'open price' : `exit ${fmtPrice(row.exit_price)}`}</small></td><td><b class="pnl-value ${pnlClass}">${fmtPnl(row.pnl)}</b><small>Flex realised</small></td><td><b>${fmtMoney(row.commission)}</b><small>commission</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function paperFlexBridgeRows(rows, pl = {}) {
    if (!rows || !rows.length) return '<p class="detail-empty">No zero-base Paper vs Flex rows are available.</p>';
    const paperTotal = sumField(rows, 'paper_pnl');
    const flexTotal = sumField(rows, 'flex_pnl');
    const diffTotal = Number.isFinite(Number(pl.paper_flex_bridge_diff_sum)) ? Number(pl.paper_flex_bridge_diff_sum) : sumField(rows, 'paper_minus_flex');
    const gridDiff = pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized;
    const reconciled = reconcileStatus(diffTotal, gridDiff);
    const mismatches = rows.filter(row => row.classification !== 'MATCHED' || Math.abs(Number(row.paper_minus_flex || 0)) > 0.005).length;
    const verdict = reconciled.cls === 'bad' ? 'BREACH' : mismatches ? 'EXPLAINED' : 'PASS';
    return `${tableVerdict(verdict, 'Paper vs Flex zero-base', mismatches ? 'Paper and Flex have row-level differences, but the table indicates whether the total still reconciles to the grid.' : 'Paper closed trades match Flex comparable broker fills on the zero-base view.', [`rows ${rows.length}`, `row diff ${mismatches}`, `grid ${reconciled.label}`])}<div class="trade-table pnl-flex-bridge-table"><table><thead><tr><th>class</th><th>trade</th><th>paper detail</th><th>Flex detail</th><th>prices / fees</th><th>diff/reason</th></tr></thead><tbody>${rows.map(row => {
      const cls = row.classification === 'MATCHED' ? 'ok' : row.classification === 'PAPER_CLOSED_FLEX_OPEN' ? 'watch' : 'bad';
      const directionClass = String(row.direction || '').toLowerCase();
      const carry = row.fifo_carry_entry_day ? `FIFO carry ${esc(row.fifo_carry_entry_day)} ${fmtMoney(row.fifo_carry_pnl)}` : '';
      return `<tr><td><span class="fill-result ${cls}">${esc(row.classification || '--')}</span></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.entry_day || '--')}</small><small>${esc(brokerIdentity(row.flex_broker_trade_id))}</small></td><td><b>${esc(row.paper_exit_day || '--')} ${fmtMoney(row.paper_pnl)}</b><small>open ${fmtPrice(row.paper_entry_price)} | exit ${fmtPrice(row.paper_exit_price)}</small></td><td><b>${esc(row.flex_exit_day || (row.flex_open_lot_price == null ? '--' : 'OPEN'))}</b><small>${row.flex_pnl == null ? `open @ ${fmtPrice(row.flex_open_lot_price)}` : fmtMoney(row.flex_pnl)}</small></td><td><b>${fmtPrice(row.flex_entry_price)} -> ${fmtPrice(row.flex_exit_price)}</b><small>Flex fee ${fmtMoney(row.flex_commission)}</small></td><td><b class="pnl-value ${moneyClass(row.paper_minus_flex)}">${fmtMoney(row.paper_minus_flex)}</b><small>${esc(row.reason || '--')}${carry ? ` | ${carry}` : ''}</small></td></tr>`;
    }).join('')}</tbody><tfoot><tr class="total-row"><td><span class="fill-result ${reconciled.cls}">TOTAL</span></td><td><b>${esc(rows.length)} zero-base row(s)</b><small>paper/Flex paired rows</small></td><td><b>${fmtMoney(paperTotal)}</b><small>paper total</small></td><td><b>${fmtMoney(flexTotal)}</b><small>Flex total</small></td><td><b>${fmtMoney(pl.flex_epoch_rebased_realized ?? pl.statement_entry_epoch_realized)}</b><small>Flex grid realised</small></td><td><b class="pnl-value ${moneyClass(diffTotal)}">${fmtMoney(diffTotal)}</b><small><span class="fill-result ${reconciled.cls}">${reconciled.label}</span> vs grid Paper - Flex ${fmtMoney(gridDiff)}</small></td></tr></tfoot></table></div>`;
  }

  function flexLedgerOverrideRows(override) {
    const rows = (override && override.included_carry_closed) || [];
    if (!rows.length) return '<p class="detail-empty">No selective ledger-alignment carry row is active.</p>';
    return `<div class="trade-table pnl-flex-bridge-table"><table><thead><tr><th>scope</th><th>trade</th><th>window</th><th>prices</th><th>P&amp;L</th><th>reason</th></tr></thead><tbody>${rows.map(row => {
      const directionClass = String(row.direction || '').toLowerCase();
      return `<tr><td><span class="fill-result watch">ON PURPOSE</span><small>${esc(override.scope || 'selective')}</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>Flex carry-in</small></td><td><b>${esc(row.entry_day || '--')}</b><small>exit ${esc(row.exit_day || '--')}</small></td><td><b>${fmtPrice(row.entry_price)}</b><small>exit ${fmtPrice(row.exit_price)}</small></td><td><b class="pnl-value ${Number(row.pnl) > 0 ? 'ok' : Number(row.pnl) < 0 ? 'bad' : 'neutral'}">${fmtPnl(row.pnl)}</b><small>Flex realised</small></td><td><b>${esc(override.reason || '--')}</b><small>global rebase changed: ${override.global_rebase_changed ? 'YES' : 'NO'}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function statementPnlCompareBlock(compare) {
    const pl = (compare && compare.statement_pnl_compare) || {};
    if (!Object.keys(pl).length) return '<p class="detail-empty">No Flex P&L comparison is available.</p>';
    const pbRecon = reconcileStatus(pl.paper_minus_backtest_realized, pl.paper_minus_backtest_realized);
    const pfRecon = reconcileStatus(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized, pl.paper_flex_bridge_diff_sum ?? pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized);
    const ledgerOk = Math.abs(Number(pl.ledger_aligned_minus_system_ledger_pnl || 0)) < 0.005;
    const verdict = pfRecon.cls === 'bad' || !ledgerOk ? 'BREACH' : Math.abs(Number(pl.paper_minus_backtest_realized || 0)) > 0.005 ? 'EXPLAINED' : 'PASS';
    const summary = verdict === 'PASS'
      ? 'Headline P&L totals are aligned across paper, backtest, Flex, and realtime ledger checks.'
      : verdict === 'EXPLAINED'
        ? 'Headline totals reconcile, with Paper vs Backtest variance expected to be explained by trade-level rows.'
        : 'Headline totals do not reconcile cleanly; inspect Flex/realtime and table footers before trusting the grid.';
    return `${tableVerdict(verdict, 'Headline P&L compare', summary, [`Paper-BT ${fmtMoney(pl.paper_minus_backtest_realized)}`, `Paper-Flex ${fmtMoney(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized)}`, `Flex-realtime ${fmtMoney(pl.ledger_aligned_minus_system_ledger_pnl)}`])}<div class="detail-metric-grid pnl-pl-grid">${[
      metricCard('Paper realised', fmtMoney(pl.paper_epoch_closed_realized), 'Closed paper trades whose entry_day is on or after the paper epoch. Uses paper trade P&L as recorded; fees are not separately attributed here.', '', 'PAPER', 'epoch entries'),
      metricCard('Backtest realised', fmtMoney(pl.backtest_epoch_closed_realized), 'Closed replay trades whose entry_day is on or after the paper epoch.', '', 'BACKTEST', 'epoch entries'),
      metricCard('Paper - backtest', fmtMoney(pl.paper_minus_backtest_realized), 'Realised P&L variance between paper closed trades and replay closed trades under the same epoch-entry filter.', Number(pl.paper_minus_backtest_realized) < 0 ? 'bad' : Number(pl.paper_minus_backtest_realized) > 0 ? 'ok' : 'ok', 'VARIANCE', 'table footer'),
      metricCard('Paper realised', fmtMoney(pl.paper_epoch_closed_realized), 'Same paper realised total, repeated to line up the Flex comparison row.', '', 'PAPER', 'epoch entries'),
      metricCard('Flex zero-base', fmtMoney(pl.flex_epoch_rebased_realized ?? pl.statement_entry_epoch_realized), 'IBKR Flex fills from the paper epoch forward, paired from a zero-position base. Flex commission is the only broker fee field shown separately in this dashboard.', '', pl.status || 'OBSERVED', 'broker source'),
      metricCard('Paper - Flex zero', fmtMoney(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized), 'Realised P&L variance between paper closed trades and epoch-rebased Flex closed lots.', Number(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized) < 0 ? 'bad' : Number(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized) > 0 ? 'ok' : 'ok', 'VARIANCE', 'table footer'),
      metricCard('Realtime ledger', fmtMoney((compare && compare.pnl_reconcile || {}).realtime_system_ledger_pnl), 'Runner system ledger realised P&L. This is not IBKR NetLiquidation.', '', 'SYSTEM', 'live_state'),
      metricCard('Flex ledger-aligned', fmtMoney(pl.flex_ledger_aligned_realized), 'Flex zero-base realised plus the intentionally selected carry-in close that reconciles the runner system ledger.', '', pl.ledger_alignment_override?.status || 'OBSERVED', 'selective carry'),
      metricCard('Flex - realtime', fmtMoney(pl.ledger_aligned_minus_system_ledger_pnl), 'Ledger-aligned Flex minus runner realtime system ledger. Expected to be zero when the selective carry override is correct.', Number(pl.ledger_aligned_minus_system_ledger_pnl) === 0 ? 'ok' : 'bad', 'VARIANCE', 'ledger check'),
    ].join('')}</div><p class="detail-note">${esc(pl.note || '')} Component note: Source Diff Analyzer shows paper gross/net from trade_log, backtest native replay-exported gross/model commission/model slippage/net, and Flex reconstructed gross/native broker fee/net+fee from IBKR statement. Paper commission is exported when the broker API emits a commission report for the fill; older trade_log rows can remain missing and Flex remains the historical broker-fee source of truth. Ignored carry-close fills inside epoch: ${esc(pl.flex_epoch_rebased_ignored_count ?? 0)}. Excluded pre-epoch closed lots: ${esc(pl.excluded_pre_epoch_closed_count ?? 0)} (${fmtMoney(pl.excluded_pre_epoch_exit_window_realized)}). Raw IBKR FIFO entry-epoch realised: ${fmtMoney(pl.raw_statement_entry_epoch_realized)}.</p><h4 class="detail-subhead">Zero-base Paper vs Flex closed trades</h4>${paperFlexBridgeRows(pl.paper_flex_bridge, pl)}<h4 class="detail-subhead">Flex epoch-rebased open lots</h4>${statementTradeRows(pl.flex_epoch_rebased_open_lots || pl.statement_entry_epoch_open_lots, 'No epoch-rebased Flex open lots are retained.')}`;
  }

  function pnlBaseMetricCards(m) {
    const base = m.base_audit || {};
    const baseOk = base.base_accounts_match !== false && base.backtest_reset_to_account !== false;
    const firstActual = `${fmtEquity(base.first_actual_equity)}${base.first_actual_vs_base == null ? '' : ` (${fmtMoney(base.first_actual_vs_base)} vs base)`}`;
    return `<div class="detail-metric-grid">${[
      metricCard('Paper base', fmtEquity(base.paper_account_base), 'The account base used for the paper comparison window.', base.base_accounts_match === false ? 'bad' : 'ok', base.base_accounts_match === false ? 'BREACH' : 'PASS', `epoch ${base.epoch || '--'}`),
      metricCard('First system ledger', firstActual, base.actual_equity_note || 'First runner system ledger equity observed in the comparison window; this is not IBKR NetLiquidation.', '', 'OBSERVED', base.first_actual_date || '--'),
      metricCard('Backtest reset', base.backtest_reset_to_account ? 'YES' : base.backtest_reset_to_account === false ? 'NO' : '--', 'Whether expected backtest equity is reset to the paper account base at the comparison epoch.', baseOk ? 'ok' : 'bad', baseOk ? 'PASS' : 'BREACH', 'must match'),
      metricCard('Curve rows', `${m.covered_daily_count ?? 0} covered / ${m.stale_daily_count ?? 0} stale`, m.curve_status_rule || 'Curve status is freshness, not standalone P&L pass/fail.', m.stale_daily_count ? 'watch' : 'ok', m.stale_daily_count ? 'PENDING' : 'PASS', 'freshness'),
    ].join('')}</div>`;
  }

  function flexPnlByDate(pl = {}) {
    const closed = pl.flex_epoch_rebased_closed || [];
    const bridge = pl.paper_flex_bridge || [];
    const byDay = new Map();
    const sourceRows = closed.length ? closed : bridge;
    sourceRows.forEach(row => {
      const day = row.exit_day || row.date;
      if (!day) return;
      const components = row.components || row.flex_components || {};
      const value = Number(components.net_pnl ?? row.pnl ?? row.flex_pnl);
      if (Number.isFinite(value)) byDay.set(day, (byDay.get(day) || 0) + value);
    });
    return byDay;
  }

  function pnlTimeline(timeline, pl = {}, compare = null) {
    const rows = (timeline || []).filter(row => row && row.date);
    if (!rows.length) return '<p class="detail-empty">No daily P&L timeline is available.</p>';
    const flexDaily = flexPnlByDate(pl);
    let flexCum = 0;
    const series = [
      {
        key: 'paper',
        label: 'Paper actual',
        cls: 'paper',
        values: rows.map(row => Number(row.paper_trade_realized_cum)),
      },
      {
        key: 'backtest',
        label: 'Backtest',
        cls: 'backtest',
        values: rows.map(row => Number(row.backtest_trade_realized_cum)),
      },
      {
        key: 'flex',
        label: 'Flex',
        cls: 'flex',
        values: rows.map(row => {
          flexCum += Number(flexDaily.get(row.date) || 0);
          return flexCum;
        }),
      },
    ];
    const values = series.flatMap(item => item.values).filter(Number.isFinite);
    const maxAbs = Math.max(1, ...values.map(value => Math.abs(value)));
    const width = 880;
    const height = 260;
    const pad = { left: 70, right: 24, top: 24, bottom: 38 };
    const parseDay = value => {
      const date = new Date(`${value}T00:00:00Z`);
      return Number.isFinite(date.getTime()) ? date.getTime() : null;
    };
    const firstMs = parseDay(rows[0].date) ?? 0;
    const lastMs = parseDay(rows[rows.length - 1].date) ?? firstMs;
    const minSpanMs = 9 * 24 * 60 * 60 * 1000;
    const x0 = firstMs;
    const x1 = Math.max(lastMs, firstMs + minSpanMs);
    const x = row => {
      const ms = parseDay(row.date) ?? firstMs;
      const pct = x1 === x0 ? 0 : (ms - x0) / (x1 - x0);
      return Math.round(pad.left + pct * (width - pad.left - pad.right));
    };
    const yMax = Math.ceil(maxAbs / 25) * 25;
    const yMin = -yMax;
    const y = value => {
      const pct = (Number(value || 0) - yMin) / (yMax - yMin || 1);
      return Math.round(height - pad.bottom - pct * (height - pad.top - pad.bottom));
    };
    const yTicks = [yMax, yMax / 2, 0, -yMax / 2, -yMax];
    const grid = yTicks.map(value => `<g class="timeline-grid"><line x1="${pad.left}" y1="${y(value)}" x2="${width - pad.right}" y2="${y(value)}"></line><text x="${pad.left - 10}" y="${y(value) + 4}" text-anchor="end">${esc(fmtMoney(value))}</text></g>`).join('');
    const lines = series.map(item => {
      const points = item.values.map((value, i) => `${x(rows[i])},${y(value)}`).join(' ');
      return `<polyline class="${item.cls}" points="${points}"></polyline>`;
    }).join('');
    const dots = series.map(item => item.values.map((value, i) => {
      const row = rows[i] || {};
      return `<g class="timeline-dot ${item.cls}"><circle cx="${x(row)}" cy="${y(value)}" r="2.4"></circle><title>${esc(row.date)} | ${esc(item.label)} | ${fmtMoney(value)} | ${esc(row.curve_status || '--')}</title></g>`;
    }).join('')).join('');
    const dateLabels = rows.map(row => `<text x="${x(row)}" y="${height - 12}" text-anchor="middle">${esc(String(row.date || '').slice(5))}</text>`).join('');
    const latestCards = series.map(item => {
      const value = item.values[item.values.length - 1];
      return `<span class="${item.cls}"><b>${esc(item.label)}</b>${fmtMoney(value)}</span>`;
    }).join('');
    const latestPaper = series[0].values[series[0].values.length - 1];
    const latestBacktest = series[1].values[series[1].values.length - 1];
    const latestFlex = series[2].values[series[2].values.length - 1];
    const paperRecon = reconcileStatus(latestPaper, pl.paper_epoch_closed_realized);
    const backtestRecon = reconcileStatus(latestBacktest, pl.backtest_epoch_closed_realized);
    const flexRecon = reconcileStatus(latestFlex, pl.flex_epoch_rebased_realized ?? pl.statement_entry_epoch_realized);
    const verdict = [paperRecon, backtestRecon, flexRecon].some(item => item.cls === 'bad') ? 'BREACH' : 'PASS';
    const summary = verdict === 'PASS'
      ? 'Timeline final values reconcile to the headline P&L grid, so the chart can be used as a visual divergence map.'
      : 'Timeline final values do not reconcile to the headline P&L grid; use table totals until the chart data source is fixed.';
    return `<div class="pnl-timeline">${renderVerdict(backendVerdict(compare, 'timeline'), verdict, 'Timeline reconcile', summary, [`paper ${paperRecon.label}`, `backtest ${backtestRecon.label}`, `Flex ${flexRecon.label}`])}<div class="timeline-readout">${latestCards}</div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Paper, backtest, and Flex net P&L timeline">${grid}<line class="zero" x1="${pad.left}" y1="${y(0)}" x2="${width - pad.right}" y2="${y(0)}"></line>${lines}${dots}<g class="timeline-labels">${dateLabels}</g></svg><div class="timeline-legend"><span class="paper">Paper actual</span><span class="backtest">Backtest</span><span class="flex">Flex</span><span class="neutral">X axis shown on a minimum 10-session span</span></div></div>`;
  }

  function pnlDailyRows(timeline, compare = null) {
    const rows = timeline || [];
    if (!rows.length) return '<p class="detail-empty">No daily rows are available.</p>';
    const stale = rows.filter(row => row.curve_status && row.curve_status !== 'covered').length;
    const latest = rows[rows.length - 1] || {};
    const tradeDiff = Number(latest.trade_filter_realized_diff);
    const verdict = stale ? 'PENDING' : Number.isFinite(tradeDiff) && Math.abs(tradeDiff) > 0.005 ? 'EXPLAINED' : 'PASS';
    const summary = stale
      ? 'Some daily rows are stale, so the curve is not a complete freshness pass yet.'
      : Math.abs(Number(tradeDiff || 0)) > 0.005
        ? 'Daily paper/backtest divergence exists and should be explained by trade-level lifecycle rows.'
        : 'Daily paper/backtest trade ledger is aligned through the latest covered row.';
    return `${renderVerdict(backendVerdict(compare, 'daily'), verdict, 'Daily divergence', summary, [`rows ${rows.length}`, `stale ${stale}`, `latest trade diff ${fmtMoney(latest.trade_filter_realized_diff)}`])}<div class="trade-table pnl-daily-table"><table><thead><tr><th>date</th><th>system ledger</th><th>paper trade ledger</th><th>backtest reset</th><th>ledger offset</th><th>trade diff</th><th>side/status</th></tr></thead><tbody>${rows.map(row => {
      const side = row.divergence_side || '--';
      const cls = side === 'FAVORABLE' ? 'ok' : side === 'ADVERSE' ? 'bad' : row.curve_status === 'covered' ? 'ok' : 'watch';
      return `<tr><td><b>${esc(row.date || '--')}</b><small>${esc(row.curve_status || '--')}</small></td><td><b>${fmtEquity(row.actual_equity)}</b><small>${esc(row.actual_equity_source || 'system ledger')}</small></td><td><b>${fmtEquity(row.paper_trade_filter_equity)}</b><small>paper closed trade P&amp;L ${fmtMoney(row.paper_trade_realized_cum)}</small></td><td><b>${fmtEquity(row.expected_equity)}</b><small>backtest closed trade P&amp;L ${fmtMoney(row.backtest_trade_realized_cum)}</small></td><td><b>${fmtMoney(row.system_ledger_vs_trade_filter)}</b><small>ledger - paper trade ledger</small></td><td><b>${fmtMoney(row.trade_filter_realized_diff)}</b><small>paper trades - backtest trades</small></td><td><span class="fill-result ${cls}">${esc(side)}</span><small>${esc(row.curve_status || '--')}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function pnlReconcileBlock(compare) {
    const reconcile = (compare && compare.pnl_reconcile) || {};
    const broker = reconcile.broker_equity_context || {};
    return `<dl class="metric-list reconcile-list">${metricLine('actual source', reconcile.actual_source || '--')}${metricLine('actual semantics', reconcile.actual_semantics || '--')}${metricLine('broker equity context', `${fmtEquity(broker.value)} | ${broker.source || '--'}`)}${metricLine('IBKR ledger bridge', reconcile.not_ibkr_equity ? 'NOT WIRED | do not infer interest / MTM / cash buckets' : 'WIRED')}</dl><p class="detail-note">${esc(reconcile.bridge_note || 'Ledger bridge compares system ledger against paper closed-trade P&L; it is not broker cash/interest/MTM attribution.')}</p>`;
  }

  function realtimeLedgerBlock(compare) {
    const reconcile = (compare && compare.pnl_reconcile) || {};
    const pl = (compare && compare.statement_pnl_compare) || {};
    const trace = reconcile.system_ledger_offset_trace || {};
    const ledgerOk = Math.abs(Number(pl.ledger_aligned_minus_system_ledger_pnl || 0)) < 0.005;
    return `${tableVerdict(ledgerOk ? 'PASS' : 'BREACH', 'Realtime ledger source', ledgerOk ? 'Ledger-aligned Flex reconciles to the runner realtime system ledger.' : 'Ledger-aligned Flex does not reconcile to realtime system ledger.', [`source ${reconcile.actual_source || '--'}`, `delta ${fmtMoney(pl.ledger_aligned_minus_system_ledger_pnl)}`])}<dl class="metric-list reconcile-list">${metricLine('Realtime system ledger P&L', fmtMoney(reconcile.realtime_system_ledger_pnl))}${metricLine('formula', reconcile.realtime_system_ledger_formula || 'live_state.meta.final_equity - paper_history.account')}${metricLine('final equity / base', `${fmtEquity(reconcile.realtime_final_equity)} / ${fmtEquity(reconcile.realtime_account_base)}`)}${metricLine('paper closed-trade P&L', fmtMoney(reconcile.paper_closed_trade_realized))}${metricLine('ledger offset vs closed trades', fmtMoney(reconcile.system_ledger_offset_vs_paper_closed_trades))}${metricLine('Flex comparable source', trace.comparable_source_of_truth || '--')}${metricLine('Flex comparable realised', fmtMoney(trace.comparable_flex_realized))}${metricLine('Flex vs realtime delta', fmtMoney(pl.ledger_aligned_minus_system_ledger_pnl))}</dl><p class="detail-note">${esc(trace.conclusion || 'The realtime system ledger is reconciled separately from zero-base strategy P&L.')} The selective carry-in is intentional and does not move the global strategy rebase date.</p><h4 class="detail-subhead">Ledger alignment override</h4>${flexLedgerOverrideRows(pl.ledger_alignment_override)}`;
  }

  function pnlPurposeBlock(m) {
    return `<p class="detail-copy">${esc(m.description || 'This panel compares paper/backtest/Flex realised P&L from the paper epoch using the same zero-position base where possible. The purpose is to separate strategy divergence from execution/accounting differences: signal and entry parity explain whether the same trade should exist, lifecycle rows compare open and exit state across sources, and table totals reconcile back to the P&L grid. Realtime ledger P&L is shown only as a system-ledger check, not as IBKR NetLiquidation.')}</p><p class="detail-copy">Signal compare checks desired decision parity; entry compare checks admitted/filled order parity; lifecycle compare checks open and exit parity across paper/backtest/Flex.</p><p class="detail-copy">Comparable base: paper and backtest use epoch-entry closed trades; Flex zero-base rebuilds broker fills from retained paper entries; Flex ledger-aligned intentionally includes the selected carry-in close only for realtime ledger reconciliation.</p>`;
  }

  function overviewVerdictCard(label, status, value, note) {
    return `<article class="overview-verdict-card ${verdictClass(status)}"><span class="fill-result ${verdictClass(status)}">${esc(status)}</span><b>${esc(label)}</b><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`;
  }

  function overviewVerdictStrip(compare, m = {}) {
    const pl = (compare && compare.statement_pnl_compare) || {};
    const base = m.base_audit || {};
    const lifecycle = (compare && compare.lifecycle_compare) || {};
    const parity = (compare && compare.open_position_parity) || {};
    const baseOk = base.base_accounts_match !== false && base.backtest_reset_to_account !== false;
    const pfRecon = reconcileStatus(lifecycle.paper_minus_flex_sum, pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized);
    const pbRecon = reconcileStatus(lifecycle.paper_minus_backtest_sum, pl.paper_minus_backtest_realized);
    const openDiff = ((parity.paper_only || []).length + (parity.backtest_only || []).length);
    const unresolved = Number(compare?.unresolved ?? 0) + openDiff + (pfRecon.cls === 'bad' ? 1 : 0) + (pbRecon.cls === 'bad' ? 1 : 0);
    const paperBacktestDelta = Number(pl.paper_minus_backtest_realized || 0);
    const backendOverview = backendVerdict(compare, 'overview');
    return `${renderVerdict(backendOverview, unresolved ? 'BREACH' : Math.abs(paperBacktestDelta) > 0.005 ? 'EXPLAINED' : 'PASS', 'Overview verdicts', unresolved ? 'At least one headline check requires drilldown before pass.' : 'Headline checks have a table-level explanation.', [`unresolved ${unresolved}`])}<div class="overview-verdict-grid">${[
      overviewVerdictCard(baseOk ? 'Base aligned' : 'Base mismatch', baseOk ? 'PASS' : 'BREACH', base.paper_account_base == null ? '--' : fmtEquity(base.paper_account_base), baseOk ? 'Paper/backtest comparison starts from the intended account base.' : 'Paper account base or backtest reset does not match the epoch spec.'),
      overviewVerdictCard(pfRecon.cls === 'bad' ? 'Paper-Flex check' : 'Paper-Flex clean', pfRecon.cls === 'bad' ? 'BREACH' : 'PASS', fmtMoney(pl.paper_minus_flex_epoch_rebased_realized ?? pl.paper_minus_statement_entry_epoch_realized), `zero-base footer ${pfRecon.label}`),
      overviewVerdictCard(pbRecon.cls === 'bad' ? 'Paper-BT check' : Math.abs(paperBacktestDelta) > 0.005 ? 'Paper-BT explained' : 'Paper-BT clean', pbRecon.cls === 'bad' ? 'BREACH' : Math.abs(paperBacktestDelta) > 0.005 ? 'EXPLAINED' : 'PASS', fmtMoney(pl.paper_minus_backtest_realized), `trade footer ${pbRecon.label}`),
      overviewVerdictCard(openDiff ? 'Open book diff' : 'Open book parity', openDiff ? 'BREACH' : 'PASS', `${parity.paper_open_count ?? 0} / ${parity.replay_open_count ?? 0}`, openDiff ? `${openDiff} unmatched open position row(s)` : 'Paper and replay open counts are aligned.'),
      overviewVerdictCard(unresolved ? 'Unresolved items' : 'No unresolved', unresolved ? 'BREACH' : 'PASS', unresolved, unresolved ? 'At least one table requires drilldown before pass.' : 'All headline checks have a table-level explanation.'),
    ].join('')}</div>`;
  }

  function openPositionParityRows(parity) {
    if (!parity) return '<p class="detail-empty">No open-position parity data is available.</p>';
    const rows = [
      ...((parity.paper_only || []).map(row => ({ ...row, side: 'paper only' }))),
      ...((parity.backtest_only || []).map(row => ({ ...row, side: 'backtest only' }))),
    ];
    const verdict = rows.length ? 'BREACH' : 'PASS';
    const body = rows.length ? rows.map(row => {
      const cls = row.side === 'paper only' ? 'watch' : 'bad';
      const directionClass = String(row.direction || '').toLowerCase();
      return `<tr><td><span class="fill-result ${cls}">${esc(row.side)}</span></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.cluster || '--')} entry ${esc(row.entry_day || '--')}</small></td><td><b>${esc(row.contracts ?? '--')}</b><small>contracts</small></td><td><b>${fmtMoney(row.risk_sized)}</b><small>risk</small></td><td><b>${fmtPrice(row.entry_price)}</b><small>${esc(row.stop_order_id ? `stop ${row.stop_order_id}` : '--')}</small></td></tr>`;
    }).join('') : `<tr><td><span class="fill-result ok">MATCH</span></td><td><b>no parity diff</b><small>${esc(parity.note || '--')}</small></td><td>--</td><td>--</td><td>--</td></tr>`;
    return `${tableVerdict(verdict, 'Open-position parity', rows.length ? 'Paper and backtest open books differ at the comparison boundary.' : 'Paper and backtest open books match at the comparison boundary.', [`paper ${parity.paper_open_count ?? 0}`, `backtest ${parity.replay_open_count ?? 0}`, `diff ${rows.length}`])}<dl class="metric-list">${metricLine('status', parity.status || '--')}${metricLine('paper day', parity.paper_day || '--')}${metricLine('replay day', parity.replay_day || '--')}${metricLine('backtest source', parity.backtest_position_source || '--')}${metricLine('open counts', `${parity.paper_open_count ?? 0} paper / ${parity.replay_open_count ?? 0} backtest`)}</dl><div class="trade-table open-position-table"><table><thead><tr><th>side</th><th>position</th><th>qty</th><th>risk</th><th>price/stop</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function pnlCompareTab(compare, m, counts, signalCompare, signalCounts, entryCompare, entryCounts, latest) {
    return `<div class="pnl-tab-panel overview-panel"><section class="more-section trade-detail overview-verdict-section"><h3>Overview Verdicts</h3>${overviewVerdictStrip(compare, m)}</section><section class="more-section trade-detail"><h3>What This Measures</h3>${pnlPurposeBlock(m)}</section><section class="more-section trade-detail"><h3>Realtime P&amp;L Source</h3>${realtimeLedgerBlock(compare)}</section><section class="more-section trade-detail"><h3>P&amp;L Compare</h3>${statementPnlCompareBlock(compare)}</section><p class="detail-note">${esc(m.curve_status_rule || 'Curve status controls daily-row freshness, not standalone P&L pass/fail.')} Known exit timing drift is expected when the paper/live path defers a stop/exit after the 14h/EOD decision.</p></div>`;
  }

  function pnlSourceDiffTab(compare) {
    const pl = compare.statement_pnl_compare || {};
    return `<div class="pnl-tab-panel components-panel"><section class="more-section trade-detail"><h3>Source Diff Analyzer</h3>${sourceDiffStatsStrip(compare.lifecycle_compare?.rows || [], pl)}${sourceDiffAnalyzerRows(compare.lifecycle_compare, pl)}</section></div>`;
  }

  function pnlTimelineTab(compare, m) {
    return `<div class="pnl-tab-panel timeline-panel"><section class="more-section trade-detail"><h3>Net P&amp;L Timeline</h3>${pnlTimeline(m.daily || m.timeline, compare.statement_pnl_compare, compare)}</section><section class="more-section trade-detail"><h3>Daily Divergence Rows</h3>${pnlDailyRows(m.daily || m.timeline, compare)}</section></div>`;
  }

  function pnlDecisionPathTab(compare, signalCompare, entryCompare) {
    return `<div class="pnl-tab-panel decision-panel"><section class="more-section trade-detail"><h3>Signal Compare (${esc(signalCompare.shown ?? 0)} / ${esc(signalCompare.total ?? 0)})</h3>${signalCompareRows(signalCompare)}</section><section class="more-section trade-detail"><h3>Entry Compare (${esc(entryCompare.shown ?? 0)} / ${esc(entryCompare.total ?? 0)})</h3>${entryCompareRows(entryCompare)}</section><section class="more-section trade-detail"><h3>Open Position Parity</h3>${openPositionParityRows(compare.open_position_parity)}</section></div>`;
  }

  function pnlTradeReconcileTab(compare, m) {
    return `<div class="pnl-tab-panel trades-panel"><section class="more-section trade-detail"><h3>Trade Master Reconcile</h3>${tradeMasterReconcileRows(compare, compare.statement_pnl_compare)}</section><section class="more-section trade-detail"><details class="secondary-table"><summary>Lifecycle Compare (${esc(compare.lifecycle_compare?.shown ?? 0)} / ${esc(compare.lifecycle_compare?.total ?? 0)})</summary>${lifecycleCompareRows(compare.lifecycle_compare, compare.statement_pnl_compare)}</details></section><section class="more-section trade-detail"><details class="secondary-table"><summary>Trade-by-trade Reasons (${esc(compare.shown ?? 0)} / ${esc(compare.total ?? 0)})</summary>${pnlCompareRows(compare)}</details></section></div>`;
  }

  function pnlRulesTab(m) {
    return `<div class="pnl-tab-panel rules-panel"><section class="more-section trade-detail"><h3>Status Rules</h3>${listItems(m.status_rules || [])}</section></div>`;
  }

  function pnlAuditTab(compare) {
    return `<div class="pnl-tab-panel audit-panel"><section class="more-section trade-detail"><h3>Backtest Artifact Audit</h3>${backtestArtifactAuditBlock(compare)}</section><section class="more-section trade-detail"><h3>Signal Path Audit</h3>${signalPathAuditBlock(compare)}</section></div>`;
  }

  function pnlCompareDetail(item) {
    const compare = item.metrics && item.metrics.trade_compare;
    const m = item.metrics || {};
    if (!compare) return `<section class="more-section trade-detail"><h3>What This Measures</h3><p class="detail-copy">${esc(m.description || 'Paper vs backtest validates aligned equity comparison.')}</p></section>`;
    const signalCompare = compare.signal_compare || {};
    const entryCompare = compare.entry_compare || {};
    return `<div class="pnl-tabs"><input type="radio" id="pnl-tab-overview" name="pnl-tab" checked><input type="radio" id="pnl-tab-trades" name="pnl-tab"><input type="radio" id="pnl-tab-components" name="pnl-tab"><input type="radio" id="pnl-tab-decision" name="pnl-tab"><input type="radio" id="pnl-tab-timeline" name="pnl-tab"><input type="radio" id="pnl-tab-rules" name="pnl-tab"><input type="radio" id="pnl-tab-audit" name="pnl-tab"><div class="pnl-tab-buttons"><label for="pnl-tab-overview">Overview</label><label for="pnl-tab-trades">Trades</label><label for="pnl-tab-components">Components</label><label for="pnl-tab-decision">Decision</label><label for="pnl-tab-timeline">Timeline</label><label for="pnl-tab-rules">Rules</label><label for="pnl-tab-audit">Audit</label></div>${pnlCompareTab(compare, m, {}, signalCompare, {}, entryCompare, {}, {})}${pnlTradeReconcileTab(compare, m)}${pnlSourceDiffTab(compare)}${pnlDecisionPathTab(compare, signalCompare, entryCompare)}${pnlTimelineTab(compare, m)}${pnlRulesTab(m)}${pnlAuditTab(compare)}</div>`;
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
    const required = m.required_continuous_sessions ?? '--';
    const streak = m.continuous_session_streak ?? 0;
    const streakOk = Number(streak) >= Number(m.required_continuous_sessions ?? Infinity);
    const failureSessions = ((m.session_streak && m.session_streak.sessions) || []).filter(row => row.status === 'FAIL').length;
    const hasDeferRule = !!(m.spec && m.spec.require_defer_rule);
    return `<div class="detail-metric-grid">${[
      metricCard('Clean sessions', `${streak} / ${required}`, 'Consecutive sessions where every deferred trade either closed before arm or had IBKR + system accepted STP after arm. Any failed session resets this streak.', streakOk ? 'ok' : 'watch', streakOk ? 'PASS' : 'PENDING', `need ${required}`, detailProgress(streak, m.required_continuous_sessions)),
      metricCard('Route failures', failureSessions, 'Sessions with a deferred trade still open after arm without IBKR + system accepted STP, with accepted-before-arm evidence, or with trade-matched placement failure.', failureSessions ? 'bad' : 'ok', failureSessions ? 'BREACH' : 'PASS', 'must be 0'),
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
    if (value === 'ACCEPTED_AFTER_ARM') return 'ACCEPTED';
    if (value === 'ACCEPTED_AFTER_DEFER') return 'ACCEPTED';
    if (value === 'ACCEPTED_BEFORE_ARM') return 'EARLY';
    if (value === 'ACCEPTED_MISSING_SYSTEM_LOG') return 'NO SYSTEM';
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
      const cls = row.outcome === 'ACCEPTED_AFTER_ARM' ? 'ok' : row.outcome === 'CLOSED_BEFORE_ARM' ? 'watch' : 'bad';
      const directionClass = String(row.direction || '').toLowerCase();
      const timing = row.outcome === 'CLOSED_BEFORE_ARM'
        ? `<b>${esc(shortTs(row.close_at))}</b><small>${esc(fmtHours(row.hours_before_arm))} | arm ${esc(shortTs(row.arm_at))}</small>`
        : row.accepted_at
          ? `<b>${esc(shortTs(row.accepted_at))}</b><small>arm ${esc(shortTs(row.arm_at))} | ${esc(row.system_evidence || 'system log missing')}</small>`
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

  function rejectionMetricCards(m) {
    const required = m.required_records ?? '--';
    const completeOk = !(m.missing_identity || m.missing_reason);
    const classifiedOk = Number(m.unclassified || 0) <= Number(m.max_unclassified ?? 0);
    const sampleOk = Number(m.rejections || 0) >= Number(m.required_records ?? Infinity);
    const capOk = (m.cap_blocks ?? 0) > 0 || !m.require_cap_classification;
    return `<div class="detail-metric-grid">${[
      metricCard('Rejected rows', `${m.rejections ?? 0} / ${required}`, m.metric_descriptions?.rejections || 'Rejected candidate log lines in the active paper epoch.', sampleOk ? 'ok' : 'watch', sampleOk ? 'PASS' : 'PENDING', `need ${required}`, detailProgress(m.rejections, m.required_records)),
      metricCard('Parsed rows', `${m.parsed ?? 0} / ${m.rejections ?? 0}`, m.metric_descriptions?.parsed || 'Rows parsed into candidate identity, risk size, and reason.', (m.parsed ?? 0) === (m.rejections ?? 0) ? 'ok' : 'watch', (m.parsed ?? 0) === (m.rejections ?? 0) ? 'PASS' : 'CHECK', 'structured', detailProgress(m.parsed, m.rejections)),
      metricCard('Cap blocks', m.cap_blocks ?? 0, m.metric_descriptions?.cap_blocks || 'Rows classified as gross/net/risk cap blocks.', capOk ? 'ok' : 'bad', capOk ? 'PASS' : 'BREACH', 'required'),
      metricCard('Completeness', (m.missing_identity || m.missing_reason) ? `${m.missing_identity ?? 0} / ${m.missing_reason ?? 0}` : 0, 'Missing identity / missing reason rows. Both must be zero when required.', completeOk ? 'ok' : 'bad', completeOk ? 'PASS' : 'BREACH', 'identity/reason'),
      metricCard('Unclassified', m.unclassified ?? 0, m.metric_descriptions?.unclassified || 'Rows whose reason could not be mapped to a guard class.', classifiedOk ? 'ok' : 'bad', classifiedOk ? 'PASS' : 'BREACH', `max ${m.max_unclassified ?? '--'}`),
      metricCard('Clusters', Object.keys(m.by_cluster || {}).length, 'Number of clusters represented by rejected candidate evidence.', '', 'OBSERVED', 'context'),
    ].join('')}</div>`;
  }

  function rejectionEvidenceRows(samples) {
    const rows = (samples && samples.rows) || [];
    if (!rows.length) return '<p class="detail-empty">No rejected-signal evidence rows are available.</p>';
    const existingTip = 'risk before trade enter';
    const signalTip = 'risk contribution of the rejected signal if sent as a new order';
    const projectedTip = 'risk after adding the rejected signal to existing open-book risk';
    const varianceTip = 'projected risk minus cap risk; positive means the signal is over cap';
    return `<div class="trade-table rejection-table"><table><thead><tr><th>class</th><th>candidate</th><th><span class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(existingTip)}">existing risk</span></th><th><span class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(signalTip)}">signal risk</span></th><th><span class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(projectedTip)}">projected risk</span></th><th><span class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(varianceTip)}">over cap variance</span></th><th>reason</th><th>evidence</th></tr></thead><tbody>${rows.map(row => {
      const klass = String(row.class || 'unclassified');
      const cls = klass === 'unclassified' ? 'bad' : klass.startsWith('cap') ? 'watch' : 'ok';
      const directionClass = String(row.direction || '').toLowerCase();
      const evidence = `${row.path || '--'}${row.line_no ? `:${row.line_no}` : ''}`;
      const existing = `${fmtMoney(row.existing_risk_sized)}${row.existing_pct == null ? '' : ` (${Number(row.existing_pct).toFixed(2)}%)`}`;
      const candidate = `${fmtMoney(row.candidate_risk_sized ?? row.risk_sized)}`;
      const projected = `${fmtMoney(row.projected_risk_sized)}${row.projected_pct == null ? '' : ` (${Number(row.projected_pct).toFixed(1)}%)`}`;
      const cap = `${fmtMoney(row.cap_risk_sized)}${row.cap_pct == null ? '' : ` (${Number(row.cap_pct).toFixed(1)}%)`}`;
      const varianceClass = Number(row.over_cap_risk_sized || 0) > 0 ? 'bad' : 'ok';
      const variance = `${fmtMoney(row.over_cap_risk_sized)}${row.over_cap_pct == null ? '' : ` (${Number(row.over_cap_pct).toFixed(1)}%)`}`;
      return `<tr><td><span class="fill-result ${cls}">${esc(klass)}</span><small>${row.parsed ? 'parsed' : 'raw only'}</small></td><td><b>${esc(row.inst || '--')} <span class="direction-chip ${directionClass}">${esc(row.direction || '--')}</span></b><small>${esc(row.cluster || '--')}</small></td><td><b>${esc(existing)}</b><small>before signal</small></td><td><b>${esc(candidate)}</b><small>new signal</small></td><td><b>${esc(projected)}</b><small>cap ${esc(cap)}</small></td><td><b class="pnl-value ${varianceClass}">${esc(variance)}</b><small>projected - cap</small></td><td><b>${esc(row.reason || '--')}</b><small class="has-tip tip-bottom" tabindex="0" data-tooltip="${esc(row.raw || '')}">raw log available</small></td><td><b>${esc(evidence)}</b><small>${esc(row.ts || '--')}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function rejectionCoverageDetail(item) {
    const m = item.metrics || {};
    return `<section class="more-section trade-detail"><h3>What This Measures</h3><p class="detail-copy">${esc(m.description || 'Rejected signal coverage validates retained guard decision evidence.')}</p></section><section class="more-section trade-detail"><h3>Metrics</h3>${rejectionMetricCards(m)}</section><section class="more-section trade-detail"><h3>Rejected Candidate Evidence (${esc(m.samples?.shown ?? 0)} / ${esc(m.samples?.total ?? 0)})</h3>${rejectionEvidenceRows(m.samples)}</section><section class="more-section trade-detail"><h3>Status Rules</h3>${listItems(m.status_rules || [])}</section>`;
  }

  function contractSpecRows(rows) {
    if (!rows || !rows.length) return '<p class="detail-empty">No local basket contract specs are available.</p>';
    return `<div class="trade-table contract-spec-table"><table><thead><tr><th>inst</th><th>local spec</th><th>IBKR spec</th><th>contract</th><th>status</th></tr></thead><tbody>${rows.map(row => {
      const local = row.local || {};
      const ibkr = row.ibkr || {};
      const contract = row.contract || {};
      const cls = row.status === 'PASS' ? 'ok' : row.status === 'BREACH' ? 'bad' : 'watch';
      const checks = row.checks || {};
      const checkText = ['point_value', 'tick', 'tick_value'].map(key => `${key}:${checks[key] ? 'OK' : 'CHECK'}`).join(' | ');
      return `<tr><td><b>${esc(row.inst || '--')}</b><small>basket symbol</small></td><td><b>point ${fmtPrice(local.point_value)}</b><small>tick ${fmtPrice(local.tick)} | tick value ${fmtMoney(local.tick_value)}</small></td><td><b>point ${fmtPrice(ibkr.point_value)}</b><small>tick ${fmtPrice(ibkr.tick)} | tick value ${fmtMoney(ibkr.tick_value)}</small></td><td><b>${esc(contract.local_symbol || contract.symbol || '--')}</b><small>${esc(contract.exchange || '--')} ${esc(contract.contract_month || '--')} conId ${esc(contract.con_id || '--')}</small></td><td><span class="fill-result ${cls}">${esc(row.status || '--')}</span><small>${esc(ibkr.error || checkText)}</small></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function contractSpecGuardDetail(item) {
    const m = item.metrics || {};
    return `<section class="more-section trade-detail"><h3>What This Measures</h3><p class="detail-copy">${esc(m.description || 'Reconciles local contract metadata against IBKR ContractDetails before using points as dollars.')}</p></section><section class="more-section trade-detail"><h3>Contract Spec Reconcile</h3>${contractSpecRows(m.rows)}</section><section class="more-section"><h3>Source State</h3><dl class="metric-list">${metricLine('local source', m.local_source || '--')}${metricLine('IBKR connected', m.ibkr_connected === true ? 'true' : 'false')}${metricLine('IBKR observed', m.ibkr_observed_at || '--')}${metricLine('mismatches', m.mismatches ?? 0)}${metricLine('missing', m.missing ?? 0)}</dl></section><section class="more-section trade-detail"><h3>Status Rules</h3>${listItems(m.status_rules || [])}</section>`;
  }

  function coverageDetail(item) {
    if (!item) return '<aside class="coverage-detail"><p class="detail-empty">Select a coverage item.</p></aside>';
    const pvb = item.key === 'paper_vs_backtest' ? pnlCompareDetail(item) : '';
    const fill = item.key === 'fill_quality' ? fillQualityDetail(item) : '';
    const stpPlacement = item.key === 'stp_placement' ? stpPlacementDetail(item) : '';
    const rejection = item.key === 'rejections' ? rejectionCoverageDetail(item) : '';
    const contractSpec = item.key === 'contract_spec_guard' ? contractSpecGuardDetail(item) : '';
    const customDetail = pvb || fill || stpPlacement || rejection || contractSpec;
    const evidence = customDetail ? '' : `<p class="coverage-detail-evidence">${esc(item.evidence)}</p>`;
    return `<aside class="coverage-detail"><div class="coverage-detail-head"><h3>${esc(item.title)}</h3><span class="gate-state ${statusClass(item.status)}">${esc(item.status)}</span></div>${evidence}<div class="c1-more-grid">${customDetail || `<section class="more-section"><h3>Metrics</h3>${coverageMetrics(item.metrics)}</section>`}<section class="more-section source-detail"><h3>Sources</h3><ul>${sourceDetail(item.sources)}</ul></section></div></aside>`;
  }

  const coverageGroups = [
    ['Execution health', ['fill_quality', 'stp_placement', 'rejections', 'paper_vs_backtest']],
    ['State and protection', ['state_persist', 'current_protection', 'runner_freshness']],
    ['Data and model', ['data_freshness', 'contract_spec_guard', 'open_incidents']],
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
