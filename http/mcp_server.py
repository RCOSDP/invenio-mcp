#!/usr/bin/env python3
"""InvenioRDM MCP サーバ（MCP 2026-07-28 authorization 準拠のリソースサーバ版）。

同梱の stdio/server.py は stdio ＋ 共有 PAT 1本だが、これは
Streamable HTTP ＋ OAuth 2.1 リソースサーバとして動く。

  MCP クライアント ──Bearer(aud=<本サーバの canonical URI>)──▶ 本サーバ
                                                              │ RFC 8693 トークン交換
                                                              ▼
                                          InvenioRDM ◀──Bearer(aud=invenio-api)

仕様対応の要点:
  * RFC 9728 保護リソースメタデータを /.well-known/oauth-protected-resource/mcp に公開
  * トークンは JWKS で署名検証し、aud が**本サーバの canonical URI**であることを必須検証
    （他所宛トークンの持ち込みを拒否）
  * 401 / 403 の WWW-Authenticate に resource_metadata と scope を載せる
  * ツール単位の scope 不足は 403 insufficient_scope で返し、step-up 認可を促す
  * 受け取ったトークンは InvenioRDM へ**転送しない**。必ずトークン交換して
    aud=invenio-api の別トークンにする（confused deputy / トークン中継の禁止）

環境変数:
  MCP_BIND_HOST / MCP_BIND_PORT   既定 127.0.0.1 / 9100
  MCP_RESOURCE                    既定 http://127.0.0.1:9100/mcp（canonical URI）
  KC_ISSUER                       既定 http://localhost:8080/realms/mcp
  MCP_SERVER_SECRET               既定値なし。keycloak モードでは必須（未設定なら停止）
  INVENIO_API                     既定 https://127.0.0.1/api
  MCP_LANG                        ツールの説明・エラーの言語。同梱は en / ja。
                                  未設定ならシステムのロケール、決まらなければ en
  MCP_LOCALES_DIR                 言語リソースの置き場。既定は本ファイルと同じ場所の locales/
"""
from __future__ import annotations

import base64
import hashlib
import heapq
import json
import os
import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.middleware.auth_context import get_access_token
from starlette.types import ASGIApp, Receive, Scope, Send

# セマンティックバージョニング（https://semver.org/lang/ja/）。
# 何を破壊的変更とみなすかは docs/about/versioning.md に書いてある。
# stdio/server.py の __version__ と揃える（tools/check.sh が一致を検査する）。
__version__ = "0.0.2"

# ------------------------------------------------------------------ i18n
# 利用者（と LLM）に見える文字列は locales/<lang>.json に置く。ツールの説明・
# エラー・起動時の表示がその対象で、コード中の注釈は開発者向けなので含めない。
#
# MCP のプロトコルに言語交渉は無い（initialize にロケールの項目が無い）。
# したがって言語は**プロセス単位**で決まる。MCP_LANG が最優先で、無ければ
# システムのロケール（LC_ALL / LC_MESSAGES / LANG）を見て、それでも決まらなければ英語。
# 利用者ごとに言語を変えたいときは、言語ごとにインスタンスを立てる。
#
# locales/ に <tag>.json を置けばその言語が増える（同梱は en と ja）。
_HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.environ.get("MCP_LOCALES_DIR") or os.path.join(_HERE, "locales")
FALLBACK_LANG = "en"


def _available_langs() -> list[str]:
    try:
        return sorted(f[:-5] for f in os.listdir(LOCALES_DIR) if f.endswith(".json"))
    except OSError:
        return []


def _normalize_tag(raw: str) -> str:
    """ja_JP.UTF-8 / ja-JP / JA → ja-jp のような比較しやすい形にする。"""
    return raw.split(".")[0].split("@")[0].strip().replace("_", "-").lower()


