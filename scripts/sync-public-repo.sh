#!/usr/bin/env bash
# Pushes the current state of main to the public OSS repo (source, minus
# the paths in EXCLUDE, with README.oss.md standing in for README.md) and
# refreshes the live GitHub Pages site from docs/site in the same run.
#
# Both steps run in throwaway git worktrees, never in this checkout's own
# working directory. That's deliberate, not incidental: this repo's
# working directory accumulates untracked build/test artifacts
# (node_modules, .venv, pytest tmp dirs) that `git add -A` would happily
# sweep into a commit on a branch with no .gitignore of its own (gh-pages
# has never had one). A worktree is always a clean checkout with nothing
# untracked in it, so that class of leak is structurally impossible here,
# not just avoided by care.
#
# Also deliberately does NOT merge main into either target branch - a
# merge carries main's full ancestry along with it, which is exactly what
# the public repo must never have. Instead each sync replaces each
# branch's tree wholesale and makes one new, ordinary commit on top of
# that branch's own history.
#
# Usage:
#   scripts/sync-public-repo.sh                  # message picked automatically
#   scripts/sync-public-repo.sh "Custom message" # override
#
# Requires a git remote named "public-remote" pointing at the OSS repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
REPO_ROOT="$(pwd)"
PARENT_DIR="$(dirname "$REPO_ROOT")"

EXCLUDE=(
  "docs/marketplace-roadmap.md"
  "docs/railway-deployment.md"
  "railway.json"
  "railway.mcp.json"
  "railway.tunnel.json"
  "CLAUDE.md"
  "AGENTS.md"
  ".cursor"
  "README.oss.md"
)

cleanup() {
  git worktree remove "$SRC_WT" --force >/dev/null 2>&1 || true
  git worktree remove "$PAGES_WT" --force >/dev/null 2>&1 || true
}
trap cleanup EXIT

# --- Work out the commit message ---
# One real commit since the last sync: reuse its message verbatim.
# Several: collapse into a bullet list of subjects. Neither is computed
# from a commit whose *entire* diff was confined to an excluded path -
# such a commit never reaches the public repo, so its message shouldn't
# either, even as a passing mention. First sync ever (no tag yet) just
# falls back to a plain label, since walking all of history would dump
# the whole private commit log into one message.
if [[ -n "${1:-}" ]]; then
  SYNC_MSG="$1"
elif git rev-parse -q --verify refs/tags/last-public-sync >/dev/null; then
  PATHSPECS=(".")
  for f in "${EXCLUDE[@]}"; do
    PATHSPECS+=(":(exclude)$f")
  done
  RANGE="$(git rev-parse last-public-sync)..main"
  mapfile -t RELEVANT_SHAS < <(git log "$RANGE" --format=%H -- "${PATHSPECS[@]}")
  if [[ ${#RELEVANT_SHAS[@]} -eq 0 ]]; then
    SYNC_MSG="Sync from main"
  elif [[ ${#RELEVANT_SHAS[@]} -eq 1 ]]; then
    SYNC_MSG="$(git log -1 --format=%B "${RELEVANT_SHAS[0]}")"
  else
    SYNC_MSG="Sync from main"$'\n\n'"$(git log "$RANGE" --format='- %s' -- "${PATHSPECS[@]}")"
  fi
else
  SYNC_MSG="Sync from main"
fi

# --- Source (public repo's main branch) ---
SRC_WT="$PARENT_DIR/hs-sync-src"
rm -rf "$SRC_WT"
if git show-ref --verify --quiet refs/heads/public; then
  git worktree add -q "$SRC_WT" public
else
  git worktree add -q --detach "$SRC_WT" main
  (cd "$SRC_WT" && git checkout --orphan public -q && git reset --hard -q)
fi

find "$SRC_WT" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
git -C "$REPO_ROOT" archive main | tar -x -C "$SRC_WT"

for f in "${EXCLUDE[@]}"; do
  rm -rf "${SRC_WT:?}/${f}"
done
cp "$REPO_ROOT/README.oss.md" "$SRC_WT/README.md"

(
  cd "$SRC_WT"
  git add -A
  git commit --quiet -m "$SYNC_MSG" --allow-empty
  git push public-remote public:main
)

git tag -f last-public-sync main >/dev/null

# --- Live Pages site (public repo's gh-pages branch) ---
PAGES_WT="$PARENT_DIR/hs-sync-pages"
rm -rf "$PAGES_WT"
if git show-ref --verify --quiet refs/heads/gh-pages; then
  git worktree add -q "$PAGES_WT" gh-pages
else
  git worktree add -q --detach "$PAGES_WT" main
  (cd "$PAGES_WT" && git checkout --orphan gh-pages -q && git reset --hard -q)
fi

find "$PAGES_WT" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
cp -r "$REPO_ROOT/docs/site/." "$PAGES_WT/"

(
  cd "$PAGES_WT"
  git add -A
  git commit --quiet -m "$SYNC_MSG" --allow-empty
  git push public-remote gh-pages:gh-pages
)

echo "Synced source and Pages site to the public repo."
