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

  /* groupBands empties `.overview-header` by taking Now Monitor, the window bar
     and the figures row down into the bands. The shell carries its own background
     and a bottom rule, so an empty one paints a stray band across the page.

     It is HIDDEN, never removed: realtime.js resolves its targets by id and a
     removed container takes any future child with it. `hidden` is also what the
     page's own header comment prescribes for exactly this case.

     Re-checked every pass rather than once, because a later render can put
     something back into it — and a header that quietly swallowed a new panel
     would be the same class of bug as a job that runs and appears nowhere. */
  /* Two figure-row differences from the design, both structural rather than
     painted, so CSS alone cannot reach them:

       Model Inputs   the design carries it as the "Model inputs" strip along the
                      top of Regime Monitor, where the regime it explains is. On
                      this page it is a top-level card in the figures row, which
                      reads as a fifth headline number.
       Figures row    the design is ONE row of four — equity, performance, risk,
                      exposure. Moving Model Inputs out leaves equity alone on a
                      two-card lead row, so the three cards below join it.

     `.metrics-figures` is emptied by the move and hidden, not removed: it is a
     container realtime.js may write into again, and a removed one takes whatever
     lands there next off the page with it.

     Every id travels with its node; realtime.js resolves by getElementById. */
  const matchFigureLayout = () => {
    const regime = document.querySelector('.regime-section');
    const mi = document.getElementById('modelInputsZone');
    const lead = document.querySelector('.metrics-lead');
    const figures = document.querySelector('.metrics-figures');
    if (!regime || !mi || !lead || !figures) return;

    /* Into the CARD, not the section. The design runs Model Inputs as the card's
       first row, above the label and its metrics, sharing the card's frame; the
       first attempt here targeted `.section-body`, which this section does not
       have, so it fell back to the section itself and the strip floated outside
       the frame above the heading — measured, and visibly not the design. */
    const body = regime.querySelector('.rg2-card') || regime;
    if (mi.parentElement !== body || mi !== body.firstElementChild) body.prepend(mi);

    while (figures.firstElementChild) lead.appendChild(figures.firstElementChild);
    if (figures.hidden !== true) figures.hidden = true;
  };

  /* The regime panel says the same thing twice. A metric tile reads "Shift
     threshold / None published / … the label comes from a Viterbi decode, which
     compares states against each other rather than against a cut", and the
     footnote two rows below reads "No fixed shift threshold: the model selects
     the most likely state by comparing posteriors." One fact, two places, and the
     tile spends a quarter of the metric row saying a number does not exist.

     The design keeps the footnote and drops the tile, so that is what happens
     here — hidden, never removed, per this page's own rule for anything
     realtime.js might write to again.

     Guarded on the footnote still carrying the fact. If that sentence ever
     changes, the tile becomes the only place the reader is told there is no
     threshold, and folding it would delete the fact rather than de-duplicate it. */
  const foldRestatedThreshold = () => {
    const host = document.getElementById('regimeMetrics');
    const note = document.getElementById('regimeNote');
    if (!host) return;
    const stillSaid = !!note && /no fixed shift threshold/i.test(note.textContent || '');
    [...host.children].forEach(el => {
      const dupe = stillSaid && /shift threshold/i.test(el.textContent || '');
      if (el.classList.contains('is-restated') !== dupe) el.classList.toggle('is-restated', dupe);
    });
  };

  /* Reading one slot across every lane.
     ────────────────────────────────────
     The lanes stack four rules over the same 22 slots, and the question they
     exist to answer is "at the slot that failed, what did the others say?".
     Answering it meant counting cells across four rows with a finger on the
     screen. The design solves it by lighting the whole column under the cursor;
     this does the same.

     Every cell and slot already carries a `title` written by realtime.js from
     the recorded verdicts — "01:10 · gate allow · passed". The readout is
     assembled from those, so it says exactly what the page already says and
     cannot drift from it. Nothing here re-derives a time: slot clocks are read
     off the titles, never interpolated between the axis ticks.

     Listeners are delegated from `.market-view-section`, which is a static
     element of the page rather than one realtime.js rebuilds, so the wiring
     survives every 8s re-render without being re-attached. */
  const SLOT_HINT = 'hover a slot to line up every rule at the same moment';
  let slotHoverWired = false;

  const slotReadoutNode = () => {
    const lanes = document.querySelector('.mv2-lanes');
    if (!lanes) return null;
    /* The design puts this hint on the RIGHT of the card head, not on a line of
       its own below it: it labels the grid, and a label under the thing it labels
       reads as a first row of data. Fall back to the old position if the card was
       built without a head. */
    const head = lanes.parentElement.querySelector('.mv2-card-head');
    let el = document.querySelector('.mv2-slot-readout');
    if (!el) {
      el = document.createElement('div');
      el.className = 'mv2-slot-readout';
      el.textContent = SLOT_HINT;
    }
    /* realtime.js may have rebuilt the card and dropped our node; put it back
       rather than assuming it survived. */
    if (head) {
      if (el.parentElement !== head || el !== head.lastElementChild) head.appendChild(el);
    } else if (el.parentElement !== lanes.parentElement || el.nextElementSibling !== lanes) {
      lanes.parentElement.insertBefore(el, lanes);
    }
    return el;
  };

  /* The design wraps verdict + inner tabs + lane grid in ONE card; the repo leaves
     them as flat children of the section, so the verdict reads as a loose bar above
     unrelated content. Wrap once. These nodes are never REPLACED by realtime.js --
     it resolves them by id and writes their innerHTML -- so once moved they stay,
     and the guard below keeps the section observer from re-entering this. */
  const SHELL = 'mv2-shell';
  const wrapMarketViewCard = () => {
    const sec = document.querySelector('.market-view-section');
    if (!sec || sec.querySelector(':scope > .' + SHELL)) return;
    const nodes = ['marketViewVerdict', 'marketViewSummary', 'marketViewInnerTabs',
                   'marketViewLanes', 'marketViewChart', 'marketViewSetup']
      .map(id => document.getElementById(id))
      .filter(n => n && n.parentElement === sec);
    if (nodes.length < 2) return;
    const shell = document.createElement('div');
    shell.className = SHELL;
    sec.insertBefore(shell, nodes[0]);
    nodes.forEach(n => shell.appendChild(n));
  };

  const clearSlotHot = () => document.querySelectorAll('.is-slot-hot')
    .forEach(n => n.classList.remove('is-slot-hot'));

  const trackOf = el => el.closest('.mv2-lane-track');
  const partsOf = el => String(el.getAttribute('title') || '').split('·').map(s => s.trim());

  const showSlot = (index, count) => {
    const readout = slotReadoutNode();
    if (!readout) return;
    clearSlotHot();
    let clock = '';
    const said = [];
    document.querySelectorAll('.mv2-lane-track').forEach(track => {
      const kids = track.querySelectorAll('.mv2-cell, .mv2-slot');
      if (kids.length !== count) return;               // a lane that runs a different grid
      const hit = kids[index];
      if (!hit) return;
      hit.classList.add('is-slot-hot');
      const p = partsOf(hit);
      if (!clock && p[0]) clock = p[0];
      if (p.length >= 3) said.push(p[1] + ': ' + p.slice(2).join(' · '));
    });
    readout.textContent = `slot ${index + 1} / ${count}`
      + (clock ? ` · ${clock} ET` : '')
      + (said.length ? ' — ' + said.join(' · ') : '');
  };

  /* The same minute, in both charts.
     ────────────────────────────────
     The price chart plots one mark per slot, each carrying data-slot / data-time
     / data-word / data-reason written by realtime.js from the recorded session;
     the series chart plots one point per slot in the same order. Hovering a mark
     draws a rule down BOTH at that slot.

     The x of a slot is taken from each chart separately, never shared. Measured:
     both SVGs are viewBox "0 0 1000 …" with preserveAspectRatio="none", but the
     marks run 341.9 → 880.7 while the series line runs 52 → 988 — the price chart
     also carries the bars before the window opened. A single fraction applied to
     both would put the two crosshairs on different minutes, which is precisely
     the error this feature exists to prevent. */
  /* Round dots in a stretched chart.
     ────────────────────────────────
     Both plots are `preserveAspectRatio="none"`: the viewBox is 1000 wide and the
     pane is ~1600px, so x is scaled ~1.6 while y is not. Every dot authored as a
     circle therefore rendered as a flattened oval — measured 10.9px wide by 6.8px
     tall on a dot meant to be 6.8 across.

     realtime.js now emits them as ellipses carrying the radius we want to SEE;
     this divides rx by the measured scale so the screen shows a circle. It is
     recomputed on every pass and on resize, because the scale is a function of
     the pane's width and nothing tells us in advance what that will be.

     Reading the scale from the rendered box rather than assuming it: the plot
     height is pinned at 320px by CSS today, but a pane that ever changes height
     would silently start stretching y too, and a hard-coded ratio would not say so. */
  const undoPaneStretch = () => {
    document.querySelectorAll('.market-view-section svg').forEach(svg => {
      const vb = (svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number);
      const box = svg.getBoundingClientRect();
      if (vb.length !== 4 || !vb[2] || !box.width) return;
      const sx = box.width / vb[2];
      const sy = box.height / vb[3];
      if (!(sx > 0) || !(sy > 0)) return;
      svg.querySelectorAll('ellipse[ry]').forEach(el => {
        const ry = parseFloat(el.getAttribute('ry'));
        if (!Number.isFinite(ry)) return;
        // ry is authored in the units we want on screen; correct BOTH axes so the
        // dot is round whatever the pane does.
        const want = (ry * sy / sx).toFixed(3);
        if (el.getAttribute('rx') !== want) el.setAttribute('rx', want);
      });
      /* Glyphs stretch on the same axis the dots did. The design keeps its axis
         labels out of the pane entirely (an HTML column beside it), which is why
         the spec forbids <text> under preserveAspectRatio="none" outright; the repo
         draws them inside the SVG, so undo the stretch per label instead. Scaling
         about the label's own x leaves the anchor where it was for start AND middle,
         so nothing moves -- only the glyph aspect changes. */
      const k = sy / sx;
      svg.querySelectorAll('text[x]').forEach(el => {
        const x = parseFloat(el.getAttribute('x'));
        if (!Number.isFinite(x)) return;
        const want2 = Math.abs(k - 1) < 0.001 ? ''
          : `translate(${(x * (1 - k)).toFixed(3)} 0) scale(${k.toFixed(5)} 1)`;
        if ((el.getAttribute('transform') || '') === want2) return;
        if (want2) el.setAttribute('transform', want2);
        else el.removeAttribute('transform');
      });
    });
  };

  /* G3. Whether the two panes share one x axis, published on the section at RENDER
     time rather than on first hover. The stylesheet labels the series pane from this,
     and a label that only appears once you have already hovered answers a question
     after the reader has stopped asking it. */
  const publishAxisMode = () => {
    const section = document.querySelector('.market-view-section');
    if (!section) return;
    const others = [...section.querySelectorAll('svg')]
      .filter(sv => !sv.querySelector('.mv-mark'));
    const want = !others.length ? ''
      : others.every(sv => sv.getAttribute('data-xspan') === 'shared') ? 'shared' : 'own';
    if (section.getAttribute('data-xaxis') === want) return;
    if (want) section.setAttribute('data-xaxis', want);
    else section.removeAttribute('data-xaxis');
  };

  const XHAIR = 'mv2-xhair';

  const clearCrosshairs = () =>
    document.querySelectorAll('.' + XHAIR).forEach(n => n.remove());

  const drawCrosshair = (svg, x) => {
    if (!svg || !Number.isFinite(x)) return;
    const vb = (svg.getAttribute('viewBox') || '').trim().split(/\s+/);
    const height = Number(vb[3]);
    if (!Number.isFinite(height)) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('class', XHAIR);
    line.setAttribute('x1', x); line.setAttribute('x2', x);
    line.setAttribute('y1', 0); line.setAttribute('y2', height);
    svg.appendChild(line);
  };

  const showChartSlot = (mark, marks) => {
    const index = marks.indexOf(mark);
    if (index < 0) return;
    clearCrosshairs();
    const svgs = [...document.querySelectorAll('.market-view-section svg')];
    const priceSvg = mark.ownerSVGElement;
    drawCrosshair(priceSvg, parseFloat(mark.getAttribute('cx')));
    /* G3. Only a pane that DECLARED `data-xspan="shared"` is on the price chart's slot
       axis; there the same viewBox x is the same minute and the rule is drawn straight
       across both. A pane on its own axis gets NO synced rule at all — it hovers by
       itself — because lining up two panes that do not share a scale is the one thing
       this crosshair exists to prevent.

       The state is published on the section so the stylesheet can label the series pane
       as being on its own axis. A reader who sweeps the price chart and sees nothing
       move below deserves to be told why, rather than concluding the hover is broken. */
    publishAxisMode();
    const section = document.querySelector('.market-view-section');
    if (section && section.getAttribute('data-xaxis') === 'shared') {
      svgs.filter(sv => sv !== priceSvg)
          .forEach(sv => drawCrosshair(sv, parseFloat(mark.getAttribute('cx'))));
    }

    const readout = chartReadoutNode();
    if (!readout) return;
    const time = mark.getAttribute('data-time') || '';
    const word = mark.getAttribute('data-word') || '';
    const why = mark.getAttribute('data-reason') || '';
    readout.textContent = `slot ${index + 1} / ${marks.length}`
      + (time ? ` · ${time} ET` : '')
      + (word ? ` — ${word}` : '')
      + (why ? ` · ${why}` : '');
  };

  const CHART_HINT = 'hover a slot to read both charts at the same minute';

  const chartReadoutNode = () => {
    const plot = document.querySelector('.mv2-plot');
    if (!plot) return null;
    let el = document.querySelector('.mv2-chart-readout');
    if (!el) {
      el = document.createElement('div');
      el.className = 'mv2-chart-readout';
      el.textContent = CHART_HINT;
    }
    if (el.parentElement !== plot.parentElement || el.nextElementSibling !== plot) {
      plot.parentElement.insertBefore(el, plot);
    }
    return el;
  };

  const wireSlotHover = () => {
    slotReadoutNode();
    chartReadoutNode();
    if (slotHoverWired) return;
    const host = document.querySelector('.market-view-section');
    if (!host) return;
    slotHoverWired = true;
    host.addEventListener('mouseover', ev => {
      /* The price chart's marks are the same slots by another drawing, so they
         share this one handler rather than a second listener that could drift. */
      const mark = ev.target.closest && ev.target.closest('.mv-mark');
      if (mark && mark.ownerSVGElement) {
        const marks = [...mark.ownerSVGElement.querySelectorAll('.mv-mark')];
        try { showChartSlot(mark, marks); } catch (e) {}
        return;
      }
      const cell = ev.target.closest && ev.target.closest('.mv2-cell, .mv2-slot');
      if (!cell) return;
      const track = trackOf(cell);
      if (!track) return;
      const kids = [...track.querySelectorAll('.mv2-cell, .mv2-slot')];
      const i = kids.indexOf(cell);
      if (i >= 0) { try { showSlot(i, kids.length); } catch (e) {} }
    });
    /* Hover anywhere in either chart, not only on the 6.8px dot.

       The design puts a full-height invisible column over every slot, so the reader
       sweeps across the pane and both charts follow. Live only answered when the
       cursor landed exactly on a dot — measured at 10.9 x 6.8px, which is a target you
       have to aim at rather than sweep through.

       Done with a pointer-position lookup rather than by injecting hit rects: the
       charts are rebuilt every 8s, so injected nodes would need re-inserting on every
       pass, and this layer must never own something realtime.js redraws. The nearest
       slot is found from the marks' own cx values, which are the authority on where a
       slot sits — never from a fraction of the pane, which would drift the moment the
       window band stopped starting at the left edge. */
    host.addEventListener('mousemove', ev => {
      const svg = ev.target.closest && ev.target.closest('svg');
      if (!svg) return;
      const marks = [...document.querySelectorAll('.market-view-section .mv-mark')];
      if (marks.length < 2) return;
      const vb = (svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number);
      const box = svg.getBoundingClientRect();
      if (vb.length !== 4 || !box.width) return;
      const xvb = (ev.clientX - box.left) / box.width * vb[2];
      let best = -1, bestD = Infinity;
      marks.forEach((m, i) => {
        const d = Math.abs(parseFloat(m.getAttribute('cx')) - xvb);
        if (d < bestD) { bestD = d; best = i; }
      });
      if (best >= 0) { try { showChartSlot(marks[best], marks); } catch (e) {} }
    });

    host.addEventListener('mouseleave', () => {
      clearSlotHot();
      clearCrosshairs();
      const r = document.querySelector('.mv2-slot-readout');
      if (r) r.textContent = SLOT_HINT;
      const c = document.querySelector('.mv2-chart-readout');
      if (c) c.textContent = CHART_HINT;
    });
  };

  /* One control that closes the open job.
     realtime.js keeps a single `selectedJobId`, so at most one row is expanded
     at a time; the control clicks that row's own trigger rather than reaching
     into the script's state, which keeps the script the only writer of it.
     Shown only while something is open — a permanently visible "Collapse all"
     over an already-collapsed list is a button that does nothing. */
  const collapseJobControl = () => {
    const journal = document.getElementById('journal');
    if (!journal) return;
    const open = journal.querySelector('.job-trigger[aria-expanded="true"]');
    let el = document.querySelector('.journal-collapse-all');
    if (!open) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('button');
      el.type = 'button';
      el.className = 'journal-collapse-all';
      el.textContent = 'Collapse all';
      el.addEventListener('click', () => {
        const live = journal.querySelector('.job-trigger[aria-expanded="true"]');
        if (live) live.click();
      });
    }
    if (el.parentElement !== journal.parentElement || el.previousElementSibling !== journal) {
      journal.parentElement.insertBefore(el, journal.nextSibling);
    }
  };

  const foldEmptyHeader = () => {
    const host = document.querySelector('.overview-header');
    if (!host) return;
    const occupied = host.childElementCount > 0;
    if (host.hidden === occupied) host.hidden = !occupied;
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

  /* Group the workspace sections under the three bands the redesign names, so the
     column reads as Operations -> Book -> Market instead of one undifferentiated
     stack of eight.

     The source order interleaves the three: Market View and Calm sit between
     Track 1 Runtime and Regime Monitor, and Open Orders sits last. A band header
     placed over that order would name a group whose members are not under it, so
     the sections are reordered to match the heading that now covers them.

     Now Monitor and the figures row come down into the bands with everything
     else. They used to be lifted into `.overview-header` so Now Monitor and the
     journal began on the same line, but the design puts Now Monitor under
     Operations and the figures under Book, and a band that names four sections
     while two of them sit above it is not the design. The header shell is left
     empty by the move and is hidden rather than removed, so realtime.js keeps
     finding anything it looks up inside it.

     `#nextWindowBar` travels with Now Monitor. It is this layer's own addition
     and the design does not name it, so it is moved but NOT counted: the band
     reports sections, and the window bar is a strip.

     MOVES, not copies. Every id travels with its node and realtime.js resolves
     targets with getElementById, which does not care where they sit. */
  const UNCOUNTED = ['#nextWindowBar'];
  const GROUPS = [
    { key: 'ops', num: '01', name: 'Operations',
      note: 'What the system is doing, and what is still open',
      members: ['.now-monitor', '#nextWindowBar', '.open-issues-section',
                '.track1-section', '.orders-section'] },
    { key: 'book', num: '02', name: 'Book',
      note: 'Money, positions and the decision of record',
      members: ['#metrics', '.positions-section', '.decision-section'] },
    { key: 'market', num: '03', name: 'Market',
      note: 'Regime, the session Track 1 read, and the two-phase sleeve',
      members: ['.regime-section', '.market-view-section:not(#calmSection)', '#calmSection'] }
  ];

  const groupBands = () => {
    const col = document.querySelector('.primary-column');
    if (!col) return;

    /* Build the order we want, skipping any section this page does not carry, so
       a missing panel shortens a group instead of emptying the column. */
    const wanted = [];
    const bands = [];
    GROUPS.forEach(g => {
      /* Searched document-wide, not inside the column: Now Monitor and the
         figures row start life in `.overview-header`, so a column-scoped lookup
         would silently find neither and quietly build a three-section
         Operations band. */
      const found = [];
      g.members.forEach(sel => {
        const el = document.querySelector(sel);
        if (el && found.indexOf(el) === -1) found.push(el);
      });
      if (!found.length) return;

      let band = col.querySelector('.group-band[data-group="' + g.key + '"]');
      if (!band) {
        band = document.createElement('div');
        band.className = 'group-band';
        band.setAttribute('data-group', g.key);
        const num = document.createElement('b'); num.className = 'group-num';
        const name = document.createElement('strong'); name.className = 'group-name';
        const note = document.createElement('span'); note.className = 'group-note';
        const count = document.createElement('i'); count.className = 'group-count';
        num.textContent = g.num; name.textContent = g.name; note.textContent = g.note;
        band.append(num, name, note, count);
      }
      /* The count states what is actually under the band on this render, not what
         the design hoped for — a hidden Calm card must not be counted as shown,
         and the window bar is not a section. */
      const shown = found.filter(el =>
        !el.hidden && !UNCOUNTED.some(sel => el.matches(sel))).length;
      band.querySelector('.group-count').textContent =
        shown + (shown === 1 ? ' section' : ' sections');

      bands.push(band);
      wanted.push(band);
      found.forEach(el => wanted.push(el));
    });
    if (!wanted.length) return;

    /* `.primary-column` is a flex column and the base sheet gives several sections
       an explicit `order`: Open Issues -2, Open Positions -1, Today's Decision 1,
       Open Orders 2. Those rules beat document order, so moving the nodes alone
       changed nothing on screen — measured: all three bands rendered at full size
       and correct colour while the sections they name had floated away from them,
       Open Orders landing 3400px below its own heading.

       So the order is set here as well, inline, which outranks the sheet without
       an !important war. The nodes are still moved, so the document reads in the
       same sequence it paints and a screen reader is not given a third order.

       This overrides a deliberate rule — the sheet floats Open Issues and Open
       Positions to the top of the column. The redesign groups them instead, and
       grouping is the thing being implemented; the two cannot both hold.

       apply() runs every poll, so re-appending an already-correct column would
       move live nodes every 30s and reset scroll inside the panels. Both the
       order and the position are compared first, and an unchanged column returns. */
    let changed = false;
    wanted.forEach((el, i) => {
      const want = String(i + 1);
      if (el.style.order !== want) { el.style.order = want; changed = true; }
      if (col.children[i] !== el) changed = true;
    });
    if (!changed) return;

    wanted.forEach(el => col.appendChild(el));
    col.classList.add('has-group-bands');
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
    /* groupBands runs AFTER renderWindowBar, not before: the bar is created into
       `.overview-header` on first pass, so grouping first would move everything
       out, hide the shell, and then let the bar be built inside the hidden shell
       — added to the page and visible nowhere. */
    try { restructure(); wrapMarketViewCard(); decorateFacts(); renderWindowBar(); renderGaugeScale(); matchFigureLayout(); foldRestatedThreshold(); wireSlotHover(); undoPaneStretch(); publishAxisMode(); collapseJobControl(); groupBands(); foldEmptyHeader(); compactProtection(); dedupeJobEvidence(); dropRepeatedFacts();
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
        /* collapseJobControl lives here as well as in apply(): opening a job is a
           click, not a poll, and a control that only appears 30s later is not a
           control. Our node is a SIBLING of #journal, so inserting it cannot
           retrigger this observer. */
        try { dedupeJobEvidence(); dropRepeatedFacts(); collapseJobControl(); } catch (e) {}
      }).observe(journal, { childList: true, subtree: true });
    }
    /* The charts are rebuilt by realtime.js every 8s; this layer polls at 30s, so for
       most of any minute the dots were back to ovals. Observed on childList only —
       undoPaneStretch writes ATTRIBUTES, so it cannot retrigger this and loop. */
    const mv = document.querySelector('.market-view-section');
    if (mv) {
      new MutationObserver(() => { try { undoPaneStretch(); publishAxisMode(); } catch (e) {} })
        .observe(mv, { childList: true, subtree: true });
    }
    const prot = document.getElementById('metricStopsCovered');
    if (prot) {
      new MutationObserver(() => { try { compactProtection(); } catch (e) {} })
        .observe(prot, { childList: true, characterData: true, subtree: true });
    }
  };

  /* The dot correction depends on the pane's width, so it has to run again when
     that width changes. Debounced: a drag fires resize dozens of times a second
     and every pass walks every ellipse. */
  let _resizeT = null;
  window.addEventListener('resize', () => {
    clearTimeout(_resizeT);
    _resizeT = setTimeout(() => { try { undoPaneStretch(); } catch (e) {} }, 120);
  });

  const start = () => { load(); watch(); setInterval(load, POLL_MS); };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start)
    : start();
})();
