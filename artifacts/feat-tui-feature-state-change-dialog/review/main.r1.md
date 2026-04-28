# Code Review: TUI Feature State Change Dialog

## Summary
The implementation artifact (main.r1.md) is incomplete and does not provide sufficient detail to verify spec compliance. While test results are positive, the summary lacks architecture decisions, file modifications, implementation details, and explicit mapping of requirements to delivered features.

## Review Result: REVISION_NEEDED

### task: main
**Status:** REVISION_NEEDED
**Issues:**
- **Missing implementation summary** — File does not describe what was actually built: which files were created, which were modified, what architectural patterns were used, or how each functional requirement was addressed.
- **No evidence of spec compliance mapping** — Spec defines 9 functional requirements (FR-1 through FR-9) plus NFRs and data model changes. The summary should explicitly confirm each is complete (e.g., "FR-1: Keybinding `S` added to PipelineMonitor; tested in test_tui_state_change.py:test_open_state_change_with_selected_feature").
- **No architecture decisions documented** — Per arch-review, three critical decisions were proposed: (1) separate `state_change.py` module, (2) `STATE_TO_QUEUE` in `dispatcher.py`, (3) extract `build_phase_task()` helper. Summary should confirm each decision was implemented as designed and list the actual files/functions created.
- **Incomplete file inventory** — Implementation should list: new files (`agentharness/state_change.py`, `agentharness/tui_state_change.py`, `tests/test_state_change.py`, `tests/test_tui_state_change.py`), modified files (`agentharness/tui.py`, `agentharness/dispatcher.py`, `agentharness/models.py`, `agentharness/run_task.py`), with line counts or key changes per file.
- **Test coverage not mapped to spec** — Tests reported as "88 feature-specific tests all green" but summary does not identify which tests cover which requirements. Should list: FR-1 (keybinding test), FR-2 (modal layout/navigation tests), FR-3 (restart test), FR-4 (rollback tests with/without task clearing), FR-5 (fail mode test), FR-6/FR-8 (error scenarios), FR-9 (disallowed state guard), NFR-1 (latency), NFR-2 (no secrets exposed).
- **Data model changes not detailed** — Spec open question 1 asks whether `with_tasks_cleared()` was added to `FeatureState`. Summary should confirm this helper exists with example usage.
- **State→Queue mapping not documented** — Architecture specifies `STATE_TO_QUEUE` constant in `dispatcher.py` and extraction of `queue_for_state()` helper. Summary should show the mapping and confirm it aligns with canonical state order.
- **Orphan task handling not confirmed** — Spec FR-7 and architecture decision 6 require a defensive guard in `run_task.run_task()` to drop orphaned task messages with an event. Summary should confirm this is implemented.
- **Missing documentation update guidance** — No mention of updates to `CLAUDE.md` (new CLI commands?), agent definitions (if any phases changed), or inline docstrings in new modules.

## Docs to Update
- `CLAUDE.md` — Add `agentharness watch` / `agentharness status` documentation if the feature adds new CLI surface (though state-change appears TUI-only, verify).
- Module docstrings in new files (`agentharness/state_change.py`, `agentharness/tui_state_change.py`) — ensure public APIs are documented.
- Inline comments in `dispatcher.py` on `STATE_TO_QUEUE` and `build_phase_task()` explaining the contract for downstream callers.

## Overall Notes
The test suite is green, which is a strong signal, but the implementation summary reads as a partial session log rather than a formal delivery document. Rewrite main.r1.md to:
1. Open with a 2-3 sentence executive summary of what was delivered
2. List all files created and all files modified, with 1-2 lines per file describing the change
3. Explicitly confirm each of the 9 functional requirements + NFRs in a checklist or bullet list
4. Document the three architectural decisions and confirm they were implemented as designed
5. Summarize test coverage, with a table mapping test names to spec requirements
6. Confirm no regressions (pre-existing 11 failures unchanged)

Once the summary is complete and detailed, it should be trivial to confirm PASS.