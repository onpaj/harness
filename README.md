# AgentHarness

A distributed, event-driven pipeline that autonomously processes development tasks using specialized Claude agents. Describe a feature, upload a brief, and a chain of agents produces the implementation without further human input.

## How it works

```
brief.md (user input)
    ↓
Analyst  →  spec.r1.md
    ↓
Architect  →  arch-review.r1.md
    ↓
Designer  →  design.r1.md
    ↓
Planner  →  task-plan.r1.md  (fan-out: N developer tasks)
    ↓
Developer ×N  →  impl/{task}.r{N}.md
    ↓
Reviewer  →  review/{task}.r{N}.md  →  PASS or REVISION_NEEDED
```

Each agent is a Claude Code CLI subprocess. All state lives in Azure Blob Storage. Queues drive execution — no central scheduler.

## Quickstart

```bash
pip install -e ".[dev]"
cp .env.example .env   # add AZURE_STORAGE_CONNECTION_STRING
agentharness init      # scaffold Azure queues and containers
```

Run the pipeline:

```bash
agentharness brainstorm                         # interactive brief → uploads to Azure
agentharness submit brief.md                    # upload existing brief, get feature ID
agentharness implement feat-20260425-abc123     # enqueue first task, start pipeline
agentharness observe                            # start observer (primary execution mode)
agentharness watch                              # Textual TUI, auto-refresh 2s
```

## CLI reference

| Command | Description |
|---------|-------------|
| `brainstorm` | Interactive discovery → writes `brief.md` → uploads to Azure |
| `submit <brief>` | Upload brief, return feature ID (no pipeline start) |
| `implement <feat-id>` | Enqueue analyst task, start autonomous pipeline |
| `observe` | Start observer: polls all queues, spawns subprocess per task |
| `worker <queue>` | Legacy: run async worker loop on one queue |
| `worker <queue> --concurrency N` | Legacy: run N parallel workers |
| `start [--dev-concurrency N]` | Legacy: start all workers as background processes |
| `watch` | Textual TUI, auto-refresh 2s |
| `status <feat-id>` | One-shot status snapshot |
| `list` | List all features |
| `init` | Initialize project scaffolding (queues, container) |

## Execution modes

**Observer mode (primary):** `agentharness observe` — a single process polls all queues and spawns `agentharness _run_task` as a subprocess per message. Tasks run in isolation; the observer manages visibility renewal and graceful shutdown.

**Legacy worker mode:** `agentharness worker {queue-name}` — async loop that processes tasks in-process. Useful for debugging a single queue.

## State machine

```
brainstorming → analyzing → architecting → designing → planning → developing → reviewing → done
                                                                       ↑              |
                                                                  dev_revision ←------+
                                                                       |
                                                                   developing → reviewing
```

`failed` is reachable from any state after `dead_letter_threshold` retries or `max_revisions` revision cycles.

### Task status values

| Status | Meaning |
|--------|---------|
| `pending` | Created, not yet enqueued (serial dispatch) |
| `queued` | Enqueued to Azure Storage Queue |
| `in_progress` | Worker has started |
| `completed` | Finished successfully |
| `failed` | Terminal failure |

## Agents (`.agents/*.md`)

| Agent | Model | Phase | Tools | Output parsing |
|-------|-------|-------|-------|----------------|
| analyst | claude-opus-4-7 | analyzing | none | none |
| architect | claude-opus-4-7 | architecting | none | none |
| designer | claude-sonnet-4-6 | designing | none | none |
| planner | claude-opus-4-7 | planning | none | `task_list` |
| developer | claude-sonnet-4-6 | developing | bash, read, write | none |
| reviewer | claude-sonnet-4-6 | reviewing | none | `review_result` |

### Agent frontmatter

```yaml
---
id: developer
model: claude-sonnet-4-6
phase: developing
max_turns: 30
allowed_tools: [bash, read, write]   # maps to --allowedTools
visibility_timeout: 1800             # seconds the worker holds the queue message
retry_limit: 3
output_parsing: none                 # none | task_list | review_result
context_files: []                    # paths injected into prompt (see below)
---
System prompt...
```

### Output parsing

- `task_list` — planner only. Extracts `### task: {name}` headers to fan out developer tasks.
- `review_result` — reviewer only. Extracts `### task: {name}` + `**Status:** PASS/REVISION_NEEDED`.

### Developer status codes

The developer agent may end its output with one of:

| Status | Effect |
|--------|--------|
| `## Status: DONE` | Task completed, enqueue reviewer |
| `## Status: DONE_WITH_CONCERNS` | Completed with caveats, enqueue reviewer |
| `## Status: BLOCKED` | Immediate feature failure |
| `## Status: NEEDS_CONTEXT` | Immediate feature failure |

## Per-agent context files

Any agent can declare `context_files` in its frontmatter. The paths are resolved relative to the project root and injected into the prompt as formatted blocks before the agent runs.

```yaml
context_files:
  - docs/api-spec.md
  - src/models/          # entire directory
  - src/**/*.ts          # recursive glob
```

Supported: single files, directories, recursive patterns (`/**`). Large files emit a warning; unreadable files skip silently.

## Serial task dispatch

Developer tasks are executed serially (not in parallel) to prevent same-file conflicts. The planner emits all tasks with `status: pending`. The dispatcher enqueues the next `pending` task only after the current task completes review. `TaskEntry.queued_message` stores the serialized `TaskMessage` for deferred enqueue.

## Per-task review

Each developer task goes through its own review cycle independently:

```
Developer task N  →  Reviewer  →  PASS → next pending task
                              ↘  REVISION_NEEDED → dev_revision → Developer task N (r+1) → Reviewer
```

After `max_revisions` revision rounds the feature is marked `failed`.

## Artifact naming

```
artifacts/{feature_id}/brief.md
artifacts/{feature_id}/spec.r1.md
artifacts/{feature_id}/arch-review.r1.md
artifacts/{feature_id}/design.r1.md
artifacts/{feature_id}/task-plan.r1.md
artifacts/{feature_id}/impl/{task}.r1.md      # r{N} = revision number
artifacts/{feature_id}/review/{task}.r1.md
artifacts/{feature_id}/state.json
```

## Concurrency safety

`StateManager.update()` acquires an Azure blob lease (30s) before read-modify-write. Lease contention retries with exponential backoff. All other errors propagate immediately.

## Claude Code skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `/brainstorm` | new feature idea | Discovery conversation → writes `brief.md` → uploads to Azure |
| `/implement {feat-id}` | after brainstorm | Enqueues analyst task → starts autonomous pipeline |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter |

## Environment

```bash
cp .env.example .env
# fill in AZURE_STORAGE_CONNECTION_STRING
```

`.env` is loaded automatically via `python-dotenv`. Never commit it — it's in `.gitignore`.

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
