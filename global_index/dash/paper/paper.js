(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

  function fmtTicks(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '--';
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)} ticks`;
  }

  function statusClass(status) {
    return String(status || 'unknown').toLowerCase().replace(/_/g, '-');
  }

  function sourceLine(gate) {
    const paths = (gate.sources || []).map(source => source.path).filter(Boolean);
    return paths.length ? `source: ${paths.join(' + ')}` : 'source: unavailable';
  }

  function gateRow(gate) {
    return `<article class="ledger-row"><b>${esc(gate.title)}</b><p>${esc(gate.evidence)}</p><small>${esc(gate.requirement)} | ${esc(sourceLine(gate))}</small><span class="gate-state ${statusClass(gate.status)}">${esc(gate.status)}</span></article>`;
  }

  function coverageItem(item) {
    return `<article class="coverage-item"><b>${esc(item.title)}</b><span class="gate-state ${statusClass(item.status)}">${esc(item.status)}</span><p>${esc(item.evidence)}</p><small>${esc(sourceLine(item))}</small></article>`;
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
    $('closeSlippageMean').textContent = `stp close mean ${fmtTicks(summary.c1_close_mean)}`;
    $('slippageCount').textContent = `${summary.c1_open_n ?? 0} / ${summary.c1_close_n ?? 0}`;
    $('ledgerSource').textContent = `Paper epoch ${payload.epoch || 'missing'} | source ${data.source || 'unknown'} | observed ${data.observed_at || 'unknown'}`;
    $('evidenceLedger').innerHTML = gates.map(gateRow).join('');
    $('paperCoverage').innerHTML = coverage.map(coverageItem).join('');
    $('evidenceGaps').innerHTML = (payload.gaps || []).map(item => `<article class="gap-item"><b>${esc(item.title)}</b><p>${esc(item.detail)}</p></article>`).join('');
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
      $('ledgerSource').textContent = 'Paper evidence source unavailable';
    }
  }

  load();
  window.setInterval(load, 60000);
})();