def _pick_lang(available: list[str]) -> str:
    explicit = os.environ.get("MCP_LANG", "").strip()
    # 明示指定が未知の言語なら、システムのロケールは見ずに既定へ落とす（意図を優先）
    candidates = [explicit] if explicit else [
        os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG")]
    for raw in candidates:
        if not raw:
            continue
        tag = _normalize_tag(raw)
        if tag in available:          # ja-jp のような地域付きの資源も選べる
            return tag
        if tag.split("-")[0] in available:
            return tag.split("-")[0]
    return FALLBACK_LANG


def _load_lang(lang: str) -> dict:
    with open(os.path.join(LOCALES_DIR, f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


AVAILABLE_LANGS = _available_langs()
LANG = _pick_lang(AVAILABLE_LANGS)
try:
    _STRINGS = _load_lang(LANG)
    _FALLBACK_STRINGS = _STRINGS if LANG == FALLBACK_LANG else _load_lang(FALLBACK_LANG)
except OSError as e:      # ここだけは翻訳できないので両言語で出す
    raise SystemExit(
        f"cannot read language resources: {e}\n"
        "Put locales/ next to this file, or point MCP_LOCALES_DIR at it.\n"
        "言語リソースを読めません。locales/ をこのファイルと同じ場所に置くか "
        "MCP_LOCALES_DIR で指してください。") from e


def _dig(strings: dict, key: str):
    cur = strings
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def t_ascii(key: str, **kw) -> str:
    """HTTP ヘッダに載せる版。**常に英語**で、ASCII 以外を落とす。

    RFC 6750 の error_description に置けるのは ASCII の一部（NQSCHAR）だけなので、
    翻訳文をそのまま WWW-Authenticate に入れることはできない。翻訳は JSON 本文の
    error_description に載せ、ヘッダにはこちらを使う。
    """
    v = _dig(_FALLBACK_STRINGS, key)
    if v is None:
        return key
    if isinstance(v, list):
        v = " ".join(v)
    if kw:
        v = v.format(**kw)
    v = v.encode("ascii", "replace").decode("ascii")
    return v.replace('"', "'").replace("\\", "/")


def t(key: str, **kw) -> str:
    """locales/<lang>.json の文字列を引く。無ければ英語 → キー名の順に落ちる。

    値が配列なら改行で連結する（長い説明文を JSON でも読める形に保つため）。
    書式引数を渡したときだけ format する（説明文に出てくる波括弧を壊さないため）。
    """
    v = _dig(_STRINGS, key)
    if v is None:
        v = _dig(_FALLBACK_STRINGS, key)
    if v is None:
        return key
    if isinstance(v, list):
        v = "\n".join(v)
    return v.format(**kw) if kw else v

# ---------------------------------------------------------------- 設定
BIND_HOST = os.environ.get("MCP_BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("MCP_BIND_PORT", "9100"))
MCP_PATH = "/mcp"
# RFC 8707 の resource 値 ＝ RFC 9728 の resource ＝ トークンの aud
RESOURCE = os.environ.get("MCP_RESOURCE", f"http://{BIND_HOST}:{BIND_PORT}{MCP_PATH}")

KC_ISSUER = os.environ.get("KC_ISSUER", "http://localhost:8080/realms/mcp")
KC_TOKEN_ENDPOINT = f"{KC_ISSUER}/protocol/openid-connect/token"
KC_JWKS = f"{KC_ISSUER}/protocol/openid-connect/certs"
MCP_CLIENT_ID = os.environ.get("MCP_SERVER_CLIENT_ID", "mcp-server")
MCP_CLIENT_SECRET = os.environ.get("MCP_SERVER_SECRET")  # 既定値は置かない

INVENIO_API = os.environ.get("INVENIO_API", "https://127.0.0.1/api").rstrip("/")
INVENIO_UI = os.environ.get("INVENIO_UI", "https://127.0.0.1").rstrip("/")
INVENIO_AUDIENCE = os.environ.get("INVENIO_AUDIENCE", "invenio-api")

# ------------------------------------------------------------------ 認証方式
# keycloak … 既定。MCP 2026-07-28 の認可（OAuth 2.1 + PKCE + RFC 8707 + 8693 交換）
# invenio  … InvenioRDM の個人アクセストークン(PAT)をそのまま Bearer で受ける
#
# なぜ「InvenioRDM を認可サーバにする」ではなく PAT なのか:
#   invenio-oauth2server は PKCE も認可サーバメタデータ(RFC 8414)も動的登録も
#   持たない（実測: /.well-known/* は 404、コードに code_challenge が無い）。
#   認可サーバに据えると、無いメタデータを本サーバが捏造し、PKCE 無しを飲み、
#   クライアントを手登録する足場が要るうえ、それでも MCP 適合には届かない。
#   一方どちらの道でも **InvenioRDM に届くのは InvenioRDM のトークン**で、
#   違うのは入手方法だけ。ならば手間の少ない PAT を採る。
AUTH_MODE = os.environ.get("MCP_AUTH_MODE", "keycloak").lower()
if AUTH_MODE not in ("keycloak", "invenio"):
    raise SystemExit(t("errors.auth_mode_invalid", given=AUTH_MODE))

# PAT には scope が無いので、**InvenioRDM のロール**から MCP scope を導く。
# 素の InvenioRDM が持つ役割をそのまま使うので、追加の語彙も拡張も要らない。
INVENIO_BASE_SCOPES = os.environ.get(
    "MCP_INVENIO_BASE_SCOPES", "mcp:read mcp:write").split()
INVENIO_ROLE_SCOPES = {
    r.strip(): "mcp:curate"
    for r in os.environ.get("MCP_INVENIO_CURATE_ROLES", "admin").split(",") if r.strip()
}
# /me を叩いて検証した結果を持つ秒数（毎リクエスト往復させないため）
INVENIO_VERIFY_TTL = int(os.environ.get("MCP_INVENIO_VERIFY_TTL", "60"))
# invenio-jairo-jwt が「メール未設定」のときに入れる仮アドレスのドメイン
PLACEHOLDER_EMAIL_DOMAIN = os.environ.get("PLACEHOLDER_EMAIL_DOMAIN", "jwt.invalid")

# InvenioRDM への TLS 検証。**既定で有効**。
# 自己署名 CA を使う環境では、CA をシステム CA 束に足した合成ファイルを
# SSL_CERT_FILE / REQUESTS_CA_BUNDLE で指す（k8s 版はマニフェストがそうしている）。
# どうしても検証を切る必要がある場合だけ MCP_TLS_INSECURE=1。
TLS_INSECURE = os.environ.get("MCP_TLS_INSECURE", "").lower() in ("1", "true", "yes")
VERIFY_TLS = not TLS_INSECURE

# 添付として運べる大きさ。MCP の引数も応答も JSON なので、ここが天井になる。
MAX_UPLOAD_BYTES = int(os.environ.get("MCP_MAX_UPLOAD_BYTES", str(16 * 1024 * 1024)))
# 認可を判定するには POST の本文を**全部**読む必要がある。上限が無いと 1 本の POST で
# メモリを食い潰せるので頭を打つ。base64 は 4/3 に膨らみ、JSON の飾りも乗るので、
# 添付の上限の 2 倍を既定にしておく。
MAX_REQUEST_BYTES = int(os.environ.get("MCP_MAX_REQUEST_BYTES",
                                       str(MAX_UPLOAD_BYTES * 2)))

# PRM の scopes_supported は「基本機能に必要な最小集合」（仕様の Scope Minimization）
BASE_SCOPES = ["mcp:read"]

# ツールごとの必要 scope。**None は「未認証でも呼べる」**という意味。
#
# リポジトリは公開レコードを誰にでも見せるものなので、MCP でも
# **公開情報の読取は未認証で通す**（InvenioRDM の REST API 自体がそうなっている）。
# トークンがあればその人として叩くので、自分の下書きなども見える。
# 認可が要るのは「本人でないとできないこと」だけ:
#   whoami        … 身元を答えるものなので認証が要る
#   write 系      … 作成・更新・公開・破棄
#
# 未認証で認可の要るツールを呼ぶと 401 チャレンジを返す。クライアントはそこで
# 初めて認可サーバを知り、認可フローに入る（＝仕様の発見フローの入口になる）。
TOOL_SCOPES = {
    "search_records": None,
    "get_record": None,
    "whoami": "mcp:read",
    "create_record": "mcp:write",
    "update_record": "mcp:write",
    "publish_record": "mcp:write",
    "delete_draft": "mcp:write",
    "new_version": "mcp:write",
    # 公開レコードの取り下げ・復元。write とは別の scope にする:
    #   * InvenioRDM 側で admin 権限が要る破壊的操作で、write より重い
    #   * ロール名（admin）は避ける。渡す力は公開レコードの取り下げと復元だけで、
    #     管理者一般ではない。一方 delete という操作名も実態と合わない
    #     （復元は delete ではないし、delete_draft / delete_file は write 側）。
    #     リポジトリの用語でこの2操作をまとめて指すのが curate。
    #   * 取り下げと復元を分けないのは、InvenioRDM 側でどちらも同じ admin 権限が
    #     要るため。scope だけ割っても実際の権限分離にならず、取り下げたものを
    #     戻せないクライアントが生まれるだけになる
    "delete_record": "mcp:curate",
    "restore_record": "mcp:curate",
    # ファイル系。一覧は公開レコードなら未認証で見せる（get_record と同じ扱い）
    "list_files": None,
    "download_file": None,
    "upload_file": "mcp:write",
    "upload_file_from_url": "mcp:write",
    "delete_file": "mcp:write",
    # 大容量向け（multipart）。3手順に分かれるが、どれも書き込み扱い
    "start_multipart_upload": "mcp:write",
    "complete_multipart_upload": "mcp:write",
    "abort_multipart_upload": "mcp:write",
    # 語彙。公開情報なので未認証で通す（当てずっぽうの id を書かせないため、
    # 読取ツールの中でも特に早い段階で引かれる）
    "list_vocabulary_types": None,
    "list_vocabulary": None,
    # レコードの派生表現・履歴。versions は公開、revisions は認証が要る（実測 403）
    "export_record": None,
    "list_versions": None,
    "list_revisions": "mcp:read",
    # 自分のもの
    "my_records": "mcp:read",
    # コミュニティ。一覧・参照は公開（get_record と同じ扱い）
    "search_communities": None,
    "get_community": None,
    "list_community_records": None,
    # リクエスト（査読・投稿）。自分に見えるものだけが返るので認証が要る
    "list_requests": "mcp:read",
    "get_request": "mcp:read",
    # 投稿とコメントは書込。受理・却下は**キュレーターの判断**なので curate
    "submit_to_community": "mcp:write",
    "comment_on_request": "mcp:write",
    "create_community": "mcp:curate",
    "request_action": "mcp:curate",
}

# **未知のツール名は None を返す＝「未認証で可」と同じ値になる。** つまり
# ツールを足して TOOL_SCOPES に書き忘れると、黙って未認証で公開される。
# 起動時に突き合わせて、食い違っていたら**起動しない**（下の _verify_tool_scopes）。


def _verify_tool_scopes() -> None:
    """登録されたツールと TOOL_SCOPES が1対1であることを確かめる。

    fail-open を構造で潰すための検査。ここで落とすほうが、書き忘れた write ツールが
    未認証で開いたまま動き続けるより、はるかに安い。
    """
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    mapped = set(TOOL_SCOPES)
    unmapped = sorted(registered - mapped)
    stale = sorted(mapped - registered)
    if unmapped or stale:
        raise SystemExit(
            "TOOL_SCOPES と登録済みツールが食い違っている。"
            "未認証で開いてしまうため起動しない。\n"
            f"  TOOL_SCOPES に無い（＝未認証で通ってしまう）: {unmapped}\n"
            f"  登録されていないのに書かれている             : {stale}")


RESOURCE_METADATA_URL = str(build_resource_metadata_url(RESOURCE))  # type: ignore[arg-type]
RESOURCE_METADATA_PATH = urlsplit(RESOURCE_METADATA_URL).path

# 認可必須の入口（同じ保護リソースへの2本目のパス）。
#
# なぜ要るか: クライアントによっては「最初の接続が 401 でなければ認可の準備をしない」
# 作りになっている。mcp-remote 0.1.37 がそれで、コールバック待ち受けを作る
# authInitializer() が connectToRemoteServer の UnauthorizedError 経路からしか
# 呼ばれない。本サーバは未認証でも接続できるので初回接続が成功してしまい、
# あとからツール単位で 401 を返しても待ち受けが無く、認可コードを受け取れない。
#
# そこで /mcp-auth では **initialize の時点から 401** を返す。
#
# これは「同じ資源の別入口」ではなく**独立した保護リソース**として作る。RFC 9728 の
# 保護リソースメタデータは `resource` が接続先の URI と一致していなければならず、
# クライアントはそこを検証する（実測: mcp-remote は
# `Protected resource … does not match expected …` で接続を拒否した）。したがって:
#   * canonical URI は AUTH_RESOURCE（= …/mcp-auth）。専用の PRM を持つ
#   * トークンは両方の aud を持つ（setup_mcp_realm.py が mcp:read/mcp:write に
#     audience mapper を2枚立てる）ので、/mcp と /mcp-auth のどちらからでも使える
#   * ツール単位の scope 判定（403 step-up）はそのまま効く
MCP_AUTH_PATH = os.environ.get("MCP_AUTH_PATH", "/mcp-auth")
_u = urlsplit(RESOURCE)
AUTH_RESOURCE = urlunsplit((_u.scheme, _u.netloc, MCP_AUTH_PATH, "", ""))
AUTH_RESOURCE_METADATA_URL = str(build_resource_metadata_url(AUTH_RESOURCE))  # type: ignore[arg-type]
AUTH_RESOURCE_METADATA_PATH = urlsplit(AUTH_RESOURCE_METADATA_URL).path

# /mcp-auth の広告 scope は **read と write の両方**にする。
# ここに来るクライアントは初回接続の 401 で認可を始めるので、その challenge の
# `scope=` がそのまま認可要求に使われる（実測: mcp-remote は
# "Using scope from WWW-Authenticate header" と記録する）。read だけを広告すると
# 書込ツールで 403 insufficient_scope になるが、**MCP SDK は 401 でしか再認可せず
# 403 を扱えない**ため、既製クライアントはそこで詰む。
# /mcp 側は仕様の Scope Minimization どおり mcp:read だけを広告する（変更なし）。
AUTH_SCOPES = ["mcp:read", "mcp:write", "mcp:curate"]


# ------------------------------------------------ トークン付きキャッシュ
class TokenCache:
    """トークンに紐づく短命な値を持つ。検証結果と交換後トークンで使う。

    素の dict にしないのは2つの理由による。

    * **鍵に生のトークンを置かない。** 必要なのは同一性の判定だけで、鍵から
      元のトークンへ戻せる必要はない。dict の鍵はプロセスのメモリにそのまま
      残るので、コアダンプや覗き見に生のトークンを晒す理由が無い。
    * **期限切れを捨てる。** TTL で「使わない」ようにするだけでは足りない。
      捨てなければ、期限の切れた交換後トークンがプロセスに残り続け、鍵の数も
      単調に増える。引くたびに掃くので、通信が止まっても溜まったままにならない。

    掃除で項目数ぶんを走査しない。期限を最小ヒープに積み、**切れたものだけ**を
    取り出す。引く操作そのものは項目数によらない——認証は毎リクエストの経路なので、
    生きているトークンが増えるほど重くなる作りにはしたくない。

    時刻は `time.monotonic()` で測る。壁時計は後ろにも前にも飛ぶ（NTP の補正、
    手動の変更）ので、TTL の判断に使うと期限切れが使えたり、生きている項目が
    早く消えたりする。ここで要るのは日付ではなく経過時間だけである。
    """

    def __init__(self) -> None:
        """値の表と、期限の索引を持つ。

        `_items` が実体で、`_deadlines` はそこを掃くための索引にすぎない。
        `_items` だけが答えを決める——索引の記録は古いことがあるので、
        捨てる前に必ず `_items` 側の期限を見直す（`_sweep`）。
        """
        self._items: dict[str, tuple[object, float]] = {}
        self._deadlines: list[tuple[float, str]] = []   # (期限, 鍵) の最小ヒープ

    @staticmethod
    def _key(token: str) -> str:
        """トークンを鍵に変える。**戻せないこと**がここでの狙いである。

        SHA-256 を選んだのは強度のためではなく、衝突が起きないことと、
        値から元のトークンを取り出せないことの2つを同時に満たすためである。
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def _sweep(self, now: float) -> None:
        """期限の早いものから、切れたぶんだけを捨てる。

        `put` で上書きされた鍵は古い記録がヒープに残る。取り出したときに今の
        期限を見直し、まだ生きていれば消さない（新しい記録が別に積んである）。
        """
        while self._deadlines and self._deadlines[0][0] <= now:
            _, key = heapq.heappop(self._deadlines)
            item = self._items.get(key)
            if item is not None and item[1] <= now:
                del self._items[key]

    def get(self, token: str, margin: float = 0.0):
        """期限切れを捨てたうえで引く。無ければ None。

        margin は「あと何秒は使えること」を求める余裕。交換後トークンのように
        受け取った側が使い切るまでの時間が要るものに使う。
        """
        now = time.monotonic()
        self._sweep(now)
        hit = self._items.get(self._key(token))
        return hit[0] if hit and hit[1] > now + margin else None

    def put(self, token: str, value, ttl: float) -> None:
        """`ttl` 秒だけ使える値として入れる。同じトークンなら上書きする。

        上書きしても古い期限の記録はヒープに残る。消すのは `_sweep` の仕事で、
        そこで `_items` の今の期限を見直すため、上書きで延びた項目は消えない。
        """
        key, deadline = self._key(token), time.monotonic() + ttl
        self._items[key] = (value, deadline)
        heapq.heappush(self._deadlines, (deadline, key))

    def drop(self, token: str) -> None:
        """期限を待たずに捨てる。無くてもよい（検証に失敗したときに使う）。"""
        # ヒープの記録はそのままでよい。期限が来たとき `_sweep` が空振りする。
        self._items.pop(self._key(token), None)


# ------------------------------------------------------ トークン検証
class KeycloakJWTVerifier(TokenVerifier):
    """Keycloak の JWT を JWKS で検証する。aud は本サーバの canonical URI 必須。"""

    def __init__(self, issuer: str, audience: str, jwks_url: str):
        self.issuer = issuer
        self.audience = audience
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True)

    def decode(self, token: str) -> dict:
        key = self._jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self.audience,   # ← 他サーバ宛トークンはここで落ちる
            issuer=self.issuer,
            leeway=10,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            c = self.decode(token)
        except Exception:
            return None
        return AccessToken(
            token=token,
            client_id=c.get("azp") or c.get("client_id") or "",
            scopes=(c.get("scope") or "").split(),
            expires_at=c.get("exp"),
            resource=self.audience,
        )


class InvenioPATVerifier(TokenVerifier):
    """InvenioRDM の個人アクセストークンを InvenioRDM 自身に問い合わせて検証する。

    PAT は不透明（JWT ではない）ので JWKS 検証ができない。`GET /api/me` が
    200 を返すかどうかが唯一の判定で、同時にそこで返る **roles** から
    MCP scope を導く（PAT には scope の概念が無いため）。

    毎リクエスト往復すると重いので、トークン→結果を TTL 付きで持つ。
    **失敗はキャッシュしない**（トークンを消したのに通り続ける、を避ける）。
    """

    def __init__(self, api: str, ttl: int):
        """`api` は InvenioRDM の API の根、`ttl` は成功を持つ秒数。

        キャッシュは**この検証器のもの**で、共有しない。トークンの意味は
        問い合わせ先ごとに違うので、別の InvenioRDM を指す検証器が同じ表を
        覗ける状態にはしない。
        """
        self.api = api
        self.ttl = ttl
        self._cache = TokenCache()

    async def _me(self, token: str) -> dict | None:
        """`GET /api/me` の応答を返す。通らなければ None。

        200 以外はすべて「このトークンでは駄目」として扱う。**結果は捨てる**
        ——失効させたトークンが直前の成功で通り続ける、を避けるためである
        （`drop`）。成功したときだけ `ttl` 秒持つ。
        """
        hit = self._cache.get(token)
        if hit is not None:
            return hit
        async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=15) as c:
            r = await c.get(f"{self.api}/me",
                            headers={"Accept": "application/json",
                                     "Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            self._cache.drop(token)
            return None
        me = r.json()
        self._cache.put(token, me, self.ttl)
        return me

    @staticmethod
    def scopes_for(me: dict) -> list[str]:
        roles = {(r or {}).get("name") for r in (me.get("roles") or [])}
        out = list(INVENIO_BASE_SCOPES)
        for role, scope in INVENIO_ROLE_SCOPES.items():
            if role in roles and scope not in out:
                out.append(scope)
        return out

    def decode(self, token: str) -> dict:
        """監査ログ・whoami 用。**キャッシュ済みのときだけ**中身を返す。

        JWT のクレームに寄せた形にして、呼び出し側の分岐を減らす。
        """
        me = self._cache.get(token)
        if me is None:
            raise RuntimeError(t("auth.unverified_token"))
        return {
            "sub": str(me.get("id")),
            "email": me.get("email"),
            "preferred_username": me.get("email"),
            "aud": [RESOURCE],
            "azp": "invenio-pat",
            "scope": " ".join(self.scopes_for(me)),
            "iss": INVENIO_API,
            "roles": sorted({(r or {}).get("name") for r in (me.get("roles") or [])}),
        }

    async def verify_token(self, token: str) -> AccessToken | None:
        me = await self._me(token)
        if me is None:
            return None
        return AccessToken(
            token=token,
            client_id="invenio-pat",
            scopes=self.scopes_for(me),
            expires_at=None,       # PAT に期限は無い（InvenioRDM 側で失効させる）
            resource=RESOURCE,
        )


if AUTH_MODE == "invenio":
    VERIFIER = InvenioPATVerifier(INVENIO_API, INVENIO_VERIFY_TTL)
    # PAT モードでは canonical URI ごとの aud 検証が無いので同じ検証器を使う
    AUTH_VERIFIER = VERIFIER
else:
    VERIFIER = KeycloakJWTVerifier(KC_ISSUER, RESOURCE, KC_JWKS)
    # /mcp-auth は別 canonical URI なので aud もそちらで検証する
    AUTH_VERIFIER = KeycloakJWTVerifier(KC_ISSUER, AUTH_RESOURCE, KC_JWKS)


# --------------------------------------- 仕様適合のための ASGI ミドルウェア
def _www_authenticate(error: str, scope_str: str, msg_key: str,
                      prm_url: str = RESOURCE_METADATA_URL,
                      msg_kw: dict | None = None) -> str:
    """RFC 6750 のチャレンジ。error_description は ASCII の英語（t_ascii）。"""
    return (
        f'Bearer error="{error}", '
        f'scope="{scope_str}", '
        f'resource_metadata="{prm_url}", '
        f'error_description="{t_ascii(msg_key, **(msg_kw or {}))}"'
    )



# ------------------------------------------------------------- 監査ログ
# 認可基盤なので「誰が・何を・どうなったか」を残す。1行1JSON で標準出力に出し、
# k8s のログ収集に載せる。**トークンそのものは絶対に出さない**（sub / azp / scope だけ）。
AUDIT_ON = os.environ.get("MCP_AUDIT", "on").lower() not in ("off", "0", "false")


def _audit(event: str, **fields) -> None:
    if not AUDIT_ON:
        return
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
    rec.update({k: v for k, v in fields.items() if v is not None})
    try:
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    except Exception:
        pass          # ログで本処理を落とさない


def _subject(claims: dict | None) -> dict:
    """監査に載せる主体の情報。トークンは含めない。"""
    if not claims:
        return {"sub": None}
    return {
        "sub": claims.get("sub"),
        "azp": claims.get("azp"),
        "scope": claims.get("scope"),
        "eppn": claims.get("eppn"),
        "tenant_id": claims.get("tenant_id"),
    }


def _peek_rpc(body: bytes):
    """監査用に JSON-RPC の method とツール名だけ取り出す（失敗しても落とさない）。"""
    try:
        p = json.loads(body or b"{}")
    except Exception:
        return None, None
    # JSON-RPC のバッチ（配列）も来うる。監査には最初の1件を載せる。
    if isinstance(p, list):
        p = next((x for x in p if isinstance(x, dict)), None)
    if not isinstance(p, dict):
        return None, None
    m = p.get("method")
    tool = (p.get("params") or {}).get("name") if m == "tools/call" else None
    return tool, m


async def _prewarm(scope: Scope, verifier) -> None:
    """PAT モード用: Authorization の中身を先に検証してキャッシュに載せる。

    keycloak モードでは JWT をその場で検証できるので何もしない。
    """
    if not isinstance(verifier, InvenioPATVerifier):
        return
    for k, v in scope.get("headers", []):
        if k.lower() == b"authorization":
            raw = v.decode()
            if raw.lower().startswith("bearer "):
                try:
                    await verifier._me(raw[7:].strip())
                except Exception:
                    pass          # 到達不能などは検証失敗と同じ扱い（後段が 401 を返す）
            return


class ScopeChallengeMiddleware:
    """ツール単位の scope 検査（403 insufficient_scope）と WWW-Authenticate の補完。

    SDK の RequireAuthMiddleware はエンドポイント全体に対する required_scopes しか見ず、
    WWW-Authenticate に `scope` も載せない（2026-07-28 の SHOULD）。
    ここで JSON-RPC の tools/call を覗いてツールごとの scope を判定し、
    不足していれば step-up 用の 403 チャレンジを返す。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path")
        if scope["type"] != "http" or path not in (MCP_PATH, MCP_AUTH_PATH):
            await self.app(scope, receive, send)
            return

        # /mcp-auth は「最初の1リクエストから認可必須」の入口。
        # 下流は /mcp のルートしか持たないので、判定後にパスを書き換えて渡す。
        require_auth = path == MCP_AUTH_PATH
        prm_url = AUTH_RESOURCE_METADATA_URL if require_auth else RESOURCE_METADATA_URL
        verifier = AUTH_VERIFIER if require_auth else VERIFIER
        adv_scopes = AUTH_SCOPES if require_auth else BASE_SCOPES
        if require_auth:
            scope = {**scope, "path": MCP_PATH, "raw_path": MCP_PATH.encode()}

        # PAT モードの検証は InvenioRDM への往復なので非同期。以降の同期 decode()
        # が使えるよう、ここで先に検証してキャッシュを温めておく。
        # （温まらなければ decode() が失敗し、下の _check が 401 を返す＝正しい挙動）
        await _prewarm(scope, verifier)

        body = b""
        if scope.get("method") == "POST":
            more = True
            oversized = False
            while more:
                msg = await receive()
                if msg["type"] == "http.request":
                    body += msg.get("body", b"")
                    # 認可を判定するために本文を**全部**貯める必要がある。上限が無いと
                    # 1本の POST でメモリを食い潰せるので、ここで頭を打つ。
                    # 上限は添付の上限（MCP_MAX_UPLOAD_BYTES）＋ JSON/base64 の膨らみ分。
                    if len(body) > MAX_REQUEST_BYTES:
                        oversized = True
                        break
                    more = msg.get("more_body", False)
                else:
                    more = False
            if oversized:
                _audit("deny", path=path, method=scope.get("method"),
                       status=413, error="payload_too_large", bytes=len(body))
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": json.dumps({"error": "payload_too_large",
                                                "limit": MAX_REQUEST_BYTES}).encode()})
                return

            tool, rpc_method = _peek_rpc(body)
            claims = self._claims(scope, verifier)
            challenge = self._check(scope, body, require_auth, verifier, adv_scopes)
            if challenge is not None:
                status, err, need = challenge[:3]
                # バッチだと _peek_rpc が拾うのは**先頭の要素**なので、拒否の理由に
                # なったツールとは限らない。チャレンジが持っている名前を優先する。
                denied = (challenge[4] or {}).get("tool") or tool
                _audit("deny", path=path, method=rpc_method, tool=denied,
                       status=status, error=err, required_scope=need,
                       **_subject(claims))
                await self._send_challenge(send, *challenge, prm_url=prm_url)
                return
        elif require_auth and self._claims(scope, verifier) is None:  # noqa: E501 (prewarm 済み)
            _audit("deny", path=path, method=scope.get("method"),
                   status=401, error="invalid_token", sub=None)
            # GET/DELETE（SSE やセッション終了）も認可必須にする
            await self._send_challenge(
                send, 401, "invalid_token", " ".join(adv_scopes),
                "auth.endpoint_requires_auth", prm_url=prm_url,
            )
            return

        replayed = {"done": False}

        async def replay() -> dict:
            if not replayed["done"]:
                replayed["done"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        started = time.time()
        seen_status = {"code": None, "tool_error": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                seen_status["code"] = message["status"]
            elif message["type"] == "http.response.body":
                # ツールの失敗は HTTP 200 ＋ isError で返る。本文を貯めずに印だけ拾う。
                if b'"isError":true' in message.get("body", b"") or \
                   b'"isError": true' in message.get("body", b""):
                    seen_status["tool_error"] = True
            # 下流が出す 401/403 に scope / resource_metadata を補う
            if message["type"] == "http.response.start" and message["status"] in (401, 403):
                headers = []
                seen = False
                for k, v in message["headers"]:
                    if k.lower() == b"www-authenticate":
                        seen = True
                        if b"scope=" not in v:
                            v = v + f', scope="{" ".join(adv_scopes)}"'.encode()
                        if b"resource_metadata=" not in v:
                            v = v + f', resource_metadata="{prm_url}"'.encode()
                    headers.append((k, v))
                if not seen:
                    headers.append((
                        b"www-authenticate",
                        _www_authenticate(
                            "invalid_token", " ".join(adv_scopes),
                            "auth.authentication_required", prm_url,
                        ).encode(),
                    ))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, replay if scope.get("method") == "POST" else receive, send_wrapper)
        if scope.get("method") == "POST":
            _audit("tool_error" if seen_status["tool_error"] else "call",
                   path=path, method=rpc_method, tool=tool,
                   status=seen_status["code"],
                   ms=int((time.time() - started) * 1000),
                   **_subject(claims))

    @staticmethod
    def _claims(scope: Scope, verifier: "KeycloakJWTVerifier" = None):
        """Authorization ヘッダを検証してクレームを返す。無効・不在なら None。"""
        raw = None
        for k, v in scope.get("headers", []):
            if k.lower() == b"authorization":
                raw = v.decode()
        if raw is None or not raw.lower().startswith("bearer "):
            return None
        try:
            return (verifier or VERIFIER).decode(raw[7:].strip())
        except Exception:
            return None

    def _check(self, scope: Scope, body: bytes, require_auth: bool = False,
               verifier: "KeycloakJWTVerifier" = None,
               adv_scopes: "list | None" = None):
        """不足があれば (status, error, scope, メッセージキー, 書式引数) を返す。

        説明文そのものではなく**キー**を返すのは、同じ内容を JSON 本文には翻訳して、
        WWW-Authenticate ヘッダには ASCII の英語で載せる必要があるため。

        方針:
          * Authorization ヘッダが**有る**のに検証に失敗 → 401（黙って匿名に落とさない）
          * require_auth（/mcp-auth 経由）→ 中身を見るまでもなく未認証は 401
          * ツールが scope 不要（None）→ 未認証でも通す
          * ツールが scope 必要で未認証 → 401 チャレンジ（発見フローの入口）
          * ツールが scope 必要で認証済みだが不足 → 403 insufficient_scope（step-up）
        """
        raw = None
        for k, v in scope.get("headers", []):
            if k.lower() == b"authorization":
                raw = v.decode()
        claims = None
        if raw is not None:
            if not raw.lower().startswith("bearer "):
                return (401, "invalid_token", " ".join(BASE_SCOPES),
                        "auth.scheme_not_bearer", {})
            try:
                claims = (verifier or VERIFIER).decode(raw[7:].strip())
            except Exception:
                # 不正・期限切れ・別 issuer・別 audience はここで落とす
                return (401, "invalid_token", " ".join(BASE_SCOPES),
                        "auth.invalid_token", {})

        adv_scopes = adv_scopes or BASE_SCOPES
        if require_auth and claims is None:
            # initialize / tools/list であっても通さない。
            # 「最初の接続が 401 でなければ認可の準備をしない」クライアント向けの入口。
            return (401, "invalid_token", " ".join(adv_scopes),
                    "auth.endpoint_requires_auth", {})

        try:
            payload = json.loads(body or b"{}")
        except Exception:
            return None
        # **バッチ（配列）を素通しさせない。** いまの SDK は配列を 400 で弾くので
        # 実害は無いが、それは下流のふるまいに守られているだけで、ここが見ている
        # わけではない。SDK がバッチを通す版になった瞬間に scope 検査が丸ごと
        # 迂回される。中の全要素を見て、**一番厳しい要求**を採る。
        calls = payload if isinstance(payload, list) else [payload]
        granted = set((claims.get("scope") or "").split()) if claims else set()
        for call in calls:
            if not isinstance(call, dict) or call.get("method") != "tools/call":
                continue         # initialize / tools/list などは誰でも呼べる
            tool = (call.get("params") or {}).get("name")
            needed = TOOL_SCOPES.get(tool)
            if needed is None:
                continue         # 公開情報の読取。未認証で通す
            if claims is None:
                return (401, "invalid_token", needed,
                        "auth.tool_requires_auth", {"tool": tool})
            if needed not in granted:
                return (403, "insufficient_scope", needed,
                        "auth.tool_requires_scope", {"tool": tool, "scope": needed})
        return None

    async def _send_challenge(self, send: Send, status, error, scope_str, msg_key,
                              msg_kw: dict | None = None,
                              prm_url: str = RESOURCE_METADATA_URL):
        # 本文（JSON・UTF-8）は翻訳を載せ、ヘッダは ASCII の英語にする
        payload = json.dumps(
            {"error": error,
             "error_description": t(msg_key, **(msg_kw or {})),
             "required_scope": scope_str},
            ensure_ascii=False,
        ).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate",
                 _www_authenticate(error, scope_str, msg_key, prm_url, msg_kw).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": payload})


# ------------------------------------------- InvenioRDM 呼び出し（要交換）
_exchange_cache = TokenCache()


def _client_secret() -> str:
    """keycloak モードのトークン交換で使うクライアントシークレット。

    **既定値は用意しない。** 設定し忘れに気づかないまま推測可能な値で
    動いてしまうより、その場で止める方がよい。PAT モードでは呼ばれない。
    """
    if not MCP_CLIENT_SECRET:
        raise RuntimeError(t("auth.client_secret_missing"))
    return MCP_CLIENT_SECRET


async def _invenio_token() -> str | None:
    """受け取ったトークンを InvenioRDM 宛トークンに**交換**して返す。

    受信トークンをそのまま Invenio に転送してはならない（MCP 仕様のトークン中継禁止）。
    Keycloak の標準トークン交換 (RFC 8693) で aud=invenio-api の別トークンを得る。

    **未認証のときは None を返す**（呼び出し側は Authorization 無しで叩き、
    InvenioRDM は公開レコードだけを返す）。
    """
    at = get_access_token()
    if at is None:
        return None
    if AUTH_MODE == "invenio":
        # 受信トークンが**そもそも InvenioRDM のトークン**なので交換しない。
        # 中継禁止は「別の資源宛トークンを転送するな」という規則で、宛先が
        # 同一のここでは当てはまらない（代わりに aud による分離は無い）。
        return at.token
    # 交換後トークンは InvenioRDM への往復に使うので、残り寿命に余裕が要る。
    hit = _exchange_cache.get(at.token, margin=30)
    if hit is not None:
        return hit

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            KC_TOKEN_ENDPOINT,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": MCP_CLIENT_ID,
                "client_secret": _client_secret(),
                "subject_token": at.token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": INVENIO_AUDIENCE,
                "scope": "invenio:api",
            },
        )
    if r.status_code != 200:
        raise RuntimeError(t("auth.token_exchange_failed",
                            status=r.status_code, body=r.text[:200]))
    tok = r.json()
    _exchange_cache.put(at.token, tok["access_token"], tok.get("expires_in", 60))
    return tok["access_token"]


