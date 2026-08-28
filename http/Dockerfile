# MCP リソースサーバ（OAuth 2.1 / MCP 2026-07-28）。
# build context: このディレクトリ（http/）。docker-compose.yml と k8s/mcp-server.yaml が共用する。
FROM python:3.12-slim

RUN pip install --no-cache-dir \
      "mcp==1.26.0" \
      "pyjwt[crypto]>=2.8" \
      "httpx>=0.27" \
      "uvicorn>=0.30"

WORKDIR /app
COPY mcp_server.py /app/mcp_server.py

# 既定値はマニフェスト側の環境変数で上書きする
ENV MCP_BIND_HOST=0.0.0.0 \
    MCP_BIND_PORT=9100

CMD ["python3", "/app/mcp_server.py"]
