# Design: `/automerge` — autonomous merge of high-confidence agent PRs

Date: 2026-08-04
Status: approved for planning

## Problem

The AgentHarness pipeline opens a PR for every issue it completes. Every one of
those PRs currently waits for a human to read it and press merge, even when the
change is trivial (docs, a one-line fix, a test addition). That human step is the
bottleneck in an otherwise autonomous pipeline.

We want a skill that scans the open PRs the pipeline produced, judges each one,
and merges the ones it is confident about — without asking anyone.

## Scope

**In scope:** open PRs created by the AgentHarness pipeline, identified by the
`agent` label on the PR.

**Out of scope:** human-authored PRs, draft PRs, PRs with merge conflicts, PRs
with requested changes. These are never candidates and are never touched.

**Explicitly not doing:** running the test suite. The reviewer judges from the
diff, the linked issue, and surrounding code only. This is a deliberate
trade-off for speed and cost, and it is the main risk this design carries — see
*Risks*.

## Architecture

```
/automerge
   |
   |-- 1. candidates.sh        ->  candidate set + skip reasons (single API call)
   |
   |-- 2. fan out: one code-reviewer subagent per candidate PR
   |        (all spawned in one message, run concurrently, fresh context each)
   |        subagents are READ-ONLY: they score, they never merge
   |
   |-- 3. parse_verdict.py     ->  validated verdict + the action to take
   |
   `-- 4. apply_verdict.sh     ->  executes that action, serially, per PR
            merge        ->  comment review, squash merge, delete branch, label issue
            comment      ->  comment review, leave PR open
            needs-work   ->  comment review, add `needs-work` label
```

### Deterministic work lives in scripts, not in the prompt

Only step 2 — reading a diff and forming a judgement — needs a model. Steps 1,
3 and 4 are pure mechanism: an API query with a filter, a parse with
validation, and a fixed sequence of `gh` calls. Those go in scripts beside
`SKILL.md`, following the `applicationinsightsscan` pattern.

This matters for more than tidiness. A model that re-derives the band boundary
or the merge command on every run will eventually derive it differently; a
script does the same thing every time, can be unit-tested, and can be read by a
human deciding whether to trust this thing with `master`.

| Script | Language | Responsibility |
|--------|----------|----------------|
| `candidates.sh` | bash + `gh` + `jq` | List open `agent` PRs, apply the mechanical filter, emit candidates and skip reasons as JSON |
| `parse_verdict.py` | Python, stdlib only | Parse the subagent's output block, validate it, decide the band, emit normalized JSON |
| `apply_verdict.sh` | bash + `gh` | Execute one action for one PR; report failure without aborting |

**The band thresholds live in exactly one place: `parse_verdict.py`.** It emits
an `action` field, and `apply_verdict.sh` executes the action it is handed
without knowing what a score is. Duplicating the boundary across a script and a
prompt is how the two drift apart.

The split matters: the subagent produces a **judgement**, the parent holds
**authority**. No subagent can merge anything, so a prompt-injected or confused
reviewer cannot write to `master` — the worst it can do is return a wrong score
that the parent then acts on.

### Why one subagent per PR

Each PR gets a clean context containing only its own diff and issue. Reviewing
five PRs in one context lets an earlier PR's reasoning bleed into a later PR's
score, and blows the context budget on large diffs. Concurrency also makes the
wall-clock cost roughly that of the single largest PR rather than the sum.

## Component 1: Candidate selection — `candidates.sh`

Run once, in the parent:

```bash
.claude/skills/automerge/candidates.sh
```

Internally a single `gh` call plus a `jq` filter:

```bash
gh pr list --state open --label agent --limit 100 \
  --json number,title,isDraft,mergeable,reviewDecision,headRefName,additions,deletions,changedFiles