async def _invenio(method: str, path: str, body=None):
    token = await _invenio_token()
    headers = {"Accept": "application/json"}
    if token:                      # 未認証なら付けない＝公開レコードだけが返る
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=30) as c:
        r = await c.request(method, f"{INVENIO_API}{path}", headers=headers, json=body)
    if r.status_code >= 400:
        raise RuntimeError(t("errors.invenio_http",
                             status=r.status_code, body=r.text[:300]))
    return r.json() if r.content else None


async def _invenio_raw(method: str, path: str, data: bytes, content_type: str):
    """本文が JSON でない要求（ファイル本体の PUT）用。

    `_invenio` は json= で送るので、バイト列はこちらを使う。
    トークンの扱い（交換・未認証なら付けない）は同じ。
    """
    token = await _invenio_token()
    headers = {"Accept": "application/json", "Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=120) as c:
        r = await c.request(method, f"{INVENIO_API}{path}", headers=headers, content=data)
    if r.status_code >= 400:
        raise RuntimeError(t("errors.invenio_http",
                             status=r.status_code, body=r.text[:300]))
    return r.json() if r.content else None


async def _invenio_text(path: str, accept: str):
    """JSON 以外の表現（DataCite XML / BibTeX など）を取るための GET。

    `_invenio` は Accept: application/json 固定なので、content negotiation で
    別のシリアライザを選ぶときはこちらを使う。
    """
    token = await _invenio_token()
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=30) as c:
        r = await c.get(f"{INVENIO_API}{path}", headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(t("errors.invenio_http",
                             status=r.status_code, body=r.text[:300]))
    return r.text, r.headers.get("content-type", "")


def _brief_community(c: dict) -> dict:
    m = (c or {}).get("metadata", {})
    return {
        "id": c.get("id"),
        "slug": c.get("slug"),
        "title": m.get("title"),
        "type": (m.get("type") or {}).get("id"),
        "visibility": (c.get("access") or {}).get("visibility"),
        "review_policy": (c.get("access") or {}).get("review_policy"),
    }


def _brief_request(r: dict) -> dict:
    if not r:
        return {}
    return {
        "id": r.get("id"),
        "type": r.get("type"),
        "title": r.get("title"),
        "status": r.get("status"),
        "is_open": r.get("is_open"),
        "created_by": (r.get("created_by") or {}).get("user"),
        "receiver": r.get("receiver"),
        "topic": r.get("topic"),
    }


def _seg(value) -> str:
    """URL のパス片を1つ分として符号化する。

    既定の `quote` は "/" を残すので、recid やファイル名に `../` が入ると
    **別のエンドポイントを叩ける**（利用者のトークンで、ではあるが、意図した
    操作ではない）。ここでは safe="" にして、1片に閉じ込める。
    """
    return quote(str(value), safe="")


def _qs(**kw) -> str:
    """None・空文字を落としてクエリ文字列にする。"""
    q = {k: v for k, v in kw.items() if v not in (None, "", [])}
    return ("?" + urlencode(q)) if q else ""


def _brief(rec: dict) -> dict:
    m = rec.get("metadata", {})
    return {
        "id": rec.get("id"),
        "title": m.get("title"),
        "resource_type": (m.get("resource_type") or {}).get("id"),
        "publication_date": m.get("publication_date"),
        "state": rec.get("status") or rec.get("state"),
        "is_published": rec.get("is_published"),
        "links": {k: v for k, v in (rec.get("links") or {}).items() if k in ("self", "self_html")},
    }


# ------------------------------------------------------------- MCP サーバ
mcp = FastMCP(
    "inveniordm-oauth",
    host=BIND_HOST,
    port=BIND_PORT,
    streamable_http_path=MCP_PATH,
    # 認可の検証を1リクエスト単位で見たいので stateless + JSON 応答にする
    # （セッション ID や SSE の都合を挟まずに 401/403 のチャレンジを観察できる）
    stateless_http=True,
    json_response=True,
    token_verifier=VERIFIER,
    auth=AuthSettings(
        # PAT モードに認可サーバは無い。issuer は形式上必要なので InvenioRDM を指す。
        issuer_url=(INVENIO_UI if AUTH_MODE == "invenio" else KC_ISSUER),  # type: ignore[arg-type]
        resource_server_url=RESOURCE,  # type: ignore[arg-type]
        required_scopes=BASE_SCOPES,
    ),
)
# FastMCP は version を受け取らないので、低レベルサーバに直接入れる。
# initialize の応答の serverInfo.version としてクライアントに見える。
mcp._mcp_server.version = __version__


def _peek(token: str) -> dict:
    """署名検証なしでクレームを覗く（表示用途のみ）。"""
    p = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


@mcp.tool(description=t("tools.whoami"))
async def whoami() -> dict:
    at = get_access_token()
    if at is None:
        raise RuntimeError(t("auth.whoami_requires_auth"))
    claims = VERIFIER.decode(at.token)
    # PAT モードでは交換が無く、トークンも JWT でないので覗けない
    exchanged = None if AUTH_MODE == "invenio" else _peek(await _invenio_token())
    me = await _invenio("GET", "/me")
    inv = await _invenio("GET", "/user/records?size=1")

    def federation(c):
        # eppn=機関 IdP 由来 / isMemberOf=mAP 由来 / idp_entity_id・tenant_id=Issuer 由来
        keys = ("eppn", "isMemberOf", "idp_entity_id", "tenant_id", "idp")
        return {k: c.get(k) for k in keys if c.get(k)}

    # メールは InvenioRDM 側の持ち物。学認から降ってこない場合は仮アドレスのまま
    # なので、利用者に設定を促せるようフラグを立てる。
    email = (me or {}).get("email") or ""
    pending = email.endswith("@" + PLACEHOLDER_EMAIL_DOMAIN)

    return {
        "mcp_token": {
            "sub": claims.get("sub"),
            "email": claims.get("email"),
            "preferred_username": claims.get("preferred_username"),
            "aud": claims.get("aud"),
            "azp": claims.get("azp"),
            "scope": claims.get("scope"),
            "iss": claims.get("iss"),
            "federation": federation(claims),
        },
        # keycloak モード: トークン中継ではなく RFC 8693 で交換した別トークン。
        # invenio(PAT) モード: 交換が無く、受け取った PAT をそのまま使う。
        "exchanged_token_for_invenio": {
            "aud": exchanged.get("aud"),
            "azp": exchanged.get("azp"),
            "sub": exchanged.get("sub"),
            "email": exchanged.get("email"),
            "federation": federation(exchanged),
        } if exchanged else {
            "note": t("auth.pat_mode_no_exchange"),
        },
        "invenio": {
            "user_id": (me or {}).get("id"),
            "email": email or None,
            # True なら本人がまだメールを設定していない（通知が届かない状態）
            "email_pending_setup": pending,
            "profile_settings_url": f"{INVENIO_UI}/account/settings/profile" if pending else None,
            "own_records": inv.get("hits", {}).get("total"),
        },
    }


@mcp.tool(description=t("tools.search_records"))
async def search_records(query: str = "", size: int = 10) -> list[dict]:
    res = await _invenio("GET", "/records" + _qs(q=query, size=size))
    return [_brief(h) for h in res.get("hits", {}).get("hits", [])]


@mcp.tool(description=t("tools.get_record"))
async def get_record(recid: str, draft: bool = False) -> dict:
    path = f"/records/{_seg(recid)}/draft" if draft else f"/records/{_seg(recid)}"
    return _brief(await _invenio("GET", path))


@mcp.tool(description=t("tools.create_record"))
async def create_record(metadata: dict, publish: bool = False,
                        files: bool = False) -> dict:
    draft = await _invenio("POST", "/records", {
        "access": {"record": "public", "files": "public"},
        "files": {"enabled": bool(files)},
        "metadata": metadata,
    })
    if publish:
        return _brief(await _invenio("POST", f"/records/{_seg(draft['id'])}/draft/actions/publish"))
    return _brief(draft)


@mcp.tool(description=t("tools.update_record"))
async def update_record(recid: str, metadata: dict, publish: bool = True) -> dict:
    try:
        await _invenio("GET", f"/records/{_seg(recid)}/draft")
    except RuntimeError:
        await _invenio("POST", f"/records/{_seg(recid)}/draft")
    cur = await _invenio("GET", f"/records/{_seg(recid)}/draft")
    cur["metadata"].update(metadata)
    upd = await _invenio("PUT", f"/records/{_seg(recid)}/draft", cur)
    if publish:
        return _brief(await _invenio("POST", f"/records/{_seg(recid)}/draft/actions/publish"))
    return _brief(upd)


@mcp.tool(description=t("tools.publish_record"))
async def publish_record(recid: str) -> dict:
    return _brief(await _invenio("POST", f"/records/{_seg(recid)}/draft/actions/publish"))


@mcp.tool(description=t("tools.delete_draft"))
async def delete_draft(recid: str) -> dict:
    await _invenio("DELETE", f"/records/{_seg(recid)}/draft")
    return {"deleted_draft": recid}


# ------------------------------------------------------------- キュレーション
# 公開済みレコードの取り下げ（ソフト削除）と復元。InvenioRDM では admin 権限が要る。
# 交換後トークンは**利用者本人**の身元なので、権限が無ければ InvenioRDM が 403 を返す。
# MCP 側の scope（mcp:curate）は「そもそも要求できるか」の分離で、最終判定は
# InvenioRDM に委ねる（二重に持たない）。
#
# ハード purge は REST に無いので提供できない。取り下げは tombstone が残り HTTP 410 を返す。

async def _removal_reasons() -> list[str]:
    """removalreasons 語彙の id を実インスタンスから引く。

    ここを定数で持つと、リポジトリが語彙を足したときに**正しい id を弾いてしまう**
    （実際 out-of-scope / copyright / retracted など既定で12件ある）。
    """
    d = await _invenio("GET", "/vocabularies/removalreasons?size=100")
    return [h.get("id") for h in (d.get("hits") or {}).get("hits", [])]


@mcp.tool(description=t("tools.delete_record"))
async def delete_record(recid: str, confirm: bool = False,
                        reason_id: str = "out-of-scope",
                        note: str = "removed via MCP") -> dict:
    if not confirm:
        return {
            "error": t("errors.destructive_needs_confirm"),
            "recid": recid,
            "effect": t("errors.destructive_effect"),
        }
    reasons = await _removal_reasons()
    if reason_id not in reasons:
        return {"error": t("errors.reason_id_invalid"),
                "given": reason_id, "valid": reasons}
    await _invenio("DELETE", f"/records/{_seg(recid)}/delete",
                   {"removal_reason": {"id": reason_id}, "note": note})
    return {"deleted_record": recid, "reason": reason_id, "note": note, "restorable": True}


# ------------------------------------------------------------------- 語彙
# InvenioRDM のメタデータは語彙 id を要求する（resource_type.id など）。
# ここが引けないと、エージェントは id を当てずっぽうで書いて 400 を踏む。
# 素の InvenioRDM が持つ語彙をそのまま見せる。


@mcp.tool(description=t("tools.list_vocabulary_types"))
async def list_vocabulary_types() -> dict:
    d = await _invenio("GET", "/vocabularies/")
    return {"types": [h.get("id") for h in (d.get("hits") or {}).get("hits", [])]}


@mcp.tool(description=t("tools.list_vocabulary"))
async def list_vocabulary(vocab_type: str, query: str = "", size: int = 20) -> dict:
    d = await _invenio("GET", f"/vocabularies/{_seg(vocab_type)}"
                              + _qs(q=query, size=size))
    hits = (d.get("hits") or {}).get("hits", [])
    return {
        "type": vocab_type,
        "total": (d.get("hits") or {}).get("total"),
        "items": [{"id": h.get("id"), "title": h.get("title")} for h in hits],
    }


# ------------------------------------------- エクスポート（content negotiation）
# InvenioRDM は Accept ヘッダでシリアライザを選ぶ。UI の /records/<id>/export/<fmt>
# に相当するものを、REST 側の content negotiation で出す。
EXPORT_FORMATS = {
    "json": "application/json",
    "inveniordm": "application/vnd.inveniordm.v1+json",
    "jsonld": "application/ld+json",                       # schema.org
    "datacite-json": "application/vnd.datacite.datacite+json",
    "datacite-xml": "application/vnd.datacite.datacite+xml",
    "dublincore": "application/x-dc+xml",
    "marcxml": "application/marcxml+xml",
    "dcat": "application/dcat+xml",
    "csl": "application/vnd.citationstyles.csl+json",
    "bibtex": "application/x-bibtex",
    "citation": "text/x-bibliography",
    "geojson": "application/vnd.geo+json",
}


@mcp.tool(description=t("tools.export_record"))
async def export_record(recid: str, fmt: str = "datacite-json") -> dict:
    mime = EXPORT_FORMATS.get(fmt)
    if mime is None:
        return {"error": t("errors.export_format_unknown",
                           formats=" / ".join(EXPORT_FORMATS)),
                "given": fmt}
    text, ctype = await _invenio_text(f"/records/{_seg(recid)}", mime)
    return {"recid": recid, "format": fmt, "content_type": ctype, "content": text}


# --------------------------------------------------------- バージョンと版履歴


@mcp.tool(description=t("tools.list_versions"))
async def list_versions(recid: str) -> dict:
    d = await _invenio("GET", f"/records/{_seg(recid)}/versions" + _qs(size=100))
    hits = (d.get("hits") or {}).get("hits", [])
    return {"total": (d.get("hits") or {}).get("total"),
            "versions": [_brief(h) for h in hits]}


@mcp.tool(description=t("tools.list_revisions"))
async def list_revisions(recid: str) -> dict:
    d = await _invenio("GET", f"/records/{_seg(recid)}/revisions")
    revs = d if isinstance(d, list) else []
    return {"recid": recid, "count": len(revs),
            "revisions": [{"created": r.get("created"),
                           "revision_id": (r.get("json") or {}).get("id"),
                           "title": ((r.get("json") or {}).get("metadata") or {}).get("title")}
                          for r in revs]}


@mcp.tool(description=t("tools.my_records"))
async def my_records(query: str = "", size: int = 10) -> dict:
    d = await _invenio("GET", "/user/records" + _qs(q=query, size=size, sort="updated-desc"))
    hits = (d.get("hits") or {}).get("hits", [])
    return {"total": (d.get("hits") or {}).get("total"),
            "records": [_brief(h) for h in hits]}


# ------------------------------------------------------------- コミュニティ
# JAIRO Cloud は機関ごとのマルチテナントで、コミュニティが組織単位そのもの。


@mcp.tool(description=t("tools.search_communities"))
async def search_communities(query: str = "", size: int = 10) -> dict:
    d = await _invenio("GET", "/communities" + _qs(q=query, size=size))
    hits = (d.get("hits") or {}).get("hits", [])
    return {"total": (d.get("hits") or {}).get("total"),
            "communities": [_brief_community(h) for h in hits]}


@mcp.tool(description=t("tools.get_community"))
async def get_community(community: str) -> dict:
    return _brief_community(await _invenio("GET", f"/communities/{_seg(community)}"))


@mcp.tool(description=t("tools.list_community_records"))
async def list_community_records(community: str, query: str = "", size: int = 10) -> dict:
    d = await _invenio("GET", f"/communities/{_seg(community)}/records"
                              + _qs(q=query, size=size))
    hits = (d.get("hits") or {}).get("hits", [])
    return {"total": (d.get("hits") or {}).get("total"),
            "records": [_brief(h) for h in hits]}


@mcp.tool(description=t("tools.create_community"))
async def create_community(slug: str, title: str, community_type: str = "topic",
                           visibility: str = "public",
                           review_policy: str = "closed") -> dict:
    c = await _invenio("POST", "/communities", {
        "slug": slug,
        "metadata": {"title": title, "type": {"id": community_type}},
        "access": {"visibility": visibility, "review_policy": review_policy},
    })
    return _brief_community(c)


# ------------------------------------------------------------- リクエスト
# 投稿 → 査読 → 受理 というリポジトリ運用の本体。
# 「出す」は write、「受理・却下する」はキュレーターの判断なので curate に分ける。


# リクエストの状態。**open / closed ではない**。InvenioRDM の status フィルタに
# 無い値を渡すと、エラーではなく黙って0件が返るので、ここで弾く。
REQUEST_STATUSES = ("submitted", "expired", "accepted", "declined", "cancelled")


@mcp.tool(description=t("tools.list_requests"))
async def list_requests(query: str = "", status: str = "", size: int = 10) -> dict:
    if status and status not in REQUEST_STATUSES:
        return {"error": t("errors.request_status_invalid",
                           statuses=" / ".join(REQUEST_STATUSES)),
                "given": status}
    d = await _invenio("GET", "/requests/" + _qs(q=query, status=status, size=size))
    hits = (d.get("hits") or {}).get("hits", [])
    return {"total": (d.get("hits") or {}).get("total"),
            "requests": [_brief_request(h) for h in hits]}


@mcp.tool(description=t("tools.get_request"))
async def get_request(request_id: str, timeline: bool = False) -> dict:
    out = _brief_request(await _invenio("GET", f"/requests/{_seg(request_id)}"))
    if timeline:
        d = await _invenio("GET", f"/requests/{_seg(request_id)}/timeline" + _qs(size=50))
        out["timeline"] = [
            {"type": h.get("type"), "created": h.get("created"),
             "by": (h.get("created_by") or {}).get("user"),
             "content": ((h.get("payload") or {}).get("content") or "")[:500]}
            for h in (d.get("hits") or {}).get("hits", [])
        ]
    return out


@mcp.tool(description=t("tools.submit_to_community"))
async def submit_to_community(recid: str, community: str, comment: str = "") -> dict:
    await _invenio("PUT", f"/records/{_seg(recid)}/draft/review",
                   {"receiver": {"community": community}, "type": "community-submission"})
    body = {"payload": {"content": comment, "format": "html"}} if comment else None
    r = await _invenio("POST", f"/records/{_seg(recid)}/draft/actions/submit-review", body)
    return {"submitted": recid, "community": community, "request": _brief_request(r)}


@mcp.tool(description=t("tools.comment_on_request"))
async def comment_on_request(request_id: str, comment: str) -> dict:
    c = await _invenio("POST", f"/requests/{_seg(request_id)}/comments",
                       {"payload": {"content": comment, "format": "html"}})
    return {"request_id": request_id, "comment_id": (c or {}).get("id")}


REQUEST_ACTIONS = ("accept", "decline", "cancel", "expire")


@mcp.tool(description=t("tools.request_action"))
async def request_action(request_id: str, action: str, comment: str = "") -> dict:
    if action not in REQUEST_ACTIONS:
        return {"error": t("errors.request_action_invalid",
                           actions=" / ".join(REQUEST_ACTIONS)),
                "given": action}
    body = {"payload": {"content": comment, "format": "html"}} if comment else None
    r = await _invenio("POST", f"/requests/{_seg(request_id)}/actions/{action}", body)
    return {"request_id": request_id, "action": action, "request": _brief_request(r)}


@mcp.tool(description=t("tools.restore_record"))
async def restore_record(recid: str) -> dict:
    return {"restored_record": recid,
            "record": _brief(await _invenio("POST", f"/records/{_seg(recid)}/restore"))}



# ------------------------------------------------------------- ファイル
# InvenioRDM のファイル登録は3手順（初期化 → 本体 → コミット）。
# MCP の引数は JSON なので、本体は **base64 か平文テキスト**で受け取る。
# 大きさの上限（MAX_UPLOAD_BYTES）は設定の節にある。


@mcp.tool(description=t("tools.upload_file"))
async def upload_file(recid: str, filename: str,
                      content_base64: str | None = None,
                      content_text: str | None = None,
                      overwrite: bool = True) -> dict:
    if (content_base64 is None) == (content_text is None):
        raise ValueError(t("errors.content_exclusive"))
    if content_base64 is not None:
        try:
            blob = base64.b64decode(content_base64, validate=True)
        except Exception as e:
            raise ValueError(t("errors.base64_undecodable", error=e)) from e
    else:
        blob = content_text.encode("utf-8")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError(t("errors.upload_too_large",
                           size=len(blob), limit=MAX_UPLOAD_BYTES))

    # 下書きの files が無効だと 400 になるので、必要なら有効にしてから進める
    draft = await _invenio("GET", f"/records/{_seg(recid)}/draft")
    if not (draft.get("files") or {}).get("enabled"):
        draft["files"] = {"enabled": True}
        await _invenio("PUT", f"/records/{_seg(recid)}/draft", draft)

    # 同名があると InvenioRDM は 400（`File with key ... already exists.`）を返す。
    # 「同じ名前で入れ直す」は普通の操作なので、既定では消してから入れ直す。
    existing = await _invenio("GET", f"/records/{_seg(recid)}/draft/files")
    if filename in {e.get("key") for e in (existing.get("entries") or [])}:
        if not overwrite:
            raise ValueError(t("errors.file_exists", filename=filename))
        await _invenio("DELETE", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}")
        replaced = True
    else:
        replaced = False

    await _invenio("POST", f"/records/{_seg(recid)}/draft/files", [{"key": filename}])
    await _invenio_raw("PUT", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}/content",
                       blob, "application/octet-stream")
    committed = await _invenio("POST", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}/commit")
    return {
        "recid": recid,
        "key": committed.get("key", filename),
        "size": committed.get("size", len(blob)),
        "checksum": committed.get("checksum"),
        "status": committed.get("status"),
        "replaced": replaced,
    }


