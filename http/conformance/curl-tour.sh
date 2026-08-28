#!/usr/bin/env bash
# MCP サーバの挙動を **curl だけ**で一通り体験する。
#
#   前半（1〜5）… 未認証の挙動。コピペでそのまま試せる。
#   後半（6〜12）… 認可コード + PKCE を通してトークンを取り、認可が要るツールを叩く。
#                   ブラウザの代わりに Keycloak のログインフォームを curl で POST する。
#
# 使い方:
#   bash curl-tour.sh                 # 全部
#   bash curl-tour.sh anon            # 未認証の部分だけ
#
# 環境変数（既定は jc2-k8s-sample の k8s 環境）:
#   CA        ルート CA        既定 ../jc2-k8s-sample/cert/jc2-ca.crt
#   MCP       canonical URI    既定 https://mcp.jc2.localhost/mcp
#   KC_BASE   Keycloak         既定 https://keycloak.jc2.localhost
#   TOUR_USER / TOUR_PASS      既定 researcher / researcher
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CA="${CA:-$HERE/../jc2-k8s-sample/cert/jc2-ca.crt}"
MCP="${MCP:-https://mcp.jc2.localhost/mcp}"
KC_BASE="${KC_BASE:-https://keycloak.jc2.localhost}"
REALM="${KC_REALM:-mcp}"
CLIENT_ID="${TOUR_CLIENT:-curl-tour}"
REDIRECT="http://127.0.0.1:8765/callback"
TOUR_USER="${TOUR_USER:-researcher}"
TOUR_PASS="${TOUR_PASS:-researcher}"
ONLY="${1:-all}"

CURL=(curl -sS --cacert "$CA")
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

say()  { echo; echo "──────── $* ────────"; }
run()  { echo "\$ $*"; }
json() { python3 -m json.tool 2>/dev/null || cat; }

# JSON-RPC を1回投げて、ステータス・ヘッダ・本文を見せる
rpc() {   # rpc <名前> <JSON> [トークン]
  local label="$1" payload="$2" token="${3:-}"
  local hdr=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')
  [ -n "$token" ] && hdr+=(-H "Authorization: Bearer $token")
  echo
  echo "# $label"
  run "curl --cacert \$CA -X POST $MCP ${token:+-H 'Authorization: Bearer <token>'} -d '$payload'"
  local code
  code=$("${CURL[@]}" -o "$TMP/body" -D "$TMP/head" -w '%{http_code}' \
         -X POST "$MCP" "${hdr[@]}" --data-binary "$payload")
  echo "→ HTTP $code"
  grep -i '^www-authenticate:' "$TMP/head" | sed 's/^/   /'
  head -c 400 "$TMP/body"; echo
}

############################################################ 未認証の挙動
say "1. 未認証で tools/list（誰でも呼べる）"
rpc "tools/list" '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

say "2. 未認証で公開レコードを検索（トークン不要）"
rpc "search_records" '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_records","arguments":{"size":3}}}'

say "3. 未認証で書込ツール → 401 チャレンジ（ここが認可フローの入口）"
rpc "create_record" '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_record","arguments":{"metadata":{}}}}'

say "4. チャレンジの resource_metadata を辿る（RFC 9728 保護リソースメタデータ）"
PRM_URL=$(grep -i '^www-authenticate:' "$TMP/head" \
          | grep -o 'resource_metadata="[^"]*"' | cut -d'"' -f2)
echo "resource_metadata = $PRM_URL"
run "curl --cacert \$CA $PRM_URL"
"${CURL[@]}" "$PRM_URL" | json
AS=$("${CURL[@]}" "$PRM_URL" | python3 -c 'import json,sys;print(json.load(sys.stdin)["authorization_servers"][0])')

