# ライセンス

invenio-mcp は **MIT ライセンス**で配布する。

```
--8<-- "LICENSE"
```

## 第三者の著作物

このリポジトリは第三者のコードを取り込んでいない。実行時に次のものを利用する。

| | ライセンス | 使う側 |
| --- | --- | --- |
| [`mcp`](https://github.com/modelcontextprotocol/python-sdk)（Python SDK） | MIT | 両方 |
| `httpx` | BSD 3-Clause | HTTP 版 |
| `PyJWT` | MIT | HTTP 版 |
| `uvicorn` | BSD 3-Clause | HTTP 版 |

stdio 版は標準ライブラリと `mcp` だけで動く。

対象とするリポジトリソフトウェア [InvenioRDM](https://inveniordm.docs.cern.ch/) は
MIT ライセンスの別プロジェクトであり、本ソフトウェアはその REST API を呼ぶだけで、
コードを取り込んでいない。

[`NOTICE`](https://github.com/RCOSDP/invenio-mcp/blob/main/NOTICE) を参照。
