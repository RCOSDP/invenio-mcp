# invenio-mcp

*[English version](README.md)*

InvenioRDM を **MCP（Model Context Protocol）経由で操作する**ためのサーバ。
レコードの検索・登録・更新・公開、ファイルの添付、コミュニティへの投稿と査読、
公開レコードの取り下げと復元までを、LLM クライアントからツールとして呼べる。

対象は **InvenioRDM v14**。2系統の実装が入っている。

| | `stdio/` | `http/` |
| --- | --- | --- |
| 転送 | stdio（クライアントの子プロセス） | Streamable HTTP |
| ツール数 | 12 | 33 |
| 認証 | 個人アクセストークン(PAT)1本 | OAuth 2.1 ／ PAT（切替可） |
| 権限分離 | なし（トークンの権限がすべて） | ツール単位の scope |
| 大容量ファイル | REST 経由のみ | 署名 URL で S3/MinIO へ直送 |
| 依存 | stdlib ＋ `mcp` | ＋ `httpx` / `PyJWT` / `uvicorn` |
| 想定 | 手元での試用・開発 | 複数利用者・運用 |

**迷ったら `http/`。** `stdio/` は依存が軽く1ファイルで読み切れるので、
まず動かして中身を把握したいときや、自分ひとりで使うときに向く。

## どちらも共通していること

- InvenioRDM の **REST API を叩くだけ**で、InvenioRDM 側に拡張を入れる必要がない
- 破壊的操作（公開レコードの取り下げ）は `confirm=True` を要求し、ソフト削除なので復元できる
- 最終的な権限判定は **InvenioRDM に委ねる**。MCP 側の scope は「そもそも要求できるか」の分離

## ツール

<!-- 33 ツール（http/）。stdio/ は ★ の 12 本 -->

**読取** — `search_records`★ / `get_record`★ / `list_versions` / `list_revisions` /
`my_records` / `export_record`（DataCite・JPCOAR 等12形式） / `list_vocabulary` /
`list_vocabulary_types` / `whoami`

**レコード** — `create_record`★ / `update_record`★ / `publish_record`★ /
`new_version`★ / `delete_draft`★

**取り下げ・復元** — `delete_record`★ / `restore_record`★

**ファイル** — `upload_file`(`add_file`★) / `list_files`★ / `delete_file`★ /
`download_file` / `upload_file_from_url` /
`start_multipart_upload` / `complete_multipart_upload` / `abort_multipart_upload`

**コミュニティ** — `search_communities` / `get_community` /
`list_community_records` / `create_community`

**査読・リクエスト** — `submit_to_community` / `list_requests` / `get_request` /
`comment_on_request` / `request_action`

語彙ツールがあるので、`resource_type.id` などの値を当てずっぽうで書く必要がない。
メタデータを書く前に `list_vocabulary("resourcetypes")` で確かめられる。

## 使いはじめ

```bash
# HTTP 版（PAT モード。認可サーバ不要）
cd http
cp .env.example .env      # INVENIO_API を自分の InvenioRDM に向ける
docker compose up -d --build

# トークンを発行して繋ぐ
#   <InvenioRDM>/account/settings/applications/tokens/new/
curl -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

詳細は [`http/README.md`](http/README.md) と [`stdio/README.md`](stdio/README.md)。

## ライセンス

MIT。[LICENSE](LICENSE) を参照。
