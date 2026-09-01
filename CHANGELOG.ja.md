# 変更履歴

*[English](CHANGELOG.md)*

<!-- --8<-- [start:body] -->
書き方は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)。
版の付け方は [セマンティックバージョニング](https://semver.org/lang/ja/)。
**利用者が言語モデルであるときに何を破壊的変更と数えるか**は
[方針](https://rcosdp.github.io/invenio-mcp/ja/project/versioning/)に書いた。

## [Unreleased]

### Security

- **キャッシュに生のトークンを置かなくなり、期限切れを捨てるようになった。** 検証結果
  （PAT モードの `/me` の応答）と交換後トークンは、受け取ったトークンそのものをキーに
  した dict に入れていた。dict のキーはプロセスのメモリに残り続け、TTL が過ぎた項目を
  捨てる処理もどこにも無かった——つまり、もう使えない交換後トークンを抱えたまま、項目
  数だけが増え続けていた。どちらも `TokenCache` にまとめ、キーはトークンの SHA-256 の
  要約に変え、引くたびに期限切れを捨てるようにした。挙動は変わらない。

### Changed

- **GitHub Actions のワークフローを廃し、検査を手元に一本化した。** `ci`・`docs`・
  `release` の3本を `tools/` の3つのスクリプトに移した——`check.sh`（コンパイル、
  ツール数と説明、言語資源のキー一致、`__version__` の一致、生成したツール一覧、
  `mkdocs build --strict`）、`deploy-docs.sh`（検査 → ビルド → `gh-pages` へ
  `gh-deploy`）、`release.sh`（タグと `__version__` の一致、変更履歴の節、検査、
  イメージのビルド、`CHANGELOG.md` からのリリースノート。`--publish` を付けない限り
  何も出さない）。見ていたものは1つも減らしていない。同じ検査を2か所に置くことが、
  両者をずらす。だから1か所にした。

### Documentation

- **認証の章を足した。** 「考え方 → 認証」に、3通りの構成（stdio・PAT・keycloak）で
  身元がどう届き、それぞれ何を検証しているか、無効な資格情報を決して匿名に落とさない
  のはなぜか、学認によるフェデレーション認証、そして失敗の症状と原因をまとめた。
  認可のページはその続きから始まるようにした。

## [0.0.2] — 2026-08-29

**セキュリティ修正の版。** ドキュメントどおりに使っているクライアントには何も変わらない。
変わるのは、探しに行ったときに届く先である。このうち1件は実際に成立していた——
`download_file` は、中身が URL のファイルを上げるだけで SSRF にできた。残りは、
開いてはいたがまだ露出していなかった構造を閉じたものである。

### Security

- **`TOOL_SCOPES` に書き忘れたツールが未認証で開かなくなった。** `TOOL_SCOPES.get()` は
  「公開してよい」と「表に無い」の両方で `None` を返していたので、write ツールを足して
  書き忘れると誰でも呼べるようになっていた。import 時に登録済みツールと突き合わせ、
  食い違っていれば**起動しない**。
- **scope 検査が JSON-RPC のバッチを見るようになった。** バッチ（配列）は
  `isinstance(payload, dict)` を素通りして検査されずに流れていた。いまの SDK が配列を
  400 で弾くので実害は無かったが、守っていたのは SDK のふるまいであってこちらではなく、
  バッチを通す SDK なら認可が丸ごと迂回された。バッチ内のすべての `tools/call` を見て、
  一番厳しい要求を採る。
- **`download_file` がファイルの中身に書かれた URL を追わなくなった。** S3 保存では
  InvenioRDM が本文に署名済み URL を入れて返すため、サーバはそれを追っていた。同じ形は
  **中身が URL のファイルを1つ上げる**だけで作れるので、任意の URL を取りに行かせて
  応答まで受け取れる SSRF になっていた。応答の長さが登録サイズと違うときだけ署名済み
  URL として読む（ファイル本体は必ず自分の大きさで返る）。
- **`recid`・ファイル名などを URL のパス片1つとして符号化するようにした。**
  `quote()` の既定は `/` を残すので、`../` を含む値は意図と別のエンドポイントに届いた。
- **要求本文に上限を設けた**（`MCP_MAX_REQUEST_BYTES`、添付上限の2倍）。認可の判定には
  本文が全部要るので、上限が無いと1本の POST でメモリを食い潰せた。超えると `413`。
- **stdio 版の `add_file(source_path=...)` が、プロセスの読めるファイルを何でも読むこと
  を明記した。** 設計どおりではあるが、呼び出すのは言語モデルなので、プロンプト
  インジェクションの的になる。名前を付けておく価値がある。

### Fixed

- **`search_records` がクエリを URL エンコードするようにした。** `&size=10000` を含む
  クエリが、InvenioRDM への要求に別のパラメータとして差し込まれていた。
- **バッチが拒否されたときの監査の行が、実際に拒否されたツールを載せるようにした。**
  それまではバッチの先頭の要素を載せていた。

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

[Unreleased]: https://github.com/RCOSDP/invenio-mcp/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/RCOSDP/invenio-mcp/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/RCOSDP/invenio-mcp/releases/tag/v0.0.1
<!-- --8<-- [end:body] -->
