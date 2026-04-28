# AgentHarness — Claude Code Guide

## What this is

A distributed, event-driven pipeline that autonomously processes development tasks using specialized Claude agents. A user describes a feature via brainstorm, uploads a brief, and a chain of agents (analyst → architect → designer → planner → developer(s) → reviewer) produces the implementation without further human input.

## Key concepts

- **Feature** — a unit of work, identified by `feat-{date}-{hash}`. Lives in a storage backend (Azure Blob Storage or GitHub branch).
- **Agent** — a Claude Code CLI subprocess defined by a Markdown file in `.agents/`. Each agent has a model, tools, and a system prompt.
- **Observer** — the primary execution process: polls all queues, spawns `agentharness _run_task` as a subprocess per message.
- **Worker** — legacy execution mode: a long-running async process that polls one queue and runs agents in-process.
- **State** — feature lifecycle source of truth. Azure backend: `state.json` in blob storage (atomic via blob lease). GitHub backend: issue labels and JSON body (no state.json file).

## Project layout

```
.agents/            Agent definitions (model, tools, system prompt)
  analyst.md        Analyze brief → spec
  architect.md      Architecture review
  designer.md       Design document generator
  planner.md        Task planning from spec (fan-out)
  developer.md      Code implementation (serial, per-task review)
  reviewer.md       Per-task review with PASS/REVISION_NEEDED
  brainstorm.md     Interactive brief discovery (CLI skill)
.claude/agents/     Claude Code skills (brainstorm, implement, azure-storage)
.pipeline/          Runtime config (queue → agent mapping, timeouts)
agentharness/       Python package
  models.py         Pydantic models — FeatureState, TaskMessage, TaskStatus, AgentDefinition
  config.py         Load .pipeline/config.json, GitHubConfig, StorageConfig
  storage_protocol.py         Pluggable backend Protocol definitions: ArtifactStorage, TaskQueue, StateBackend
  storage.py        Factory functions: create_artifact_store, create_task_queue, create_state_manager
  azure_artifacts.py          Azure Blob Storage artifact backend
  azure_queue.py              Azure Storage Queue backend
  github_client.py            httpx async GitHub REST API wrapper
  github_labels.py            GitHub label name constants and utilities
  github_queue.py             GitHub Issues as task queue backend (claim/delete operations)
  github_artifacts.py         Git branch artifact storage backend; commit_workdir_changes() auto-commits developer code after agent runs
  github_state.py             GitHub issue label + JSON body state manager, parse_state_from_issue helper
  state_manager.py  Lease-based atomic state updates (abstracts over backends)
  context_files.py  Per-agent context file resolution and prompt injection
  prompt_builder.py Assemble prompt from agent MD + downloaded artifacts + context files
  agent_runner.py   Subprocess wrapper for `claude -p ...`
  dispatcher.py     State machine transitions, serial task dispatch, per-task review loop
  observer.py       Primary runner: concurrent queue polling (Azure) or unified GitHub polling, spawns run_task subprocess per message
  run_task.py       Single-task runner invoked by observer (reads TaskMessage from stdin)
  worker.py         Legacy async worker loop (in-process execution)
  brainstorm.py     Brief upload + analyst enqueue (called by CLI + skill)
  worktree_manager.py Git worktree utilities for branch management
  tui.py            Textual real-time monitoring UI
  cli.py            Click entry points
tests/              Unit tests (pytest-asyncio)
  test_config.py
  test_context_files.py
  test_dispatcher.py
  test_prompt_builder.py
  test_worker.py
  test_run_task.py
  fixtures/context_files/
```

## Claude Code skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `/brainstorm` | new feature idea | Discovery conversation → writes `brief.md` → uploads to configured backend |
| `/implement {feat-id}` | after brainstorm | Enqueues analyst task → starts autonomous pipeline |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter (Azure backend only) |

## CLI commands

