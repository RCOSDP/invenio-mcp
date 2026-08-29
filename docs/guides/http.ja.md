# HTTP 版を動かす

Streamable HTTP で 33 ツール。認証方式は `MCP_AUTH_MODE` で選ぶ。リポジトリ側に要るものは
[InvenioRDM と繋ぐ](invenio.md)にある——keycloak モードだけが必要とする、素の
InvenioRDM には無いものも含めて。

|  | `invenio`（PAT・既定） | `keycloak` |
| --- | --- | --- |
| クライアントが提示するもの | InvenioRDM の個人アクセストークン | OAuth 2.1 で得たトークン |
| 認可サーバ | 不要 | Keycloak（realm `mcp`） |
| ブラウザでのログイン | 起きない | 起きる |
| scope の出どころ | InvenioRDM の**ロール**から導く | トークンの `scope` クレーム |
| トークン交換 | なし（宛先が同じ） | RFC 8693 で `aud=invenio-api` へ |
| MCP 2026-07-28 適合 | ×（認可サーバが無い） | ○ |

## PAT モード

```bash
cd http
cp .env.example .env      # INVENIO_API / INVENIO_UI を自分のインスタンスに向ける
docker compose up -d --build
```

InvenioRDM が自己署名証明書なら、ルート CA を `./ca.crt` に置く（`CA_FILE` で変更可）。
compose ファイルはそれをシステムの CA 束に**足す**。束ごと置き換えると、サーバが行う
他のすべての HTTPS 通信が壊れるからである。

InvenioRDM 側でトークンを発行する。

```bash
invenio tokens create -n mcp -u <メールアドレス>
# UI なら <InvenioRDM>/account/settings/applications/tokens/new/
```

### ロールから scope を導く

個人アクセストークンに scope の概念は無いので、`GET /api/me` が返す**ロール**から
組み立てる。素の InvenioRDM が持つロールをそのまま使うので、追加の語彙も拡張も要らない。

| 設定 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_INVENIO_BASE_SCOPES` | `mcp:read mcp:write` | 認証できた全員に与える |
| `MCP_INVENIO_CURATE_ROLES` | `admin` | このロールにだけ `mcp:curate` も与える |
| `MCP_INVENIO_VERIFY_TTL` | `60` | `/me` の結果を保持する秒数 |

`/me` の結果は TTL のあいだ保持する。毎リクエスト往復させないためである。
**失敗はキャッシュしない**——トークンを消したら効かなくなる必要がある。

!!! warning "PAT モードに audience による分離は無い"

    提示されるトークンが*そもそも* InvenioRDM のトークンなので、交換する先が無く、
    リポジトリに直接使うことも止められない。それが認可サーバを要らなくすることの代価
    である。そこが問題になるなら keycloak モードを使う。

### なぜ InvenioRDM を認可サーバにしないのか

`invenio-oauth2server` は PKCE も認可サーバメタデータ（RFC 8414）も動的登録も持たない。
`/.well-known/*` は 404 を返し、コードに `code_challenge` は無い。認可サーバに据えると、
本サーバが在りもしないメタデータを捏造し、PKCE 無しを飲み、クライアントを手で登録する
足場を用意することになる——そのうえで、それでも MCP 適合には届かない。

どちらの道でも **InvenioRDM に届くのは InvenioRDM のトークン**であり、違うのは入手方法
だけである。ならば手間の少ないほうを採る。

## keycloak モード

```bash
export KC_BASE=https://<keycloak>
export KC_ADMIN_PASSWORD=<Keycloak の管理者パスワード>
export MCP_SERVER_SECRET=<mcp-server クライアントのシークレット>
export MCP_RESOURCE=https://<mcp>/mcp
python3 keycloak/setup_mcp_realm.py
```

`KC_ADMIN_PASSWORD` と `MCP_SERVER_SECRET` に**既定値は無い**。推測可能な値で黙って
動いてしまうより、その場で止まるほうがよい。同じ `MCP_SERVER_SECRET` をサーバにも渡す。

!!! danger "`setup_mcp_realm.py` は既存の realm を削除して作り直す"

    作り直すと Keycloak の `sub` が変わり、InvenioRDM の `UserIdentity` が壊れて
    既存の利用者の紐付けが切れる。稼働中の realm に何かを足すときは、`ensure_realm()` を
    通さず `ensure_scope()` などを個別に呼ぶこと。

デモ利用者（`researcher`・`rdmadmin`）は既定では**作らない**。要るなら
`MCP_DEMO_USERS=yes` を付ける。**パスワードが弱いので、捨ててよい realm に限ること。**

`keycloak/setup_gakunin_idp.py` は学認 SAML ブローカを足す（任意）。

デプロイは[デプロイ](deployment.md)にまとめてある。

## canonical URI

`MCP_RESOURCE` は**クライアントが実際に叩く URL と一字一句同じ**でなければならない。
`resource`（RFC 8707）・`resource`（RFC 9728）・トークンの `aud` が揃うのは、この1本の
文字列によってである。末尾のスラッシュ1つ、クライアントが `127.0.0.1` と言うところの
`localhost` 1つで、すべてのトークンが検証に落ちる。

## 監査ログ

標準出力に 1行1 JSON。コンテナのログ収集にそのまま載る。

```json
{"ts":"2026-08-29T12:00:00+0900","event":"call","path":"/mcp",
 "method":"tools/call","tool":"create_record","status":200,"ms":412,
 "sub":"3f2b...","azp":"mcp-client","scope":"mcp:read mcp:write"}
```

`event` は `call`・`tool_error`（ツールは走って失敗した——これは HTTP 200 ＋ `isError` で
返る）・`deny`（チャレンジを返した）のいずれか。**トークンは決して出さない。**
止めるには `MCP_AUDIT=off`。

## 確かめ方

```bash
# 認可仕様の適合（PASS/FAIL）
MCP_RESOURCE=https://<mcp>/mcp MCP_TEST_USER=... MCP_TEST_PASSWORD=... \
  python3 conformance/mcp_client.py

# ファイル3経路（16点）
MCP_RESOURCE=https://<mcp>/mcp INVENIO_UI=https://<invenio> \
  python3 conformance/verify-mcp-files.py

# curl だけで認可フローを追う教材
bash conformance/curl-tour.sh
```
