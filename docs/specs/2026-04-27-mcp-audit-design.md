# MCP Audit & Test Harness Design

**Status:** approved 2026-04-27 via brainstorming session.
**Successor of:** `docs/specs/2026-04-19-multi-agent-auth-design.md` (which defines
the current MCP surface). This spec governs the *redesign* of that surface.

## 1. Purpose

The Markland MCP server ships with 19 tools that accreted across 10
implementation plans rather than being designed as a coherent surface. This
project audits the existing surface, lands a deliberate v1.0 (17 tools after
folding, plus 5 new = 22), and builds a dual-layer test harness that gives
the codebase a regression net during the audit and a fast feedback loop
afterward.

Out of scope for this spec: new product features (comments, sections,
revisions UI), performance work, infrastructure changes.

The audit *does* promote a small set of existing HTTP-only behaviors to MCP
where they fill obvious gaps in the surface — see §8.5 axis 5. Anything not
listed there is out of scope.

## 2. Goals

1. **Coherent MCP surface** — naming, return shapes, error model, granularity,
   pagination, and idempotency consistent across all tools.
2. **Discoverability** — every tool's docstring and schema is good enough that
   an LLM client can pick the right tool and call it correctly without
   out-of-band docs.
3. **Test harness** — pytest fixture exposing a single `harness.call(...)` API
   over both direct (in-process handler) and HTTP (JSON-RPC over `/mcp/`)
   backends, so the same test exercises either layer.
4. **Behavior baseline** — per-tool JSON snapshots capture every tool's success
   and error scenarios, so audit-driven changes are intentional and unintended
   regressions fail CI.
5. **Moderate-policy deprecations** — old tool names and shapes survive
   alongside new ones for one release; behavior parity is tested.

## 3. Non-goals

- Real-time / CRDT editing.
- Comments, threads, or section-level surfaces.
- Performance benchmarks.
- Backwards compatibility beyond a single deprecation window.
- Changes to the service layer (`src/markland/service/`) beyond what the audit
  requires at the MCP boundary.

## 4. Architecture

Three artefacts:

1. **`tests/_mcp_harness.py`** — pure test helper, dual backends.
2. **`tests/fixtures/mcp_baseline/<tool_name>.json`** — one snapshot file per
   tool, version-controlled.
3. **This spec** — authoritative target surface; codebase converges to it.

Implementation lives in `src/markland/server.py` and `src/markland/tools/`.
Service layer should not change for the audit.

```
tests/
├── _mcp_harness.py            harness module (MCPHarness, Caller, Response)
├── conftest.py                fixtures (mcp, mcp_http)
├── test_mcp_harness.py        Layer A — tests of the harness itself
├── test_mcp_baseline.py       Layer B — snapshot suite, all current tools
├── test_audit_naming.py       Layer C — per-axis audit tests
├── test_audit_return_envelopes.py
├── test_audit_error_model.py
├── test_audit_granularity.py
├── test_audit_missing.py
├── test_audit_docstrings.py
├── test_audit_pagination.py
├── test_audit_idempotency.py
├── test_audit_deprecations.py
└── fixtures/
    └── mcp_baseline/
        ├── markland_publish.json
        ├── markland_get.json
        ├── ...                one per tool
```

## 5. Harness — public API

### 5.1 Construction

```python
@pytest.fixture
def mcp(tmp_path) -> MCPHarness:
    return MCPHarness.create(tmp_path, mode="direct")  # default

@pytest.fixture
def mcp_http(tmp_path) -> MCPHarness:
    return MCPHarness.create(tmp_path, mode="http")
```

`MCPHarness.create(tmp_path, *, mode)` initializes a fresh SQLite tmp file via
`init_db`, builds a FastMCP via `build_mcp(...)`, and (for `mode="http"`)
mounts the FastAPI app and enters a `TestClient` context manager so the app
lifespan runs.

