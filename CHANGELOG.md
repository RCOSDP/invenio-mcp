# Changelog

*[日本語](CHANGELOG.ja.md)*

<!-- --8<-- [start:body] -->
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/invenio-mcp/project/versioning/) for what counts
as breaking when the consumer is a language model rather than a compiler.

## [Unreleased]

## [0.0.2] — 2026-08-29

**A security release.** Nothing changes for a client that was using the servers as
documented; what changes is what a client could reach if it went looking. One of these
was reachable in practice — `download_file` could be turned into an SSRF by uploading a
file whose contents are a URL. The rest closed structures that were open but not yet
exposed.

### Security

- **A tool missing from `TOOL_SCOPES` no longer defaults to public.** `TOOL_SCOPES.get()`
  returned `None` both for "this tool is public" and for "this tool is not in the map",
  so adding a write tool and forgetting the entry would have opened it to anyone. The
  server now compares the map against the registered tools at import and **refuses to
  start** when they disagree.
- **The scope check now inspects JSON-RPC batches.** A batch (a JSON array) fell through
  `isinstance(payload, dict)` and was passed on unchecked. The current SDK rejects
  batches with a 400, so nothing was exposed — but the guard was the SDK's behaviour
  rather than ours, and an SDK that accepted batches would have bypassed authorization
  entirely. Every `tools/call` in a batch is now checked, and the strictest requirement
  wins.
- **`download_file` no longer follows a URL found in a file's own bytes.** InvenioRDM
  answers a content request for S3 storage with a presigned URL in the body, which the
  server followed. The same shape can be produced by **uploading a file whose contents
  are a URL**, which turned the tool into an SSRF with the response handed back to the
  caller. The body is now only read as a presigned URL when its length differs from the
  file's registered size — a file always comes back at its own size.
- **`recid`, filenames and other values are encoded as single URL path segments.**
  `quote()`'s default leaves `/` intact, so a value containing `../` reached a different
  endpoint than the one intended.
- **The request body is capped** (`MCP_MAX_REQUEST_BYTES`, twice the upload limit).
  Authorization needs the whole body, so an unbounded POST could exhaust memory. Over
  the cap the answer is `413`.
- **Documented that `add_file(source_path=...)` in the stdio server reads any file the
  process can read.** That is by design, but the caller is a language model, so it is a
  prompt-injection target worth naming.

### Fixed

- **`search_records` URL-encodes its query.** A query containing `&size=10000` was
  injected into the InvenioRDM request as a separate parameter.
- **The audit line for a denied batch names the tool that was actually denied**, not the
  first entry in the batch.

## [0.0.1] — 2026-08-29

**First public release.** Two MCP servers that drive InvenioRDM over nothing but its
REST API — no extension to install on the repository side.

### Added

- **`stdio/server.py` — 12 tools over stdio, one personal access token.** The
  dependencies are the standard library plus `mcp`, so the whole thing can be read in
  one sitting and run by one person for themselves.

- **`http/mcp_server.py` — 33 tools over Streamable HTTP, with switchable
  authentication.** `MCP_AUTH_MODE=keycloak` makes it a resource server conforming to
  [MCP authorization 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization):
  RFC 9728 protected resource metadata, JWKS signature checking, **`aud` validated
  against this server's own canonical URI** so a token minted for somewhere else cannot
  be walked in, and RFC 8693 token exchange so the received token is **never forwarded**
  to InvenioRDM. `MCP_AUTH_MODE=invenio` (the default) takes an InvenioRDM personal
  access token instead, which needs no authorization server at all.

- **Per-tool scopes, with reading left unauthenticated.** A repository shows published
  records to everyone and the InvenioRDM REST API behaves that way, so searching,
  fetching and exporting need no token. `mcp:read` covers what has to be *you*,
  `mcp:write` covers changes, and `mcp:curate` is separated out for withdrawing a
  published record, restoring one, accepting a review and creating a community —
  operations that need the admin role in InvenioRDM. A tool called without the scope
  answers `403 insufficient_scope` with the scope named, so a client can step up.

- **`/mcp-auth`, a second path onto the same resource that is 401 from the first
  request.** Some clients only prepare for authorization if the initial connection
  fails — `mcp-remote` 0.1.37 builds its callback listener solely from the
  `UnauthorizedError` path. Because this server lets anonymous connections succeed,
  those clients would connect and then have nowhere to receive the authorization code.
  It is a **separate protected resource** with its own metadata, since RFC 9728
  requires `resource` to match the URI the client connected to.

- **Vocabulary tools** (`list_vocabulary_types`, `list_vocabulary`). Without them a
  model guesses at `resource_type.id` and collects 400s; with them it can check first.

- **Three ways to move file bytes**, because one does not cover the range: `upload_file`
  carries them as base64 (bounded by JSON, 16MB by default), `upload_file_from_url`
  registers a URI for InvenioRDM to fetch, and `start_multipart_upload` hands back
  presigned URLs so the client PUTs **straight to S3/MinIO**, past both this server and
  InvenioRDM.

- **Japanese and English language resources** (`locales/en.json`, `locales/ja.json` next
  to each server). Tool descriptions, error messages and the startup banner all come
  from them; `MCP_LANG` selects one, falling back to the system locale and then to
  English. Dropping another `<tag>.json` in adds a language, and any key it lacks falls
  back to English, so a partial translation still runs. One string stays English on
  purpose: `error_description` in the `WWW-Authenticate` header, where RFC 6750 permits
  only a subset of ASCII — the translated text goes in the JSON body of the same
  response.

- **An audit line per call**, one JSON object per line on stdout: subject, tool, status,
  duration. **Never the token.**

- **Conformance checks that run against a live instance.**
  `conformance/mcp_client.py` reports PASS/FAIL for the discovery flow, PKCE with
  `resource` (RFC 8707), `iss` validation (RFC 9207), the 403-then-step-up path, and
  rejection of a token issued for a different audience.
  `conformance/verify-mcp-files.py` round-trips real bytes through all three transfer
  paths and checks the composite ETag and MD5 against locally computed values.

- **Deployment for both shapes.** `docker-compose.yml` runs PAT mode as a single
  service; `k8s/mcp-server.yaml` is a template for the Keycloak setup. Both build from
  the same `Dockerfile`.

- **A documentation site** at <https://rcosdp.github.io/invenio-mcp/>, in English and
  Japanese. The tool reference is generated from the servers and their language
  resources, so it cannot drift from what a client actually sees.

### Security

- **No credential has a default.** `MCP_SERVER_SECRET` and `KC_ADMIN_PASSWORD` stop the
  program when unset, rather than running on a guessable value.
- **TLS verification is on by default.** Turning it off takes `MCP_TLS_INSECURE=1`.
- Demo users are not created unless `MCP_DEMO_USERS=yes`; their passwords are weak.

[Unreleased]: https://github.com/RCOSDP/invenio-mcp/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/RCOSDP/invenio-mcp/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/RCOSDP/invenio-mcp/releases/tag/v0.0.1
<!-- --8<-- [end:body] -->
