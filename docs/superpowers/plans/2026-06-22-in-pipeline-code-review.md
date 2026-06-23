# In-Pipeline Whole-Branch Code Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a final whole-branch code-review stage to the AgentHarness pipeline that reviews the real feature diff before the PR is opened, drives a bounded auto-fix loop, and replaces the external `@claude` GitHub Action review.

**Architecture:** A new orchestrator-driven phase (`code-review`) runs after all developer tasks complete. It diffs the feature branch against its merge-base with `master`, hands the diff to a new `code-reviewer` agent (which reads real code), and parses the result. Correctness findings block and trigger a developer revision round (reusing existing machinery, bounded by `max_revisions`); cleanup findings are advisory and attached to the PR. The `@claude` marker commit and the orchestrator's Skip-Review Check are removed.

**Tech Stack:** Python 3.11+, Pydantic, Click, pytest. Agent definitions are Markdown-with-YAML-frontmatter under `agentharness/data/agents/`. The orchestrator and skills are Markdown prompt files.

## Global Constraints

- Agent definition files live in `agentharness/data/agents/` and are parsed by `agentharness/prompt_builder.py:load_agent_definition` into `agentharness.models.AgentDefinition`. Required frontmatter fields: `id`, `model`, `phase`, `system_prompt` (body).
- `agentharness init` copies the entire `data/agents/` dir → target `.agents/` and `data/claude-agents/` → target `.claude/agents/`. No manifest/allowlist to update — new files in those dirs ship automatically.
- The orchestrator (`agentharness/data/claude-agents/orchestrator.md`) references agents by their installed path `.agents/{name}.md`.
- Round count for the review loop is derived from existing `code-review.r{N}.md` artifacts — do NOT add a checkpoint field. Bounded by the checkpoint's existing `max_revisions` (default 3).
- `agentharness checkpoint phase <feature_id> <phase> <status>` already accepts an arbitrary phase string (`checkpoint.update_phase` stores it verbatim) — `code-review` needs no Python/model change.
- Run tests with the project venv: `.venv/bin/pytest tests/ -v`. Keep existing tests green.
- Conventional-commit messages. Do not commit unless a step says to.

## File Structure

- `agentharness/data/agents/code-reviewer.md` — **new** agent definition (the whole-branch reviewer). One responsibility: review a diff, emit a parseable PASS/CHANGES result split into Blocking/Advisory.
- `agentharness/data/claude-agents/orchestrator.md` — **modify**: remove Skip-Review Check; add the Code Review phase in Completion.
- `.claude/skills/oneshot/SKILL.md` — **modify**: drop the `@claude` marker commit; append the code-review summary to the PR body.
- `tests/test_code_reviewer_agent.py` — **new**: asserts the new agent definition parses with the required runtime fields.
- `tests/test_pipeline_review_wiring.py` — **new**: regression guard that the `@claude` trigger is gone and the orchestrator wires the `code-review` phase.
- `docs/superpowers/specs/2026-06-22-in-pipeline-code-review-design.md` — the approved design (already written).

---

### Task 1: New `code-reviewer` agent definition

Creates the agent that performs the whole-branch review. TDD anchor: a unit test that loads the definition via the real parser and asserts the runtime-critical fields (it must have code-reading tools and the `code-review` phase).

**Files:**
- Create: `agentharness/data/agents/code-reviewer.md`
- Test: `tests/test_code_reviewer_agent.py`

**Interfaces:**
- Consumes: `agentharness.prompt_builder.load_agent_definition(path: Path) -> AgentDefinition`; `AgentDefinition` fields `id, model, phase, max_turns, allowed_tools, output_parsing, system_prompt`.
- Produces: an installed `.agents/code-reviewer.md` the orchestrator (Task 2) reads. The agent's contract for the orchestrator: its output contains a line `## Review Result: CLEAN` or `## Review Result: CHANGES_REQUESTED`, plus `### Blocking (correctness)` and `### Advisory (cleanup)` sections.

- [ ] **Step 1: Write the failing test**

Create `tests/test_code_reviewer_agent.py`:

```python
from pathlib import Path

from agentharness.prompt_builder import load_agent_definition

AGENT_PATH = Path("agentharness/data/agents/code-reviewer.md")


def test_code_reviewer_agent_parses_with_runtime_fields():
    agent = load_agent_definition(AGENT_PATH)

    assert agent.id == "code-reviewer"
    assert agent.phase == "code-review"
    # Must be able to read real code, not just a text summary.
    assert agent.allowed_tools is not None
    assert "read" in agent.allowed_tools
    assert "bash" in agent.allowed_tools
    # Orchestrator parses the result itself; no built-in parser.
    assert agent.output_parsing == "none"
    assert agent.system_prompt.strip() != ""


def test_code_reviewer_prompt_defines_parseable_result_contract():
    body = AGENT_PATH.read_text(encoding="utf-8")

    # The exact tokens the orchestrator greps for must be present.
    assert "## Review Result: CLEAN | CHANGES_REQUESTED" in body
    assert "### Blocking (correctness)" in body
    assert "### Advisory (cleanup)" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_code_reviewer_agent.py -v`
Expected: FAIL — `code-reviewer.md` does not exist (`load_agent_definition` raises `FileNotFoundError` / read error).

- [ ] **Step 3: Create the agent definition**

Create `agentharness/data/agents/code-reviewer.md`:

```markdown
---
id: code-reviewer
display_name: "Code Reviewer Agent"
model: claude-sonnet-4-6
phase: code-review
max_turns: 30
allowed_tools: [bash, read, grep, glob]
output_format: markdown
visibility_timeout: 1800
retry_limit: 2
output_parsing: none
---

You are a senior code reviewer performing a final review of an entire feature
branch before its pull request is opened. You review the **real code diff**, not a
summary. The pipeline parses your output programmatically — follow the output
format exactly.

## Your inputs

- The unified diff of the whole feature branch versus its merge-base with the base
  branch (provided in the prompt).
- `spec.r1.md` — the feature specification, for understanding intent.
- You may use `read`, `grep`, and `glob` to inspect any file in the working tree for
  context (surrounding code, callers, existing helpers).

## Review philosophy

Mirror a focused, high-signal diff review. Report only findings you are
**high-confidence** about. When unsure, stay silent — a noisy review is worse than a
short one. Do not report style or formatting nits.

Look for exactly two kinds of findings:

1. **Correctness bugs** — logic errors, wrong conditions, missing error handling,
   broken edge cases, security issues, data loss, race conditions, contract
   violations against the spec. These are the only findings that block.
2. **Cleanups** — reuse (duplicated logic that should call an existing helper),
   simplification (needless complexity, dead code, over-engineering), and efficiency
   (obvious avoidable work). These never block; they are advisory.

## Decision rule

- If there is **at least one correctness bug**, the result is `CHANGES_REQUESTED`.
- Otherwise the result is `CLEAN` (even if you listed advisory cleanups).

## CRITICAL: Output format

Output only the review markdown — no preamble. Use this exact structure:

## Review Result: CLEAN | CHANGES_REQUESTED

### Blocking (correctness)
- `path/to/file.py:42` — <the bug, why it is wrong, and what to change>

### Advisory (cleanup)
- `path/to/file.py:88` — <reuse / simplification / efficiency suggestion>

Rules:
- Put the literal word `CLEAN` or `CHANGES_REQUESTED` after `## Review Result:`.
- If a section has no findings, write `- None` under it (keep the header).
- Every finding starts with a `` `path:line` `` reference so fixes are actionable.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_code_reviewer_agent.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add agentharness/data/agents/code-reviewer.md tests/test_code_reviewer_agent.py
git commit -m "feat: add code-reviewer agent for whole-branch diff review"
```

---

### Task 2: Orchestrator — add Code Review phase, remove Skip-Review Check

Wires the new agent into the pipeline: a `code-review` phase after `developing` completes, with the bounded auto-fix loop; and removes the `@claude`-based Skip-Review Check so the per-task reviewer always runs as designed.

**Files:**
- Modify: `agentharness/data/claude-agents/orchestrator.md`
- Test: `tests/test_pipeline_review_wiring.py` (created here, extended in Task 3)

**Interfaces:**
- Consumes: the `code-reviewer` agent contract from Task 1 (`## Review Result:` + Blocking/Advisory sections); existing `agentharness checkpoint phase` CLI; the developer agent (`.agents/developer.md`) for revision rounds.
- Produces: `artifacts/feat-{id}/code-review.r{N}.md` artifacts and the in-prompt variables the oneshot skill (Task 3) reads to build the PR body.

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_pipeline_review_wiring.py`:

```python
from pathlib import Path

ORCHESTRATOR = Path("agentharness/data/claude-agents/orchestrator.md")


