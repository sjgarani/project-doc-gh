#!/usr/bin/env bash
# Configures Git hooks and merge options for managing the devel -> main workflow.

set -euo pipefail

git config core.hooksPath .githooks
git config merge.ours.driver true
git config branch.main.mergeoptions "--no-ff --no-edit"
git config branch.devel.mergeoptions "--no-ff --no-edit"
git config alias.merge-to-main '!bash tools/merge-to-main.sh'

# Ensure 'git subtree' is available even if active git exec-path lacks git-subtree
if ! [ -x "$(git --exec-path)/git-subtree" ]; then
  if [ -x "/usr/lib/git-core/git-subtree" ]; then
    git config alias.subtree '!/usr/lib/git-core/git-subtree'
  elif [ -f "/usr/share/doc/git/contrib/subtree/git-subtree.sh" ]; then
    git config alias.subtree '!sh /usr/share/doc/git/contrib/subtree/git-subtree.sh'
  fi
fi

echo "Configured git core.hooksPath='.githooks', merge.ours.driver='true', mergeoptions='--no-ff --no-edit', alias 'git merge-to-main', and 'git subtree'."