The harness installs a **capturing email dispatcher** by default (records sends
to an in-memory list, never hits Resend) and raises rate-limit defaults to
10000/min so tests don't trip the limiter incidentally. Specific tests can
override these via fixture params.

### 5.2 Principal seeding

| Method | Behavior |
|---|---|
| `harness.as_user(email=..., is_admin=False, fresh=False)` | Seeds user row + mints `mk_usr_…`. Caches by email; `fresh=True` mints a new token. |
| `harness.as_agent(owner_email=..., display_name=..., fresh=False)` | Seeds owning user (if needed) + agent row + mints `mk_agt_…`. |
| `harness.as_admin()` | Convenience: `as_user(email="admin@x", is_admin=True)`. |
| `harness.anon()` | Returns a `Caller` with no principal / no bearer. |
| `harness.db` | Raw `sqlite3.Connection` for direct setup/assertions. |
| `harness.emails_sent_to(email_or_agent_id)` | Returns captured email payloads. |

### 5.3 Caller

```python
class Caller:
    principal: Principal | None
    principal_id: str | None
    token: str | None  # bearer for HTTP mode

    def call(self, tool: str, **kwargs) -> Any:
        """Happy path. Returns result on success; raises MCPCallError on error."""
    def call_raw(self, tool: str, **kwargs) -> Response:
        """Returns a Response wrapper; never raises for protocol-level errors."""
```

### 5.4 Response wrapper

```python
@dataclass
class Response:
    ok: bool
    value: dict | list | None      # decoded payload on success
    error_code: str | None          # closed set; see §7
    error_data: dict                # structured error context (default {})
    raw: Any                        # original return value or exception

    def assert_error(self, code: str, **expected_data) -> None: ...
    def assert_ok(self) -> None: ...
```

`error_code` values are drawn from a closed set of seven codes (§7). The
wrapper's normalization table absorbs today's mixed shapes and shrinks as the
audit progresses.

### 5.5 Snapshot helper

```python
class MCPHarness:
    def snapshot(self, tool: str, scenario: str, payload: Any) -> None:
        """Compare against tests/fixtures/mcp_baseline/<tool>.json[scenario].
        With --snapshot-update, write the current value instead.
        Raises AssertionError on mismatch with a useful diff."""
```

Snapshot payloads are passed through `as_envelope(...)` — a helper that
replaces volatile fields (timestamps, IDs, share tokens) with placeholders
(`"<ID>"`, `"<TIMESTAMP>"`, `"<SHARE_TOKEN>"`) so snapshots are stable.

### 5.6 Caching & isolation

- Caller cache is per-harness, so per-test.
- Two `harness.as_user("alice@x")` calls return the same `Caller`.
- `fresh=True` mints a new token but reuses the same user.
- HTTP mode: each `Caller` gets its own MCP session (separate `initialize`,
  separate `Mcp-Session-Id`). Switching principals mid-test costs ~5ms once
  per principal but matches real-world client behavior.

## 6. Data flow

### 6.1 Direct mode

```
test → caller.call("markland_publish", content="# hi")
     → harness.handlers["markland_publish"](_Ctx(p), content="# hi")
        ├─ runs service.docs.publish(...)
        └─ returns dict | raises Exception
     → harness normalizes to Response (see §6.3)
     → if ok: return value;  if error: raise MCPCallError(response)
```

### 6.2 HTTP mode

```
test → caller.call("markland_publish", content="# hi")
     → POST /mcp/  Authorization: Bearer mk_usr_…
                   Mcp-Session-Id: <id>
                   body: tools/call name="markland_publish" args={...}
     → TestClient → PrincipalMiddleware → RateLimit → FastMCP → handler
     → JSON-RPC response
     → harness normalizes to Response (see §6.3)
     → return / raise as in direct mode
```

### 6.3 Normalization

The harness owns a small translation table that maps today's mixed conventions
to the seven canonical error codes:

