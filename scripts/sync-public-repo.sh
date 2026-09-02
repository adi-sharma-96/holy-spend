#!/usr/bin/env bash
# Pushes the current state of main to the public OSS repo (source, minus
# the paths in EXCLUDE, with README.oss.md standing in for README.md) and
# refreshes the live GitHub Pages site from docs/site in the same run.
#
# Deliberately does NOT merge main into either target branch - a merge
# carries main's full ancestry along with it, which is exactly what the
# public repo must never have. Instead each sync replaces each branch's
# tree wholesale and makes one new, ordinary commit on top of that
# branch's own history.
#
# Usage: scripts/sync-public-repo.sh
# Requires a git remote named "public-remote" pointing at the OSS repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

EXCLUDE=(
  "docs/marketplace-roadmap.md"
  "docs/railway-deployment.md"
  "railway.json"
  "railway.mcp.json"
  "railway.tunnel.json"
  "CLAUDE.md"
  "AGENTS.md"
  ".cursor"
)

if ! git show-ref --verify --quiet refs/heads/public; then
  git checkout --orphan public
  git reset --hard
else
  git checkout public
fi

# Replace the tree wholesale with main's current tree.
git rm -rf --quiet -- . >/dev/null 2>&1 || true
git checkout main -- .

for f in "${EXCLUDE[@]}"; do
  git rm -rf --ignore-unmatch --quiet -- "$f"
done

git show main:README.oss.md > README.md
git add -A
git commit --quiet -m "Sync from main" --allow-empty

git push public-remote public:main

git checkout main

# --- Refresh the live Pages site (public repo's gh-pages branch) ---
if ! git show-ref --verify --quiet refs/heads/gh-pages; then
  git checkout --orphan gh-pages
  git reset --hard
else
  git checkout gh-pages
fi

git rm -rf --quiet -- . >/dev/null 2>&1 || true
git checkout main -- docs/site
shopt -s dotglob
mv docs/site/* .
rm -rf docs
shopt -u dotglob

git add -A
git commit --quiet -m "Sync from main" --allow-empty

git push public-remote gh-pages:gh-pages

git checkout main
echo "Synced source and Pages site to the public repo."
