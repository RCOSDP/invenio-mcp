#!/usr/bin/env python3
"""MCP のファイル系ツールを端から端まで通す検証（PASS/FAIL）。

`mcp_client.py` は**認可**の適合を見るもので、ファイルの授受は見ていなかった。
ファイル系は 3 手順（初期化 → 本体 → コミット）で、しかも InvenioRDM の
transfer 種別ごとに経路が違うため、壊れても認可テストでは気づけない。
ここでは 4 経路すべてを実データで往復させる。

  L  LOCAL     upload_file            … base64/平文で MCP サーバ経由
  F  FETCH     upload_file_from_url   … URL を渡して InvenioRDM に取りに行かせる
  M  MULTIPART start_multipart_upload … 署名済み URL でクライアントから S3 へ直接
  -  取得      download_file          … presigned へのリダイレクトを追って取る

使い方（`mcp_client.py` と同じ環境変数）:

    export SSL_CERT_FILE=/path/to/ca.crt        # 自己署名のとき
    export KC_BASE=https://keycloak.example.org
    export MCP_RESOURCE=https://mcp.example.org/mcp
    python3 conformance/verify-mcp-files.py

環境変数:
  MCP_FETCH_URL   FETCH 経路で取りに行かせる URL
                  （既定 INVENIO_UI の robots.txt。
                    InvenioRDM の許可ドメインに入っている必要がある）
  MCP_MP_SIZE     multipart で送る検証データの大きさ（既定 12MiB）
  MCP_MP_PART     1パートの大きさ（既定 8MiB。S3 の下限は 5MiB）
"""
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_client as mc  # noqa: E402  （認可の段取りをそのまま使い回す）

FETCH_URL = os.environ.get(
    "MCP_FETCH_URL",
    os.environ.get("INVENIO_UI", "https://localhost").rstrip("/") + "/robots.txt")
MP_SIZE = int(os.environ.get("MCP_MP_SIZE", str(12 * 1024 * 1024)))
MP_PART = int(os.environ.get("MCP_MP_PART", str(8 * 1024 * 1024)))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def call(tool, args, token):
    """ツールを呼んで、返ってきた JSON を dict で返す。失敗時は例外の代わりに dict。"""
    st, _h, body = mc.tools_call(tool, args, token)
    res = body.get("result") or {}
    text = (res.get("content") or [{}])[0].get("text", "")
    if st != 200 or res.get("isError"):
        return {"_error": True, "status": st, "text": text[:400]}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}


def get_token():
    """PRM → AS メタデータ → 動的登録 → 認可コード の順に進めて token を得る。"""
    br = mc.Browser()
    # PRM の在り処は 401 の WWW-Authenticate から辿る（仕様どおりの発見手順）
    _st, hdrs, _b = mc.tools_call("create_record", {"metadata": {}}, None)
    wa = mc.parse_www_authenticate(hdrs.get("www-authenticate", ""))
    st, prm = mc.get_json(wa["resource_metadata"])
    if st != 200:
        raise SystemExit(f"保護リソースメタデータが取れない: status={st}")
    as_issuer = prm["authorization_servers"][0]
    p = urllib.parse.urlparse(as_issuer)
    st, md = mc.get_json(
        f"{p.scheme}://{p.netloc}/.well-known/oauth-authorization-server{p.path}")
    if st != 200:
        st, md = mc.get_json(f"{as_issuer.rstrip('/')}/.well-known/openid-configuration")

    reg = {"client_name": "MCP File Tools Test Client",
           "redirect_uris": [mc.REDIRECT],
           "grant_types": ["authorization_code", "refresh_token"],
           "response_types": ["code"],
           "token_endpoint_auth_method": "none",
           "application_type": "native"}
    st, _h, b = mc.req(md["registration_endpoint"], data=json.dumps(reg).encode(),
                       headers={"Content-Type": "application/json"}, method="POST")
    if st not in (200, 201):
        raise SystemExit(f"クライアント登録に失敗: status={st} {b[:200]}")
    info = json.loads(b)
    # ファイル操作は write が要るので、最初からまとめて要求する（step-up は認可側の検証事項）
    token, _notes = mc.authorize(md, info["client_id"], ["mcp:read", "mcp:write"],
                                 br, info.get("client_secret"))
    return token


