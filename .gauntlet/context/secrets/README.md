# Gauntlet secret fixtures

This directory holds secrets that smoke cards need at run time, in the
fixture-file pattern the gauntlet `read` tool expects (see
`~/Developer/gauntlet/docs/credentials.md`).

**Files here are gitignored by default.** Only `*.example` templates and
this README are committed. To set up a secret locally:

```
cp .gauntlet/context/secrets/<name>.example .gauntlet/context/secrets/<name>
$EDITOR .gauntlet/context/secrets/<name>   # paste the real value
```

The corresponding card should reference the file via the `read` tool,
e.g. `read .gauntlet/context/secrets/e2e-mint-secret.md`.

## Current secrets

| File | Used by | Where the real value lives |
|---|---|---|
| `e2e-mint-secret.md` | `magic-link-cross-site-click.md` | Fly: `flyctl secrets list -a markland` shows the digest; the plaintext is whatever was passed to `flyctl secrets set MARKLAND_E2E_SECRET=...` |
