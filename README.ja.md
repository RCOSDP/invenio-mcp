# invenio-mcp

*[English version](README.md)*

[![docs](https://img.shields.io/badge/docs-rcosdp.github.io%2Finvenio--mcp-teal)](https://rcosdp.github.io/invenio-mcp/ja/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![InvenioRDM](https://img.shields.io/badge/InvenioRDM-v14-informational)](https://inveniordm.docs.cern.ch/)
[![MCP](https://img.shields.io/badge/MCP%20authorization-2026--07--28-informational)](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

**ドキュメント: <https://rcosdp.github.io/invenio-mcp/ja/>**

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
- 利用者に見える文字列（ツールの説明・エラー・起動時の表示）は言語リソースから読む。
  **日本語と英語を標準で同梱**し、`MCP_LANG` で選ぶ

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

## 言語

ツールの説明とエラーは、各サーバの隣にある `locales/<tag>.json`
（`stdio/locales/`・`http/locales/`）から読む。`en.json` と `ja.json` を同梱している。

| `MCP_LANG` | 結果 |
| --- | --- |
| `ja` | 日本語 |
| `en` | 英語 |
| 未設定 | システムのロケール（`LC_ALL` / `LC_MESSAGES` / `LANG`）に従う。決まらなければ英語 |
| それ以外 | 英語（明示した未知のタグは、システムのロケールへは落とさない） |

言語を足すには `locales/` に `<tag>.json` を置くだけでよく、サーバは在るものを拾う。
足りないキーは英語に落ちるので、途中まで訳した状態でも動く。MCP のプロトコルには
言語交渉が無いため、**言語はプロセス単位**で決まる。2言語を同時に出すならインスタンスを2つ立てる。

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

短い説明は [`http/README.md`](http/README.md) と [`stdio/README.md`](stdio/README.md) に、
詳しくは[ドキュメントサイト](https://rcosdp.github.io/invenio-mcp/ja/)に——考え方・手引き・
生成しているツール一覧・設定の全項目。

## プロジェクト

- [変更履歴](CHANGELOG.ja.md) — [セマンティックバージョニング](https://rcosdp.github.io/invenio-mcp/ja/project/versioning/)。
  2つのサーバは同じ版を持つ
- [参加する](CONTRIBUTING.md) —[詳しい手引き](https://rcosdp.github.io/invenio-mcp/ja/project/contributing/)
- [セキュリティ](SECURITY.md) — 公開の issue ではなく GitHub の非公開報告から
- [行動規範](CODE_OF_CONDUCT.md)

## ライセンス

MIT。[LICENSE](LICENSE) と [NOTICE](NOTICE) を参照。