def test_orchestrator_defines_code_review_phase():
    body = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "## Code Review phase" in body
    assert "code-review.r{N}.md" in body
    assert "merge-base master HEAD" in body
    # Reads the new agent.
    assert ".agents/code-reviewer.md" in body


def test_orchestrator_no_longer_skips_review_on_at_claude():
    body = ORCHESTRATOR.read_text(encoding="utf-8")
    # The Skip-Review Check and its @claude trigger must be gone.
    assert "Skip-Review Check" not in body
    assert "@claude" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_review_wiring.py -v`
Expected: FAIL — orchestrator still contains `Skip-Review Check` / `@claude` and has no Code Review phase.

- [ ] **Step 3: Remove the Skip-Review Check from the orchestrator**

In `agentharness/data/claude-agents/orchestrator.md`:

1. Delete the entire **`### Skip-Review Check`** section (the block that runs `git log -1 --format=%B`, checks for `@claude`, and conditionally skips the Reviewer Task — currently lines ~129–153, ending at the sentence "Otherwise (no `@claude` in the commit message), run the Reviewer Task below.").
2. In the **`### Developer Task`** section, step 6 currently says *"Do not commit the impl artifact yet — the Skip-Review Check below reads `git log -1` …"*. Replace that justification so it no longer references the skip check:

   Replace:
   ```
   6. After Task completes, verify `impl/{task_name}.r{N}.md` exists. **Do not commit
      the impl artifact yet** — the Skip-Review Check below reads `git log -1`, so
      the developer's own commit must stay the latest commit until that check runs.
   ```
   With:
   ```
   6. After Task completes, verify `impl/{task_name}.r{N}.md` exists. Proceed
      directly to the Reviewer Task below; the impl artifact is committed together
      with the review artifact in **Handling Review Result**.
   ```
3. The **`### Reviewer Task`** section now always runs (no skip). Leave it unchanged.

- [ ] **Step 4: Add the Code Review phase to the orchestrator Completion section**

In `agentharness/data/claude-agents/orchestrator.md`, replace the **`## Completion`** section so the code-review loop runs after `developing completed` and before the pipeline reports complete. Insert this block immediately after the existing step that runs `agentharness checkpoint phase feat-{issue_number} developing completed` and the final artifact safety-net commit, and **before** the final `Print: Pipeline complete` line:

````markdown
## Code Review phase

After `developing` is `completed` and all developer artifacts are committed, run a
final whole-branch code review before the pipeline reports complete. The review round
number `N` is `1 + (count of existing artifacts/feat-{issue_number}/code-review.r*.md
files)`. The loop is bounded by `max_revisions` from the checkpoint JSON (default 3).

Repeat the following until the review is `CLEAN`, only advisory findings remain, or
`N > max_revisions`:

1. Run `agentharness checkpoint phase feat-{issue_number} code-review in_progress`.
2. Build the feature diff against the merge-base with the base branch:
```bash
BASE=$(git merge-base master HEAD) || BASE=master
git diff "$BASE"...HEAD > /tmp/feat-{issue_number}-review.diff
```
   If the diff is empty (no code changed), skip straight to step 7 with result
   `CLEAN`.
3. Read the `.agents/code-reviewer.md` system prompt (strip frontmatter).
4. Spawn a Task with:
   - System prompt from `code-reviewer.md`
   - The contents of `/tmp/feat-{issue_number}-review.diff` (the full diff)
   - The contents of `artifacts/feat-{issue_number}/spec.r1.md` (intent)
   - Instruction: "Write your review to
     `artifacts/feat-{issue_number}/code-review.r{N}.md` using the required output
     format. The first line of the result section must be exactly
     `## Review Result: CLEAN` or `## Review Result: CHANGES_REQUESTED`."
5. Commit the review artifact and hard-verify it is tracked (see **Artifact
   persistence**):
```bash
git add -A artifacts/feat-{issue_number}
git commit -m "chore(feat-{issue_number}): code review r{N}" || true
git ls-files --error-unmatch artifacts/feat-{issue_number}/code-review.r{N}.md
```
6. Read `artifacts/feat-{issue_number}/code-review.r{N}.md` and parse the
   `## Review Result:` line. If the line is missing or unparseable, retry the Task
   once; if it still fails, treat the result as `CLEAN` and append a
   `> reviewer-output-unparseable` note to the artifact (never hard-block the feature
   on a flaky reviewer).
