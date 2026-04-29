Design document written to `artifacts/feat-raw-github-issue-tui-visibility-auto-con/design.r1.md`.

Key decisions captured:

- **`FeatureState.is_raw`** — computed property (`not self.history`), never serialised; all guards call it instead of inspecting the list.
- **`slug_title`** — single top-level function in `github_state.py`, shared by synthesis and matching; algorithm documented as a byte-for-byte contract with `/convertforagent`.
- **`list_features` modification** — raw issues fall back to `_synthesize_raw_state` instead of being dropped; the existing `log.warning` is removed (silenced).
- **`patch_existing_issue`** — public method on `GitHubStateManager` only (not on the `StateBackend` protocol); uses `_replace_state_block` for idempotent body construction.
- **`_convert_raw_issue`** — side-effect order is branch → artifact upload → issue patch, designed for safe retry; total API budget is 4–6 calls, bounded.
- **`enqueue_planner` preflight** — single `get()` call (not `list_features()`); `ValueError` propagates to TUI/CLI.
- **TUI guard** — single `if state.is_raw: self.notify(...); return` in `action_open_state_change`; the `i` key path requires no TUI changes.