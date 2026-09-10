#!/usr/bin/env bash
# _lib/lease.sh — a real, cross-machine mutual-exclusion lease for pipeline
# stages, stored as a git ref on `origin`.
#
# WHY THIS EXISTS
# ---------------
# `implement-next-task/find_candidate.sh` used to decide "is another worker
# still on this issue?" purely from the age of the last commit on the
# feature branch. That is not a liveness signal: a single unit of work
# (notably a full build+test verification pass) routinely runs far longer
# than the staleness window without committing anything, so a perfectly
# healthy worker was declared abandoned and its issue handed to a second
# worker. The `agent-implementing` label could not prevent it either --
# `gh issue edit` has no compare-and-set, and the stale-reclaim path
# deliberately ignores the label anyway.
#
# WHY A GIT REF
# -------------
# A ref update on the server is genuinely atomic and gives us
# compare-and-set for free, which no GitHub label or issue comment does:
#
#   * Creating `refs/agent-leases/<id>` when it does not exist: two racers
#     both push; the first wins, the second's push is no longer a create
#     and is not a fast-forward, so the server rejects it.
#   * Taking over an expired lease: the new lease commit is parented on the
#     exact sha we read, so the push is a fast-forward only if nobody else
#     moved the ref in between. Two thieves cannot both win.
#
# It also works identically with or without the `gh` CLI (unlike everything
# else in _lib/), and it never touches the feature branch's own history.
#
# The lease payload is the commit message of an empty-tree commit:
#   {"lease_id","holder","acquired_at","expires_at","ttl_minutes"}
#
# HOLDER IDENTITY
# ---------------
# A skill acquires in one shell and releases in another (each bash block a
# skill runs is its own process), so an exported environment variable
# cannot carry the holder id between them. `acquire` therefore records the
# id it used under the repo's git common dir, and `renew`/`release` read it
# back from there.
#
# Note the asymmetry, which is deliberate: `acquire` NEVER reads that file.
# If it did, a second worker starting in the same checkout would adopt the
# first worker's identity, mistake its live lease for its own, and take it
# over -- precisely the collision this library exists to stop. A fresh
# acquire always mints a fresh id and so is always correctly refused.
#
# AGENT_LEASE_HOLDER overrides both mechanisms when set.
#
# TTL
# ---
# There is no background heartbeat: a skill runs one bounded unit inside a
# single blocking agent call and cannot refresh a lease mid-call. So the
# TTL must exceed the longest single unit -- default 120 minutes. If a
# worker dies, its lease self-expires after the TTL and the work is
# reclaimable; that delay is the deliberate price of not needing a daemon.
#
# Usage:
#   lease.sh acquire <lease-id> [ttl-minutes]   # 0 acquired, 3 held by other
#   lease.sh renew   <lease-id> [ttl-minutes]   # 0 renewed,  3 lost
#   lease.sh release <lease-id>                 # 0 released/absent, 3 not ours,
#                                               # 1 origin unreachable
#   lease.sh status  <lease-id>                 # 0, prints JSON
set -euo pipefail

REF_PREFIX="refs/agent-leases"
DEFAULT_TTL_MINUTES="${LEASE_TTL_MINUTES:-120}"

# Exit code meaning "someone else holds this lease" -- distinct from 1
# (usage/plumbing error) so callers can branch on contention alone.
EXIT_HELD=3

die() { echo "lease.sh: $*" >&2; exit 1; }

