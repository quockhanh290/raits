(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]);
  const empty = message => `<p class="empty-report">${esc(message)}</p>`;
  const state = { report:null, broker:null, journalView:'jobs', selectedJob:null, selectedEvent:null, loadSequence:0 };
  const statusLabel = value => ({completed:'COMPLETED',completed_with_debt:'KNOWN DEBT',failed:'OPEN',missed:'MISSED',skipped:'SKIPPED',running:'RUNNING',recovered:'RECOVERED'}[value] || 'UNKNOWN');
  const isoTime = value => value ? new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value))+' ET' : '--';
  const dateTime = value => value ? new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)).replace(',','')+' ET' : '--';
  const money = value => value == null || Number.isNaN(Number(value)) ? '--' : `${Number(value)>=0?'+':'-'}$${Math.abs(Number(value)).toLocaleString('en-US',{maximumFractionDigits:2})}`;
  const emptyRecord = message => `<div class="decision-record"><p>${esc(message)}</p></div>`;
  function etDate(){const x=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const p=Object.fromEntries(x.map(i=>[i.type,i.value]));return `${p.year}-${p.month}-${p.day}`;}
  function activityValue(counts,keys){return keys.reduce((sum,key)=>sum+Number(counts[key]||0),0);}
  function rootOf(symbol){const clean=String(symbol||'').toUpperCase().replace(/[^A-Z0-9]/g,'');if(clean.startsWith('NKD')||clean.startsWith('MNKD'))return 'MNKD';return ['M2K','MNQ','MYM','MES'].find(x=>clean.startsWith(x))||clean.replace(/[0-9].*$/,'');}

  function renderAttention(report){
    const daily=report.daily||{}, incidents=daily.incidents||[], debts=daily.known_debt||[];
    const items=incidents.map(item=>{
      const recovered=item.lifecycle_status==='recovered'; const isJob=Boolean(item.job_id);
      return {kind:recovered?'RECOVERED':(item.status||'OPEN'),cls:recovered?'recovered':'bad',
        title:isJob?`${item.job_id} / ${recovered?'recovered':statusLabel(item.status)}`:(item.title||'Scheduler incident'),
        detail:item.impact||item.message||item.reason||'Operational incident observed.',action:item.action,
        when:`${isoTime(item.started_at||item.ts)}${item.recovered_at?` / recovered ${isoTime(item.recovered_at)}`:item.ended_at?` to ${isoTime(item.ended_at)}`:''}`};
    }).concat(debts.map(debt=>({kind:'KNOWN DEBT',cls:'debt',title:debt.title,detail:`Observed in ${debt.count} completed runner job(s); grouped as one known issue.`,action:'Track under the existing remediation decision; this is not counted as a new daily incident.',when:`${isoTime(debt.first_at)} to ${isoTime(debt.last_at)}`})));
    $('attentionMeta').textContent=`${daily.open_incident_count||0} open / ${incidents.length} occurred / ${debts.length} known debt`;
    $('attentionList').innerHTML=items.length?items.map(item=>`<article class="attention-item"><span class="status-chip ${item.cls}">${esc(item.kind)}</span><div><h3>${esc(item.title)}</h3><p>${esc(item.when)} | ${esc(item.detail)}</p>${item.action?`<p class="action"><strong>Action:</strong> ${esc(item.action)}</p>`:''}</div></article>`).join(''):empty('No incident or known diagnostic was observed for this session.');
  }

  function sessionDecisions(report){
    const daily=report.daily||{}, snap=daily.session_snapshot, events=daily.session_events||[];
    if(snap?.decision){
      const ledger=events.filter(e=>e.kind==='trade_exit_decision');
      const exits=(snap.decision.exits||[]).map(exit=>{const detail=ledger.find(e=>rootOf(e.inst)===rootOf(exit.inst));return {...exit,exit_reason:exit.exit_reason||detail?.exit_reason,exit_price:exit.exit_price||detail?.exit_price,pnl:exit.pnl??detail?.pnl};});
      const tradeRegimes=[...new Set([...(snap.decision.entries||[]),...exits].map(x=>x.regime).filter(Boolean))];
      return {source:'runner decision snapshot + retained execution log',regime:snap.regime||tradeRegimes.join(' / ')||(daily.regime_evidence||[]).join(' / ')||null,decision:{...snap.decision,exits},snap};
    }
    const submitted=events.filter(e=>e.kind==='market_open_submitted');
    const entries=events.filter(e=>e.kind==='market_open_filled').map(fill=>{const sent=submitted.find(x=>x.inst===fill.inst&&x.ts===fill.ts)||{};return {...fill,direction:sent.action==='SELL'?'SHORT':'LONG',cluster:sent.cluster};});
    const exits=events.filter(e=>e.kind==='trade_exit_decision');
    const rejected=events.filter(e=>e.kind==='entry_rejected');
    return {source:'reconstructed from retained execution log',regime:(daily.regime_evidence||[]).join(' / ')||null,decision:{entries,exits,rejected_detail:rejected},snap:null};
  }
  function decisionRecord(title,detail,tone=''){return `<div class="decision-record"><strong class="${tone}">${esc(title)}</strong><p>${esc(detail)}</p></div>`;}
  function renderDecisions(report){
    const daily=report.daily||{}, view=sessionDecisions(report), decision=view.decision||{}, snap=view.snap;
    const ops=snap?.operational_status||{}; const preflight=(daily.jobs||[]).find(x=>x.job_type==='preflight');
    const regime=view.regime||'Unavailable'; const spy=ops.regime_freshness?.last_spy_date||((preflight?.status==='completed')?'Pre-flight passed':'Unavailable');
    const model=ops.model_age ? `${ops.model_age.status}${ops.model_age.months_old==null?'':` / ${ops.model_age.months_old} mo`}` : 'Not retained';
    const breaker=snap?.breaker_level||ops.breaker?.level||'Not retained';
    const breakerNote=snap?.breaker_level?`DD ${(Number(snap.drawdown_pct||0)*100).toFixed(2)}%`:'snapshot unavailable';
    const fit=daily.model_health;
    const fitValue=fit?`${fit.completed_fits}/${fit.attempts} complete`:'Not observed';
    const fitNote=fit?`${fit.non_convergence_count||0} convergence warnings / diagnostic only`:'no retained fit evidence';
    $('contextStrip').innerHTML=[['Regime',regime,snap?.regime?'runner snapshot':'trade decision evidence'],['SPY data',spy,ops.regime_freshness?.status||'daily pre-flight evidence'],['Model age',model,ops.model_age?.model_name||'snapshot unavailable'],['HMM fit',fitValue,fitNote],['Breaker',breaker,breakerNote]].map(([name,value,note])=>`<div class="context-item"><span>${esc(name)}</span><b class="${/ok|calm|normal|complete/i.test(value)?'good':/urgent|hard|stress/i.test(value)?'warn':''}">${esc(value)}</b><small>${esc(note)}</small></div>`).join('');
    const entries=decision.entries||[], exits=decision.exits||[], rejected=decision.rejected_detail||[];
    $('entryDecisionCount').textContent=entries.length; $('exitDecisionCount').textContent=exits.length; $('rejectedDecisionCount').textContent=rejected.length;
    $('entryDecisions').innerHTML=entries.length?entries.map(x=>decisionRecord(`${x.inst||'--'} ${x.direction||''}`.trim(),[x.cluster,x.entry_price||x.price?`fill ${x.entry_price||x.price}`:'',x.risk_sized==null?'':`risk ${money(x.risk_sized)}`].filter(Boolean).join(' / '),'good')).join(''):emptyRecord('No confirmed entry.');
    $('exitDecisions').innerHTML=exits.length?exits.map(x=>decisionRecord(`${x.inst||'--'} ${x.direction||''}`.trim(),[x.exit_reason||'exit type not emitted',x.pnl==null?'':money(x.pnl),x.exit_price?`fill ${x.exit_price}`:''].filter(Boolean).join(' / '),Number(x.pnl||0)>=0?'good':'warn')).join(''):emptyRecord('No confirmed exit.');
    $('rejectedDecisions').innerHTML=rejected.length?rejected.map(x=>decisionRecord(`${x.inst||'--'} ${x.direction||''}`.trim(),[x.cluster,x.reason,Number(x.occurrences||1)>1?`${x.occurrences} observations`:null].filter(Boolean).join(' / '),'warn')).join(''):emptyRecord('No rejected entry observed.');
    $('decisionCoverage').textContent=view.source;
  }

  function brokerReconciliation(report){
    if(!report.is_today)return {cls:'',title:'IBKR RECONCILIATION NOT AVAILABLE',detail:'Historical broker positions and working orders are not retained; activity remains log-confirmed only.'};
    const broker=state.broker, payload=broker?.payload;
    if(!broker?.connected||broker.freshness!=='fresh'||!payload)return {cls:'bad',title:'IBKR RECONCILIATION UNKNOWN',detail:'Current broker read is disconnected or stale.'};
    const expected=report.positions||[], live=payload.positions||[], orders=payload.orders||[];
    const positionMatch=expected.length===live.length&&expected.every(pos=>live.some(x=>rootOf(x.inst)===rootOf(pos.inst)&&(Number(x.position)>=0?'LONG':'SHORT')===String(pos.direction).toUpperCase()&&Math.abs(Number(x.position))===Math.abs(Number(pos.contracts))));
    const stops=orders.filter(x=>/^(STP|STOP)/i.test(String(x.type||''))); const protectedCount=live.filter(pos=>stops.some(order=>String(order.inst).toUpperCase()===String(pos.inst).toUpperCase()&&String(order.action).toUpperCase()===(Number(pos.position)>0?'SELL':'BUY')&&Number(order.qty)===Math.abs(Number(pos.position))&&['SUBMITTED','PRESUBMITTED'].includes(String(order.status).toUpperCase()))).length;
    const orphan=stops.filter(order=>!live.some(pos=>String(pos.inst).toUpperCase()===String(order.inst).toUpperCase())).length;
    const ok=positionMatch&&protectedCount===live.length&&orphan===0;
    return {cls:ok?'good':'bad',title:ok?'RECONCILED WITH IBKR NOW':'IBKR RECONCILIATION NEEDS REVIEW',detail:`${live.length}/${expected.length} positions ${positionMatch?'matched':'do not match'} / ${protectedCount}/${live.length} protected / ${orphan} orphan stop / broker ${isoTime(broker.observed_at)}`};
  }
  function renderActivity(report){
    const events=report.daily?.session_events||[],counts=report.daily?.activity_counts||{};
    const metrics=[['Open fills',activityValue(counts,['market_open_filled']),'good'],['Close fills',activityValue(counts,['market_close_filled','stop_filled']),'good'],['Rejected entries',activityValue(counts,['entry_rejected']),'warn'],['Stops armed',activityValue(counts,['stop_armed','stop_armed_after_deferral']),''],['Stops repaired',activityValue(counts,['stop_repaired']),'warn'],['Stops deferred',activityValue(counts,['stop_deferred']),'warn'],['Stops cancelled',activityValue(counts,['stop_cancelled_after_close']),'']];
    $('activityMetrics').innerHTML=metrics.map(([name,value,cls])=>`<div class="activity-metric ${cls}"><span>${esc(name)}</span><b>${value}</b></div>`).join('');
    const material=events.filter(e=>['EXEC','PROTECTION','DECISION'].includes(e.category)&&!['market_open_submitted','market_close_submitted','trade_exit_decision'].includes(e.kind)); $('activityMeta').textContent=`${material.length} grouped activity item(s)`;
    $('activityFeed').innerHTML=material.length?[...material].reverse().map(e=>`<div class="event-row"><time>${isoTime(e.ts)}</time><span class="event-kind ${String(e.category||'').toLowerCase()}">${esc(e.category)}</span><p>${esc(e.message)}${Number(e.occurrences||1)>1?`<small>Observed ${e.occurrences} times from ${isoTime(e.first_ts)} through ${isoTime(e.ts)}</small>`:''}</p></div>`).join(''):empty('No confirmed trading or protection activity in the session log.');
    const rec=brokerReconciliation(report); $('brokerReconcile').innerHTML=`<b class="${rec.cls}">${esc(rec.title)}</b><p>${esc(rec.detail)}</p>`;
  }

  function renderExecution(report){
    const quality=report.daily?.execution_quality||{}, fills=quality.fills||[], summary=quality.summary||{}, coverage=quality.coverage||{};
    const dist=summary.all_evaluable||{}, opens=summary.opens||{}, stops=summary.stop_fills||{};
    const ticks=value=>value==null?'--':`${Number(value)>=0?'+':''}${Number(value).toFixed(2)}t`;
    const price=value=>value==null?'--':Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4});
    $('executionMeta').textContent=`${fills.length} fill(s) / ${quality.assumption_ticks??2}-tick paper assumption`;
    $('executionSummary').innerHTML=[
      ['Evaluable fills',dist.n||0,`${dist.over_assumption_count||0} above assumption`],
      ['Mean slippage',ticks(dist.mean),dist.n?`${dist.adverse_count||0}/${dist.n} adverse`:'no evaluable fill'],
      ['Open fills',ticks(opens.mean),`${opens.n||0} observed`],
      ['Stop fills',ticks(stops.mean),`${stops.n||0} observed / ${summary.signal_market_closes_not_evaluable||0} signal close not evaluable`]
    ].map(([label,value,note])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join('');
    const coverageItem=(label,count,total)=>`<span><b class="${!total?'':count===total?'available':'missing'}">${esc(label)}</b> ${count}/${total}</span>`;
    $('executionCoverage').innerHTML=[
      coverageItem('Expected-price benchmark',coverage.execution_slippage_evaluable||0,coverage.fill_records||0),
      coverageItem('Commission',coverage.commission_emitted||0,coverage.fill_records||0),
      coverageItem('Route',coverage.route_emitted||0,coverage.fill_records||0),
      coverageItem('Stable execution ID',coverage.stable_execution_id_emitted||0,coverage.fill_records||0),
      `<span><b class="${!coverage.fill_records?'':coverage.signal_close_expected_price_missing?'missing':'available'}">Signal-close benchmark</b> ${coverage.fill_records?(coverage.signal_close_expected_price_missing||0)+' missing':'not observed'}</span>`
    ].join('');
    $('executionRows').innerHTML=fills.length?[...fills].reverse().map(fill=>{
      const benchmark=fill.reference_type==='expected_entry'?'EXPECTED ENTRY':fill.reference_type==='stop_trigger'?'STOP TRIGGER':fill.reference_type==='protective_stop_reference'?'PROTECTIVE STOP REF':'UNAVAILABLE';
      const qualityText=fill.metric_type==='execution_slippage'?ticks(fill.signed_slippage_ticks):fill.metric_type==='distance_to_stop'?`${ticks(fill.signed_distance_to_stop_ticks)} stop distance`:'NOT EVALUABLE';
      const qualityClass=fill.exception?'warn':fill.metric_type==='execution_slippage'?'good':'missing';
      const qualityNote=(fill.exception_reasons||[]).join(' / ')||(fill.metric_type==='distance_to_stop'?'reference only / excluded from execution distribution':fill.metric_type==='execution_slippage'?'within observed assumption':'expected-price benchmark not emitted');
      return `<tr><td><strong>${esc(fill.inst)} ${esc(fill.type)} ${esc(fill.action)}</strong><small>${esc(isoTime(fill.ts))} / ${esc(fill.filled_qty??'--')}/${esc(fill.ordered_qty??'--')} ${esc(fill.status)}</small></td><td><strong>${esc(benchmark)}</strong><small>${esc(price(fill.reference_price))}</small></td><td>${esc(price(fill.actual_price))}</td><td class="${qualityClass}"><strong>${esc(qualityText)}</strong><small>${esc(qualityNote)}</small></td><td><strong>${fill.commission==null?'NOT EMITTED':esc(money(-Math.abs(fill.commission)))}</strong><small>${esc(fill.route||'route not emitted')}</small></td><td><strong>${esc(fill.perm_id||'NOT EMITTED')}</strong><small>${fill.order_id==null?'order ID not emitted':`order #${esc(fill.order_id)}`}</small></td></tr>`;
    }).join(''):`<tr><td colspan="6">${empty('No retained fills for this session.')}</td></tr>`;
  }

  function jobPresentation(job){const recovered=job.lifecycle_status==='recovered'||/Publication resumed at/.test(job.impact||'');const debt=job.status==='completed_with_debt';return {status:recovered?'recovered':debt?'known_debt':job.status==='failed'?'open':job.status,label:recovered?'RECOVERED':debt?'KNOWN DEBT':statusLabel(job.status),tone:recovered?'success':debt?'cleanup':['failed','missed'].includes(job.status)?'incident':job.status==='skipped'?'deferred':'success'};}
  function jobSummary(job){const counts=job.event_counts||{};const parts=[];for(const [key,label] of [['market_open_filled','entry fill'],['market_close_filled','exit fill'],['stop_filled','stop fill'],['stop_armed','stop armed'],['stop_deferred','deferred']])if(counts[key])parts.push(`${counts[key]} ${label}`);if(job.diagnostics?.length)parts.push(`${job.diagnostics.length} diagnostic`);return parts.join(' / ')||job.reason||'No operational change';}
  function renderJobs(jobs){return [...jobs].sort((a,b)=>String(b.started_at).localeCompare(String(a.started_at))).map(job=>{const p=jobPresentation(job),selected=state.selectedJob===job.id;return `<li class="job-row tone-${p.tone} status-${p.status} ${selected?'selected':''}"><button class="job-trigger" type="button" data-job-id="${esc(job.id)}"><span class="job-time">${isoTime(job.started_at)}</span><span class="job-status">${p.label}</span><b class="job-name">${esc(job.job_id)}</b><span class="job-duration">${job.duration_seconds==null?'--':`${job.duration_seconds}s`}</span><span class="job-summary">${esc(jobSummary(job))}</span><span class="job-chevron">${selected?'−':'+'}</span></button>${selected?`<div class="job-detail"><dl><div><dt>Component</dt><dd>${esc(job.job_type)}</dd></div><div><dt>Status</dt><dd>${p.label}</dd></div><div><dt>Started</dt><dd>${dateTime(job.started_at)}</dd></div><div><dt>Ended</dt><dd>${dateTime(job.ended_at)}</dd></div></dl><div class="job-assessment"><div class="job-impact"><b>IMPACT</b><p>${esc(job.impact||'No classified impact.')}</p></div><div class="job-action"><b>ACTION</b><p>${esc(job.action||'No action derived.')}</p></div></div><div class="job-resolution"><b>RESOLUTION</b><p>${esc(p.status==='recovered'?job.impact:(job.status==='completed'?'Completed with no operational failure.':job.reason||'No positive resolution evidence.'))}</p></div>${(job.diagnostics||[]).map(x=>`<div class="job-diagnostic"><b>DIAGNOSTIC</b><p>${esc(x)}</p></div>`).join('')}</div>`:''}</li>`;}).join('');}
  function normalizedEvents(daily){
    const incidentByTs=new Map((daily.incidents||[]).map(x=>[x.ts||x.started_at,x])); const rows=[];
    (daily.monitor_events||[]).forEach(e=>{if(e.kind==='scheduler_recovered')return;if(e.kind==='scheduler_stalled'){const i=incidentByTs.get(e.ts)||e;rows.push({...e,...i,category:'STALL',status:i.lifecycle_status||'open',title:i.title||'Scheduler heartbeat stalled'});}else rows.push({...e,category:e.category||'MONITOR',status:'info'});});
    (daily.incidents||[]).filter(x=>x.job_id).forEach(x=>rows.push({...x,ts:x.ended_at||x.started_at,category:x.status==='missed'?'MISSED SLOT':'JOB FAILURE',title:`${x.job_id} ${x.lifecycle_status==='recovered'?'recovered':x.status}`,status:x.lifecycle_status||'open',message:x.impact||x.reason}));
    (daily.session_events||[]).forEach(e=>rows.push({...e,status:e.status||'info',title:e.title||e.message}));
    const runner=(daily.runner_events||[]).filter(e=>!/^(Runner started:|Day started:)/.test(String(e.message||'')));const latestG2=[...runner].reverse().find(e=>/G2: model age/i.test(e.message||''));runner.filter(e=>!/G2: model age/i.test(e.message||'')||e===latestG2).forEach(e=>rows.push({...e,status:/G2: model age/i.test(e.message||'')?'known_debt':'info',title:/G2: model age/i.test(e.message||'')?'Model age exceeds hard limit':e.message}));
    return rows.sort((a,b)=>String(b.ts).localeCompare(String(a.ts)));
  }
  function renderEvents(daily){return normalizedEvents(daily).map((e,index)=>{const key=`${e.kind||e.category}:${e.ts}:${index}`,selected=state.selectedEvent===key,status=e.status||'info',expandable=['open','recovered','known_debt','diagnostic'].includes(status),tone=status==='open'?'incident':status==='recovered'?'success':status==='known_debt'?'cleanup':status==='diagnostic'?'deferred':e.level==='warn'?'deferred':'action';const body=`<div class="journal-meta"><span>${esc(e.category||e.level||'EVENT')}</span><time>${dateTime(e.ts)}</time></div><div class="event-badges"><span class="event-status ${status}">${status.replace('_',' ').toUpperCase()}</span></div><div class="journal-message">${esc(e.title||e.message)}</div>${e.title&&e.message!==e.title?`<div class="event-summary">${esc(e.message||'')}</div>`:''}${e.recovered_at?`<div class="event-times"><span><b>INCURRED</b>${dateTime(e.started_at||e.ts)}</span><span><b>RECOVERED</b>${dateTime(e.recovered_at)}</span></div>`:''}`;return `<li class="event-row tone-${tone} status-${status} ${selected?'selected':''}">${expandable?`<button type="button" class="event-trigger" data-event-id="${esc(key)}">${body}</button>`:`<div class="event-static">${body}</div>`}${selected&&expandable?`<div class="event-detail"><div><b>PROBLEM</b><p>${esc(e.problem||e.reason||e.message||e.title)}</p></div><div><b>IMPACT</b><p>${esc(e.impact||'No additional impact classified.')}</p></div><div><b>ACTION</b><p>${esc(e.action||'No action derived.')}</p></div><div><b>RESOLUTION</b><p>${esc(e.resolution||(status==='recovered'?`Recovered at ${dateTime(e.recovered_at)}.`:status==='known_debt'?'Open known debt; closes on positive runner evidence.':'No positive resolution evidence observed.'))}</p></div></div>`:''}</li>`;}).join('');}
  function bindJournal(){document.querySelectorAll('[data-job-id]').forEach(b=>b.addEventListener('click',()=>{state.selectedJob=state.selectedJob===b.dataset.jobId?null:b.dataset.jobId;renderJournal();}));document.querySelectorAll('[data-event-id]').forEach(b=>b.addEventListener('click',()=>{state.selectedEvent=state.selectedEvent===b.dataset.eventId?null:b.dataset.eventId;renderJournal();}));}
  function renderJournal(){const daily=state.report?.daily||{};$('journalList').innerHTML=state.journalView==='jobs'?(renderJobs(daily.jobs||[])||`<li>${empty('No scheduler jobs observed.')}</li>`):(renderEvents(daily)||`<li>${empty('No structured events observed.')}</li>`);document.querySelectorAll('.journal-toggle button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===state.journalView)));bindJournal();}

  function renderVerification(report){const resume=report.resume||{},grid=resume.grid||[];$('verificationMeta').textContent=`${resume.streak||0} / ${resume.needed||5} consecutive passing sessions`;if(!grid.length){$('verificationBody').innerHTML=empty('No shadow verification evidence is available for this date.');return;}$('verificationBody').innerHTML=`<div class="shadow-table-wrap"><table class="shadow-table"><thead><tr><th>Session</th><th>MES</th><th>MNQ</th><th>MYM</th><th>M2K</th><th>MNKD</th><th>Verdict</th></tr></thead><tbody>${grid.map(row=>`<tr><td>${esc(row.date)}</td>${row.cells.map(cell=>`<td><span class="shadow-state ${cell.state==='lech'?'mismatch':cell.state==='missing'?'missing':''}">${cell.state==='khop'?'MATCH':cell.state==='lech'?'MISMATCH':'MISSING'}</span></td>`).join('')}<td><span class="shadow-verdict">${row.cells.every(x=>x.state==='khop')?'PASS':'REVIEW'}</span></td></tr>`).join('')}</tbody></table></div>`;}

  function render(report){state.report=report;const daily=report.daily||{},counts=daily.activity_counts||{},occurred=Number(daily.incident_count||0),open=Number(daily.open_incident_count||0),debts=(daily.known_debt||[]).length;const verdict=report.empty?'NO LOG DATA':open?'REVIEW REQUIRED':occurred?'COMPLETED / INCIDENTS RECOVERED':debts?'COMPLETED WITH DEBT':'NORMAL';const cls=report.empty?'unknown':open?'bad':occurred||debts?'watch':'ok';$('reportVerdict').parentElement.className=`report-verdict ${cls}`;$('reportVerdict').textContent=verdict;$('reportScope').textContent=`Daily evidence for ${report.day} ET`;$('verdictScope').textContent=`${open} open / ${occurred} occurred`;$('jobsMetric').textContent=report.empty?'--':String(daily.observed_job_count||0);$('jobsScope').textContent=`${daily.job_status_counts?.completed||0} clean / ${daily.known_debt_job_count||0} with debt`;$('issuesMetric').textContent=`${open} / ${occurred}`;$('tradesMetric').textContent=`${activityValue(counts,['market_open_filled'])} / ${activityValue(counts,['market_close_filled','stop_filled'])}`;$('debtMetric').textContent=String(debts);$('debtScope').textContent=`${daily.known_debt_job_count||0} job observations`;renderDecisions(report);renderAttention(report);renderActivity(report);renderExecution(report);renderJournal();renderVerification(report);$('positionsBand').hidden=!report.is_today;$('reportPositions').innerHTML=(report.positions||[]).length?report.positions.map(p=>`<article class="report-position"><b>${esc(p.inst)} ${esc(p.direction)} x${esc(p.contracts)}</b><p>${esc(p.cluster)} | entry ${esc(p.entry_day)} @ ${esc(p.entry_price)} | ${p.stop_order_id==null?`stop deferred, planned ${esc(p.stop_price)}`:`stop #${esc(p.stop_order_id)} @ ${esc(p.stop_price)}`}</p></article>`).join(''):empty('No current persisted positions.');const c=daily.coverage||{};$('reportSource').textContent=report.source?`${report.source.line_count} report lines | ${report.source.first_time}-${report.source.last_time} ET | scheduler: ${c.job_error||'available'} | execution: ${c.event_error||'available'} | runner JSONL: ${c.runner_event_error||`from ${dateTime(c.runner_event_started_at)}`} | snapshot: ${c.runner_snapshot_available?'available':'not retained'} | files: ${(report.files||[]).join(', ')||'not listed'}`:'No source lines found.';}
  async function fetchJson(url){const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();}
  async function load(){const day=$('reportDate').value,sequence=++state.loadSequence;$('loadReport').disabled=true;$('reportVerdict').textContent='LOADING';try{const requests=[fetchJson(`/api/v1/reports/${encodeURIComponent(day)}`),day===etDate()?fetchJson('/api/v1/broker').catch(()=>null):Promise.resolve(null)];const [report,broker]=await Promise.all(requests);if(sequence!==state.loadSequence)return;state.broker=broker;render(report);}catch(error){if(sequence!==state.loadSequence)return;render({day,empty:true,daily:{jobs:[],session_events:[],monitor_events:[],coverage:{job_error:error.message,event_error:error.message}}});$('reportScope').textContent=`Report unavailable: ${error.message}`;}finally{if(sequence===state.loadSequence)$('loadReport').disabled=false;}}
  document.querySelectorAll('.journal-toggle button').forEach(button=>button.addEventListener('click',()=>{state.journalView=button.dataset.view;state.selectedEvent=null;state.selectedJob=null;renderJournal();}));$('reportDate').value=etDate();$('loadReport').addEventListener('click',load);$('reportDate').addEventListener('change',load);load();
})();
