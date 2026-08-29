# クライアントから繋ぐ

## Claude Desktop

### 設定ファイルの場所

アプリから開ける。**Claude メニュー → 設定… → 開発者 → 構成を編集**。ファイルが無ければ
そこで作られる。

| | パス |
| --- | --- |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

**変更のたびに Claude Desktop を完全に終了して開き直す。** macOS ではウィンドウを閉じても
終了しない——プロセスは古い設定のまま動き続ける。一覧にコネクタが出ることは
「起動できた」以上を意味しない。

### stdio 版（macOS・Linux）

いちばん単純な形。ポートも橋渡しも要らず、トークンはファイル1本。

```json
{
  "mcpServers": {
    "inveniordm": {
      "command": "python3",
      "args": ["/Users/you/invenio-mcp/stdio/server.py"],
      "env": {
        "INVENIO_API": "https://invenio.example.org/api",
        "INVENIO_CA_BUNDLE": "/Users/you/invenio-mcp/stdio/ca.crt",
        "MCP_LANG": "ja"
      }
    }
  }
}
```

**絶対パスで書くこと。** Claude Desktop はプロジェクトのディレクトリからサーバを起動する
わけではないので、相対パスは意図しない場所に解決される。トークンは `INVENIO_TOKEN` か、
`server.py` の隣の `.token` から読む（[stdio 版を動かす](stdio.md)を参照）。

### HTTP 版を mcp-remote 経由で（macOS・Linux）

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.example.org/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only"],
      "env": {"AUTH_HEADER": "Bearer <PAT>"}
    }
  }
}
```

`mcp-remote` は `npx` で動くので、Node.js が要る。

### HTTP 版を mcp-remote 経由で（Windows）

**引数に空白を入れないこと。** Windows の Claude Desktop は `cmd` 経由で起動し、引数を
引用符で囲まない。`Bearer ` の空白は環境変数の側に置く。

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote",
               "https://mcp.example.org/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only"],
      "env": {
        "AUTH_HEADER": "Bearer <PAT>",
        "MCP_LANG": "ja",
        "NODE_EXTRA_CA_CERTS": "C:\\certs\\ca.crt"
      }
    }
  }
}
```

- **`command` にフルパスを書かない。** `C:\Program Files\...` は空白で壊れる。
- 自己署名証明書なら `NODE_EXTRA_CA_CERTS` が要る。**Node は Windows の証明書ストアを
  読まない**ので `certutil -addstore` だけでは足りず、逆にブラウザは
  `NODE_EXTRA_CA_CERTS` を読まない。たいてい両方が要る。
- 平文 HTTP なら `--allow-http` を足す。トークンが平文で流れるので、信頼できる経路に
  限ること。

keycloak モードでは `--header` は無く、代わりにブラウザでのログインが起きる。既定の
30 秒では短すぎるので `--auth-timeout 300` が要る。

### カスタムコネクタ（リモート MCP・手元にプロセスを置かない）

`mcp-remote` を使わず、手元で何も動かさずに HTTP 版へ繋ぐこともできる。
**設定 → コネクタ → カスタムコネクタを追加**にサーバの URL を入れる。Team と Enterprise
では組織設定の側から追加し、追加できるのは所有者だけである。OAuth に対応していて、
詳細設定でクライアント ID とシークレットも指定できる——[keycloak モード](../concepts/authorization.md)が
まさにそのための構成である。

!!! warning "接続元は手元の機械ではなく Anthropic のサーバ"

    カスタムコネクタは Claude のアカウント側を経由するので、**URL がインターネットから
    到達できる必要がある**。`127.0.0.1` に居るサーバ、学内ネットワークの中、VPN の
    向こうにあるものはこの方法では使えない。それらは、手元の機械から接続する
    `mcp-remote` を使う。

    公開するなら keycloak モードにすること。ヘッダに貼った個人アクセストークンは、
    機関の外に置かれることになる。

### 動かないとき

理由はログに出る。MCP の接続失敗は `mcp.log` に、stdio サーバが標準エラーに書いたものは
`mcp-server-<名前>.log` に落ちる。

| | パス |
| --- | --- |
| macOS | `~/Library/Logs/Claude/` |
| Windows | `%APPDATA%\Claude\logs\` |

```bash
tail -n 20 -f ~/Library/Logs/Claude/mcp*.log     # macOS
```

```powershell
type "%APPDATA%\Claude\logs\mcp*.log"
```

同じ環境変数で同じコマンドを手で走らせて、何が出るか見るのも早い。`locales/` が無い、
`.token` が読めないといった場合はサーバが起動時にメッセージを出して止まるが、そのままでは
このログにしか届かない。

続きは[困ったとき](troubleshooting.md)。

## Claude Code

```bash
# HTTP 版
claude mcp add --transport http invenio-mcp https://<mcp>/mcp \
  --header "Authorization: Bearer $PAT"

# stdio 版
claude mcp add inveniordm python3 /path/to/invenio-mcp/stdio/server.py \
  --env INVENIO_API=https://invenio.example.org/api \
  --env INVENIO_CA_BUNDLE=/path/to/ca.crt
```

## その他の MCP クライアント

ここに書いたことに Claude 固有のものは無い。クライアントに要るのはどちらかである。

- **stdio 版** — 実行するコマンド（`python3 .../stdio/server.py`）と、それを動かす環境変数
- **HTTP 版** — URL と、`Authorization: Bearer` ヘッダ（PAT モード）または
  OAuth 2.1 への対応（keycloak モード）

ツール名はどちらでも同じである。

## 401 を見ないと認可を始めないクライアント

コールバックの待ち受けを失敗の経路でしか作らないクライアントがある。匿名で接続できる
サーバでは、その経路をそもそも通らない。そういうクライアントは `/mcp` ではなく
**`/mcp-auth`** に向ける——ツールは同じで、最初の要求から `401` を返す。仕組みは
[認可](../concepts/authorization.md#mcp-auth)にある。

```json
"args": ["-y", "mcp-remote", "https://<mcp>/mcp-auth", "--auth-timeout", "300"]
```

## curl で叩く

呼び出しはすべて POST 1本の JSON-RPC。`Content-Type` と、`application/json` **および**
`text/event-stream` を含む `Accept` の両方が要る。MCP の Streamable HTTP はこれが無いと
要求を拒む。

```bash
curl -s -X POST https://<mcp>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $PAT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"my_records","arguments":{"size":5}}}'
```

`conformance/curl-tour.sh` が同じやり方で認可フロー全体を追う教材になっている。

## クライアントに見える言語

言語は**サーバのプロセス単位**で決まる。MCP に言語交渉が無く、`initialize` に
ロケールの項目が無いためである。stdio 版はクライアントが起動するので `MCP_LANG` を
クライアントの `env` に書く。HTTP 版はコンテナの設定側で決め、そのインスタンスに繋ぐ
全員が同じ言語を見る。[言語](../reference/languages.md)を参照。
