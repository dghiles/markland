"""Publish every *.md file in a directory as the principal owning a token.

Used to seed initial demo content. Idempotent in the sense of "safe to run
twice" — it doesn't dedupe; running twice publishes twice. Check the doc
list first if you want to avoid duplicates.

Usage:
    /app/.venv/bin/python scripts/admin/seed_demo_docs.py \\
        --token mk_usr_... \\
        --dir seed-content/agent \\
        --public

Run via:
    flyctl ssh console -a markland -C \\
        "/app/.venv/bin/python scripts/admin/seed_demo_docs.py \\
         --token mk_... --dir seed-content/agent --public"

The first H1 (`# Title`) of each markdown file becomes the doc title.
Falls back to "Untitled" if no H1 is present.

Prints one line per published doc:
    <filename>  <doc_id>  <share_url>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from markland.config import get_config
from markland.db import init_db
from markland.service import auth as auth_svc
from markland.service import docs as docs_svc


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-publish *.md from a dir.")
    parser.add_argument("--token", required=True, help="user or agent token")
    parser.add_argument("--dir", required=True, help="directory of *.md files")
    parser.add_argument(
        "--public", action="store_true", help="publish docs as public (default false)"
    )
    args = parser.parse_args()

    cfg = get_config()
    conn = init_db(cfg.db_path)

    principal = auth_svc.resolve_token(conn, args.token)
    if principal is None:
        print("error: token did not resolve to a principal", file=sys.stderr)
        return 1

    src_dir = Path(args.dir)
    if not src_dir.is_dir():
        print(f"error: not a directory: {src_dir}", file=sys.stderr)
        return 2

    md_files = sorted(src_dir.glob("*.md"))
    if not md_files:
        print(f"error: no *.md files in {src_dir}", file=sys.stderr)
        return 2

    print(f"# publishing as principal: {principal.principal_type}:{principal.principal_id}")
    print(f"# display_name: {principal.display_name}")
    print(f"# public: {args.public}")
    print(f"# files: {len(md_files)}")
    print()

    failures = 0
    for md in md_files:
        content = md.read_text(encoding="utf-8")
        try:
            result = docs_svc.publish(
                conn,
                base_url=cfg.base_url,
                principal=principal,
                content=content,
                public=args.public,
            )
        except Exception as exc:
            failures += 1
            print(f"FAIL  {md.name}  {exc}", file=sys.stderr)
            continue
        print(f"{md.name:<45}  {result['id']:<24}  {result['share_url']}")

    if failures:
        print(f"\n{failures} failure(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
