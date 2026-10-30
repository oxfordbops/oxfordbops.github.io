#!/usr/bin/env bash
# One-time history rewrite: replaces every commit with a single fresh one under the project's
# neutral identity, so the public history carries no personal author, no early tool logs and
# no remnants of the old backend. Run from the repo root. Nobody else has cloned the repo yet,
# so the force-push is safe; after it, any other clone must be re-cloned.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "commit or stash your changes first"; exit 1; }
export GIT_AUTHOR_NAME="Cambridge Bops" GIT_AUTHOR_EMAIL="cambridgebops@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
git checkout -q --orphan fresh
git add -A
git commit -q -m "Cambridge Bops: static site, verified-source registry, daily routine, tests and Pages deploy"
git branch -D main -q
git branch -m main
git push --force origin main
git log --format='%h %an <%ae> | %s'
echo "History rewritten: one commit, author $GIT_AUTHOR_NAME."
