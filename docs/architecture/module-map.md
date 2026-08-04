# Application Module Map

**Purpose:** a stable, exhaustive partition of the AgentHarness repository into **14 analysis units**
("parts"). Each part is small enough that a single focused review session can hold it in context, and
large enough that the review produces something meaningful. The map is designed to be **iterated**:
pick one part, review it, move on.

> This document describes *cuts*, not architecture. It is the substrate the `/arch-review` skill
> samples from — see `.claude/skills/arch-review/SKILL.md`.

---

## How the cut was made

**Cut rules applied, in priority order:**

1. **A Python module and its tests are one part.** The package is small (~1.0k LOC across 8 modules),
   so the natural seam is one module + the tests that cover it. Splitting a 100-line module further
   would produce parts too thin to say anything about.
2. **Merge when a module is too thin.** `models.py` has no tests of its own and is consumed by
   everything; it is folded into the part that owns the models it defines — `Checkpoint` into #2,
   `AgentDefinition` into #3.
3. **Markdown that drives behaviour is code.** The orchestration logic of this project lives in
   `.claude/skills/*/SKILL.md` and `agentharness/data/agents/*.md`, not in Python. Those files get
   real parts, cut by role, not lumped into a "docs" bucket.
4. **The duplicated skill tree is one part, not two.** `agentharness/data/skills/` is a byte-identical
   packaged copy of `.claude/skills/` (enforced by `tests/test_packaged_skills.py`). A part owns both
   copies of the skills it covers; reviewing them separately would double every finding.
5. **Non-domain concerns get explicit parts.** Packaging/CI, project documentation, and committed
   pipeline artifacts are parts too — they are where a lot of the drift lives.

**Sizing target:** roughly 100–700 LOC of hand-written code or prose per part.

**Notation:**