```

Output is JSON on stdout, so the model never re-implements the filter:

```json
{
  "candidates": [ { "number": 129, "title": "…", "changedFiles": 2 } ],
  "skipped":    [ { "number": 112, "reason": "CONFLICTING" } ],
  "truncated":  0
}
```

The repo is auto-detected from the `origin` remote, matching `gh-api.sh` in
`applicationinsightsscan`; override with `GH_REPO=owner/repo`.

A PR is a candidate only if **all** of these hold:

| Condition | Value |
|-----------|-------|
| `isDraft` | `false` |
| `mergeable` | `"MERGEABLE"` |
| `reviewDecision` | not `"CHANGES_REQUESTED"` |
| `agent` label | present (guaranteed by the `--label agent` filter) |

These are mechanical facts, not scoring inputs. A draft or conflicted PR cannot
be merged by anyone, so it is filtered out before a subagent is spawned — no
tokens are spent on it. Filtered PRs are listed in the final report under
`skipped`, with the reason, so nothing disappears silently.

`mergeable` is `"UNKNOWN"` when GitHub has not finished computing mergeability.
Treat `UNKNOWN` as not-a-candidate and report it as `skipped (mergeability not
computed, retry)` — do not poll or wait.

If the candidate set is empty, print `No agent PRs ready to review.` and stop.

## Component 2: The reviewer subagent

One `code-reviewer` subagent per candidate PR, all spawned in a single message
so they run concurrently.

**Tools available to it:** `Read`, `Grep`, `Glob`, `Bash`. Its Bash use is
limited to read-only `gh` calls and local file inspection. The prompt states
explicitly: *you must not run `gh pr merge`, `gh pr close`, `git push`, or any
other state-changing command.*

**Input given to the subagent:** the PR number, and the rubric below.

**What it gathers itself:**

```bash
gh pr view {N} --json title,body,headRefName,additions,deletions,changedFiles
gh pr diff {N}
gh issue view {linked_issue} --json title,body    # issue number parsed from PR body
```

Plus `Read`/`Grep` on the repo to check whether the change fits the code around
it.

### Rubric

The subagent scores 0-100. It starts from 100 and deducts:

| Signal | Deduction |
|--------|-----------|
| Diff does something the linked issue did not ask for | -40 |
| No linked issue found in the PR body | -30 |
| New behaviour added with no accompanying test | -25 |
| Touches concurrency-critical code (`state_manager.py`, blob-lease or claim logic) | -30 |
| Touches auth, secrets handling, or `.github/workflows/` | -30 |
| Hardcoded secret, credential, or leftover debug statement | -100 (forces REJECT) |
| Diff exceeds 400 added lines or 10 changed files | -20 |
| Developer summary claims work the diff does not contain | -50 |
| Any change whose correctness the reviewer cannot verify from the diff alone | -25 |

The last row is the calibration anchor: **uncertainty must cost score.** A
reviewer that cannot tell whether a change is correct has, by definition, low
confidence, and the rubric must force that to show up as a number below the
threshold rather than an optimistic guess.

### Output contract

The subagent's final message must end with exactly this block, and nothing after
it:

```
pr: 129
score: 94
verdict: MERGE
risk: low
reasons:
  - diff is docs-only, 2 files, matches linked issue #118 exactly
  - no runtime code paths touched
concerns: none
```

- `verdict` is derived from `score`, not chosen independently, and maps
  one-to-one onto the action the parent takes:

  | `score` | subagent `verdict` | parent `action` |
  |---------|--------------------|-----------------|
  | >= 80 | `MERGE` | `merge` |
  | 40-79 | `COMMENT` | `comment` |
  | < 40 | `REJECT` | `needs-work` |

- `risk` is `low` | `medium` | `high`, free judgement, informational only.
- `reasons` is 2-5 bullets, each a specific fact about this diff. Generic
  statements ("code looks good") are not acceptable.
- `concerns` is `none` or a list of what a human should look at.

## Component 3: Verdict parsing — `parse_verdict.py`

The subagent's raw output is piped in on stdin; normalized JSON comes out:

```bash
echo "$SUBAGENT_OUTPUT" | .claude/skills/automerge/parse_verdict.py
```

```json
{ "pr": 129, "score": 94, "action": "merge", "risk": "low",
  "reasons": ["…"], "concerns": "none", "valid": true }
```

Validation rules, all enforced in the script:

- The block must be the last block in the output and contain `pr`, `score`,
  `verdict`, `reasons`.
- `score` must be an integer 0-100. Anything else is invalid.
- `action` is computed **from `score` only**. The subagent's own `verdict`
  string is compared against the computed action and a mismatch marks the
  verdict invalid — a reviewer that says `MERGE` at score 30 is confused, and
  confusion must not merge.
- Any failure yields `{"valid": false, "score": 0, "action": "comment"}` plus
  the reason. **A malformed review never merges.**

Band boundaries (`MERGE_THRESHOLD = 80`, `NEEDS_WORK_THRESHOLD = 40`) are
constants at the top of this file and nowhere else.

## Component 4: Acting on verdicts — `apply_verdict.sh`

The parent calls the script once per PR, **serially**, in ascending PR number,
so two merges never race on `master`:

```bash
.claude/skills/automerge/apply_verdict.sh --pr 129 --action merge --review-file /tmp/review-129.md
```

The script takes the action as an argument and does not compute it. For every
PR regardless of action, it first posts the review as a comment — the audit
trail for why the bot did what it did:

```bash
gh pr comment {N} --body-file "$REVIEW_FILE"
```

Then, by action:

**`merge`**

```bash
gh pr merge {N} --squash --delete-branch
gh issue edit {linked_issue} --add-label agent-merged
```

Squash keeps `master` history one-commit-per-feature, matching the existing
history and the semantic-release setup. `--delete-branch` keeps the branch list
and `chopchop`'s "does this issue have a PR?" check clean. The linked issue
number is parsed from the PR body; if no issue is linked, the merge still
proceeds and the report notes that no issue was labelled.

**`comment`** — comment only. The PR stays open for a human.

**`needs-work`**

```bash
gh pr edit {N} --add-label needs-work
```

The script creates the `needs-work` label first if missing (`gh label create
needs-work --color d93f0b --description "Agent review found blocking
problems"`), ignoring the error when it already exists.

