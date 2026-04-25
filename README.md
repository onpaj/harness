# AgentHarness

Distributed, event-driven pipeline for autonomous software development using specialized Claude AI agents. Describe a feature, the agents handle the rest.

```
brief.md → planner → architect → designer → developer(s) → reviewer → done
                                                  ↑               |
                                             dev_revision ←───────┘
```

## How it works

1. **Brainstorm** — describe your feature in a conversation with Claude Code. The agent asks clarifying questions and produces a structured `brief.md`.
2. **Upload** — the brief is stored in Azure Blob Storage under a unique feature ID.
3. **Implement** — a single command enqueues the first task. From here, agents run autonomously.
4. **Monitor** — a Textual TUI shows real-time pipeline status across all features.

Each agent is a Claude Code CLI subprocess, defined by a versioned Markdown file with a YAML frontmatter specifying model, tools, and timeouts. Agents communicate through artifacts (Markdown files in blob storage) and Azure Storage Queues.

## Requirements

- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) (`claude` in PATH, authenticated)
- Azure Storage account (Blob + Queues)
- Azure CLI (`az`) for setup and debugging

## Installation

```bash
git clone https://github.com/your-org/AgentHarness
cd AgentHarness
python -m venv .venv
.venv/bin/pip install -e .
```

## Configuration

### 1. Environment

```bash
cp .env.example .env
# Edit .env and fill in your Azure Storage connection string
```

`.env` is loaded automatically on startup — never commit it to version control.

### 2. Azure infrastructure

Use the `/azure-storage` Claude Code skill or run directly:

```bash
az storage container create --name pipeline-artifacts \
  --connection-string "$AZURE_STORAGE_CONNECTION_STRING"

for q in planner-queue architect-queue designer-queue developer-queue review-queue; do
  az storage queue create --name "$q" \
    --connection-string "$AZURE_STORAGE_CONNECTION_STRING"
done
```

### 3. Pipeline config

Edit `.pipeline/config.json` to point to your storage account and adjust timeouts.

## Usage

### With Claude Code (recommended)

Open this repository in Claude Code and use the built-in skills:

```
/brainstorm       → guided feature discovery, produces brief.md
/implement        → starts the autonomous pipeline for a feature
/azure-storage    → setup, inspect, and debug Azure storage
```

### CLI

```bash
# Upload a brief (no pipeline yet)
agentharness submit brief.md
# → Brief uploaded: feat-20260425-abc123
# → Start pipeline: agentharness implement feat-20260425-abc123

# Start the pipeline
agentharness implement feat-20260425-abc123

# Run workers (one process per queue, or multiple for developer-queue)
agentharness worker planner-queue &
agentharness worker architect-queue &
agentharness worker designer-queue &
agentharness worker developer-queue --concurrency 3 &
agentharness worker review-queue &

# Monitor
agentharness watch                              # real-time TUI
agentharness status feat-20260425-abc123        # snapshot
agentharness list                               # all features
```

## Pipeline phases

| Phase | Agent | Model | Role |
|-------|-------|-------|------|
| Planning | planner | claude-opus-4-6 | Transforms brief into structured spec |
| Architecting | architect | claude-opus-4-6 | Architecture assessment and guidance |
| Designing | designer | claude-sonnet-4-6 | UX/UI design, breaks work into developer tasks |
| Developing | developer | claude-sonnet-4-6 | Implements each task (has bash/read/write tools) |
| Reviewing | reviewer | claude-haiku-4-5 | Reviews against spec, marks pass/fail per task |

The reviewer can send failing tasks back to developers (up to 3 rounds by default).

## Artifacts

All artifacts are stored in Azure Blob Storage:

```
artifacts/{feature_id}/
  state.json           Feature lifecycle state (source of truth)
  brief.md             Original user brief
  spec.r1.md           Planner output
  arch-review.r1.md    Architect output
  design.r1.md         Designer output (includes task list)
  impl/
    {task}.r1.md       Developer implementation summary
    {task}.r2.md       After revision (if needed)
  review/
    review.r1.md       Reviewer output
```

## Agent definitions

Agents live in `.agents/` as Markdown files with YAML frontmatter:

```yaml
---
id: developer
model: claude-sonnet-4-6
max_turns: 30
allowed_tools: [bash, read, write]
visibility_timeout: 1800
output_parsing: none
---
System prompt...
```

Add or modify agents without changing Python code — just edit the Markdown and update `.pipeline/config.json`.

## Architecture

- **Queues** — one Azure Storage Queue per pipeline phase. Workers are stateless and can run on any machine with storage access.
- **State** — `state.json` per feature in blob storage, updated atomically via Azure blob lease (no database needed).
- **Fan-out** — designer emits `N` developer tasks; the last developer worker to finish triggers review (last-writer pattern).
- **Fault tolerance** — failed tasks return to queue after visibility timeout. After `dead_letter_threshold` failures, messages move to `{queue}-poison` for manual inspection.
- **Distribution** — run workers on any machine that has `AZURE_STORAGE_CONNECTION_STRING` and the `claude` CLI. No direct communication between workers required.

## Development

```bash
# Run tests
.venv/bin/pytest tests/ -v

# Add a new agent
# 1. Create .agents/{name}.md
# 2. Add to .pipeline/config.json
# 3. Add transition in agentharness/dispatcher.py
# 4. Create the Azure queue (/azure-storage skill)
```

## Project structure

```
.agents/            Agent definitions
.claude/agents/     Claude Code skills
.pipeline/          Runtime config
agentharness/       Python package
  models.py         Pydantic models
  config.py         Config loading
  storage.py        Azure client wrappers
  state_manager.py  Atomic state updates (blob lease)
  prompt_builder.py Prompt assembly
  agent_runner.py   Claude CLI subprocess
  dispatcher.py     State machine + fan-out/fan-in
  worker.py         Async worker loop
  brainstorm.py     Brief upload + pipeline kickoff
  tui.py            Textual monitoring UI
  cli.py            CLI entry points
tests/              Unit tests
```
