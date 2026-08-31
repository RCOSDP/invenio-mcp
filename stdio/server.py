#!/usr/bin/env python3
"""InvenioRDM MCP server — メタデータ／ファイルの登録・更新・削除。

stdio 型 MCP サーバ（公式 mcp SDK / FastMCP）。InvenioRDM REST API を Bearer トークンで叩く。
依存は stdlib のみ（urllib/ssl/json）＋ mcp。追加インストール不要。

対象は **InvenioRDM v14**。

環境変数:
  INVENIO_API         既定 https://localhost/api
  INVENIO_TOKEN       無ければ同ディレクトリの .token を読む
  INVENIO_VERIFY_TLS  既定 true。自己署名なら INVENIO_CA_BUNDLE が要る
  INVENIO_CA_BUNDLE   ルート CA。既定は同ディレクトリの ca.crt（在れば読む）
  MCP_LANG            ツールの説明・エラーの言語。同梱は en / ja。
                      未設定ならシステムのロケール、決まらなければ en
  MCP_LOCALES_DIR     言語リソースの置き場。既定は同ディレクトリの locales/

CLI: `python3 server.py --selftest` で REST 一連を実走して片付ける。
     `python3 server.py --version` で版を表示する。
"""
import base64
import json as _json
import os
import ssl
import sys
import urllib.request
import urllib.error
import urllib.parse

from mcp.server.fastmcp import FastMCP

# セマンティックバージョニング（https://semver.org/lang/ja/）。
# 何を破壊的変更とみなすかは docs/about/versioning.md に書いてある。
# http/mcp_server.py の __version__ と揃える（tools/check.sh が一致を検査する）。
__version__ = "0.0.2"

# ---- 設定 ----
_HERE = os.path.dirname(os.path.abspath(__file__))

# ---- i18n ----
# 利用者（と LLM）に見える文字列は locales/<lang>.json に置く。ツールの説明と
# エラーがその対象で、コード中の注釈は開発者向けなので含めない。
#
# MCP のプロトコルに言語交渉は無いので、言語は**プロセス単位**で決まる。
# MCP_LANG が最優先、無ければシステムのロケール（LC_ALL / LC_MESSAGES / LANG）、
# それでも決まらなければ英語。locales/ に <tag>.json を置けば言語を足せる。
LOCALES_DIR = os.environ.get("MCP_LOCALES_DIR") or os.path.join(_HERE, "locales")
FALLBACK_LANG = "en"


def _available_langs():
    try:
        return sorted(f[:-5] for f in os.listdir(LOCALES_DIR) if f.endswith(".json"))
    except OSError:
        return []