@mcp.tool(description=t("tools.list_files"))
async def list_files(recid: str, draft: bool = False) -> dict:
    path = f"/records/{_seg(recid)}/draft/files" if draft else f"/records/{_seg(recid)}/files"
    res = await _invenio("GET", path)
    return {
        "recid": recid,
        "draft": draft,
        "enabled": res.get("enabled"),
        "files": [
            {"key": e.get("key"), "size": e.get("size"),
             "checksum": e.get("checksum"), "status": e.get("status")}
            for e in (res.get("entries") or [])
        ],
    }


@mcp.tool(description=t("tools.delete_file"))
async def delete_file(recid: str, filename: str) -> dict:
    await _invenio("DELETE", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}")
    return {"recid": recid, "deleted": filename}


@mcp.tool(description=t("tools.download_file"))
async def download_file(recid: str, filename: str, draft: bool = False) -> dict:
    seg = "draft/files" if draft else "files"
    path = f"/records/{_seg(recid)}/{seg}/{_seg(filename)}/content"

    # 署名済み URL を追うかどうかの判定に使う「登録されている大きさ」。
    # 取れなければ**追わない**（安全側に倒す）。
    try:
        entry = await _invenio("GET", f"/records/{_seg(recid)}/{seg}/{_seg(filename)}")
        declared_size = (entry or {}).get("size")
    except Exception:
        declared_size = None

    token = await _invenio_token()
    headers = {"Accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=120, follow_redirects=False) as c:
        r = await c.get(f"{INVENIO_API}{path}", headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(t("errors.invenio_http",
                                 status=r.status_code, body=r.text[:200]))
        # S3 保存時、InvenioRDM は本体ではなく **presigned URL** を返す。
        # 実測ではリダイレクト（3xx）ではなく **200 で URL を本文**にして返してきた。
        # どちらの形でも拾えるようにする。
        target = None
        if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
            target = r.headers["location"]
        elif declared_size is not None and len(r.content) != declared_size:
            # **本体ではない**ことが長さで分かるときだけ、署名済み URL として読む。
            # 長さが一致するなら、たとえ中身が署名済み URL の形をしていても、それは
            # 利用者が置いたファイルそのものなので追わない（SSRF を塞ぐ）。
            head = r.content[:2048].lstrip()
            if head[:4] in (b"http",) and b"X-Amz-Signature" in head:
                target = r.content.decode("utf-8", "replace").strip()
        if target:
            # presigned URL は署名だけで認可されている。
            # **Authorization を付けずに**取りに行く（InvenioRDM 宛トークンを S3 に渡さない）
            r = await c.get(target)
            if r.status_code >= 400:
                raise RuntimeError(t("errors.object_store_http", status=r.status_code))

    blob = r.content
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError(t("errors.download_too_large",
                           size=len(blob), limit=MAX_UPLOAD_BYTES))
    out = {
        "recid": recid,
        "key": filename,
        "size": len(blob),
        "content_type": r.headers.get("content-type"),
        "content_base64": base64.b64encode(blob).decode(),
    }
    try:
        out["text"] = blob.decode("utf-8")
    except UnicodeDecodeError:
        pass          # バイナリ。base64 だけ返す
    return out


@mcp.tool(description=t("tools.new_version"))
async def new_version(recid: str, import_files: bool = True,
                      publication_date: str | None = None,
                      version: str | None = None) -> dict:
    draft = await _invenio("POST", f"/records/{_seg(recid)}/versions")
    new_id = draft["id"]
    imported = None
    if import_files:
        try:
            res = await _invenio(
                "POST", f"/records/{_seg(new_id)}/draft/actions/files-import")
            imported = len((res or {}).get("entries") or [])
        except Exception as e:
            # 元にファイルが無い等。新バージョン自体は作れているので失敗にはしない
            imported = t("errors.import_files_failed", error=e)
    # 公開日を埋める（引き継がれないので、ここで入れておかないと publish できない）
    draft = await _invenio("GET", f"/records/{_seg(new_id)}/draft")
    md = draft.setdefault("metadata", {})
    changed = False
    if not md.get("publication_date"):
        md["publication_date"] = publication_date or time.strftime("%Y-%m-%d")
        changed = True
    elif publication_date:
        md["publication_date"] = publication_date
        changed = True
    if version:
        md["version"] = version
        changed = True
    if changed:
        draft = await _invenio("PUT", f"/records/{_seg(new_id)}/draft", draft)

    out = _brief(draft)
    out["source_recid"] = recid
    out["imported_files"] = imported
    out["publication_date"] = (draft.get("metadata") or {}).get("publication_date")
    return out


@mcp.tool(description=t("tools.upload_file_from_url"))
async def upload_file_from_url(recid: str, filename: str, url: str,
                               overwrite: bool = True) -> dict:
    draft = await _invenio("GET", f"/records/{_seg(recid)}/draft")
    if not (draft.get("files") or {}).get("enabled"):
        draft["files"] = {"enabled": True}
        await _invenio("PUT", f"/records/{_seg(recid)}/draft", draft)

    existing = await _invenio("GET", f"/records/{_seg(recid)}/draft/files")
    if filename in {e.get("key") for e in (existing.get("entries") or [])}:
        if not overwrite:
            raise ValueError(t("errors.file_exists", filename=filename))
        await _invenio("DELETE", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}")
        replaced = True
    else:
        replaced = False

    # transfer 種別の指定方法は InvenioRDM v13 で変わった。
    #   v12: {"storage_class": "F", "uri": ...}
    #   v14: {"transfer": {"type": "F", "url": ...}}
    # v14 のスキーマは未知フィールドを RAISE するので、旧形式は 400 になる。
    try:
        res = await _invenio("POST", f"/records/{_seg(recid)}/draft/files",
                             [{"key": filename, "transfer": {"type": "F", "url": url}}])
    except RuntimeError as e:
        if "HTTP 403" in str(e):
            raise ValueError(t("errors.fetch_forbidden")) from e
        raise
    entry = next((e for e in (res or {}).get("entries", []) if e.get("key") == filename), {})
    return {
        "recid": recid,
        "key": filename,
        "source_url": url,
        "status": entry.get("status"),
        "transfer": (entry.get("transfer") or {}).get("type"),
        "replaced": replaced,
        "note": t("notes.fetch_async"),
    }


# --- 大容量ファイル（multipart） -------------------------------------------
# S3 のマルチパートアップロードの決まり:
#   * 最後以外のパートは **5MiB 以上**（MinIO / S3 共通の下限）
#   * パート数は **10000 まで**
#   * 最後以外のパートは**すべて同じ大きさ**でなければならない
S3_MIN_PART_BYTES = 5 * 1024 * 1024
S3_MAX_PARTS = 10000
DEFAULT_PART_BYTES = int(os.environ.get("MCP_MULTIPART_PART_BYTES",
                                        str(64 * 1024 * 1024)))


def _plan_parts(size: int, part_size: int | None) -> tuple[int, int]:
    """総サイズから (パート数, パートの大きさ) を決める。

    指定が無ければ既定値から始め、パート数が 10000 を超えないところまで倍にする。
    """
    if size <= 0:
        raise ValueError(t("errors.size_must_be_positive"))
    part_size = part_size or DEFAULT_PART_BYTES
    if part_size < S3_MIN_PART_BYTES and size > part_size:
        raise ValueError(t("errors.part_size_too_small",
                           part_size=part_size, minimum=S3_MIN_PART_BYTES))
    while -(-size // part_size) > S3_MAX_PARTS:      # 切り上げ除算
        part_size *= 2
    return -(-size // part_size), part_size


@mcp.tool(description=t("tools.start_multipart_upload"))
async def start_multipart_upload(recid: str, filename: str, size: int,
                                 part_size: int | None = None,
                                 overwrite: bool = True) -> dict:
    parts, part_size = _plan_parts(size, part_size)

    draft = await _invenio("GET", f"/records/{_seg(recid)}/draft")
    if not (draft.get("files") or {}).get("enabled"):
        draft["files"] = {"enabled": True}
        await _invenio("PUT", f"/records/{_seg(recid)}/draft", draft)

    existing = await _invenio("GET", f"/records/{_seg(recid)}/draft/files")
    if filename in {e.get("key") for e in (existing.get("entries") or [])}:
        if not overwrite:
            raise ValueError(t("errors.file_exists", filename=filename))
        await _invenio("DELETE", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}")
        replaced = True
    else:
        replaced = False

    res = await _invenio("POST", f"/records/{_seg(recid)}/draft/files", [{
        "key": filename, "size": size,
        "transfer": {"type": "M", "parts": parts, "part_size": part_size},
    }])
    entry = next((e for e in (res or {}).get("entries", []) if e.get("key") == filename), {})
    links = entry.get("links") or {}
    part_links = links.get("parts") or []
    if not part_links:
        raise ValueError(t("errors.no_part_links"))

    return {
        "recid": recid,
        "key": filename,
        "size": size,
        "parts": len(part_links),
        "part_size": part_size,
        "replaced": replaced,
        "parts_urls": [
            {"part": p.get("part"), "url": p.get("url"),
             "expiration": p.get("expiration")}
            for p in part_links
        ],
        "hint": t("notes.multipart_hint", part_size=part_size),
        "note": t("notes.multipart_direct"),
    }


@mcp.tool(description=t("tools.complete_multipart_upload"))
async def complete_multipart_upload(recid: str, filename: str) -> dict:
    committed = await _invenio(
        "POST", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}/commit")
    return {
        "recid": recid,
        "key": committed.get("key", filename),
        "size": committed.get("size"),
        "checksum": committed.get("checksum"),
        "status": committed.get("status"),
        "transfer": (committed.get("transfer") or {}).get("type"),
    }


@mcp.tool(description=t("tools.abort_multipart_upload"))
async def abort_multipart_upload(recid: str, filename: str) -> dict:
    await _invenio("DELETE", f"/records/{_seg(recid)}/draft/files/{_seg(filename)}")
    return {"recid": recid, "aborted": filename}

# ツールの定義がすべて済んだところで突き合わせる。**import した時点で落ちる。**
_verify_tool_scopes()


def build_app():
    """匿名アクセスを通すため、MCP ルートの RequireAuthMiddleware を外す。

    FastMCP は token_verifier を渡すとルートを RequireAuthMiddleware で包み、
    **トークンが無ければ無条件に 401** にする。公開情報を未認証で返したいので、
    その包みだけ剥がして中身（StreamableHTTP の ASGI アプリ）に差し替える。

    認証そのものは残る:
      * AuthenticationMiddleware は有効なままなので、トークンがあれば
        scope["user"] が立ち、ツール内から get_access_token() で取れる
      * 認可の判定は ScopeChallengeMiddleware が行う（未認証可 / 401 / 403）
      * RFC 9728 の保護リソースメタデータのルートもそのまま残る
    """
    from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
    from starlette.routing import Route

    app = mcp.streamable_http_app()
    for r in app.routes:
        if isinstance(r, Route) and r.path == MCP_PATH:
            inner = getattr(r.app, "app", None)
            if isinstance(r.app, RequireAuthMiddleware) and inner is not None:
                r.app = inner

    # /mcp-auth は独立した保護リソースなので、専用の保護リソースメタデータを出す。
    # `resource` は接続先 URI と一致していなければならない（クライアントが検証する）。
    from starlette.responses import JSONResponse

    async def _auth_prm(_request):
        prm = {
            "resource": AUTH_RESOURCE,
            "scopes_supported": AUTH_SCOPES,
            "bearer_methods_supported": ["header"],
        }
        if AUTH_MODE == "invenio":
            # 認可サーバが無いので authorization_servers は出さない。
            # 代わりにトークンの入手方法を人間向けに示す（RFC 9728 の任意項目）。
            prm["resource_documentation"] = (
                f"{INVENIO_UI}/account/settings/applications/tokens/new/")
        else:
            prm["authorization_servers"] = [KC_ISSUER]
        return JSONResponse(prm)

    app.routes.append(Route(AUTH_RESOURCE_METADATA_PATH, _auth_prm, methods=["GET"]))

    if AUTH_MODE == "invenio":
        # SDK は AuthSettings.issuer_url をそのまま authorization_servers に載せるが、
        # PAT モードに認可サーバは無い（InvenioRDM は RFC 8414 メタデータを持たない）。
        # そのまま広告すると、クライアントが在りもしない AS を探しに行って詰まる。
        async def _prm(_request):
            return JSONResponse({
                "resource": RESOURCE,
                "scopes_supported": BASE_SCOPES,
                "bearer_methods_supported": ["header"],
                "resource_documentation":
                    f"{INVENIO_UI}/account/settings/applications/tokens/new/",
            })

        for i, r in enumerate(app.routes):
            if isinstance(r, Route) and r.path == RESOURCE_METADATA_PATH:
                app.routes[i] = Route(RESOURCE_METADATA_PATH, _prm, methods=["GET"])
                break
        else:
            app.routes.append(Route(RESOURCE_METADATA_PATH, _prm, methods=["GET"]))

    return ScopeChallengeMiddleware(app)


if __name__ == "__main__":
    import uvicorn

    print(t("startup.server", host=BIND_HOST, port=BIND_PORT, path=MCP_PATH))
    print(t("startup.version", version=__version__))
    print(t("startup.canonical_uri", resource=RESOURCE))
    print(t("startup.resource_metadata", url=RESOURCE_METADATA_URL))
    print(t("startup.auth_mode", mode=AUTH_MODE))
    print(t("startup.language", lang=LANG, available=" ".join(AVAILABLE_LANGS)))
    if AUTH_MODE == "invenio":
        print(t("startup.pat_direct", api=INVENIO_API))
        print(t("startup.pat_issue",
                url=f"{INVENIO_UI}/account/settings/applications/tokens/new/"))
        print(t("startup.pat_scopes", base=" ".join(INVENIO_BASE_SCOPES),
                roles=INVENIO_ROLE_SCOPES))
    else:
        print(t("startup.authorization_server", issuer=KC_ISSUER))
    print(t("startup.tls",
            state=t("startup.tls_on" if VERIFY_TLS else "startup.tls_off")))
    print(t("startup.audit",
            state=t("startup.audit_on" if AUDIT_ON else "startup.audit_off")))
    print(t("startup.auth_path", path=MCP_AUTH_PATH))
    uvicorn.run(build_app(), host=BIND_HOST, port=BIND_PORT, log_level="warning")
