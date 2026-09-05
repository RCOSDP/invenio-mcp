#!/usr/bin/env python3
"""MCP 2026-07-28 authorization の適合クライアント（headless E2E 検証）。

ブラウザの代わりに Keycloak のログイン／同意フォームを機械的に通し、
仕様が MUST / SHOULD と書いている各項目を実測して PASS/FAIL を出す。

  1. 未認証で公開情報は読めること、認可の要るツールで 401 と WWW-Authenticate を得ること
  2. resource_metadata から RFC 9728 保護リソースメタデータを取る
  3. authorization_servers から AS メタデータを取る（RFC 8414 → OIDC の順）
  4. クライアント登録（CIMD 優先、無ければ RFC 7591 動的登録）
  5. PKCE(S256) + resource(RFC 8707) + state で認可要求、issuer を記録
  6. 認可応答の iss を RFC 9207 の表どおりに検証
  7. code_verifier + resource でトークン要求、aud を確認
  8. 認証済みで tools/list・tools/call
  9. write 系ツールで 403 insufficient_scope → step-up 再認可 → 再試行
 10. 別オーディエンス（Invenio 宛）のトークンを持ち込んで 401 になることを確認
"""
import base64
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

MCP_URL = os.environ.get("MCP_RESOURCE", "http://127.0.0.1:9100/mcp")
REDIRECT = "http://127.0.0.1:8765/callback"
CIMD_URL = os.environ.get("MCP_CIMD_URL")  # 設定されていれば CIMD を優先

# MCP_TEST_IDP を設定すると、認可サーバのローカルログインではなく
# その alias の外部 IdP（本 PoC では学認 SAML ブローカ）を経由する。
IDP = os.environ.get("MCP_TEST_IDP")
if IDP:
    USERNAME = os.environ.get("MCP_TEST_USER", "gakunin-user")
    PASSWORD = os.environ.get("MCP_TEST_PASSWORD", "Gakunin1!")
else:
    USERNAME = os.environ.get("MCP_TEST_USER", "researcher")
    PASSWORD = os.environ.get("MCP_TEST_PASSWORD", "researcher")

RESULTS = []


