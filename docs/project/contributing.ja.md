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

## CI が見るもの

pull request を出す前にこれを走らせること。`.github/workflows/ci.yml` がするのと
まったく同じである。

```bash
python3 -m py_compile http/mcp_server.py stdio/server.py
python3 tools/gen_tool_reference.py --check    # ドキュメントが実装と合っているか
mkdocs build --strict                          # リンク切れが無いか
```

CI はさらに、両方のサーバを読み込んでツール数（12 と 33）を確かめ、すべてのツールに
説明が在ること、`en.json` と `ja.json` のキーが一致すること、両サーバの `__version__` が
同じであることを検査する。

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
- ツール数が変わったなら、README・`docs/index.ja.md`・`.github/workflows/ci.yml` の
  検査値も直す。

## 言語を足す

`locales/en.json` を写して訳し、隣に `<tag>.json` として置く。登録の手続きは無く、
サーバはディレクトリに在るものを拾う。足りないキーは英語に落ちるので、部分訳のまま
出してもらってかまわない。

## ドキュメントを書く

どのページにも `.md` と `.ja.md` がある。**同じ pull request で両方**を。片方の言語にしか
無いページは、無いページより悪い。言語切替が、在りもしない場所へ連れて行くからである。

[ツール一覧](../reference/tools.md)は生成物である。言語リソースのほうを直すこと。

## コミットメッセージ

`type: 要約`。命令形で、日本語でも英語でもよい（履歴には両方ある）。
`feat:`・`fix:`・`docs:`・`chore:`・`refactor:`。
