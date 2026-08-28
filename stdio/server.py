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

CLI: `python3 server.py --selftest` で REST 一連を実走して片付ける。
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

# ---- 設定 ----
_HERE = os.path.dirname(os.path.abspath(__file__))
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
    raise RuntimeError("INVENIO_TOKEN 未設定かつ .token が無い")

_CTX = ssl.create_default_context()
if VERIFY:
    if CA_BUNDLE:
        _CTX.load_verify_locations(CA_BUNDLE)
else:
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


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
        raise ApiError(f"HTTP {e.code} {method} {path}: {detail}")


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

# ---------------- 読取 ----------------
@mcp.tool()
def search_records(query: str = "", size: int = 10) -> dict:
    """公開レコードを検索する。query は Invenio 検索式（空で全件）。要点のみ返す。"""
    q = f"?q={urllib.parse.quote(query)}&size={int(size)}" if query else f"?size={int(size)}"
    _, j = _req("GET", f"/records{q}")
    hits = (j or {}).get("hits", {}).get("hits", [])
    return {"total": (j or {}).get("hits", {}).get("total"), "records": [_brief(h) for h in hits]}


@mcp.tool()
def get_record(recid: str, draft: bool = False) -> dict:
    """1レコードを取得する。draft=True で下書きを取得。"""
    path = f"/records/{recid}/draft" if draft else f"/records/{recid}"
    _, j = _req("GET", path)
    return _brief(j)


# ---------------- メタデータ 登録/更新 ----------------
def _default_access():
    return {"record": "public", "files": "public"}


@mcp.tool()
def create_record(metadata: dict, access: dict = None, files_enabled: bool = False, publish: bool = False) -> dict:
    """新規レコードを作成する。metadata は Invenio の metadata オブジェクト
    （必須: resource_type{id}, title(≥3), publication_date(EDTF), creators[{person_or_org{type,family_name,given_name}}]）。
    files_enabled=False は metadata-only。publish=True で即公開。返り値に recid を含む。"""
    body = {"access": access or _default_access(), "files": {"enabled": bool(files_enabled)}, "metadata": metadata}
    _, j = _req("POST", "/records", body=body)
    recid = j.get("id")
    out = {"recid": recid, "state": "draft", "record": _brief(j)}
    if publish:
        out["record"] = _brief(_req("POST", f"/records/{recid}/draft/actions/publish")[1])
        out["state"] = "published"
    return out


@mcp.tool()
def update_record(recid: str, metadata: dict, publish: bool = True) -> dict:
    """既存レコードのメタデータを更新する。公開済みなら edit(下書き化)→更新→(publish) を行う。
    metadata は完全な metadata オブジェクト（部分ではなく置換）。publish=False なら下書きのまま。"""
    # 既存の下書きがあればそれを、無ければ公開レコードから編集下書きを作る
    try:
        _, draft = _req("GET", f"/records/{recid}/draft")
    except ApiError:
        _req("POST", f"/records/{recid}/draft")            # 公開レコードから編集下書きを作成
        _, draft = _req("GET", f"/records/{recid}/draft")
    draft["metadata"] = metadata
    _, upd = _req("PUT", f"/records/{recid}/draft", body=draft)
    out = {"recid": recid, "state": "draft", "record": _brief(upd)}
    if publish:
        out["record"] = _brief(_req("POST", f"/records/{recid}/draft/actions/publish")[1])
        out["state"] = "published"
    return out


@mcp.tool()
def publish_record(recid: str) -> dict:
    """下書きを公開する。"""
    _, j = _req("POST", f"/records/{recid}/draft/actions/publish")
    return {"recid": recid, "state": "published", "record": _brief(j)}


@mcp.tool()
def new_version(recid: str, metadata: dict = None, publish: bool = False) -> dict:
    """新しいバージョンの下書きを作る。metadata を渡すと差し替え、publish=True で即公開。"""
    _, nv = _req("POST", f"/records/{recid}/versions")
    new_id = nv.get("id")
    if metadata is not None:
        nv["metadata"] = metadata
        # 新版は publication_date が必須になる場合があるため呼び出し側で含めること
        _, nv = _req("PUT", f"/records/{new_id}/draft", body=nv)
    out = {"recid": new_id, "state": "draft", "record": _brief(nv)}
    if publish:
        out["record"] = _brief(_req("POST", f"/records/{new_id}/draft/actions/publish")[1])
        out["state"] = "published"
    return out


# ---------------- 削除 ----------------
@mcp.tool()
def delete_draft(recid: str) -> dict:
    """下書き（未公開 or 編集中の下書き）を破棄する。"""
    _req("DELETE", f"/records/{recid}/draft")
    return {"recid": recid, "deleted": "draft"}


@mcp.tool()
def delete_record(recid: str, confirm: bool = False, reason_id: str = "out-of-scope", note: str = "removed via MCP") -> dict:
    """公開レコードをソフト削除（tombstone・HTTP 410）する。admin トークン必須。
    confirm=True が無いと実行しない。restore_record で復元可能。
    reason_id は removalreasons 語彙（out-of-scope / duplicate / spam / retracted 等）。"""
    if not confirm:
        return {"error": "破壊的操作です。confirm=True を指定してください。", "recid": recid}
    _req("DELETE", f"/records/{recid}/delete", body={"removal_reason": {"id": reason_id}, "note": note})
    return {"recid": recid, "deleted": "record(soft)", "restorable": True}


@mcp.tool()
def restore_record(recid: str) -> dict:
    """ソフト削除された公開レコードを復元する。admin トークン必須。"""
    _, j = _req("POST", f"/records/{recid}/restore")
    return {"recid": recid, "restored": True, "record": _brief(j)}


# ---------------- ファイル ----------------
def _resolve_bytes(text, content_base64, source_path):
    if source_path:
        return open(source_path, "rb").read()
    if content_base64:
        return base64.b64decode(content_base64)
    if text is not None:
        return text.encode("utf-8")
    raise ValueError("text / content_base64 / source_path のいずれかが必要")


@mcp.tool()
def add_file(recid: str, key: str, text: str = None, content_base64: str = None, source_path: str = None) -> dict:
    """下書きにファイルを追加（init→content→commit）する。対象レコードは files_enabled=True である必要がある。
    中身は text(UTF-8) / content_base64 / source_path(サーバ上のパス) のいずれかで渡す。"""
    data = _resolve_bytes(text, content_base64, source_path)
    _req("POST", f"/records/{recid}/draft/files", body=[{"key": key}])
    _req("PUT", f"/records/{recid}/draft/files/{key}/content", raw=data, ctype="application/octet-stream")
    _, j = _req("POST", f"/records/{recid}/draft/files/{key}/commit")
    return {"recid": recid, "key": key, "size": (j or {}).get("size", len(data)), "status": (j or {}).get("status")}


@mcp.tool()
def list_files(recid: str, draft: bool = True) -> dict:
    """レコード/下書きのファイル一覧。"""
    seg = "draft/files" if draft else "files"
    _, j = _req("GET", f"/records/{recid}/{seg}")
    ents = (j or {}).get("entries", [])
    return {"recid": recid, "files": [{"key": e.get("key"), "size": e.get("size"), "status": e.get("status")} for e in ents]}


@mcp.tool()
def delete_file(recid: str, key: str) -> dict:
    """下書きからファイルを削除する。"""
    _req("DELETE", f"/records/{recid}/draft/files/{key}")
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
    if "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run()
