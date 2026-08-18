/* ─────────────────────────────────────────────────────────────────────────────
   preview-states.js — mock-state viewer, DESIGN USE ONLY

   Why this exists: the operations page exists to serve BAD DAYS, but today's live
   data shows exactly one fair-weather state (OK, one known debt, one position). A
   design validated only against that will break on the day it matters most.

   This file is NOT loaded by the operations page. It exists only in preview.html.

   Two rules:
   1. NEVER fabricate a payload. Take the REAL response and mutate only the fields
      that decide the state. A hand-written payload drifts from the real API shape,
      and the design would then be validated against something that does not exist.
   2. Every scenario carries a PREDICTED OUTCOME (see `expect`), so the viewer can
      be checked to actually produce that state — a viewer that can never go red is
      as useless as a test that can never go red.

   Field -> state map, read from realtime.js itself (not inferred):
     FAIL  schedule.open_incidents / incidents non-empty
           schedule.unexplained_overdue non-empty
           schedule.evidence.severity === 'incident'
           runner.freshness in {late, stale, missing}
           runner.payload.meta.operational_status.breaker.level !== 'OK'
           runner.payload.meta.operational_status.regime_unreliable === true
           any API endpoint failing (dead source)
     WARN  schedule.evidence_available === false, or broker not verifiable
   ───────────────────────────────────────────────────────────────────────────── */
