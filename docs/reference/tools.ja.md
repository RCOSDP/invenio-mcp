<!-- tools/gen_tool_reference.py が生成する。手で書き換えない。 -->
# ツール一覧

2つのサーバが公開しているすべてのツールと、その引数・必要な scope。ここに載る説明は
**サーバが実際に LLM へ渡している文字列そのもの**で、`locales/ja.json` から取っている。
クライアントが見るものとずれることがない。

- **http** — [HTTP 版](../guides/http.md)の 33 ツール
- **stdio** — [stdio 版](../guides/stdio.md)の 12 ツール

scope の欄が空のツールは公開情報の読取で、未認証でも呼べる。scope の意味は
[認可](../concepts/authorization.md)を見ること。


## レコードを読む

### `search_records`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | 不要（未認証で可） |

```python
search_records(query: str = '', size: int = 10)
```

公開レコードを検索する（**未認証でも可**）。

トークンがあればその人として検索するので、自分の下書きなども対象になる。


!!! note "stdio 版はふるまいが違う:"

    公開レコードを検索する。query は Invenio 検索式（空で全件）。要点のみ返す。

### `get_record`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | 不要（未認証で可） |

```python
get_record(recid: str, draft: bool = False)
```

レコードを1件取得する（**未認証でも可**）。draft=True で下書き（要認証）。


!!! note "stdio 版はふるまいが違う:"

    1レコードを取得する。draft=True で下書きを取得。

### `my_records`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:read` |

```python
my_records(query: str = '', size: int = 10)   # http
```

自分のレコードと下書きを一覧する（mcp:read）。

公開済みだけでなく**未公開の下書きも含む**ので、「書きかけはどれ」を答えられる。

### `list_versions`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
list_versions(recid: str)   # http
```

レコードの全バージョンを一覧する（未認証可）。`new_version` で作った版もここに出る。

### `list_revisions`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:read` |

```python
list_revisions(recid: str)   # http
```

レコードの版履歴（いつ何が変わったか）を一覧する（mcp:read）。

バージョン（`list_versions`）とは別物で、こちらは**同じレコードの編集履歴**。
公開レコードでも認証が要る。

### `export_record`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
export_record(recid: str, fmt: str = 'datacite-json')   # http
```

公開レコードを別のメタデータ形式で出す（未認証可）。

fmt は json / inveniordm / jsonld / datacite-json / datacite-xml /
dublincore / marcxml / dcat / csl / bibtex / citation / geojson。
**下書きには使えない**（公開レコードのみ）。


## 語彙

### `list_vocabulary_types`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
list_vocabulary_types()   # http
```

このリポジトリが持つ語彙の種類を一覧する（未認証可）。

返った id を `list_vocabulary` に渡すと中身が引ける。

### `list_vocabulary`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
list_vocabulary(vocab_type: str, query: str = '', size: int = 20)   # http
```

語彙の項目を引く（未認証可）。

vocab_type は `list_vocabulary_types` が返す id
（resourcetypes / licenses / languages / subjects / removalreasons /
creatorsroles / descriptiontypes / relationtypes / titletypes / datetypes など）。
**メタデータを書く前にここで正しい id を確かめること。**


## 作成と更新

### `create_record`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:write` |

```python
create_record(metadata: dict, publish: bool = False, files: bool = False)   # http
```

```python
create_record(metadata: dict, access: dict = None, files_enabled: bool = False, publish: bool = False)   # stdio
```

レコードを作成する（mcp:write）。

publish=True で公開まで行う。
files=True にするとファイルを添付できる下書きになる（`upload_file` で入れる）。
**ファイルを入れるなら publish は後回しにする**（公開後は新バージョンでしか足せない）。


!!! note "stdio 版はふるまいが違う:"

    新規レコードを作成する。metadata は Invenio の metadata オブジェクト
    （必須: resource_type{id}, title(≥3), publication_date(EDTF),
    creators[{person_or_org{type,family_name,given_name}}]）。
    files_enabled=False は metadata-only。publish=True で即公開。返り値に recid を含む。

### `update_record`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:write` |

```python
update_record(recid: str, metadata: dict, publish: bool = True)
```

レコードのメタデータを更新する（mcp:write）。公開済みは edit→更新→publish。


