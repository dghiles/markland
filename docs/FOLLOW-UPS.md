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
- **~~Signed-in nav banner missing on secondary pages~~** — Fixed 2026-05-01.
  Added `markland.web.render_helpers.render_with_nav(tpl, request, conn, *,
  base_url, secret, **ctx)` that auto-injects `signed_in_user`, `request`,
  and `canonical_host` (the three context kwargs every base.html render
  needs). Routed every base.html render in app.py + auth_routes.py +
  identity_routes.py + routes_agents.py + dashboard.py through it. Banner
  now shows on `/`, `/d/<token>`, `/explore`, `/quickstart`, `/about`,
  `/security`, `/privacy`, `/terms`, `/alternatives`, `/alternatives/<slug>`,
  `/verify_sent`, `/settings/tokens`, `/settings/agents`, and `/dashboard`.
  Plan: `docs/plans/2026-05-01-signed-in-banner-coverage-and-overflow.md`.
- **`view_document` cookie/Bearer split for owner controls** — the handler at
  `src/markland/web/app.py` renders the "Signed in as <email>" banner via
  `signed_in_user_ctx` (cookie-aware) but still computes `is_owner` from
  `request.state.principal` (Bearer-only). A cookie-auth'd owner viewing their
  own private doc sees the banner but is treated as anonymous for owner
  controls (share dialog, etc.). Fix: replace the `getattr(request.state,
  "principal", None)` with a fallback to `session_principal(...)` like
  `/explore` does. Pre-existing inconsistency that became visibly weird now
  that the banner advertises the signed-in state.
- **~~`settings_tokens.html` logout fetch is wasteful but not broken~~** —
  Fixed 2026-05-01 by deleting the bespoke fetch entirely. The page now
  extends `base.html` and uses the shared `_signed_in_nav.html` partial's
  form-POST sign-out. Plan: `docs/plans/2026-05-01-signed-in-banner-coverage-
  and-overflow.md`.
- **Add `needs: [test]` gate to `.github/workflows/deploy.yml`** — currently
  `needs: []` (intentionally), so a red test run does not block deploy. For a
  1-machine app with no automatic rollback (we use `--strategy immediate`,
  see next entry), this is the cheapest meaningful safety net. Wire the test
  workflow into the deploy job's `needs:` so a failing pytest blocks
  auto-deploy. Manual `workflow_dispatch` runs can keep the existing path or
  add a `if: github.event_name == 'workflow_dispatch'` bypass.
- **Add `paths-ignore` to `.github/workflows/deploy.yml`** — every push to
  `main` triggers a deploy, including docs-only commits. The deploy itself
  is harmless (machine rolls in place with byte-equivalent image) but
  wasteful (Fly build + push + machine restart for no behavior change).
  Add `paths-ignore: ['docs/**', '*.md', '.github/**']` to the `push:`
  trigger so docs-only changes skip the deploy. Test workflow should
  still run (test.yml has its own trigger).
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

## Metrics

- **`first_mcp_call` event persistence** — `service/metrics.py::emit_first_time`
  writes to stdout only. The new `markland_admin_metrics` tool returns
  `first_mcp_call: null` because there is no DB row to count. Either add a
  `metrics_events (event, principal_id, created_at)` table written alongside
  stdout, or parse `flyctl logs` from the tool. Cheapest path is the table; one
  `CREATE TABLE` + one `INSERT` per emit.
- **Token-create reveal disappears before user can copy** —
  `/settings/tokens` shows the freshly minted plaintext (`mk_usr_...`) only
  briefly after `POST /api/tokens` returns, then the value vanishes from the
  DOM. Plaintext is one-shot (server stores only the hash), so once dismissed
  the user must revoke and recreate. Caught during the cutover (2026-05-01)
  generating a smoke token — the workaround was to read the value off the
  user's screen before it vanished. Fix: persist the reveal until an explicit
  "Copy"/"I've saved it" action; consider an explicit clipboard-copy button
  with a confirmed state. Touch points: `src/markland/web/identity_routes.py`
  (`POST /api/tokens` JSON shape), the `/settings/tokens` template, and any
  client-side JS that consumes the response.

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
- **`scripts/hosted_smoke.sh` whoami grep mismatches escaped JSON** —
  the final assertion does `grep -q '"principal_type"'` on the body of the
  `markland_whoami` tool/call, but the MCP envelope wraps the principal
  JSON inside a `text` content block, so the on-wire form is
  `\"principal_type\"` (backslash-escaped) which the literal grep doesn't
  match. The whoami call itself returns 200 with the right principal —
  this is purely a test-script false-positive. Caught in cutover Task
  12.1 (2026-05-01). Fix: extract the inner content text (e.g. with `jq
  -r '.result.content[0].text'`) and grep that, or relax the pattern to
  match either form.

## Deploy / operations (post-2026-04-20 first-deploy)

- **~~Cut over to `markland.dev`.~~** Done 2026-05-01 via `docs/plans/2026-04-29-cutover-to-markland-dev.md` (all 12 tasks). Dedicated Fly IPv4 (149.248.214.141) + v6, Porkbun-direct A/AAAA at apex (Porkbun API), Fly TLS cert issued, `MARKLAND_BASE_URL` flipped, machine rolled in place, hosted_smoke green on cutover-relevant checks, `FlyDevRedirectMiddleware` 301s the old fly.dev origin (`076a3c2`), GSC domain property + sitemap.xml submitted. Residual smoke-script grep false-positive on whoami logged separately below.
- **~~Resend signup + DNS verification.~~** Done 2026-05-01. SPF/DKIM/DMARC/return-path records at the `markland.dev` zone, `RESEND_API_KEY` + `RESEND_FROM_EMAIL` set on Fly, end-to-end magic-link verified by signing in at `https://markland.dev/login` and clicking through to `/verify`. Evidence: `cutover-evidence/09-resend/done.log` (gitignored).
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
- **~~Submit `/sitemap.xml` to Google Search Console.~~** Done 2026-05-01.
  Domain property `markland.dev` added in GSC, verified via DNS TXT
  (`google-site-verification=...` added at apex via Porkbun API),
  `sitemap.xml` submitted (13 URLs all `https://markland.dev/*`,
  2026-05-01 lastmod). Evidence: `cutover-evidence/11-*.log` (gitignored).

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

