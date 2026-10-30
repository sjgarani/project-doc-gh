#!/usr/bin/env bash
# Merges a source branch (default: devel) into 'main' while always ignoring 'doc/', 'test/', and 'tests/'.

set -euo pipefail

SOURCE_BRANCH="${1:-devel}"
CURRENT_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
EXCLUDED_DIRS=(doc test tests)

if [ "${CURRENT_BRANCH}" != "main" ]; then
  echo "Error: tools/merge-to-main.sh must be run from the 'main' branch (current: '${CURRENT_BRANCH}')." >&2
  exit 1
fi

echo "Merging '${SOURCE_BRANCH}' into 'main' (excluding doc/, test/, tests/)..."
git merge --no-commit --no-ff "${SOURCE_BRANCH}" || true

for dir in "${EXCLUDED_DIRS[@]}"; do
  git rm -rf --quiet --ignore-unmatch "${dir}"
  rm -rf "${dir}"
done

if git rev-parse -q --verify HEAD:.gitignore >/dev/null 2>&1; then
  git checkout HEAD -- .gitignore
fi

UNMERGED="$(git diff --name-only --diff-filter=U)"
if [ -n "${UNMERGED}" ]; then
  echo "Error: Merge conflicts remain outside excluded directories:" >&2
  echo "${UNMERGED}" >&2
  exit 1
fi

if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
  if git diff --cached --quiet; then
    git merge --abort
    echo "No changes to merge into 'main' (only excluded directories changed)."
  else
    git commit --no-edit
    echo "Merge into 'main' completed without doc/, test/, tests/."
  fi
else
  echo "Already up to date."
fi
