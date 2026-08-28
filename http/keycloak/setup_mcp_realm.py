#!/usr/bin/env python3
"""MCP 認可 PoC 用の Keycloak realm `mcp` を Admin REST API で構成する（冪等）。

構成物:
  client scope `mcp:read` / `mcp:write` / `mcp:curate`
                                         … audience mapper で aud=<MCP サーバ canonical URI>
  client scope `invenio:api`             … audience mapper で aud=invenio-api
  client `mcp-server`  (confidential)    … RFC 8693 標準トークン交換の実行主体
  client `invenio-api` (confidential)    … 交換先オーディエンスの実体
  user   researcher@example.org          … Invenio 未登録（JIT 作成の確認用）
  user   admin@test.com                  … Invenio 既存ユーザ（id=1）に一致
  匿名 DCR（RFC 7591）を PoC 用に開放     … trusted-hosts ポリシーを撤去

realm 既定の *optional* client scope に mcp:read / mcp:write を入れることで、
動的登録された（＝事前に何も知らない）MCP クライアントでも要求できるようにする。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KC = os.environ.get("KC_BASE", "http://gx10-b61b:18080").rstrip("/")
REALM = os.environ.get("KC_REALM", "mcp")
ADMIN_USER = os.environ.get("KC_ADMIN", "admin")
ADMIN_PASS = os.environ.get("KC_ADMIN_PASSWORD", "admin")

# MCP サーバの canonical URI（RFC 8707 の resource 値／トークンの aud）
MCP_RESOURCE = os.environ.get("MCP_RESOURCE", "http://127.0.0.1:9100/mcp")

# 認可必須の入口（mcp_server.py の MCP_AUTH_PATH）。RFC 9728 では保護リソースごとに
# canonical URI が要るので、こちらも独立した audience として aud に載せる。
# 「最初の接続が 401 でないと認可を始めない」クライアント（mcp-remote 等）向けの入口。
MCP_AUTH_RESOURCE = os.environ.get(
    "MCP_AUTH_RESOURCE", MCP_RESOURCE.rsplit("/", 1)[0] + "/mcp-auth"
)
MCP_SERVER_SECRET = os.environ.get("MCP_SERVER_SECRET", "mcp-server-secret")
INVENIO_CLIENT_ID = "invenio-api"

# CIMD（Client ID Metadata Documents）で受け入れるドメイン。
# client_id の host だけでなく redirect_uri の host も照合されるため localhost 系も要る。
# k8s 版（jc2-k8s-sample）は CIMD_DOMAINS=cimd.jc2.localhost,127.0.0.1,localhost を渡す。
CIMD_DOMAINS = [d.strip() for d in os.environ.get(
    "CIMD_DOMAINS", "cimd.example,*.cimd.example,127.0.0.1,localhost").split(",") if d.strip()]


def _req(method, path, body=None, token=None, form=None):
    url = path if path.startswith("http") else f"{KC}{path}"
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            loc = r.headers.get("Location")
            if not raw:
                return r.status, None, loc
            try:
                return r.status, json.loads(raw), loc
            except Exception:
                return r.status, raw, loc
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        return e.code, detail, None


def admin_token():
    st, body, _ = _req(
        "POST",
        "/realms/master/protocol/openid-connect/token",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASS,
        },
    )
    if st != 200:
        sys.exit(f"admin token 取得失敗: {st} {body}")
    return body["access_token"]


T = None


def get(path):
    st, body, _ = _req("GET", path, token=T)
    return body if st == 200 else None


def post(path, body):
    st, resp, loc = _req("POST", path, body=body, token=T)
    if st not in (200, 201, 204):
        print(f"  ! POST {path} -> {st} {resp}", file=sys.stderr)
        return None
    return loc.rstrip("/").rsplit("/", 1)[-1] if loc else True


def put(path, body):
    st, resp, _ = _req("PUT", path, body=body, token=T)
    if st not in (200, 204):
        print(f"  ! PUT {path} -> {st} {resp}", file=sys.stderr)
    return st


def delete(path):
    st, resp, _ = _req("DELETE", path, token=T)
    return st


# ---------------------------------------------------------------- realm
def ensure_realm():
    if get(f"/admin/realms/{REALM}"):
        print(f"realm {REALM}: 既存 → 作り直し")
        delete(f"/admin/realms/{REALM}")
    post(
        "/admin/realms",
        {
            "realm": REALM,
            "enabled": True,
            "displayName": "MCP Authorization PoC",
            # PoC は HTTP。本番は必ず external/all にする。
            "sslRequired": "none",
            "registrationAllowed": False,
            "accessTokenLifespan": 900,
            # SSO セッションの無操作タイムアウト。Keycloak 既定は 30 分だが、
            # 切れるたびに認可フローをやり直すことになり、Claude Desktop 経由だと
            # **MCP 要求の 60 秒タイムアウト**でプロセスが作り直されて
            # PKCE の code_verifier が入れ替わり、pkce_verification_failed で失敗する。
            # 断続的に1日使う想定で 8 時間にする。
            # ssoSessionMaxLifespan（既定 10 時間）は据え置き、上限は必ず効かせる。
            "ssoSessionIdleTimeout": 28800,
            # リフレッシュトークンのローテーション。
            # Keycloak には「リフレッシュトークンの寿命」という独立した設定が無く、
            # 実効寿命は上の ssoSessionIdleTimeout（上限 ssoSessionMaxLifespan）で決まる。
            # 寿命を縮めると再認証が頻発して実用にならないので、代わりに
            # **使い捨てに近づける**。使い回しは
            # `invalid_grant: Maximum allowed refresh token reuse exceeded` で弾かれる。
            #
            # maxReuse は 0 ではなく **1**。0（1回も許さない）にすると、
            # Claude Desktop がプロセスを作り直したときに2つのインスタンスが
            # 同じ tokens.json で同時に更新し、片方が「使い回し」と判定されて
            # **セッションごと吹き飛ぶ**（＝手動ログインからやり直し）。
            # 1 なら競合1回ぶんを吸収でき、継続的な再利用は依然として弾ける。
            # 実測: 同じ refresh_token は 2 回まで通り、3 回目で拒否される。
            "revokeRefreshToken": True,
            "refreshTokenMaxReuse": 1,
        },
    )
    print(f"realm {REALM}: 作成")


# ---------------------------------------------------------- client scopes
def ensure_scope(name, audience, description, client_audience=None, extra_audience=None):
    """audience mapper 付きの client scope を作る。

    Keycloak は RFC 8707 の resource パラメータを解釈しないため、
    「scope を要求する → その scope の audience mapper が aud を立てる」
    という Keycloak 公式の回避策で audience binding を成立させる。

    client_audience を渡すと Keycloak のクライアント ID も aud に加える。
    これは MCP 仕様のためではなく Keycloak の標準トークン交換の前提
    （交換を要求するクライアントが subject_token の aud に含まれること）を
    満たすため。MCP クライアントから見た宛先はあくまで canonical URI 側。
    """
    sid = post(
        f"/admin/realms/{REALM}/client-scopes",
        {
            "name": name,
            "description": description,
            "protocol": "openid-connect",
            "attributes": {
                "include.in.token.scope": "true",
                "display.on.consent.screen": "true",
                "consent.screen.text": description,
            },
        },
    )
    if not sid:
        return None
    post(
        f"/admin/realms/{REALM}/client-scopes/{sid}/protocol-mappers/models",
        {
            "name": f"aud-{name}",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {
                "included.custom.audience": audience,
                "access.token.claim": "true",
                "id.token.claim": "false",
                "introspection.token.claim": "true",
            },
        },
    )
    if extra_audience:
        # 認可必須の入口（別 canonical URI）にも同じトークンで入れるようにする。
        # 両方の aud を載せるので、/mcp と /mcp-auth のどちらから来ても検証が通る。
        post(
            f"/admin/realms/{REALM}/client-scopes/{sid}/protocol-mappers/models",
            {
                "name": f"aud-alt-{name}",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.custom.audience": extra_audience,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                    "introspection.token.claim": "true",
                },
            },
        )
    if client_audience:
        post(
            f"/admin/realms/{REALM}/client-scopes/{sid}/protocol-mappers/models",
            {
                "name": f"aud-client-{name}",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": client_audience,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                    "introspection.token.claim": "true",
                },
            },
        )
    extra = f" +{client_audience}" if client_audience else ""
    if extra_audience:
        extra += f" +{extra_audience}"
    print(f"client scope {name}: 作成 (aud={audience}{extra})")
    return sid


def add_realm_default_optional_scope(scope_id):
    put(f"/admin/realms/{REALM}/default-optional-client-scopes/{scope_id}", {})


# --------------------------------------------------------------- clients
def ensure_mcp_server_client():
    cid = post(
        f"/admin/realms/{REALM}/clients",
        {
            "clientId": "mcp-server",
            "name": "MCP Server (resource server / token exchange actor)",
            "enabled": True,
            "publicClient": False,
            "secret": MCP_SERVER_SECRET,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "attributes": {
                # RFC 8693 標準トークン交換（Keycloak 26.2+ / feature: token-exchange-standard）
                "standard.token.exchange.enabled": "true",
            },
        },
    )
    print("client mcp-server: 作成")
    return cid


def ensure_curl_tour_client():
    """curl で認可コードフローを体験するための**事前登録**クライアント。

    仕様が認めるクライアント登録は CIMD / 事前登録 / 動的登録の3つ。
    動的登録したクライアントには匿名 DCR ポリシーで同意画面が強制されるため、
    シェルだけで完走させるのが煩雑になる。ここは事前登録（同意なし）にして、
    `curl-tour.sh` が素の curl だけで PKCE + 認可コードを通せるようにする。
    PKCE は realm の client policy で全クライアントに強制されているので、
    このクライアントでも省略はできない。
    """
    cid = post(
        f"/admin/realms/{REALM}/clients",
        {
            "clientId": "curl-tour",
            "name": "curl で挙動を体験するための事前登録クライアント",
            "enabled": True,
            "publicClient": True,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "consentRequired": False,
            "redirectUris": ["http://127.0.0.1:8765/callback"],
            "attributes": {"post.logout.redirect.uris": "+"},
        },
    )
    print("client curl-tour: 作成（curl 体験用・事前登録）")
    return cid


def ensure_invenio_client():
    cid = post(
        f"/admin/realms/{REALM}/clients",
        {
            "clientId": INVENIO_CLIENT_ID,
            "name": "InvenioRDM REST API (audience target)",
            "enabled": True,
            "publicClient": False,
            "secret": "invenio-api-secret",
            "standardFlowEnabled": False,
            "serviceAccountsEnabled": False,
        },
    )
    print(f"client {INVENIO_CLIENT_ID}: 作成")
    return cid


def assign_optional_scope(client_uuid, scope_id):
    put(f"/admin/realms/{REALM}/clients/{client_uuid}/optional-client-scopes/{scope_id}", {})


def assign_default_scope(client_uuid, scope_id):
    put(f"/admin/realms/{REALM}/clients/{client_uuid}/default-client-scopes/{scope_id}", {})


# ----------------------------------------------------------------- users
def ensure_user(username, email, password, first, last):
    uid = post(
        f"/admin/realms/{REALM}/users",
        {
            "username": username,
            "email": email,
            "emailVerified": True,
            "enabled": True,
            "firstName": first,
            "lastName": last,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        },
    )
    print(f"user {username} <{email}>: 作成")
    return uid


# -------------------------------------------------- 匿名 DCR（RFC 7591）
def open_anonymous_dcr():
    """PoC 用に匿名動的クライアント登録を通す。

    Keycloak は既定で `trusted-hosts` ポリシーにより匿名 DCR を拒否する。
    PoC ではこれを外す（本番では信頼ホストを列挙するか CIMD に寄せる）。
    """
    comps = get(
        f"/admin/realms/{REALM}/components"
        f"?type=org.keycloak.services.clientregistration.policy.ClientRegistrationPolicy"
    ) or []
    for c in comps:
        if c.get("providerId") == "trusted-hosts" and c.get("subType") == "anonymous":
            delete(f"/admin/realms/{REALM}/components/{c['id']}")
            print("client-registration policy trusted-hosts(anonymous): 削除")

    # 「Allowed Client Scopes」ポリシー（providerId は allowed-client-templates）は
    # 既定が allow-default-scopes だけで、realm の**既定**スコープしか認めない。
    # mcp:read / mcp:write は optional スコープなので、登録要求の `scope` に載せる
    # クライアントは 400 insufficient_scope で弾かれる。
    #   Policy 'Allowed Client Scopes' rejected request to client-registration service.
    # `openid` も入れる: realm にその名前のクライアントスコープは存在しないが、
    # OIDC クライアントは `scope` に必ず openid を含めるため、これが無いと同じ理由で落ちる。
    # （mcp_client.py は登録時に scope を送らないので影響を受けず、この穴に気づけなかった）
    for c in comps:
        if c.get("providerId") == "allowed-client-templates":
            cfg = c.setdefault("config", {})
            cfg["allowed-client-scopes"] = [
                "mcp:read", "mcp:write", "mcp:curate", "openid"]
            put(f"/admin/realms/{REALM}/components/{c['id']}", c)
            print(
                "client-registration policy allowed-client-templates"
                f"({c.get('subType')}): mcp:read / mcp:write / "
                "mcp:curate / openid を許可"
            )


def configure_client_policies():
    """client policy を2本入れる。profiles/policies は全置換なのでまとめて PUT する。

    1) oauth21     — 全クライアントに PKCE(S256) を強制。
       OAuth 2.1 は認可コードフローで PKCE を必須にしているが、Keycloak は既定では
       「送られてくれば検証する」だけ。pkce-enforcer で「送らないクライアントを拒否」に
       して初めて OAuth 2.1 の要件を満たす。
    2) cimd        — client_id が HTTPS URL のクライアント（Client ID Metadata
       Documents）を受け付ける。MCP 2026-07-28 が推す登録方式で、動的登録の代わり。
    """
    put(
        f"/admin/realms/{REALM}/client-policies/profiles",
        {
            "profiles": [
                {
                    "name": "oauth21",
                    "description": "OAuth 2.1: PKCE(S256) 必須",
                    "executors": [
                        {"executor": "pkce-enforcer", "configuration": {"auto-configure": True}}
                    ],
                },
                {
                    "name": "cimd",
                    "description": "Client ID Metadata Documents を受理",
                    "executors": [
                        {
                            "executor": "client-id-metadata-document",
                            "configuration": {
                                # PoC のみ。redirect_uri が http://127.0.0.1:... のため必要。
                                "cimd-allow-http-scheme": True,
                                # client_id の host と redirect_uri の host の両方が対象
                                "cimd-allow-permitted-domains": CIMD_DOMAINS,
                                "cimd-restrict-same-domain": False,
                                "cimd-required-properties": [
                                    "client_id", "client_name", "redirect_uris",
                                ],
                                "only-allow-confidential-client": False,
                            },
                        }
                    ],
                },
            ]
        },
    )
    put(
        f"/admin/realms/{REALM}/client-policies/policies",
        {
            "policies": [
                {
                    "name": "oauth21-all-clients",
                    "description": "全クライアントに oauth21 プロファイルを適用",
                    "enabled": True,
                    "conditions": [{"condition": "any-client", "configuration": {}}],
                    "profiles": ["oauth21"],
                },
                {
                    "name": "cimd-clients",
                    "description": "client_id が https URL のクライアントに cimd を適用",
                    "enabled": True,
                    "conditions": [
                        {
                            "condition": "client-id-uri",
                            "configuration": {
                                "client-id-uri-scheme": ["https"],
                                "client-id-uri-allow-permitted-domains": CIMD_DOMAINS,
                            },
                        }
                    ],
                    "profiles": ["cimd"],
                },
            ]
        },
    )
    print("client policy: oauth21(PKCE 強制) / cimd(Client ID Metadata Documents) を適用")


def main():
    global T
    T = admin_token()
    ensure_realm()

    read_id = ensure_scope("mcp:read", MCP_RESOURCE, "MCP サーバの読取ツール", "mcp-server",
                           extra_audience=MCP_AUTH_RESOURCE)
    write_id = ensure_scope("mcp:write", MCP_RESOURCE, "MCP サーバの書込ツール", "mcp-server",
                            extra_audience=MCP_AUTH_RESOURCE)
    # 公開レコードの取り下げ・復元。write より重い破壊的操作なので別の scope にする。
    # ロール名ではなく能力名にする（渡すのは取り下げと復元の2操作だけ）。
    del_id = ensure_scope("mcp:curate", MCP_RESOURCE,
                          "公開レコードの取り下げと復元（キュレーション）", "mcp-server",
                          extra_audience=MCP_AUTH_RESOURCE)
    inv_id = ensure_scope("invenio:api", INVENIO_CLIENT_ID, "InvenioRDM REST API")

    # 動的登録クライアントでも要求できるように realm 既定の optional scope にする
    for sid in (read_id, write_id, del_id):
        add_realm_default_optional_scope(sid)
    print("realm default optional client scopes: mcp:read, mcp:write, mcp:curate")

    mcp_uuid = ensure_mcp_server_client()
    ensure_invenio_client()
    tour_uuid = ensure_curl_tour_client()
    for sid in (read_id, write_id, del_id):
        assign_optional_scope(tour_uuid, sid)
    # 交換後トークンに aud=invenio-api を立てるための scope
    assign_optional_scope(mcp_uuid, inv_id)
    assign_default_scope(mcp_uuid, read_id)
    assign_default_scope(mcp_uuid, write_id)
    assign_default_scope(mcp_uuid, del_id)

    ensure_user("researcher", "researcher@example.org", "researcher", "花子", "研究")
    ensure_user("rdmadmin", "admin@test.com", "rdmadmin", "太郎", "管理")

    open_anonymous_dcr()
    configure_client_policies()

    print("\n--- 確認 ---")
    md = get(f"/realms/{REALM}/.well-known/openid-configuration")
    for k in (
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "code_challenge_methods_supported",
        "client_id_metadata_document_supported",
        "authorization_response_iss_parameter_supported",
    ):
        print(f"{k}: {md.get(k)}")


if __name__ == "__main__":
    main()