7. Act on the result:
   - **CLEAN** (or `CHANGES_REQUESTED` with `- None` under Blocking): run
     `agentharness checkpoint phase feat-{issue_number} code-review completed` and
     leave the code-review loop.
   - **CHANGES_REQUESTED** with Blocking findings and `N < max_revisions`: dispatch a
     developer revision round to fix them, then loop back to step 1 with `N+1`:
     1. Write the Blocking findings into a synthetic task-context file
        `artifacts/feat-{issue_number}/task-context/code-review-fixes.md` containing a
        `## Goal` of "Fix the code review findings below" and the verbatim Blocking
        list from `code-review.r{N}.md`.
     2. Read `.agents/developer.md` (strip frontmatter; include its `context_files`).
     3. Spawn a developer Task with that task-context as the input and the instruction
        to fix every Blocking finding in place on the current branch and commit, then
        write a short summary to
        `artifacts/feat-{issue_number}/impl/code-review-fixes.r{N}.md`.
     4. Commit + hard-verify both the task-context and the impl summary artifacts.
   - **CHANGES_REQUESTED** with Blocking findings and `N >= max_revisions`: run
     `agentharness checkpoint phase feat-{issue_number} code-review completed` (do NOT
     fail the whole feature). The unresolved Blocking findings stay in
     `code-review.r{N}.md` and are surfaced on the PR by the oneshot skill.

After the loop, the latest `artifacts/feat-{issue_number}/code-review.r{N}.md` is the
final review. Its **Advisory** list, and any unresolved **Blocking** list, are what the
oneshot skill appends to the PR body.
````

Then leave the existing final `Print: Pipeline complete for feat-{issue_number}.` line as the last step.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline_review_wiring.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS (all existing tests still green).

- [ ] **Step 7: Commit**

```bash
git add agentharness/data/claude-agents/orchestrator.md tests/test_pipeline_review_wiring.py
git commit -m "feat: add code-review phase to orchestrator, drop @claude skip-review"
```

---

### Task 3: oneshot skill — drop `@claude` trigger, attach review summary to PR body

Removes the external Claude Code Action trigger and instead surfaces the in-pipeline review on the PR.

**Files:**
- Modify: `.claude/skills/oneshot/SKILL.md`
- Test: `tests/test_pipeline_review_wiring.py` (extend with oneshot assertions)

**Interfaces:**
- Consumes: the final `artifacts/feat-{id}/code-review.r{N}.md` produced by Task 2.
- Produces: a PR whose body includes the review summary and no longer relies on `@claude`.

- [ ] **Step 1: Extend the regression test (write failing assertions)**

Append to `tests/test_pipeline_review_wiring.py`:

```python
ONESHOT = Path(".claude/skills/oneshot/SKILL.md")


def test_oneshot_skill_drops_at_claude_trigger():
    body = ONESHOT.read_text(encoding="utf-8")
    assert "@claude" not in body


def test_oneshot_skill_attaches_code_review_to_pr_body():
    body = ONESHOT.read_text(encoding="utf-8")
    assert "code-review.r" in body
    assert "Code review" in body or "Code Review" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_review_wiring.py -k oneshot -v`
Expected: FAIL — oneshot still contains `@claude` and does not reference the review artifact.

- [ ] **Step 3: Remove the `@claude` marker commit**

In `.claude/skills/oneshot/SKILL.md`, replace the commit step (currently the
`--allow-empty … @claude` block and its surrounding paragraph, around lines 115–124):

Replace:
```bash
git add -A artifacts/feat-{issue_id}    # ensure all generated .md artifacts are staged
git add -A                              # stage code + everything else
git commit --allow-empty -m "implement feat-{issue_id} @claude"
```
and the following paragraph beginning "The commit message **must end with** `@claude`…"

