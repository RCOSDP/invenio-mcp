# Connecting to InvenioRDM

Both servers are REST API clients. This page is what has to be true on the **InvenioRDM
side** before either of them works.

## What the instance has to provide

| | Needed for |
| --- | --- |
| **InvenioRDM v14**, reachable over HTTP(S) | everything |
| The REST API answering at `<INVENIO_API>` | everything |
| A personal access token | PAT mode, and the stdio server |
| The `admin` role on that account | `delete_record`, `restore_record`, `request_action` |
| Loaded vocabularies | `list_vocabulary`, and writing valid metadata |
| S3-compatible storage (MinIO or S3) | `start_multipart_upload` — presigned URLs |
| Accepting a Keycloak-issued JWT | **keycloak mode only** — see [below](#keycloak-mode) |

Start by checking that it answers at all. Neither of these needs a token:

```bash
curl -sk https://invenio.example.org/api/records?size=1 | head -c 200
curl -sk https://invenio.example.org/api/vocabularies/ | head -c 200
```

Then with a token — this one is the whole of PAT-mode authentication:

```bash
curl -sk -H "Authorization: Bearer $PAT" https://invenio.example.org/api/me
```

`GET /api/me` returning 200 is exactly what the HTTP server checks in PAT mode, and its
`roles` are where the scopes come from.

## Tokens

From the UI: `<InvenioRDM>/account/settings/applications/tokens/new/`.
Inside the application container:

```bash
invenio tokens create -n mcp -u <email>
```

An InvenioRDM personal access token **does not expire**. Revoking it is the only way to
end access, so treat it as a long-lived credential:

```bash
invenio tokens delete -n mcp -u <email>
```

| Account | What it can do through these servers |
| --- | --- |
| a regular user | search, create, update, publish, discard drafts, files, submit to communities |
| `admin` role | the above, plus withdrawing, restoring, accepting reviews, creating communities |

In PAT mode the HTTP server derives `mcp:curate` from the role
(`MCP_INVENIO_CURATE_ROLES`, `admin` by default). It caches `/me` for
`MCP_INVENIO_VERIFY_TTL` seconds — **failures are never cached**, so deleting a token
takes effect within the TTL.

## `INVENIO_API` and `INVENIO_UI`

```bash
INVENIO_API=https://invenio.example.org/api      # REST API base, no trailing slash
INVENIO_UI=https://invenio.example.org           # web UI base
```

`INVENIO_UI` is not decorative. It appears in the token-issuing link on the protected
resource metadata in PAT mode, and in the `profile_settings_url` that `whoami` returns
when a user has no email address set.

## TLS with a self-signed certificate

Verification is **on by default** in both servers. Do not turn it off; give them the CA.

=== "stdio"

    ```bash
    INVENIO_CA_BUNDLE=/path/to/ca.crt
    ```

    The server opens this file directly rather than relying on `SSL_CERT_FILE`, because
    it runs as a child process of the MCP client and the login shell's environment does
    not always reach it. It also picks up `ca.crt` sitting next to `server.py`.

=== "HTTP"

    **Append** the CA to the system bundle and point at the combined file:

    ```bash
    cat /etc/ssl/certs/ca-certificates.crt > /tmp/ca-bundle.crt
    cat /etc/ca/ca.crt >> /tmp/ca-bundle.crt
    export SSL_CERT_FILE=/tmp/ca-bundle.crt REQUESTS_CA_BUNDLE=/tmp/ca-bundle.crt
    ```

    Pointing `SSL_CERT_FILE` at the CA alone makes that file the *entire* trust store,
    which breaks every other HTTPS call the server makes — Keycloak included. The
    compose file and the k8s manifest both do the append for you.

`MCP_TLS_INSECURE=1` exists and disables verification for InvenioRDM **and** Keycloak.
It is for a development instance, not an answer.

## Networking

If InvenioRDM runs on the same machine as the MCP server container — a kind ingress,
another compose stack — the container cannot resolve the same hostname you use from the
host. Add it explicitly:

```yaml
extra_hosts:
  - "invenio.example.org:host-gateway"
```

If it is on another host, you do not need this.

## File storage

What the storage is changes which tools work.

| Storage | Effect |
| --- | --- |
| **S3 / MinIO** | Everything works. `start_multipart_upload` returns presigned URLs; `download_file` follows the presigned redirect on your behalf |
| **Local filesystem** | `start_multipart_upload` has no presigned URLs to hand out and reports so. Uploads go through InvenioRDM |

Two InvenioRDM settings matter for the file tools:

- **`RECORDS_RESOURCES_FILES_ALLOWED_DOMAINS`** — `upload_file_from_url` fails with
  `Domain not allowed` for anything outside it.
- **`RDMRecordPermissionPolicy.can_draft_create_files`** — the default admits ordinary
  users for transfer types `L` and `M` only. `F` (fetch-by-URL) is restricted to
  `SystemProcess()`, so `upload_file_from_url` returns 403 for a normal account. That is
  deliberate on InvenioRDM's part; making a server fetch an arbitrary URL is SSRF-shaped.

`web-api` and `worker` must both be able to reach the configured storage. Details in
[Files and transfers](../concepts/files.md).

## Vocabularies

The vocabulary tools read whatever the instance has. If `list_vocabulary_types` comes
back nearly empty, the fixtures were never loaded, and metadata writes will fail
validation on `resource_type.id` and friends. Load them the usual way
(`invenio rdm-records fixtures`).

`delete_record` validates `reason_id` against the live `removalreasons` vocabulary
rather than a hard-coded list, so a repository that adds its own reasons keeps working.

## keycloak mode: the one thing that is not stock {#keycloak-mode}

Everywhere else, these servers install nothing into InvenioRDM. **Keycloak mode is the
exception**, and it is worth being clear about why.

In that mode the token the MCP server sends to InvenioRDM is a **Keycloak-issued JWT**
with `aud=invenio-api`, obtained by RFC 8693 exchange. Stock InvenioRDM does not accept
a JWT as a bearer token — it knows personal access tokens and its own OAuth server. So
the instance needs a layer that:

1. **validates the JWT** against the Keycloak realm's JWKS and the `invenio-api`
   audience, and
2. **resolves it to a user**, creating one just in time if the subject is new, and
   linking it through `UserIdentity`.

At NII this is `invenio-jairo-jwt`. Any equivalent works — what the MCP server requires
is only that an `Authorization: Bearer <Keycloak JWT>` is accepted and acts as that
person.

!!! danger "Recreating the realm severs existing users"

    `setup_mcp_realm.py` deletes and recreates the realm if one exists. That changes
    Keycloak's `sub`, which is what `UserIdentity` keys on — every existing link breaks
    and the same person comes back as a new user. To add something to a live realm, call
    `ensure_scope()` and friends individually rather than going through
    `ensure_realm()`.

### Federated login and the missing email address

When people arrive through a federation such as GakuNin, `mail` is often not released.
InvenioRDM still needs an address, so a placeholder is stored — `@jwt.invalid` by default
(`PLACEHOLDER_EMAIL_DOMAIN`).

`whoami` reports this as `invenio.email_pending_setup: true` and returns
`profile_settings_url`. It is worth surfacing, because in that state **the user receives
no notification mail from the repository** — including review requests.

### Checking the whole chain

```bash
MCP_RESOURCE=https://<mcp>/mcp MCP_TEST_USER=... MCP_TEST_PASSWORD=... \
  python3 http/conformance/mcp_client.py
```

`whoami` is the quickest manual check: it shows the MCP-bound token, the exchanged
InvenioRDM-bound token, and the InvenioRDM user they resolved to, side by side.

## A checklist

- [ ] `GET /api/records` answers without a token
- [ ] `GET /api/me` answers 200 with the token, and shows the roles you expect
- [ ] `GET /api/vocabularies/` lists more than a handful of types
- [ ] TLS verifies without `MCP_TLS_INSECURE`
- [ ] The MCP server's container can resolve the InvenioRDM hostname
- [ ] Storage is S3 if you need multipart uploads
- [ ] *(keycloak mode)* InvenioRDM accepts a Keycloak JWT and resolves it to a user
