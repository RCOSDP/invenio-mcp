# Quickstart

A running server and a first tool call, in about five minutes. This uses the **HTTP
server in PAT mode**, which needs no authorization server — one container and a token.

For the single-file version instead, see [Running the stdio
server](guides/stdio.md).

## 1. Get a token from InvenioRDM

Either from the UI at `<InvenioRDM>/account/settings/applications/tokens/new/`, or
inside the application container:

```bash
invenio tokens create -n mcp -u <email>
```

A regular account is enough for creating, publishing and handling files. **Withdrawing
and restoring published records needs the `admin` role** — that is what
[`mcp:curate`](concepts/authorization.md) maps to.

If the instance is not yours, or the token does not work, start from [Connecting to
InvenioRDM](guides/invenio.md) — it covers what the repository side has to provide.

## 2. Start the server

```bash
cd http
cp .env.example .env
```

Point `INVENIO_API` and `INVENIO_UI` at your own instance. If it uses a self-signed
certificate, put the root CA at `./ca.crt` (or set `CA_FILE`).

```bash
docker compose up -d --build
```

The banner tells you what it decided:

```
MCP resource server: http://0.0.0.0:9100/mcp
  version                           : 0.0.1
  canonical URI (RFC 8707 resource) : http://127.0.0.1:9100/mcp
  auth mode (MCP_AUTH_MODE)         : invenio
  language (MCP_LANG)               : en (available: en ja)
```

## 3. Call a tool

```bash
export PAT=<the token from step 1>

curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 400
```

Searching needs no token at all — this is a repository, and published records are
public:

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"search_records","arguments":{"query":"","size":3}}}'
```

Ask it who you are, and this one does need the token:

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"whoami"}}'
```

Without the header the same call answers `401` with a `WWW-Authenticate` naming the
scope it wanted. That is the [discovery flow](concepts/authorization.md) working, not a
failure.

## 4. Create something

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
        "name":"create_record","arguments":{"metadata":{
          "resource_type":{"id":"dataset"},
          "title":"Created from MCP",
          "publication_date":"2026-08-29",
          "creators":[{"person_or_org":{"type":"personal",
                       "family_name":"Yamada","given_name":"Taro"}}]}}}}'
```

!!! tip "Let the model check the vocabulary first"

    `resource_type.id` comes from a vocabulary. `list_vocabulary("resourcetypes")`
    returns the valid ids, which is why an agent does not have to guess and collect
    400s.

## 5. Point a client at it

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:9100/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only", "--allow-http"],
      "env": {"AUTH_HEADER": "Bearer <PAT>"}
    }
  }
}
```

`--allow-http` sends the token in the clear, so keep it to a local path. The full set
of client recipes, including Windows, is in [Connecting a
client](guides/clients.md).

## Next

- [The two servers](concepts/servers.md) — what the HTTP version adds
- [Authorization](concepts/authorization.md) — scopes, step-up, and keycloak mode
- [Troubleshooting](guides/troubleshooting.md) — when the client says it connected but
  nothing works
