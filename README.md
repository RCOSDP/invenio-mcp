# invenio-mcp

*[日本語版はこちら / Japanese version](README.ja.md)*

MCP (Model Context Protocol) servers for **operating InvenioRDM from an LLM client**.
Search, create, update and publish records; attach files; submit to communities and
run the review workflow; withdraw and restore published records — all exposed as tools.

Targets **InvenioRDM v14**. Two implementations are included.

| | `stdio/` | `http/` |
| --- | --- | --- |
| Transport | stdio (child process of the client) | Streamable HTTP |
| Tools | 12 | 33 |
| Authentication | one personal access token (PAT) | OAuth 2.1 **or** PAT (switchable) |
| Privilege separation | none (whatever the token can do) | per-tool scopes |
| Large files | through the REST API only | presigned URLs straight to S3/MinIO |
| Dependencies | stdlib + `mcp` | + `httpx` / `PyJWT` / `uvicorn` |
| Intended for | trying it out, local development | multiple users, real operation |

**Start with `http/` unless you have a reason not to.** `stdio/` is a single file with
almost no dependencies, which makes it a good way to read the whole thing and to run it
for yourself alone.

## What both share

- They only call the **InvenioRDM REST API**. Nothing has to be installed into InvenioRDM.
- The destructive operation (withdrawing a published record) requires `confirm=True`,
  and it is a soft delete, so it can be restored.
- The final permission decision is left to **InvenioRDM**. The MCP scopes only separate
  *what a client may ask for*.

## Tools

<!-- 33 tools in http/. The 12 marked ★ are the ones stdio/ also has. -->

**Read** — `search_records`★ / `get_record`★ / `list_versions` / `list_revisions` /
`my_records` / `export_record` (12 formats incl. DataCite) / `list_vocabulary` /
`list_vocabulary_types` / `whoami`

**Records** — `create_record`★ / `update_record`★ / `publish_record`★ /
`new_version`★ / `delete_draft`★

**Withdraw and restore** — `delete_record`★ / `restore_record`★

**Files** — `upload_file` (`add_file`★) / `list_files`★ / `delete_file`★ /
`download_file` / `upload_file_from_url` /
`start_multipart_upload` / `complete_multipart_upload` / `abort_multipart_upload`

**Communities** — `search_communities` / `get_community` /
`list_community_records` / `create_community`

**Reviews and requests** — `submit_to_community` / `list_requests` / `get_request` /
`comment_on_request` / `request_action`

Because the vocabulary tools are there, an agent never has to guess at values such as
`resource_type.id`. It can check with `list_vocabulary("resourcetypes")` before writing
any metadata.

## Getting started

```bash
# HTTP version, PAT mode — no authorization server needed
cd http
cp .env.example .env      # point INVENIO_API at your own InvenioRDM
docker compose up -d --build

# Issue a token and connect
#   <InvenioRDM>/account/settings/applications/tokens/new/
curl -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

See [`http/README.md`](http/README.md) and [`stdio/README.md`](stdio/README.md) for details.

## License

MIT. See [LICENSE](LICENSE).