```bash
agentharness brainstorm                         # interactive (terminal-only, uses os.execvp)
agentharness submit brief.md                    # upload brief, get feature ID (no pipeline)
agentharness implement feat-20260425-abc123     # enqueue analyst task, start pipeline
agentharness observe                            # start observer (primary execution mode)
agentharness worker planner-queue              # legacy: run worker for one queue
agentharness worker developer-queue --concurrency 3
agentharness start --dev-concurrency 3         # legacy: start all workers as background procs
agentharness watch                              # Textual TUI, auto-refresh 2s
agentharness status feat-20260425-abc123        # one-shot status snapshot
agentharness list                               # all features
agentharness init                               # initialize project scaffolding
```

Internal (called by observer, not for direct use):
```bash
agentharness _observe                           # observer loop
agentharness _run_task                          # single-task runner (reads JSON from stdin)
```

## Execution modes

**Observer mode (primary):** `agentharness observe` — a single process polls all queues and spawns `agentharness _run_task` as an isolated subprocess per message. For Azure backends, each queue is polled concurrently with visibility renewal (60s interval, 150s timeout). For GitHub backends, a single unified poller fetches all open issues (one API call per cycle) and handles task dispatch, stale-claim sweeping, and state cache writing. The observer handles SIGTERM/SIGINT gracefully.

**Legacy worker mode:** `agentharness worker {queue-name}` — async loop that processes tasks in-process. Useful for debugging a single queue.

## State machine

```
brainstorming → analyzing → architecting → designing → planning → developing → reviewing → done
                                                                       ↑              |
                                                                  dev_revision ←------+
                                                                       |
                                                                   developing → reviewing
```

`failed` is reachable from any state after `dead_letter_threshold` retries or `max_revisions` revision rounds.

### Task status values (`TaskStatus`)

| Value | Meaning |
|-------|---------|
| `pending` | Created by planner but not yet enqueued (serial dispatch) |
| `queued` | Enqueued to Azure Storage Queue |
| `in_progress` | Worker/observer has started |
| `completed` | Finished successfully |
| `failed` | Terminal failure |

## Agent definitions (`.agents/*.md`)

YAML frontmatter controls runtime behaviour:

```yaml
---
id: developer
model: claude-sonnet-4-6
phase: developing
max_turns: 30
allowed_tools: [bash, read, write]   # maps to --allowedTools
visibility_timeout: 1800             # seconds observer holds the queue message
retry_limit: 3
output_parsing: none                 # none | task_list | review_result
context_files: []                    # paths resolved relative to project root
---
System prompt...
```

- `allowed_tools: []` → plain `claude -p` (no tool use). Used for analyst, architect, designer, planner, reviewer.
- `allowed_tools: [bash, read, write]` → developer agents that write code.
- `output_parsing: task_list` → dispatcher extracts `### task: name` headers from planner output to fan-out developer tasks.
- `output_parsing: review_result` → dispatcher extracts `### task: name` + `**Status:** PASS/REVISION_NEEDED` from reviewer output.

### Developer code commit (GitHub backend)