# Where `acquire` records the identity it used, so a later shell's
# `renew`/`release` can recognise the lease as this invocation's own. Lives
# under the git COMMON dir so every worktree of the checkout agrees on it.
holder_file() {  # lease-id
  local common
  common="$(git rev-parse --git-common-dir 2>/dev/null)" || return 1
  # `--git-common-dir` answers relative to the CURRENT directory, so the
  # same checkout yields ".git" from the root and "../.git" one level down.
  # Both resolve to the same file today only because every caller uses the
  # answer without changing directory first; absolutising it removes that
  # unwritten precondition.
  case "$common" in
    /*) ;;
    *) common="$(cd "$common" 2>/dev/null && pwd)" || return 1 ;;
  esac
  echo "${common}/agentharness-leases/$1"
}

# Mint a brand-new identity. Only `acquire` may use this.
new_holder_id() {
  local host
  host="$(hostname -s 2>/dev/null || echo unknown)"
  echo "${host}-$$-$(date -u +%s)-${RANDOM}"
}

# The identity to acquire under: an explicit override, else always a fresh
# one. Never the recorded file -- see HOLDER IDENTITY above.
acquire_holder_id() {
  if [[ -n "${AGENT_LEASE_HOLDER:-}" ]]; then echo "$AGENT_LEASE_HOLDER"; return; fi
  new_holder_id
}

# The identity to renew/release under: an explicit override, else whatever
# `acquire` recorded. Falling back to a fresh id when neither exists is
# safe -- it simply will not match, and the operation is refused.
current_holder_id() {
  local f
  if [[ -n "${AGENT_LEASE_HOLDER:-}" ]]; then echo "$AGENT_LEASE_HOLDER"; return; fi
  f="$(holder_file "$1")" || { new_holder_id; return; }
  if [[ -f "$f" ]]; then cat "$f"; return; fi
  new_holder_id
}

record_holder_id() {  # lease-id, holder
  local f
  f="$(holder_file "$1")" || return 0
  mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
  printf '%s' "$2" > "$f" 2>/dev/null || true
}

# The recorded id as it stands right now, or nothing. Used only to put it
# back when an acquire we optimistically recorded turns out to have lost.
read_holder_record() {  # lease-id
  local f
  f="$(holder_file "$1")" || return 0
  [[ -f "$f" ]] || return 0
  cat "$f" 2>/dev/null || true
}

restore_holder_id() {  # lease-id, previous-record ("" means there was none)
  if [[ -n "$2" ]]; then record_holder_id "$1" "$2"; else forget_holder_id "$1"; fi
}

forget_holder_id() {  # lease-id
  local f
  f="$(holder_file "$1")" || return 0
  rm -f "$f" 2>/dev/null || true
}

# Current time as epoch seconds. LEASE_NOW_OVERRIDE (ISO 8601 Zulu) exists
# so tests can drive expiry deterministically instead of sleeping.
now_epoch() {
  if [[ -n "${LEASE_NOW_OVERRIDE:-}" ]]; then
    iso_to_epoch "$LEASE_NOW_OVERRIDE"
    return
  fi
  date -u +%s
}

# ISO 8601 Zulu -> epoch seconds, on both GNU date (Linux) and BSD date
# (macOS). Prints nothing and returns non-zero if unparseable.
iso_to_epoch() {
  local iso="$1" out
  out="$(date -u -d "$iso" +%s 2>/dev/null)" \
    || out="$(date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso" +%s 2>/dev/null)" \
    || return 1
  echo "$out"
}

# epoch seconds -> ISO 8601 Zulu, on both GNU and BSD date.
epoch_to_iso() {
  local e="$1"
  date -u -d "@$e" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -r "$e" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || return 1
}

# Refresh the local mirror of the remote lease ref, setting LEASE_SHA to
# its sha (empty when no lease exists remotely) and LEASE_FETCH_OK to
# whether we actually managed to ask origin at all.
#
# That second signal matters: a fetch also fails when the ref simply is not
# there, and folding both outcomes into "absent" would let a network blip
# read as "nobody holds this" -- harmless for `acquire` (the CAS push still
# rejects a double-acquire) but not for `release`, which would report a
# successful release of a lease it never touched. So the ambiguous case is
# disambiguated with one extra probe, and only when the fetch failed.
#
# CALL THIS AS A PLAIN STATEMENT, never inside `$(...)`: the globals it
# sets would be discarded along with the subshell.
#
# The local ref is deleted FIRST so that a lease released on another
# machine cannot linger here and make an absent lease look held.
LEASE_FETCH_OK=1
fetch_lease_ref() {
  local ref="$1"
  LEASE_SHA=""
  git update-ref -d "$ref" 2>/dev/null || true
  if git fetch --quiet origin "+${ref}:${ref}" 2>/dev/null; then
    LEASE_FETCH_OK=1
  elif git ls-remote origin >/dev/null 2>&1; then
    # Origin answered, so the ref genuinely is not there. (No --exit-code:
    # a reachable repo with no refs at all must still count as reachable.)
    LEASE_FETCH_OK=1
  else
    LEASE_FETCH_OK=0
    return
  fi
  LEASE_SHA="$(git rev-parse --verify --quiet "$ref" 2>/dev/null || true)"
}

# Echo the lease JSON stored in a lease commit's message.
read_lease_payload() {
  git log -1 --format=%B "$1" 2>/dev/null | head -1
}

# Build a lease commit and push it to the remote ref.
#
# `parent_sha` is the sha we believe the ref currently points at (empty for
# a create). Parenting on exactly that sha is what makes the push a
# compare-and-set: if anyone moved the ref since we read it, our push is
# neither a create nor a fast-forward and the server rejects it.
push_lease() {
  local ref="$1" parent_sha="$2" payload="$3" tree commit
  tree="$(git hash-object -w -t tree /dev/null)" || die "could not write empty tree"

  # commit-tree refuses to run without an identity; supply one rather than
  # depending on the ambient git config of whatever machine this runs on.
  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-agentharness}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-agentharness@localhost}"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-agentharness}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-agentharness@localhost}"

  if [[ -n "$parent_sha" ]]; then
    commit="$(git commit-tree "$tree" -p "$parent_sha" -m "$payload")" || return 1
  else
    commit="$(git commit-tree "$tree" -m "$payload")" || return 1
  fi
  git push --quiet origin "${commit}:${ref}" 2>/dev/null || return 1
  git update-ref "$ref" "$commit" 2>/dev/null || true
  echo "$commit"
}

make_payload() {
  local lease_id="$1" holder="$2" ttl="$3" acquired="$4" expires="$5"
  jq -nc \
    --arg lease_id "$lease_id" --arg holder "$holder" \
    --arg acquired_at "$acquired" --arg expires_at "$expires" \
    --argjson ttl_minutes "$ttl" \
    '{lease_id: $lease_id, holder: $holder, acquired_at: $acquired_at,
      expires_at: $expires_at, ttl_minutes: $ttl_minutes}'
}

validate_ttl() {
  [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -gt 0 ] \
    || die "ttl-minutes must be a positive integer, got: $1"
}

validate_lease_id() {
  # Keep the id to characters that are unambiguously safe in a ref name.
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]] \
    || die "lease-id must match [A-Za-z0-9._-]+, got: $1"
}

# Populate LEASE_STATE ("held"/"expired"/"absent"/"unknown") plus the sha, payload,
# holder and expiry of the current lease.
#
# CALL THIS AS A PLAIN STATEMENT, never as `x="$(inspect_lease ...)"`: a
# command substitution runs the function in a subshell, and every global it
# sets is discarded when that subshell exits -- which silently yields a
# correct state with an empty holder.
LEASE_STATE=""
LEASE_SHA=""
LEASE_PAYLOAD=""
LEASE_HOLDER=""
LEASE_EXPIRES=""
inspect_lease() {
  local ref="$1" now exp_epoch
  fetch_lease_ref "$ref"
  if [[ -z "$LEASE_SHA" ]]; then
    LEASE_PAYLOAD=""; LEASE_HOLDER=""; LEASE_EXPIRES=""
    # "unknown" is deliberately not "absent": we did not learn that nobody
    # holds this lease, only that we could not find out.
    if [ "$LEASE_FETCH_OK" -eq 0 ]; then LEASE_STATE="unknown"; else LEASE_STATE="absent"; fi
    return
  fi
  LEASE_PAYLOAD="$(read_lease_payload "$LEASE_SHA")"
  LEASE_HOLDER="$(echo "$LEASE_PAYLOAD" | jq -r '.holder // ""' 2>/dev/null || echo "")"
  LEASE_EXPIRES="$(echo "$LEASE_PAYLOAD" | jq -r '.expires_at // ""' 2>/dev/null || echo "")"

  # A lease we cannot parse is treated as expired rather than as a
  # permanent roadblock -- a corrupt payload must never wedge the pipeline
  # forever, and the CAS push still keeps the takeover safe.
  if [[ -z "$LEASE_EXPIRES" ]]; then LEASE_STATE="expired"; return; fi
  exp_epoch="$(iso_to_epoch "$LEASE_EXPIRES")" || { LEASE_STATE="expired"; return; }
  now="$(now_epoch)"
  if [ "$now" -ge "$exp_epoch" ]; then LEASE_STATE="expired"; else LEASE_STATE="held"; fi
}

cmd_acquire() {
  local lease_id="${1:-}" ttl="${2:-$DEFAULT_TTL_MINUTES}"
  [[ -n "$lease_id" ]] || die "usage: lease.sh acquire <lease-id> [ttl-minutes]"
  validate_lease_id "$lease_id"; validate_ttl "$ttl"

  local ref="${REF_PREFIX}/${lease_id}" me now acquired expires payload prev_record
  me="$(acquire_holder_id)"
  inspect_lease "$ref"

  # Cannot see origin, so cannot know whether anyone holds this. Refusing
  # is the only safe answer; the push would fail immediately anyway.
  if [[ "$LEASE_STATE" == "unknown" ]]; then
    jq -nc '{acquired: false, reason: "could not reach origin to read the lease"}'
    return $EXIT_HELD
  fi

  # An unexpired lease belonging to someone else is the whole point: stop.
  if [[ "$LEASE_STATE" == "held" && "$LEASE_HOLDER" != "$me" ]]; then
    jq -nc --arg holder "$LEASE_HOLDER" --arg expires_at "$LEASE_EXPIRES" \
      '{acquired: false, holder: $holder, expires_at: $expires_at}'
    return $EXIT_HELD
  fi

  now="$(now_epoch)"
  acquired="$(epoch_to_iso "$now")"
  expires="$(epoch_to_iso "$((now + ttl * 60))")"
  payload="$(make_payload "$lease_id" "$me" "$ttl" "$acquired" "$expires")"

  # Record BEFORE pushing. Die in the gap between a push that landed and
  # the record of it, and the lease exists remotely with nothing locally
  # able to name itself as its holder -- so nothing can release it before
  # its TTL runs out. Recording first cannot cause the opposite error: the
  # id is checked against the remote holder either way, and a lost race
  # simply puts the previous record back.
  prev_record="$(read_holder_record "$lease_id")"
  record_holder_id "$lease_id" "$me"
  if ! push_lease "$ref" "$LEASE_SHA" "$payload" >/dev/null; then
    # Rejected push == another worker moved the ref between our read and
    # our write. Losing this race is a normal outcome, not an error.
    restore_holder_id "$lease_id" "$prev_record"
    jq -nc '{acquired: false, holder: "unknown", reason: "lost the race to acquire"}'
    return $EXIT_HELD
  fi
  echo "$payload"
}

cmd_renew() {
  local lease_id="${1:-}" ttl="${2:-$DEFAULT_TTL_MINUTES}"
  [[ -n "$lease_id" ]] || die "usage: lease.sh renew <lease-id> [ttl-minutes]"
  validate_lease_id "$lease_id"; validate_ttl "$ttl"

  local ref="${REF_PREFIX}/${lease_id}" me now expires payload
  me="$(current_holder_id "$lease_id")"
  inspect_lease "$ref"

  # "We lost the lease" and "the network blipped" call for very different
  # reactions from the caller, so never dress the second up as the first.
  if [[ "$LEASE_STATE" == "unknown" ]]; then
    jq -nc '{renewed: false, reason: "could not reach origin to renew the lease"}'
    return $EXIT_HELD
  fi

  # Renewing is only meaningful while we still hold it. If the lease is
  # gone or already stolen, say so instead of silently re-acquiring -- the
  # caller may have been working without exclusivity and needs to know.
  if [[ "$LEASE_STATE" == "absent" || "$LEASE_HOLDER" != "$me" ]]; then
    jq -nc --arg holder "${LEASE_HOLDER:-}" \
      '{renewed: false, holder: $holder, reason: "lease is no longer ours"}'
    return $EXIT_HELD
  fi

  now="$(now_epoch)"
  expires="$(epoch_to_iso "$((now + ttl * 60))")"
  payload="$(make_payload "$lease_id" "$me" "$ttl" \
    "$(echo "$LEASE_PAYLOAD" | jq -r '.acquired_at // ""')" "$expires")"

  if ! push_lease "$ref" "$LEASE_SHA" "$payload" >/dev/null; then
    jq -nc '{renewed: false, reason: "lost the race to renew"}'
    return $EXIT_HELD
  fi
  echo "$payload"
}

cmd_release() {
  local lease_id="${1:-}"
  [[ -n "$lease_id" ]] || die "usage: lease.sh release <lease-id>"
  validate_lease_id "$lease_id"

  local ref="${REF_PREFIX}/${lease_id}" me
  me="$(current_holder_id "$lease_id")"
  inspect_lease "$ref"

  # Reporting `released: true` without having reached origin would tell the
  # caller the lease is free when it in fact stays held until its TTL runs
  # out -- and would discard the identity a retry needs.
  if [[ "$LEASE_STATE" == "unknown" ]]; then
    jq -nc '{released: false, reason: "could not reach origin to release the lease"}'
    return 1
  fi
  if [[ "$LEASE_STATE" == "absent" ]]; then
    forget_holder_id "$lease_id"
    jq -nc '{released: true, reason: "no lease to release"}'
    return 0
  fi
  # Never delete a lease someone else holds -- that would hand their work
  # to a third worker, which is the exact failure this library prevents.
  if [[ "$LEASE_HOLDER" != "$me" && "$LEASE_STATE" == "held" ]]; then
    jq -nc --arg holder "$LEASE_HOLDER" \
      '{released: false, holder: $holder, reason: "lease is held by another worker"}'
    return $EXIT_HELD
  fi
  # The delete is a compare-and-set like every other write here. A plain
  # `push origin :ref` deletes whatever the ref points at *now*, which in
  # the window between the read above and this push may already be a SECOND
  # worker's freshly and legitimately acquired lease -- wiping it while it
  # believes it holds exclusivity, and freeing a third worker to acquire.
  # Naming the sha we read makes the server refuse exactly that case.
  if ! git push --quiet --force-with-lease="${ref}:${LEASE_SHA}" \
        origin --delete "${ref}" 2>/dev/null; then
    # Either the ref moved under us or origin went away. Find out which,
    # and never claim a release that did not happen.
    inspect_lease "$ref"
    if [[ "$LEASE_STATE" == "absent" ]]; then
      git update-ref -d "$ref" 2>/dev/null || true
      forget_holder_id "$lease_id"
      jq -nc '{released: true, reason: "lease was already gone"}'
      return 0
    fi
    if [[ "$LEASE_STATE" == "unknown" ]]; then
      jq -nc '{released: false, reason: "could not reach origin to release the lease"}'
      return 1
    fi
    forget_holder_id "$lease_id"
    jq -nc --arg holder "$LEASE_HOLDER" \
      '{released: false, holder: $holder,
        reason: "lease was taken over before we could release it"}'
    return $EXIT_HELD
  fi
  git update-ref -d "$ref" 2>/dev/null || true
  forget_holder_id "$lease_id"
  jq -nc '{released: true}'
}

cmd_status() {
  local lease_id="${1:-}"
  [[ -n "$lease_id" ]] || die "usage: lease.sh status <lease-id>"
  validate_lease_id "$lease_id"

  local ref="${REF_PREFIX}/${lease_id}"
  inspect_lease "$ref"
  local fetch_ok=false
  [ "$LEASE_FETCH_OK" -eq 1 ] && fetch_ok=true
  jq -nc --arg state "$LEASE_STATE" --arg holder "${LEASE_HOLDER:-}" \
    --arg expires_at "${LEASE_EXPIRES:-}" --argjson fetch_ok "$fetch_ok" \
    '{state: $state, held: ($state == "held"), holder: $holder,
      expires_at: $expires_at, fetch_ok: $fetch_ok}'
}

command -v jq >/dev/null 2>&1 || die "jq is required"

case "${1:-}" in
  acquire) shift; cmd_acquire "$@" ;;
  renew)   shift; cmd_renew "$@" ;;
  release) shift; cmd_release "$@" ;;
  status)  shift; cmd_status "$@" ;;
  *)
    cat >&2 <<'USAGE'
usage: lease.sh <command> [args]

  acquire <lease-id> [ttl-minutes]   take the lease (exit 3 if held by another)
  renew   <lease-id> [ttl-minutes]   extend a lease we hold (exit 3 if lost)
  release <lease-id>                 drop a lease we hold (exit 3 if not ours)
  status  <lease-id>                 print {state, held, holder, expires_at, fetch_ok}

`acquire` records the identity it used under the git common dir, so a
later renew/release in a DIFFERENT shell recognises the lease as its own
with no environment passing. Set AGENT_LEASE_HOLDER to override.
USAGE
    exit 1 ;;
esac
