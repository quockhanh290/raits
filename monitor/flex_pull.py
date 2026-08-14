"""Pull an IBKR Flex report into a local monitoring input folder.

Read-only: this script calls IBKR Flex Web Service and writes the downloaded
report under monitor/inputs/ibkr_flex/. It does not import or mutate the runner.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
LEGACY_BASE_URL = "https://www.interactivebrokers.com/Universal/servlet"
DEFAULT_OUT_DIR = Path("monitor") / "inputs" / "ibkr_flex"
USER_AGENT = "Java/1.8"
_NO_PROXY = False
_DEBUG = False
_BASE_URL = BASE_URL
_LEGACY = False


def _env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing env var {name}")
    return value


def _redact(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    pairs = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        pairs.append((key, "***" if key.lower() in {"t", "q"} else value))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(pairs)))


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if _DEBUG:
        print(f"GET {_redact(url)}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if _NO_PROXY else None
    open_url = opener.open if opener else urllib.request.urlopen
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with open_url(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if _DEBUG:
                print(f"attempt {attempt} failed: {exc}")
            time.sleep(float(attempt))
    proxies = urllib.request.getproxies()
    proxy_note = "proxy disabled by --no-proxy" if _NO_PROXY else f"detected proxies={proxies or '{}'}"
    raise SystemExit(f"Request failed: {last_error}; {proxy_note}")


def _url(path: str, params: dict[str, str]) -> str:
    if _LEGACY:
        endpoint = "FlexStatementService.SendRequest" if path == "/SendRequest" else "FlexStatementService.GetStatement"
        return f"{_BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
    return f"{_BASE_URL}{path}?{urllib.parse.urlencode(params)}"


def _text(root: ET.Element, tag: str) -> str | None:
    for elem in root.iter():
        if elem.tag.lower().split("}")[-1] == tag.lower():
            return (elem.text or "").strip()
    return None


def _send_request(token: str, query_id: str, from_date: str | None,
                  to_date: str | None) -> tuple[str, str | None]:
    params = {"t": token, "q": query_id, "v": "3"}
    if from_date:
        params["fd"] = from_date
    if to_date:
        params["td"] = to_date
    raw = _get(_url("/SendRequest", params))
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SystemExit(f"SendRequest returned non-XML response: {raw[:300]!r}") from exc

    status = _text(root, "Status")
    if status != "Success":
        code = _text(root, "ErrorCode") or _text(root, "Code") or "--"
        message = _text(root, "ErrorMessage") or _text(root, "Message") or raw.decode("utf-8", errors="replace")
        raise SystemExit(f"SendRequest failed: status={status} code={code} message={message}")
    ref = _text(root, "ReferenceCode")
    if not ref:
        raise SystemExit("SendRequest succeeded but did not return ReferenceCode")
    return ref, _text(root, "Url") or _text(root, "url")


def _get_statement(token: str, reference_code: str, response_url: str | None) -> bytes:
    base = response_url or _url("/GetStatement", {})
    if base.endswith("?"):
        base = base[:-1]
    params = {"t": token, "q": reference_code, "v": "3"}
    sep = "&" if "?" in base else "?"
    return _get(f"{base}{sep}{urllib.parse.urlencode(params)}")


def _extension(payload: bytes) -> str:
    prefix = payload[:200].lstrip().lower()
    if prefix.startswith(b"<?xml") or prefix.startswith(b"<flex"):
        return ".xml"
    if b"transaction history" in prefix or b"," in prefix:
        return ".csv"
    return ".txt"


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    global USER_AGENT, _BASE_URL, _DEBUG, _LEGACY, _NO_PROXY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", help="YYYYMMDD override, max 365 days")
    parser.add_argument("--to-date", help="YYYYMMDD override, max 365 days")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--prefix", default="flex")
    parser.add_argument("--sleep", type=float, default=2.0,
                        help="seconds to wait between SendRequest and GetStatement")
    parser.add_argument("--no-proxy", action="store_true",
                        help="bypass Windows/env proxy settings for the Flex request")
    parser.add_argument("--debug", action="store_true",
                        help="print redacted request URL and retry diagnostics")
    parser.add_argument("--legacy-url", action="store_true",
                        help="use legacy www.interactivebrokers.com Universal servlet endpoints")
    parser.add_argument("--user-agent", default=USER_AGENT,
                        help="User-Agent header value; IBKR examples use Java/1.8 or Python/3.x")
    args = parser.parse_args()
    _NO_PROXY = bool(args.no_proxy)
    _DEBUG = bool(args.debug)
    _LEGACY = bool(args.legacy_url)
    _BASE_URL = LEGACY_BASE_URL if _LEGACY else BASE_URL
    USER_AGENT = args.user_agent

    token = _env_required("IBKR_FLEX_TOKEN")
    query_id = _env_required("IBKR_FLEX_QUERY_ID")

    ref, response_url = _send_request(token, query_id, args.from_date, args.to_date)
    if args.sleep > 0:
        time.sleep(args.sleep)
    payload = _get_statement(token, ref, response_url)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = _extension(payload)
    name_parts = [args.prefix, _stamp(), f"q{query_id}", f"ref{ref}"]
    if args.from_date or args.to_date:
        name_parts.append(f"{args.from_date or 'start'}-{args.to_date or 'end'}")
    out_path = out_dir / ("_".join(name_parts) + suffix)
    out_path.write_bytes(payload)
    print(f"saved {out_path} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