After a developer agent finishes, `run_task.py` checks whether the agent had `allowed_tools` set and the store exposes `commit_workdir_changes`. If so, all files the agent wrote to its work directory (`clone_root/artifacts/{feature_id}/`) are staged with `git add -A`, committed, and pushed to the feature branch **before** the impl markdown is uploaded. This ensures actual code files (not just the agent's text summary) appear in the feature PR.

`GitHubArtifactStore.commit_workdir_changes(message)` returns `True` if a commit was created, `False` if nothing was staged (idempotent — no empty commits).

### Developer status codes

The developer agent ends its output with one of:

| Status | Effect |
|--------|--------|
| `## Status: DONE` | Task completed, enqueue reviewer |
| `## Status: DONE_WITH_CONCERNS` | Completed with caveats, enqueue reviewer |
| `## Status: BLOCKED` | Immediate feature failure |
| `## Status: NEEDS_CONTEXT` | Immediate feature failure |

## Per-agent context files

Agents can declare `context_files` in frontmatter — paths resolved relative to the project root and injected into the prompt before the agent runs. Supports single files, directories, and recursive globs (`/**`). Large files emit a warning; unreadable paths skip silently.

`context_files.py` exports:
- `resolve_context_files(paths, project_root)` → `list[ResolvedContextFile]`
- `format_context_section(files)` → formatted string block

## Serial task dispatch

Developer tasks are executed serially to prevent same-file conflicts. The planner emits all tasks with `status: pending`. The dispatcher enqueues only the next `pending` task after the current task passes review. `TaskEntry.queued_message` stores the serialized `TaskMessage` for deferred enqueue. `FeatureState.next_pending_task()` and `all_tasks_complete()` drive this logic.

## Per-task review

Each developer task goes through its own review cycle:

```
Developer task N  →  Reviewer  →  PASS → enqueue next pending task
                              ↘  REVISION_NEEDED → dev_revision → Developer task N (r+1) → Reviewer
```

After `max_revisions` rounds the feature is marked `failed`.

## Fan-out (planner → developers)

Planner output is parsed for `### task: {name}` headers. All tasks are written to `state.json` with `status: pending`. The first task is immediately enqueued; remaining tasks are enqueued serially as each completes review.

## Concurrency safety

**Azure backend:** `state_manager.StateManager.update()` acquires an Azure blob lease (30s) before read-modify-write. Only `HttpResponseError` with lease contention error codes trigger retry with exponential backoff.

**GitHub backend:** Issue state updates are atomic; GitHub prevents simultaneous writes via optimistic locking. The unified poller sweeps abandoned task claims by checking `updated_at` timestamps and reclaiming issues idle longer than `visibility_timeout` (150s).

All other errors propagate immediately.

## Artifact naming

```
artifacts/{feature_id}/brief.md
artifacts/{feature_id}/spec.r1.md              # analyst output
artifacts/{feature_id}/arch-review.r1.md       # architect output
artifacts/{feature_id}/design.r1.md            # designer output
artifacts/{feature_id}/task-plan.r1.md         # planner output
artifacts/{feature_id}/impl/{task}.r1.md       # r{N} = revision number
artifacts/{feature_id}/review/{task}.r1.md
artifacts/{feature_id}/state.json
```

## Backends

AgentHarness supports two pluggable storage backends: **Azure** (default) and **GitHub**.

### Azure backend (default)

**Uses:** Azure Blob Storage for artifacts, Azure Storage Queues for work queue, blob leases for atomic state updates.

**Environment variables:**
```bash
STORAGE_BACKEND=azure  # or omit (default)
AZURE_STORAGE_CONNECTION_STRING=...  # required
```

### GitHub backend

**Uses:** GitHub Issues (with labels) as work queue, git branches as artifact store, issue state (labels + JSON body) as state manager.

**Environment variables:**
```bash
STORAGE_BACKEND=github
GITHUB_TOKEN=ghp_...  # required
GITHUB_OWNER=...      # optional (auto-detected from git remote)
GITHUB_RUNS_REPO=...  # optional (auto-detected from git remote)
```

### Configuration

```bash
cp .env.example .env
# Set STORAGE_BACKEND to 'azure' or 'github'
# Set backend-specific variables above
```

`.env` is loaded automatically via `python-dotenv` in `config.py`. Never commit `.env` — it's in `.gitignore`.

## Pluggable backend system

The backend system is defined in `storage_protocol.py` and factored in `storage.py`:

- **`storage_protocol.py`** — Protocol definitions: `ArtifactStorage`, `TaskQueue`, `StateBackend`, `RawMessage`
- **`storage.py`** — Factory functions that return backend implementations based on `config.storage_backend`
  - `create_artifact_store(config, feature_id)` → Azure or GitHub artifact store
  - `create_task_queue(config, queue_name)` → Azure or GitHub task queue
  - `create_state_manager(config)` → Azure or GitHub state manager

Components that use storage (`observer.py`, `run_task.py`, `brainstorm.py`, `dispatcher.py`, `tui.py`) import the factory and use it to get the appropriate backend implementation at runtime.

## Running tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v
```

Tests use mocked Azure clients — no real storage needed.

## Adding a new agent

1. Create `.agents/{name}.md` with YAML frontmatter + system prompt
2. Add queue entry to `.pipeline/config.json`
3. Add transition logic to `dispatcher.py` (`_LINEAR_TRANSITIONS` or custom handler)
4. Backend setup:
   - **Azure:** Use `/azure-storage` skill → "create queue {name}-queue"
   - **GitHub:** No manual setup needed (issues are created dynamically)
