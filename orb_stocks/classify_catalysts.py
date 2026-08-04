"""
classify_catalysts.py — Step 2: point-in-time filter + LLM catalyst classification
(EXPERIMENTAL harness, orb_stocks/)

For each of the 148 primary SHORT events (orb_event_index.parquet filtered to
in_primary_151=True AND gap_suspect=False), this:

  1. POINT-IN-TIME FILTER — selects only news an analyst could have seen before
     the 09:31-09:45 opening range formed:
       include published_utc in  (prev_trading_day 16:00 ET , entry_day 09:29:59 ET]
     i.e. same-day pre-market PLUS prior-trading-day after-hours/overnight.
     (prev_trading_day from a real trading calendar, so Fri-close -> Mon-open and
      holidays are handled correctly.) Everything at/after 09:30 ET is look-ahead.
  2. Passes ALL qualifying articles (most recent first) to the classifier.
  3. Calls claude-sonnet-4-6 with the exact prompt template (TEXT ONLY — no
     gap_pct / price / return data ever enters the prompt, by design).
  4. Caches each event's result JSON (idempotent — a re-run does not re-bill).
  5. Merges results into orb_event_catalyst.parquet and prints the distribution
     summary + LLM call count / token cost.

Auth: ANTHROPIC_API_KEY env var, or ANTHROPIC_API_KEY in config_private.py.
Model: claude-sonnet-4-6 (as specified).

NOT in scope (Step 3): bootstrap / statistical validation.

Run:
    cd d:\\raits
    pip install anthropic                # one-time
    setx ANTHROPIC_API_KEY "sk-ant-..."  # or add ANTHROPIC_API_KEY to config_private.py
    python orb_stocks\\classify_catalysts.py            # real run (calls the API)
    python orb_stocks\\classify_catalysts.py --dry-run  # offline preview: filter +
                                                        # prompts + cost estimate, no API
"""

from __future__ import annotations

import os
import sys
import json
import time
import pickle
import argparse
import collections
from bisect import bisect_left
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from raits.data.raits_news import build_news_index

EASTERN = ZoneInfo("America/New_York")
CACHE_DIR = os.path.join(REPO, "raits", "data", "cache")
NEWS_DIR = os.path.join(CACHE_DIR, "news")
EVENT_INDEX = os.path.join(NEWS_DIR, "orb_event_index.parquet")
CATALYST_OUT = os.path.join(NEWS_DIR, "orb_event_catalyst.parquet")
RESULT_CACHE = os.path.join(NEWS_DIR, "catalyst")          # per-event result JSON
CALENDAR_JSON = os.path.join(NEWS_DIR, "_trading_calendar.json")
FIVE_MIN_PKL = os.path.join(CACHE_DIR, "window_debug_5min.pkl")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
PREMARKET_CUTOFF = dtime(9, 29, 59)   # last visible instant before the OR forms
PREV_CLOSE = dtime(16, 0, 0)          # prior-session close; overnight news starts here

# ── Exact prompt template (use verbatim) ──────────────────────────────────
SYSTEM_PROMPT = (
    "You are a financial-news catalyst classifier for offline backtesting research\n"
    "on US large/mega-cap stocks. Do NOT use hindsight of what the stock did after\n"
    "publication — judge only the text itself, as an analyst reading it in real\n"
    "time would, with zero foreknowledge of outcome.\n\n"
    "Output strict JSON, no prose outside the JSON object:\n"
    "{\n"
    '  "catalyst_type": one of ["earnings", "guidance", "fda_regulatory", "ma_deal",\n'
    '    "analyst_action", "macro_or_sector_wide", "legal_regulatory_action",\n'
    '    "management_change", "product_launch", "rumor_unconfirmed", "other",\n'
    '    "no_clear_catalyst"],\n'
    '  "is_idiosyncratic": true | false,\n'
    '  "catalyst_substance": one of ["hard_fact", "guidance_or_estimate",\n'
    '    "rumor_or_speculation", "opinion_or_analyst_view"],\n'
    '  "magnitude_signal": one of ["large", "moderate", "small", "unclear"],\n'
    '  "confidence": 0.0-1.0,\n'
    '  "notes": "<one sentence, factual, no price prediction language>"\n'
    "}\n"
    "Rules:\n"
    '- If is_idiosyncratic is false, catalyst_type MUST be "macro_or_sector_wide".\n'
    "- Never output trading recommendations or direction predictions.\n"
    "- If no article clearly explains why the stock might be moving, use\n"
    '  "no_clear_catalyst" / magnitude_signal "unclear".'
)

