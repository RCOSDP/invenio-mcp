# 変更履歴

*[English](CHANGELOG.md)*

<!-- --8<-- [start:body] -->
書き方は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)。
版の付け方は [セマンティックバージョニング](https://semver.org/lang/ja/)。
**利用者が言語モデルであるときに何を破壊的変更と数えるか**は
[方針](https://rcosdp.github.io/invenio-mcp/ja/project/versioning/)に書いた。

## [Unreleased]

## [0.0.1] — 2026-08-29

**最初の公開版。** InvenioRDM を **REST API だけ**で操作する MCP サーバ2種。
リポジトリ側に入れる拡張は無い。

### Added

- **`stdio/server.py` — stdio で 12 ツール、トークン1本。** 依存は stdlib ＋ `mcp` だけ
  なので、一度で読み切れて、自分ひとりで動かせる。

- **`http/mcp_server.py` — Streamable HTTP で 33 ツール、認証方式は切り替え式。**
  `MCP_AUTH_MODE=keycloak` なら
  [MCP 2026-07-28 の認可仕様](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
  に適合するリソースサーバとして動く。RFC 9728 の保護リソースメタデータ、JWKS による
  署名検証、**`aud` が本サーバの canonical URI であることの必須検証**（他所宛トークンの
  持ち込みを拒む）、RFC 8693 のトークン交換により受信トークンを InvenioRDM へ
  **転送しない**こと。`MCP_AUTH_MODE=invenio`（既定）なら InvenioRDM の個人アクセス
  トークンをそのまま受けるので、認可サーバ自体が要らない。

- **ツール単位の scope。ただし読取は未認証で通す。** リポジトリは公開レコードを誰にでも
  見せるものだし、InvenioRDM の REST API 自体がそうなっている。検索・取得・エクスポートに
  トークンは要らない。`mcp:read` は「本人でないとできないこと」、`mcp:write` は変更、
  `mcp:curate` は公開レコードの取り下げ・復元・査読の受理・コミュニティ作成——
  InvenioRDM 側で admin 権限が要る操作——に分けてある。scope の足りない呼び出しには
  必要な scope を名指しした `403 insufficient_scope` を返すので、クライアントは
  step-up 認可に入れる。

- **`/mcp-auth`——同じ資源へのもう1本の入口で、最初の要求から 401 を返す。**
  クライアントによっては、初回接続が失敗しないと認可の準備をしない。`mcp-remote`
  0.1.37 がそれで、コールバックの待ち受けを `UnauthorizedError` の経路でしか作らない。
  本サーバは未認証でも接続できてしまうため、そのままでは認可コードの受け取り先が無い。
  RFC 9728 は `resource` が接続先 URI と一致することを求めるので、これは
  **独立した保護リソース**として専用のメタデータを持たせてある。

- **語彙ツール**（`list_vocabulary_types` / `list_vocabulary`）。これが無いとモデルは
  `resource_type.id` を当てずっぽうで書いて 400 を集める。先に確かめられるようにした。

- **ファイルを運ぶ経路を3つ。** 1つでは range を覆えないため。`upload_file` は中身を
  base64 で運ぶ（JSON に載る大きさが限界。既定 16MB）、`upload_file_from_url` は URI を
  登録して InvenioRDM に取りに行かせる、`start_multipart_upload` は署名済み URL を返し、
  クライアントが **S3(MinIO) へ直接** PUT する（本サーバも InvenioRDM も通らない）。

- **日本語と英語の言語リソース**（各サーバの隣の `locales/en.json`・`locales/ja.json`）。
  ツールの説明・エラー・起動時の表示はすべてここから読む。`MCP_LANG` で選び、未設定なら
  システムのロケール、決まらなければ英語。`<tag>.json` を置けば言語が増え、足りないキーは
  英語に落ちるので部分訳でも動く。1か所だけ意図して英語のまま残した：`WWW-Authenticate`
  ヘッダの `error_description` で、RFC 6750 がここに ASCII の一部しか許していない。
  翻訳文は同じ応答の JSON 本文に載る。

- **1呼び出し1行の監査ログ。** 標準出力に 1行1 JSON で、主体・ツール・状態・所要時間。
  **トークンは決して出さない。**

- **実インスタンスに対して走る適合検査。** `conformance/mcp_client.py` は発見フロー、
  `resource` 付き PKCE（RFC 8707）、`iss` の検証（RFC 9207）、403 からの step-up、
  別 audience 宛トークンの拒否を PASS/FAIL で報告する。
  `conformance/verify-mcp-files.py` は3経路すべてに実データを往復させ、複合 ETag と
  MD5 を手元の計算値と突き合わせる。

- **2つの形のデプロイ。** `docker-compose.yml` は PAT モードを1サービスで、
  `k8s/mcp-server.yaml` は Keycloak 構成の雛形。どちらも同じ `Dockerfile` から作る。

- **ドキュメントサイト** <https://rcosdp.github.io/invenio-mcp/>（日英）。ツール一覧は
  サーバの実装と言語リソースから生成するので、クライアントが実際に見るものとずれない。

### Security

- **資格情報に既定値を置かない。** `MCP_SERVER_SECRET` と `KC_ADMIN_PASSWORD` は
  未設定ならその場で止まる。推測可能な値で動いてしまうより良い。
- **TLS 検証は既定で有効。** 切るには `MCP_TLS_INSECURE=1` が要る。
- デモ利用者は `MCP_DEMO_USERS=yes` を付けない限り作らない（パスワードが弱いため）。

[Unreleased]: https://github.com/RCOSDP/invenio-mcp/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/RCOSDP/invenio-mcp/releases/tag/v0.0.1
<!-- --8<-- [end:body] -->
