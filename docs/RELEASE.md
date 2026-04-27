# Release & deployment runbook

scoutdocs-mcp ships two artifacts from one repo:

1. **PyPI package** `scoutdocs-mcp` (Python stdio server)
2. **Cloudflare Worker** at `scoutdocs-mcp.<your>.workers.dev/mcp`

Both releases are independent and can ship at different cadences.

## Versioning

Semantic versioning. Beta releases are tagged `0.x.0bN`. Once the public API
stabilizes we drop the `bN` suffix. Bump `__version__` in
`src/scoutdocs_mcp/__init__.py` and `version` in `pyproject.toml` in the same
commit. Worker version lives in `worker/wrangler.toml` (`SCOUTDOCS_VERSION`)
and `worker/package.json`; keep them in sync with the Python package.

## Python release (PyPI)

### First-time setup (do once)

1. Create accounts on **TestPyPI** (<https://test.pypi.org/account/register/>)
   and **PyPI** (<https://pypi.org/account/register/>).
2. Reserve the project name by uploading the first beta to TestPyPI manually
   (see "Manual release" below).
3. After the first manual upload, configure **Trusted Publishing**:
   <https://docs.pypi.org/trusted-publishers/> — point it at this repo's
   `release` GitHub Actions environment. No long-lived API token needed.

### Manual release (used for the first publish, and as a fallback)

```bash
# Clean
rm -rf dist
# Build sdist + wheel
uv build
# Sanity check metadata
uv tool run twine check dist/*
# Upload to TestPyPI first
uv tool run twine upload --repository testpypi dist/*
# Verify install in a clean env
uv venv /tmp/v && uv pip install --python /tmp/v/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  scoutdocs-mcp
/tmp/v/bin/scoutdocs-mcp --help
# If happy, publish to real PyPI
uv tool run twine upload dist/*
```

### Automated release (post-trusted-publishing)

Tag `v0.X.Y` on `main`. The `release.yml` workflow (to be added) builds and
uploads via OIDC to PyPI. Until then, use the manual flow above.

### Yank a bad release

```bash
uv tool run twine yank scoutdocs-mcp==0.X.Y --reason "describe issue"
```

PyPI keeps the file but stops resolving it for new installs. Existing pinned
installs are unaffected.

## Cloudflare Worker

### First-time setup (do once)

```bash
cd worker
# Sign in
npx wrangler login
# Create the KV namespaces (production + preview)
npx wrangler kv namespace create scoutdocs_cache
npx wrangler kv namespace create scoutdocs_cache --preview
# Copy the printed `id` values into wrangler.toml under [[kv_namespaces]]
```

You'll need to do this once per Cloudflare account. The IDs are not secrets
but are environment-specific; keep them in `wrangler.toml`.

### Deploy

```bash
cd worker
npm ci
npm test
npm run typecheck
npx wrangler deploy
```

The Worker URL is printed at the end. Test it:

```bash
curl https://scoutdocs-mcp.<your>.workers.dev/                # liveness
curl -X POST https://scoutdocs-mcp.<your>.workers.dev/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Rollback

```bash
npx wrangler deployments list                # find the previous deployment ID
npx wrangler rollback --message "describe reason" <deployment-id>
```

Rollbacks are atomic — traffic shifts to the previous version within seconds.

## Local development

### Python

```bash
uv sync --extra dev
uv run pytest tests/                         # mocked, offline, deterministic
RUN_LIVE_TESTS=1 uv run pytest tests/test_smoke_live.py  # opt-in network tests
```

To run the stdio server against the source tree:

```bash
uv run scoutdocs-mcp
```

### Worker

```bash
cd worker
npm install
npm test                                     # vitest in workers pool
npx wrangler dev                             # local dev server on :8787
```

Test the dev endpoint with MCP Inspector or curl:

```bash
curl -X POST http://localhost:8787/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

## Pre-release checklist

- [ ] `uv run pytest tests/` — green
- [ ] `RUN_LIVE_TESTS=1 uv run pytest tests/test_smoke_live.py` — green (catches upstream schema drift)
- [ ] `cd worker && npm test && npm run typecheck` — green
- [ ] `cd worker && npx wrangler deploy --dry-run --outdir=dist` — clean
- [ ] `uv build && uv tool run twine check dist/*` — clean
- [ ] Version bumped in `pyproject.toml`, `src/scoutdocs_mcp/__init__.py`, `worker/package.json`, and `SCOUTDOCS_VERSION` in `worker/wrangler.toml`
- [ ] CHANGELOG / GitHub release notes drafted
- [ ] Manually verified one tool call against MCP Inspector for both local and hosted endpoints
