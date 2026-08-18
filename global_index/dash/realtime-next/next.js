/* ─────────────────────────────────────────────────────────────────────────────
   next.js — enhancement layer for /realtime-next

   Two jobs:
     E3  State the time in the OPERATOR's frame, not the machine's.
     ——  Surface the evidence behind a FAIL verdict next to the verdict itself.

   Why E3: the page says `NKD_NIGHT_0110 · Mon 01:10 ET`. An operator on Hanoi
   time has to translate that into "around midday tomorrow, in about N hours".
   That is a convention the reader must memorise, and it gets done at 2am.

   This file now runs on /realtime as well as /realtime-next and preview.html.
   Three self-imposed rules:

   1. ADD ONLY — never edit or remove what realtime.js owns. It has full authority
      over its own elements; we insert new nodes and always clear our own previous
      nodes before re-inserting. We never touch one of its ids.
   2. NEVER derive a time from displayed text. The page's <time> elements carry no
      datetime attribute, only strings like "Mon 01:10 ET" — reconstructing a date
      from that is guesswork. Absolute instants come from /api/v1/schedule-status.
   3. NEVER take the page down. Everything is wrapped in try/catch: if this layer
      breaks, the page must behave exactly as if it were not loaded.
   ───────────────────────────────────────────────────────────────────────────── */