USER_TEMPLATE = (
    "Ticker: {ticker}   Date: {date}   Entry direction: SHORT (gap-down breakdown)\n"
    "Articles (most recent first, published_utc shown, pre-market-visible only):\n"
    "{headlines_block}"
)

# Enforced response schema (guarantees parseable JSON matching the template).
CATALYST_TYPES = ["earnings", "guidance", "fda_regulatory", "ma_deal",
                  "analyst_action", "macro_or_sector_wide", "legal_regulatory_action",
                  "management_change", "product_launch", "rumor_unconfirmed", "other",
                  "no_clear_catalyst"]
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "catalyst_type": {"type": "string", "enum": CATALYST_TYPES},
        "is_idiosyncratic": {"type": "boolean"},
        "catalyst_substance": {"type": "string", "enum": [
            "hard_fact", "guidance_or_estimate", "rumor_or_speculation",
            "opinion_or_analyst_view"]},
        "magnitude_signal": {"type": "string",
                             "enum": ["large", "moderate", "small", "unclear"]},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["catalyst_type", "is_idiosyncratic", "catalyst_substance",
                 "magnitude_signal", "confidence", "notes"],
    "additionalProperties": False,
}


# ── Auth ──────────────────────────────────────────────────────────────────
def load_anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    cp = os.path.join(REPO, "config_private.py")
    if os.path.exists(cp):
        import importlib.util
        spec = importlib.util.spec_from_file_location("config_private", cp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = getattr(mod, "ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit(
            "FATAL: ANTHROPIC_API_KEY not set (env var or config_private.py).\n"
            "Set it, then re-run. (Polygon key is separate and unrelated.)"
        )
    return key


# ── Trading calendar (for prev-trading-day) ───────────────────────────────
def load_trading_calendar() -> list:
    """Sorted list of ISO trading dates; built once from 5min data, then cached."""
    if os.path.exists(CALENDAR_JSON):
        with open(CALENDAR_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    if not os.path.exists(FIVE_MIN_PKL):
        sys.exit(f"FATAL: need {FIVE_MIN_PKL} to build the trading calendar once.")
    print("Building trading calendar from 5min data (one-time, ~15s)...")
    with open(FIVE_MIN_PKL, "rb") as f:
        d = pickle.load(f)
    # SPY trades every session; use it as the market calendar.
    ref = "SPY" if "SPY" in d else next(iter(d))
    idx = pd.to_datetime(d[ref].index)
    dates = sorted({ts.normalize().date().isoformat() for ts in idx})
    with open(CALENDAR_JSON, "w", encoding="utf-8") as f:
        json.dump(dates, f)
    print(f"  calendar cached: {len(dates)} trading days ({dates[0]}..{dates[-1]})")
    return dates


def prev_trading_day(cal: list, day_iso: str) -> str | None:
    """Most recent trading date strictly before day_iso."""
    i = bisect_left(cal, day_iso)
    return cal[i - 1] if i > 0 else None


def _to_et(published_utc: str) -> datetime | None:
    if not published_utc:
        return None
    try:
        dt = datetime.fromisoformat(published_utc.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(EASTERN).replace(tzinfo=None)
    except Exception:
        return None


# ── Point-in-time filter ──────────────────────────────────────────────────
def qualifying_articles(idx: pd.DataFrame, ticker: str, day, prev_day_iso):
    """Articles for (ticker, day) inside (prev_close, entry-day 09:29:59] ET,
    most recent first. prev_day_iso may be None (then no overnight lower bound)."""
    if ticker not in idx.index.get_level_values("ticker"):
        return []
    sub = idx.loc[ticker].reset_index()
    d = pd.Timestamp(day).date()
    end = datetime.combine(d, PREMARKET_CUTOFF)
    if prev_day_iso:
        start = datetime.combine(pd.Timestamp(prev_day_iso).date(), PREV_CLOSE)
    else:
        start = None
    out = []
    for _, row in sub.iterrows():
        et = _to_et(row["published_utc"])
        if et is None or et > end:
            continue
        if start is not None and et <= start:
            continue
        title = row.get("title")
        body = row.get("body")
        out.append({
            "published_utc": row["published_utc"],
            "et": et,
            "title": ("" if pd.isna(title) else str(title)).strip(),
            "body": ("" if pd.isna(body) else str(body)).strip(),
        })
    out.sort(key=lambda a: a["et"], reverse=True)   # most recent first
    return out


def build_headlines_block(arts: list) -> str:
    parts = []
    for a in arts:
        block = f"[{a['published_utc']}] {a['title']}"
        if a["body"]:
            block += f"\n    {a['body']}"
        parts.append(block)
    return "\n".join(parts)


# ── Classifier call ───────────────────────────────────────────────────────
def classify(client, ticker: str, date_str: str, headlines_block: str):
    user = USER_TEMPLATE.format(ticker=ticker, date=date_str,
                                headlines_block=headlines_block)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    parsed = json.loads(text)
    usage = resp.usage
    return parsed, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }


def result_path(ticker: str, date_str: str) -> str:
    return os.path.join(RESULT_CACHE, f"{ticker}_{date_str}.json")


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="offline: filter + prompts + cost estimate, no API calls")
    args = ap.parse_args()

    os.makedirs(RESULT_CACHE, exist_ok=True)

    df = pd.read_parquet(EVENT_INDEX)
    pop = df[(df["in_primary_151"]) & (~df["gap_suspect"])].copy()
    events = [(tk, pd.Timestamp(dt).date().isoformat())
              for (tk, dt) in pop.index]
    tickers = sorted({tk for tk, _ in events})

    print("=" * 78)
    print(f"ORB STOCKS — STEP 2: catalyst classification  ({'DRY-RUN' if args.dry_run else 'LIVE'})")
    print(f"Population: {len(events)} SHORT events | model: {MODEL}")
    print("=" * 78)

    idx = build_news_index(CACHE_DIR, tickers=tickers, dates=None)
    cal = load_trading_calendar()

    client = None
    if not args.dry_run:
        try:
            import anthropic
        except ImportError:
            sys.exit("FATAL: `pip install anthropic` first (or use --dry-run).")
        client = anthropic.Anthropic(api_key=load_anthropic_key())

    records = []
    n_zero = n_called = n_cached = 0
    est_in = est_out = tok_in = tok_out = 0

    for ticker, date_str in sorted(events):
        pd_iso = prev_trading_day(cal, date_str)
        arts = qualifying_articles(idx, ticker, date_str, pd_iso)
        n_used = len(arts)

        base = {"ticker": ticker, "date": date_str,
                "n_articles_used": n_used,
                "has_no_qualifying_articles": (n_used == 0),
                "prev_trading_day": pd_iso}

        if n_used == 0:
            # No point-in-time news -> no API call; naturally "no_clear_catalyst".
            n_zero += 1
            records.append({**base, "catalyst_type": "no_clear_catalyst",
                            "is_idiosyncratic": False,
                            "catalyst_substance": "opinion_or_analyst_view",
                            "magnitude_signal": "unclear", "confidence": 0.0,
                            "notes": "No pre-market-visible article passed the "
                                     "point-in-time filter."})
            continue

        headlines_block = build_headlines_block(arts)

        if args.dry_run:
            # rough token estimate: ~4 chars/token
            chars = len(SYSTEM_PROMPT) + len(USER_TEMPLATE) + len(headlines_block) + 40
            est_in += chars // 4
            est_out += 150
            records.append({**base, "catalyst_type": None, "is_idiosyncratic": None,
                            "catalyst_substance": None, "magnitude_signal": None,
                            "confidence": None, "notes": None})
            continue

        # ── LIVE: idempotent cache ──
        rp = result_path(ticker, date_str)
        if os.path.exists(rp):
            with open(rp, "r", encoding="utf-8") as f:
                cached = json.load(f)
            n_cached += 1
            records.append({**base, **cached})
            continue

        for attempt in range(4):
            try:
                parsed, usage = classify(client, ticker, date_str, headlines_block)
                break
            except Exception as exc:
                if attempt == 3:
                    raise
                wait = 2 ** attempt
                print(f"  [retry {attempt+1}] {ticker} {date_str}: {type(exc).__name__} — {wait}s")
                time.sleep(wait)

        tok_in += usage["input_tokens"]
        tok_out += usage["output_tokens"]
        n_called += 1
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        records.append({**base, **parsed})
        if n_called % 20 == 0:
            print(f"  ... {n_called} classified")

    out = (pd.DataFrame(records)
           .assign(date=lambda x: pd.to_datetime(x["date"]))
           .set_index(["ticker", "date"]).sort_index())

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print("STEP 2 SUMMARY")
    print("=" * 78)
    print(f"Events: {len(events)} | with >=1 qualifying article: {len(events)-n_zero} "
          f"| ZERO qualifying (flagged, no call): {n_zero}")

    if args.dry_run:
        in_cost = est_in / 1e6 * 3.0      # sonnet-4-6: $3 / 1M input
        out_cost = est_out / 1e6 * 15.0   # $15 / 1M output
        print(f"\nDRY-RUN cost ESTIMATE (rough, ~4 chars/token):")
        print(f"  LLM calls that WOULD be made : {len(events)-n_zero}")
        print(f"  est input tokens  : ~{est_in:,}")
        print(f"  est output tokens : ~{est_out:,}")
        print(f"  est total cost    : ~${in_cost + out_cost:.3f} "
              f"(in ~${in_cost:.3f} + out ~${out_cost:.3f})")
        print("\n  (No API calls made. Run without --dry-run to classify + merge.)")
        # article-count distribution for sanity
        dist = collections.Counter(r["n_articles_used"] for r in records)
        print(f"\n  qualifying-article count per event (n_used -> #events):")
        for k in sorted(dist):
            print(f"    {k:>3}: {dist[k]}")
        print("=" * 78)
        return

    out.to_parquet(CATALYST_OUT)
    in_cost = tok_in / 1e6 * 3.0
    out_cost = tok_out / 1e6 * 15.0
    print(f"LLM calls this run: {n_called} (+{n_cached} from cache) | "
          f"tokens in={tok_in:,} out={tok_out:,} | cost=${in_cost+out_cost:.3f}")

    def dist(col):
        return dict(collections.Counter(r[col] for r in records))
    print(f"\ncatalyst_type      : {dist('catalyst_type')}")
    print(f"is_idiosyncratic   : {dist('is_idiosyncratic')}")
    print(f"catalyst_substance : {dist('catalyst_substance')}")
    print(f"magnitude_signal   : {dist('magnitude_signal')}")
    confs = [r["confidence"] for r in records if r["confidence"] is not None]
    print(f"confidence         : mean={sum(confs)/len(confs):.2f} "
          f"min={min(confs):.2f} max={max(confs):.2f}")

    ncc = sum(1 for r in records if r["catalyst_type"] == "no_clear_catalyst")
    print(f"\nFLAGS:")
    print(f"  no_clear_catalyst : {ncc}/{len(events)} ({ncc/len(events)*100:.0f}%)"
          f"  [{n_zero} of these are zero-article events]")
    if ncc / len(events) > 0.5:
        print("  ** >50% no_clear_catalyst — point-in-time filter may be too strict,")
        print("     or coverage genuinely thin. Investigate before Step 3.")
    lowconf = sum(1 for c in confs if c < 0.3)
    if lowconf > len(confs) * 0.3:
        print(f"  ** {lowconf}/{len(confs)} calls confidence<0.3 — classifier unsure.")
    print(f"\nWritten: {CATALYST_OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
