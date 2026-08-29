# 言語

人とモデルが読むもの——ツールの説明・エラー・起動時の表示——はすべて言語リソースから
読む。**日本語と英語を標準で同梱している。**

コード中の注釈は別の話で、開発者向けなのでそのままにしてある。

## 選び方

| `MCP_LANG` | 結果 |
| --- | --- |
| `ja` | 日本語 |
| `en` | 英語 |
| 未設定 | システムのロケール（`LC_ALL`・`LC_MESSAGES`・`LANG`）に従う。決まらなければ英語 |
| それ以外 | 英語——明示した未知のタグは、システムのロケールへ**落とさない** |

システム流儀の書き方も通る。`ja_JP.UTF-8`・`ja-JP`・`JA` はいずれも `ja` になる。
地域付きの資源が在ればそちらを優先するので、`LANG=ja_JP.UTF-8` では `ja-jp.json` が
`ja.json` より先に選ばれる。

起動時の表示が、何に解決したかと、どの言語が見つかったかを教えてくれる。

```
  言語 (MCP_LANG)                   : ja（利用可能: en ja）
```

## ファイルの場所

```
http/locales/en.json     stdio/locales/en.json
http/locales/ja.json     stdio/locales/ja.json
```

各サーバの隣に置いてある。サーバを写せば、その文言も一緒に付いてくるようにするため。
`MCP_LOCALES_DIR` で別の場所を指せる。

2つのサーバでファイルが分かれているのは、ツールが違い、言うことも違うからである。
stdio 側の説明は短く、scope の話も出てこない。

## 書き方

入れ子のキーと、文字列または「改行で連結される行の配列」。配列の形が在るのは、長い
説明文を JSON のままでも読めて差分が取れる形に保つためである。

```json
{
  "tools": {
    "publish_record": "下書きを公開する（mcp:write）。",
    "search_records": [
      "公開レコードを検索する（**未認証でも可**）。",
      "",
      "トークンがあればその人として検索するので、自分の下書きなども対象になる。"
    ]
  },
  "errors": {
    "file_exists": "'{filename}' は既にある。置き換えるなら overwrite=True"
  }
}
```

`{name}` は `str.format` で埋める。**書式引数を渡したときだけ** format するので、
説明文の中の波括弧——`resource_type{id}` や JSON の例——はそのまま残る。

## 言語を足す

`en.json` を写して訳し、`<tag>.json` として置くだけでよい。サーバはディレクトリに
在るものを拾うので、登録の手続きは無い。

**足りないキーは英語に落ちる**ので、1つ訳した時点から正しく動く。どの言語にも無いキーは
キー名がそのまま出る。見苦しいのは意図的で、気づかれるためにそうしてある。

CI は `en.json` と `ja.json` のキーが完全に一致することを検査する。片方にしか無いキーも
*動いてしまう*（黙って英語に落ちる）——それこそが、放っておけば気づかれない理由である。

## 1か所だけ英語のまま

`WWW-Authenticate` ヘッダの `error_description`。RFC 6750 がここに ASCII の一部しか
許していないので、翻訳した文字列を入れられない。ヘッダには英語を載せ、同じ 401 / 403
応答の JSON 本文に翻訳を載せる。

```http
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer error="invalid_token", scope="mcp:write",
  resource_metadata="https://mcp.example.org/.well-known/oauth-protected-resource/mcp",
  error_description="tool 'create_record' requires authorization"

{"error": "invalid_token",
 "error_description": "ツール 'create_record' には認可が要る",
 "required_scope": "mcp:write"}
```

## 言語はプロセス単位

MCP に言語交渉は無く、`initialize` にロケールの項目も無いので、サーバがクライアント
ごとに変えることはできない。2言語を出すなら、`MCP_LANG` の違うインスタンスを2つ立てる。

stdio 版では、これは見た目ほどの制約ではない。プロセスを起動するのはクライアントなので、
クライアントの `env` に書いた `MCP_LANG` は既に利用者ごとの設定になっている。

## モデルが見ているもの

このサイトの[ツール一覧](tools.md)は同じファイルから生成している。日英どちらのページも、
サーバがクライアントに渡している文字列そのものを表示している。