say "5. 認可サーバのメタデータ（RFC 8414。未認証で取れる）"
AS_HOST="${AS%%/realms/*}"; AS_PATH="/realms/${AS##*/realms/}"
run "curl --cacert \$CA $AS_HOST/.well-known/oauth-authorization-server$AS_PATH"
"${CURL[@]}" "$AS_HOST/.well-known/oauth-authorization-server$AS_PATH" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);[print(f"  {k} = {d.get(k)}") for k in
    ("issuer","authorization_endpoint","token_endpoint","code_challenge_methods_supported",
     "authorization_response_iss_parameter_supported","client_id_metadata_document_supported")]'

echo
echo "# 不正なトークンは匿名に落とさず 401 になる"
rpc "壊れたトークンで search_records" '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_records","arguments":{"size":1}}}' 'broken.token.here'

[ "$ONLY" = "anon" ] && { echo; echo "（未認証パートのみ実行しました）"; exit 0; }

############################################ 認可コード + PKCE でトークンを取る
say "6. PKCE を作る（S256）"
VERIFIER=$(openssl rand -base64 60 | tr -d '\n=+/' | cut -c1-64)
CHALLENGE=$(printf '%s' "$VERIFIER" | openssl dgst -binary -sha256 | openssl base64 \
            | tr -d '\n=' | tr '+/' '-_')
STATE=$(openssl rand -hex 8)
echo "  code_verifier  = ${VERIFIER:0:20}…"
echo "  code_challenge = $CHALLENGE"

say "7. 認可要求（本来はブラウザ。ここは curl でログインフォームを通す）"
AUTH_URL="$AS/protocol/openid-connect/auth?response_type=code&client_id=$CLIENT_ID&redirect_uri=$REDIRECT&scope=mcp:read&state=$STATE&code_challenge=$CHALLENGE&code_challenge_method=S256&resource=$MCP"
echo "  scope=mcp:read（最小権限から始める）"
echo "  resource=$MCP  ← RFC 8707。Keycloak は無視するが仕様上 MUST"
JAR="$TMP/jar"
LOGIN_PAGE=$("${CURL[@]}" -c "$JAR" -L "$AUTH_URL")
FORM=$(echo "$LOGIN_PAGE" | grep -o 'action="[^"]*login-actions/authenticate[^"]*"' \
       | head -1 | cut -d'"' -f2 | python3 -c 'import html,sys;print(html.unescape(sys.stdin.read().strip()))')
echo "  ログインフォーム: ${FORM:0:80}…"
LOC=$("${CURL[@]}" -b "$JAR" -c "$JAR" -o /dev/null -D - "$FORM" \
      --data-urlencode "username=$TOUR_USER" --data-urlencode "password=$TOUR_PASS" \
      | grep -i '^location:' | tail -1 | tr -d '\r' | sed 's/^[Ll]ocation: //')
CODE=$(echo "$LOC" | grep -o 'code=[^&]*' | cut -d= -f2)
ISS=$(echo "$LOC" | grep -o 'iss=[^&]*' | cut -d= -f2 | python3 -c 'import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()))')
echo "  戻り: ${LOC:0:90}…"
[ -z "$CODE" ] && { echo "!! 認可コードが取れなかった"; exit 1; }

say "8. iss を検証（RFC 9207 — 記録した issuer と単純文字列比較）"
echo "  受け取った iss = $ISS"
echo "  記録した issuer = $AS"
[ "$ISS" = "$AS" ] && echo "  → 一致。続行してよい" || { echo "  → 不一致。中止すべき"; exit 1; }

say "9. トークン要求（code_verifier + resource）"
run "curl --cacert \$CA -d grant_type=authorization_code -d code=… -d code_verifier=… -d resource=$MCP $AS/protocol/openid-connect/token"
TOK=$("${CURL[@]}" -X POST "$AS/protocol/openid-connect/token" \
      -d grant_type=authorization_code -d "code=$CODE" \
      --data-urlencode "redirect_uri=$REDIRECT" -d "client_id=$CLIENT_ID" \
      -d "code_verifier=$VERIFIER" --data-urlencode "resource=$MCP")
