#!/usr/bin/env bash
# Pushes the current state of main to the public OSS repo, minus the
# paths in EXCLUDE, with README.oss.md standing in for README.md.
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
)

if git show-ref --verify --quiet refs/heads/public; then
  git checkout public
  git merge main --no-commit --no-ff -m "Sync from main" || true
else
  git checkout -b public main
fi

# Resolve modify/delete conflicts on paths we intentionally keep stripped,
# and re-strip them in case main touched them again since the last sync.
for f in "${EXCLUDE[@]}" "README.oss.md"; do
  git rm -rf --ignore-unmatch --quiet -- "$f" 2>/dev/null || true
done

if git diff --name-only --diff-filter=U 2>/dev/null | grep -q .; then
  echo "Unresolved merge conflicts outside the known-excluded list:"
  git diff --name-only --diff-filter=U
  exit 1
fi

git show main:README.oss.md > README.md
git add README.md
git commit --quiet -m "Sync from main" --allow-empty

git push public-remote public:main

git checkout main
echo "Synced and pushed to public repo."
