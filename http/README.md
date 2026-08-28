# HTTP version — Streamable HTTP with switchable authentication (33 tools)

*[日本語版はこちら / Japanese version](README.ja.md)*

A resource server following the
[MCP Authorization specification of 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
The authentication method is selected with `MCP_AUTH_MODE`.

| | `invenio` (PAT, default) | `keycloak` |
| --- | --- | --- |
| What the client presents | an InvenioRDM personal access token | a token obtained through OAuth 2.1 |
| Authorization server | not needed | Keycloak (realm `mcp`) |
| Browser login | never happens | happens |
| Where scopes come from | derived from InvenioRDM **roles** | the token's `scope` claim |
| Token exchange | none (same audience) | RFC 8693, into `aud=invenio-api` |
| Conforms to MCP 2026-07-28 | no (there is no authorization server) | yes |

## Files

| | |
| --- | --- |
| `mcp_server.py` | the server |
| `Dockerfile` | based on `python:3.12-slim`; shared by compose and k8s |
| `docker-compose.yml` | standalone run, PAT mode by default |
| `.env.example` | configuration template |
| `k8s/mcp-server.yaml` | Service + Deployment + Ingress (assumes keycloak mode) |
| `keycloak/setup_mcp_realm.py` | builds realm `mcp` through the Admin REST API |
| `keycloak/setup_gakunin_idp.py` | adds the GakuNin SAML broker (optional) |
| `conformance/mcp_client.py` | headless end-to-end conformance check with PASS/FAIL |
| `conformance/curl-tour.sh` | walks the authorization flow with nothing but curl |

## Running in PAT mode

```bash
cp .env.example .env
# Point INVENIO_API / INVENIO_UI at your own InvenioRDM.
# If it is self-signed, put the root CA at ./ca.crt (CA_FILE changes the location).
docker compose up -d --build
```

Issue the token on the InvenioRDM side:

```bash
# From the UI:  <InvenioRDM>/account/settings/applications/tokens/new/
# From the CLI: invenio tokens create -n mcp -u <email>
```

### Deriving scopes from roles

A PAT carries no scopes, so the MCP scopes are assembled from the **roles** returned by
`GET /api/me`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `MCP_INVENIO_BASE_SCOPES` | `mcp:read mcp:write` | granted to anyone who authenticates |
| `MCP_INVENIO_CURATE_ROLES` | `admin` | only these roles also get `mcp:curate` |
| `MCP_INVENIO_VERIFY_TTL` | `60` | seconds to cache the result of `/me` |

This uses nothing but stock InvenioRDM roles — no extra vocabulary, no extension to install.

## Running in keycloak mode

```bash
export KC_BASE=https://<keycloak>  MCP_RESOURCE=https://<mcp>/mcp
python3 keycloak/setup_mcp_realm.py          # build realm mcp
kubectl apply -f k8s/mcp-server.yaml         # after substituting JC2_MCP_IMAGE
```

> **`setup_mcp_realm.py` deletes and recreates the realm if one already exists.**
> Recreating it changes Keycloak's `sub`, which breaks `UserIdentity` in InvenioRDM and
> severs existing user links. To add something to a live realm, call `ensure_scope()` and
> friends individually instead of going through `ensure_realm()`.

`k8s/mcp-server.yaml` assumes the following, which belong to a larger deployment. Adapt
them if you use it on its own.

- ConfigMaps `jc2-ca` and `jc2-ca-bootstrap` (a bootstrap that **appends** the self-signed
  CA to the system CA bundle rather than replacing it)
- `MCP_SERVER_SECRET` in the Secret `jc2-backend`
- cert-manager ClusterIssuer `jc2-ca-issuer` and ingress class `nginx`
- `nodeSelector: nodeType=APP`

## Scopes and tools

| Scope | Tools |
| --- | --- |
| (none — unauthenticated) | searching and fetching published records, listing and downloading files, vocabularies, exports, versions, reading communities |
| `mcp:read` | `whoami` / `my_records` / `list_revisions` / `list_requests` / `get_request` |
| `mcp:write` | create, update, publish, discard draft, new version, file operations, submitting to a community, commenting |
| `mcp:curate` | `delete_record` / `restore_record` / `request_action` / `create_community` |

Reading public information is left unauthenticated because a repository shows published
records to everyone — the InvenioRDM REST API behaves the same way. Authorization is
required only for things that need to be *you*.

`mcp:curate` is separated from `mcp:write` because withdrawing a published record and
accepting a review are **destructive operations that require the admin role in
InvenioRDM**, which is a different weight from discarding a draft. It is named after the
capability rather than the role (`admin`) because what it grants is limited to withdrawing
and restoring records and accepting reviews — not administration in general.

## Connecting a client

### Claude Desktop on Windows

Bridge stdio to HTTP with `mcp-remote`. **Do not put spaces in the arguments** — on
Windows, Claude Desktop launches through `cmd` without quoting them. Keep the space in
`Bearer ` inside the environment variable instead.

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote",
               "https://<mcp>/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only"],
      "env": {
        "AUTH_HEADER": "Bearer <PAT>",
        "NODE_EXTRA_CA_CERTS": "C:\\certs\\ca.crt"
      }
    }
  }
}
```

- Node.js has to be installed on Windows (for `npx`).
- Do not write a full path in `command`. `C:\Program Files\...` breaks at the space.
- With a self-signed certificate you need `NODE_EXTRA_CA_CERTS`. **Node does not read the
  Windows certificate store**, so `certutil -addstore` alone is not enough — and
  conversely the browser does not read `NODE_EXTRA_CA_CERTS`. You generally need both.
- Add `--allow-http` for plaintext HTTP. The PAT then travels in the clear, so only do
  this over a trusted path.

In keycloak mode there is no `--header`; a browser login happens instead, and
`--auth-timeout 300` is required because the 30-second default is too short.

### Conformance test

```bash
MCP_RESOURCE=https://<mcp>/mcp MCP_TEST_USER=... MCP_TEST_PASSWORD=... \
  python3 conformance/mcp_client.py
```

It measures and reports PASS/FAIL for: the 401 on an unauthenticated call, discovery from
`resource_metadata`, PKCE (S256) with `resource` (RFC 8707), `iss` validation per RFC 9207,
the 403 on insufficient scope followed by step-up re-authorization, and rejection of a
token issued for a different audience.

## Caveats

- PAT mode has **no audience separation via `aud`**. That follows structurally from the
  token being an InvenioRDM token in the first place. Use keycloak mode if you need
  conformance with MCP 2026-07-28.
- `MCP_RESOURCE` must be **character-for-character the URL the client actually calls**.
  That is what makes `resource` (RFC 8707), `resource` (RFC 9728) and the token's `aud`
  line up.
- Defaults such as `mcp-server-secret`, `researcher` and `Gakunin1!` are placeholders for
  a proof of concept. **Replace them in any real deployment.**