| Input | → | error_code |
|---|---|---|
| `{"error": "not_found"}` | → | `not_found` |
| `{"error": "forbidden"}` | → | `forbidden` |
| `{"error": "invalid_argument", "reason": ...}` | → | `invalid_argument` |
| `ToolError("conflict: …", data={...})` | → | `conflict` |
| `PermissionError(...)` | → | `forbidden` |
| `ValueError(...)` (in lookup contexts) | → | `not_found` |
| HTTP 401 | → | `unauthenticated` |
| HTTP 403 | → | `forbidden` |
| HTTP 429 | → | `rate_limited` |
| Anything else | → | `internal_error` |

After axis 3 (error model) lands, the table collapses to: HTTP error → code,
body → data; success → `ok=True`. The shrinking of this table is itself a
signal the audit is working.

## 7. Error model (target — axis 3)

The audit converges every tool on a closed set of seven error codes:

| code | When | `error_data` |
|---|---|---|
| `unauthenticated` | No bearer / unknown bearer. | `{}` |
| `forbidden` | Authenticated but not allowed. Admin-only tool by non-admin. | `{}` |
| `not_found` | Doc/grant/invite doesn't exist, or "deny-as-not-found" hides existence per spec §12.5. | `{}` |
| `conflict` | Optimistic-concurrency mismatch on `markland_update`. | `{current_version, current_content, current_title}` |
| `invalid_argument` | Bad input — unknown grant level, bad status string, malformed agent id. | `{reason}` |
| `rate_limited` | HTTP 429. | `{retry_after}` |
| `internal_error` | Unexpected exception, malformed JSON-RPC. | `{raw}` |

**Wire representation.** Tool-level errors travel as `ToolError` with
`err.data = {"code": ..., **error_data}`. Transport-level errors that occur
before a tool runs (HTTP 401 / 403 / 429) never reach the FastMCP layer; the
harness synthesizes the matching `Response` from the HTTP status (and
`Retry-After` header for 429). Either way, tests see the same `Response`
shape.

**Idempotency policy** (axis 8). Default: idempotent-success-when-defensible.
Calling a mutating tool with arguments that match current state is a no-op,
returns success. Exceptions:
- `markland_delete` of non-existent doc → `not_found` (the deletion intent is
  load-bearing; silently succeeding hides bugs).
- `markland_update` with stale `if_version` → `conflict` (point of optimistic
  concurrency).

Each tool's idempotency contract is stated in its docstring.

## 8. Audit axes (target surface)

The following changes ship behind the moderate-policy deprecation window: old
name/shape lives alongside new for one release, marked `Deprecated.` in its
docstring with the removal date.

### 8.0 Per-tool disposition

The 19 current tools and 5 new tools, with their target-surface disposition.
This is the canonical work-unit list that the implementation plan will
enumerate against.

