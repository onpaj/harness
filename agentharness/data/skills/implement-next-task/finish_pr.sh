#!/usr/bin/env bash
# Finish an implementing issue: undraft its PR, confirm the undraft actually
# took effect, and only then move the issue to its terminal label.
#
#   finish_pr.sh --issue N --branch BRANCH
#
# Emits JSON: {"status": "completed"|"needs-human"|"unconfirmed", "detail": "..."}
# Always exits 0 — the status field is the result, so a caller never has to
# distinguish "the script broke" from "the finish did not go through".
#
# Why this is a script rather than an inline SKILL.md block: undrafting is the
# one step in Finishing with no REST equivalent (GraphQL
# `markPullRequestReadyForReview` only), and it has been observed to return
# cleanly while leaving the PR a draft. The previous inline version applied
# `agent-completed` BEFORE verifying, then retried with `2>/dev/null || true`
# and never re-checked, so a failed undraft produced a fully "complete"-looking
# issue whose PR nobody could merge — and which nothing would ever revisit:
# /automerge-pr and /hygiene-pr both skip drafts by design
# (automerge-pr/candidates.sh: `if .isDraft then "draft"`), and the issue had
# already left the `agent-implementing` pool that would otherwise reclaim it.
#
# The ordering below is the fix: undraft -> verify -> retry -> verify, with the
# terminal label swap gated on a confirmed non-draft PR. A PR still stuck in
# draft sends the issue to `agent-needs-human` and flags the PR `needs-work` —
# the same routing step 6's terminal task-failure branch already uses. A human
# is the only route out: /automerge-pr, /hygiene-pr and /rework-pr all skip
# drafts, so no amount of re-running the pipeline can recover one.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LIB="$SCRIPT_DIR/../_lib/gh_api.sh"

IMPLEMENTING_LABEL="agent-implementing"
COMPLETED_LABEL="agent-completed"
HUMAN_LABEL="agent-needs-human"
NEEDS_WORK_LABEL="needs-work"
STAGE_COLOR="5319e7"
ALERT_COLOR="d93f0b"

ISSUE=""; BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --issue)  ISSUE="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
[ -n "$ISSUE" ]  || { echo "--issue is required" >&2; exit 1; }
[ -n "$BRANCH" ] || { echo "--branch is required" >&2; exit 1; }

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
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

# When USE_GH_API is set every call below routes through the shared curl+REST
# library instead of the `gh` CLI; the logic is identical either way.
emit_json() { jq -cn --arg s "$1" --arg d "$2" '{status:$s, detail:$d}'; }

pr_is_ready() {
  local draft
  if [ -n "${USE_GH_API:-}" ]; then
    draft=$(GH_REPO="$REPO" "$LIB" pr-view "$BRANCH" 2>/dev/null | jq -r '.isDraft')
  else
    draft=$(gh pr view "$BRANCH" --repo "$REPO" --json isDraft --jq '.isDraft' 2>/dev/null)
  fi
  [ "$draft" = "false" ]
}

# Prints whatever the undraft wrote to stderr; its exit code is deliberately
# ignored, because pr_is_ready is the only trustworthy signal either way.
undraft() {
  if [ -n "${USE_GH_API:-}" ]; then
    GH_REPO="$REPO" "$LIB" pr-ready "$BRANCH" 2>&1 >/dev/null
  else
    gh pr ready "$BRANCH" --repo "$REPO" 2>&1 >/dev/null
  fi
}

label_create() {  # name, color, description
  if [ -n "${USE_GH_API:-}" ]; then
    GH_REPO="$REPO" "$LIB" label-create "$1" "$2" "$3" >/dev/null 2>&1 || true
  else
    gh label create "$1" --repo "$REPO" --color "$2" --description "$3" >/dev/null 2>&1 || true
  fi
}

