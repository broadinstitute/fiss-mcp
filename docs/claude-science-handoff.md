# Handoff: make fiss-mcp work fully under Claude Science

> **Status: implemented.** Both code changes described here landed in `5b9c1ef`
> (awaited `ctx.*` logging; a GCS XML-API backend selected with
> `--gcs-backend`), and the GCS path was confirmed working inside the Claude
> Science sandbox on 2026-10-02. This file is kept as the record of the
> investigation that produced them, not as outstanding work. Current behaviour
> is documented in `README.md` under "Claude Science Integration" and in
> `CLAUDE.md`; the open question at the end of this file, about the
> per-connector workspace directory, is still open.

Context for a Claude Code session working in `broadinstitute/fiss-mcp`
(upstream `main` at `a4becf1` as of 2026-10-02). Written after a debugging
session that got the server running inside Claude Science's sandbox. The
install-side work is done and documented in `CLAUDE_SCIENCE.md` (README
section) and `scripts/install-claude-science.sh` — add both to the repo. This
file covers the **code changes** still needed.

## TL;DR

1. **Bug A (all clients):** `ctx.info/error/warning/debug` are coroutines under
   FastMCP ≥ 3 and the server never `await`s them → every log line is silently
   dropped, and the real exception behind a `ToolError` is lost. Fix: `await`
   them; make the two sync helpers that use `ctx` async.
2. **Bug B (Claude Science only):** `storage.googleapis.com` is permanently
   blocked by Claude Science's sandbox. The `google-cloud-storage` client only
   uses that host (JSON API), so all five GCS-touching tools fail there. Fix:
   add an XML-API code path using per-bucket hostnames
   (`{bucket}.storage.googleapis.com`), which Claude Science allows you to
   allowlist individually.
3. **Minor:** `storage.Client()` with user ADC and no gcloud config raises
   `OSError: Project was not passed and could not be determined from the
   environment`. Make the project optional (`storage.Client(project=...)` from
   env, or `project=None` with an anonymous-safe fallback) and document
   `GOOGLE_CLOUD_PROJECT`.

Acceptance: with the four allowed domains plus one workspace-bucket domain
configured in Claude Science, `get_workflow_logs(fetch_content=True)`,
`read_gcs_object`, `get_gcs_object_metadata`, `list_gcs_objects`, and
`download_gcs_file` (to `/tmp/...`) all work; `pytest` passes; and a failing
Terra call shows its underlying exception in the server's stderr.

---

## Bug A — unawaited `ctx` logging

**Evidence** (stderr from the sandbox run):

```
/opt/fiss-mcp/repo/src/terra_mcp/server.py:760: RuntimeWarning: coroutine 'Context.info' was never awaited
  ctx.info("Fetching accessible Terra workspaces")
/opt/fiss-mcp/repo/src/terra_mcp/server.py:790: RuntimeWarning: coroutine 'Context.error' was never awaited
  ctx.error(f"Unexpected error listing workspaces: {type(e).__name__}: {e}")
```

`pyproject.toml` pins `fastmcp>=3.0.0b1`; the installed version was 4.0.10. In
FastMCP 3/4, `Context.info/debug/warning/error` are `async def`.

**Counts** (`src/terra_mcp/server.py`): 100 call sites of the form
`ctx.(info|error|warning|debug)(`; **0** are awaited.

- 96 are inside `async def` tool functions → prefix with `await`.
- 4 are inside **sync** helpers and cannot simply get `await`:
  - line 58, `_check_write_access(ctx)` — `ctx.warning(...)`
  - lines 114, 126, 130, `_fetch_gcs_log(gcs_url, ctx)` — `ctx.error/info/error`

  Options: make both helpers `async def` and `await` their call sites
  (`_check_write_access` is called at the top of the five write tools;
  `_fetch_gcs_log` is called from `get_workflow_logs`), or drop `ctx` logging
  from them and use the `logging` module. Making them async is cleaner and
  `_fetch_gcs_log` becomes async anyway for Bug B.

