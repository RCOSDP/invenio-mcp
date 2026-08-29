# stdio 版を動かす

12 ツール、トークン1本、ファイル1つ。リポジトリ側に先に要るものは
[InvenioRDM と繋ぐ](invenio.md)にある。

依存は標準ライブラリと `mcp` だけなので、
SDK のほかに入れるものは無い。

## 1. トークンを発行する

InvenioRDM のアプリケーションコンテナの中で実行する。

```bash
invenio tokens create -n mcp-stdio -u <メールアドレス> | tail -1 \
  | tr -d '\n' > "$PWD/.token"
chmod 600 "$PWD/.token"
```

UI から出すなら `<InvenioRDM>/account/settings/applications/tokens/new/`。

作成・公開・下書きの破棄・ファイルの扱いは通常のアカウントで足りる。
**公開レコードの取り下げと復元には `admin` ロールが要る。**

サーバはまず `INVENIO_TOKEN` を見て、無ければ自分の隣の `.token` を読む。`.token` は
gitignore してあり、600 のまま置くこと。`.mcp.json` に平文で書かないこと。

## 2. 自己署名 CA での TLS

検証は既定のまま**有効**にして、ルート CA を `INVENIO_CA_BUNDLE` で渡す。
サーバは `SSL_CERT_FILE` に頼らずファイルを直接開く。**MCP クライアントの子プロセスとして
動くので、ログインシェルの環境が届かないことがある**ためである。自分のディレクトリに
`ca.crt` が在ればそれも読む。

## 3. クライアントに登録する

```json
{
  "mcpServers": {
    "inveniordm": {
      "command": "python3",
      "args": ["/path/to/invenio-mcp/stdio/server.py"],
      "env": {
        "INVENIO_API": "https://invenio.example.org/api",
        "INVENIO_CA_BUNDLE": "/path/to/ca.crt",
        "MCP_LANG": "ja"
      }
    }
  }
}
```

**設定を変えたらクライアントを再起動する。** 起動済みのプロセスは古い環境変数のまま
動くし、接続一覧の ✔ は「起動できた」しか見ていない。

ツールは `mcp__inveniordm__<name>` として現れる。

## 4. 通しで確かめる

```bash
python3 stdio/server.py --selftest
```

作成 → 更新 → `add_file` → 公開 → 検索 → ソフト削除 → 復元 → ソフト削除 を実インスタンスに
対して走らせ、各段階を表示する。**tombstone が残る**ので、捨ててよいデータのデモ
インスタンスに向けること。

```bash
python3 stdio/server.py --version
```

## 12 のツール

説明と引数は[ツール一覧](../reference/tools.md)にある。

**読取** — `search_records`・`get_record`

**作成と更新** — `create_record`・`update_record`・`publish_record`・`new_version`

**削除** — `delete_draft`・`delete_record`・`restore_record`

**ファイル** — `add_file`・`list_files`・`delete_file`

### `create_record` に要る最小のメタデータ

```json
{
  "resource_type": {"id": "dataset"},
  "title": "3文字以上のタイトル",
  "publication_date": "2026-08-29",
  "creators": [
    {"person_or_org": {"type": "personal",
                       "family_name": "山田", "given_name": "太郎"}}
  ]
}
```

`resource_type.id` は語彙から取る（`dataset`・`publication-article` など）。
stdio 版に**語彙ツールは無い**——それは [HTTP 版](http.md)が足しているものの1つ——ので、
こちらでは値をあらかじめ知っている必要がある。

## 知っておくとよい違い

- **`update_record` はメタデータ全体を置き換える。** 部分更新ではない。HTTP 版の
  `update_record` はマージする。
- **`add_file` は `source_path` を取る。** サーバが動いている機械の上のパスで、base64 の
  上限を避けられる。ただしバイト列は `web-api` を通る。GB 級のファイルには
  [HTTP 版](../concepts/files.md)の `start_multipart_upload` を使うこと。
- **権限分離は無い。** どのツールも、トークンにできることは全部できる。それが問題になる
  なら [HTTP 版](http.md)を使う。

## 安全のために

- 書き込みは、捨ててよいデータの**デモインスタンス**に対して行うこと。
- `delete_record` は `confirm=True` を要求し、ソフト削除で、`restore_record` で戻せる。
  ハード削除は REST に無いので、ここでもできない。
- 権限を戻すにはトークンを消す（`invenio tokens delete ...`）。