### Error handling

Every `gh` call is checked. `apply_verdict.sh` exits non-zero with the `gh`
stderr on its own stdout as structured JSON, and **the parent continues to the
next PR**. A failure on one PR — merge race, branch protection rejection,
network error, missing label — never aborts the batch. Failures appear in the
final report under `errors` with the PR number and the underlying message.

If a merge fails because the PR became unmergeable between listing and merging
(someone else pushed to `master`), it is reported as `skipped (became
unmergeable)` rather than as an error.

### Final report

After the batch, print a table: PR, score, verdict, action taken. Plus the
`skipped` and `errors` lists. This is the only output the user reads, so it must
be complete — including what was *not* done and why.

## Component 5: `oneshot` label fix

The merge skill keys entirely off the `agent` label, and **no PR in this repo
currently carries any label**, including PRs merged after the
`feature/pr-agent-label` work landed. Without this fix `/automerge` finds zero
candidates forever.

Patch `.claude/skills/oneshot/SKILL.md` so the PR-creation step applies the label
at creation time and verifies it stuck:

```bash
gh pr create --label agent ...
gh pr edit {N} --add-label agent    # idempotent belt-and-braces if create dropped it
```

The label must exist in the repo first (`gh label create agent` — ignore error if
present).

This is a prerequisite, not an optional extra: it ships in the same change.

## Constants

Each constant is defined in exactly one file — the script that acts on it:

| Constant | Value | Defined in |
|----------|-------|-----------|
| `MERGE_THRESHOLD` | `80` | `parse_verdict.py` |
| `NEEDS_WORK_THRESHOLD` | `40` | `parse_verdict.py` |
| `MAX_CANDIDATES` | `20` | `candidates.sh` |
| `AGENT_LABEL` | `agent` | `candidates.sh` |
| `MERGED_ISSUE_LABEL` | `agent-merged` | `apply_verdict.sh` |
| `NEEDS_WORK_LABEL` | `needs-work` | `apply_verdict.sh` |

`SKILL.md` documents where each lives; it does not restate the values, so there
is nothing for the prompt and the scripts to disagree about.

If more than `MAX_CANDIDATES` PRs match, `candidates.sh` returns the oldest 20
and sets `truncated` to the number left over. `SKILL.md` must state that number
in the report — silent truncation reads as "covered everything" when it did
not.

## Risks

**The reviewer never runs the code.** Scores come from reading a diff. A change
that looks correct and is not will score high and merge. Threshold 80 with the
uncertainty deduction is the mitigation, and the review comment on every merged
PR means a bad merge is at least traceable afterwards. Accepted deliberately.

**No CI on PRs.** `.github/workflows/` contains only `release.yml`, so there are
no check results to read even if we wanted them. Adding a test workflow would
give this skill a real signal and is the obvious follow-up — out of scope here.

**Fully autonomous by default.** There is no confirmation prompt. A miscalibrated
rubric merges to `master` unattended. The first few runs should be watched.

## Testing

Putting the deterministic logic in scripts is what makes this testable at all —
a prompt cannot be unit-tested, `parse_verdict.py` can. Tests live in
`tests/test_automerge.py` and run under the existing pytest setup.

`parse_verdict.py` (unit, pure stdin/stdout — no mocking needed):
- well-formed block → correct `pr`, `score`, `action`
- band boundaries: 39 → `needs-work`, 40 → `comment`, 79 → `comment`,
  80 → `merge`
- missing block, missing `score`, non-integer score, score `101`, score `-1` →
  `valid: false`, `action: comment`
- `verdict: MERGE` with `score: 30` → mismatch → `valid: false`
- prose after the block, and two blocks in one output (last one wins)

`candidates.sh` (unit, `gh` stubbed by a fake on `PATH` returning canned JSON):
- draft, `CONFLICTING`, `UNKNOWN`, `CHANGES_REQUESTED` each land in `skipped`
  with the right reason
- a clean PR lands in `candidates`
- 25 matching PRs → 20 candidates, `truncated: 5`
- empty result → empty `candidates`, exit 0

`apply_verdict.sh` (unit, `gh` stubbed): each action issues exactly the expected
`gh` calls in the expected order; a failing `gh` call produces structured JSON
on stdout and a non-zero exit rather than a partial silent action.

Coverage target 80% per the repo standard, measured on `parse_verdict.py`.

## Deliverables

1. `.claude/skills/automerge/SKILL.md` — orchestration and the reviewer prompt.
2. `.claude/skills/automerge/candidates.sh`
3. `.claude/skills/automerge/parse_verdict.py`
4. `.claude/skills/automerge/apply_verdict.sh`
5. `.claude/skills/oneshot/SKILL.md` — patched to apply the `agent` label.
6. `tests/test_automerge.py` — per the section above.
