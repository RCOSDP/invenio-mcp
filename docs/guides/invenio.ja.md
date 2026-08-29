# InvenioRDM と繋ぐ

どちらのサーバも REST API のクライアントである。このページは、そのどちらかを動かす前に
**InvenioRDM の側**で満たされている必要のあることをまとめたものである。

## インスタンスに要るもの

| | 何のために |
| --- | --- |
| **InvenioRDM v14** に HTTP(S) で到達できること | すべて |
| `<INVENIO_API>` で REST API が応答すること | すべて |
| 個人アクセストークン | PAT モードと stdio 版 |
| そのアカウントの `admin` ロール | `delete_record`・`restore_record`・`request_action` |
| 語彙が投入されていること | `list_vocabulary`、および妥当なメタデータを書くこと |
| S3 互換のストレージ（MinIO か S3） | `start_multipart_upload`（署名済み URL） |
| Keycloak が発行した JWT を受け付けること | **keycloak モードのみ**——[後述](#keycloak) |

まず応答するかどうかから確かめる。次の2つにトークンは要らない。

```bash
curl -sk https://invenio.example.org/api/records?size=1 | head -c 200
curl -sk https://invenio.example.org/api/vocabularies/ | head -c 200
```

次にトークン付きで。PAT モードの認証はこれがすべてである。

```bash
curl -sk -H "Authorization: Bearer $PAT" https://invenio.example.org/api/me
```

`GET /api/me` が 200 を返すこと——HTTP 版が PAT モードで見ているのはまさにこれで、
返ってくる `roles` が scope の出どころになる。

## トークン

UI からは `<InvenioRDM>/account/settings/applications/tokens/new/`。
アプリケーションコンテナの中からは次のとおり。

```bash
invenio tokens create -n mcp -u <メールアドレス>
```

InvenioRDM の個人アクセストークンに**有効期限は無い**。アクセスを終わらせる方法は失効
させることだけなので、長命の資格情報として扱うこと。

```bash
invenio tokens delete -n mcp -u <メールアドレス>
```

| アカウント | このサーバ経由でできること |
| --- | --- |
| 通常の利用者 | 検索・作成・更新・公開・下書きの破棄・ファイル・コミュニティへの投稿 |
| `admin` ロール | 上記に加えて、取り下げ・復元・査読の受理・コミュニティの作成 |

PAT モードでは、HTTP 版が `mcp:curate` をロールから導く（`MCP_INVENIO_CURATE_ROLES`、
既定は `admin`）。`/me` の結果は `MCP_INVENIO_VERIFY_TTL` 秒だけ保持するが、
**失敗はキャッシュしない**ので、トークンを消せば TTL のうちに効く。

## `INVENIO_API` と `INVENIO_UI`

```bash
INVENIO_API=https://invenio.example.org/api      # REST API のベース。末尾のスラッシュ無し
INVENIO_UI=https://invenio.example.org           # Web UI のベース
```

`INVENIO_UI` は飾りではない。PAT モードの保護リソースメタデータに出るトークン発行の
案内と、メールアドレスが未設定の利用者に対して `whoami` が返す `profile_settings_url` が
これを使う。

## 自己署名証明書での TLS

どちらのサーバも検証は**既定で有効**である。切るのではなく、CA を渡すこと。

=== "stdio"

    ```bash
    INVENIO_CA_BUNDLE=/path/to/ca.crt
    ```

    サーバは `SSL_CERT_FILE` に頼らずこのファイルを直接開く。MCP クライアントの子プロセス
    として動くため、ログインシェルの環境が届かないことがあるからである。`server.py` の
    隣に置いた `ca.crt` も拾う。

=== "HTTP"

    CA をシステムの束に**足して**、合成したファイルを指す。

    ```bash
    cat /etc/ssl/certs/ca-certificates.crt > /tmp/ca-bundle.crt
    cat /etc/ca/ca.crt >> /tmp/ca-bundle.crt
    export SSL_CERT_FILE=/tmp/ca-bundle.crt REQUESTS_CA_BUNDLE=/tmp/ca-bundle.crt
    ```

    `SSL_CERT_FILE` で CA 単体を指すと、そのファイルが信頼の*すべて*になり、サーバが行う
    他のすべての HTTPS 通信——Keycloak を含む——が壊れる。compose ファイルと k8s の
    マニフェストは、この連結を代わりに行っている。

`MCP_TLS_INSECURE=1` は在るが、InvenioRDM **と** Keycloak の両方で検証を切る。
開発用インスタンスのためのものであって、答えではない。

## ネットワーク

InvenioRDM が MCP サーバのコンテナと同じ機械に居る場合——kind の ingress、別の compose
スタックなど——コンテナからは、ホストで使っているのと同じホスト名を引けない。明示する。

```yaml
extra_hosts:
  - "invenio.example.org:host-gateway"
```

別のホストに居るなら要らない。

## ファイルストレージ

何を保存先にしているかで、使えるツールが変わる。

| 保存先 | 影響 |
| --- | --- |
| **S3 / MinIO** | すべて動く。`start_multipart_upload` が署名済み URL を返し、`download_file` が署名済みリダイレクトを代わりに辿る |
| **ローカルファイルシステム** | `start_multipart_upload` に配れる署名済み URL が無く、その旨を返す。アップロードは InvenioRDM を通る |

ファイル系ツールに効く InvenioRDM 側の設定が2つある。

- **`RECORDS_RESOURCES_FILES_ALLOWED_DOMAINS`** — ここに無い URL に対して
  `upload_file_from_url` は `Domain not allowed` で失敗する。
- **`RDMRecordPermissionPolicy.can_draft_create_files`** — 既定は transfer 種別 `L` と `M`
  にしか一般利用者を通さない。`F`（URL 取得）は `SystemProcess()` に限られるので、
  通常のアカウントでは `upload_file_from_url` が 403 になる。これは InvenioRDM 側の意図で
  あって、サーバに任意の URL を取りに行かせる操作は SSRF の形をしているためである。

`web-api` と `worker` の双方が、設定した保存先に到達できる必要がある。詳しくは
[ファイルの運び方](../concepts/files.md)。

## 語彙

語彙ツールは、インスタンスが持っているものをそのまま見せる。`list_vocabulary_types` が
ほとんど空で返るなら fixture が投入されていない。その状態ではメタデータの書き込みが
`resource_type.id` などの検証で落ちる。通常どおり投入すること
（`invenio rdm-records fixtures`）。

`delete_record` は `reason_id` を固定の一覧ではなく、実インスタンスの `removalreasons`
語彙に対して検証する。独自の理由を足したリポジトリでもそのまま動く。

## keycloak モード：唯一、素のままでは済まないところ {#keycloak}

他のすべての場面で、このサーバは InvenioRDM に何もインストールしない。
**keycloak モードだけが例外**であり、その理由をはっきりさせておく価値がある。

このモードで MCP サーバが InvenioRDM に送るのは、RFC 8693 の交換で得た
**Keycloak 発行の JWT**（`aud=invenio-api`）である。素の InvenioRDM は JWT を Bearer
トークンとして受け付けない——知っているのは個人アクセストークンと、自前の OAuth サーバ
である。したがってインスタンス側に、次を行う層が要る。

1. Keycloak realm の JWKS と `invenio-api` という audience に対して **JWT を検証する**
2. それを**利用者に解決する**。初見の subject なら just-in-time で作成し、
   `UserIdentity` で紐付ける

NII ではこれが `invenio-jairo-jwt` にあたる。同等のものであれば何でもよい。MCP サーバが
求めるのは、`Authorization: Bearer <Keycloak の JWT>` が受け付けられ、その人として
振る舞うこと、それだけである。

!!! danger "realm を作り直すと既存の利用者の紐付けが切れる"

    `setup_mcp_realm.py` は realm が既に在れば削除して作り直す。これは Keycloak の `sub` を
    変える——`UserIdentity` が鍵にしているのがそれなので、既存の紐付けはすべて壊れ、
    同じ人が新しい利用者として現れる。稼働中の realm に何かを足すときは、`ensure_realm()` を
    通さず `ensure_scope()` などを個別に呼ぶこと。

### 連合認証と、降りてこないメールアドレス

学認のような連合認証で来た場合、`mail` は返ってこないことが多い。それでも InvenioRDM は
アドレスを必要とするので、仮のものが入る（既定で `@jwt.invalid`。
`PLACEHOLDER_EMAIL_DOMAIN`）。

`whoami` はこれを `invenio.email_pending_setup: true` として報告し、
`profile_settings_url` を返す。表に出す価値がある。この状態では
**リポジトリからの通知メールが本人に届かない**——査読の依頼も含めて。

### 全体を通して確かめる

```bash
MCP_RESOURCE=https://<mcp>/mcp MCP_TEST_USER=... MCP_TEST_PASSWORD=... \
  python3 http/conformance/mcp_client.py
```

手で見るなら `whoami` が早い。MCP サーバ宛のトークン、交換後の InvenioRDM 宛トークン、
それが解決した InvenioRDM の利用者が、並べて返る。

## 確認項目

- [ ] `GET /api/records` がトークン無しで応答する
- [ ] `GET /api/me` がトークン付きで 200 を返し、想定どおりのロールが出る
- [ ] `GET /api/vocabularies/` に、ひと握り以上の種類が並ぶ
- [ ] `MCP_TLS_INSECURE` 無しで TLS が検証できる
- [ ] MCP サーバのコンテナから InvenioRDM のホスト名が引ける
- [ ] multipart が要るなら保存先が S3 である
- [ ]（keycloak モード）InvenioRDM が Keycloak の JWT を受け付け、利用者に解決する