!!! note "stdio 版はふるまいが違う:"

    既存レコードのメタデータを更新する。公開済みなら edit(下書き化)→更新→(publish) を行う。
    metadata は完全な metadata オブジェクト（部分ではなく置換）。publish=False なら下書きのまま。

### `publish_record`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:write` |

```python
publish_record(recid: str)
```

下書きを公開する（mcp:write）。


!!! note "stdio 版はふるまいが違う:"

    下書きを公開する。

### `new_version`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:write` |

```python
new_version(recid: str, import_files: bool = True, publication_date: str | None = None, version: str | None = None)   # http
```

```python
new_version(recid: str, metadata: dict = None, publish: bool = False)   # stdio
```

公開済みレコードの**新しいバージョンの下書き**を作る（mcp:write）。

InvenioRDM は公開済みレコードを書き換えられない。ファイルを足す・差し替えるには
新バージョンを作ってそこで作業し、改めて公開する。

recid        … 元の（公開済み）レコード ID
import_files … True なら**前バージョンのファイルを引き継ぐ**
               （InvenioRDM の files-import。既定 True）。
               False だとファイル無しの下書きから始まる。
publication_date … 新バージョンの公開日（`YYYY-MM-DD`）。
               **InvenioRDM は新バージョン下書きに公開日を引き継がない**ので、
               省略時は今日の日付を入れる。これが無いと publish が
               `metadata.publication_date: Missing data for required field` で失敗する。
version      … 版表示（`v2` など）。任意。

戻り値の `id` が新しい下書きの ID。`upload_file` などはその ID に対して行い、
最後に `publish_record` で公開する。


!!! note "stdio 版はふるまいが違う:"

    新しいバージョンの下書きを作る。metadata を渡すと差し替え、publish=True で即公開。

### `delete_draft`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:write` |

```python
delete_draft(recid: str)
```

下書きを破棄する（mcp:write）。


!!! note "stdio 版はふるまいが違う:"

    下書き（未公開 or 編集中の下書き）を破棄する。


## 取り下げと復元

### `delete_record`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:curate` |

```python
delete_record(recid: str, confirm: bool = False, reason_id: str = 'out-of-scope', note: str = 'removed via MCP')
```

公開レコードをソフト削除（tombstone・HTTP 410）する（mcp:curate）。

**破壊的操作なので confirm=True が無いと実行しない。** `restore_record` で復元できる。
reason_id は removalreasons 語彙の id（`list_vocabulary("removalreasons")` で引ける。
既定は out-of-scope / copyright / disputed-authorship / duplicate / fraud /
misconduct / personal-data / retracted / spam / replaced / take-down-request /
test-record の12件）。note は tombstone に残る公開メモ。
InvenioRDM 側で admin 権限が無ければ 403 になる。


!!! note "stdio 版はふるまいが違う:"

    公開レコードをソフト削除（tombstone・HTTP 410）する。admin トークン必須。
    confirm=True が無いと実行しない。restore_record で復元可能。
    reason_id は removalreasons 語彙（out-of-scope / duplicate / spam / retracted 等）。

### `restore_record`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:curate` |

```python
restore_record(recid: str)
```

ソフト削除された公開レコードを復元する（mcp:curate）。

tombstone が外れて再び公開状態に戻る。InvenioRDM 側で admin 権限が無ければ 403。


!!! note "stdio 版はふるまいが違う:"

    ソフト削除された公開レコードを復元する。admin トークン必須。


## ファイル

### `upload_file`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
upload_file(recid: str, filename: str, content_base64: str | None = None, content_text: str | None = None, overwrite: bool = True)   # http
```

下書きにファイルを登録する（mcp:write）。

recid          … 下書きの ID（`create_record` が返す id）
filename       … 登録するファイル名（キーになる）
content_base64 … 中身を base64 で。バイナリはこちら
content_text   … 中身を平文で。テキストならこちらが楽（UTF-8 で符号化する）

overwrite      … 同名のファイルが既にあるとき置き換える（既定 True）。
                 False なら「既にある」と伝えて何もしない。

**公開済みレコードには足せない**（InvenioRDM の仕様。新バージョンを作ること）。
下書きの files が無効なら自動で有効にする。

### `add_file`

| | |
| --- | --- |
| 提供 | stdio 版のみ |

```python
add_file(recid: str, key: str, text: str = None, content_base64: str = None, source_path: str = None)   # stdio
```

下書きにファイルを追加（init→content→commit）する。対象レコードは files_enabled=True である必要がある。
中身は text(UTF-8) / content_base64 / source_path(サーバ上のパス) のいずれかで渡す。

### `list_files`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | 不要（未認証で可） |

```python
list_files(recid: str, draft: bool = False)   # http
```

```python
list_files(recid: str, draft: bool = True)   # stdio
```

レコードのファイル一覧を返す（未認証でも公開レコードなら見られる）。

draft=True で下書きのファイルを見る（本人の認証が要る）。


!!! note "stdio 版はふるまいが違う:"

    レコード/下書きのファイル一覧。

### `download_file`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
download_file(recid: str, filename: str, draft: bool = False)   # http
```