(() => {
  'use strict';

  const POLL_MS = 30000;          // slower than realtime.js (8s); this is only a side layer
  const OPERATOR_TZ = 'Asia/Ho_Chi_Minh';
  const MARKET_TZ = 'America/New_York';
  const MARK = 'next-when';       // our own marker, so we clear only our nodes
  let schedule = null;
  let runner = null;

  const fmtTZ = (iso, tz) => new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(iso));

  const dayKey = (iso, tz) => new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(iso));

  /* "today / tomorrow / yesterday" is resolved against the OPERATOR's calendar —
     not the market's, and not the machine's. Those three clocks cannot be derived
     from one another, so the frame has to be stated explicitly. */
  const dayWord = (iso, nowIso) => {
    const a = dayKey(iso, OPERATOR_TZ), b = dayKey(nowIso, OPERATOR_TZ);
    if (a === b) return 'today';
    const diff = Math.round((new Date(a) - new Date(b)) / 86400000);
    if (diff === 1) return 'tomorrow';
    if (diff === -1) return 'yesterday';
    if (diff > 1) return `in ${diff} days`;
    return `${-diff} days ago`;
  };

  const spanText = (ms) => {
    const s = Math.abs(Math.round(ms / 1000));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    if (s < 60) return 'under 1m';
    if (h === 0) return `${m}m`;
    if (h < 48) return m ? `${h}h ${m}m` : `${h}h`;
    return `${Math.floor(h / 24)}d ${h % 24}h`;
  };

  /* How far away, and nothing else.

     This used to also print the instant in the operator's own zone
     ("13:35 today HAN"). That has been dropped: the status rail already runs a
     live clock in all three zones (JST · HAN · YYC), and a RELATIVE time needs no
     zone at all — "in 4m" is the same answer wherever the reader is sitting. The
     absolute local time was restating a conversion the relative time had already
     made unnecessary. */
  const whenLine = (iso, nowIso) => {
    const delta = new Date(iso) - new Date(nowIso);
    const lead = delta >= 0 ? `in ${spanText(delta)}` : `${spanText(delta)} ago`;
    const el = document.createElement('small');
    el.className = MARK;
    el.innerHTML = `<b>${lead}</b>`;
    return el;
  };

  /* Three figures the payload already carries and no panel showed.

     Read from /api/v1/runner-state, the same source realtime.js uses for the
     rest of Model Inputs — not scraped off the page, and not derived from
     anything displayed.

       Fit end     `operational_status.model_age.model_name` arrives as
                   "fit_end=2024-12-31". "20 mo stale" says how OLD the fit is;
                   this says what it is anchored TO, which is the half needed to
                   judge whether the staleness matters.
       Re-freeze   `operational_status.refreeze.pending` — reported by the
                   runner, never inferred from model age here.
       Gross       cluster_exposure[*].gross_pct summed. Read as a percentage of
                   equity per cluster; if that aggregation is wrong the label is
                   one line to change, and the figure is not used for anything
                   else on the page.

     Every one writes "--" when its source is absent, so a missing field reads as
     unknown rather than as zero. */
  const FIT_END = /fit_end\s*=\s*([0-9]{4}-[0-9]{2}-[0-9]{2})/i;
  const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };

  const renderModelExtras = () => {
    const ops = runner?.payload?.meta?.operational_status;
    if (!ops) { setText('modelFitEnd', '--'); setText('modelRefreeze', '--'); return; }
    const name = ops.model_age?.model_name;
    const match = name ? FIT_END.exec(String(name)) : null;
    setText('modelFitEnd', match ? match[1] : (name || '--'));
    const pending = ops.refreeze?.pending;
    setText('modelRefreeze', pending === true ? 'pending' : pending === false ? 'none' : '--');
  };

  const renderGrossExposure = () => {
    const snaps = runner?.payload?.snapshots;
    const latest = Array.isArray(snaps) && snaps.length ? snaps[snaps.length - 1] : null;
    const byCluster = latest?.cluster_exposure;
    if (!byCluster || typeof byCluster !== 'object') { setText('metricGrossExposure', '--'); return; }
    let total = 0, seen = 0;
    for (const entry of Object.values(byCluster)) {
      const g = Number(entry?.gross_pct);
      if (Number.isFinite(g)) { total += g; seen += 1; }
    }
    setText('metricGrossExposure', seen ? `${total.toFixed(1)}%` : '--');
  };

  const clearMarks = (root) =>
    root.querySelectorAll('.' + MARK).forEach(n => n.remove());

  /* Which label reads which instant. Only fields that certainly exist in the API
     are mapped — "Latest job" has no matching field, so it is left alone rather
     than filled with a nearby instant that would merely look right. */
  const FIELD_BY_LABEL = {
    'next job': s => s.next_scheduled_job?.at,
    'next decision': s => s.next_decision_job?.at,
    'latest decision': s => s.latest_expected_at,
  };

  const decorateFacts = () => {
    const host = document.getElementById('nowScheduleFacts');
    if (!host || !schedule) return;
    clearMarks(host);
    const now = schedule.server_now;
    host.querySelectorAll('.schedule-fact').forEach(fact => {
      const label = fact.querySelector('span')?.textContent.trim().toLowerCase();
      const pick = FIELD_BY_LABEL[label];
      if (!pick) return;
      const iso = pick(schedule);
      if (!iso) return;
      fact.querySelector('div')?.appendChild(whenLine(iso, now));
    });
  };

  /* Anchor for anything we add to the header. realtime.js only overwrites the
     CONTENTS of #statusRail, never its siblings, so nodes placed here survive
     every render pass. */
  const headerAnchor = (id, after) => {
    const host = document.querySelector('.overview-header');
    if (!host) return null;
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      const ref = after && document.getElementById(after);
      const rail = host.querySelector('.status-rail');
      (ref || rail) ? (ref || rail).after(el) : host.prepend(el);
    }
    return el;
  };

  const renderWindowBar = () => {
    if (!schedule) return;
    const bar = headerAnchor('nextWindowBar');
    if (!bar) return;
    const now = schedule.server_now;
    const iso = schedule.next_decision_job?.at;
    const job = schedule.next_decision_job?.job_id || '';
    if (schedule.active_window) {
      bar.className = 'window-bar in-window';
      bar.innerHTML =
        `<b>ENTRY WINDOW OPEN NOW</b><span>${job ? job + ' · ' : ''}` +
        `${fmtTZ(now, OPERATOR_TZ)} HAN right now</span>`;
      return;
    }
    if (!iso) { bar.className = 'window-bar'; bar.innerHTML = '<b>No entry window scheduled</b>'; return; }
    const delta = new Date(iso) - new Date(now);
    bar.className = 'window-bar';
    bar.innerHTML =
      `<b>Next entry window opens in ${spanText(delta)}</b>` +
      `<span>${job} · ${fmtTZ(iso, OPERATOR_TZ)} ${dayWord(iso, now)} HAN` +
      ` · ${new Date(iso).toISOString().slice(11, 16)} UTC</span>`;
  };

  /* A grouped incident card used to be built here, to put the evidence for a FAIL
     verdict next to the verdict itself. It has been removed, and the reason is
     worth keeping: it was redundant from the moment it was written.

     realtime.js already groups recovered incidents by the same stream key, labels
     them RECOVERED, names the slot that resumed the stream, and adds "N slot(s)
     lost, recovered" to the Now Monitor summary. All of it existed; it was simply
     1285px down the page. Moving Now Monitor under the verdict fixed the actual
     problem — distance — and left this card restating the section directly below it.

     The lesson: the gap was in PLACEMENT, and the first fix built a new component
     instead. Check whether the page already says it somewhere before adding a
     second place that says it. */

  /* E6 · Text labels for the three threshold bands on the risk gauge.

     66% and 100% are the thresholds realtime.js ALREADY uses to switch the bar's
     class (>=100 'bad', >=66 'watch') — the system's own thresholds, not new ones
     invented here. No absolute figure is printed: the hard limit already appears
     on the line below ("… of 15.00% hard limit"), and re-reading it from rendered
     text would be guesswork. */
  const renderGaugeScale = () => {
    const gauge = document.querySelector('.risk-zone .dd-gauge');
    if (!gauge || gauge.parentElement.querySelector('.gauge-scale')) return;
    const scale = document.createElement('div');
    scale.className = 'gauge-scale';
    scale.innerHTML = '<span>safe</span><span>watch</span><span>over limit</span>';
    scale.setAttribute('aria-hidden', 'true');   // the meter carries its own label
    gauge.after(scale);
  };

  /* Now Monitor belongs directly under the verdict strip, but it lives in the
     workspace column while the strip lives in the header — two different
     containers, so CSS `order` cannot reach across. The node is MOVED rather than
     copied, and every id inside it travels with it: realtime.js finds its targets
     with getElementById, which does not care where in the document they sit.

     Placed after the evidence card when one exists, so the verdict and the
     evidence for it stay adjacent; on a clean day there is no evidence card and
     it lands straight under the strip. */
  const placeNowMonitor = () => {
    const host = document.querySelector('.overview-header');
    const monitor = document.querySelector('.now-monitor');
    if (!host || !monitor) return;
    if (monitor.parentElement === host && monitor === host.firstElementChild) return;
    host.prepend(monitor);
  };

  /* Lift the verdict strip and the journal out of their original containers so the
     page can run as one two-column grid from the top:

         status rail            (full width)
         Now Monitor  | journal   <- both start on the same line
         figures      | journal
         workspace    | journal

     Before this the journal lived inside `.workspace`, which begins only after the
     figures, so it started roughly a screen below Now Monitor.

     These are MOVES, not copies or rebuilds. Every id travels with the node and
     realtime.js resolves its targets with getElementById, which does not care
     where in the document they sit. Nothing is removed. */
  const restructure = () => {
    const main = document.querySelector('main');
    const overview = document.querySelector('.overview-header');
    if (!main || !overview) return;

    const rail = overview.querySelector('.status-rail');
    if (rail && rail.parentElement !== main) main.prepend(rail);

    const journal = document.querySelector('.journal-column');
    if (journal && journal.parentElement !== main) main.append(journal);

    main.classList.add('is-two-column');
  };

  /* Exposure reads as figures, not sentences — but only where the sentence is
     unambiguous.

     realtime.js writes this field as one of:
         --  ·  no positions  ·  N covered
         N covered / M deferred  ·  N covered / M naked

     `naked` means a position with no protective stop against it. Collapsing
     that line to a bare number would delete the one word on the card an
     operator must not miss, so this only rewrites the form that means
     "everything is covered" — an exact `N covered` and nothing else. Every
     other string, including anything mentioning deferred or naked, is left
     exactly as realtime.js wrote it.

     This does read rendered text, which this file otherwise avoids. It is safe
     here only because it fails CLOSED: an unrecognised string is not touched. */
  const ALL_COVERED = /^(\d+) covered$/;
  const compactProtection = () => {
    const el = document.getElementById('metricStopsCovered');
    if (!el) return;
    const txt = el.textContent.trim();
    if (/^\d+$/.test(txt) || txt === '--') return;   // already ours, or nothing to say
    if (txt === 'no positions') {        // no position means nothing to protect
      el.dataset.tooltip = txt;
      el.textContent = '--';
      return;
    }
    const m = ALL_COVERED.exec(txt);
    if (!m) return;                      // deferred or naked — the words stay
    el.textContent = m[1];
    el.dataset.tooltip = txt;            // the sentence stays one hover away
  };

  /* The expanded job card printed the same sentence twice.

     realtime.js builds a KNOWN DEBT / ERROR EVIDENCE block from `job.diagnostics`
     and, below it, an EVIDENCE / RESOLUTION block whose first line is
     `presentation.evidence`. For a model-age job those two are the SAME string,
     so the card showed one diagnostic line, then a heading, then the identical
     line again — with only the resolution sentence underneath carrying anything
     new.

     Where the texts match, the upper block is hidden: the lower one keeps both
     the evidence and the "closes when …" line, so nothing is lost. Compared as
     normalised text, never by index, and only ever hiding an exact duplicate. */
  const norm = el => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');

  /* The expanded card repeated the run duration.

     The collapsed row already prints it verbatim — "1m 34s" sits about forty
     pixels above — and the detail block printed it again as one of four facts.
     The reference build carries only two facts here (Started · Exit), and this
     is the one of ours that says nothing new.

     NOT removed: "Completed". The reference omits it, but omitting it here would
     leave the reader to add 02:50:07 + 1m 34s in their head, and this page is
     read at 2am across three clocks. A layout that matches at the cost of mental
     arithmetic is the wrong trade for this operator.

     Matched on the LABEL, never on position: if realtime.js renames or reorders
     the cells, nothing is hidden rather than the wrong thing. */
  const DUPLICATED_FACT = /^duration$/i;
  const dropRepeatedFacts = () => {
    document.querySelectorAll('.job-detail > dl > div').forEach(cell => {
      const label = cell.querySelector('dt');
      cell.hidden = Boolean(label) && DUPLICATED_FACT.test(label.textContent.trim());
    });
  };
  const dedupeJobEvidence = () => {
    document.querySelectorAll('.job-detail').forEach(detail => {
      const resolution = detail.querySelector('.job-resolution');
      if (!resolution) return;
      const said = new Set([...resolution.querySelectorAll('p')].map(norm).filter(Boolean));
      if (!said.size) return;
      detail.querySelectorAll('.job-diagnostic').forEach(block => {
        const body = norm(block.querySelector('p'));
        block.hidden = Boolean(body) && said.has(body);
      });
    });
  };

  const apply = () => {
    try { restructure(); placeNowMonitor(); decorateFacts(); renderWindowBar(); renderGaugeScale(); compactProtection(); dedupeJobEvidence(); dropRepeatedFacts();
            renderModelExtras(); renderGrossExposure(); }
    catch (e) { /* must never take the page down */ }
  };

  const load = async () => {
    try {
      const [scheduleRes, runnerRes] = await Promise.all([
        fetch('/api/v1/schedule-status', { cache: 'no-store' }),
        fetch('/api/v1/runner-state', { cache: 'no-store' }).catch(() => null),
      ]);
      if (!scheduleRes.ok) return;
      schedule = await scheduleRes.json();
      /* A runner read that fails leaves `runner` null, and every field it feeds
         falls back to "--". Never carried over from a previous poll: a stale
         figure presented as current is worse than an absent one. */
      runner = runnerRes && runnerRes.ok ? await runnerRes.json().catch(() => null) : null;
      apply();
    } catch (e) { /* silent: if this layer fails the page must still run */ }
  };

  /* realtime.js rebuilds #nowScheduleFacts on every poll (8s), which removes our
     extra lines with it. Re-attach after each of its render passes. */
  const watch = () => {
    const host = document.getElementById('nowScheduleFacts');
    if (host) {
      new MutationObserver(() => {
        if (host.querySelector('.' + MARK)) return;   // avoid retriggering ourselves
        apply();
      }).observe(host, { childList: true, subtree: true });
    }
    /* The protection field is rewritten by realtime.js every 8s — faster than
       this layer's 30s poll — so it needs its own watcher or the shortened form
       flickers back to the sentence between passes. compactProtection() returns
       immediately when the text is already ours, so this cannot loop. */
    const journal = document.getElementById('journal');
    if (journal) {
      new MutationObserver(() => {
        try { dedupeJobEvidence(); dropRepeatedFacts(); } catch (e) {}
      }).observe(journal, { childList: true, subtree: true });
    }
    const prot = document.getElementById('metricStopsCovered');
    if (prot) {
      new MutationObserver(() => { try { compactProtection(); } catch (e) {} })
        .observe(prot, { childList: true, characterData: true, subtree: true });
    }
  };

  const start = () => { load(); watch(); setInterval(load, POLL_MS); };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start)
    : start();
})();
