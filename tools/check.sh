#!/usr/bin/env bash
# check.sh — 手元で回す検査。**これが唯一の門番**である。
#
# もともと .github/workflows/ci.yml が見ていたものを、そのままここへ移した。
# GitHub Actions は使わない（動かせない環境がある）。CI と手元の2系統を並べると、
# 片方でしか通らない変更が必ず生まれるので、系統は1つにしてある。
#
#   bash tools/check.sh          # 全部
#   SKIP_IMPORT=1 …              # mcp を入れていない環境（構文と資源だけ見る）
#
# 依存（サーバの読み込み検査に要る。無ければ SKIP_IMPORT=1）:
#   pip install "mcp==1.26.0" "pyjwt[crypto]>=2.8" "httpx>=0.27" "uvicorn>=0.30"
# ドキュメントのビルド検査に要るもの（無ければその項目だけ飛ばす）:
#   pip install -r docs/requirements.txt
set -uo pipefail

# どこから叩かれてもリポジトリの根で動く
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
PASS=0; FAIL=0; SKIP=0

run() {   # run [-q] <名前> <コマンド…>   -q は通ったときの出力を捨てる
  local quiet=""
  [ "$1" = "-q" ] && { quiet=1; shift; }
  local name="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    echo "  [PASS] $name"
    [ -z "$quiet" ] && [ -n "$out" ] && echo "$out" | sed 's/^/         /'
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    echo "$out" | sed 's/^/         /'
    FAIL=$((FAIL + 1))
  fi
}

skip() { echo "  [SKIP] $1 — $2"; SKIP=$((SKIP + 1)); }

echo "=== 1. 構文 ==="
run "両サーバがコンパイルできる" "$PY" -m py_compile http/mcp_server.py stdio/server.py

echo
echo "=== 2. サーバの中身 ==="
# **ツールの数を数える。** 数が変わるのは機能の変更であって、事故で変わることは無い。
# 説明の無いツールは、モデルから見ると存在しないのと同じなので落とす。
if [ "${SKIP_IMPORT:-}" = "1" ]; then
  skip "両サーバが読み込め、ツール数と説明が揃っている" "SKIP_IMPORT=1"
elif ! "$PY" -c "import mcp" 2>/dev/null; then
  skip "両サーバが読み込め、ツール数と説明が揃っている" \
       "mcp が無い（pip install \"mcp==1.26.0\" \"pyjwt[crypto]>=2.8\" \"httpx>=0.27\" \"uvicorn>=0.30\"）"
else
  run "両サーバが読み込め、ツール数と説明が揃っている" "$PY" -c '
import importlib.util, asyncio
for path, n in (("stdio/server.py", 12), ("http/mcp_server.py", 33)):
    spec = importlib.util.spec_from_file_location("m", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    tools = asyncio.run(m.mcp.list_tools())
    assert len(tools) == n, f"{path}: {len(tools)} tools, expected {n}"
    missing = [t.name for t in tools if not t.description]
    assert not missing, f"{path}: tools with no description: {missing}"
    print(path, len(tools), "tools ok")
'
fi

# **同じキーが全言語に在ること。** 片方にしか無いキーは、その言語だと英語に落ちる
# ——動きはするので気づかないまま残る。
run "言語資源のキーが一致している" "$PY" -c '
import json, sys
def flat(d, p=""):
    out = set()
    for k, v in d.items():
        out |= flat(v, p + k + ".") if isinstance(v, dict) else {p + k}
    return out
bad = False
for loc in ("http/locales", "stdio/locales"):
    base = flat(json.load(open(f"{loc}/en.json", encoding="utf-8")))
    for lang in ("ja",):
        other = flat(json.load(open(f"{loc}/{lang}.json", encoding="utf-8")))
        diff = base ^ other
        print(f"{loc} en/{lang}: {len(base)} keys, diff {sorted(diff)}")
        bad |= bool(diff)
sys.exit(1 if bad else 0)
'

# **2つのサーバは1つの版で出す。** 片方だけ上がっていると、利用者が
# 「0.2.0 の invenio-mcp」と言ったときに何を指すのか決まらなくなる。
run "2つのサーバの版が一致している" "$PY" -c '
import re, sys
v = {}
for p in ("http/mcp_server.py", "stdio/server.py"):
    v[p] = re.search(r"^__version__ = \"([^\"]+)\"", open(p, encoding="utf-8").read(), re.M).group(1)
print(v)
sys.exit(0 if len(set(v.values())) == 1 else 1)
'

echo
echo "=== 3. ドキュメント ==="
run "ツール一覧が実装と一致している" "$PY" tools/gen_tool_reference.py --check

# --strict: リンク切れや解決できない参照を警告で済ませず、失敗にする
if command -v mkdocs >/dev/null 2>&1; then
  # 出力は通ったときだけ捨てる（mkdocs は通っても大量に喋る）
  run -q "サイトが --strict で建つ" mkdocs build --strict --quiet --site-dir "$(mktemp -d)"
else
  skip "サイトが --strict で建つ" "mkdocs が無い（pip install -r docs/requirements.txt）"
fi

echo
echo "============================================================"
echo "結果: $PASS PASS / $FAIL FAIL / $SKIP SKIP"
[ "$FAIL" -eq 0 ] || exit 1