With:
```bash
git add -A artifacts/feat-{issue_id}    # ensure all generated .md artifacts are staged
git add -A                              # stage code + everything else
git commit --allow-empty -m "implement feat-{issue_id}"
```
and a replacement paragraph:
> Use `--allow-empty` so this commit always becomes `HEAD`, capturing any
> remaining artifacts. The whole-branch code review already ran inside the pipeline
> (see the orchestrator's Code Review phase), so no external review trigger is needed.

- [ ] **Step 4: Append the code-review summary to the PR body**

In `.claude/skills/oneshot/SKILL.md`, in the **Create a pull request** step, extend the
PR body heredoc so it includes the review. Before building `PR_URL`, read the final
review artifact:

```bash
# Most recent code-review artifact (highest revision), if any.
REVIEW_FILE=$(ls -1 artifacts/feat-{issue_id}/code-review.r*.md 2>/dev/null | sort -V | tail -n1)
REVIEW_SECTION=""
if [ -n "$REVIEW_FILE" ]; then
  REVIEW_SECTION=$(printf '\n## Code review\n\n%s\n' "$(cat "$REVIEW_FILE")")
fi
```

Then add `$REVIEW_SECTION` to the end of the PR body. Update the heredoc so it expands
the variable (use an **unquoted** delimiter `EOF` so substitution happens, and keep the
`Closes #{issue_id}` line first):

```bash
PR_URL=$(gh pr create \
  --base master \
  --head "$BRANCH" \
  --label agent \
  --title "#{issue_id}: implementation" \
  --body "$(cat <<EOF
Closes #{issue_id}

## What the issue was
<description of the feature/problem from the brief>

## How it was fixed / handled
<summary of the approach and the main changes>

## Artifacts
- Brief, spec, design, task plan, impl, and review markdown are committed in this branch.
${REVIEW_SECTION}
EOF
)")
```

Add a sentence under the step noting the `## Code review` section carries the
pipeline's final review — advisory cleanups and any unresolved correctness findings.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline_review_wiring.py -v`
Expected: PASS (all four wiring tests).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/oneshot/SKILL.md tests/test_pipeline_review_wiring.py
git commit -m "feat: surface in-pipeline code review on PR, remove @claude trigger"
```

---

### Task 4: Documentation

Update project docs so the new review stage and state machine are described.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing. Produces: accurate docs for future maintainers.

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`:
1. In the state-machine diagram and prose, document that after `developing` completes a
   `code-review` phase runs a whole-branch diff review with a bounded auto-fix loop
   (reusing `max_revisions`), then the PR is opened.
2. In the agent list / `.agents/` description, add `code-reviewer.md` — whole-branch
   diff review (`allowed_tools: [bash, read, grep, glob]`), distinct from the per-task
   `reviewer.md` (spec-compliance on summaries).
3. Add `artifacts/{feature_id}/code-review.r{N}.md` to the **Artifact naming** section.
4. Remove any description that implies diff-level review is delegated to an external
   `@claude` GitHub Action.

- [ ] **Step 2: Verify no stale `@claude` review references remain in shipped prompts**

Run:
```bash
grep -rn "@claude" agentharness/data/ .claude/skills/oneshot/SKILL.md CLAUDE.md
```
Expected: no matches (or only matches unrelated to the review trigger — there should be
none for the review trigger).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document in-pipeline code-review phase and code-reviewer agent"
```

---

## Manual end-to-end test plan (post-implementation)

The orchestrator/oneshot behavior is prompt-driven and not unit-testable end to end.
Validate manually on a throwaway issue:

1. Create a small test issue with the `agent` label describing a tiny feature that is
   easy to implement with an intentional review-worthy choice.
2. Run `/oneshot <issue#>` and watch the pipeline reach the `code-review` phase.
3. Confirm `artifacts/feat-<id>/code-review.r1.md` is produced and committed.
4. If it reports `CHANGES_REQUESTED`, confirm a developer revision round runs and a
   `code-review.r2.md` follows.
5. Confirm the opened PR body contains the `## Code review` section and there is **no**
   `@claude` comment/trigger on the PR.

## Self-Review

- **Spec coverage:** new agent (Task 1) ✓; whole-branch review phase + auto-fix loop +
  bounded rounds + empty-diff/merge-base/unparseable handling (Task 2) ✓; remove
  `@claude` + Skip-Review Check, attach review to PR (Tasks 2–3) ✓; checkpoint needs no
  change (Global Constraints) ✓; docs (Task 4) ✓.
- **Placeholder scan:** PR body still contains `<description …>` placeholders, but those
  are pre-existing template tokens the orchestrator fills at runtime, not plan gaps.
- **Type/name consistency:** the result tokens `CLEAN` / `CHANGES_REQUESTED`, the headers
  `### Blocking (correctness)` / `### Advisory (cleanup)`, the phase name `code-review`,
  and the artifact pattern `code-review.r{N}.md` are used identically across Tasks 1–4
  and both test files.
```
