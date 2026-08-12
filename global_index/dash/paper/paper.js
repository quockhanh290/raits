(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  const normalizeExit = value => {
    const reason = String(value || '').toUpperCase();
    if (reason.includes('MAX_HOLD')) return 'MAX_HOLD';
    if (reason.includes('CHANDELIER')) return 'CHANDELIER';
    if (reason === 'STOP' || reason.includes('STP')) return 'STP';
    return null;
  };

  function observations(payload) {
    const epoch = payload.meta?.system_epoch;
    const eligible = (payload.snapshots || []).filter(row => row.date && (!epoch || row.date >= epoch));
    const rows = [...new Map(eligible.map(row => [row.date, row])).values()];
    const regimes = [...new Set(rows.map(row => row.regime).filter(value => value === 'Normal' || value === 'Stress'))];
    const exits = { CHANDELIER: 0, MAX_HOLD: 0, STP: 0 };
    const openSlips = [];
    const closeSlips = [];
    rows.forEach(row => {
      (row.decision?.exits || []).forEach(item => { const key = normalizeExit(item.exit_reason); if (key) exits[key] += 1; });
      (row.slippage || []).forEach(item => {
        if (!Number.isFinite(Number(item.ticks))) return;
        if (String(item.type).toUpperCase() === 'OPEN') openSlips.push(Number(item.ticks));
        if (String(item.type).toUpperCase() === 'CLOSE') closeSlips.push(Number(item.ticks));
      });
    });
    const mean = values => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    return { epoch, rows, regimes, exits, openSlips, closeSlips, openMean: mean(openSlips), closeMean: mean(closeSlips) };
  }

  function gate(title, evidence, requirement, state) {
    return `<article class="ledger-row"><b>${esc(title)}</b><p>${esc(evidence)}</p><small>${esc(requirement)}</small><span class="gate-state ${state.toLowerCase()}">${esc(state)}</span></article>`;
  }

  function render(data) {
    const payload = data.payload || {};
    const sourceFreshness = data.freshness || 'unknown';
    const sourceMissing = !Array.isArray(payload.snapshots) || sourceFreshness === 'missing' || sourceFreshness === 'unknown';
    const obs = observations(payload);
    const daysState = obs.rows.length >= 60 ? 'PASS' : 'PENDING';
    const regimeState = obs.regimes.includes('Normal') && obs.regimes.includes('Stress') ? 'PASS' : 'PENDING';
    const exitPass = Object.values(obs.exits).every(count => count >= 3);
    const slipState = obs.openMean == null && obs.closeMean == null ? 'MISSING' : 'PENDING';
    $('paperDays').textContent = `${obs.rows.length} / 60`;
    $('regimesSeen').textContent = obs.regimes.length ? obs.regimes.join(' + ') : 'None';
    $('exitCoverage').textContent = `${Object.values(obs.exits).filter(count => count >= 3).length} / 3`;
    $('slippageMean').textContent = obs.openMean == null ? '--' : `${obs.openMean >= 0 ? '+' : ''}${obs.openMean.toFixed(2)} ticks`;
    $('closeSlippageMean').textContent = obs.closeMean == null ? 'close mean --' : `close mean ${obs.closeMean >= 0 ? '+' : ''}${obs.closeMean.toFixed(2)} ticks`;
    $('slippageCount').textContent = `${obs.openSlips.length} / ${obs.closeSlips.length}`;
    $('ledgerSource').textContent = `Runner epoch ${obs.epoch || 'missing'} | source ${sourceFreshness} | observed ${data.observed_at || 'unknown'}`;
    $('evidenceLedger').innerHTML = [
      gate('Paper duration', `${obs.rows.length} distinct runner snapshot day(s) in paper epoch`, 'Conservative end of documented minimum: 60 days', daysState),
      gate('Regime coverage', obs.regimes.length ? obs.regimes.join(', ') : 'No qualifying regime observed', 'Normal and Stress must both be observed', regimeState),
      gate('Exit path coverage', `Chandelier ${obs.exits.CHANDELIER} | MAX_HOLD ${obs.exits.MAX_HOLD} | STP ${obs.exits.STP}`, 'Each path several times; ledger interprets several as 3', exitPass ? 'PASS' : 'PENDING'),
      gate('C1 slippage', obs.openMean == null && obs.closeMean == null ? 'No samples emitted' : `OPEN ${obs.openMean == null ? '--' : `${obs.openMean.toFixed(2)} ticks N=${obs.openSlips.length}`} | CLOSE ${obs.closeMean == null ? '--' : `${obs.closeMean.toFixed(2)} ticks N=${obs.closeSlips.length}`}`, 'Signed ticks: positive is adverse. Limit is <= 2 ticks, but gate scope and minimum N are not quantified', slipState),
      gate('B3 cold-start reconcile', 'No structured B3 observation in runner state', '0 mismatches on every cold start', 'MISSING'),
      gate('STP verification', 'No structured false-halt count in runner state', 'No false halt', 'MISSING'),
      gate('TWS restart nights', 'No structured restart-night evidence in runner state', 'Many nights; minimum count is not quantified', 'MISSING')
    ].join('');
    $('evidenceGaps').innerHTML = [
      ['C1 gate definition', 'PAPER_ROUTE requires mean <= 2 ticks and a sufficiently large N, but does not say whether OPEN and CLOSE are gated separately or define minimum N. The monitor keeps both signed means separate.'],
      ['TWS restart coverage', 'The document requires many restart nights, but neither a numeric threshold nor structured observations exist.'],
      ['B3 / STP outcomes', 'Runner state does not emit cold-start mismatch or false-halt counters. Review remains log/report evidence until a separate telemetry decision.']
    ].map(([title, detail]) => `<article class="gap-item"><b>${esc(title)}</b><p>${esc(detail)}</p></article>`).join('');
    const complete = !sourceMissing && daysState === 'PASS' && regimeState === 'PASS' && exitPass && slipState === 'PASS';
    const readiness = $('overallStatus').parentElement;
    readiness.classList.toggle('unknown', sourceMissing);
    readiness.classList.toggle('complete', complete);
    $('overallStatus').textContent = sourceMissing ? 'UNKNOWN' : complete ? 'EVIDENCE COMPLETE' : 'INSUFFICIENT DATA';
    $('overallReason').textContent = sourceMissing ? 'Runner evidence source is unavailable' : complete ? 'All observable gates passed' : sourceFreshness === 'late' ? 'Evidence is incomplete; current runner source is also late' : 'Pending gates or missing structured evidence remain';
  }

  async function load() {
    try {
      const response = await fetch('/api/v1/runner-state', { cache: 'no-store', signal: AbortSignal.timeout(6000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      const readiness = $('overallStatus').parentElement;
      readiness.classList.add('unknown');
      readiness.classList.remove('complete');
      $('overallStatus').textContent = 'UNKNOWN';
      $('overallReason').textContent = `Runner state unavailable: ${error.message}`;
      $('ledgerSource').textContent = 'Runner evidence source unavailable';
    }
  }

  load();
  window.setInterval(load, 60000);
})();