- **Part numbers (#1–#14) are the stable identifier.** Use them when referring to a part anywhere else
  — review artifacts, issues, commits. They are never reused or reassigned.
- Parts are grouped A–D for readability only. The group letter carries no meaning beyond ordering.
- `PY` = Python LOC, `MD` = Markdown LOC, `SH` = shell LOC. Test LOC is counted with its part.
- Paths are repo-relative. A trailing `/` means the whole subtree.
- Sizes are approximate — measured at the time of writing, meant for triage not accounting.

---

## Normative documents

Read these before judging; they are what a finding must be grounded in.

- `CLAUDE.md` at the repository root — the project's own description of its concepts, conventions, and
  state machine.
- `README.md` — the user-facing contract.
- `agentic-pipeline-spec.md` — the pipeline specification.
- This map — including how neighbouring parts are cut.

There is no `docs/adr/` directory and no ADR series in this repository. Do not report their absence as
a finding; the conventions here are carried by `CLAUDE.md` and by the prevailing code, not by ADRs.

> **`CLAUDE.md` and `README.md` are known to be stale — verify every claim against the code.**
> They document `observer.py`, `dispatcher.py`, `storage.py`, `storage_protocol.py`,
> `azure_artifacts.py`, `azure_queue.py`, `github_client.py`, `github_queue.py`,
> `github_artifacts.py`, `github_state.py`, `state_manager.py`, `agent_runner.py`, `run_task.py`,
> `worker.py` and `worktree_manager.py` — **none of which exist in the package**. `README.md`
> documents `agentharness submit` and `agentharness observe`, which do not exist, and claims
> `agentharness init` scaffolds Azure queues, which it does not — it copies files.
>
> A gap between these documents and correct code is a **documentation** finding against part #14, at
> most `minor`. It is not an architecture finding against the code.

---

## Summary table

### A. Python package — parts #1–#7

| # | Part | Approx. size | Primary entry point |
|---|------|--------------|---------------------|
| 1 | CLI & Project Scaffolding | PY ~302 / tests ~92 | `agentharness` console script |
| 2 | Checkpoint State & Pipeline Models | PY ~200 / tests ~275 | `agentharness checkpoint *` |
| 3 | Prompt Assembly & Agent Definitions | PY ~82 / tests ~247 | `build_prompt()` |
| 4 | Context File Resolution | PY ~176 / tests ~306 | `resolve_context_files()` |
| 5 | Configuration & Environment | PY ~82 / tests ~65 | `load_config()` |
| 6 | Interactive Brainstorm | PY ~49 / tests ~51 | `agentharness brainstorm` |
| 7 | Monitoring TUI | PY ~116 / tests ~61 | `agentharness watch` |

### B. Agent personas — parts #8–#9

| # | Part | Approx. size | Consumed by |
|---|------|--------------|-------------|
| 8 | Specification Personas | MD ~400 | `analyzing` → `planning` phases |
| 9 | Implementation & Review Personas | MD ~350 / tests ~92 | `developing` → `code-review` phases |

### C. Orchestration & operational skills — parts #10–#12

| # | Part | Approx. size | Trigger |
|---|------|--------------|---------|
| 10 | Pipeline Orchestration Skills | MD ~370 / SH ~120 / tests ~253 | `/oneshot`, `/chopchop` |
| 11 | Storage Backend Skills | MD ~636 | `/azure-storage`, `/github-storage` |
| 12 | Telemetry Scan Skill | MD ~180 / SH ~400 | `/applicationinsightsscan` |

### D. Project infrastructure — parts #13–#14

| # | Part | Approx. size | Notes |
|---|------|--------------|-------|
| 13 | Packaging, Release & CI | ~120 | semantic-release |
| 14 | Project Documentation & Committed Artifacts | MD ~1.5k | see analysis notes |

---

## 1. CLI & Project Scaffolding

**Purpose:** the `agentharness` console script — the only Python entry point a user touches directly.
Command group, project scaffolding (`init`), and the Rich-rendered `status` / `list` views.

**Owns:**
- `agentharness/cli.py`
- `tests/test_cli_init.py`, `tests/test_cli_new.py`

**Depends on:** #2 (checkpoint CRUD), #6 (brainstorm entry), #7 (TUI entry).

**Consumed by:** the user, and `/oneshot` (#10) which shells out to `agentharness checkpoint *`.

**Analysis notes:** the largest module in the package at 302 lines, and the least cohesive — it mixes
`gh` authentication, interactive `.env` editing (`_write_env`), file-tree copying (`_copy_dir`), and
Rich table rendering in one file. `_write_env` prompts interactively from inside a command that is
also run non-interactively. Worth checking whether the presentation layer should split out.

---

## 2. Checkpoint State & Pipeline Models

**Purpose:** the pipeline's state, and the only durable thing the Python side owns. Phase and task
status for each feature, persisted as `artifacts/{feature_id}/state.json`.

**Owns:**
- `agentharness/checkpoint.py`
- `agentharness/models.py` — `Checkpoint`, `PhaseCheckpoint`, `TaskCheckpoint`, `CheckpointStatus`
- `tests/test_checkpoint.py`, `tests/test_checkpoint_cli.py`

**Depends on:** nothing inside the package.

**Consumed by:** #1, #7, and `/oneshot` (#10) via the CLI.

**Analysis notes:** writes go through `_save_raw`, which is atomic per-write (`tmp` + `os.replace`) but
has no cross-process lock — worth checking against how `/oneshot` and `agentharness watch` interleave.
`list_checkpoints` swallows every exception with a bare `except Exception: continue`, so a corrupt
`state.json` silently disappears from both `list` and the TUI. `next_pending_phase()` deliberately
omits `developing`; the reasoning is in a comment in `models.py` and nowhere else.

---

## 3. Prompt Assembly & Agent Definitions

**Purpose:** turning an agent Markdown file plus input artifacts into the single prompt string handed
to the Claude CLI. Owns the frontmatter contract every file in `data/agents/` must satisfy.

**Owns:**
- `agentharness/prompt_builder.py`
- `agentharness/models.py` — `AgentDefinition`
- `tests/test_prompt_builder.py`

**Depends on:** #4 (context file injection), #5 (`config_dir`).

**Consumed by:** #6, and the pipeline personas in #8/#9 through their frontmatter.

**Analysis notes:** `build_prompt()` reads `task.context`, `task.review_feedback` and `task.task_id`
off a duck-typed `task: object`, but no `TaskMessage` model exists in `models.py` any more — the
comment there says the model file is "kept for prompt_builder.py and brainstorm.py". Worth checking
what actually constructs that argument today, and whether the contract should be typed.

---

## 4. Context File Resolution

**Purpose:** resolving an agent's declared `context_files` frontmatter to real files — single paths,
directories, and recursive globs — reading them, and formatting the block injected into the prompt.

**Owns:**
- `agentharness/context_files.py`
- `tests/test_context_files.py`, `tests/fixtures/context_files/`

**Depends on:** nothing inside the package.

**Consumed by:** #3, #6.

**Analysis notes:** the largest non-CLI module and the most heavily tested (306 test LOC against 176
source LOC). Failure handling is deliberately asymmetric — unreadable files produce a warning and are
skipped, empty directories only log at debug. Check that the two callers agree on the
`(declared_paths, agent_name, config_dir)` signature; they do not obviously do so today.

---

## 5. Configuration & Environment

**Purpose:** loading `.pipeline/config.json`, resolving GitHub credentials, and auto-detecting
owner/repo from the `origin` remote.

**Owns:**
- `agentharness/config.py`
- `.pipeline/config.json`, `agentharness/data/pipeline/config.json`
- `.env.example`
- `tests/test_config_new.py`

**Depends on:** nothing inside the package.

**Consumed by:** #3 (`config_dir`), and every skill that needs `GITHUB_*`.

**Analysis notes:** `Config` sets `extra="ignore"`, so the `queues`, `defaults` and `storage` blocks in
`config.json` are parsed and discarded — nothing in the Python package reads the queue→agent mapping.
Worth establishing whether that config is still live (read by the skills) or dead. `GitHubConfig`
resolves env lazily through properties, so a missing token fails at first use rather than at load.

---

## 6. Interactive Brainstorm

**Purpose:** the human-in-the-loop entry point. Builds the brainstorm persona's system prompt and
hands the terminal to `claude` via `os.execvp`.

**Owns:**
- `agentharness/brainstorm.py`
- `agentharness/data/agents/brainstorm.md`
- `.claude/skills/brainstorm/`, `agentharness/data/skills/brainstorm/`
- `tests/test_brainstorm_simple.py`

**Depends on:** #3 (`load_agent_definition`), #4 (`resolve_context_files`).

**Analysis notes:** `os.execvp` replaces the process, so nothing after it in the call stack runs —
including the `tempfile.TemporaryDirectory` cleanup in `start_brainstorm`. The `work_dir` argument to
`run_brainstorm_session` is accepted and never used. The call to `resolve_context_files` passes two
positional arguments where #4 defines three; verify against the current signature before assuming the
path is exercised.

---

## 7. Monitoring TUI

**Purpose:** the Textual full-screen monitor — a 2-second-refresh table of every feature's phase and
task progress.

**Owns:**
- `agentharness/tui.py`
- `tests/test_tui_checkpoint.py`

**Depends on:** #2.

**Analysis notes:** `_phase_summary` hard-codes the pipeline phase list that #2's `models.py` also
hard-codes in `_PIPELINE_PHASES`. Two copies of the same ordered list, in two modules, with no shared
constant.

---

## 8. Specification Personas

**Purpose:** the agent definitions that turn a brief into a specification, an architecture assessment,
a design, and a task plan — the read-only front half of the pipeline.

**Owns:**
- `agentharness/data/agents/analyst.md`
- `agentharness/data/agents/product.md`
- `agentharness/data/agents/architect.md`
- `agentharness/data/agents/designer.md`
- `agentharness/data/agents/planner.md`

**Depends on:** #3 (the frontmatter contract).

**Consumed by:** the `analyzing` → `planning` phases, driven by #10.

**Analysis notes:** `architect.md` carries a `## Skip Design: true|false` marker that the downstream
designer phase is expected to honour — check where that is actually parsed. Frontmatter fields
(`visibility_timeout`, `retry_limit`, `output_parsing`) describe a queue-based runtime; confirm which
of them anything still reads.

---

## 9. Implementation & Review Personas

**Purpose:** the agent definitions that write code and judge it — `developer`, the per-task
`reviewer`, and the whole-branch `code-reviewer`.

**Owns:**
- `agentharness/data/agents/developer.md`
- `agentharness/data/agents/reviewer.md`
- `agentharness/data/agents/code-reviewer.md`
- `tests/test_code_reviewer_agent.py`, `tests/test_pipeline_review_wiring.py`

**Depends on:** #3, #8 (reviews against the spec and architecture).

**Analysis notes:** `code-reviewer.md` is the only persona whose output is parsed programmatically
(`## Review Result: CLEAN | CHANGES_REQUESTED`), and the only one with a test asserting its contract.
Its blocking/advisory split is the sharpest severity rule in the repo — worth checking whether
`reviewer.md` should adopt the same shape.

---

## 10. Pipeline Orchestration Skills

**Purpose:** the actual state machine. `/oneshot` drives a feature end to end; `/chopchop` picks the
next issue; `/convertforagent` adapts an existing issue; `/submit` uploads a brief.

**Owns:**
- `.claude/skills/oneshot/` (+ `ensure_pr_linked.sh`), `.claude/skills/chopchop/`,
  `.claude/skills/convertforagent/`, `.claude/skills/submit/`
- the packaged mirrors of those four under `agentharness/data/skills/`
- `agentharness/data/claude-agents/orchestrator.md`
- `tests/test_ensure_pr_linked.py`, `tests/test_packaged_skills.py`

**Depends on:** #1 (`agentharness checkpoint *`), #2, #8, #9.

**Analysis notes:** the orchestration logic of this project is prose, not code — the phase transitions,
the revision loop, and the label lifecycle (`agent` → `agent-wip` → `agent-completed`) exist only as
instructions in `oneshot/SKILL.md`. `ensure_pr_linked.sh` is the one piece with real tests. Worth
checking which invariants are load-bearing enough that an LLM "usually" honouring them is not enough.

---

## 11. Storage Backend Skills

**Purpose:** operator tooling for the two storage backends — inspecting blobs and queues (Azure), and
issues, branches and artifacts (GitHub).

**Owns:**
- `.claude/skills/azure-storage/`, `.claude/skills/github-storage/`
- the packaged mirrors of both under `agentharness/data/skills/`

**Depends on:** #5 (credentials).

**Analysis notes:** the two largest skill documents in the repo (268 and 368 lines). Both describe a
queue-and-blob runtime; cross-check their claims against what the Python package actually implements
before treating them as normative.

---

## 12. Telemetry Scan Skill

**Purpose:** the production-telemetry anomaly routine — reads Application Insights, correlates with
GitHub, dedups, and files an issue per new anomaly. Read-only against code.

**Owns:**
- `.claude/skills/applicationinsightsscan/` (`SKILL.md`, `telemetry-rules.md`,
  `appinsights-query.sh`, `gh-api.sh`, `telemetry-digest.sh`)
- the packaged mirror under `agentharness/data/skills/`

**Depends on:** nothing in the package — it is self-contained by design.

**Analysis notes:** the closest structural sibling to `/arch-review` (#10's neighbour in spirit): a
scheduled, read-only, dedup-then-file routine with bundled shell helpers. Its `.env` fallback resolves
the repo root three levels up from the skill's install path — a convention any new bundled script
should match rather than reinvent.

---

## 13. Packaging, Release & CI

**Purpose:** how the package is built, versioned and released.

**Owns:**
- `pyproject.toml`
- `.github/workflows/release.yml`
- `CHANGELOG.md`
- `scripts/` — operator utilities run by hand, not by the package

**Analysis notes:** exactly one workflow — release. There is no CI job running `pytest` on push or on
pull requests, so the test suite is only ever run locally. Worth checking whether that is deliberate.
`scripts/reset_feature.py` is untested and imports nothing from the package — check whether it still
matches the checkpoint format in #2.

---

## 14. Project Documentation & Committed Artifacts

**Purpose:** the normative prose describing what this project is, plus the pipeline output committed
back into the repository.

**Owns:**
- `CLAUDE.md`, `README.md`, `agentic-pipeline-spec.md`
- `docs/` (excluding this map)
- `plans/`
- `artifacts/`, and the root-level `spec.r1.md`, `design.r1.md`, `arch-review.r1.md`,
  `task-plan.r1.md`

**Analysis notes:** **this part is known to be stale, and it is the reason every other part must be
read against the code rather than against the docs.** `CLAUDE.md` documents `observer.py`,
`dispatcher.py`, `storage.py`, `storage_protocol.py`, `azure_artifacts.py`, `azure_queue.py`,
`github_client.py`, `github_queue.py`, `github_artifacts.py`, `github_state.py`, `state_manager.py`,
`agent_runner.py`, `run_task.py`, `worker.py` and `worktree_manager.py` — **none of which exist in the
package.** `README.md` documents `agentharness submit`, `agentharness observe` and `agentharness init`
scaffolding Azure queues; only `init` exists, and it copies files. Four generated `*.r1.md` artifacts
sit loose in the repository root rather than under `artifacts/`.

---

## Maintenance

When the codebase moves:

- **Never renumber or reuse a part number.** A part that disappears keeps its row, with its name
  replaced by `RETIRED — <reason>`; the picker skips those rows but old references stay resolvable.
- **Adding a part** appends the next free number, in whichever group fits. The group letter is
  cosmetic; the number is the identity.
- **Splitting a part** retires the original and adds two new numbers, so no existing reference silently
  changes meaning.
- Keep every row in a **summary table** — `.claude/skills/arch-review/pick-module.sh` parses the
  `| <n> | <name> | …` rows and ignores the `## N.` headings, precisely so retiring a part cannot
  resurrect it.
