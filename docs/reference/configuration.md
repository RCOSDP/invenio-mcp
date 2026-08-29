# Configuration

Everything is an environment variable. Nothing is read from a configuration file at run
time except the [language resources](languages.md).

## Both servers

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_LANG` | the system locale, else `en` | Language of tool descriptions and errors. `en` / `ja`, or any other `<tag>.json` in `locales/` |
| `MCP_LOCALES_DIR` | `locales/` beside the server | Where to read the language resources from |

## stdio server

| Variable | Default | Meaning |
| --- | --- | --- |
| `INVENIO_API` | `https://localhost/api` | REST API base |
| `INVENIO_TOKEN` | falls back to reading `.token` | Bearer token |
| `INVENIO_VERIFY_TLS` | `true` | TLS verification. Set `false` only to turn it off |
| `INVENIO_CA_BUNDLE` | `ca.crt` beside the server, if present | Root CA used for verification |

`INVENIO_TOKEN` wins over `.token`. The CA is read as a file rather than through
`SSL_CERT_FILE`, because the server runs as a child process of the MCP client and the
login shell's environment does not always reach it.

## HTTP server

### Binding and identity

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_BIND_HOST` | `127.0.0.1` | Listen address (`0.0.0.0` in the image) |
| `MCP_BIND_PORT` | `9100` | Listen port |
| `MCP_RESOURCE` | `http://<host>:<port>/mcp` | **The canonical URI.** Must equal the URL clients call, character for character |
| `MCP_AUTH_PATH` | `/mcp-auth` | The [authorization-required entrance](../concepts/authorization.md#mcp-auth) |

!!! danger "`MCP_RESOURCE` is the one to get right"

    It is simultaneously the RFC 8707 `resource`, the RFC 9728 `resource`, and the
    `aud` every token is validated against. A trailing slash, or `localhost` where the
    client says `127.0.0.1`, makes every token fail.

### Authentication

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_AUTH_MODE` | `invenio` | `invenio` (personal access token) or `keycloak` (OAuth 2.1) |
| `KC_ISSUER` | `http://localhost:8080/realms/mcp` | Keycloak realm issuer — keycloak mode |
| `MCP_SERVER_CLIENT_ID` | `mcp-server` | Client id used for token exchange |
| `MCP_SERVER_SECRET` | **none — required** | Client secret. Unset stops the program |
| `INVENIO_AUDIENCE` | `invenio-api` | The `aud` the exchanged token is minted for |
| `MCP_INVENIO_BASE_SCOPES` | `mcp:read mcp:write` | PAT mode: granted to anyone who authenticates |
| `MCP_INVENIO_CURATE_ROLES` | `admin` | PAT mode: roles that also get `mcp:curate` (comma-separated) |
| `MCP_INVENIO_VERIFY_TTL` | `60` | PAT mode: seconds to cache the result of `/me` |

`MCP_SERVER_SECRET` deliberately has no default. Stopping immediately beats running on
a guessable value without noticing.

### InvenioRDM

| Variable | Default | Meaning |
| --- | --- | --- |
| `INVENIO_API` | `https://127.0.0.1/api` | REST API base |
| `INVENIO_UI` | `https://127.0.0.1` | Web UI base — used for the token-issuing link and profile URL |
| `MCP_TLS_INSECURE` | unset | `1` disables certificate verification for InvenioRDM **and** Keycloak |
| `PLACEHOLDER_EMAIL_DOMAIN` | `jwt.invalid` | Domain of the placeholder address used when a federated login carries no `mail` |

The supported way to trust a self-signed CA is to **append** it to the system bundle
(`SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` pointing at the combined file), which is what
the compose file and the manifest do. Pointing at the CA alone replaces the whole trust
store.

### Files

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_MAX_UPLOAD_BYTES` | `16777216` (16MiB) | Cap on base64 content in both directions |
| `MCP_MULTIPART_PART_BYTES` | `67108864` (64MiB) | Default part size for multipart uploads |

Raising `MCP_MAX_UPLOAD_BYTES` does not make large files a good idea — the ceiling is
there because MCP arguments and results are JSON. Use
[multipart](../concepts/files.md) instead.

### Operations

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_AUDIT` | `on` | One JSON line per call on stdout. `off` / `0` / `false` disables it |

The audit line carries `sub`, `azp` and `scope`. **It never carries the token.**

## Where a setting goes

| Running as | Set it in |
| --- | --- |
| stdio server | the `env` block of the client's MCP configuration |
| Docker Compose | `.env` (copy `http/.env.example`) |
| Kubernetes | the `env:` list in `k8s/mcp-server.yaml`; secrets through `secretKeyRef` |
