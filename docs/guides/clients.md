# Connecting a client

## Claude Desktop

### Where the configuration lives

Open it from the app: **Claude menu → Settings… → Developer → Edit Config**. That
creates the file if it does not exist yet.

| | Path |
| --- | --- |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

**Quit Claude Desktop completely and reopen it** after every change. On macOS, closing
the window does not quit the app — the process keeps the old configuration, and a
connector that shows up in the list only means "it started".

### The stdio server (macOS, Linux)

The simplest arrangement: no port, no bridge, one token in a file.

```json
{
  "mcpServers": {
    "inveniordm": {
      "command": "python3",
      "args": ["/Users/you/invenio-mcp/stdio/server.py"],
      "env": {
        "INVENIO_API": "https://invenio.example.org/api",
        "INVENIO_CA_BUNDLE": "/Users/you/invenio-mcp/stdio/ca.crt",
        "MCP_LANG": "en"
      }
    }
  }
}
```

**Use absolute paths.** Claude Desktop does not launch the server from your project
directory, and a relative path resolves somewhere you did not intend. The token comes
from `INVENIO_TOKEN` or from `.token` beside `server.py` — see [Running the stdio
server](stdio.md).

### The HTTP server, via mcp-remote (macOS, Linux)

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.example.org/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only"],
      "env": {"AUTH_HEADER": "Bearer <PAT>"}
    }
  }
}
```

Node.js has to be installed, because `mcp-remote` runs through `npx`.

### The HTTP server, via mcp-remote (Windows)

**Do not put spaces in the arguments.** On Windows, Claude Desktop launches through
`cmd` without quoting them. Keep the space in `Bearer ` inside the environment variable
instead.

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote",
               "https://mcp.example.org/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only"],
      "env": {
        "AUTH_HEADER": "Bearer <PAT>",
        "MCP_LANG": "en",
        "NODE_EXTRA_CA_CERTS": "C:\\certs\\ca.crt"
      }
    }
  }
}
```

- **Do not write a full path in `command`.** `C:\Program Files\...` breaks at the space.
- With a self-signed certificate you need `NODE_EXTRA_CA_CERTS`. **Node does not read
  the Windows certificate store**, so `certutil -addstore` alone is not enough — and
  conversely the browser does not read `NODE_EXTRA_CA_CERTS`. You generally need both.
- Add `--allow-http` for plaintext HTTP. The token then travels in the clear, so only
  over a trusted path.

In keycloak mode there is no `--header`; a browser login happens instead, and
`--auth-timeout 300` is required because the 30-second default is too short.

### Custom connectors (remote MCP, no local process)

Claude can also reach the HTTP server directly, with no `mcp-remote` and nothing running
on your machine: **Settings → Connectors → Add custom connector**, then the server's URL.
Team and Enterprise organisations add these under Organization settings instead, and
only an owner can. OAuth is supported, including a client id and secret under Advanced
settings — which is what [keycloak mode](../concepts/authorization.md) is for.

!!! warning "The connection comes from Anthropic's servers, not your machine"

    A custom connector is brokered through your Claude account, so **the URL has to be
    reachable from the public internet**. An MCP server on `127.0.0.1`, inside a campus
    network, or behind a VPN cannot be used this way. Those need `mcp-remote`, which
    connects from your own machine.

    If you do expose it, use keycloak mode. A personal access token pasted into a header
    would be held outside your institution.

### When it does not work

The logs say why. MCP connection failures land in `mcp.log`, and everything a stdio
server writes to stderr lands in `mcp-server-<name>.log`.

| | Path |
| --- | --- |
| macOS | `~/Library/Logs/Claude/` |
| Windows | `%APPDATA%\Claude\logs\` |

```bash
tail -n 20 -f ~/Library/Logs/Claude/mcp*.log     # macOS
```

```powershell
type "%APPDATA%\Claude\logs\mcp*.log"
```

Run the same command by hand with the same environment to see what it prints — a
missing `locales/` directory or an unreadable `.token` stops the server at startup with
a message that only reaches these files otherwise.

More in [Troubleshooting](troubleshooting.md).

## Claude Code

```bash
# the HTTP server
claude mcp add --transport http invenio-mcp https://<mcp>/mcp \
  --header "Authorization: Bearer $PAT"

# the stdio server
claude mcp add inveniordm python3 /path/to/invenio-mcp/stdio/server.py \
  --env INVENIO_API=https://invenio.example.org/api \
  --env INVENIO_CA_BUNDLE=/path/to/ca.crt
```

## Any other MCP client

Nothing here is Claude-specific. A client needs one of two things:

- **the stdio server** — a command to run (`python3 .../stdio/server.py`) and the
  environment to run it with, or
- **the HTTP server** — a URL, and either an `Authorization: Bearer` header (PAT mode)
  or OAuth 2.1 support (keycloak mode)

Tool names are the same either way.

## When a client only authorizes after a 401

Some clients build their OAuth callback listener solely from the failure path, so a
server that lets them connect anonymously never triggers it. Point those at
**`/mcp-auth`** instead of `/mcp` — same tools, but `401` from the first request. The
mechanics are in [Authorization](../concepts/authorization.md#mcp-auth).

```json
"args": ["-y", "mcp-remote", "https://<mcp>/mcp-auth", "--auth-timeout", "300"]
```

## Talking to it with curl

Every call is JSON-RPC over one POST. Both `Content-Type` and an `Accept` covering
`application/json` **and** `text/event-stream` are required — the MCP Streamable HTTP
transport rejects the request without them.

```bash
curl -s -X POST https://<mcp>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"my_records","arguments":{"size":5}}}'
```

`conformance/curl-tour.sh` walks the whole authorization flow this way, as a
walkthrough.

## Which language the client sees

The language is fixed **per server process** — MCP has no locale negotiation, so
`initialize` carries no locale field. For the stdio server, `MCP_LANG` goes in the
client's `env` block, because the client is what launches it. For the HTTP server it is
set where the container is configured, and every client of that instance sees the same
language. See [Languages](../reference/languages.md).