ファイルの中身を取り出す（公開レコードなら未認証でも可）。

InvenioRDM は S3 の **presigned URL へリダイレクト**して返す。その URL のホストは
クラスタ内部名（`minio:9000`）なので**クラスタ外からは辿れない**。そこで MCP サーバが
代わりに取得し、中身を base64 で返す。UTF-8 として読めるものは `text` にも入れる。

draft=True で下書きのファイルを取る（本人の認証が要る）。

### `delete_file`

| | |
| --- | --- |
| 提供 | 両方 |
| 必要な scope | `mcp:write` |

```python
delete_file(recid: str, filename: str)   # http
```

```python
delete_file(recid: str, key: str)   # stdio
```

下書きからファイルを削除する（mcp:write）。公開済みレコードからは消せない。


!!! note "stdio 版はふるまいが違う:"

    下書きからファイルを削除する。

### `upload_file_from_url`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
upload_file_from_url(recid: str, filename: str, url: str, overwrite: bool = True)   # http
```

URL を渡して InvenioRDM 側にファイルを取得させる（mcp:write）。

`upload_file` は中身を base64 で運ぶので、MCP の応答が JSON である以上
大きなファイルには向かない（既定上限 16MB）。こちらは **URI を登録するだけ**で、
実体は InvenioRDM の Celery ワーカーが非同期にダウンロードする
（InvenioRDM の transfer 種別 `F` = FETCH）。**サイズの上限が無い。**

**InvenioRDM v14 では通常の利用者は使えない。** 既定の権限方針
（`RDMRecordPermissionPolicy.can_draft_create_files`）は transfer 種別 `L` と `M`
にしか一般利用者を通さず、`F`（と `R`）は `SystemProcess()`、つまり
システム処理と superuser だけに限られている。サーバに任意の URL を
取りに行かせる操作（SSRF になりうる）を絞ったもの。権限が無ければ 403 になる。

取得先は InvenioRDM 側の許可ドメイン
（`RECORDS_RESOURCES_FILES_ALLOWED_DOMAINS`）にも含まれている必要がある。
許可されていない URL は `Domain not allowed` になる。

**非同期なので、戻った時点ではまだ取得中**（`status` が `pending`）のことがある。
完了は `list_files` の `status` が `completed` になったかで確かめる。

**手元にあるファイル**は URL を持たないので、この経路には乗らない。
その場合は `start_multipart_upload` を使う（大きさの上限が無く、権限も通常の書き込みでよい）。

### `start_multipart_upload`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
start_multipart_upload(recid: str, filename: str, size: int, part_size: int | None = None, overwrite: bool = True)   # http
```

手元の大容量ファイルを送るための**署名済み URL を発行する**（mcp:write）。

`upload_file` は中身を base64 で運ぶので JSON に載る大きさが限界（既定 16MB）。
`upload_file_from_url` は URL を持つファイルにしか使えない。
**手元にある大きなファイル**はこの経路で送る（InvenioRDM の transfer 種別
`M` = MULTIPART）。中身は MCP サーバも InvenioRDM も通らず、
**クライアントから S3(MinIO) へ直接** PUT される。サイズの上限は事実上無い。

recid     … 下書きの ID
filename  … 登録するファイル名
size      … 送るファイルの**実バイト数**（必須。S3 に事前申告する）
part_size … 1パートの大きさ。既定 64MiB。最後以外は 5MiB 以上で全て同じ大きさ

返り値の `parts` の各 `url` に、ファイルを先頭から `part_size` ずつ切って
**PUT** する。全部送ったら `complete_multipart_upload` を呼ぶ。
やめるときは `abort_multipart_upload`。

