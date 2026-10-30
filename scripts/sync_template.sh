#!/usr/bin/env bash
# Copy the shared, city-independent parts of this repository into another city's repository,
# then rebuild its pages from its own city.json. City-specific files are never touched:
# city.json, docs/events.json, docs/sources.json.
#
#   scripts/sync_template.sh ../oxfordbops
#
# Run it from the repository that has the newer template. Then review the target's git status,
# run its tests, commit and push there.
set -euo pipefail
cd "$(dirname "$0")/.."
target="${1:?path to the other city repository}"
if [ ! -f "$target/city.json" ]; then
  echo "$target has no city.json; not a bops city repository"
  exit 1
fi
for item in site scripts tests .github LICENSE .gitignore README.md; do
  rm -rf "${target:?}/$item"
  cp -R "$item" "$target/$item"
done
(cd "$target" && python3 scripts/build.py)
if (cd "$target" && python3 -m unittest discover -s tests >/dev/null 2>&1); then
  echo "Template synced into $target; tests pass there."
else
  echo "Template synced into $target; its tests FAIL, run them there to see why."
fi
