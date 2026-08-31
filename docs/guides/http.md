# Running the HTTP server

33 tools over Streamable HTTP, with the authentication method chosen by
`MCP_AUTH_MODE`. This page is how to run each mode; what each one actually verifies is
in [Authentication](../concepts/authentication.md). What the repository side has to
provide is in [Connecting to InvenioRDM](invenio.md) — including the one thing keycloak
mode needs that stock InvenioRDM does not have.

|  | `invenio` (PAT, default) | `keycloak` |
| --- | --- | --- |
| What the client presents | an InvenioRDM personal access token | a token obtained through OAuth 2.1 |
| Authorization server | not needed | Keycloak (realm `mcp`) |
| Browser login | never happens | happens |
| Where scopes come from | derived from InvenioRDM **roles** | the token's `scope` claim |
| Token exchange | none (same audience) | RFC 8693, into `aud=invenio-api` |
| Conforms to MCP 2026-07-28 | no — there is no authorization server | yes |

## PAT mode

```bash
cd http
cp .env.example .env      # point INVENIO_API / INVENIO_UI at your instance
docker compose up -d --build
```

If InvenioRDM uses a self-signed certificate, put the root CA at `./ca.crt` (or set
`CA_FILE`). The compose file **appends** it to the system CA bundle rather than
replacing it — replacing the bundle outright breaks every other HTTPS call the server
makes.

Issue a token on the InvenioRDM side:

```bash
invenio tokens create -n mcp -u <email>
# or the UI: <InvenioRDM>/account/settings/applications/tokens/new/
```

### Scopes from roles

A personal access token carries no scopes, so they are assembled from the **roles**
returned by `GET /api/me`. This uses stock InvenioRDM roles — no extra vocabulary, no
extension to install.

| Setting | Default | Meaning |
| --- | --- | --- |
| `MCP_INVENIO_BASE_SCOPES` | `mcp:read mcp:write` | granted to anyone who authenticates |
| `MCP_INVENIO_CURATE_ROLES` | `admin` | only these roles also get `mcp:curate` |
| `MCP_INVENIO_VERIFY_TTL` | `60` | seconds to cache the result of `/me` |

The result of `/me` is cached for the TTL so that every request does not make a round
trip. **Failures are never cached** — deleting a token has to take effect.

!!! warning "PAT mode has no audience separation"

    The token you present *is* an InvenioRDM token, so there is nothing to exchange it
    into, and nothing stops it being used directly against the repository. That is the
    price of not needing an authorization server. Use keycloak mode where it matters.

### Why not make InvenioRDM the authorization server?

`invenio-oauth2server` has no PKCE, no authorization server metadata (RFC 8414) and no
dynamic client registration — `/.well-known/*` returns 404 and there is no
`code_challenge` in the code. Putting it in that role would mean this server fabricating
metadata that does not exist, accepting the absence of PKCE, and needing somewhere to
register clients by hand — and it still would not reach MCP conformance.

Either way, **what reaches InvenioRDM is an InvenioRDM token**. Only the way of
obtaining it differs. So the simpler route wins.

## keycloak mode

```bash
export KC_BASE=https://<keycloak>
export KC_ADMIN_PASSWORD=<Keycloak admin password>
export MCP_SERVER_SECRET=<secret for the mcp-server client>
export MCP_RESOURCE=https://<mcp>/mcp
python3 keycloak/setup_mcp_realm.py
```

`KC_ADMIN_PASSWORD` and `MCP_SERVER_SECRET` **have no defaults**: stopping immediately
beats silently running on a guessable value. Pass the same `MCP_SERVER_SECRET` to the
server.

!!! danger "`setup_mcp_realm.py` deletes and recreates the realm if one exists"

    Recreating it changes Keycloak's `sub`, which breaks `UserIdentity` in InvenioRDM
    and severs existing user links. To add something to a live realm, call
    `ensure_scope()` and friends individually instead of going through
    `ensure_realm()`.

The demo users (`researcher`, `rdmadmin`) are **not** created by default. Add
`MCP_DEMO_USERS=yes` if you want them. **Their passwords are weak, so only do this in a
throwaway realm.**

`keycloak/setup_gakunin_idp.py` adds the GakuNin SAML broker, which is optional.

Deployment is covered in [Deployment](deployment.md).

## The canonical URI

`MCP_RESOURCE` must be **character-for-character the URL the client actually calls**.
That single string is what makes `resource` (RFC 8707), `resource` (RFC 9728) and the
token's `aud` line up. A trailing slash or `localhost` where the client says `127.0.0.1`
is enough to make every token fail validation.

## The audit log

One JSON object per line on stdout, so it lands in whatever collects container logs:

```json
{"ts":"2026-08-29T12:00:00+0900","event":"call","path":"/mcp",
 "method":"tools/call","tool":"create_record","status":200,"ms":412,
 "sub":"3f2b...","azp":"mcp-client","scope":"mcp:read mcp:write"}
```

`event` is `call`, `tool_error` (the tool ran and failed — those come back as HTTP 200
with `isError`) or `deny` (the challenge was returned). **The token is never logged.**
Set `MCP_AUDIT=off` to turn it off.

## Checking it

```bash
# the authorization specification, PASS/FAIL
MCP_RESOURCE=https://<mcp>/mcp MCP_TEST_USER=... MCP_TEST_PASSWORD=... \
  python3 conformance/mcp_client.py

# all three file transfer paths, 16 assertions
MCP_RESOURCE=https://<mcp>/mcp INVENIO_UI=https://<invenio> \
  python3 conformance/verify-mcp-files.py

# the authorization flow with nothing but curl, as a walkthrough
bash conformance/curl-tour.sh
```
