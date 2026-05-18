"""Pull a window of Umami analytics for the markland site.

Reads UMAMI_API_KEY from the prod env (set as a Fly secret), so this MUST
run inside the Fly machine — never paste the key into a local shell.

Usage (always over fly ssh, not locally):
    flyctl ssh console -a markland -C \\
        "/app/.venv/bin/python scripts/admin/umami_summary.py --days 14"

Prints aggregate stats + top URLs / referrers / browsers / countries for the
window. Intentionally JSON-shaped so the output can be piped into jq or saved
for cross-referencing with /admin/metrics.

Reference: see docs/runbooks/metrics-review.md for the full soak-window flow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

WEBSITE_ID = "79f6978f-5ade-4019-bee4-46da56d1dd25"
HOST = "https://api.umami.is"


def _get(path: str, params: dict, key: str) -> object:
    url = f"{HOST}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"x-umami-api-key": key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=14, help="lookback window")
    parser.add_argument("--limit", type=int, default=15, help="rows per metric")
    args = parser.parse_args()

    key = os.environ.get("UMAMI_API_KEY")
    if not key:
        print("error: UMAMI_API_KEY not set — run this over fly ssh", file=sys.stderr)
        return 2

    end = int(time.time() * 1000)
    start = end - args.days * 24 * 3600 * 1000
    base = {"startAt": start, "endAt": end}

    out = {
        "window_days": args.days,
        "window_ms": [start, end],
        "stats": _get(f"/v1/websites/{WEBSITE_ID}/stats", base, key),
        "pageviews_by_day": _get(
            f"/v1/websites/{WEBSITE_ID}/pageviews",
            {**base, "unit": "day", "timezone": "UTC"},
            key,
        ),
        "top_urls": _get(
            f"/v1/websites/{WEBSITE_ID}/metrics",
            {**base, "type": "url", "limit": args.limit},
            key,
        ),
        "top_referrers": _get(
            f"/v1/websites/{WEBSITE_ID}/metrics",
            {**base, "type": "referrer", "limit": args.limit},
            key,
        ),
        "top_browsers": _get(
            f"/v1/websites/{WEBSITE_ID}/metrics",
            {**base, "type": "browser", "limit": args.limit},
            key,
        ),
        "top_countries": _get(
            f"/v1/websites/{WEBSITE_ID}/metrics",
            {**base, "type": "country", "limit": args.limit},
            key,
        ),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
