# クイックスタート

動かして1回ツールを呼ぶまで、5分ほど。ここでは **HTTP 版の PAT モード**を使う。
認可サーバが要らないので、コンテナ1つとトークン1本で済む。

1ファイル版を使うなら [stdio 版を動かす](guides/stdio.md)を見ること。

## 1. InvenioRDM でトークンを発行する

UI なら `<InvenioRDM>/account/settings/applications/tokens/new/`、
アプリケーションコンテナの中からなら次のとおり。

```bash
invenio tokens create -n mcp -u <メールアドレス>
```

作成・公開・ファイルの扱いは通常のアカウントで足りる。**公開レコードの取り下げと復元には
`admin` ロールが要る**——[`mcp:curate`](concepts/authorization.md) が対応するのがそれ。

自分のインスタンスでない場合や、トークンが通らない場合は
[InvenioRDM と繋ぐ](guides/invenio.md)から始めること。リポジトリ側に要るものを
まとめてある。

## 2. サーバを起動する

```bash
cd http
cp .env.example .env
```

`INVENIO_API` と `INVENIO_UI` を自分のインスタンスに向ける。自己署名証明書なら
ルート CA を `./ca.crt` に置く（`CA_FILE` で場所を変えられる）。

```bash
docker compose up -d --build
```

起動時の表示が、何をどう解釈したかを教えてくれる。

```
MCP リソースサーバ: http://0.0.0.0:9100/mcp
  版                                : 0.0.2
  canonical URI (RFC 8707 resource) : http://127.0.0.1:9100/mcp
  認証方式 (MCP_AUTH_MODE)          : invenio
  言語 (MCP_LANG)                   : ja（利用可能: en ja）
```

## 3. ツールを呼ぶ

```bash
export PAT=<手順1で発行したトークン>

curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 400
```

検索にトークンは要らない。リポジトリなのだから、公開レコードは公開情報である。

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"search_records","arguments":{"query":"","size":3}}}'
```

身元を訊くほうにはトークンが要る。

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"whoami"}}'
```

ヘッダを外すと同じ呼び出しが `401` を返し、`WWW-Authenticate` に必要な scope が載る。
これは失敗ではなく、[発見フロー](concepts/authorization.md)が働いている姿。

## 4. 作ってみる

```bash
curl -s -X POST http://127.0.0.1:9100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
        "name":"create_record","arguments":{"metadata":{
          "resource_type":{"id":"dataset"},
          "title":"MCP から作成",
          "publication_date":"2026-08-29",
          "creators":[{"person_or_org":{"type":"personal",
                       "family_name":"山田","given_name":"太郎"}}]}}}}'
```

!!! tip "先に語彙を引かせる"

    `resource_type.id` は語彙から取る。`list_vocabulary("resourcetypes")` が正しい id を
    返すので、エージェントは当てずっぽうで書いて 400 を集めずに済む。

## 5. クライアントを繋ぐ

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:9100/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only", "--allow-http"],
      "env": {"AUTH_HEADER": "Bearer <PAT>"}
    }
  }
}
```

`--allow-http` はトークンを平文で送るので、手元の経路に限ること。Windows を含む
設定例は[クライアントから繋ぐ](guides/clients.md)にまとめてある。

## 次に

- [2つのサーバ](concepts/servers.md) — HTTP 版が何を足しているか
- [認可](concepts/authorization.md) — scope・step-up・keycloak モード
- [困ったとき](guides/troubleshooting.md) — 「繋がっているのに動かない」とき
