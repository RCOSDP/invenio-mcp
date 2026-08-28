# HTTP 版 — Streamable HTTP ＋ 認証切替（33 ツール）

*[English version](README.md)*

MCP の [Authorization 仕様 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
に沿ったリソースサーバ。認証方式を `MCP_AUTH_MODE` で切り替えられる。

| | `invenio`（PAT・既定） | `keycloak` |
| --- | --- | --- |
| クライアントが渡すもの | InvenioRDM の個人アクセストークン | OAuth 2.1 で取得したトークン |
| 認可サーバ | 不要 | Keycloak（realm `mcp`） |
| ブラウザでのログイン | 起きない | 起きる |
| scope の出どころ | InvenioRDM の**ロール**から導出 | トークンの `scope` クレーム |
| トークン交換 | なし（宛先が同一） | RFC 8693 で `aud=invenio-api` に変換 |
| MCP 2026-07-28 適合 | ×（認可サーバが無いので） | ○ |

## ファイル

| | |
| --- | --- |
| `mcp_server.py` | サーバ本体 |
| `Dockerfile` | `python:3.12-slim` ベース。compose と k8s が共用 |
| `docker-compose.yml` | 単体起動（既定は PAT モード） |
| `.env.example` | 設定の雛形 |
| `k8s/mcp-server.yaml` | Service ＋ Deployment ＋ Ingress（keycloak モード想定） |
| `keycloak/setup_mcp_realm.py` | realm `mcp` を Admin REST API で構成 |
| `keycloak/setup_gakunin_idp.py` | 学認（GakuNin）SAML ブローカを足す（任意） |
| `conformance/mcp_client.py` | 仕様適合の headless E2E（PASS/FAIL 判定） |
| `conformance/curl-tour.sh` | curl だけで認可フローを追う教材 |

## PAT モードで動かす

```bash
cp .env.example .env
# INVENIO_API / INVENIO_UI を自分の InvenioRDM に向ける。
# 自己署名なら CA を ./ca.crt に置く（CA_FILE で場所を変えられる）。
docker compose up -d --build
```

トークンは InvenioRDM 側で発行する。

```bash
# UI から:  <InvenioRDM>/account/settings/applications/tokens/new/
# CLI から: invenio tokens create -n mcp -u <email>
```

### ロールから scope を導く

PAT には scope の概念が無いので、`GET /api/me` が返す **ロール**から MCP scope を組み立てる。

| 設定 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_INVENIO_BASE_SCOPES` | `mcp:read mcp:write` | 認証できた全員に与える |
| `MCP_INVENIO_CURATE_ROLES` | `admin` | このロールの人にだけ `mcp:curate` |
| `MCP_INVENIO_VERIFY_TTL` | `60` | `/me` による検証結果を保持する秒数 |

素の InvenioRDM のロールを使うだけなので、語彙の追加も拡張の導入も要らない。

## keycloak モードで動かす

```bash
export KC_BASE=https://<keycloak>
export KC_ADMIN_PASSWORD=<Keycloak 管理者のパスワード>
export MCP_SERVER_SECRET=<mcp-server クライアントのシークレット>
export MCP_RESOURCE=https://<mcp>/mcp
python3 keycloak/setup_mcp_realm.py          # realm mcp を構成
kubectl apply -f k8s/mcp-server.yaml         # 雛形の値を置換してから
```

`KC_ADMIN_PASSWORD` と `MCP_SERVER_SECRET` に**既定値は無い**。設定し忘れたまま
推測できる値で動いてしまうより、その場で止まる方がよいため。
`MCP_SERVER_SECRET` はサーバ側にも同じ値を渡す。

動作確認用のデモ利用者（`researcher` / `rdmadmin`）は既定では作らない。
必要なら `MCP_DEMO_USERS=yes` を付ける。**パスワードが弱いので、使い捨ての realm でのみ。**

> **`setup_mcp_realm.py` は realm が既存なら削除して作り直す。**
> 作り直すと Keycloak の `sub` が変わり、InvenioRDM の `UserIdentity` が切れて
> 既存ユーザの紐付けが壊れる。稼働中の realm に追加だけしたいときは、
> `ensure_realm()` を呼ばずに `ensure_scope()` 等を個別に叩くこと。

`k8s/mcp-server.yaml` は**雛形**で、次を自分の環境の値に置き換える。

| 雛形の値 | 置き換える先 |
| --- | --- |
| `MCP_IMAGE` | ビルドしたイメージ |
| `*.example.org` | 実際のホスト名（3か所） |
| `namespace: invenio-mcp` | 実際の namespace |
| `ca-issuer` / `nginx` / `nodeType=APP` | 自分のクラスタの ClusterIssuer・IngressClass・nodeSelector |

あわせて次を用意しておく。

- ConfigMap `ca-bundle` / `ca-bootstrap` — 自己署名 CA をシステム CA 束に**足す**
  ブートストラップ。CA 単体で差し替えると外部 HTTPS が壊れるので、必ず追記にする
- Secret `mcp-server-secret` の `MCP_SERVER_SECRET`

## scope とツールの対応

| scope | ツール |
| --- | --- |
| （不要・未認証可） | 公開レコードの検索・取得、ファイル一覧・取得、語彙、エクスポート、バージョン、コミュニティ参照 |
| `mcp:read` | `whoami` / `my_records` / `list_revisions` / `list_requests` / `get_request` |
| `mcp:write` | 作成・更新・公開・下書き破棄・新バージョン・ファイル操作・コミュニティへの投稿・コメント |
| `mcp:curate` | `delete_record` / `restore_record` / `request_action` / `create_community` |

公開情報の読取を未認証で通すのは、リポジトリが誰にでも公開レコードを見せるものだから
（InvenioRDM の REST API 自体がそうなっている）。認可が要るのは「本人でないとできないこと」だけ。

`mcp:curate` を `mcp:write` から分けているのは、公開レコードの取り下げと査読の受理が
**InvenioRDM 側で admin 権限を要する破壊的操作**で、下書きを捨てるのとは重さが違うため。
ロール名（`admin`）ではなく能力名にしてあるのは、渡す力が「公開レコードの取り下げと復元、
査読の受理」に限られ、管理者一般ではないから。

## クライアントから繋ぐ

### Claude Desktop（Windows）

`mcp-remote` を stdio ブリッジとして挟む。**引数に空白を入れないこと**
（Claude Desktop は Windows では cmd 経由で起動し、引数を引用符で囲まない）。
`Bearer ` の空白は環境変数側に寄せる。

```json
{
  "mcpServers": {
    "invenio-mcp": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote",
               "https://<mcp>/mcp",
               "--header", "Authorization:${AUTH_HEADER}",
               "--transport", "http-only"],
      "env": {
        "AUTH_HEADER": "Bearer <PAT>",
        "NODE_EXTRA_CA_CERTS": "C:\\certs\\ca.crt"
      }
    }
  }
}
```

- Windows に Node.js が要る（`npx` を使うため）
- `command` にフルパスを書かない。`C:\Program Files\...` は空白で切れる
- 自己署名なら `NODE_EXTRA_CA_CERTS` が要る。**Node は Windows の証明書ストアを見ない**ので、
  `certutil -addstore` だけでは通らない（逆にブラウザは `NODE_EXTRA_CA_CERTS` を見ない）
- 平文 HTTP に繋ぐときは `--allow-http` を足す。PAT が平文で流れるので信頼できる経路でのみ

keycloak モードでは `--header` の代わりにブラウザでのログインが起き、`--auth-timeout 300` が要る。

### 適合テスト

```bash
MCP_RESOURCE=https://<mcp>/mcp MCP_TEST_USER=... MCP_TEST_PASSWORD=... \
  python3 conformance/mcp_client.py
```

未認証での 401、`resource_metadata` からの発見、PKCE(S256) ＋ `resource`(RFC 8707)、
RFC 9207 の `iss` 検証、scope 不足の 403 → step-up 再認可、別 audience のトークン拒否
までを実測して PASS/FAIL を出す。

## 注意

- PAT モードでは **`aud` によるオーディエンス分離が無い**。トークンが InvenioRDM 宛
  そのものなので構造的にそうなる。MCP 2026-07-28 適合が要るなら keycloak モードを使う
- `MCP_RESOURCE` は**クライアントが実際に叩く URL と一字一句同じ**にすること。
  RFC 8707 の `resource`、RFC 9728 の `resource`、トークンの `aud` がこれで揃う
- 資格情報に既定値は置いていない。`MCP_SERVER_SECRET` と `KC_ADMIN_PASSWORD` は
  未設定なら起動・実行時に止まる
- デモ利用者は既定では作られない（`MCP_DEMO_USERS=yes` のときだけ）。
  そのパスワードは弱いので、使い捨ての realm 以外では使わない