**Mechanical first pass** (verified safe for the 96; then hand-fix the 4):

```bash
sed -i '' -E 's/^([[:space:]]*)ctx\.(info|error|warning|debug)\(/\1await ctx.\2(/' src/terra_mcp/server.py
python -m py_compile src/terra_mcp/server.py   # will fail on the 4 sync sites until fixed
```

Use `ast` to confirm nothing is left inside a sync function:

```python
import ast
src = open("src/terra_mcp/server.py").read()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.FunctionDef):            # sync defs only
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and isinstance(sub.func.value, ast.Name) and sub.func.value.id == "ctx"):
                print(sub.lineno, node.name)
```

**Tests:** `tests/test_server.py` builds `ctx = MagicMock()`. Once the calls are
awaited, `MagicMock` returns a non-awaitable and the tools will raise
`TypeError: object MagicMock can't be used in 'await' expression`. Switch the
ctx mocks to `AsyncMock()` (or `MagicMock(spec=Context)` with async methods).
Also, a few tests may assert on `ctx.error.assert_called...`; those still work
with `AsyncMock`.

**Also consider:** in the `except Exception as e:` branches, the user-facing
`ToolError` text ("Please verify your Google credentials…") hides the real
cause. Append `type(e).__name__: {e}` to the `ToolError` message, or at least
`logging.exception(...)` to stderr, so a client that doesn't surface MCP log
notifications (Claude Science shows only stderr) can still see it. This alone
would have saved an hour of debugging.

---

## Bug B — GCS via `storage.googleapis.com` is unreachable in Claude Science

### The sandbox, as observed

Claude Science runs local MCP servers under a sandbox ("Operon" 0.1.55). From
the server's environment:

```
HTTPS_PROXY=http://localhost:65366          # also HTTP_PROXY, ALL_PROXY=socks5h://localhost:65367
NO_PROXY=localhost,127.0.0.1,::1,*.local,.local,169.254.0.0/16,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
TMPDIR=/tmp/operon-sandbox
OPERON_WRITABLE_ROOTS=/Users/<u>/.claude-science/orgs/<org>/workspaces/_mcp-terra:...:/private/tmp:/dev/shm
```

- No direct DNS/sockets (`socket.create_connection` → `gaierror`). All traffic
  goes through the HTTP CONNECT proxy, which enforces a per-connector
  **domain allowlist** (UI: connector → "Allowed domains"). Off-list host →
  `OSError: Tunnel connection failed: 403 Forbidden (host X not on the allowlist)`.
- Currently allowlisted and working: `oauth2.googleapis.com`,
  `api.firecloud.org`, `batch.googleapis.com`, `www.googleapis.com`.
- The UI refuses `storage.googleapis.com` with: *"storage.googleapis.com is
  always blocked in Claude Science. Use the bucket's own address, like
  my-bucket.storage.googleapis.com."* So per-bucket virtual-hosted names
  **are** allowlistable.
- Filesystem: no exec and no read under `$HOME` (except the per-connector
  workspace dir above), writes only to `/private/tmp` and that workspace dir.
  `download_gcs_file` destinations must therefore be under `/tmp`.

### Why the current client can't be configured around it

`google-cloud-storage` uses the JSON API (`https://storage.googleapis.com/storage/v1/...`
and `/download/storage/v1/...`). `client_options={"api_endpoint": ...}` changes
the base host but the JSON API is not served on `{bucket}.storage.googleapis.com`
(only the XML API is). I'm ~90% sure of this; a one-line check from a normal
terminal settles it:

```bash
TOKEN=$(gcloud auth application-default print-access-token)
B=fc-<workspace-bucket-uuid>
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  "https://$B.storage.googleapis.com/storage/v1/b/$B/o?maxResults=1"      # expect 404/400 → JSON not served here
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  "https://$B.storage.googleapis.com/?list-type=2&max-keys=1"            # expect 200 → XML works
```

