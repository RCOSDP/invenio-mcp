# stdio 版 — 12 ツール・トークン1本

*[English version](README.md)*

InvenioRDM のレコード（メタデータ）とファイルを **Claude から MCP 経由で CRUD** するための stdio 型 MCP サーバ。
公式 `mcp` SDK(FastMCP) ＋ stdlib のみ（追加インストール不要）。InvenioRDM REST API を Bearer トークンで叩く。
対象は InvenioRDM v14。12 ツールすべての疎通を確認済み。

## 構成
- `server.py` — MCP サーバ本体（12 ツール）
- `.token` — API トークン（600・**gitignore**、コミットしない）
- 登録はクライアント側の MCP 設定（`.mcp.json` / `claude_desktop_config.json`）

## セットアップ

### 1. API トークン発行（一度だけ）
```bash
# InvenioRDM のアプリケーションコンテナ内で実行する。
# 公開レコードのソフト削除・復元まで行うなら admin ロールのアカウントで発行する。
invenio tokens create -n mcp-stdio -u <管理者のメールアドレス> | tail -1 \
  | tr -d '\n' > "$PWD/.token"
chmod 600 "$PWD/.token"
# UI からでも発行できる: <InvenioRDM>/account/settings/applications/tokens/new/
```
※ 作成/公開/下書き削除/ファイルのみで良いなら一般ユーザ（`researcher@example.org` 等）でも可。ただし**公開レコードの削除・復元は admin 必須**。

### 2. ファイル保存の前提
v14 の file location（S3/MinIO など）に `web-api` / `worker` から到達できていること。

### 3. TLS（自己署名ルート CA）
InvenioRDM が自己署名証明書のときは、**検証は既定でオンのまま**
`INVENIO_CA_BUNDLE` でルート CA を渡す。
MCP サーバは Claude Code の子プロセスで、ログインシェルの `SSL_CERT_FILE` が届かないことがあるため、
環境変数に頼らずファイルを直接読む作りにしてある。

### 4. クライアントへの登録
クライアントの MCP 設定に登録する。**設定を変えたらクライアントの再起動が要る**
（起動済みプロセスは古い環境変数のまま動く。接続一覧の ✔ は「起動できた」しか見ていない）。
ツールは `mcp__inveniordm__<name>` として利用可能。

## 環境変数
| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `INVENIO_API` | `https://localhost/api` | REST API ベース |
| `INVENIO_TOKEN` | （未設定なら `.token` を読む） | Bearer トークン |
| `INVENIO_VERIFY_TLS` | `true` | TLS 検証。落とすときだけ `false` |
| `INVENIO_CA_BUNDLE` | （自己署名なら必須） | 検証に使うルート CA |

## ツール一覧（12）

**読取**
- `search_records(query="", size=10)` — 公開レコード検索（要点のみ）
- `get_record(recid, draft=False)` — 1件取得（draft=True で下書き）

**メタデータ 登録/更新**
- `create_record(metadata, access=None, files_enabled=False, publish=False)` — 新規作成
- `update_record(recid, metadata, publish=True)` — 更新（公開済みは edit→更新→publish）
- `publish_record(recid)` — 下書きを公開
- `new_version(recid, metadata=None, publish=False)` — 新バージョン

**削除**
- `delete_draft(recid)` — 下書き破棄
- `delete_record(recid, confirm=False, reason_id="out-of-scope", note=...)` — 公開レコードのソフト削除（tombstone/410・**admin必須**・`confirm=True` 必須・復元可）
- `restore_record(recid)` — ソフト削除の復元（admin）

**ファイル**（対象レコードは `files_enabled=True`）
- `add_file(recid, key, text=None, content_base64=None, source_path=None)` — 追加（init→content→commit）
- `list_files(recid, draft=True)` — 一覧
- `delete_file(recid, key)` — 削除

## 最小メタデータ（create_record の `metadata`）
```json
{
  "resource_type": {"id": "dataset"},
  "title": "タイトル（3文字以上）",
  "publication_date": "2026-07-09",
  "creators": [
    {"person_or_org": {"type": "personal", "family_name": "山田", "given_name": "太郎"}}
  ]
}
```
`resource_type.id` は語彙（`dataset`, `publication-article` 等）。`publisher` 等は任意。

## 使用例（自然言語→ツール）
- 「dataset を1件作って公開して」→ `create_record(metadata=..., publish=True)`
- 「recid xxxx にファイル report.txt を追加」→ 事前に `files_enabled=True` で作成 or 新draft、`add_file(xxxx, "report.txt", text=...)`
- 「recid xxxx を削除」→ `delete_record(xxxx, confirm=True)`（ソフト削除・`restore_record` で復元可）

## 動作確認
```bash
/usr/bin/python3 server.py --selftest   # create→update→add_file→publish→search→delete→restore を実走
```
selftest はテストレコードを最後にソフト削除する（tombstone が残る点に留意）。

## 大きなファイルを送るとき
本サーバの `add_file` は InvenioRDM 経由の PUT（transfer `L`）1本で、**MCP の応答上限（base64 16MB）は
`source_path` を使えば回避できる**が、送り先は常に web-api を通る。GB 級を扱うなら、本リポジトリの
HTTP 版（`../http/`）の `start_multipart_upload` を使う。署名済み URL で
クライアントから MinIO へ直接送るため、web-api を通らない。
なお v14 では URL 取得（transfer `F`）が一般利用者から取り上げられている（`SystemProcess()` のみ）。

## 安全・留意
- 書込は**デモインスタンス**（fake データ）に対して行う。破壊的操作（`delete_record`）は `confirm=True` 必須・ソフト削除で `restore_record` により復元可能。ハード purge は REST 非公開のため本サーバでも不可。
- トークンは秘密情報。`.token`(600)・`.gitignore` 済み。`.mcp.json` に平文で置かない。
- ロールバック: トークン削除は `invenio tokens delete ...`。
