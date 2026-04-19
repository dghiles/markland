"""Automated end-to-end smoke test.

Starts the web server in a background thread, exercises all tool functions,
verifies the shared URL renders AND the landing + explore pages work.
"""

import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

os.environ["MARKLAND_DATA_DIR"] = str(_ROOT / ".smoke-data")
os.environ["MARKLAND_WEB_PORT"] = "8952"
os.environ["MARKLAND_BASE_URL"] = "http://127.0.0.1:8952"

shutil.rmtree(_ROOT / ".smoke-data", ignore_errors=True)

from markland.config import get_config, reset_config  # noqa: E402

reset_config()
config = get_config()

import uvicorn  # noqa: E402

from markland.db import init_db  # noqa: E402
from markland.tools.documents import (  # noqa: E402
    delete_doc,
    feature_doc,
    get_doc,
    list_docs,
    publish_doc,
    search_docs,
    set_visibility_doc,
    share_doc,
    update_doc,
)
from markland.web.app import create_app  # noqa: E402

db_conn = init_db(config.db_path)
app = create_app(db_conn)


def start_server():
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=config.web_port, log_level="warning")
    )
    server.run()


def fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def assert_ok(label: str, cond: bool, detail: str = ""):
    prefix = "PASS" if cond else "FAIL"
    print(f"[{prefix}] {label}{': ' + detail if detail else ''}")
    if not cond:
        raise SystemExit(1)


def main():
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(2.0)

    # Health
    code, body = fetch(f"{config.base_url}/health")
    assert_ok("health endpoint", code == 200 and '"ok"' in body)

    # Publish an unlisted doc (existing behavior)
    pub = publish_doc(db_conn, config.base_url, None, "# Private Smoke\n\nShh.")
    assert_ok("publish unlisted returns id", "id" in pub)
    assert_ok("publish unlisted defaults to is_public False", pub["is_public"] is False)
    doc_id = pub["id"]

    # Fetch the share URL
    code, body = fetch(pub["share_url"])
    assert_ok("share URL returns 200", code == 200)
    assert_ok("rendered HTML contains title", "Private Smoke" in body)

    # List / get / search / share / update / delete — smoke flow
    assert_ok("list returns one doc", len(list_docs(db_conn)) == 1)
    assert_ok("get returns content", "Shh" in get_doc(db_conn, doc_id).get("content", ""))
    assert_ok("search finds match", len(search_docs(db_conn, "Smoke")) == 1)
    assert_ok("share returns url", "share_url" in share_doc(db_conn, config.base_url, doc_id))
    updated = update_doc(db_conn, config.base_url, doc_id, content="# Updated Private\n\nChanged.")
    assert_ok("update succeeds", "error" not in updated)
    _, updated_body = fetch(pub["share_url"])
    assert_ok("updated content visible via URL", "Updated Private" in updated_body)

    # Landing should be empty (no public docs yet)
    code, landing_body = fetch(f"{config.base_url}/")
    assert_ok("landing returns 200", code == 200)
    assert_ok("landing shows empty featured", "Nothing yet." in landing_body)
    assert_ok("private doc hidden from landing", "Updated Private" not in landing_body)

    # Explore should be empty
    code, explore_body = fetch(f"{config.base_url}/explore")
    assert_ok("explore returns 200", code == 200)
    assert_ok("explore shows empty state", "Nothing here yet" in explore_body)

    # Now publish a public + featured doc
    public_pub = publish_doc(
        db_conn, config.base_url, "Published Smoke", "# Published Smoke\n\nSee me on the landing.", public=True
    )
    feat_result = feature_doc(db_conn, public_pub["id"], is_featured=True)
    assert_ok("feature tool succeeds", "error" not in feat_result and feat_result["is_featured"] is True)

    # Landing should now show the public doc with Pinned badge
    _, landing_body2 = fetch(f"{config.base_url}/")
    assert_ok("landing shows public featured title", "Published Smoke" in landing_body2)
    assert_ok("landing shows Pinned badge", "Pinned" in landing_body2)

    # Explore should show the public doc
    _, explore_body2 = fetch(f"{config.base_url}/explore")
    assert_ok("explore shows public doc", "Published Smoke" in explore_body2)

    # Search on explore
    _, search_body = fetch(f"{config.base_url}/explore?q=Published")
    assert_ok("explore search matches", "Published Smoke" in search_body)

    _, no_match_body = fetch(f"{config.base_url}/explore?q=zzznomatches")
    assert_ok("explore search empty-state on miss", "No docs matched" in no_match_body)

    # Visibility toggle: demote back to unlisted, confirm it disappears from explore
    demote = set_visibility_doc(db_conn, config.base_url, public_pub["id"], is_public=False)
    assert_ok("set_visibility demote succeeds", demote["is_public"] is False)
    _, explore_body3 = fetch(f"{config.base_url}/explore")
    assert_ok("demoted doc disappears from explore", "Published Smoke" not in explore_body3)

    # Cleanup
    delete_doc(db_conn, doc_id)
    delete_doc(db_conn, public_pub["id"])
    code, _ = fetch(pub["share_url"])
    assert_ok("deleted doc returns 404", code == 404)

    # --- Waitlist smoke ---
    import urllib.parse

    test_email = f"smoke+{int(time.time())}@example.com"
    data = urllib.parse.urlencode({"email": test_email, "source": "hero"}).encode()
    req = urllib.request.Request(
        f"{config.base_url}/api/waitlist",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(req, timeout=5)
        status = 200
        location = ""
    except urllib.error.HTTPError as e:
        status = e.code
        location = e.headers.get("Location", "")
    assert_ok("waitlist POST returns 303", status == 303, f"got {status}")
    assert_ok("waitlist POST redirects to signup=ok", location == "/?signup=ok", location)

    _, chip_body = fetch(f"{config.base_url}/?signup=ok")
    assert_ok("signup=ok renders success chip", "You&#39;re on the list" in chip_body or "You're on the list" in chip_body)

    shutil.rmtree(_ROOT / ".smoke-data", ignore_errors=True)

    print("\n[OK] All smoke tests passed.")


if __name__ == "__main__":
    main()
