# Troubleshooting

## The client shows a green check but no tools appear

A green check in a connection list means "the process started", not "it works".

- **Restart the client after any configuration change.** A running process keeps the
  old environment.
- For the stdio server, run it by hand with the same environment and see what it prints.
  A missing `locales/` directory or an unreadable `.token` stops it at startup with a
  message.
- For the HTTP server, call `tools/list` with curl. If that works, the problem is on the
  client side.

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 200
```

## `406 Not Acceptable`

The `Accept` header has to cover **both** `application/json` and `text/event-stream`.
The Streamable HTTP transport rejects the request otherwise. This is the most common
curl mistake.

## Every token is rejected with `invalid_token`

Almost always `MCP_RESOURCE`. It must be **character-for-character the URL the client
actually calls**, because that string is simultaneously the RFC 8707 `resource`, the
RFC 9728 `resource`, and the `aud` the token is validated against.

`http://localhost:9100/mcp` and `http://127.0.0.1:9100/mcp` are different strings. So
are `.../mcp` and `.../mcp/`.

Check what the server is advertising:

```bash
curl -s http://127.0.0.1:9100/.well-known/oauth-protected-resource/mcp
```

## `403 insufficient_scope`

Working as designed: you authenticated, but the tool needs a scope you do not have.
The response names it.

- In PAT mode, `mcp:curate` comes from a **role** — `admin` by default
  (`MCP_INVENIO_CURATE_ROLES`). Check `whoami`.
- Off-the-shelf clients often cannot act on a 403, because the MCP SDK re-authorizes
  only on 401. Point those at [`/mcp-auth`](../concepts/authorization.md#mcp-auth),
  which advertises the full scope set up front.

## The client never opens a browser for login

Some clients build their OAuth callback listener only from the failure path, so a server
that lets them connect anonymously never triggers it. Use `/mcp-auth`, which is 401 from
the first request. Also raise `--auth-timeout`; `mcp-remote`'s 30-second default is too
short for a real login.

## `Protected resource … does not match expected …`

The client compared the `resource` in the metadata against the URL it connected to and
they differ. If you connected to `/mcp-auth`, it must serve **its own** metadata with
`resource` ending in `/mcp-auth` — that is why it is a separate protected resource
rather than a second door.

## TLS failures against a self-signed InvenioRDM

- **stdio:** set `INVENIO_CA_BUNDLE`. The server reads the file directly, because as a
  child process of the client it may not receive the login shell's `SSL_CERT_FILE`.
- **HTTP:** append your CA to the system bundle. Pointing `SSL_CERT_FILE` at the CA
  alone replaces the whole trust store and breaks every other HTTPS call.
- **`mcp-remote` on Windows:** `NODE_EXTRA_CA_CERTS`. **Node does not read the Windows
  certificate store**, and the browser does not read `NODE_EXTRA_CA_CERTS`. You
  generally need both.
- `MCP_TLS_INSECURE=1` exists but turns verification off entirely. It is not the answer
  for anything you care about.

## `metadata.publication_date: Missing data for required field` when publishing

**InvenioRDM does not carry the publication date into a new version's draft.**
`new_version` fills in today's date when it is missing, so this appears if you built the
draft another way. Pass `publication_date` explicitly.

## `File with key ... already exists.`

`upload_file` deletes and re-adds by default (`overwrite=True`). If you passed
`overwrite=False`, that message is the tool telling you it did nothing.

## Files cannot be added to a published record

An InvenioRDM rule. Make a new version, add there, publish:

```python
new_version(recid, import_files=True)
upload_file(new_id, "extra.csv", content_text="...")
publish_record(new_id)
```

## `upload_file_from_url` returns 403

Expected on InvenioRDM v14 for an ordinary user: transfer type `F` is restricted to
`SystemProcess()`. Use [`start_multipart_upload`](../concepts/files.md) for a local
file — no size limit, and ordinary write permission is enough.

If you do have the permission and it still fails, the URL is probably outside
`RECORDS_RESOURCES_FILES_ALLOWED_DOMAINS`, which reports `Domain not allowed`.

## No presigned URLs came back from `start_multipart_upload`

The storage is probably not S3. With local storage InvenioRDM has no presigned URLs to
hand out, and uploads go through it instead.

## Tool descriptions are in the wrong language

`MCP_LANG` is read **by the server process**, so it belongs wherever that process is
configured: the client's `env` block for stdio, the container's environment for HTTP.
The startup banner prints what it resolved. See [Languages](../reference/languages.md).

## Reading the audit log

One JSON object per line on the server's stdout. `deny` lines carry the status and the
scope that was required, which usually answers "why did that call fail" directly.

```bash
docker compose logs -f mcp-server | grep '"event":"deny"'
```
