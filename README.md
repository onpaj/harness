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

Each agent is a Claude Code CLI subprocess. State lives in a pluggable backend (Azure Blob Storage or GitHub). Queues drive execution — no central scheduler.

## Quickstart

### Setup

```bash
pip install -e ".[dev]"
cp .env.example .env
# Choose your backend: set "storage_backend" in .pipeline/config.json
# See Environment section below for required variables
```

**Azure backend** — set `"storage_backend": "azure"` in `.pipeline/config.json`:
```bash
AZURE_STORAGE_CONNECTION_STRING=...
agentharness init      # scaffold Azure queues and containers
```

**GitHub backend** — set `"storage_backend": "github"` in `.pipeline/config.json`:
```bash
GITHUB_TOKEN=ghp_...
# GITHUB_OWNER and GITHUB_RUNS_REPO auto-detected from git remote, or set explicitly
```

### Run the pipeline

```bash
agentharness brainstorm                         # interactive brief → uploads to backend
agentharness submit brief.md                    # upload existing brief, get feature ID
agentharness implement feat-20260425-abc123     # enqueue first task, start pipeline
agentharness observe                            # start observer (primary execution mode)
agentharness watch                              # Textual TUI, auto-refresh 2s
```

## Deployment (local machine, targeting a different project)

This section covers running AgentHarness locally while targeting a **different GitHub repository** — the common case where you install the harness once and run it against whichever project you're working on.

### Prerequisites

- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) installed and authenticated (`claude --version`)
- `git` ≥ 2.38 (for worktree support)
- A GitHub personal access token with `repo` and `workflow` scopes

### 1. Install

```bash
git clone https://github.com/pajgrtondrej/AgentHarness.git
cd AgentHarness
python -m venv .venv
.venv/bin/pip install -e .
```

Verify:

```bash
.venv/bin/agentharness --version
```

### 2. Configure for a target project

Copy the env template and fill in your target repo:

```bash
cp .env.example .env
```

Set `"storage_backend": "github"` in `.pipeline/config.json`, then edit `.env`:

```bash
GITHUB_TOKEN=ghp_your_token_here
GITHUB_OWNER=target-org-or-user    # owner of the project you want to develop
GITHUB_RUNS_REPO=target-repo       # repo where issues/branches will be created
```

`GITHUB_OWNER` and `GITHUB_RUNS_REPO` tell AgentHarness which repo to use for task queues and artifact branches. Set them explicitly when the harness is not cloned from the target project's remote.

### 3. Verify GitHub access

```bash
gh repo view $GITHUB_OWNER/$GITHUB_RUNS_REPO
```

The token must have read/write access to issues and branches on the target repo.

### 4. Start the observer

Run from the AgentHarness directory:

```bash
.venv/bin/agentharness observe
```

The observer polls the target repo's issues for queued tasks and spawns agent subprocesses as work arrives. It clones the target repo into `.runs-cache/owner/repo/` on first use.

### 5. Submit work

In a separate terminal (or Claude Code session in the target project), use the `/brainstorm` skill or CLI:

```bash
.venv/bin/agentharness brainstorm          # interactive → uploads brief
.venv/bin/agentharness implement <feat-id> # kick off the pipeline
```

Or set `AGENTHARNESS_CONFIG` to an absolute path if you want to run commands from outside the AgentHarness directory:

```bash
export AGENTHARNESS_CONFIG=/path/to/AgentHarness/.pipeline/config.json
agentharness observe
```

### What happens under the hood

1. `brainstorm` uploads `brief.md` to the target repo branch and creates a GitHub issue for the analyst task.
2. The observer picks up the issue, spawns `agentharness _run_task`, which runs the analyst Claude agent.
3. Each subsequent agent (architect → designer → planner → developer → reviewer) runs the same way.
4. The developer agent clones the target repo into `.runs-cache/`, writes code there, commits, and pushes to a `feature/{feat-id}` branch.
5. When the pipeline completes the feature branch is ready for a PR against the target repo.

### Notes

- **Agent context:** Developer agents write to `.runs-cache/{owner}/{repo}/artifacts/{feat-id}/`. Add target-project files to `context_files` in `.agents/developer.md` so agents have project context.
- **Logs:** `agentharness observe` writes structured JSON logs to stdout. Pipe to `jq` for filtering.
- **Concurrency:** The observer handles one task at a time per queue by default. GitHub's unified poller runs on a 15-second cycle (configurable via `github_poll_interval_seconds` in `.pipeline/config.json`).
- **Cleanup:** Stale task claims (idle > 150 s) are swept automatically by the observer.

## CLI reference

| Command | Description |
|---------|-------------|
| `brainstorm` | Interactive discovery → writes `brief.md` → uploads to Azure |
| `submit <brief>` | Upload brief, return feature ID (no pipeline start) |
| `implement <feat-id>` | Enqueue analyst task, start autonomous pipeline |
| `observe` | Start observer: polls all queues, spawns subprocess per task |
| `watch` | Textual TUI, auto-refresh 2s |
| `status <feat-id>` | One-shot status snapshot |
| `list` | List all features |
| `init` | Initialize project scaffolding (queues, container) |

## Execution modes

**Observer mode (primary):** `agentharness observe` — a single process polls all queues and spawns `agentharness _run_task` as a subprocess per message. Tasks run in isolation; the observer manages visibility renewal and graceful shutdown.

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

**Azure backend:** `StateManager.update()` acquires an Azure blob lease (30s) before read-modify-write. Lease contention retries with exponential backoff.

**GitHub backend:** Issue state updates are atomic via GitHub's API. The observer runs a stale claim sweeper to clean up abandoned task claims.

All other errors propagate immediately.

## Claude Code skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `/brainstorm` | new feature idea | Discovery conversation → writes `brief.md` → uploads to configured backend |
| `/implement {feat-id}` | after brainstorm | Enqueues analyst task → starts autonomous pipeline |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter (Azure backend only) |

## Backends

AgentHarness supports two pluggable storage backends:

### Azure backend (default)

**Uses:** Azure Blob Storage for artifacts, Azure Storage Queues for work queue, blob leases for atomic state updates.

**Requirements:**
- Azure Storage account
- Connection string in `AZURE_STORAGE_CONNECTION_STRING`

**config.json:**
```json
{ "storage_backend": "azure" }
```

**.env:**
```bash
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
```

**Setup:**
```bash
agentharness init      # Creates containers and queues
```

### GitHub backend

**Uses:** GitHub Issues (with labels) as work queue, git branches as artifact store, issue state (labels + JSON body) as state manager.

**Requirements:**
- GitHub token with repo read/write and workflow access

**config.json:**
```json
{ "storage_backend": "github" }
```

**.env:**
```bash
GITHUB_TOKEN=ghp_...
# GITHUB_OWNER=owner       # optional (auto-detected from git remote)
# GITHUB_RUNS_REPO=repo    # optional (auto-detected from git remote)
```

**No manual setup needed** — issues and branches are created dynamically.

## Environment

The storage backend is selected via `"storage_backend"` in `.pipeline/config.json` (`"azure"` or `"github"`). Credentials go in `.env`:

```bash
cp .env.example .env
# Set backend credentials — see Backends section above
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
4. Backend setup:
   - **Azure:** Use `/azure-storage` skill → "create queue {name}-queue"
   - **GitHub:** No manual setup needed (issues are created dynamically)