ACCESS=$(echo "$TOK" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("access_token",""))')
[ -z "$ACCESS" ] && { echo "!! トークンが取れなかった: $TOK"; exit 1; }
echo "$ACCESS" | cut -d. -f2 | python3 -c '
import base64,json,sys
p=sys.stdin.read().strip(); p+="="*(-len(p)%4)
c=json.loads(base64.urlsafe_b64decode(p))
print("  aud   =", c.get("aud"))
print("  scope =", c.get("scope"))
print("  sub   =", c.get("sub"), "/ email =", c.get("email"))'

say "10. トークンを付けて whoami（MCP → トークン交換 → InvenioRDM）"
rpc "whoami" '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{}}}' "$ACCESS"

say "11. 書込ツールは scope 不足で 403（step-up を促される）"
rpc "create_record（mcp:read しか無い）" '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_record","arguments":{"metadata":{}}}}' "$ACCESS"

say "12. step-up：scope の和集合で取り直して再実行"
echo "  もう一度 scope=mcp:read mcp:write で認可（SSO セッションがあるので再ログイン不要）"
V2=$(openssl rand -base64 60 | tr -d '\n=+/' | cut -c1-64)
C2=$(printf '%s' "$V2" | openssl dgst -binary -sha256 | openssl base64 | tr -d '\n=' | tr '+/' '-_')
AUTH2="$AS/protocol/openid-connect/auth?response_type=code&client_id=$CLIENT_ID&redirect_uri=$REDIRECT&scope=mcp:read%20mcp:write&state=$(openssl rand -hex 8)&code_challenge=$C2&code_challenge_method=S256&resource=$MCP"
LOC2=$("${CURL[@]}" -b "$JAR" -c "$JAR" -o /dev/null -D - "$AUTH2" | grep -i '^location:' | tail -1 | tr -d '\r' | sed 's/^[Ll]ocation: //')
CODE2=$(echo "$LOC2" | grep -o 'code=[^&]*' | cut -d= -f2)
TOK2=$("${CURL[@]}" -X POST "$AS/protocol/openid-connect/token" \
       -d grant_type=authorization_code -d "code=$CODE2" \
       --data-urlencode "redirect_uri=$REDIRECT" -d "client_id=$CLIENT_ID" \
       -d "code_verifier=$V2" --data-urlencode "resource=$MCP")
ACCESS2=$(echo "$TOK2" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("access_token",""))')
[ -z "$ACCESS2" ] && { echo "!! step-up のトークンが取れなかった"; exit 1; }
echo "  新しい scope: $(echo "$ACCESS2" | cut -d. -f2 | python3 -c '
import base64,json,sys;p=sys.stdin.read().strip();p+="="*(-len(p)%4)
print(json.loads(base64.urlsafe_b64decode(p)).get("scope"))')"

RECJSON='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_record","arguments":{"metadata":{"resource_type":{"id":"dataset"},"title":"curl ツアーで作ったレコード","publication_date":"2026-08-14","creators":[{"person_or_org":{"type":"personal","family_name":"研究","given_name":"花子"}}]}}}}'
rpc "create_record（mcp:write あり）" "$RECJSON" "$ACCESS2"

RECID=$(python3 -c '
import json,sys
try:
    d=json.load(open(sys.argv[1])); print(json.loads(d["result"]["content"][0]["text"]).get("id",""))
except Exception: print("")' "$TMP/body")
if [ -n "$RECID" ]; then
  echo
  echo "# 後片付け: 作った下書き $RECID を破棄"
  rpc "delete_draft" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"delete_draft\",\"arguments\":{\"recid\":\"$RECID\"}}}" "$ACCESS2"
fi

say "おわり"
cat <<EOF
体験できたこと:
  * 公開情報は**未認証で読める**（1〜2）
  * 認可が要る操作で **401 + WWW-Authenticate** が返り、そこから
    保護リソースメタデータ → 認可サーバメタデータ と辿れる（3〜5）
  * 不正なトークンは匿名に落とさず 401（5 の最後）
  * PKCE(S256) + resource + iss 検証でトークンを取る（6〜9）
  * scope 不足は **403 insufficient_scope**、和集合で取り直すと通る（11〜12）
EOF
