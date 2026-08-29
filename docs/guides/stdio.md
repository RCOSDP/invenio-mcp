# Running the stdio server

12 tools, one token, one file. What the repository side
has to provide first is in [Connecting to InvenioRDM](invenio.md).

 The dependencies are the standard library plus `mcp`,
so there is nothing to install beyond the SDK.

## 1. Issue a token

Run this inside the InvenioRDM application container:

```bash
invenio tokens create -n mcp-stdio -u <email> | tail -1 \
  | tr -d '\n' > "$PWD/.token"
chmod 600 "$PWD/.token"
```

Or issue one from the UI at
`<InvenioRDM>/account/settings/applications/tokens/new/`.

A regular account covers creating, publishing, discarding drafts and handling files.
**Withdrawing and restoring published records needs the `admin` role.**

The server reads `INVENIO_TOKEN` first and falls back to `.token` beside itself.
`.token` is gitignored; keep it at mode 600 and do not put the token in plain text in
`.mcp.json`.

## 2. TLS with a self-signed CA

Leave verification on — the default — and pass the root CA through `INVENIO_CA_BUNDLE`.
The server opens the file directly rather than relying on `SSL_CERT_FILE`, because **it
runs as a child process of the MCP client and the login shell's environment does not
always reach it**. It also reads `ca.crt` from its own directory if one is there.

## 3. Register it with a client

```json
{
  "mcpServers": {
    "inveniordm": {
      "command": "python3",
      "args": ["/path/to/invenio-mcp/stdio/server.py"],
      "env": {
        "INVENIO_API": "https://invenio.example.org/api",
        "INVENIO_CA_BUNDLE": "/path/to/ca.crt",
        "MCP_LANG": "en"
      }
    }
  }
}
```

**Restart the client after changing the configuration.** A running process keeps the
old environment, and a green check in a connection list only means "it started", not
"it works".

Tools appear as `mcp__inveniordm__<name>`.

## 4. Check it end to end

```bash
python3 stdio/server.py --selftest
```

This runs create → update → `add_file` → publish → search → soft delete → restore →
soft delete against the live instance and prints each step. **It leaves a tombstone
behind**, so point it at a demo instance with disposable data.

```bash
python3 stdio/server.py --version
```

## The 12 tools

Full descriptions and signatures are in the [tool reference](../reference/tools.md).

**Reading** — `search_records`, `get_record`

**Creating and updating** — `create_record`, `update_record`, `publish_record`,
`new_version`

**Deleting** — `delete_draft`, `delete_record`, `restore_record`

**Files** — `add_file`, `list_files`, `delete_file`

### Minimum metadata for `create_record`

```json
{
  "resource_type": {"id": "dataset"},
  "title": "A title of at least 3 characters",
  "publication_date": "2026-08-29",
  "creators": [
    {"person_or_org": {"type": "personal",
                       "family_name": "Yamada", "given_name": "Taro"}}
  ]
}
```

`resource_type.id` comes from a vocabulary (`dataset`, `publication-article`, …).
The stdio server has **no vocabulary tools** — that is one of the things the
[HTTP server](http.md) adds — so with this one the values have to be known in advance.

## Differences worth knowing

- **`update_record` replaces the whole metadata object**, it does not patch it. The
  HTTP server's `update_record` merges instead.
- **`add_file` takes `source_path`**, a path on the machine the server runs on. That
  sidesteps the base64 limit, but the bytes still travel through `web-api`. For
  gigabyte-scale files use `start_multipart_upload` in the [HTTP
  version](../concepts/files.md).
- **There is no privilege separation.** Every tool can do whatever the token can do.
  If that matters, you want the [HTTP server](http.md).

## Safety notes

- Write against a **demo instance** with disposable data.
- `delete_record` requires `confirm=True`, is a soft delete, and is recoverable with
  `restore_record`. A hard purge is not exposed over REST and is therefore not possible
  here either.
- To roll back access, delete the token: `invenio tokens delete ...`.
