#!/usr/bin/env bash
# release.sh — 版を出す。**唯一の出し方**である。
#
# もともと .github/workflows/release.yml がタグ push を受けてやっていたことを、
# そのままここへ移した。順番も同じで、確かめてから出す。
#
#   bash tools/release.sh v0.0.3              # 検査とイメージのビルドだけ（既定）
#   bash tools/release.sh v0.0.3 --publish    # ＋ タグを打って push し、リリースを作る
#
# 既定が「出さない」なのは、確かめる作業と出す作業を分けておきたいからである。
# --publish は git のタグと GitHub のリリースを作る——**取り消しにくい**。
#
# 必要なもの: docker（イメージのビルド）、gh（リリースの作成・--publish のときだけ）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
TAG="${1:-}"
PUBLISH=""
[ "${2:-}" = "--publish" ] && PUBLISH=1

die() { echo "  ✗ $*" >&2; exit 1; }

case "$TAG" in
  v*) ;;
  *)  die "使い方: bash tools/release.sh v0.0.3 [--publish]" ;;
esac
VER="${TAG#v}"

echo "=== 1. 版が揃っているか ==="
# **タグと __version__ が一致していること。** ずれると「v0.0.2 と名乗る 0.0.1」が
# 世に出る。版はコードが持つので、ここで突き合わせる。
for f in http/mcp_server.py stdio/server.py; do
  got="$("$PY" -c "import re;print(re.search(r'^__version__ = \"([^\"]+)\"', open('$f').read(), re.M).group(1))")"
  [ "$VER" = "$got" ] || die "tag=$VER だが $f=$got"
  echo "  ✓ $f = $got"
done

# **変更履歴にその版の節があること。** 無いまま出すと、利用者が「何が変わったのか」を
# 調べる先が無くなる。両言語とも見る。
for f in CHANGELOG.md CHANGELOG.ja.md; do
  grep -q "^## \[$VER\]" "$f" || die "$f に $VER の節が無い"
  echo "  ✓ $f に $VER の節がある"
done

echo
echo "=== 2. 検査 ==="
# 出力は段を下げて出す（この中の「=== 1. …」は check.sh のもの）
bash tools/check.sh 2>&1 | sed 's/^/  /' || die "検査に落ちた"

echo
echo "=== 3. イメージ ==="
# マニフェストと同じ作り方で通ることを確かめる（配るのは別の話）。
if command -v docker >/dev/null 2>&1; then
  docker build -t "invenio-mcp:$TAG" http/ >/dev/null || die "イメージのビルドに失敗した"
  echo "  ✓ invenio-mcp:$TAG"
else
  echo "  ! docker が無いので飛ばす"
fi

echo
echo "=== 4. リリースノート ==="
# CHANGELOG.md のその版の節を、そのままノートにする（二重に書かない）。
notes="$(mktemp)"
awk "/^## \[$VER\]/{f=1;next} /^## \[/{f=0} f" CHANGELOG.md > "$notes"
[ -s "$notes" ] || die "CHANGELOG.md から $VER の節を取り出せなかった"
sed 's/^/    /' "$notes"

if [ -z "$PUBLISH" ]; then
  echo
  echo "ここまでが検査。出すなら --publish を付けて実行する。"
  exit 0
fi

echo
echo "=== 5. 公開 ==="
command -v gh >/dev/null 2>&1 || die "gh が無い（リリースの作成に要る）"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "未コミットの変更がある"

git tag -a "$TAG" -m "$TAG"
git push origin "$TAG"
gh release create "$TAG" --title "$TAG" --notes-file "$notes" --verify-tag
echo "  ✓ $TAG"
