"""Settings pages. Only /settings/notifications is implemented at launch — stub."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_NOTIFICATIONS_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Notification settings — Markland</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f6f6f4; color: #1a1a1a; margin: 0; padding: 48px 16px; }
  main { max-width: 560px; margin: 0 auto; background: #fff;
          border: 1px solid #e5e5e2; border-radius: 8px; padding: 32px; }
  h1 { margin: 0 0 12px 0; font-size: 22px; }
  p  { line-height: 1.55; color: #3a3a38; }
  .muted { color: #6b6b68; font-size: 13px; }
  a { color: #1a1a1a; }
</style>
</head>
<body>
<main>
  <h1>Notification settings</h1>
  <p><strong>Coming soon.</strong> Per-user notification preferences are not available at launch.</p>
  <p>For now, Markland sends transactional email only: magic-link login, grant created,
     grant level changed, agent-grant to the agent's owner, and invite accepted. These
     are required for the product to function and cannot be disabled.</p>
  <p class="muted">If you're receiving mail you didn't expect, reply to this email or
     contact support and we'll investigate.</p>
  <p><a href="/">&larr; Back to Markland</a></p>
</main>
</body>
</html>
"""


@router.get("/settings/notifications", response_class=HTMLResponse)
def notifications_settings() -> HTMLResponse:
    return HTMLResponse(_NOTIFICATIONS_PAGE)
