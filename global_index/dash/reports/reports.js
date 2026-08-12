(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  const empty = message => `<p class="empty-report">${esc(message)}</p>`;
  const jobFamily = id => {
    const value = String(id || '');
    if (value.startsWith('nkd_night')) return { key: 'nkd_night', label: 'NKD Night runner' };
    if (value.startsWith('live_day')) return { key: 'live_day', label: 'Live Day runner' };
    if (value.startsWith('stop_repair')) return { key: 'stop_repair', label: 'Stop repair' };
    return null;
  };

  function etDate() {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const value = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${value.year}-${value.month}-${value.day}`;
  }

  function render(report) {
    const issues = report.issues || [];
    const blockerCount = (report.blockers || []).length;
    const seriousCount = (report.serious || []).length;
    const verdict = report.empty ? 'NO LOG DATA' : blockerCount ? 'BLOCKING ISSUE' : seriousCount ? 'SERIOUS ISSUE' : report.need ? 'REVIEW NEEDED' : 'NORMAL';
    const verdictClass = report.empty ? 'unknown' : blockerCount ? 'bad' : seriousCount || report.need ? 'watch' : 'ok';
    const verdictEl = $('reportVerdict').parentElement;
    verdictEl.className = `report-verdict ${verdictClass}`;
    $('reportVerdict').textContent = verdict;
    $('reportScope').textContent = report.empty ? 'No matching scheduler/live log lines' : `Session ${report.day} ET`;
    $('jobsMetric').textContent = report.empty ? '--' : `${report.jobs_ran || 0} / ${report.jobs_due || 0}`;
    $('issuesMetric').textContent = String(issues.length);
    $('positionsMetric').textContent = report.is_today ? String(report.current_position_count || 0) : 'N/A';
    $('positionsScope').textContent = report.is_today ? 'current state' : 'not valid for past dates';
    $('linesMetric').textContent = report.source ? Number(report.source.line_count || 0).toLocaleString('en-US') : '0';

    $('actionList').innerHTML = (report.todo || []).length ? report.todo.map(item => `<div class="action-item">${esc(item)}</div>`).join('') : empty(report.empty ? 'No evidence available to derive actions.' : 'No operator action derived from this session.');
    $('reportIssues').innerHTML = issues.length ? issues.map(issue => `<article class="report-issue ${(report.blockers || []).includes(issue.title) ? 'blocker' : ''}"><span>${esc(issue.severity_label)}</span><h3>${esc(issue.title)}</h3><p>${esc(issue.first)} to ${esc(issue.last)} | ${esc(issue.count)} occurrence(s)${issue.ended ? ' | no recent recurrence' : ''}</p><p>${esc(issue.mean)}</p></article>`).join('') : empty(report.empty ? 'No log lines to inspect.' : 'No known issue patterns detected.');

    const jobs = (report.timeline || []).filter(item => item.kind === 'job');
    const grouped = [];
    const familyIndexes = new Map();
    jobs.forEach(job => {
      const family = jobFamily(job.id);
      if (!family) {
        grouped.push({ type: 'single', jobs: [job] });
        return;
      }
      if (!familyIndexes.has(family.key)) {
        familyIndexes.set(family.key, grouped.length);
        grouped.push({ type: 'family', family, jobs: [] });
      }
      grouped[familyIndexes.get(family.key)].jobs.push(job);
    });
    const jobRow = job => `<div class="job-row ${job.missing ? 'missing' : ''}"><time>${esc(job.time)}</time><i></i><b>${esc(job.id)}</b><span>${job.missing ? 'NOT OBSERVED' : 'OBSERVED'}</span></div>`;
    $('jobTimeline').innerHTML = grouped.length ? grouped.map(group => {
      if (group.type === 'single') return jobRow(group.jobs[0]);
      const missing = group.jobs.filter(job => job.missing).length;
      const first = group.jobs[0]?.time || '--';
      const last = group.jobs[group.jobs.length - 1]?.time || '--';
      const observed = group.jobs.length - missing;
      return `<details class="job-family ${missing ? 'missing' : ''}" ${missing ? 'open' : ''}>
        <summary><time>${esc(first)}-${esc(last)}</time><i></i><b>${esc(group.family.label)}</b><span>${observed}/${group.jobs.length} OBSERVED</span></summary>
        <div class="job-family-rows">${group.jobs.map(jobRow).join('')}</div>
      </details>`;
    }).join('') : empty('No due jobs available for this report.');
    $('timelineNote').textContent = report.skipped_past_missing ? 'Past date: missing-job verdict suppressed because the current schedule is not historical evidence.' : `${(report.missing_jobs || []).length} missing due job(s)`;

    $('positionsBand').hidden = !report.is_today;
    $('reportPositions').innerHTML = (report.positions || []).length ? report.positions.map(pos => `<article class="report-position"><b>${esc(pos.inst)} ${esc(pos.direction)} x${esc(pos.contracts)}</b><p>${esc(pos.cluster)} | entry ${esc(pos.entry_day)} @ ${esc(pos.entry_price)}</p><p>${pos.stop_order_id == null ? `Deferred / no broker stop ID | planned ${esc(pos.stop_price)}` : `Stop ${esc(pos.stop_order_id)} @ ${esc(pos.stop_price)}`}</p></article>`).join('') : empty('No current persisted positions.');
    $('reportSource').textContent = report.source ? `${report.source.line_count} lines | ${report.source.first_time}-${report.source.last_time} ET | ${report.dropped || 0} test lines excluded | files: ${(report.files || []).join(', ') || 'not listed'}` : `No source lines found under ${report.root || 'repository root'}`;
  }

  async function load() {
    const day = $('reportDate').value;
    $('loadReport').disabled = true;
    $('reportVerdict').textContent = 'LOADING';
    try {
      const response = await fetch(`/api/v1/reports/${encodeURIComponent(day)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      render({ day, empty: true, root: '', issues: [], todo: [] });
      $('reportVerdict').parentElement.className = 'report-verdict unknown';
      $('reportVerdict').textContent = 'UNKNOWN';
      $('reportScope').textContent = `Report unavailable: ${error.message}`;
      $('reportSource').textContent = 'Report source unavailable; no conclusion can be drawn about session logs.';
    } finally {
      $('loadReport').disabled = false;
    }
  }

  $('reportDate').value = etDate();
  $('loadReport').addEventListener('click', load);
  $('reportDate').addEventListener('change', load);
  load();
})();