If the first returns 200, the fix is trivial (`client_options` with a
per-bucket endpoint). Assume it doesn't.

### Proposed design

Add a small XML-API backend and route the five GCS call sites through a
common helper. Keep the JSON client as the default outside Claude Science.

**Call sites** (`src/terra_mcp/server.py`, line numbers at `a4becf1`):

| Function | `storage.Client()` at | Operation |
|---|---|---|
| `_fetch_gcs_log` | 120 | `blob.download_as_text()` (used by `get_workflow_logs(fetch_content=True)`) |
| `list_gcs_objects` | 1580 | `client.list_blobs(bucket, prefix=, delimiter=)` |
| `get_gcs_object_metadata` | 1672 | `bucket.get_blob()` → size, content_type, md5/crc32c, updated, generation |
| `read_gcs_object` | 1766 | `blob.download_as_bytes(start=, end=)` (100 KB cap, offset) |
| `download_gcs_file` | 1891 | `blob.download_to_filename()` with size/disk checks |

`_parse_gcs_uri` (line 1501) already splits `gs://bucket/key`.

**XML API mapping** (host `https://{bucket}.storage.googleapis.com`, auth
header `Authorization: Bearer <token>`; obtain token via
`google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])`
+ `creds.refresh(google.auth.transport.requests.Request())`; refresh hits
`oauth2.googleapis.com`, already allowlisted):

| Operation | XML request | Notes |
|---|---|---|
| list | `GET /?list-type=2&prefix=<p>&delimiter=/&max-keys=1000[&continuation-token=]` | Response is XML: `<Contents><Key>,<Size>,<LastModified>,<ETag>` and `<CommonPrefixes><Prefix>`; `<IsTruncated>` / `<NextContinuationToken>` for paging. Parse with `xml.etree.ElementTree`; namespace `http://doc.s3.amazonaws.com/2006-03-01`. |
| metadata | `HEAD /<key>` | Headers: `Content-Length`, `Content-Type`, `Last-Modified`, `ETag`, `x-goog-generation`, `x-goog-hash: crc32c=...,md5=...`, `x-goog-stored-content-length`. |
| read range | `GET /<key>` with `Range: bytes=<start>-<end>` | 206 on success. Keep existing 100 KB default cap and UTF-8/base64 behaviour. |
| download | `GET /<key>`, `stream=True`, write chunks | Keep existing overwrite / disk-free / size-verification checks; verify against `Content-Length`. |

URL-encode keys with `urllib.parse.quote(key, safe="/")`.

**Selection logic** — one of:

- CLI flag `--gcs-backend {json,xml,auto}` (default `auto`): try the JSON
  client; on `requests.exceptions.ProxyError` / `OSError` containing
  `"not on the allowlist"` (or any connection-level failure to
  `storage.googleapis.com`), fall back to XML and remember the choice for the
  process lifetime. Log which backend is in use once at startup / first use.
- Or simply detect `SANDBOX_RUNTIME=1` / `OPERON_VERSION` in the environment
  and default to XML. Less general; the flag is better.

Expose the backend in tool error messages, e.g. *"GCS (xml backend): 403 from
fc-….storage.googleapis.com — is this bucket's hostname on the Claude Science
allowed-domains list?"*. That's the error users will actually hit.

**Project requirement:** `storage.Client()` raises
`OSError: Project was not passed and could not be determined from the environment`
when ADC is a user credential and there's no gcloud config (the sandbox runs
with `HOME=/opt/fiss-mcp`, so `~/.config/gcloud` isn't visible). For read
operations the project is only used as a quota project. Use
`storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))`, and if that's
`None` pass `project="_"`? — no: cleaner is
`google.auth.default()` → `(creds, project)` and
`storage.Client(project=project or os.environ.get("GOOGLE_CLOUD_PROJECT") or "unused", credentials=creds)`.
The XML backend doesn't need a project at all. Document `GOOGLE_CLOUD_PROJECT`
in the README's Claude Science section either way. Requester-pays buckets
would additionally need `?userProject=` (XML) / `user_project=` (JSON); Terra
workspace buckets are not requester-pays, so out of scope.

