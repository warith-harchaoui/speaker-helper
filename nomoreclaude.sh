#!/usr/bin/env bash
# nomoreclaude.sh — strip every Claude / Anthropic attribution from this
# repo's commit history, then (optionally) force-push the rewritten history
# to ``origin``. Authorship of this repo is Warith Harchaoui's alone.
#
# What it strips (commit messages only — trees are untouched):
#   - ``Co-Authored-By: Claude …`` trailers (any casing)
#   - ``Co-Authored-By: … <noreply@anthropic.com>`` lines
#   - ``🤖 Generated with [Claude Code]`` / ``Generated with Claude`` footers
# What it does NOT touch:
#   - source files; tags/branches/other remotes (only ``origin`` on push).
#
# Usage:
#   ./nomoreclaude.sh            # rewrite local history, show the diff
#   ./nomoreclaude.sh --push     # also force-push origin (destructive)
set -euo pipefail
cd "$(dirname "$0")"

echo "== commits carrying a Claude/Anthropic attribution (before) =="
before=$(git log --all --format='%H' | while read -r h; do
  git log -1 --format='%B' "$h" | grep -qiE 'co-authored-by:.*(claude|anthropic)|generated with \[?claude|🤖 generated with' && echo x
done | wc -l | tr -d ' ')
echo "  $before"
[ "$before" = "0" ] && { echo "nothing to strip."; exit 0; }

# Message-only rewrite: fast, keeps every tree/blob byte-identical.
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
  --msg-filter "sed -E '/^[Cc]o-[Aa]uthored-[Bb]y:.*([Cc]laude|anthropic\.com)/d; /🤖 [Gg]enerated with/d; /[Gg]enerated with \[?[Cc]laude/d'" \
  -- --all

after=$(git log --all --format='%H' | while read -r h; do
  git log -1 --format='%B' "$h" | grep -qiE 'co-authored-by:.*(claude|anthropic)|generated with \[?claude|🤖 generated with' && echo x
done | wc -l | tr -d ' ')
echo "== after: $after contaminated commits =="

if [ "${1:-}" = "--push" ]; then
  echo "== force-pushing origin (destructive) =="
  git push --force origin --all
  git push --force origin --tags
fi