issue_swap() {  # remove-label, add-label
  if [ -n "${USE_GH_API:-}" ]; then
    GH_REPO="$REPO" "$LIB" issue-edit "$ISSUE" --remove-label "$1" --add-label "$2" >/dev/null 2>&1 || true
  else
    gh issue edit "$ISSUE" --repo "$REPO" --remove-label "$1" --add-label "$2" >/dev/null 2>&1 || true
  fi
}

issue_has_label() {  # name
  local names
  if [ -n "${USE_GH_API:-}" ]; then
    names=$(GH_REPO="$REPO" "$LIB" issue-view "$ISSUE" 2>/dev/null | jq -c '[.labels[].name]')
  else
    names=$(gh issue view "$ISSUE" --repo "$REPO" --json labels --jq '[.labels[].name]' 2>/dev/null)
  fi
  [ -n "$names" ] || return 1
  echo "$names" | jq -e --arg l "$1" 'index($l)' >/dev/null 2>&1
}

pr_add_label() {  # name
  if [ -n "${USE_GH_API:-}" ]; then
    GH_REPO="$REPO" "$LIB" pr-edit "$BRANCH" --add-label "$1" >/dev/null 2>&1 || true
  else
    gh pr edit "$BRANCH" --repo "$REPO" --add-label "$1" >/dev/null 2>&1 || true
  fi
}

pr_comment() {  # body
  local f; f=$(mktemp); printf '%s' "$1" > "$f"
  if [ -n "${USE_GH_API:-}" ]; then
    GH_REPO="$REPO" "$LIB" pr-comment "$BRANCH" "$f" >/dev/null 2>&1 || true
  else
    gh pr comment "$BRANCH" --repo "$REPO" --body-file "$f" >/dev/null 2>&1 || true
  fi
  rm -f "$f"
}

# ---- undraft, then prove it ------------------------------------------------

UNDRAFT_ERR=$(undraft)
if ! pr_is_ready; then
  RETRY_ERR=$(undraft)
  [ -n "$RETRY_ERR" ] && UNDRAFT_ERR="${UNDRAFT_ERR:+${UNDRAFT_ERR}; }${RETRY_ERR}"
fi

if ! pr_is_ready; then
  DETAIL="PR on ${BRANCH} is still a draft after two undraft attempts${UNDRAFT_ERR:+: ${UNDRAFT_ERR}}"
  label_create "$NEEDS_WORK_LABEL" "$ALERT_COLOR" "Agent review found blocking problems"
  pr_add_label "$NEEDS_WORK_LABEL"
  label_create "$HUMAN_LABEL" "$ALERT_COLOR" "AgentHarness pipeline stage label"
  issue_swap "$IMPLEMENTING_LABEL" "$HUMAN_LABEL"
  pr_comment "$(printf 'All tasks passed review, but this PR could not be taken out of draft.\n\n```\n%s\n```\n\n/automerge-pr, /hygiene-pr and /rework-pr all skip draft PRs, so nothing downstream would ever pick this up. Issue #%s has been moved to `%s` instead of `%s` so it is not reported as finished — a human needs to undraft the PR (or say why it cannot be).\n' \
    "$DETAIL" "$ISSUE" "$HUMAN_LABEL" "$COMPLETED_LABEL")"
  emit_json "needs-human" "$DETAIL"
  exit 0
fi

# ---- PR confirmed out of draft: the terminal label swap is now safe --------

label_create "$COMPLETED_LABEL" "$STAGE_COLOR" "AgentHarness pipeline stage label"
issue_swap "$IMPLEMENTING_LABEL" "$COMPLETED_LABEL"
if ! issue_has_label "$COMPLETED_LABEL"; then
  issue_swap "$IMPLEMENTING_LABEL" "$COMPLETED_LABEL"
fi
if ! issue_has_label "$COMPLETED_LABEL"; then
  emit_json "unconfirmed" "PR on ${BRANCH} is out of draft, but issue #${ISSUE} could not be moved to ${COMPLETED_LABEL}"
  exit 0
fi

emit_json "completed" "PR on ${BRANCH} is out of draft and issue #${ISSUE} is ${COMPLETED_LABEL}"