**Dependencies:** `requests` and `google-auth` are already transitive deps of
`firecloud` and `google-cloud-storage`; add them explicitly to `pyproject.toml`
if you import them directly.

**Tests:** mock `requests.Session.get/head` (or use `responses`) with canned
XML listing bodies and header sets; cover paging (`IsTruncated`), delimiter
prefixes, range reads, 403/404 mapping to `ToolError`, and the auto-fallback
trigger. Existing tests mock `storage.Client`; keep those for the JSON path.

**README:** in the Claude Science section's "Allowed domains", add a line
explaining that each workspace bucket needs its own entry,
`fc-<uuid>.storage.googleapis.com` (the bucket name is in
`get_workspace_metadata` → `bucketName`), and remove the "GCS tools do not
work" limitation once implemented. The `get_workflow_logs` log paths live in
the workspace bucket too, so one entry per workspace covers logs, outputs,
and inputs stored there; inputs in *other* buckets need their own entries.

---

## How to test inside the real sandbox

There's no way to run the sandbox from a terminal; the loop is:

1. Edit code in the install tree Claude Science launches
   (`/opt/fiss-mcp/repo` on the dev machine; a clone outside `$HOME`, launched
   by `/opt/fiss-mcp/run.sh`, which redirects stderr to
   `/tmp/fiss-mcp-stderr.log`).
2. `pkill -f terra_mcp/server.py` — Claude Science keeps the process alive
   across calls/conversations; it respawns on the next tool call.
3. Ask Claude Science to call the tool; `tail -n 60 /tmp/fiss-mcp-stderr.log`.

A probe that runs *inside* the sandbox at startup (env dump + a Terra call
with full traceback) is in `CLAUDE_SCIENCE.md` → Troubleshooting; it's how the
allowlist error was found. Equivalent probe for GCS:

```python
import requests, google.auth, google.auth.transport.requests
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
creds.refresh(google.auth.transport.requests.Request())
b = "fc-<uuid>"
r = requests.get(f"https://{b}.storage.googleapis.com/?list-type=2&max-keys=3",
                 headers={"Authorization": f"Bearer {creds.token}"}, timeout=20)
print(r.status_code, r.text[:300])
```

Expect 200 once `fc-<uuid>.storage.googleapis.com` is on the allowlist; a
`403 ... not on the allowlist` otherwise.

Terminal smoke tests outside the sandbox (`env -i HOME=/opt/fiss-mcp
GOOGLE_APPLICATION_CREDENTIALS=... PATH=... python -c ...`) validate
credentials and imports but **not** the network policy.

---

## Things that turned out not to matter (don't re-investigate)

- `FASTMCP_SHOW_CLI_BANNER=false` — had no effect (banner still printed); the
  earlier `mcp.run()` crash was fixed by redirecting stderr to a file in the
  launcher. Root cause of that crash was never captured, but it's gone with
  the redirect.
- `TMPDIR` — don't override; the sandbox sets `/tmp/operon-sandbox`.
- gcloud under `$HOME` — FISS's import-time `which('gcloud')` only `stat`s the
  file, which the read-restricted sandbox allowed. No relocation needed.
- Credentials — a copied ADC JSON at `/opt/fiss-mcp/adc.json` via
  `GOOGLE_APPLICATION_CREDENTIALS` works; token refresh succeeds once
  `oauth2.googleapis.com` is allowlisted.

## Open question worth a 10-minute test

`OPERON_WRITABLE_ROOTS` and `OPERON_DLOPEN_EXEMPT` both name
`~/.claude-science/orgs/<org-id>/workspaces/_mcp-terra/` (with `.venv/python`
exempted). That looks like the *intended* location for a local MCP server's
code and venv, which would remove the need for `/opt/fiss-mcp` entirely. If a
venv created there (from Homebrew Python) launches under the sandbox, update
the installer to prefer it.
