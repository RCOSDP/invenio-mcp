# Deployment

Both shapes build from the **same `Dockerfile`**, so the image you test with compose is
the image the manifests run.

## Docker Compose

The default is PAT mode, which needs nothing but this one service.

```bash
cd http
cp .env.example .env
docker compose up -d --build
```

The compose file does one thing worth knowing about. It **appends** your root CA to the
system bundle rather than pointing `SSL_CERT_FILE` at the CA alone:

```bash
cat /etc/ssl/certs/ca-certificates.crt > /tmp/ca-bundle.crt
[ -f /etc/ca/ca.crt ] && cat /etc/ca/ca.crt >> /tmp/ca-bundle.crt
```

Pointing at the CA by itself would make that file the *entire* trust store, breaking
every other HTTPS call the server makes. If your certificate is publicly trusted, delete
the `volumes:` entry altogether.

!!! tip "When InvenioRDM is on the same machine"

    If InvenioRDM is reachable on the host (a kind ingress, another compose stack), the
    container cannot resolve the same hostname. Uncomment `extra_hosts:` and put the
    real hostname there. If it lives on another host, you do not need this.

The healthcheck fetches the protected resource metadata, which is unauthenticated by
definition — a good liveness signal that needs no credential.

## Kubernetes

`http/k8s/mcp-server.yaml` is a **template** (Service + Deployment + Ingress), written
for keycloak mode. Replace these:

| Template value | Replace with |
| --- | --- |
| `MCP_IMAGE` | the image you built |
| `*.example.org` | your real hostnames (three of them) |
| `namespace: invenio-mcp` | your namespace |
| `ca-issuer` / `nginx` / `nodeType=APP` | your ClusterIssuer, ingress class, node selector |

You also have to provide:

- **ConfigMaps `ca-bundle` and `ca-bootstrap`** — a bootstrap that **appends** the
  self-signed CA to the system CA bundle, for the reason above.
- **`MCP_SERVER_SECRET`** in the Secret `mcp-server-secret`. There is no default; the
  server stops without it.

```bash
export KC_BASE=https://<keycloak>
export KC_ADMIN_PASSWORD=<admin password>
export MCP_SERVER_SECRET=<the secret>
export MCP_RESOURCE=https://<mcp>/mcp
python3 keycloak/setup_mcp_realm.py
kubectl apply -f k8s/mcp-server.yaml
```

## Settings that matter in production

| Variable | Why |
| --- | --- |
| `MCP_RESOURCE` | **Character-for-character the URL clients call.** Everything about audience validation hangs off this one string |
| `MCP_TLS_INSECURE` | Leave unset. It disables certificate verification for both InvenioRDM and Keycloak |
| `MCP_AUDIT` | Leave on. One JSON line per call, and it never contains the token |
| `MCP_LANG` | Fixed per process. Two languages means two deployments |
| `MCP_MAX_UPLOAD_BYTES` | Caps base64 in both directions. Raising it does not make large files a good idea — use [multipart](../concepts/files.md) |

Full list: [Configuration](../reference/configuration.md).

## Scaling

The server is **stateless** (`stateless_http=True`, JSON responses), so replicas need no
shared session store and no sticky routing. Two caches live in each process and are
purely optimisations:

- the exchanged-token cache (keycloak mode), keyed by the incoming token
- the `/me` result cache (PAT mode), held for `MCP_INVENIO_VERIFY_TTL` seconds

A new replica simply repeats a token exchange or a `/me` call once. **Failures are never
cached**, so revoking a token takes effect within the TTL on every replica.

## Publishing the documentation

This site lives on a **`gh-pages` branch**, which GitHub Pages serves directly.
`tools/deploy-docs.sh` builds it and pushes with `mkdocs gh-deploy`. It runs on a
maintainer's machine, not in CI — there is no CI here at all, and
[Contributing](../project/contributing.md#the-checks) says why.

Enable it once, on the repository:

> **Settings → Pages → Source: Deploy from a branch → `gh-pages` / `(root)`**

Or from the command line, once the branch exists:

```bash
gh api -X POST repos/RCOSDP/invenio-mcp/pages \
  -f 'source[branch]=gh-pages' -f 'source[path]=/'
```

!!! warning "`gh-pages` is generated — never edit it"

    `tools/deploy-docs.sh` is its only writer, and it pushes with `--force`. Anything
    committed there by hand is gone at the next deploy. Everything that belongs to the
    site lives under `docs/` on `main`.

Before it pushes anything, the script regenerates the [tool
reference](../reference/tools.md) and stops if it differs from what is committed, so the
published list cannot fall behind the code. It also stops on a dirty working tree and
warns when `HEAD` is not on `origin` — a published page that cannot be found in the
repository is worse than an outdated one.

```bash
pip install -r docs/requirements.txt
mkdocs serve                          # English at /, Japanese at /ja/
bash tools/deploy-docs.sh --dry-run   # check and build, publish nothing
bash tools/deploy-docs.sh             # publish. Needs push rights
```
