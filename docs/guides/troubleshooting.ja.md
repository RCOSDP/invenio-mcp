# 困ったとき

## 接続一覧は ✔ なのにツールが出ない

一覧の ✔ は「プロセスが起動した」であって「動いている」ではない。

- **設定を変えたらクライアントを再起動する。** 起動済みのプロセスは古い環境変数のまま
  動く。
- stdio 版なら、同じ環境変数で手で起動して出力を見る。`locales/` が無い、`.token` が
  読めない、といった場合は起動時にメッセージを出して止まる。
- HTTP 版なら curl で `tools/list` を叩く。それが通るなら、問題はクライアント側にある。

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 200
```

## `406 Not Acceptable`

`Accept` ヘッダが `application/json` と `text/event-stream` の**両方**を含んでいる必要が
ある。Streamable HTTP はそうでない要求を拒む。curl での最も多い間違いがこれ。

## トークンが常に `invalid_token` で弾かれる

ほぼ必ず `MCP_RESOURCE` である。**クライアントが実際に叩く URL と一字一句同じ**でなければ
ならない。その文字列が同時に、RFC 8707 の `resource`、RFC 9728 の `resource`、そして
トークンを検証する `aud` になっているからである。

`http://localhost:9100/mcp` と `http://127.0.0.1:9100/mcp` は違う文字列である。
`.../mcp` と `.../mcp/` も違う。

サーバが何を広告しているか確かめる。

```bash
curl -s http://127.0.0.1:9100/.well-known/oauth-protected-resource/mcp
```

## `403 insufficient_scope`

設計どおりの応答である。認証は通ったが、そのツールに要る scope を持っていない。
応答が必要な scope を名指ししている。

- PAT モードでは `mcp:curate` は**ロール**から来る。既定は `admin`
  （`MCP_INVENIO_CURATE_ROLES`）。`whoami` で確かめる。
- 既製のクライアントは 403 を扱えないことが多い。MCP SDK が 401 でしか再認可しないため
  である。そういうものは [`/mcp-auth`](../concepts/authorization.md#mcp-auth) に向ける。
  最初から必要な scope 一式を広告している。

## クライアントがログイン画面を開かない

コールバックの待ち受けを失敗の経路でしか作らないクライアントがある。匿名で接続できる
サーバでは、その経路をそもそも通らない。最初の要求から 401 を返す `/mcp-auth` を使う。
併せて `--auth-timeout` を伸ばすこと。`mcp-remote` の既定 30 秒は実際のログインには短い。

## `Protected resource … does not match expected …`

クライアントがメタデータの `resource` と接続先 URL を比べて、食い違っている。
`/mcp-auth` に接続したなら、そこは `resource` が `/mcp-auth` で終わる**専用の**メタデータを
返さなければならない。これが、同じ資源の別の扉ではなく独立した保護リソースにしてある
理由である。

## 自己署名の InvenioRDM に対して TLS が失敗する

- **stdio:** `INVENIO_CA_BUNDLE` を設定する。クライアントの子プロセスとして動くため
  ログインシェルの `SSL_CERT_FILE` が届かないことがあり、サーバはファイルを直接読む。
- **HTTP:** CA をシステムの束に足す。`SSL_CERT_FILE` で CA 単体を指すと信頼の全体が
  置き換わり、他のすべての HTTPS 通信が壊れる。
- **Windows の `mcp-remote`:** `NODE_EXTRA_CA_CERTS`。**Node は Windows の証明書ストアを
  読まず**、ブラウザは `NODE_EXTRA_CA_CERTS` を読まない。たいてい両方が要る。
- `MCP_TLS_INSECURE=1` は在るが、検証を丸ごと切る。大事なものに対する答えにはならない。

## publish で `metadata.publication_date: Missing data for required field`

**InvenioRDM は新バージョンの下書きに公開日を引き継がない。** `new_version` は無ければ
今日の日付を埋めるので、これが出るのは下書きを別の方法で作ったとき。`publication_date` を
明示して渡す。

## `File with key ... already exists.`

`upload_file` は既定（`overwrite=True`）で消してから入れ直す。`overwrite=False` を渡した
なら、このメッセージは「何もしなかった」という報告である。

## 公開済みレコードにファイルを足せない

InvenioRDM の決まり。新バージョンを作り、そこで足して、公開する。

```python
new_version(recid, import_files=True)
upload_file(new_id, "extra.csv", content_text="...")
publish_record(new_id)
```

## `upload_file_from_url` が 403 を返す

InvenioRDM v14 の一般利用者では想定どおり。transfer 種別 `F` は `SystemProcess()` に
限られている。手元のファイルなら [`start_multipart_upload`](../concepts/files.md) を使う
——サイズの上限が無く、通常の書き込み権限で足りる。

権限があるのに失敗するなら、URL が `RECORDS_RESOURCES_FILES_ALLOWED_DOMAINS` の外に
ある可能性が高い。その場合は `Domain not allowed` になる。

## `start_multipart_upload` が署名済み URL を返さない

保存先が S3 でない可能性が高い。ローカル保存では InvenioRDM に配れる署名済み URL が
無く、アップロードは InvenioRDM 経由になる。

## ツールの説明が想定と違う言語で出る

`MCP_LANG` を読むのは**サーバのプロセス**なので、そのプロセスを設定する場所に書く。
stdio ならクライアントの `env`、HTTP ならコンテナの環境変数である。起動時の表示が、
何に解決したかを教えてくれる。[言語](../reference/languages.md)を参照。

## 監査ログを読む

サーバの標準出力に 1行1 JSON。`deny` の行には状態と要求された scope が載るので、
「なぜその呼び出しが失敗したか」はたいていそこで分かる。

```bash
docker compose logs -f mcp-server | grep '"event":"deny"'
```
