# 設定

すべて環境変数で決まる。実行時に設定ファイルから読むのは[言語リソース](languages.md)
だけである。

## 両方に共通

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_LANG` | システムのロケール。決まらなければ `en` | ツールの説明とエラーの言語。`en` / `ja`、または `locales/` に置いた `<tag>.json` |
| `MCP_LOCALES_DIR` | サーバの隣の `locales/` | 言語リソースの置き場 |

## stdio 版

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `INVENIO_API` | `https://localhost/api` | REST API のベース |
| `INVENIO_TOKEN` | 未設定なら `.token` を読む | Bearer トークン |
| `INVENIO_VERIFY_TLS` | `true` | TLS 検証。落とすときだけ `false` |
| `INVENIO_CA_BUNDLE` | サーバの隣の `ca.crt`（在れば） | 検証に使うルート CA |

`INVENIO_TOKEN` が `.token` より優先される。CA を `SSL_CERT_FILE` ではなくファイルとして
読むのは、MCP クライアントの子プロセスとして動くためログインシェルの環境が届かない
ことがあるからである。

## HTTP 版

### 待ち受けと身元

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_BIND_HOST` | `127.0.0.1` | 待ち受けアドレス（イメージ内では `0.0.0.0`） |
| `MCP_BIND_PORT` | `9100` | 待ち受けポート |
| `MCP_RESOURCE` | `http://<host>:<port>/mcp` | **canonical URI。** クライアントが叩く URL と一字一句同じにする |
| `MCP_AUTH_PATH` | `/mcp-auth` | [認可必須の入口](../concepts/authorization.md#mcp-auth) |

!!! danger "間違えてはいけないのは `MCP_RESOURCE`"

    これが同時に、RFC 8707 の `resource`、RFC 9728 の `resource`、すべてのトークンを
    検証する `aud` になっている。末尾のスラッシュ1つ、クライアントが `127.0.0.1` と
    言うところの `localhost` 1つで、全トークンが落ちる。

### 認証

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_AUTH_MODE` | `invenio` | `invenio`（個人アクセストークン）か `keycloak`（OAuth 2.1） |
| `KC_ISSUER` | `http://localhost:8080/realms/mcp` | Keycloak realm の issuer（keycloak モード） |
| `MCP_SERVER_CLIENT_ID` | `mcp-server` | トークン交換に使うクライアント id |
| `MCP_SERVER_SECRET` | **無し——必須** | クライアントシークレット。未設定なら起動しない |
| `INVENIO_AUDIENCE` | `invenio-api` | 交換後トークンの `aud` |
| `MCP_INVENIO_BASE_SCOPES` | `mcp:read mcp:write` | PAT モード: 認証できた全員に与える |
| `MCP_INVENIO_CURATE_ROLES` | `admin` | PAT モード: `mcp:curate` も与えるロール（カンマ区切り） |
| `MCP_INVENIO_VERIFY_TTL` | `60` | PAT モード: `/me` の結果を保持する秒数 |

`MCP_SERVER_SECRET` に既定値を置いていないのは意図的である。推測可能な値で気づかずに
動いてしまうより、その場で止まるほうがよい。

### InvenioRDM

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `INVENIO_API` | `https://127.0.0.1/api` | REST API のベース |
| `INVENIO_UI` | `https://127.0.0.1` | Web UI のベース。トークン発行の案内とプロフィール URL に使う |
| `MCP_TLS_INSECURE` | 未設定 | `1` で InvenioRDM **と** Keycloak の証明書検証を切る |
| `PLACEHOLDER_EMAIL_DOMAIN` | `jwt.invalid` | 連合認証が `mail` を返さないときに入る仮アドレスのドメイン |

自己署名 CA を信頼させる正しい手順は、システムの束に**足す**こと
（`SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` で合成ファイルを指す）。compose もマニフェストも
そうしている。CA 単体を指すと信頼の全体が置き換わる。

### ファイル

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_MAX_UPLOAD_BYTES` | `16777216`（16MiB） | 往復両方の base64 の上限 |
| `MCP_MAX_REQUEST_BYTES` | `MCP_MAX_UPLOAD_BYTES` の2倍 | 要求本文そのものの上限。認可の判定に本文を全部読むので、上限が無いと1本の POST でメモリを食い潰せる。超えると `413` |
| `MCP_MULTIPART_PART_BYTES` | `67108864`（64MiB） | multipart の既定パートサイズ |

`MCP_MAX_UPLOAD_BYTES` を上げても、大きなファイルが良い考えになるわけではない。
この上限は MCP の引数と結果が JSON であることから来ている。
[multipart](../concepts/files.md) を使うこと。

### 運用

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_AUDIT` | `on` | 標準出力に 1呼び出し1行の JSON。`off` / `0` / `false` で止まる |

監査の行には `sub`・`azp`・`scope` が載る。**トークンは決して載らない。**

## どこに書くか

| 動かし方 | 書く場所 |
| --- | --- |
| stdio 版 | クライアントの MCP 設定の `env` |
| Docker Compose | `.env`（`http/.env.example` を写す） |
| Kubernetes | `k8s/mcp-server.yaml` の `env:`。秘密は `secretKeyRef` で |
