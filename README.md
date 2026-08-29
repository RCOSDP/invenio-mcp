# invenio-mcp

*[日本語版はこちら / Japanese version](README.ja.md)*

[![docs](https://img.shields.io/badge/docs-rcosdp.github.io%2Finvenio--mcp-teal)](https://rcosdp.github.io/invenio-mcp/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![InvenioRDM](https://img.shields.io/badge/InvenioRDM-v14-informational)](https://inveniordm.docs.cern.ch/)
[![MCP](https://img.shields.io/badge/MCP%20authorization-2026--07--28-informational)](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

**Documentation: <https://rcosdp.github.io/invenio-mcp/>**

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
- Everything a user sees — tool descriptions, error messages, the startup banner — comes
  from language resources. **English and Japanese ship by default**; `MCP_LANG` selects
  one.

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

## Language

Tool descriptions and error messages are read from `locales/<tag>.json`, which sits
next to each server (`stdio/locales/`, `http/locales/`). `en.json` and `ja.json` are
included.

| `MCP_LANG` | Result |
| --- | --- |
| `en` | English |
| `ja` | Japanese |
| unset | taken from the system locale (`LC_ALL` / `LC_MESSAGES` / `LANG`), English if that does not resolve |
| anything else | English (an explicit unknown tag does not fall back to the system locale) |

Adding a language means dropping another `<tag>.json` into `locales/` — the server
picks up whatever is there. Any key missing from it falls back to English, so a partial
translation still runs. MCP has no locale negotiation in the protocol, so **the language
is per process**: to serve two languages at once, run two instances.

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

See [`http/README.md`](http/README.md) and [`stdio/README.md`](stdio/README.md) for the
short version, or the [documentation site](https://rcosdp.github.io/invenio-mcp/) for
the full one — concepts, guides, the generated tool reference and every setting.

## Project

- [Changelog](CHANGELOG.md) — [Semantic Versioning](https://rcosdp.github.io/invenio-mcp/project/versioning/);
  both servers carry the same version
- [Contributing](CONTRIBUTING.md) — and the
  [full guide](https://rcosdp.github.io/invenio-mcp/project/contributing/)
- [Security](SECURITY.md) — report privately through GitHub, not as an issue
- [Code of conduct](CODE_OF_CONDUCT.md)

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
