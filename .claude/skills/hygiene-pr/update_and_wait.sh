#!/usr/bin/env bash
# Bring one PR's branch current with its base branch and wait for CI to
# resolve. Never touches labels, comments, or merge state — only reads, and
# if needed, runs `gh pr update-branch`.
#
#   update_and_wait.sh --pr N
#
# Emits JSON: {"pr": N, "status": "already-clean|fixed|still-failing|
#              conflict|pending-timeout", "detail": "..."}
# Always exits 0 — this script reports, it never fails the caller.
set -uo pipefail

POLL_INTERVAL_SECONDS="${HYGIENE_POLL_INTERVAL_SECONDS:-15}"
POLL_MAX_ATTEMPTS="${HYGIENE_POLL_MAX_ATTEMPTS:-40}"

PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pr) PR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

[ -n "$PR" ] || { echo "--pr is required" >&2; exit 1; }

report() {  # status, detail
  jq -n --argjson pr "$PR" --arg status "$1" --arg detail "$2" \
    '{pr: $pr, status: $status, detail: $detail}'
}

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  # Same convention as automerge-pr/candidates.sh's detect_repo().
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

# Normalizes statusCheckRollup (a mix of CheckRun and legacy StatusContext
# objects) into one overall state: "success" | "failure" | "pending" | "none".
CI_STATE_FILTER='
  def check_state:
    if .__typename == "StatusContext" then
      (if .state == "SUCCESS" then "success"
       elif .state == "PENDING" then "pending"
       else "failure" end)
    else
      (if .status != "COMPLETED" then "pending"
       elif (.conclusion == "SUCCESS" or .conclusion == "NEUTRAL" or .conclusion == "SKIPPED") then "success"
       else "failure" end)
    end;
  def ci_state:
    if length == 0 then "none"
    else (map(check_state)) as $s
      | if ($s | any(. == "failure")) then "failure"
        elif ($s | any(. == "pending")) then "pending"
        else "success" end
    end;
'

read_state() {
  gh pr view "$PR" --repo "$REPO" \
    --json mergeable,mergeStateStatus,statusCheckRollup \
  | jq -r "$CI_STATE_FILTER"' [.mergeable, .mergeStateStatus, (.statusCheckRollup | ci_state)] | @tsv'
}

IFS=$'\t' read -r mergeable merge_state ci_state < <(read_state)

is_behind=false
[ "$merge_state" = "BEHIND" ] && is_behind=true
is_conflicting=false
[ "$mergeable" = "CONFLICTING" ] && is_conflicting=true

if ! $is_behind && ! $is_conflicting; then
  case "$ci_state" in
    success|none)
      report "already-clean" "branch is current, checks are $ci_state"; exit 0 ;;
    failure)
      report "still-failing" "branch is current with base, but checks are failing"; exit 0 ;;
    pending)
      : # already current — fall through to the poll loop without updating
      ;;
  esac
else
  if ! update_err=$(gh pr update-branch "$PR" --repo "$REPO" 2>&1); then
    report "conflict" "gh pr update-branch failed: $update_err"; exit 0
  fi
fi

attempt=0
while [ "$attempt" -lt "$POLL_MAX_ATTEMPTS" ]; do
  IFS=$'\t' read -r mergeable merge_state ci_state < <(read_state)
  case "$ci_state" in
    success|none)
      report "fixed" "branch updated/current, checks are $ci_state"; exit 0 ;;
    failure)
      report "still-failing" "branch is current with base, but checks are failing"; exit 0 ;;
  esac
  attempt=$((attempt + 1))
  [ "$attempt" -lt "$POLL_MAX_ATTEMPTS" ] && sleep "$POLL_INTERVAL_SECONDS"
done

report "pending-timeout" "checks still running after $POLL_MAX_ATTEMPTS polls"
