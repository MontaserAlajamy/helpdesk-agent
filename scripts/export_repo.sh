#!/usr/bin/env bash
# Create a standalone git history for helpdesk-agent from the monorepo.
#
# Usage (run from anywhere; the script moves to the monorepo root):
#   scripts/export_repo.sh
# It creates the local branch `helpdesk-agent-export` containing only the history of helpdesk-agent/ at the root.
# Then, by hand:
#   git remote add helpdesk-agent git@github.com:OWNER/helpdesk-agent.git   # an empty, new GitHub repo
#   git push helpdesk-agent helpdesk-agent-export:main
# This script never pushes.
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"
if [ ! -d helpdesk-agent ]; then
  echo "run from a monorepo that contains helpdesk-agent/ (looked in $ROOT)" >&2
  exit 1
fi
if git show-ref --verify --quiet refs/heads/helpdesk-agent-export; then
  echo "branch helpdesk-agent-export exists; delete it first: git branch -D helpdesk-agent-export" >&2
  exit 1
fi
git subtree split --prefix=helpdesk-agent -b helpdesk-agent-export
echo
echo "Done. Next, in $ROOT:"
echo "  git remote add helpdesk-agent git@github.com:OWNER/helpdesk-agent.git"
echo "  git push helpdesk-agent helpdesk-agent-export:main"