| Current tool | Disposition | Target name | Notes |
|---|---|---|---|
| `markland_whoami` | keep | `markland_whoami` | docstring rewrite |
| `markland_publish` | keep | `markland_publish` | returns `doc_envelope`; not idempotent |
| `markland_list` | keep | `markland_list` | returns `list_envelope`; +pagination |
| `markland_get` | keep | `markland_get` | returns `doc_envelope` (with `active_principals`) |
| `markland_search` | keep | `markland_search` | returns `list_envelope`; +pagination |
| `markland_share` | keep | `markland_share` | docstring rewrite |
| `markland_update` | keep | `markland_update` | returns `doc_envelope`; conflict via `if_version` |
| `markland_delete` | keep | `markland_delete` | not idempotent (errors on second delete) |
| `markland_set_visibility` | **fold** | `markland_doc_meta` | folded with `markland_feature` |
| `markland_feature` | **fold** | `markland_doc_meta` | folded with `markland_set_visibility` |
| `markland_grant` | keep | `markland_grant` | param `principal` → `target`; idempotent (upsert) |
| `markland_revoke` | keep | `markland_revoke` | idempotency flip: success even if no grant |
| `markland_list_grants` | keep | `markland_list_grants` | returns `list_envelope`; +pagination |
| `markland_create_invite` | keep | `markland_create_invite` | not idempotent |
| `markland_revoke_invite` | keep | `markland_revoke_invite` | idempotency flip: success even if no invite |
| `markland_list_my_agents` | keep | `markland_list_my_agents` | returns `list_envelope`; +pagination |
| `markland_set_status` | **fold** | `markland_status` | folded with `markland_clear_status` |
| `markland_clear_status` | **fold** | `markland_status` | folded with `markland_set_status` |
| `markland_audit` | keep | `markland_audit` | returns `list_envelope`; +pagination |
| _(new)_ | add | `markland_get_by_share_token` | anonymous-viewer-equivalent read |
| _(new)_ | add | `markland_list_invites` | owner-only; mirrors `markland_list_grants` |
| _(new)_ | add | `markland_explore` | public docs feed; anonymous-friendly |
| _(new)_ | add | `markland_fork` | promote existing HTTP fork to MCP |
| _(new)_ | add | `markland_revisions` | list capped revisions; read-only |

Net surface: 19 current → 17 after folds → 22 with the 5 additions.

### 8.1 Axis 1 — Naming

- Tool names: `markland_<verb>(_<noun>)?`. Audit pass enforces this pattern
  on any tool that survives axis 4 (granularity) intact. Tools that get folded
  in axis 4 (`set_visibility`, `feature`, `set_status`, `clear_status`) are
  not renamed separately — they're replaced by the folded tool's name.
- New-tool names from axis 5 follow the pattern from the start.
- Parameter names: canonical forms across all tools.
  - Document identifier: `doc_id` (consistent today).
  - Grant subject: today's `principal` is overloaded (sometimes a `usr_…` id,
    sometimes an email, sometimes an `agt_…`). Rename to `target` and
    document the accepted forms in the docstring.
  - Booleans: drop `is_` prefix on inputs (`public`, `featured`,
    `single_use`); keep on outputs (`is_public`, `is_featured`) so the
    payload mirrors the database column names readers will see in SQL.

### 8.2 Axis 2 — Return shapes

Three shared envelopes:

- **`doc_envelope`** — used by `markland_publish`, `markland_get`,
  `markland_update`. Fields:
  ```
  {id, title, content, version, owner_id, share_url, is_public,
   is_featured, created_at, updated_at, active_principals?}
  ```
  `active_principals` is only included from `markland_get`.
- **`doc_summary`** — used by `markland_list`, `markland_search`. A subset of
  `doc_envelope` without `content`.
- **`list_envelope`** — used by every list-returning tool:
  ```
  {items: [...], next_cursor: str | null}
  ```

Today: every tool returns its own dict shape. Audit consolidates.

### 8.3 Axis 3 — Error model

Detailed in §7. Closed set of seven codes; consistent wire representation;
documented idempotency contract per tool.

### 8.4 Axis 4 — Granularity

- **Fold:** `markland_set_status` + `markland_clear_status` →
  `markland_status(doc_id, status: str | None)`. `status=None` clears.
- **Fold:** `markland_set_visibility` + `markland_feature` →
  `markland_doc_meta(doc_id, *, public=None, featured=None)`. Admin-gated for
  `featured`; owner-gated for `public`. Either field may be None to leave
  unchanged.
- **Keep separate:** `markland_grant` / `markland_revoke` / `markland_list_grants`
  — separate verbs over the same noun is fine; folding hurts readability.
- **Keep separate:** `markland_create_invite` / `markland_revoke_invite`. Same
  reasoning.

### 8.5 Axis 5 — Missing pieces

Add:
- **`markland_get_by_share_token(share_token)`** — anonymous-viewer-equivalent
  read. Returns `doc_envelope` if doc is public, else `not_found`.