def check(name, ok, detail="", known_gap=False):
    """known_gap=True は「仕様は求めるが実装が未対応」と分かっている項目。

    落ちても集計上の FAIL にはせず、GAP として別勘定にする（隠さないための区別）。
    """
    label = "PASS" if ok else ("GAP " if known_gap else "FAIL")
    RESULTS.append((name, ok, known_gap))
    print(f"  [{label}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def jwt_claims(tok: str) -> dict:
    p = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


# ------------------------------------------------------------- HTTP 基本
def req(url, data=None, headers=None, method=None):
    body = None
    h = dict(headers or {})
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(data, (bytes, bytearray)):
        body = bytes(data)
    req = urllib.request.Request(url, data=body, headers=h, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def get_json(url):
    st, h, b = req(url)
    return st, (json.loads(b) if b else None)


def parse_www_authenticate(value: str) -> dict:
    """`Bearer k="v", k2="v2"` を辞書にする。"""
    out = {}
    for k, v in re.findall(r'(\w+)="([^"]*)"', value or ""):
        out[k] = v
    return out


def mcp_post(payload, token=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    st, hdrs, b = req(MCP_URL, data=json.dumps(payload).encode(), headers=h, method="POST")
    hdrs = {k.lower(): v for k, v in hdrs.items()}
    try:
        parsed = json.loads(b)
    except Exception:
        parsed = b.decode("utf-8", "replace")
    return st, hdrs, parsed


def tools_call(name, args, token):
    return mcp_post(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": args}},
        token,
    )


def tool_result(body):
    """ツールの戻り値を取り出す。

    ⚠️ **`content[0]["text"]` を読んではいけない。**〔PoC実測 2026-09-05・mcp 1.26〕
    FastMCP は list を返すツールの戻り値を、**要素ごとに1つの content ブロック**へ
    ばらす（`func_metadata._convert_to_content`）。したがって

    - **0 件なら `content` は空**で、`content[0]` は IndexError になる
      （公開レコードが 1 件も無い作りたての環境では、ここで適合テストが全滅する）
    - **N 件なら `content[0]` は先頭の1件**であって全体ではない。
      `len(json.loads(content[0]["text"]))` は件数ではなく
      **先頭レコードの項目数**を数えていた

    構造化出力（`structuredContent`）は戻り値そのものなので、そちらを見る。
    list を返すツールは `{"result": [...]}` に包まれる（FastMCP の wrap_output）。
    `structuredContent` を持たない相手のために content からの復元も残してある。
    """
    res = body.get("result") or {}
    sc = res.get("structuredContent")
    if sc is not None:
        if isinstance(sc, dict) and list(sc) == ["result"]:
            return sc["result"]
        return sc
    blocks = res.get("content") or []
    if not blocks:
        return None
    if len(blocks) == 1:
        return json.loads(blocks[0]["text"])
    return [json.loads(b["text"]) for b in blocks]


# --------------------------------------- ブラウザ相当（リダイレクト手動追従）
class Browser:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect()
        )
        self.op.addheaders = [("User-Agent", "mcp-conformance-client/1.0")]

    def open(self, url, data=None):
        d = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            r = self.op.open(url, d, timeout=30)
            return r.getcode(), r.geturl(), r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, url, e.read().decode("utf-8", "replace"), dict(e.headers)

    def follow(self, res, stop_prefix, maxn=15):
        c, u, b, h = res
        n = 0
        while c in (301, 302, 303, 307, 308) and h.get("Location") and n < maxn:
            loc = urllib.parse.urljoin(u, h["Location"])
            if loc.startswith(stop_prefix):
                return c, loc, b, h
            n += 1
            c, u, b, h = self.open(loc)
        return c, u, b, h


def extract_form(body):
    m = re.search(r'<form[^>]+action="([^"]+)"', body)
    fields = {}
    for n, v in re.findall(r'name="([^"]+)"[^>]*\svalue="([^"]*)"', body):
        fields[html.unescape(n)] = html.unescape(v)
    return (html.unescape(m.group(1)) if m else None), fields


def authorize(md, client_id, scopes, browser, client_secret=None):
    """認可コード + PKCE(S256) + resource。戻り値は (access_token, 検証メモ)。"""
    verifier = b64u(os.urandom(32))
    challenge = b64u(hashlib.sha256(verifier.encode()).digest())
    state = b64u(os.urandom(16))
    expected_issuer = md["issuer"]            # ← 認可要求の**前**に記録する（RFC 9207）

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # RFC 8707: 認可要求・トークン要求の両方に MUST。Keycloak は無視するが必ず送る。
        "resource": MCP_URL,
    }
    url = md["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

    c, u, b, h = browser.follow(browser.open(url), REDIRECT)
    used_broker = False
    for _ in range(12):
        if u.startswith(REDIRECT):
            break

        # 学認などの外部 IdP を使う場合、認可サーバのログイン画面に出る
        # 「この IdP でログイン」リンクへ最初に飛ぶ（＝学認 DS のボタン相当）
        if IDP and not used_broker:
            m = re.search(r'href="([^"]*/broker/' + re.escape(IDP) + r'/login[^"]*)"', b)
            if m:
                used_broker = True
                link = urllib.parse.urljoin(u, html.unescape(m.group(1)).replace("\\/", "/"))
                c, u, b, h = browser.follow(browser.open(link), REDIRECT)
                continue

        act, fields = extract_form(b)
        if not act:
            raise SystemExit(f"認可画面の form が見つからない (status={c})\n{b[:400]}")
        act = urllib.parse.urljoin(u, act)   # Keycloak の form action は相対 URL
        if "SAMLRequest" in fields or "SAMLResponse" in fields:
            pass                              # SAML の自動 POST（ブラウザが素通しする分）
        elif "login-actions/authenticate" in act:
            fields.update({"username": USERNAME, "password": PASSWORD, "credentialId": ""})
        elif "login-actions/consent" in act:
            fields.update({"accept": "Yes"})
        c, u, b, h = browser.follow(browser.open(act, fields), REDIRECT)

    if not u.startswith(REDIRECT):
        raise SystemExit(f"redirect_uri に到達しなかった: {u}\n{b[:400]}")

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    notes = {}

    # --- RFC 9207: 認可応答の iss 検証 -------------------------------------
    advertised = md.get("authorization_response_iss_parameter_supported") is True
    got_iss = qs.get("iss", [None])[0]
    if advertised and got_iss is None:
        raise SystemExit("AS は iss を出すと宣言しているのに応答に iss が無い → 拒否")
    if got_iss is not None:
        # 単純文字列比較（正規化してはならない）
        notes["iss_match"] = got_iss == expected_issuer
        if not notes["iss_match"]:
            raise SystemExit(f"iss 不一致: {got_iss!r} != {expected_issuer!r}")
    notes["iss_advertised"] = advertised
    notes["iss_present"] = got_iss is not None

    if qs.get("state", [None])[0] != state:
        raise SystemExit("state 不一致")
    if "code" not in qs:
        raise SystemExit(f"認可コードが無い: {qs}")

    data = {
        "grant_type": "authorization_code",
        "code": qs["code"][0],
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": MCP_URL,
    }
    if client_secret:
        data["client_secret"] = client_secret
    st, hdrs, b = req(md["token_endpoint"], data=data)
    if st != 200:
        raise SystemExit(f"トークン要求失敗: {st} {b[:300]}")
    tok = json.loads(b)
    notes["scope"] = tok.get("scope")
    notes["verifier"] = verifier
    return tok["access_token"], notes


# ------------------------------------------------------------------ 本体
def main():
    br = Browser()

    print("\n=== 1. 未認証アクセス（公開情報は読める / 認可が要るものは 401）===")
    # リポジトリの公開レコードは誰でも見られるべきなので、MCP でも未認証で通す。
    st, hdrs, body = mcp_post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    check("未認証でも tools/list は 200", st == 200, f"status={st}")

    st, hdrs, body = tools_call("search_records", {"size": 3}, None)
    ok = st == 200 and not body.get("result", {}).get("isError")
    # **0 件でも合格である。**ここで見ているのは「未認証でも検索が通ること」であって、
    # レコードがあることではない（作りたての環境には 1 件も無い）。
    recs = tool_result(body) if ok else None
    n = len(recs) if isinstance(recs, list) else -1
    check("未認証でも公開レコードを検索できる", ok, f"status={st} 件数={n}")

    # 認可の要るツールを呼んだときに 401 チャレンジが返る。
    # ここが仕様の発見フロー（PRM → AS メタデータ）の入口になる。
    st, hdrs, body = tools_call("create_record", {"metadata": {}}, None)
    check("未認証で write 系ツールは 401", st == 401, f"status={st}")
    wa = parse_www_authenticate(hdrs.get("www-authenticate", ""))
    check("WWW-Authenticate に resource_metadata", "resource_metadata" in wa,
          wa.get("resource_metadata", ""))
    check("WWW-Authenticate に scope (2026-07-28 SHOULD)", "scope" in wa, wa.get("scope", ""))
    challenge_scopes = wa.get("scope", "").split()   # ここでは mcp:write が返る

    print("\n=== 2. RFC 9728 保護リソースメタデータ ===")
    wa_initial_prm = wa["resource_metadata"]
    st, prm = get_json(wa_initial_prm)
    check("PRM が 200", st == 200)
    check("resource が canonical URI と一致", prm.get("resource") == MCP_URL,
          str(prm.get("resource")))
    check("authorization_servers がある", bool(prm.get("authorization_servers")),
          str(prm.get("authorization_servers")))
    check("scopes_supported がある", bool(prm.get("scopes_supported")),
          str(prm.get("scopes_supported")))
    as_issuer = prm["authorization_servers"][0]

    # 最初の認可は **PRM の scopes_supported（最小集合）** で始める。
    # 仕様の scope 選択は「401 の challenge があればそれ、無ければ scopes_supported」だが、
    # ここでは最小権限から始めて step-up を実際に踏むために scopes_supported を使う
    # （write の challenge は上で検証済み）。
    initial_scopes = prm.get("scopes_supported") or challenge_scopes

    print("\n=== 3. 認可サーバメタデータ探索（RFC 8414 → OIDC Discovery）===")
    p = urllib.parse.urlparse(as_issuer)
    rfc8414 = f"{p.scheme}://{p.netloc}/.well-known/oauth-authorization-server{p.path}"
    oidc = f"{as_issuer.rstrip('/')}/.well-known/openid-configuration"
    st, md = get_json(rfc8414)
    used = "RFC 8414"
    if st != 200:
        st, md = get_json(oidc)
        used = "OIDC Discovery"
    check(f"AS メタデータ取得（{used}）", st == 200, rfc8414 if used == "RFC 8414" else oidc)
    check("issuer が PRM の値と一致", md.get("issuer") == as_issuer, str(md.get("issuer")))
    check("PKCE S256 対応", "S256" in (md.get("code_challenge_methods_supported") or []))
    check("RFC 9207 iss を宣言", md.get("authorization_response_iss_parameter_supported") is True)
    check("RFC 8707 resource 対応を宣言", "resource_indicators_supported" in md or
          bool(md.get("resource_parameter_supported")),
          "Keycloak 26.7.1 は RFC 8707 未対応。scope+audience mapper で aud を立てて代替",
          known_gap=True)

    print("\n=== 4. クライアント登録 ===")
    client_secret = None
    if CIMD_URL and md.get("client_id_metadata_document_supported"):
        client_id = CIMD_URL
        check("Client ID Metadata Document を使用", True, CIMD_URL)
    else:
        if CIMD_URL:
            check("CIMD 利用", False, "AS が未対応")
        check("AS が CIMD 対応を宣言", md.get("client_id_metadata_document_supported") is True,
              "client_id_metadata_document_supported=true")
        reg = {
            "client_name": "MCP Conformance Test Client",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            # OIDC AS では既定が "web" になり localhost の redirect_uri と衝突しうる
            "application_type": "native",
        }
        st, hdrs, b = req(md["registration_endpoint"], data=json.dumps(reg).encode(),
                           headers={"Content-Type": "application/json"}, method="POST")
        check("RFC 7591 動的クライアント登録", st in (200, 201), f"status={st} {b[:160]}")
        info = json.loads(b)
        client_id = info["client_id"]
        client_secret = info.get("client_secret")
        print(f"       client_id={client_id}")

    print("\n=== 5-7. 認可コード + PKCE(S256) + resource → トークン ===")
    scopes = initial_scopes or prm.get("scopes_supported") or []
    token, notes = authorize(md, client_id, scopes, br, client_secret)
    check("認可コードフロー完了", True, f"scope={notes['scope']}")
    check("RFC 9207 iss を検証（単純文字列比較）",
          notes.get("iss_present") and notes.get("iss_match") is True,
          f"advertised={notes['iss_advertised']} present={notes['iss_present']}")
    c = jwt_claims(token)
    aud = c.get("aud")
    aud = aud if isinstance(aud, list) else [aud]
    check("アクセストークンの aud に canonical URI", MCP_URL in aud, str(aud))
    if IDP:
        # 学認では mail が降りてこない前提。本人性の鍵は eppn。
        check("機関 IdP 由来の eppn がトークンに載る",
              (c.get("eppn") or [None])[0] == "hanako@example.ac.jp", str(c.get("eppn")))
        check("mail は出ない前提でも通る", c.get("email") is None,
              f"email={c.get('email')}")
        check("mAP 由来の isMemberOf が載る", bool(c.get("isMemberOf")),
              str(c.get("isMemberOf")))
        # 機関 IdP の entityID は認可サーバの URL から決まるので、環境ごとに変わる
        # （認可サーバの実際のホスト名は環境により異なる）。
        # AS メタデータの issuer から導出して比較する。
        expected_entity = os.environ.get(
            "MCP_TEST_IDP_ENTITY_ID",
            md["issuer"].rsplit("/realms/", 1)[0] + "/realms/gakunin")
        check("所属が Issuer（機関 IdP entityID）由来で載る",
              (c.get("idp_entity_id") or [None])[0] == expected_entity,
              f"{c.get('idp_entity_id')} (期待 {expected_entity})")
        check("Issuer から引いた機関コードが載る",
              (c.get("tenant_id") or [None])[0] == "example-univ", str(c.get("tenant_id")))
        check("そのセッションで使われた IdP が載る", c.get("idp") == "gakunin",
              str(c.get("idp")))
    else:
        check("トークンの sub / email が本人", c.get("email") == "researcher@example.org",
              str(c.get("email")))

    print("\n=== 8. 認証済みで MCP を呼ぶ ===")
    st, hdrs, body = mcp_post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token)
    check("tools/list が 200", st == 200, f"status={st}")
    names = [t["name"] for t in (body.get("result", {}).get("tools") or [])]
    print(f"       tools: {names}")

    st, hdrs, body = tools_call("whoami", {}, token)
    ok = st == 200 and not body.get("result", {}).get("isError")
    check("whoami（MCP→トークン交換→Invenio）", ok, f"status={st}")
    who = {}
    if ok:
        who = tool_result(body)
        print("       " + json.dumps(who, ensure_ascii=False)[:400])
        inv = who.get("invenio", {})
        check("Invenio 側のユーザに解決されている", bool(inv.get("user_id")),
              f"user_id={inv.get('user_id')} email={inv.get('email')}")
        if IDP:
            # 学認からは mail が降りてこないので、メールは Invenio 側で設定させる。
            # エージェントが利用者に案内できるよう、未設定を検出できること。
            check("メール未設定をエージェントが検出できる",
                  isinstance(inv.get("email_pending_setup"), bool),
                  f"email_pending_setup={inv.get('email_pending_setup')}"
                  f" url={inv.get('profile_settings_url')}")

    st, hdrs, body = tools_call("search_records", {"size": 3}, token)
    check("search_records（mcp:read）", st == 200 and not body.get("result", {}).get("isError"),
          f"status={st}")

    print("\n=== 9. scope 不足 → 403 insufficient_scope → step-up ===")
    st, hdrs, body = tools_call("create_record", {"metadata": {}}, token)
    check("write 系ツールが 403", st == 403, f"status={st}")
    wa2 = parse_www_authenticate(hdrs.get("www-authenticate", ""))
    check("error=insufficient_scope", wa2.get("error") == "insufficient_scope", str(wa2))
    check("必要 scope を提示", wa2.get("scope") == "mcp:write", wa2.get("scope", ""))
    check("403 にも resource_metadata", "resource_metadata" in wa2)

    # 仕様: 直前に要求した scope 集合と、チャレンジの scope の**和集合**で再認可する
    stepped = sorted(set(scopes) | set(wa2.get("scope", "").split()))
    print(f"       step-up 再認可: {stepped}")
    token2, notes2 = authorize(md, client_id, stepped, br, client_secret)
    check("step-up 後のトークン取得", True, f"scope={notes2['scope']}")

    st, hdrs, body = tools_call("create_record", {"metadata": {
        "resource_type": {"id": "dataset"},
        "title": "MCP OAuth 2.1 適合テストで作成したレコード",
        "publication_date": "2026-08-11",
        "creators": [{"person_or_org": {"type": "personal",
                                        "family_name": "研究", "given_name": "花子"}}],
    }}, token2)
    ok = st == 200 and not body.get("result", {}).get("isError")
    check("step-up 後に create_record 成功", ok, f"status={st}")
    recid = None
    if ok:
        rec = tool_result(body)
        recid = rec.get("id")
        print(f"       作成された draft: {recid}")

    print("\n=== 10. 別オーディエンスのトークン持ち込み（拒否されること）===")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from setup_mcp_realm import KC, REALM, MCP_SERVER_SECRET  # noqa: E402
    st, hdrs, b = req(
        f"{KC}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": "mcp-server", "client_secret": MCP_SERVER_SECRET,
            "subject_token": token2,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "invenio-api", "scope": "invenio:api",
        })
    inv_token = json.loads(b)["access_token"]
    st, hdrs, body = mcp_post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, inv_token)
    check("Invenio 宛トークンを MCP に出すと 401", st == 401, f"status={st}")


    print("\n=== 10b. 匿名と認証済みで見えるものが変わる ===")
    st, _, b_anon = tools_call("search_records", {"size": 50}, None)
    st2, _, b_auth = tools_call("search_records", {"size": 50}, token2)
    n_anon = len(tool_result(b_anon) or [])
    n_auth = len(tool_result(b_auth) or [])
    check("匿名でも認証済みでも公開レコードは読める", st == 200 and st2 == 200,
          f"匿名={n_anon}件 / 認証済み={n_auth}件")
    st, _, body = tools_call("whoami", {}, None)
    check("匿名では whoami は通らない（401）", st == 401, f"status={st}")

    print("\n=== 11. 未認証・不正トークンの扱い（仕様: 401 でなければならない）===")
    import time as _time
    import jwt as _jwt
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa

    now = int(_time.time())
    issuer = md["issuer"]

    def expect401(label, tok, detail=""):
        # 匿名で通るはずの tools/list を使う。**トークンが付いている以上、
        # それが不正なら 401 でなければならない**（黙って匿名に落としてはいけない）。
        st, hdrs, _ = mcp_post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tok)
        wa = parse_www_authenticate(hdrs.get("www-authenticate", ""))
        ok = st == 401
        check(label, ok, f"status={st} {detail}".strip())
        return wa

    # (a) そもそも JWT ですらない文字列
    expect401("ゴミ文字列のトークンは 401", "not-a-jwt-at-all")

    # (b) 別の鍵で署名した「それらしい」JWT（他所の IdP が発行したもの相当）。
    #     iss も aud も正しく詐称しているので、**署名検証だけが防波堤**になる。
    _k = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = _jwt.encode({"iss": issuer, "aud": MCP_URL, "sub": "attacker",
                          "iat": now, "exp": now + 3600,
                          "scope": "mcp:read mcp:write"}, _k, algorithm="RS256")
    expect401("別の鍵で署名した偽トークンは 401", forged)

    # (c) issuer が違うトークン（自分の AS 以外が出したもの）
    other = _jwt.encode({"iss": "https://evil.example/realms/mcp", "aud": MCP_URL,
                         "sub": "attacker", "iat": now, "exp": now + 3600,
                         "scope": "mcp:read"}, _k, algorithm="RS256")
    expect401("issuer が違うトークンは 401", other)

    # (d) 本物のトークンの署名部だけ差し替えたもの
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}.{'A' * len(sig)}"
    expect401("署名を改竄した本物のトークンは 401", tampered)

    # (e) Authorization ヘッダのスキームが Bearer でない
    st, hdrs, _ = req(MCP_URL, data=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "Authorization": f"Basic {token}"}, method="POST")
    check("Bearer 以外のスキームは 401", st == 401, f"status={st}")

    # (f) クエリ文字列でトークンを渡す。仕様は
    #     「アクセストークンを URI クエリ文字列に入れてはならない」。
    #     匿名で通るツールでは区別できないので、**認可の要る write 系**で見る。
    #     クエリのトークンが効いていなければ 401 のまま。
    st, hdrs, _ = req(f"{MCP_URL}?access_token={token}", data=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "create_record", "arguments": {"metadata": {}}}}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"}, method="POST")
    check("クエリ文字列のトークンは受理しない（401）", st == 401, f"status={st}")

    # (g) 期限切れトークン。Keycloak に寿命の短いクライアントを作って実際に失効させる。
    #     （サーバ側の検証は leeway 10 秒なので、それを超えて待つ）
    from setup_mcp_realm import REALM as _REALM  # noqa: E402
    _adm = __import__("setup_mcp_realm").admin_token()
    _rq = __import__("setup_mcp_realm")._req
    _st, _cl, _ = _rq("GET", f"/admin/realms/{_REALM}/clients?clientId={client_id}", token=_adm)
    if _cl:
        _uuid = _cl[0]["id"]
        _orig = _cl[0].get("attributes", {}) or {}
        _rq("PUT", f"/admin/realms/{_REALM}/clients/{_uuid}", token=_adm,
            body={**_cl[0], "attributes": {**_orig, "access.token.lifespan": "1"}})
        _short, _ = authorize(md, client_id, scopes, br, client_secret)
        _rq("PUT", f"/admin/realms/{_REALM}/clients/{_uuid}", token=_adm,
            body={**_cl[0], "attributes": _orig})   # 寿命を戻す
        _exp = jwt_claims(_short).get("exp", 0)
        _wait = max(0, _exp - int(_time.time())) + 12   # leeway 10 秒 + 余裕
        print(f"       期限切れを待つ… {_wait} 秒")
        _time.sleep(_wait)
        expect401("期限切れトークンは 401", _short)
    else:
        check("期限切れトークンは 401", False, "クライアントを特定できず検証できなかった")

    # (h) 未認証でも取れなければならないもの（ここが 401 だと発見が成立しない）
    st, _ = get_json(wa_initial_prm)
    check("PRM は未認証で取得できる", st == 200, f"status={st}")
    st, _ = get_json(rfc8414 if used == "RFC 8414" else oidc)
    check("AS メタデータは未認証で取得できる", st == 200, f"status={st}")

    if recid:
        tools_call("delete_draft", {"recid": recid}, token2)
        print(f"\n       後片付け: draft {recid} を破棄")

    ng = [n for n, ok, gap in RESULTS if not ok and not gap]
    gaps = [n for n, ok, gap in RESULTS if not ok and gap]
    passed = [n for n, ok, _ in RESULTS if ok]
    print("\n" + "=" * 62)
    print(f"結果: {len(passed)} PASS / {len(ng)} FAIL / {len(gaps)} 既知ギャップ")
    for n in ng:
        print(f"  FAIL: {n}")
    for n in gaps:
        print(f"  GAP : {n}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
