# デプロイ

どちらの形も**同じ `Dockerfile`** から作る。compose で試したイメージが、そのまま
マニフェストが動かすイメージになる。

## Docker Compose

既定は PAT モードで、このサービス1つ以外に要るものが無い。

```bash
cd http
cp .env.example .env
docker compose up -d --build
```

compose ファイルは1つだけ知っておくべきことをしている。`SSL_CERT_FILE` で CA 単体を
指すのではなく、ルート CA をシステムの束に**足している**。

```bash
cat /etc/ssl/certs/ca-certificates.crt > /tmp/ca-bundle.crt
[ -f /etc/ca/ca.crt ] && cat /etc/ca/ca.crt >> /tmp/ca-bundle.crt
```

CA 単体を指すと、そのファイルが信頼の*すべて*になり、サーバが行う他のすべての HTTPS
通信が壊れる。公的な証明書を使っているなら `volumes:` の行ごと消してよい。

!!! tip "InvenioRDM が同じ機械に居るとき"

    InvenioRDM がホスト側で待ち受けている（kind の ingress、別の compose など）場合、
    コンテナからは同じホスト名を引けない。`extra_hosts:` を有効にして、実際に使っている
    ホスト名を書く。別のホストに居るなら不要。

healthcheck は保護リソースメタデータを取りに行く。これは定義上未認証で読めるので、
資格情報を要らない生存確認になる。

## Kubernetes

`http/k8s/mcp-server.yaml` は keycloak モード向けの**雛形**（Service ＋ Deployment ＋
Ingress）。次を置き換える。

| 雛形の値 | 置き換える先 |
| --- | --- |
| `MCP_IMAGE` | 自分でビルドしたイメージ |
| `*.example.org` | 実際のホスト名（3か所） |
| `namespace: invenio-mcp` | 自分の namespace |
| `ca-issuer` / `nginx` / `nodeType=APP` | ClusterIssuer・ingress class・node selector |

別途、次を用意する。

- **ConfigMap `ca-bundle` と `ca-bootstrap`** — 自己署名 CA をシステムの CA 束に
  **足す**ブートストラップ。理由は上と同じ。
- Secret `mcp-server-secret` の **`MCP_SERVER_SECRET`**。既定値は無く、これが無いと
  サーバは起動しない。

```bash
export KC_BASE=https://<keycloak>
export KC_ADMIN_PASSWORD=<管理者パスワード>
export MCP_SERVER_SECRET=<シークレット>
export MCP_RESOURCE=https://<mcp>/mcp
python3 keycloak/setup_mcp_realm.py
kubectl apply -f k8s/mcp-server.yaml
```

## 運用で効く設定

| 変数 | 理由 |
| --- | --- |
| `MCP_RESOURCE` | **クライアントが叩く URL と一字一句同じに。** audience 検証のすべてがこの1本の文字列に懸かっている |
| `MCP_TLS_INSECURE` | 設定しないこと。InvenioRDM と Keycloak の両方で証明書検証が切れる |
| `MCP_AUDIT` | 有効のままに。1呼び出し1行、トークンは決して入らない |
| `MCP_LANG` | プロセス単位で固定。2言語なら2つ立てる |
| `MCP_MAX_UPLOAD_BYTES` | 往復両方の base64 の上限。上げても大きなファイルが良い考えになるわけではない——[multipart](../concepts/files.md) を使う |

全一覧は[設定](../reference/configuration.md)。

## 台数を増やす

サーバは**状態を持たない**（`stateless_http=True`・JSON 応答）ので、レプリカに共有の
セッション保管も sticky な振り分けも要らない。プロセスごとに2つのキャッシュがあるが、
どちらも純粋な最適化である。

- 交換後トークンのキャッシュ（keycloak モード）。受信トークンを鍵にする
- `/me` の結果のキャッシュ（PAT モード）。`MCP_INVENIO_VERIFY_TTL` 秒だけ持つ

新しいレプリカは、トークン交換か `/me` を1回やり直すだけで済む。**失敗はキャッシュ
しない**ので、トークンを失効させれば TTL のうちに全レプリカへ効く。

## ドキュメントを公開する

このサイトは **`gh-pages` ブランチ**に置かれ、GitHub Pages がそれをそのまま配信する。
ビルドして `mkdocs gh-deploy` で push するのは `tools/deploy-docs.sh` で、走るのは CI では
なくメンテナの手元である。そもそも CI を置いていない理由は
[参加する](../project/contributing.md#検査)にある。

リポジトリ側で一度だけ設定する。

> **Settings → Pages → Source: Deploy from a branch → `gh-pages` / `(root)`**

ブランチができたあとなら、コマンドからでもよい。

```bash
gh api -X POST repos/RCOSDP/invenio-mcp/pages \
  -f 'source[branch]=gh-pages' -f 'source[path]=/'
```

!!! warning "`gh-pages` は生成物。手で触らない"

    書き手は `tools/deploy-docs.sh` だけで、`--force` で push する。手でコミットした
    ものは次のデプロイで消える。サイトに属するものはすべて `main` の `docs/` 以下にある。

push する前に、スクリプトは[ツール一覧](../reference/tools.md)を作り直し、コミットされて
いるものと違えば止まる。公開されている一覧がコードから遅れないようにするためである。
未コミットの変更があっても止まり、`HEAD` が `origin` に無ければ警告する——**リポジトリで
追えないページが公開されている**ほうが、古いページより悪い。

```bash
pip install -r docs/requirements.txt
mkdocs serve                          # 英語が /、日本語が /ja/
bash tools/deploy-docs.sh --dry-run   # 検査とビルドだけ。公開しない
bash tools/deploy-docs.sh             # 公開する。push 権限が要る
```
