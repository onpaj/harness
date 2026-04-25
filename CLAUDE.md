# AgentHarness — Claude Code Guide

## What this is

A distributed, event-driven pipeline that autonomously processes development tasks using specialized Claude agents. A user describes a feature via brainstorm, uploads a brief, and a chain of agents (planner → architect → designer → developer(s) → reviewer) produces the implementation without further human input.

## Key concepts

- **Feature** — a unit of work, identified by `feat-{date}-{hash}`. Lives in `artifacts/{feature_id}/` in Azure Blob Storage.
- **Agent** — a Claude Code CLI subprocess defined by a Markdown file in `.agents/`. Each agent has a model, tools, and a system prompt.
- **Worker** — a long-running Python process that polls an Azure Storage Queue, runs the appropriate agent, and dispatches the next step.
- **State** — `artifacts/{feature_id}/state.json` is the source of truth for feature lifecycle. All updates are atomic via Azure blob lease.

## Project layout

```
.agents/            Agent definitions (model, tools, system prompt)
.claude/agents/     Claude Code skills (brainstorm, implement, azure-storage)
.pipeline/          Runtime config (queue → agent mapping, timeouts)
agentharness/       Python package
  models.py         Pydantic models — FeatureState, TaskMessage, AgentDefinition
  config.py         Load .pipeline/config.json
  storage.py        Azure Blob + Queue client wrappers
  state_manager.py  Lease-based atomic state.json updates
  prompt_builder.py Assemble prompt from agent MD + downloaded artifacts
  agent_runner.py   Subprocess wrapper for `claude -p ...`
  dispatcher.py     State machine transitions, fan-out/fan-in, review loop
  worker.py         Async worker loop
  brainstorm.py     Brief upload + planner enqueue (called by CLI + skill)
  tui.py            Textual real-time monitoring UI
  cli.py            Click entry points
tests/              Unit tests (pytest-asyncio)
```

## Claude Code skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `/brainstorm` | new feature idea | Discovery conversation → writes `brief.md` → uploads to Azure |
| `/implement {feat-id}` | after brainstorm | Enqueues planner task → starts autonomous pipeline |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter |

## CLI commands

```bash
agentharness brainstorm                        # interactive (terminal-only, uses os.execvp)
agentharness submit brief.md                   # upload brief, get feature ID (no pipeline)
agentharness implement feat-20260425-abc123    # enqueue planner, start pipeline
agentharness worker planner-queue              # run worker for one queue
agentharness worker developer-queue --concurrency 3
agentharness watch                             # Textual TUI, auto-refresh 2s
agentharness status feat-20260425-abc123       # one-shot status snapshot
agentharness list                              # all features
```

## State machine

```
brainstorming → analyzing → architecting → designing → planning → developing → reviewing → done
                                                                       ↑              |
                                                                  dev_revision ←------+
                                                                       |
                                                                   developing → reviewing
```

`failed` is reachable from any state after `dead_letter_threshold` retries or `max_revisions` revision rounds.

## Agent definitions (`.agents/*.md`)

YAML frontmatter controls runtime behaviour:

```yaml
---
id: developer
model: claude-sonnet-4-6
phase: developing
max_turns: 30
allowed_tools: [bash, read, write]   # maps to --allowedTools
visibility_timeout: 1800             # seconds worker holds the message
retry_limit: 3
output_parsing: none                 # none | task_list | review_result
---
System prompt...
```

- `allowed_tools: []` → plain `claude -p` (no tool use). Used for planner, architect, designer, reviewer.
- `allowed_tools: [bash, read, write]` → developer agents that write code.
- `output_parsing: task_list` → dispatcher extracts `### task: name` blocks from output to fan out developer tasks.
- `output_parsing: review_result` → dispatcher extracts `### task: name` + `**Status:** REVISION_NEEDED` blocks.

## Fan-out / fan-in

Designer publishes `N` developer tasks (parsed from `### task:` headers). Each developer worker, on completion, atomically updates `state.json` via blob lease and checks `all_tasks_complete("developing")`. The last worker to finish enqueues the review task — no external coordinator.

## Concurrency safety

`state_manager.StateManager.update()` acquires an Azure blob lease (30s) before read-modify-write. Only `HttpResponseError` with lease contention error codes trigger retry with exponential backoff. All other errors propagate immediately.

## Artifact naming

```
artifacts/{feature_id}/brief.md
artifacts/{feature_id}/spec.r1.md          # r{N} = revision number
artifacts/{feature_id}/arch-review.r1.md
artifacts/{feature_id}/design.r1.md
artifacts/{feature_id}/impl/{task}.r1.md   # per developer task
artifacts/{feature_id}/review/review.r1.md
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