def _pick_lang(available):
    explicit = os.environ.get("MCP_LANG", "").strip()
    # 明示指定が未知の言語なら、システムのロケールは見ずに既定へ落とす（意図を優先）
    candidates = [explicit] if explicit else [
        os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG")]
    for raw in candidates:
        if not raw:
            continue
        tag = raw.split(".")[0].split("@")[0].strip().replace("_", "-").lower()
        if tag in available:          # ja-jp のような地域付きの資源も選べる
            return tag
        if tag.split("-")[0] in available:
            return tag.split("-")[0]
    return FALLBACK_LANG


def _load_lang(lang):
    with open(os.path.join(LOCALES_DIR, f"{lang}.json"), encoding="utf-8") as f:
        return _json.load(f)


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


def t(key, **kw):
    """locales/<lang>.json の文字列を引く。無ければ英語 → キー名の順に落ちる。

    値が配列なら改行で連結する。書式引数を渡したときだけ format する
    （説明文に出てくる波括弧を壊さないため）。
    """
    for strings in (_STRINGS, _FALLBACK_STRINGS):
        cur = strings
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur is not None:
            if isinstance(cur, list):
                cur = "\n".join(cur)
            return cur.format(**kw) if kw else cur
    return key


API = os.environ.get("INVENIO_API", "https://localhost/api").rstrip("/")
VERIFY = os.environ.get("INVENIO_VERIFY_TLS", "true").lower() in ("1", "true", "yes")
# 自己署名のルート CA。MCP サーバはクライアントの子プロセスなので、ログインシェルの
# SSL_CERT_FILE が届かないことがある。既定の置き場を直接見にいく。
_DEFAULT_CA = os.path.join(_HERE, "ca.crt")
CA_BUNDLE = os.environ.get("INVENIO_CA_BUNDLE") or (
    os.path.abspath(_DEFAULT_CA) if os.path.exists(_DEFAULT_CA) else None
)

def _token():
    t = os.environ.get("INVENIO_TOKEN")
    if t:
        return t.strip()
    p = os.path.join(_HERE, ".token")
    if os.path.exists(p):
        return open(p).read().strip()
    raise RuntimeError(t("errors.token_missing"))

_CTX = ssl.create_default_context()
if VERIFY:
    if CA_BUNDLE:
        _CTX.load_verify_locations(CA_BUNDLE)
else:
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


def _seg(value):
    """URL のパス片を1つ分として符号化する。

    既定の `quote` は "/" を残すので、recid やファイル名に `../` が入ると
    **別のエンドポイントを叩ける**。safe="" にして1片に閉じ込める。
    """
    return urllib.parse.quote(str(value), safe="")


class ApiError(Exception):
    pass


def _req(method, path, body=None, raw=None, ctype="application/json"):
    """InvenioRDM REST 呼び出し。body=dict(JSON) か raw=bytes。返り値は (status, parsed_json_or_bytes)。"""
    url = path if path.startswith("http") else f"{API}{path}"
    headers = {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype
    elif body is not None:
        data = _json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=30) as r:
            b = r.read()
            if r.status == 204 or not b:
                return r.status, None
            try:
                return r.status, _json.loads(b)
            except Exception:
                return r.status, b
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = _json.loads(detail)
        except Exception:
            pass
        raise ApiError(t("errors.api_http", status=e.code, method=method,
                         path=path, detail=detail))


def _brief(rec):
    """レコード JSON を要点に圧縮（token節約）。"""
    if not isinstance(rec, dict):
        return rec
    md = rec.get("metadata", {}) or {}
    return {
        "id": rec.get("id"),
        "is_published": rec.get("is_published"),
        "is_draft": rec.get("is_draft"),
        "title": md.get("title"),
        "resource_type": (md.get("resource_type") or {}).get("id"),
        "publication_date": md.get("publication_date"),
        "access": (rec.get("access") or {}).get("record"),
        "files_enabled": (rec.get("files") or {}).get("enabled"),
        "files": list(((rec.get("files") or {}).get("entries") or {}).keys()),
        "links": {k: rec.get("links", {}).get(k) for k in ("self", "self_html", "draft", "publish") if rec.get("links", {}).get(k)},
    }


mcp = FastMCP("inveniordm")
# FastMCP は version を受け取らないので、低レベルサーバに直接入れる。
# initialize の応答の serverInfo.version としてクライアントに見える。
mcp._mcp_server.version = __version__

# ---------------- 読取 ----------------
@mcp.tool(description=t("tools.search_records"))
def search_records(query: str = "", size: int = 10) -> dict:
    q = f"?q={urllib.parse.quote(query)}&size={int(size)}" if query else f"?size={int(size)}"
    _, j = _req("GET", f"/records{q}")
    hits = (j or {}).get("hits", {}).get("hits", [])
    return {"total": (j or {}).get("hits", {}).get("total"), "records": [_brief(h) for h in hits]}


@mcp.tool(description=t("tools.get_record"))
def get_record(recid: str, draft: bool = False) -> dict:
    path = f"/records/{_seg(recid)}/draft" if draft else f"/records/{_seg(recid)}"
    _, j = _req("GET", path)
    return _brief(j)


# ---------------- メタデータ 登録/更新 ----------------
def _default_access():
    return {"record": "public", "files": "public"}


@mcp.tool(description=t("tools.create_record"))
def create_record(metadata: dict, access: dict = None, files_enabled: bool = False, publish: bool = False) -> dict:
    body = {"access": access or _default_access(), "files": {"enabled": bool(files_enabled)}, "metadata": metadata}
    _, j = _req("POST", "/records", body=body)
    recid = j.get("id")
    out = {"recid": recid, "state": "draft", "record": _brief(j)}
    if publish:
        out["record"] = _brief(_req("POST", f"/records/{_seg(recid)}/draft/actions/publish")[1])
        out["state"] = "published"
    return out


@mcp.tool(description=t("tools.update_record"))
def update_record(recid: str, metadata: dict, publish: bool = True) -> dict:
    # 既存の下書きがあればそれを、無ければ公開レコードから編集下書きを作る
    try:
        _, draft = _req("GET", f"/records/{_seg(recid)}/draft")
    except ApiError:
        _req("POST", f"/records/{_seg(recid)}/draft")            # 公開レコードから編集下書きを作成
        _, draft = _req("GET", f"/records/{_seg(recid)}/draft")
    draft["metadata"] = metadata
    _, upd = _req("PUT", f"/records/{_seg(recid)}/draft", body=draft)
    out = {"recid": recid, "state": "draft", "record": _brief(upd)}
    if publish:
        out["record"] = _brief(_req("POST", f"/records/{_seg(recid)}/draft/actions/publish")[1])
        out["state"] = "published"
    return out


@mcp.tool(description=t("tools.publish_record"))
def publish_record(recid: str) -> dict:
    _, j = _req("POST", f"/records/{_seg(recid)}/draft/actions/publish")
    return {"recid": recid, "state": "published", "record": _brief(j)}


@mcp.tool(description=t("tools.new_version"))
def new_version(recid: str, metadata: dict = None, publish: bool = False) -> dict:
    _, nv = _req("POST", f"/records/{_seg(recid)}/versions")
    new_id = nv.get("id")
    if metadata is not None:
        nv["metadata"] = metadata
        # 新版は publication_date が必須になる場合があるため呼び出し側で含めること
        _, nv = _req("PUT", f"/records/{_seg(new_id)}/draft", body=nv)
    out = {"recid": new_id, "state": "draft", "record": _brief(nv)}
    if publish:
        out["record"] = _brief(_req("POST", f"/records/{_seg(new_id)}/draft/actions/publish")[1])
        out["state"] = "published"
    return out


# ---------------- 削除 ----------------
@mcp.tool(description=t("tools.delete_draft"))
def delete_draft(recid: str) -> dict:
    _req("DELETE", f"/records/{_seg(recid)}/draft")
    return {"recid": recid, "deleted": "draft"}


@mcp.tool(description=t("tools.delete_record"))
def delete_record(recid: str, confirm: bool = False, reason_id: str = "out-of-scope", note: str = "removed via MCP") -> dict:
    if not confirm:
        return {"error": t("errors.destructive_needs_confirm"), "recid": recid}
    _req("DELETE", f"/records/{_seg(recid)}/delete", body={"removal_reason": {"id": reason_id}, "note": note})
    return {"recid": recid, "deleted": "record(soft)", "restorable": True}


@mcp.tool(description=t("tools.restore_record"))
def restore_record(recid: str) -> dict:
    _, j = _req("POST", f"/records/{_seg(recid)}/restore")
    return {"recid": recid, "restored": True, "record": _brief(j)}


# ---------------- ファイル ----------------
def _resolve_bytes(text, content_base64, source_path):
    if source_path:
        return open(source_path, "rb").read()
    if content_base64:
        return base64.b64decode(content_base64)
    if text is not None:
        return text.encode("utf-8")
    raise ValueError(t("errors.content_required"))


@mcp.tool(description=t("tools.add_file"))
def add_file(recid: str, key: str, text: str = None, content_base64: str = None, source_path: str = None) -> dict:
    data = _resolve_bytes(text, content_base64, source_path)
    _req("POST", f"/records/{_seg(recid)}/draft/files", body=[{"key": key}])
    _req("PUT", f"/records/{_seg(recid)}/draft/files/{_seg(key)}/content", raw=data, ctype="application/octet-stream")
    _, j = _req("POST", f"/records/{_seg(recid)}/draft/files/{_seg(key)}/commit")
    return {"recid": recid, "key": key, "size": (j or {}).get("size", len(data)), "status": (j or {}).get("status")}


@mcp.tool(description=t("tools.list_files"))
def list_files(recid: str, draft: bool = True) -> dict:
    seg = "draft/files" if draft else "files"
    _, j = _req("GET", f"/records/{_seg(recid)}/{seg}")
    ents = (j or {}).get("entries", [])
    return {"recid": recid, "files": [{"key": e.get("key"), "size": e.get("size"), "status": e.get("status")} for e in ents]}


@mcp.tool(description=t("tools.delete_file"))
def delete_file(recid: str, key: str) -> dict:
    _req("DELETE", f"/records/{_seg(recid)}/draft/files/{_seg(key)}")
    return {"recid": recid, "key": key, "deleted": True}


# ---------------- selftest ----------------
def _selftest():
    print("== InvenioRDM MCP selftest ==")
    md = {
        "resource_type": {"id": "dataset"},
        "title": "MCP selftest record",
        "publication_date": "2026-07-09",
        "creators": [{"person_or_org": {"type": "personal", "family_name": "Test", "given_name": "MCP"}}],
    }
    r = create_record(md, files_enabled=True, publish=False)
    rid = r["recid"]; print(" create draft:", rid)
    print(" get:", get_record(rid, draft=True)["title"])
    md2 = dict(md, title="MCP selftest record (updated)")
    # 下書き段階の更新（publish=Falseで下書きのまま）
    u = update_record(rid, md2, publish=False); print(" update draft title ->", u["record"]["title"])
    print(" add_file:", add_file(rid, "hello.txt", text="hello from MCP"))
    print(" list_files:", list_files(rid, draft=True))
    p = publish_record(rid); print(" publish:", p["state"])
    import time; time.sleep(1)
    print(" search finds it:", any(x["id"] == rid for x in search_records("MCP selftest", 20)["records"]))
    d = delete_record(rid, confirm=True); print(" delete_record(soft):", d)
    time.sleep(1)
    print(" restore:", restore_record(rid)["restored"])
    time.sleep(1)
    d2 = delete_record(rid, confirm=True); print(" cleanup delete:", d2["deleted"])
    print("== selftest OK ==")


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"invenio-mcp stdio server {__version__}")
    elif "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run()
