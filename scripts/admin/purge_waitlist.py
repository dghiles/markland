"""Delete waitlist rows belonging to one email domain (spam cleanup).

Waitlist signups are unauthenticated, so the form collects bot bursts —
a run of random local parts on a single throwaway domain. This removes
them so `waitlist_total` in /admin/metrics reflects real interest.

Usage:
    /app/.venv/bin/python scripts/admin/purge_waitlist.py <domain> [--dry-run]

Run via:
    flyctl ssh console -a markland -C \
        "/app/.venv/bin/python scripts/admin/purge_waitlist.py spam.invalid --dry-run"

Always --dry-run first: it prints the exact rows that would go, and the
delete has no undo. Matching is on the domain after the `@` only, so a
subdomain is a different domain and is left alone.
"""

from __future__ import annotations

import argparse

from markland.config import get_config
from markland.db import delete_waitlist_by_domain, init_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", help="email domain to purge, e.g. spam.invalid")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    domain = args.domain.strip().lstrip("@")
    conn = init_db(get_config().db_path)

    if args.dry_run:
        rows = conn.execute(
            "SELECT email, created_at, source FROM waitlist "
            "WHERE lower(substr(email, instr(email, '@') + 1)) = lower(?) "
            "ORDER BY email",
            (domain,),
        ).fetchall()
        print(f"dry-run: {len(rows)} row(s) match @{domain}; no writes")
        for email, created_at, source in rows:
            print(f"  {email}  {created_at}  {source}")
        return 0

    deleted = delete_waitlist_by_domain(conn, domain)
    print(f"deleted {len(deleted)} row(s) matching @{domain}")
    for email in deleted:
        print(f"  {email}")
    remaining = conn.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    print(f"waitlist_total now {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
