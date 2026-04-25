# AgentHarness — Claude Code Guide

## What this is

A distributed, event-driven pipeline that autonomously processes development tasks using specialized Claude agents. A user describes a feature via brainstorm, uploads a brief, and a chain of agents (analyst → architect → designer → planner → developer(s) → reviewer) produces the implementation without further human input.

## Key concepts

- **Feature** — a unit of work, identified by `feat-{date}-{hash}`. Lives in `artifacts/{feature_id}/` in Azure Blob Storage.
- **Agent** — a Claude Code CLI subprocess defined by a Markdown file in `.agents/`. Each agent has a model, tools, and a system prompt.
- **Observer** — the primary execution process: polls all queues, spawns `agentharness _run_task` as a subprocess per message.
- **Worker** — legacy execution mode: a long-running async process that polls one queue and runs agents in-process.
- **State** — `artifacts/{feature_id}/state.json` is the source of truth for feature lifecycle. All updates are atomic via Azure blob lease.

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
  config.py         Load .pipeline/config.json
  storage.py        Azure Blob + Queue async client wrappers
  state_manager.py  Lease-based atomic state.json updates
  context_files.py  Per-agent context file resolution and prompt injection
  prompt_builder.py Assemble prompt from agent MD + downloaded artifacts + context files
  agent_runner.py   Subprocess wrapper for `claude -p ...`
  dispatcher.py     State machine transitions, serial task dispatch, per-task review loop
  observer.py       Primary runner: polls all queues, spawns run_task subprocess per message
  run_task.py       Single-task runner invoked by observer (reads TaskMessage from stdin)
  worker.py         Legacy async worker loop (in-process execution)
  brainstorm.py     Brief upload + analyst enqueue (called by CLI + skill)
  tui.py            Textual real-time monitoring UI
  cli.py            Click entry points
tests/              Unit tests (pytest-asyncio)
  test_config.py
  test_context_files.py
  test_dispatcher.py
  test_prompt_builder.py
  test_worker.py
  fixtures/context_files/
```

## Claude Code skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `/brainstorm` | new feature idea | Discovery conversation → writes `brief.md` → uploads to Azure |
| `/implement {feat-id}` | after brainstorm | Enqueues analyst task → starts autonomous pipeline |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter |

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

**Observer mode (primary):** `agentharness observe` — a single process polls all queues concurrently and spawns `agentharness _run_task` as an isolated subprocess per message. The observer manages visibility renewal (60s interval, 150s timeout) and handles SIGTERM/SIGINT gracefully.

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

`state_manager.StateManager.update()` acquires an Azure blob lease (30s) before read-modify-write. Only `HttpResponseError` with lease contention error codes trigger retry with exponential backoff. All other errors propagate immediately.

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

## Environment

```bash
cp .env.example .env
# fill in AZURE_STORAGE_CONNECTION_STRING
```

`.env` is loaded automatically via `python-dotenv` in `config.py`. Never commit `.env` — it's in `.gitignore`.

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
4. Create the Azure queue: `/azure-storage` → "create queue {name}-queue"
