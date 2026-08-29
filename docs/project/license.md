# License

invenio-mcp is released under the **MIT License**.

```
--8<-- "LICENSE"
```

## Third-party

This repository vendors no third-party code. At run time it uses:

| | License | Used by |
| --- | --- | --- |
| [`mcp`](https://github.com/modelcontextprotocol/python-sdk) (Python SDK) | MIT | both servers |
| `httpx` | BSD 3-Clause | HTTP server |
| `PyJWT` | MIT | HTTP server |
| `uvicorn` | BSD 3-Clause | HTTP server |

The stdio server runs on the standard library plus `mcp` alone.

[InvenioRDM](https://inveniordm.docs.cern.ch/), the repository software these servers
drive, is a separate project under the MIT License. These servers only call its REST
API; none of its code is included.

See [`NOTICE`](https://github.com/RCOSDP/invenio-mcp/blob/main/NOTICE).
