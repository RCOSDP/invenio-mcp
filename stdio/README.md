# stdio version — 12 tools, one token

*[日本語版はこちら / Japanese version](README.ja.md)*

A stdio MCP server for doing CRUD on InvenioRDM records and files.
Built on the official `mcp` SDK (FastMCP) plus the standard library only — nothing else
to install. It calls the InvenioRDM REST API with a bearer token.

Targets InvenioRDM v14. All 12 tools have been exercised against a live instance.

## Layout

- `server.py` — the server itself (12 tools)
- `.token` — the API token (mode 600, **gitignored**, never commit it)
- Registration goes in the client's MCP config (`.mcp.json` / `claude_desktop_config.json`)

## Setup

### 1. Issue an API token (once)

```bash
# Run inside the InvenioRDM application container.
# Use an account with the admin role if you want to withdraw and restore published records.
invenio tokens create -n mcp-stdio -u <admin email> | tail -1 \
  | tr -d '\n' > "$PWD/.token"
chmod 600 "$PWD/.token"
```

You can also issue one from the UI at
`<InvenioRDM>/account/settings/applications/tokens/new/`.

A regular user is enough for creating, publishing, discarding drafts and handling files.
**Withdrawing and restoring published records requires the admin role.**

### 2. File storage

`web-api` and `worker` must be able to reach the configured file location (S3/MinIO or similar).

### 3. TLS with a self-signed root CA

Leave verification **on** (the default) and pass the root CA through `INVENIO_CA_BUNDLE`.
The server reads the file directly rather than relying on `SSL_CERT_FILE`, because it runs
as a child process of the MCP client and the login shell's environment does not always
reach it.

### 4. Register with the client

Add it to your client's MCP configuration. **Restart the client after changing the
configuration** — an already running process keeps the old environment, and a green check
in a connection list only means "it started", not "it works".

Tools appear as `mcp__inveniordm__<name>`.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `INVENIO_API` | `https://localhost/api` | REST API base |
| `INVENIO_TOKEN` | (falls back to reading `.token`) | Bearer token |
| `INVENIO_VERIFY_TLS` | `true` | TLS verification. Set `false` only to turn it off |
| `INVENIO_CA_BUNDLE` | (required when self-signed) | Root CA used for verification |

## Tools (12)

**Read**
- `search_records(query="", size=10)` — search published records (summary fields)
- `get_record(recid, draft=False)` — fetch one (`draft=True` for the draft)

**Create and update**
- `create_record(metadata, access=None, files_enabled=False, publish=False)`
- `update_record(recid, metadata, publish=True)` — for published records this does edit → update → publish
- `publish_record(recid)` — publish a draft
- `new_version(recid, metadata=None, publish=False)`

**Delete**
- `delete_draft(recid)` — discard a draft
- `delete_record(recid, confirm=False, reason_id="out-of-scope", note=...)` — soft delete a
  published record (tombstone, HTTP 410). **Requires admin**, requires `confirm=True`, restorable
- `restore_record(recid)` — restore a soft-deleted record (admin)

**Files** (the record must have `files_enabled=True`)
- `add_file(recid, key, text=None, content_base64=None, source_path=None)` — init → content → commit
- `list_files(recid, draft=True)`
- `delete_file(recid, key)`

## Minimum metadata for `create_record`

```json
{
  "resource_type": {"id": "dataset"},
  "title": "A title of at least 3 characters",
  "publication_date": "2026-07-09",
  "creators": [
    {"person_or_org": {"type": "personal", "family_name": "Yamada", "given_name": "Taro"}}
  ]
}
```

`resource_type.id` comes from a vocabulary (`dataset`, `publication-article`, …).
`publisher` and the rest are optional.

## Self-test

```bash
python3 server.py --selftest   # create → update → add_file → publish → search → delete → restore
```

The self-test soft-deletes its test record at the end, which leaves a tombstone behind.

## Sending large files

`add_file` here is a single PUT through InvenioRDM (transfer type `L`). The MCP response
limit on base64 (16 MB) can be sidestepped with `source_path`, but the bytes always travel
through `web-api`. For gigabyte-scale files use `start_multipart_upload` in the
[HTTP version](../http/README.md), which hands the client a presigned URL so the data goes
straight to object storage.

Note that in v14 fetching by URL (transfer type `F`) is restricted to `SystemProcess()`
and is no longer available to ordinary users.

## Safety notes

- Write against a **demo instance** with disposable data.
- `delete_record` requires `confirm=True` and is a soft delete, recoverable with
  `restore_record`. A hard purge is not exposed over REST and is therefore not possible here either.
- The token is a secret. Keep `.token` at mode 600, keep it gitignored, and do not put it
  in plain text in `.mcp.json`.
- To roll back, delete the token: `invenio tokens delete ...`