- **`markland_list_invites(doc_id)`** — owner-only. Mirrors
  `markland_list_grants`. Returns `list_envelope` of invite summaries (no
  plaintext token; just id, level, uses_remaining, expires_at).
- **`markland_explore(limit?, cursor?)`** — public docs feed (what `/explore`
  shows). Anonymous-friendly.
- **`markland_fork(doc_id, title?)`** — duplicate a doc you can view. Already
  exists as an HTTP route; promote to MCP for symmetry.
- **`markland_revisions(doc_id, limit?)`** — list capped revisions. Read-only
  for now; no rollback tool yet (out of scope, would be a separate plan).

Defer:
- **Agent token CRUD from MCP** — minting `mk_agt_…` from MCP is a privilege
  escalation footgun; keep it in the HTML settings flow.
- **Threaded comments** — separate product surface, separate plan.

### 8.6 Axis 6 — Docstrings & schemas

Every tool's docstring follows a four-part structure:

```
{One-line summary stating the action and the actor's role.}

{One paragraph: when to use this, common patterns, gotchas.}

Args:
    {arg}: {Type, format, accepted forms, default behavior.}

Returns:
    {Shape reference (e.g., "doc_envelope") and what fields mean.}

Raises:
    not_found: {Specific conditions that surface as not_found.}
    forbidden: {Same.}
    conflict: {Same — only on markland_update.}

Idempotency: {Idempotent | Not idempotent — and why.}
```

Audit pass rewrites every tool's docstring to this template. The new tools
from axis 5 are written to it from the start.

### 8.7 Axis 7 — Pagination & limits

Every list-returning tool gets `limit: int = 50` (max 200) and `cursor: str |
None = None`. Returns `list_envelope` with `next_cursor` set when more results
exist. Cursor format: opaque base64 of `{last_id, last_updated_at}`; tools
don't expose internals.

Tools affected: `markland_list`, `markland_search`, `markland_list_grants`,
`markland_list_invites` (new), `markland_explore` (new), `markland_revisions`
(new), `markland_audit`, `markland_list_my_agents`.

### 8.8 Axis 8 — Idempotency & safety

Every mutating tool's docstring states its idempotency contract. The closed
set:

- **Idempotent** — repeating the call with same args produces same outcome:
  `markland_doc_meta`, `markland_grant` (upsert), `markland_revoke` (success
  even if no grant existed), `markland_status`, `markland_revoke_invite`
  (success even if no invite).
- **Not idempotent** — repeating produces different outcome:
  `markland_publish` (creates a new doc each time), `markland_update`
  (changes version), `markland_delete` (errors second time), `markland_fork`
  (creates new doc).

A small machine-readable table lives at the top of `server.py` and a
`tests/test_audit_idempotency.py` asserts that idempotent tools called twice
with the same args produce the same final state.

## 9. Deprecation policy

Each renamed/folded tool ships in two phases:

**Phase A (audit release):** new name lives; old name lives; both work; old's
docstring starts with `Deprecated. Use markland_<new> instead. Removed in the
release scheduled 30 days after this one.` The exact removal date is filled
in at audit-release time; the implementation plan tracks the date. Behavior
parity test asserts old and new produce the same value for the same args.

**Phase B (audit-release + 30 days):** old name deleted; deprecation parity
test deleted. README's tool table updated.

Folded tools (e.g., set_status + clear_status → status) keep both old tools as
deprecation shims that delegate to the new tool.

## 10. Testing strategy

Three layers, run in single CI job (`pytest tests/ -v`).

**Layer A — Tests of the harness itself** (`tests/test_mcp_harness.py`,
~15-20 tests, <1s):
- Principal seeding (user, agent, admin, anon).
- Caller caching (cached vs `fresh=True`).
- `call` raises `MCPCallError`; `call_raw` doesn't.
- `Response` wrapper normalizes today's mixed error shapes.
- Mode-equivalence: same call in `direct` and `http` produces equivalent
  `Response`.
