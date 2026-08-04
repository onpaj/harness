#!/usr/bin/env bash
# List open `agent` PRs that are mechanically mergeable.
#
# Emits JSON: {"candidates": [...], "skipped": [...], "truncated": N}
#
# Eligibility here is fact, not judgement: a draft or conflicted PR cannot be
# merged by anyone, so it is filtered out before any subagent is spawned.
set -euo pipefail

AGENT_LABEL="agent"
MAX_CANDIDATES=20

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  # Same convention as .claude/skills/applicationinsightsscan/gh-api.sh's
  # detect_repo(): parse `origin` directly rather than relying on gh's own
  # remote-resolution heuristics.
  url=$(git remote get-url origin 2>/dev/null) || { echo "cannot detect repo: no origin remote" >&2; exit 1; }
  case "$url" in
    *github.com*) ;;
    *) echo "cannot detect repo: origin is not a github.com remote" >&2; exit 1 ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  if [ -z "$REPO" ] || [[ "$REPO" != */* ]]; then
    echo "cannot detect repo: could not parse origin URL" >&2; exit 1
  fi
fi

gh pr list \
  --repo "$REPO" \
  --state open \
  --label "$AGENT_LABEL" \
  --limit 100 \
  --json number,title,isDraft,mergeable,reviewDecision,headRefName,additions,deletions,changedFiles \
| jq --argjson max "$MAX_CANDIDATES" '
    def reason:
      if .isDraft then "draft"
      elif .mergeable == "CONFLICTING" then "CONFLICTING (merge conflicts)"
      elif .mergeable == "UNKNOWN" then "UNKNOWN (mergeability not computed, retry)"
      elif .mergeable != "MERGEABLE" then "not mergeable: \(.mergeable)"
      elif .reviewDecision == "CHANGES_REQUESTED" then "CHANGES_REQUESTED"
      else null end;

    (map(select(reason == null))          | sort_by(.number)) as $ok
  | (map(select(reason != null))
      | map({number, reason: reason})     | sort_by(.number)) as $skipped
  | {
      candidates: ($ok[:$max] | map({number, title, additions, changedFiles})),
      skipped: $skipped,
      truncated: (($ok | length) - $max | if . < 0 then 0 else . end)
    }
  '