(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const active = params.get('state') || 'ok';

  /* Visual-direction probes. Loaded on top of next.css so a skin only ever adds
     overrides — the structure being compared stays identical between them.
     Design-time only; the operations page never loads these. */
  const SKINS = {
    base: 'Base',
    a: 'A · refined terminal',
    b: 'B · modern console',
    c: 'C · bento',
    d: 'D · HUD',
    e: 'E · closed palette',
  };
  const skin = SKINS[params.get('skin')] ? params.get('skin') : 'base';
  /* Fills the placeholder <link id="skinLink"> that sits last in <head>. Creating
     and appending a link from here instead would land it BEFORE the static
     stylesheets, since appendChild only sees the head parsed so far. */
  if (skin !== 'base') {
    const setSkin = () => {
      const link = document.getElementById('skinLink');
      if (link) link.href = `/dash/realtime-next/skin-${skin}.css`;
    };
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', setSkin, { once: true })
      : setSkin();
  }

  const opsOf = (runner) => {
    runner.payload = runner.payload || {};
    runner.payload.meta = runner.payload.meta || {};
    runner.payload.meta.operational_status = runner.payload.meta.operational_status || {};
    return runner.payload.meta.operational_status;
  };

  /* Shape taken from the backend itself (schedule_status.py), not invented:
       state     in not_observed | skipped | failed | executed
       reason    in unknown | mutex | preflight | misfire | exception | none
       severity  in watch | incident | expected | none
       lifecycle in open | recovered      <- the field that says "has it recovered"
       recovered_by = slot_id of the FIRST CLEAN slot after it, same stream
     The first version invented `reason: 'ib_gateway_disconnected'` and omitted
     lifecycle / recovered_by entirely — i.e. designing against a shape that does
     not exist. */
  const incident = (i, { recoveredBy = null } = {}) => {
    const mm = (i * 5).toString().padStart(2, '0');
    return {
      slot_id: `NKD_NIGHT_02${mm}`,
      slot_at: `2026-08-16T06:${mm}:00Z`,
      state: 'failed',
      reason: 'exception',
      severity: 'incident',
      detail: `run_nkd_night exited with code 1 (slot 02:${mm} ET)`,
      lifecycle: recoveredBy ? 'recovered' : 'open',
      recovered_by: recoveredBy,
    };
  };

  /* Each scenario: label, note, mutation, and the verdict state it EXPECTS. */
  const SCENARIOS = {
    ok: {
      label: 'Nominal',
      note: 'Live data, nothing altered.',
      expect: 'ok',
      apply: (url, data) => data,
    },
    warn: {
      label: 'Evidence missing',
      note: 'Schedule cannot be verified — not broken, but not safe to call healthy.',
      expect: 'watch',
      apply: (url, data) => {
        if (url.includes('/schedule-status')) data.evidence_available = false;
        return data;
      },
    },
    stale: {
      label: 'Runner stale',
      note: 'Runner snapshot is old — every number derived from it is suspect.',
      expect: 'bad',
      apply: (url, data) => {
        if (url.includes('/runner-state')) { data.freshness = 'stale'; data.age_seconds = 9400; }
        return data;
      },
    },
    incidents: {
      label: '6 NKD slots failed',
      note: 'Six consecutive NKD night slots failed and none has recovered — a real past case.',
      expect: 'bad',
      apply: (url, data) => {
        if (url.includes('/schedule-status')) {
          data.incidents = Array.from({ length: 6 }, (_, i) => incident(i + 1));
          data.open_incidents = data.incidents.filter(x => x.lifecycle === 'open');
          data.evidence = { ...(data.evidence || {}), severity: 'incident', state: 'failed',
            reason: 'exception', detail: 'Sáu slot liên tiếp không chạy.' };
        }
        return data;
      },
    },
    recovered: {
      label: '6 failed, recovered',
      note: 'Six incidents still on the day record, but none still open. '
          + 'Whether the design can tell these two apart is the real test.',
      expect: 'ok',
      apply: (url, data) => {
        if (url.includes('/schedule-status')) {
          // Same rule as the backend: the FIRST clean slot afterwards on the same
          // stream is what "recovered" means — not the most recent one.
          data.incidents = Array.from({ length: 6 },
            (_, i) => incident(i + 1, { recoveredBy: 'NKD_NIGHT_0230' }));
          data.open_incidents = data.incidents.filter(x => x.lifecycle === 'open');
        }
        return data;
      },
    },
    breaker: {
      label: 'Risk breaker HALT',
      note: 'Breaker tripped — the system has stopped itself.',
      expect: 'bad',
      apply: (url, data) => {
        if (url.includes('/runner-state')) opsOf(data).breaker = { level: 'HALT', reason: 'daily loss -4%' };
        return data;
      },
    },
    blocked: {
      label: 'Entries blocked',
      note: 'SPY too old, so the guard blocks entries; exits still run. The page used to stay silent about this.',
      expect: 'bad',
      apply: (url, data) => {
        if (url.includes('/runner-state')) opsOf(data).regime_unreliable = true;
        return data;
      },
    },
    dead: {
      label: 'Data source down',
      note: 'Broker endpoint is dead — the page must say it does NOT KNOW, never guess.',
      expect: 'bad',
      apply: null,          // handled separately: make the request fail outright
      failUrls: ['/api/v1/broker'],
    },
  };

  /* Typeface probes. Self-hosted, so switching costs no external request. Applied
     by overriding --mono, which every rule resolves through. */
  const FONTS = {
    jetbrains: ['JetBrains',  '"JetBrains Mono"'],
    cascadia:  ['Cascadia',   '"Cascadia Mono"'],
    ibm:       ['IBM Plex',   '"IBM Plex Mono"'],
    roboto:    ['Roboto',     '"Roboto Mono"'],
    space:     ['Space',      '"Space Mono"'],
    azeret:    ['Azeret',     '"Azeret Mono"'],
    redhat:    ['Red Hat',    '"Red Hat Mono"'],
    spline:    ['Spline Sans','"Spline Sans Mono"'],
    intel:     ['Intel One',  '"Intel One Mono"'],
    sometype:  ['Sometype',   '"Sometype Mono"'],
    kode:      ['Kode',       '"Kode Mono"'],
    martian:   ['Martian',    '"Martian Mono"'],
    geist:     ['Geist',      '"Geist Mono"'],
    fragment:  ['Fragment',   '"Fragment Mono"'],
    sourcecode:['Source Code','"Source Code Pro"'],
  };
  const font = FONTS[params.get('font')] ? params.get('font') : 'jetbrains';
  /* Set as an INLINE style on the root element, not as an injected <style>.
     A <style> appended from a head script lands BEFORE the static stylesheets —
     appendChild only sees the head parsed so far — so its `:root{--mono:…}` loses
     to skin-b's identical selector on load order. That is the same trap the skin
     <link> hit earlier in this file; an inline style outranks every stylesheet
     and so cannot be beaten by ordering.

     Only --mono is overridden. It used to set --sans and --font-ui to the same
     stack as well, which suited skin B — that skin deliberately runs one family
     — but it silently flattened every other skin to mono too, including E,
     whose whole type system is a sans for language paired with a mono for
     figures. A switcher meant to probe ONE variable was quietly deciding the
     design of another.

     Skins that want a single family say so themselves: skin B declares
     `--sans: var(--mono)`, which resolves against this inline value and follows
     the switcher without the switcher having to know about it. */
  {
    const applyFont = () => {
      const stack = `${FONTS[font][1]}, "Cascadia Mono", Consolas, monospace`;
      document.documentElement.style.setProperty('--mono', stack);
    };
    applyFont();
    document.addEventListener('DOMContentLoaded', applyFont, { once: true });
  }

  const scenario = SCENARIOS[active] || SCENARIOS.ok;
  const realFetch = window.fetch.bind(window);

  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (scenario.failUrls && scenario.failUrls.some(u => url.includes(u))) {
      throw new TypeError(`[preview] simulated dead source: ${url}`);
    }
    const response = await realFetch(input, init);
    if (!scenario.apply || !url.includes('/api/')) return response;
    let data;
    try { data = await response.clone().json(); } catch (e) { return response; }
    const mutated = scenario.apply(url, data);
    return new Response(JSON.stringify(mutated), {
      status: 200, headers: { 'content-type': 'application/json' },
    });
  };

  /* Warning banner. This page must NEVER be mistaken for live data — the same
     failure family earlier audits caught (stale data displayed as "fresh"). So it
     is loud, sticky, and cannot be dismissed. */
  const mountBanner = () => {
    const bar = document.createElement('div');
    bar.id = 'previewBanner';
    bar.innerHTML =
      `<b>MOCK DATA — DESIGN PREVIEW, NOT LIVE</b>` +
      `<span>scenario: <b>${scenario.label}</b> · expects: <b>${scenario.expect.toUpperCase()}</b> · ${scenario.note}</span>` +
      `<nav>${Object.entries(SCENARIOS).map(([k, s]) =>
        `<a href="?state=${k}&skin=${skin}&font=${font}"${k === active ? ' aria-current="page"' : ''}>${s.label}</a>`).join('')}</nav>` +
      `<nav class="skin-nav">${Object.entries(SKINS).map(([k, label]) =>
        `<a href="?state=${active}&skin=${k}&font=${font}"${k === skin ? ' aria-current="page"' : ''}>${label}</a>`).join('')}</nav>` +
      `<nav class="skin-nav font-nav">${Object.entries(FONTS).map(([k, [label]]) =>
        `<a href="?state=${active}&skin=${skin}&font=${k}"${k === font ? ' aria-current="page"' : ''}>${label}</a>`).join('')}</nav>`;
    document.body.prepend(bar);
    document.documentElement.dataset.preview = active;
    document.documentElement.dataset.skin = skin;
  };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', mountBanner)
    : mountBanner();

  /* Exposes the running scenario's expectation to external checks. */
  window.__preview = { active, skin, expect: scenario.expect,
                       all: Object.keys(SCENARIOS), skins: Object.keys(SKINS) };
})();