- Email capture: `markland_grant` triggers a captured send.
- Per-test isolation: two harnesses don't share state.
- HTTP-mode session-per-Caller.

**Layer B — Behavior baseline** (`tests/test_mcp_baseline.py`, ~50-70
scenarios):
- Every tool: 1 happy-path scenario + 1-2 error scenarios.
- Snapshots written to `tests/fixtures/mcp_baseline/<tool>.json` keyed by
  scenario name.
- `as_envelope(...)` strips volatile fields before snapshot.
- Run in direct mode by default; sampled subset (~5 tools × 2 scenarios) also
  runs in HTTP mode.
- `pytest --mcp-http-full` opts into running every baseline scenario in HTTP
  mode too. Default in CI: sampled.
- `pytest --snapshot-update` rewrites snapshot files.

**Layer C — Per-axis audit tests** (`tests/test_audit_*.py`, one file per
axis): explicit assertions about the target contract from §8. Each axis's
file is also documentation of that axis's invariants.

Plus `tests/test_audit_deprecations.py` — for every deprecation: behavior
parity, docstring marker, removal-date present. Deleted in Phase B.

## 11. Snapshot mechanism

Hand-rolled, ~50 lines in the harness:

```python
def snapshot(self, tool: str, scenario: str, payload: Any) -> None:
    path = Path("tests/fixtures/mcp_baseline") / f"{tool}.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    if self._snapshot_update_mode:
        existing[scenario] = payload
        path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
        return
    if scenario not in existing:
        raise AssertionError(
            f"Missing snapshot for {tool}/{scenario}. "
            f"Run: pytest --snapshot-update"
        )
    if existing[scenario] != payload:
        raise AssertionError(self._format_diff(existing[scenario], payload))
```

`--snapshot-update` is wired via a custom pytest CLI flag in `conftest.py`.
`as_envelope(...)` is a separate helper, not part of the snapshot writer, so
tests can normalize before snapshotting.

## 12. Migration plan

Suggested ordering (full plan is the writing-plans output, not this spec):

1. Harness + Layer A tests. Lands first; nothing depends on it.
2. Layer B baseline against current surface. Captures status quo before
   anything changes.
3. Axis 1 (naming) + Axis 6 (docstrings). Touch every tool but no behavior
   change. Smallest blast radius first.
4. Axis 3 (error model). Behavior change but well-bounded; the harness's
   normalization table shrinks.
5. Axis 2 (return shapes). Bigger touch; introduces shared envelopes.
6. Axis 7 (pagination). Additive.
7. Axis 4 (granularity). New folded tools land; old ones get deprecation
   shims.
8. Axis 5 (missing pieces). New tools land; no migration needed.
9. Axis 8 (idempotency). Mostly docstring + flipping a few "not_found" cases
   to idempotent success.
10. Phase B: drop deprecation shims after 30 days.

## 13. Open questions

None pending — all design questions resolved during brainstorming. Re-open
during plan authoring if implementation surfaces new ones.

## 14. Acceptance criteria

The audit is complete when:

1. All 19 existing tools land their disposition per the §8.0 table (keep,
   fold, or — none in this audit — remove).
2. Five new tools from axis 5 are live: `markland_get_by_share_token`,
   `markland_list_invites`, `markland_explore`, `markland_fork`,
   `markland_revisions`.
3. Every tool returns one of three envelopes (doc, doc_summary, list).
4. Every error path uses one of seven codes.
5. Every list-returning tool supports `limit` + `cursor`.
6. Every tool's docstring follows the §8.6 template.
7. Every mutating tool's idempotency contract is stated and tested.
8. Layer A, Layer B, and all Layer C test files pass.
9. Phase A deprecations live with parity tests; Phase B removal scheduled.
10. README's tool table reflects the new surface.
