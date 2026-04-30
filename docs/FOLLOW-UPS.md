# Follow-Ups

Consolidated from `docs/execution/log.md` — every item flagged as "follow-up",
"known security finding", or open deviation during plan execution that was not
already shipped. None of these block the v1 launch; they are the first items a
post-launch sprint should pick up.

## Security

- **Magic-link single-use enforcement** — `src/markland/service/magic_link.py`
  uses `URLSafeTimedSerializer` (stateless), so a token can be replayed any
  number of times within its 15-minute window. Today this is honestly
  disclosed on `/security` ("a captured link can be used within its 15-minute
  window before it expires"), but the long-term fix is to track consumed
  JTIs in a `magic_link_consumed (jti, email, consumed_at)` table and reject
  reused tokens at `read_magic_link_token`. Update `/security` wording back
  to "single-use" once enforced.
- **Agent token leak via query string** — `src/markland/web/routes_agents.py:224`
  redirects to `/settings/agents?new_token={plaintext}` after minting, exposing
  the token to browser history, Referer headers, and proxy access logs. Replace
  with a signed one-shot flash cookie or a server-side one-shot cache keyed off
  the session. Audit `src/markland/web/identity_routes.py` for the same pattern
  on user-token minting.
- **Unescaped `user_code` in device login redirect** —
  `src/markland/web/device_routes.py:230` interpolates `user_code` directly.
  Wrap with `urllib.parse.quote(...)` defensively so a malformed code can't
  corrupt the redirect target.
- **Per-IP rate limit on device confirm** — `POST /device/confirm` and `POST
  /api/auth/device-authorize` in `src/markland/web/device_routes.py` are not
  rate-limited, leaving the 38-bit `user_code` open to online guessing. Add a
  per-IP sliding-window limiter mirroring the one already on `device-start`
  (10 req/min).
- **Lock / expire device row after N failed confirms** — same file, same
  threat model; after (e.g.) 5 failed confirms for a given `device_code`, mark
  it expired so the next poll returns `expired_token` regardless of TTL.
- **`grant_by_principal_id` defensive check** — `src/markland/service/grants.py`
  (helper used by `accept_invite`) does not assert `principal_type ∈
  {'user','agent'}` or that agent ids start with `agt_`. All current callers
  are correct; add a runtime check for defensive hardening.
- **Append-only audit enforcement** — `audit_log` rows are written by
  `service/audit.py::record()` but there is no DB-level protection against
  UPDATE/DELETE. Either add a BEFORE UPDATE/DELETE SQLite trigger that raises,
  or document the trust boundary (operator with DB access is trusted).
- **`/admin/audit` duplicates bearer resolution** — the handler in
  `src/markland/web/app.py` re-runs `resolve_token` because `PrincipalMiddleware`
  only gates `/mcp`. Widen the middleware's protected-prefix set to cover
  `/admin/*` so principal resolution happens in one place.
- **No CSRF protection on save routes** — `POST /d/{t}/fork`,
  `POST /d/{t}/bookmark`, and `DELETE /d/{t}/bookmark` in
  `src/markland/web/save_routes.py` accept plain form/fetch submissions with
  `SameSite=Lax` session cookies. Lax does not cover every cross-site POST in
  every browser/version, so a third-party page could trigger a spurious fork
  (full doc copy + revision) or bookmark on a logged-in viewer. Consistent with
  existing posture (no CSRF tokens anywhere in the app) but these are the first
  user-authored mutating POST endpoints. Add a per-form CSRF token wired off the
  session, or switch to a custom-header check (e.g. `X-Markland-Origin`) that
  cross-site forms can't set.

## Correctness / tech debt

- **Middleware ordering inconsistency** — `src/markland/web/app.py` adds
  `PrincipalMiddleware` first and `RateLimitMiddleware` second; Starlette reverses
  add-order so `RateLimitMiddleware` is outermost and compensates via
  `_resolve_principal_lazy()` in `src/markland/web/rate_limit_middleware.py`.
  Either swap add-order so `PrincipalMiddleware` runs first for real and drop
  the lazy resolve, or document the current arrangement as intentional in
  `docs/ARCHITECTURE.md`.
- **Duplicate `_InlineDispatcher` shim** — defined in both
  `src/markland/web/app.py:80` and `src/markland/service/grants.py:264`. Extract
  a single factory (e.g. `service/email_dispatcher.py::inline_dispatcher(client)`)
  and import from both sites. Migrate the back-compat `email_client=` kwarg in
  `grants.grant()` and `invite_routes._notify_creator` to dispatchers and delete
  the shim entirely once all callers are switched.
- **`datetime.utcnow()` deprecation** — used in `src/markland/web/app.py`
  (`_minutes_ago`) and likely elsewhere. Replace with `datetime.now(UTC)` and
  drop the naive-datetime path.
- **`service.docs.get()` dual signature** — still dispatches on positional type
  (`str` → Document form, `Principal` → legacy dict form) in
  `src/markland/service/docs.py`. Rename the Document form to
  `get_document(...)` (or similar), migrate remaining dict-form callers in
  `src/markland/server.py::_get` and HTTP handlers, then delete the legacy
  path.
- **`EmailDispatcher.stop()` misleading comment** —
  `src/markland/service/email_dispatcher.py` says "drains" but actually drops
  queued items on shutdown. Either add a bounded drain with timeout or update
  the comment to match behaviour.
- **Widen `EmailDispatcher` retry trigger** — currently only `EmailSendError`
  triggers retry; `src/markland/service/email_dispatcher.py` should catch any
  non-`CancelledError` exception so a transient Resend SDK bug doesn't drop the
  message silently.
- **Bounded queue size for DoS defense** — `asyncio.Queue()` in
  `email_dispatcher.py` has no `maxsize`. Set one (e.g. 1000) and log-drop on
  overflow.
- **Back-compat `email_client=` kwargs** — `create_app`, `grants.grant()`,
  `invite_routes._notify_creator` all still accept the pre-Plan-7 `email_client=`
  parameter. Remove once all internal callers use `dispatcher=`.
- **Signed-in nav banner missing on secondary pages** — `_signed_in_nav.html`
  renders on `/`, `/d/<token>`, and `/explore` because those handlers pass
  `signed_in_user_ctx(...)` into the render context. Other base.html-extending
  pages (`/quickstart`, `/about`, `/security`, `/competitors/...`, etc.) inherit
  the include but their handlers don't pass the dict, so the banner silently
  disappears when a signed-in user navigates to them via the top-nav and
  reappears when they come back. Either factor a tiny `_render_with_nav(...)`
  helper that injects `signed_in_user` for every base.html render, or extract a
  middleware that hangs `signed_in_user` off `request.state` so all templates
  can pull from there. Cosmetic but visible.
- **`view_document` cookie/Bearer split for owner controls** — the handler at
  `src/markland/web/app.py` renders the "Signed in as <email>" banner via
  `signed_in_user_ctx` (cookie-aware) but still computes `is_owner` from
  `request.state.principal` (Bearer-only). A cookie-auth'd owner viewing their
  own private doc sees the banner but is treated as anonymous for owner
  controls (share dialog, etc.). Fix: replace the `getattr(request.state,
  "principal", None)` with a fallback to `session_principal(...)` like
  `/explore` does. Pre-existing inconsistency that became visibly weird now
  that the banner advertises the signed-in state.
- **`settings_tokens.html` logout fetch is wasteful but not broken** —
  `templates/settings_tokens.html:79` calls `fetch('/api/auth/logout',
  {method:'POST'})` with no `Accept` header. After PR #28 the server returns
  a 303 redirect to `/` for non-JSON callers, so fetch transparently follows
  the redirect → fetches `/` → JS discards the body and forces
  `location.href = '/login'`. Cookie deletion happens correctly but the
  browser does an unnecessary GET. Add `headers: {'Accept':
  'application/json'}` (or `redirect: 'manual'`) to the fetch.
- **Add `needs: [test]` gate to `.github/workflows/deploy.yml`** — currently
  `needs: []` (intentionally), so a red test run does not block deploy. For a
  1-machine app with no automatic rollback (we use `--strategy immediate`,
  see next entry), this is the cheapest meaningful safety net. Wire the test
  workflow into the deploy job's `needs:` so a failing pytest blocks
  auto-deploy. Manual `workflow_dispatch` runs can keep the existing path or
  add a `if: github.event_name == 'workflow_dispatch'` bypass.
- **Revisit `--strategy immediate` once Fly's launch-group lookup bug is
  fixed** — we use `--strategy immediate` to work around the orphan-machine
  bug (default `rolling` strategy hits a flyctl lookup path that creates
  sibling machines instead of updating in place). `immediate` skips per-
  instance health-check waits, so a bad image ships as "deploy succeeded"
  even when the new machine fails `/health` — there is no automatic rollback
  to the previous image. Once Fly fixes the underlying bug (file a support
  ticket, or test new flyctl versions), revert to `--strategy rolling` to
  get back automatic stop-on-unhealthy semantics. Detection: orphan in
  `flyctl machine list -a markland` returns → revert and reopen
  `docs/plans/2026-04-29-fix-fly-deploy-launch-group.md`.

## Test coverage

- **EmailDispatcher lifespan test** — `tests/test_email_integration.py`
  currently exercises the dispatcher by direct `start()`/`stop()` calls. Add a
  test that enters `TestClient(app)` as a context manager and asserts the
  real `EmailDispatcher` (not `_InlineDispatcher`) is attached at
  `app.state.email_dispatcher` and receives an enqueued email end-to-end.
- **Concurrent-update threading test** — `tests/test_conflict_e2e.py` runs
  sequentially; add a test that uses `threading` + two SQLite connections to
  drive an actual race against `docs.update()`'s `BEGIN IMMEDIATE` and verify
  the loser cleanly sees `ConflictError`.
- **Non-viewer presence list test** — add `GET /api/docs/{id}/presence` test
  in `tests/test_presence_api.py` asserting a 404 (deny-as-NotFound) when the
  caller has neither view grant nor ownership.
- **Device confirm rate-limit test** — once the per-IP limiter on
  `POST /device/confirm` lands, add a test driving 11 confirms from the same IP
  in a minute and asserting the 11th returns 429 with `Retry-After`.

## Deploy / operations (post-2026-04-20 first-deploy)

- **Cut over to `markland.dev`.** Domain registered 2026-04-29 at Porkbun
  (Porkbun nameservers active: `curitiba|fortaleza|maceio|salvador.ns.porkbun.com`).
  App still runs at `markland.fly.dev`. Cutover: (1) `flyctl ips allocate-v4 --yes`
  (~$2/mo) + `flyctl ips allocate-v6`, (2) **DNS strategy decision** — either
  (a) Porkbun DNS direct: add `A` / `AAAA` records on Porkbun pointing at the
  Fly IPs (simplest, no proxy/CDN), or (b) switch nameservers to Cloudflare
  and add `A`/`AAAA` DNS-only / grey-cloud (preserves the option to enable
  proxy/CDN/WAF later), (3) `flyctl certs add markland.dev` and poll until
  Issued, (4) edit `fly.toml` `MARKLAND_BASE_URL` from `https://markland.fly.dev`
  to `https://markland.dev`, `flyctl deploy`, (5) re-run `scripts/hosted_smoke.sh`
  with `MARKLAND_URL=https://markland.dev`, (6) add a 301 redirect from
  `markland.fly.dev` → `markland.dev` (or document it as an SEO follow-up).
- **Resend signup + DNS verification.** Blocks magic-link email on the live
  deploy. Steps in `docs/runbooks/first-deploy.md` §2. Until this lands,
  sign-ins require extracting the magic-link URL from `flyctl logs`.
- **~~Cloudflare R2 bucket + Litestream keys.~~** Done 2026-04-28. R2 bucket
  `markland-db`, scoped Account API token, secrets `LITESTREAM_BUCKET` /
  `LITESTREAM_ENDPOINT` / `LITESTREAM_ACCESS_KEY_ID` /
  `LITESTREAM_SECRET_ACCESS_KEY` set on Fly. Litestream replicating to R2
  every 10s with 6h snapshot interval and 72h retention.
- **~~CI auto-deploy.~~** Wired but **disabled** until the launch-group bug
  below is fixed. `.github/workflows/deploy.yml` only runs on
  `workflow_dispatch` for now; deploys are operator-driven via
  `flyctl machine update`.
- **~~Fly launch-group registration is broken.~~** Worked around 2026-04-30
  with `flyctl deploy --strategy immediate`, which uses a different deploy
  code path inside flyctl that correctly finds the existing machine.
  Verified by running `flyctl deploy --remote-only --strategy immediate`
  against prod and observing machine `185191df264378` update in place with
  no orphan sibling. CI auto-deploy re-enabled in PR #31 with the same
  flag. The underlying flyctl bug is not fixed (default `rolling` strategy
  still produces orphans), so see the related entry above about reverting
  to `rolling` once Fly fixes it. Full diagnostic with `flyctl scale count`
  and metadata-edit attempts: `docs/plans/2026-04-29-fix-fly-deploy-launch-
  group.md`.
- **Submit `/sitemap.xml` to Google Search Console** — deferred until the
  canonical domain is live. Submitting under `markland.fly.dev` now would
  burn the property on a host we plan to abandon, and Search Console does
  not migrate indexed URLs cleanly across properties. After the
  `markland.dev` cutover (see first item of this section), verify
  `https://markland.dev/sitemap.xml` loads, then add the domain property in
  GSC, verify via DNS TXT, and submit the sitemap there.

## Docs

- **`/d/{token}` presence disclosure** — document (or reconsider) that
  share-token holders see active reader display names with no per-user view
  check beyond token possession. Call it out in `docs/ARCHITECTURE.md` or the
  spec, whichever is closer.
- **Middleware lazy-resolve architecture** — if we keep the current
  `RateLimitMiddleware`-outside ordering, document it next to the
  `PrincipalMiddleware` section in `docs/ARCHITECTURE.md` so a future reader
  doesn't "fix" it.
- **`Organization.founder.name` real name vs handle** — JSON-LD currently
  emits `{"@type":"Person","name":"@dghiles","url":"https://github.com/dghiles"}`
  in `src/markland/web/templates/_seo_meta.html`. Schema.org doesn't reject
  this but Google's rich-card UI treats `name` as a personal name, not a
  social handle. When ready to publish a real name, swap to
  `{"name":"<real name>","alternateName":"@dghiles","url":...}` and mirror
  the byline in `base.html` footer.

