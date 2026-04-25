# Feature Brief: Artifact Browser in TUI

## Problem Statement
Users running AgentHarness have no way to inspect pipeline artifacts without leaving the terminal or manually navigating Azure Blob Storage. The TUI shows pipeline status but offers no way to read what agents actually produced.

## Goals
- Allow users to browse and read all artifacts for any feature directly inside the TUI watch command.

## Functional Requirements
- Add an artifact browser panel or screen to the existing Textual TUI (`agentharness watch`)
- List all features, then list all artifacts for a selected feature (brief.md, spec, arch-review, design, impl files, review)
- On selection, display the artifact content in a readable pane
- Navigation via keyboard (arrow keys, enter to open, escape/back to return)
- All artifact types must be supported: brief.md, spec.rN.md, arch-review.rN.md, design.rN.md, impl/{task}.rN.md, review/review.rN.md, state.json

## Non-Functional Requirements
- Artifact content is fetched from Azure Blob Storage on demand (no pre-caching)
- UI must remain responsive during fetch (async)
- Should integrate cleanly into the existing Textual TUI without disrupting the main pipeline monitor view

## Technical Constraints
- Python + Textual framework (existing TUI in `agentharness/tui.py`)
- Azure Blob Storage via existing `agentharness/storage.py` client
- Read-only — no writes, no pipeline actions triggered from this view

## Out of Scope
- Editing artifacts
- Triggering pipeline actions from artifact view
- Copying artifacts to clipboard or opening in external editor
- Diffing artifact revisions

## Success Criteria
- User can open TUI, navigate to any feature, browse its artifact list, and read any artifact without leaving the terminal
- All artifact types are accessible
- UI remains responsive while loading artifact content from Azure

## Additional Context
Artifacts live in Azure Blob Storage under `artifacts/{feature_id}/`. The storage client already supports listing and downloading blobs. The TUI is built with Textual and currently shows a pipeline monitor with queue depths and event logs.
