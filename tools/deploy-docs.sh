#!/usr/bin/env bash
# deploy-docs.sh — ドキュメントサイトを gh-pages へ出す。**唯一の公開手順**である。
#
# もともと .github/workflows/docs.yml がやっていたことを、そのままここへ移した。
# GitHub Pages は gh-pages ブランチを直接配信している
# （Settings → Pages → Deploy from a branch → gh-pages / root）。
# **gh-pages は生成物**なので、手で触らない。書き手はこのスクリプトだけ。
#
#   bash tools/deploy-docs.sh              # 検査 → ビルド → 公開
#   bash tools/deploy-docs.sh --dry-run    # 検査とビルドだけ（push しない）
#
# 必要なもの:  pip install -r docs/requirements.txt
#
# 出す前に2つ確かめる。どちらも「サイトにあるのにリポジトリで追えない内容」を
# 防ぐためのもので、CI では checkout がその役をしていた。
#   * 追跡ファイルに未コミットの変更が無いこと（ALLOW_DIRTY=1 で外せる）
#   * HEAD が origin に押されていること（押されていなければ警告のみ）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY=1

die() { echo "  ✗ $*" >&2; exit 1; }

command -v mkdocs >/dev/null 2>&1 || \
  die "mkdocs が無い。pip install -r docs/requirements.txt"

echo "=== 1. 出せる状態か ==="
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  if [ "${ALLOW_DIRTY:-}" = "1" ]; then
    echo "  ! 未コミットの変更があるまま出す（ALLOW_DIRTY=1）"
  else
    git status --short --untracked-files=no | sed 's/^/    /'
    die "未コミットの変更がある。先にコミットするか ALLOW_DIRTY=1 を付ける"
  fi
fi
head="$(git rev-parse HEAD)"
branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$branch" 2>/dev/null
remote="$(git rev-parse "origin/$branch" 2>/dev/null || true)"
if [ -n "$remote" ] && [ "$head" != "$remote" ]; then
  echo "  ! HEAD が origin/$branch と違う。サイトにだけ在って追えない内容になりうる"
fi
echo "  ✓ $branch $(git rev-parse --short HEAD)"

echo
echo "=== 2. 検査 ==="
# ツール一覧は実装と locales/ から起こしている。**そこを直したのに公開が
# 追随しない**ことがないよう、出す前に必ず突き合わせる。
# 通ったときは黙る。出るのは落ちたときの理由だけでよい。
out="$("$PY" tools/gen_tool_reference.py --check 2>&1)" \
  || { echo "$out" | sed 's/^/    /'; die "ツール一覧が実装とずれている"; }
echo "  ✓ ツール一覧は最新"

# --strict: リンク切れや解決できない参照を警告で済ませず、失敗にする
out="$(mkdocs build --strict --quiet --site-dir "$(mktemp -d)" 2>&1)" \
  || { echo "$out" | sed 's/^/    /'; die "サイトが --strict で建たない"; }
echo "  ✓ サイトが --strict で建つ"

if [ -n "$DRY" ]; then
  echo
  echo "--dry-run のためここで止める（公開していない）"
  exit 0
fi

echo
echo "=== 3. 公開 ==="
mkdocs gh-deploy --force --strict \
  --message "Deployed {sha} from tools/deploy-docs.sh with MkDocs version: {version}" \
  || die "gh-deploy に失敗した"

echo
echo "  https://rcosdp.github.io/invenio-mcp/     （反映まで1分ほどかかる）"
echo "  https://rcosdp.github.io/invenio-mcp/ja/"
