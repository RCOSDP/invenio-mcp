# 参加する

issue も pull request も歓迎する。「ここのドキュメントが間違っている」も含めて——
それも他と同じ欠陥である。

## 用意するもの

ビルドは無い。サーバは Python ファイル2つである。

```bash
git clone https://github.com/RCOSDP/invenio-mcp
cd invenio-mcp
pip install "mcp==1.26.0" "pyjwt[crypto]>=2.8" "httpx>=0.27" "uvicorn>=0.30"
```

stdio 版に要るのは `mcp` だけで、残りは HTTP 版のためのものである。

```bash
# ドキュメントサイト
pip install -r docs/requirements.txt
mkdocs serve            # 英語が /、日本語が /ja/
```

## 検査

**CI は無い。** 検査は手元で走り、`tools/check.sh` がその全部である。1本にしてあるのは、
2系統あると「片方では通り、もう片方では落ちる」変更が必ず生まれるからである。

```bash
bash tools/check.sh
```

| 見るもの | なぜ |
| --- | --- |
| 両サーバがコンパイルできる | いちばん安く見つかる失敗 |
| 両サーバが読み込め、ツールが 12 と 33 在り、すべてに説明が在る | 説明の無いツールは、モデルから見れば存在しないのと同じ |
| `en.json` と `ja.json` のキーが一致する | 片方にしか無いキーは黙って英語に落ちる |
| 両サーバの `__version__` が同じ | でなければ「0.2.0 の invenio-mcp」が2つのものを指す |
| 生成したツール一覧が実装と一致する | 生成物なので、古いままなら嘘になる |
| サイトが `--strict` で建つ | リンク切れを警告で済ませず失敗にする |

依存が無い検査は、黙って通さず `SKIP` と出す——サーバの読み込みには `mcp`、サイトには
`mkdocs` が要る。上のコマンドで入れるか、ドキュメントだけを触ったなら
`SKIP_IMPORT=1 bash tools/check.sh` でよい。

pull request には、通ったことと、飛ばした項目があればそれを書く。

## 実インスタンスに対して試す

InvenioRDM 無しで走るテスト一式は無い。在るふりをするより、無いと言うほうがよい。
在るのは、実インスタンスに対して走るものである。

```bash
python3 stdio/server.py --selftest                # 作成 → 公開 → 削除 → 復元
python3 http/conformance/mcp_client.py            # 認可仕様（PASS/FAIL）
python3 http/conformance/verify-mcp-files.py      # ファイル3経路
bash    http/conformance/curl-tour.sh             # 認可フローを curl で
```

**捨ててよいデータのデモインスタンスを使うこと。** `--selftest` は最後にレコードを
ソフト削除するので、tombstone が残る。

pull request には、どれを何に対して走らせたかを書いてほしい。

## レビューで訊かれること

1. **利用者に見える文字列は `locales/` に在るか。** 人とモデルが読むもの——ツールの説明・
   エラー・起動時の表示——は、**両方の言語**でそこに置く。コード中の注釈はそのままでよい。
   開発者向けだからである。[言語](../reference/languages.md)を参照。
2. **理由がコードに書いてあるか。** 注釈は *なぜ* を説明する。何をしているかは既に見える。
   このファイル群の注釈のほとんどは、実際に踏んだこと——401 を見ないと認可を始めない
   クライアント、一般利用者には使えない transfer 種別——を記録している。残す価値が
   あるのはそういうものである。
3. **権限の判定は今も InvenioRDM で終わっているか。** MCP の scope は、クライアントが
   *要求してよいか* を分けるだけのものである。権限の仕組みを二重に持つ変更は差し戻す。
4. **モデルに見えるものが変わるか。** ツールや引数の改名・削除は、何もコンパイルに
   失敗しなくても破壊的変更である。注意書きを落とす説明の書き直しも同じ。
   [バージョン](versioning.md)を参照。

## ツールを足す

- `@mcp.tool(description=t("tools.<name>"))` を付けた関数を書く。**docstring は書かない**
  ——説明は言語リソースから来るため。
- 文言を `locales/en.json` **と** `locales/ja.json` の両方に足す。
- `TOOL_SCOPES` に scope を足す。`None` は「未認証で呼べる」という意味で、公開情報の
  読取にだけ正しい。
- `tools/gen_tool_reference.py` の分類に入れる。どこにも属さないツールがあると生成器は
  失敗する。意図的にそうしてある——分類し忘れたツールは、一覧から黙って消えるからである。
- `python3 tools/gen_tool_reference.py` を走らせ直す。
- ツール数が変わったなら、README・`docs/index.ja.md`・`tools/check.sh` の検査値も直す。

## 言語を足す

`locales/en.json` を写して訳し、隣に `<tag>.json` として置く。登録の手続きは無く、
サーバはディレクトリに在るものを拾う。足りないキーは英語に落ちるので、部分訳のまま
出してもらってかまわない。

## ドキュメントを書く

どのページにも `.md` と `.ja.md` がある。**同じ pull request で両方**を。片方の言語にしか
無いページは、無いページより悪い。言語切替が、在りもしない場所へ連れて行くからである。

[ツール一覧](../reference/tools.md)は生成物である。言語リソースのほうを直すこと。

### 公開する

サイトは `gh-pages` ブランチから配信されている。あれは**生成物**であって、手で触る人は
いない。書き手は `tools/deploy-docs.sh` だけで、リポジトリへの push 権限が要る——
つまり Markdown を書くのは誰でもよく、出すのはメンテナである。

```bash
bash tools/deploy-docs.sh --dry-run   # 検査とビルドだけ。公開しない
bash tools/deploy-docs.sh             # 検査 → ビルド → gh-pages へ push
```

出す前に、未コミットの変更があれば止まり、`HEAD` が `origin` に無ければ警告する。
どちらも同じことを守っている——**サイトに在るのにリポジトリで追えない内容**を作らない。

## コミットメッセージ

`type: 要約`。命令形で、日本語でも英語でもよい（履歴には両方ある）。
`feat:`・`fix:`・`docs:`・`chore:`・`refactor:`。