def put_part(url, blob):
    """署名済み URL にパートを PUT する。戻りは HTTP ステータス。"""
    req = urllib.request.Request(url, data=blob, method="PUT")
    req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main():
    print(f"対象: {mc.MCP_URL}")
    token = get_token()
    print("認可: 取得済み（mcp:read mcp:write）\n")

    print("=== 下書きを作る ===")
    rec = call("create_record", {
        "metadata": {"title": "MCP ファイル系ツール検証"},
        "files": True,
    }, token)
    if rec.get("_error"):
        return check("下書きの作成", False, str(rec)) or 1
    recid = rec["id"]
    check("下書きの作成", True, recid)

    print("\n=== L: upload_file（平文）===")
    text = "これは MCP 経由で入れた検証用のテキストです。\n"
    up = call("upload_file", {"recid": recid, "filename": "note.txt",
                              "content_text": text}, token)
    check("upload_file が completed", up.get("status") == "completed",
          f"size={up.get('size')} {up.get('text', '')}"[:120] if up.get("_error") else
          f"size={up.get('size')}")

    print("\n=== 取得: download_file ===")
    dl = call("download_file", {"recid": recid, "filename": "note.txt",
                                "draft": True}, token)
    got = dl.get("text")
    check("download_file の中身が一致", got == text,
          "" if got == text else f"取得={str(got)[:60]!r}")

    print("\n=== F: upload_file_from_url（FETCH）===")
    # v14 の既定の権限方針は transfer 種別 F を SystemProcess() だけに許す
    # （サーバに任意の URL を取りに行かせる操作を絞った）。通常の利用者では 403 になる。
    # ここで見たいのは **送っている形が v14 のスキーマに合っていること**なので、
    # 400（検証エラー＝形が違う）ではなく 403（権限）で止まることを確かめる。
    fe = call("upload_file_from_url",
              {"recid": recid, "filename": "fetched.bin", "url": FETCH_URL}, token)
    msg = str(fe.get("text") or "")
    if not fe.get("_error"):
        check("FETCH の登録が通る（権限のある利用者）", fe.get("transfer") == "F", str(fe))
        fetch_done = True
    else:
        check("FETCH は権限で止まる（形の誤りではない）",
              "権限が無い" in msg or "403" in msg, msg[:160])
        fetch_done = False

    print(f"\n=== M: multipart（{MP_SIZE} バイトを {MP_PART} バイトずつ）===")
    # 内容を再現できる形で作る（一致判定のため）
    blob = bytes((i * 7 + 3) % 256 for i in range(65536))
    blob = (blob * (MP_SIZE // len(blob) + 1))[:MP_SIZE]

    mp = call("start_multipart_upload",
              {"recid": recid, "filename": "big.bin",
               "size": MP_SIZE, "part_size": MP_PART}, token)
    if mp.get("_error"):
        check("start_multipart_upload", False, str(mp)[:200])
        return 1
    expected_parts = -(-MP_SIZE // MP_PART)
    check("パート数が想定どおり", mp.get("parts") == expected_parts,
          f"{mp.get('parts')} / 想定 {expected_parts}")
    urls = mp.get("parts_urls") or []
    check("署名済み URL が返る", len(urls) == expected_parts, f"{len(urls)} 本")
    # 中身が MCP サーバを通らないこと＝URL の宛先が MCP サーバでないこと
    host = urllib.parse.urlparse(urls[0]["url"]).netloc if urls else ""
    check("URL の宛先が S3（MCP サーバではない）",
          host and host != urllib.parse.urlparse(mc.MCP_URL).netloc, host)

    codes = []
    for i, p in enumerate(urls):
        chunk = blob[i * MP_PART:(i + 1) * MP_PART]
        codes.append(put_part(p["url"], chunk))
    check("全パートの PUT が 200", all(c == 200 for c in codes), str(codes))

    cm = call("complete_multipart_upload",
              {"recid": recid, "filename": "big.bin"}, token)
    check("commit が completed", cm.get("status") == "completed", str(cm)[:160])
    check("サイズが一致", cm.get("size") == MP_SIZE, str(cm.get("size")))
    check("transfer が L に変わる（通常ファイルになる）",
          cm.get("transfer") == "L", str(cm.get("transfer")))

    print("\n=== 中身の突き合わせ ===")
    # commit 直後の checksum は S3 の複合 ETag（パートごとの MD5 をまとめた MD5）。
    # 手元でも同じ計算ができるので、**全パートが化けずに着いたか**を照合できる。
    part_md5s = [hashlib.md5(blob[i * MP_PART:(i + 1) * MP_PART]).digest()
                 for i in range(expected_parts)]
    expect_etag = f"multipart:{hashlib.md5(b''.join(part_md5s)).hexdigest()}-{expected_parts}-{MP_PART}"
    check("複合 ETag が手元の計算と一致", cm.get("checksum") == expect_etag,
          f"{cm.get('checksum')} / 期待 {expect_etag}")

    # そのあと InvenioRDM が非同期ジョブでファイル全体の MD5 を計算し直す。
    # そこまで待って、**送った中身そのもの**と一致することを確かめる。
    want_md5 = "md5:" + hashlib.md5(blob).hexdigest()
    got = None
    for _ in range(30):
        files = call("list_files", {"recid": recid, "draft": True}, token)
        got = next((f.get("checksum") for f in files.get("files", [])
                    if f.get("key") == "big.bin"), None)
        if got and got.startswith("md5:"):
            break
        time.sleep(2)
    check("全体の MD5 が再計算され、送った中身と一致", got == want_md5,
          f"{got} / 期待 {want_md5}")

    files = call("list_files", {"recid": recid, "draft": True}, token)
    keys = {f["key"] for f in files.get("files", [])}
    want_keys = {"note.txt", "big.bin"} | ({"fetched.bin"} if fetch_done else set())
    check("一覧に出るファイルが想定どおり", want_keys <= keys, str(sorted(keys)))

    print("\n=== 中断の経路 ===")
    mp2 = call("start_multipart_upload",
               {"recid": recid, "filename": "aborted.bin",
                "size": MP_SIZE, "part_size": MP_PART}, token)
    ab = call("abort_multipart_upload",
              {"recid": recid, "filename": "aborted.bin"}, token)
    check("abort_multipart_upload が通る",
          not mp2.get("_error") and ab.get("aborted") == "aborted.bin", str(ab)[:120])

    print("\n=== 後片付け ===")
    dd = call("delete_draft", {"recid": recid}, token)
    check("検証用の下書きを破棄", not dd.get("_error"), str(dd)[:120])

    ng = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"結果: {len(RESULTS) - len(ng)} PASS / {len(ng)} FAIL")
    for n in ng:
        print(f"  FAIL: {n}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