分割と送信の例（返り値の `hint` にも同じものが入る）:

    split -b <part_size> ./big.bin part_
    curl -X PUT --data-binary @part_aa "<parts[0].url>"
    curl -X PUT --data-binary @part_ab "<parts[1].url>"

### `complete_multipart_upload`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
complete_multipart_upload(recid: str, filename: str)   # http
```

全パートを送り終えた multipart を確定する（mcp:write）。

S3 側でパートを1つのオブジェクトに結合し、transfer 種別が `M` から `L`
（通常のファイル）に変わる。**1つでもパートが欠けていると失敗する。**

直後の `checksum` は `multipart:<ETag>-<パート数>-<パートの大きさ>` の形で、
これは S3 が返す複合 ETag（パートごとの MD5 をまとめたもの）。
ファイル全体の MD5 は InvenioRDM が背後の非同期ジョブで計算し直す。

### `abort_multipart_upload`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
abort_multipart_upload(recid: str, filename: str)   # http
```

途中でやめた multipart を破棄する（mcp:write）。

S3 側の未完了アップロードも中止されるので、送りかけのパートが
課金対象として残り続けることを防げる。


## コミュニティ

### `search_communities`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
search_communities(query: str = '', size: int = 10)   # http
```

コミュニティを検索する（未認証可）。

### `get_community`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
get_community(community: str)   # http
```

コミュニティを1件取る（未認証可）。community は id(UUID) か slug。

### `list_community_records`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | 不要（未認証で可） |

```python
list_community_records(community: str, query: str = '', size: int = 10)   # http
```

コミュニティに属する公開レコードを一覧する（未認証可）。

### `create_community`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:curate` |

```python
create_community(slug: str, title: str, community_type: str = 'topic', visibility: str = 'public', review_policy: str = 'closed')   # http
```

コミュニティを作る（mcp:curate）。

組織単位を作る操作なので write ではなく curate に置く。
slug はURLに出る識別子（英小文字・数字・ハイフン）。
community_type は communitytypes 語彙（organization / event / topic / project）。
review_policy=closed なら投稿は査読を経る、open なら直接公開できる。


## 査読とリクエスト

### `list_requests`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:read` |

```python
list_requests(query: str = '', status: str = '', size: int = 10)   # http
```

自分に見えるリクエストを一覧する（mcp:read）。

status は submitted / expired / accepted / declined / cancelled。
**査読待ちは status="submitted"**（"open" という状態は無い）。
未指定なら全件。`query` は Lucene 風の絞り込みも受ける（例 type:community-submission）。

### `get_request`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:read` |

```python
get_request(request_id: str, timeline: bool = False)   # http
```

リクエストを1件取る（mcp:read）。timeline=True でコメント等の経過も返す。

### `submit_to_community`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
submit_to_community(recid: str, community: str, comment: str = '')   # http
```

下書きをコミュニティに査読申請する（mcp:write）。

2手順（査読先を設定 → 提出）をまとめて行う。対象は**未公開の下書き**。
受理されると公開される。受理・却下は `request_action`（mcp:curate）。

### `comment_on_request`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:write` |

```python
comment_on_request(request_id: str, comment: str)   # http
```

リクエストにコメントする（mcp:write）。

### `request_action`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:curate` |

```python
request_action(request_id: str, action: str, comment: str = '')   # http
```

リクエストを受理・却下する（mcp:curate）。

action は accept / decline / cancel / expire。
**accept は投稿を公開する**ので、キュレーターの判断として curate に置く。


## セッション

### `whoami`

| | |
| --- | --- |
| 提供 | HTTP 版のみ |
| 必要な scope | `mcp:read` |

```python
whoami()   # http
```

このセッションの認証主体と、InvenioRDM 側で解決された身元を返す（mcp:read）。

学認経由の場合は eppn / 所属（Issuer 由来）/ グループ（mAP 由来）が、
MCP サーバ宛トークンと InvenioRDM 宛の交換後トークンの**両方**に
載っていることを確認できる。

`invenio.email_pending_setup` が true のときは、利用者がまだ
InvenioRDM 側でメールアドレスを設定していない（学認からは mail が
降りてこないため仮アドレスのまま）。通知メールが届かない状態なので、
`profile_settings_url` を案内して設定を促すこと。
