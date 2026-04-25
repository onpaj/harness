# Feature Brief: Per-Agent Mandatory Context Files

## Problem Statement
Consumers of AgentHarness have no way to provide domain-specific context (design libraries, coding standards, architecture docs) to individual agents. Every agent runs with only the feature artifacts — there's no mechanism to inject shared, reusable files that apply globally to a specific agent type.

## Goals
- Allow consumers to declare local filesystem paths (files or directories) per agent in `config.json`
- Have those files automatically read and injected into the agent's prompt at runtime

## Functional Requirements
- `config.json` supports a new optional `context_files` field per agent entry, accepting a list of local filesystem paths (files or directories)
- At runtime, before the agent prompt is assembled, all declared paths are resolved and their contents are read from the local filesystem
- File contents are injected into the agent prompt as clearly labelled context blocks (e.g. `### Context: /docs/design_library/tokens.md`)
- Directories expand to all files within them (non-recursive by default, recursive opt-in via trailing `**`)
- Missing or unreadable files produce a clear warning (logged) but do not abort the pipeline
- The feature is purely additive — agents with no `context_files` entry behave exactly as before

## Non-Functional Requirements
- File reads happen once per task dispatch, not on every retry
- No size limit enforced by the harness, but documentation should warn about prompt bloat
- Works on any OS path format supported by Python's `pathlib`

## Technical Constraints
- Config loaded via `agentharness/config.py` from `.pipeline/config.json`
- Prompt assembled in `agentharness/prompt_builder.py`
- Must not break existing agent definitions or config structure

## Out of Scope
- Fetching files from Azure Blob or remote URLs
- Per-feature context files (only global, per-agent-type)
- Hot-reloading config changes without worker restart

## Success Criteria
- A designer agent configured with `context_files: ["/docs/design_library"]` receives those file contents in its prompt
- Existing agents with no `context_files` pass all existing tests unchanged
- Unit tests cover: path resolution, directory expansion, missing file warning, prompt injection format

## Additional Context
Primary use cases: design token files for designer agent, coding standards for developer agents, architecture decision records for architect agent.
