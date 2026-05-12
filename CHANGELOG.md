# CHANGELOG


## v0.8.0 (2026-05-12)

### Features

- Order features by ID ascending throughout (lowest ID first)
  ([`543b9ce`](https://github.com/onpaj/harness/commit/543b9ce5f4875a61022b6c73fd5a81dc33535baa))

- github_state.list_features(): fetch with direction=asc and sort by issue number ascending so
  oldest/lowest-ID features come first - tui._load_all_states(): replace active-first/updated_at
  sort with simple feature_id ascending sort - Update test to reflect ascending order


## v0.7.1 (2026-05-12)

### Bug Fixes

- Sync agentharness-task-state JSON block with label on task status changes
  ([`3982e39`](https://github.com/onpaj/harness/commit/3982e39b7426087792c7b8737c145c18d09b2329))

Task queue issues now carry an `agentharness-task-state` fenced block alongside the existing
  `agentharness-task` block. The status field in that block is kept in sync with the label on every
  transition: - claim_issue: queued → in_progress - delete_message: in_progress → completed -
  move_to_dead_letter: in_progress → dead_letter - _reclaim_issue: in_progress → queued (stale claim
  reset)


## v0.7.0 (2026-05-12)

### Documentation

- Update install instructions to use uv and git URL
  ([`a8d50e3`](https://github.com/onpaj/harness/commit/a8d50e3e3e7b3b1f7654f6f5d9352663e172cb41))

Replace pip/venv setup with uv tool install from git URL and drop .venv/bin/ prefixes throughout the
  deployment guide and test section.

### Features

- Order tasks by ID asc in TUI and auto-mode candidate selection
  ([`274b104`](https://github.com/onpaj/harness/commit/274b104400c241828721d0022604b47581ff710c))

- TUI task panel: sort tasks by task_id ascending before rendering - Observer auto-mode: pick
  candidate by feature_id asc instead of created_at; raw GitHub issues sort after known features
  (raw- > feat- lexicographically) - Update auto-mode tests to reflect ID-based ordering


## v0.6.4 (2026-05-12)

### Bug Fixes

- Sync working branch from remote and base before each agent task
  ([`0dc626e`](https://github.com/onpaj/harness/commit/0dc626e25297da461e821cb640c4db7eb14b13eb))

Before each task the GitHubArtifactStore now fetches origin, fast-forwards the feature branch
  (falling back to -X ours on conflict), and merges in the default base branch so agents always
  start on an up-to-date working tree. This prevents push failures when another feature was merged
  to the target branch in parallel.


## v0.6.3 (2026-05-12)

### Bug Fixes

- Use spec artifact title for PR instead of generic brief heading
  ([`07e859b`](https://github.com/onpaj/harness/commit/07e859bc2f7c578b31883d3f04eb60f140ee1a9b))

Brief templates use section headers like '## Module' that produce useless PR titles like 'feat:
  Module'. The analyst spec always has a descriptive heading, so prefer it as the primary title
  source.

Adds _extract_spec_title() that strips analyst prefixes ('Specification: ' etc.) and updates
  _build_pr_content() to download and apply the spec title, falling back to the brief heading when
  the spec is unavailable.


## v0.6.2 (2026-05-12)

### Bug Fixes

- Allow state changes from failed features and add product-queue to init template
  ([`6e65aea`](https://github.com/onpaj/harness/commit/6e65aea7d81d96f58282101e91fd0b4ba496276d))

- TUI state-change modal now shows all canonical rollback targets when the current status is
  `failed` (previously the list was empty) - Rollback from `failed` adds a `phase_resumed` event so
  the retry counter resets — without this the re-enqueued task would exhaust its limit immediately
  and fail again - `agentharness init` template now includes `product-queue`; omitting it caused
  features to fail when the analyst returned HAS_QUESTIONS


## v0.6.1 (2026-05-12)

### Bug Fixes

- Remove brief.md written to worktree root and show auto-mode in TUI status bar
  ([`3a4404f`](https://github.com/onpaj/harness/commit/3a4404f8a10512ba9f4bed81b7346abb80bbdb96))

- Remove erroneous write of brief.md to clone root — store.upload already commits it to
  artifacts/{feature_id}/brief.md on the feature branch, and run_task.py re-downloads it there
  before the analyst runs. Root-level brief.md caused merge conflicts across features sharing the
  same clone. - Show auto-mode on/off indicator in TUI StatusBar, updated every refresh cycle.


## v0.6.0 (2026-05-12)

### Features

- Auto-mode bootstraps raw agent-labeled issues without prior pipeline state
  ([`2c1c510`](https://github.com/onpaj/harness/commit/2c1c5104a338dd871fc0c25e7b7d5cc570fc8bfd))

Previously auto-mode only started features already in 'brainstormed' state (created via the
  implement label flow). Now it also picks up any open issue carrying the feature-marker label
  (agent) that has no feat:/state:/queue: labels, bootstrapping it and enqueuing the analyst
  immediately.

Candidates from both paths are sorted by created_at so the oldest eligible issue always runs first
  regardless of whether it was pre-bootstrapped or raw.


## v0.5.2 (2026-05-12)

### Bug Fixes

- Auto-mode now starts all brainstormed features including epic children
  ([`fd9d327`](https://github.com/onpaj/harness/commit/fd9d32781deaf98b462ba4305516ba80d6d56bef))

Previously the candidate filter excluded features with epic_parent set, so brainstormed epic
  children were visible in the TUI but never picked up. All features shown as brainstormed in the
  TUI are now eligible.


## v0.5.1 (2026-05-12)

### Bug Fixes

- Enforce conventional commit format on PR titles and fall back to brief body for PR description
  ([`ad23ef7`](https://github.com/onpaj/harness/commit/ad23ef7b9345f43ae03a00468c678bc9d0f0d290))

PR titles derived from brief headings now always follow conventional commits format (e.g. "feat:
  Telemetry" instead of "Telemetry"). When the developer impl artifact lacks a ## PR Summary
  section, the PR description falls back to the brief content instead of the raw phase log.


## v0.5.0 (2026-05-12)

### Features

- Allow architect to skip design phase for non-UI features
  ([`5fde7f3`](https://github.com/onpaj/harness/commit/5fde7f3e161520a652427ac546b67a449cdeac9b))

The designer agent previously ran unconditionally after every architect review. The architect now
  emits `## Skip Design: true` in its output for backend-only work (performance fixes, migrations,
  refactors, etc.), causing the dispatcher to jump straight from architecting to planning and bypass
  the designer entirely.


## v0.4.0 (2026-05-12)

### Features

- Introduce observer auto mode with TUI toggle
  ([`9077e39`](https://github.com/onpaj/harness/commit/9077e39f36b2b06ceb3bf71c5a966d602094eca2))

Add opt-in auto mode that drains brainstormed features one at a time serially. When enabled, the
  observer picks the oldest brainstormed feature (by created_at) and calls enqueue_planner when no
  other feature is actively running.

- agentharness/auto_mode.py: sentinel-file toggle (logs/auto-mode.enabled) - observer.py:
  _auto_mode_loop runs alongside queue pollers; checks active statuses across all features before
  dispatching; skips epic children conservatively - config.py: auto_mode (bool) and
  auto_mode_poll_seconds (float, 60s) - cli.py: agentharness observe --auto threads flag to _observe
  subprocess - tui.py: 'a' binding toggles auto mode live with toast notification; no observer
  restart needed — toggle takes effect on next poll cycle - 30 new tests covering toggle module,
  loop behaviour, and config defaults


## v0.3.7 (2026-05-06)

### Bug Fixes

- Make TUI resilient to transient GitHub API failures
  ([`6d0662d`](https://github.com/onpaj/harness/commit/6d0662d4d6ec8c4bf0da80147a79db1a3e68a0d4))

Adds retry logic to GitHubClient for idempotent requests (GET/HEAD) on 5xx/429 and httpx network
  exceptions, with 0.5s/1.5s backoff and a Retry-After cap of 5s. Explicit httpx.Timeout(connect=5,
  read=15) replaces the implicit 5s default that caused crashes when GitHub was slow.

Guards the 2s refresh tick (_refresh_data) so a failed poll shows '⚠ refresh failed: GitHub 503' in
  the StatusBar instead of crashing the TUI. Previous state is preserved across failures and the
  indicator clears on recovery. Action workers (_do_implement, _do_purge_queues, _do_resume_task)
  now surface errors via notify() instead of printing tracebacks on shutdown.


## v0.3.6 (2026-05-06)

### Bug Fixes

- Handle "no changes added to commit" in artifact upload
  ([`6bda14e`](https://github.com/onpaj/harness/commit/6bda14e71312e3c3702357a0eff3d50aa904e2bd))

git emits this message instead of "nothing to commit" when working-tree files are modified but
  nothing is staged — which occurs on idempotent re-uploads where the artifact is already on the
  branch.


## v0.3.5 (2026-05-05)


## v0.3.4 (2026-05-05)

### Bug Fixes

- Max turns
  ([`99feef4`](https://github.com/onpaj/harness/commit/99feef4589b4eb0e9f36a0f5c1146a0470fd020a))


## v0.3.3 (2026-05-05)

### Bug Fixes

- Fast-forward in commit_workdir_changes to prevent non-fast-forward push
  ([`e1c9a1c`](https://github.com/onpaj/harness/commit/e1c9a1c0660cfec8a3c36809b9e3fb3b5ef00dd0))

- Fast-forward local branch before artifact upload to avoid non-fast-forward push rejection
  ([`c609b1c`](https://github.com/onpaj/harness/commit/c609b1c444c4124e902b81c097e631cb94b38e32))

When sequential agents (e.g. analyst then architect) each upload artifacts to the same feature
  branch, the second agent's local clone is behind the remote after the first agent's push. The
  plain push then fails with non-fast-forward rejection. Merging --ff-only after checkout brings the
  local branch up to date before committing the new artifact.

- Reset retry counter after phase_resumed; raise architect max_turns to 50
  ([`ea691e3`](https://github.com/onpaj/harness/commit/ea691e37746ef54a067b85d9493d53897978bf99))

Two bugs caused the architect phase to repeatedly fail after a manual resume:

1. _recover_task counted all historical task_requeued events across runs, so phase_resumed never
  reset the counter — any exception after a manual resume immediately exhausted retries and killed
  the feature. Fixed by counting only requeues since the most recent phase_resumed or
  pipeline_started event.

2. architect max_turns was 10, but complex codebases (C#+React monorepo) require ~47 tool calls for
  thorough codebase exploration. The agent hit error_max_turns on every attempt. Raised to 50.


## v0.3.2 (2026-05-05)

### Bug Fixes

- Load .env from project root, not package install path
  ([`601a4e4`](https://github.com/onpaj/harness/commit/601a4e487a7b4e0a39fe80f886c9cec3c9e287d5))

load_dotenv() at module level resolves relative to the installed package path, never finding the
  user's project .env. Load it explicitly from the project root (parent of .pipeline/) inside
  load_config() instead.

- Place harness comment directly before its variables in .env
  ([`e38390d`](https://github.com/onpaj/harness/commit/e38390de037586f0fc591ccc16b47efaf45ebb88))


## v0.3.1 (2026-05-05)

### Bug Fixes

- Use auto-detected env values silently, only prompt for missing ones
  ([`e83d692`](https://github.com/onpaj/harness/commit/e83d6920d5a879535ac7700ab6bdc8d8c9b50343))


## v0.3.0 (2026-05-05)

### Features

- Auto-run gh auth login in agentharness init when not authenticated
  ([`17a1bfb`](https://github.com/onpaj/harness/commit/17a1bfb6dc1525c1c4d8356ee1dac93942abf8bc))


## v0.2.0 (2026-05-05)

### Features

- Semantic versioning with conventional commits
  ([`cc00385`](https://github.com/onpaj/harness/commit/cc00385afbedf50571a8066abe2903a76cc03600))

- Add python-semantic-release config to pyproject.toml - Replace publish.yml with release.yml:
  triggers on push to master, auto-bumps version from conventional commits, publishes to PyPI - Fix
  agentharness init .env handling: merge missing values instead of skipping when file already exists


## v0.1.1 (2026-05-05)

### Bug Fixes

- Agents
  ([`cbfe537`](https://github.com/onpaj/harness/commit/cbfe5376f10cc8242e9acffed63442c7516acb20))

- Cleanup
  ([`758335c`](https://github.com/onpaj/harness/commit/758335c07fce901a54f8e18a476f066ffe44c03b))

- Close state_mgr in cli, move sha fetch inside branch-creation guard
  ([`b5de192`](https://github.com/onpaj/harness/commit/b5de1927cf52cbfa661b898d86d89f975aabab00))

Fix 1: In _implement_with_epic_check, add await state_mgr.close() in the finally block to ensure the
  state manager is properly closed on all paths. Updated all relevant tests to assert
  state_mgr.close.assert_called_once().

Fix 2: In _convert_raw_issue, move the get_default_branch and get_ref calls inside the
  branch-creation guard (epic_position is None or epic_position == 1). This avoids redundant API
  calls for epic child N>1 where the SHA is never used. Updated tests to assert these calls are NOT
  made for N>1 child cases.

Fixes found in code review of epic-support feature.

- Close state_mgr in enqueue_planner; prefer initialized over raw in dedup
  ([`95d4bf0`](https://github.com/onpaj/harness/commit/95d4bf0e84f5e6cb735adad80fbc194335f82ded))

- Add try/finally to enqueue_planner to ensure state_mgr.close() is always called, preventing httpx
  connection pool leaks on GitHub backend - Fix list_features dedup logic to prefer initialized
  state over raw issues, regardless of issue number (only compare numbers when both are same type) -
  Add tests verifying state_mgr closure in both success and error paths - Update dedup test to
  verify initialized issue is kept over newer raw issue - Add test for two initialized issues where
  newer wins

- Gh orchestration
  ([`031fa82`](https://github.com/onpaj/harness/commit/031fa8229d68ec60532521369a31079a7f254098))

- Github targetting
  ([`c687db3`](https://github.com/onpaj/harness/commit/c687db3d8fcec4fa62038cfb097494f6425e8970))

- Gitignore
  ([`bf42add`](https://github.com/onpaj/harness/commit/bf42addc053e441d115ef017b54fefd6fd4e20b5))

- Handle GitHubApiError in epic gate, extract print helper
  ([`e7925ea`](https://github.com/onpaj/harness/commit/e7925ea484850f8028d77a1f5681d9bb629bd7a1))

- Wrap get_issue() call in try/except to handle GitHubApiError gracefully - Print warning and
  proceed when parent epic cannot be accessed - Extract repeated "Pipeline started" print logic into
  _print_started() helper - Add test for GitHubApiError case: verify warning is printed and enqueue
  proceeds

- Ignore PR, show just issues
  ([`554fa0b`](https://github.com/onpaj/harness/commit/554fa0b71b310046dae3d5e41d179b56d34df64d))

- Local updates
  ([`63757d2`](https://github.com/onpaj/harness/commit/63757d209cb362ca28bc824616e9b7c7002d2a00))

- Paginate list_sub_issues, guard empty payload in update_pull_request
  ([`7aea07a`](https://github.com/onpaj/harness/commit/7aea07a80941ce1304dd3fd9f0285ed64c7432d5))

- Pass per_page=100 to list_sub_issues to avoid silent truncation at GitHub's default page size;
  documents the 100-item limitation - Raise ValueError in update_pull_request when called with
  neither body nor draft, preventing silent no-op PATCH requests - Add test:
  test_update_pull_request_requires_at_least_one_field

- Remove broken force-include from pyproject.toml
  ([`057827c`](https://github.com/onpaj/harness/commit/057827c0802dd7255aaa2aa255d244705c546cd1))

Data files are already bundled under agentharness/data/ — force-include was pointing at empty
  repo-root .agents dir and breaking pip builds.

- Resolve final review issues — stale import, dead code, connection leak, broken test import
  ([`c9c723e`](https://github.com/onpaj/harness/commit/c9c723eeab07374c56e50581a9134c81ff9dc385))

- Review closes issue
  ([`2b8635a`](https://github.com/onpaj/harness/commit/2b8635a74d9cc24d8a946f6594eb6c9b33e03613))

- Set get_work_dir as sync mock in TestOrphanTaskGuard tests
  ([`e81743c`](https://github.com/onpaj/harness/commit/e81743c4284381571aa7b336abba95b22b312fd3))

- Stage
  ([`d1045bc`](https://github.com/onpaj/harness/commit/d1045bc5013a2466e38e28d2a57a263cf929153d))

- Store branch for epic children, dedupe list_sub_issues, add checkout tests
  ([`02fe0d2`](https://github.com/onpaj/harness/commit/02fe0d2b028f23777e88c67a8dd5092a660d1110))

- Move GitHubArtifactStore creation to after branch_name is resolved so epic children use the
  correct epic branch (not feature_id) for all git operations in upload() - Guard store.close() in
  finally block against None when store was never created (e.g. issue-not-found error path) - Reuse
  sub_issues list from position-computation step instead of making a second list_sub_issues() call
  for the N>1 sibling check - Add three unit tests for _checkout_or_create covering local branch,
  remote-only branch, and brand-new branch fallback paths

- Tick first-child checkbox, paginate list_pull_requests, cleanup
  ([`34c6d50`](https://github.com/onpaj/harness/commit/34c6d50450a3d2c5912b1dc288f7d0ba498d220f))

- Tick the first epic child's own checkbox immediately after opening the draft PR (Fix 1) - Update
  test_opens_draft_pr_for_first_child to assert update_pull_request is called for checkbox tick -
  Paginate list_pull_requests with the same while-True loop pattern as list_issues (Fix 2) - Move
  EPIC_PAUSED import from deferred (inside handle_epic_child_failed) to module level (Fix 3) -
  Remove redundant f-string around parent.get('title') — use or-chain fallback instead (Fix 4) - Log
  warning when epic PR lifecycle or pause label is skipped on non-GitHub backend (Fix 5)

- Timeouts
  ([`9543cd2`](https://github.com/onpaj/harness/commit/9543cd2b6c6cec35017bfe7065400d11aa5ad426))

- Tui
  ([`190ea62`](https://github.com/onpaj/harness/commit/190ea6233eb17993fa1f7e78e82d3cd22cb4ffd4))

- Tui filter
  ([`2d3fb11`](https://github.com/onpaj/harness/commit/2d3fb1199ac61a80652e309e64afa6ddedb6591f))

- Update AzureStateManager.open_review signature to match protocol
  ([`b4e552d`](https://github.com/onpaj/harness/commit/b4e552dcc43c05d855e5a8ea864f65a41832daca))

- Updated skill
  ([`c94864a`](https://github.com/onpaj/harness/commit/c94864ac21faaea0fe52761b1ef79538475dc8eb))

- Updates
  ([`f6af3a4`](https://github.com/onpaj/harness/commit/f6af3a42c68e7558b4dfd3b89ce15ed21738ec51))

- Updates
  ([`374ce31`](https://github.com/onpaj/harness/commit/374ce31d34a7f78efeb1fd97696ada0e7bb2d4cb))

- Use correct product-queue name in STATE_TO_QUEUE
  ([`d07ca28`](https://github.com/onpaj/harness/commit/d07ca2860970be0c1d06339d653d26b77afdc68b))

- **models**: Clean up TestWithTasksCleared test style
  ([`343d0a1`](https://github.com/onpaj/harness/commit/343d0a11c5284ddc4111cdaed1ba942366abebd6))

Replace __import__ hack with direct import, fix >= to > in timestamp assertion, move import time to
  module level.

### Chores

- Add .runs-cache to gitignore and untrack clone directory
  ([`78705e7`](https://github.com/onpaj/harness/commit/78705e7583079cb6c72b3c6db2919c9345b044c0))

- Add httpx dependency for github client
  ([`12cf7e1`](https://github.com/onpaj/harness/commit/12cf7e14dbf9b69995300cc79cbc3ff669fb5f6f))

- Bump version to 0.1.1
  ([`7aed7a9`](https://github.com/onpaj/harness/commit/7aed7a9e21fdc73968107e0631861a0d19d5af07))

- Merge master into feat-tui-feature-state-change-dialog
  ([`eac0ce4`](https://github.com/onpaj/harness/commit/eac0ce448b81e045ee37a9d4d3a39b8f57ef5c48))

- Merge origin/master — storage abstraction refactor
  ([`9fbb3ef`](https://github.com/onpaj/harness/commit/9fbb3ef9bf85299ee6a14fc97a6752fb68e6f3e2))

Resolved conflicts from the storage-abstraction refactor: - dispatcher: _open_feature_pr now
  delegates to state_mgr.open_review() - github_state: parse_state_from_issue delegates to
  GitHubStateManager._parse_state_from_issue (strict=False preserved for embedded newlines) - tui:
  _do_resume_task/_resume_phase/_resume_dev_task use factory functions - tests: updated
  TestOpenFeaturePr and TestDispatchReviewResult for new API

- Remove tracked artifacts, venv, cache and tighten .gitignore
  ([`ec1931f`](https://github.com/onpaj/harness/commit/ec1931f7f0aa60fea466b4fc99a4af31aa884b9c))

- Untrack tests/__pycache__ and fix gitignore to cover all subdirs
  ([`4281b73`](https://github.com/onpaj/harness/commit/4281b73e2e0ca1a48928f45a9eb471c2c089c317))

### Documentation

- Add design spec for configurable feature marker label
  ([`e5428f2`](https://github.com/onpaj/harness/commit/e5428f269e06f9bfd8101d7b72bbfb9eb11c13f6))

- Add github backend env vars to .env.example and init command
  ([`8b18edb`](https://github.com/onpaj/harness/commit/8b18edb85f11be03704e9cc86f56df78e7490db6))

- Add github backend implementation plan
  ([`40616fe`](https://github.com/onpaj/harness/commit/40616fe73b90cadb59cce3264fdb6917db6ccc7b))

- Add product agent design spec for analyst open questions loop
  ([`3b50f75`](https://github.com/onpaj/harness/commit/3b50f75f3c779216305e8372d97eb9d67e4bb91c))

- Document feature_marker config and migration
  ([`cde66ec`](https://github.com/onpaj/harness/commit/cde66ec4ebd22a8880b1cb226ac494b8cb82be9e))

- Document optional real-stream fixture capture procedure
  ([`d6a3a9f`](https://github.com/onpaj/harness/commit/d6a3a9f11f0baa5125a140dd9c30323ca3bf642e))

- Pr summary design spec
  ([`d902386`](https://github.com/onpaj/harness/commit/d902386af75984ebaeae680c92ec7810b7057958))

- Remove STORAGE_BACKEND env var references and CLI changes for removed worker commands
  ([`014b394`](https://github.com/onpaj/harness/commit/014b394628d39dba681452bf3cb1525cf816a8a1))

- Update CLAUDE.md and README for github backend
  ([`6805714`](https://github.com/onpaj/harness/commit/6805714b2293f61f1f2e9a380fc594a1e6f2825e))

### Features

- Active agents
  ([`96d5b07`](https://github.com/onpaj/harness/commit/96d5b07e0b4422b5cd70debdcf93cea60c7005ce))

- Add ## PR Summary section to developer agent prompt
  ([`a21eb0f`](https://github.com/onpaj/harness/commit/a21eb0f2646518bc55c7d1e0981616b9f903b26d))

- Add _build_pr_content helper for PR title and summary
  ([`f020e32`](https://github.com/onpaj/harness/commit/f020e32b94f294efd9665d820191f519b7cb61e8))

- Add _convert_raw_issue helper for in-Python issue conversion
  ([`2d6b34b`](https://github.com/onpaj/harness/commit/2d6b34b6d7b1d8f9f9114d65ea4fa8144c5fdbc6))

- Add _extract_brief_title helper to dispatcher
  ([`1d79df8`](https://github.com/onpaj/harness/commit/1d79df8ff5596d879e87cb231e3fcbb531978f70))

- Add _extract_pr_summary helper to dispatcher
  ([`dccb403`](https://github.com/onpaj/harness/commit/dccb4039a06f4aafb7543f721d78e0e4f1212710))

- Add _last_developer_artifact helper to dispatcher
  ([`9f6044b`](https://github.com/onpaj/harness/commit/9f6044b18bea7e0a9529106666c67590f2207303))

- Add _parse_analyst_status, _latest_spec_revision helpers; update _artifacts_for_phase to support
  analyst loop
  ([`dac51f1`](https://github.com/onpaj/harness/commit/dac51f1875753ad823d3a052b8ad264868b22092))

- Task 7: Add _parse_analyst_status helper to parse analyst's '## Status:' line (COMPLETE vs
  HAS_QUESTIONS) - Task 8: Add _latest_spec_revision helper to compute spec revision from
  current_analyst_iteration - Task 9: Replace _artifacts_for_phase signature to accept state instead
  of feature_id; implement accumulator logic for analyzing and questioning phases to include prior
  specs and answers; update architecting/designing/planning to use latest_spec_revision - Task 10:
  Replace remaining hard-coded spec,1 references with _latest_spec_revision in _dispatch_fan_out,
  _enqueue_per_task_review, and build_phase_task reviewing branch

All 62 tests pass (21 new tests added)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add _synthesize_raw_state for surfacing raw labelled issues
  ([`c8d2ea7`](https://github.com/onpaj/harness/commit/c8d2ea79f4827592f64070efb2b72bc7cfe53fed))

- Add backend factory functions to storage.py and tests
  ([`6174fc3`](https://github.com/onpaj/harness/commit/6174fc340d76dd6d88ab0bb0142eb63efb1db49a))

Add create_artifact_store, create_task_queue, and create_state_manager factory functions that
  dispatch on config.storage_backend ("azure"|"github"), returning the appropriate backend instance.
  All three are exported via __all__. Include 7 unit tests covering both backends and the ValueError
  guard.

- Add brief for feat-agentharness-landing-page
  ([`19a2637`](https://github.com/onpaj/harness/commit/19a2637dc42002c7b0b69b92377ae183da077cb5))

- Add brief for feat-agentharness-landing-page
  ([`6c1cd2f`](https://github.com/onpaj/harness/commit/6c1cd2f5c75f36b3e07fde132343cb2012761f00))

- Add brief for feat-tui-feature-state-change-dialog
  ([`0ec9295`](https://github.com/onpaj/harness/commit/0ec92951881ce64c2a510d8bcc777732e0ca196f))

- Add epic_parent, epic_position, epic_branch to FeatureState
  ([`dd6c40b`](https://github.com/onpaj/harness/commit/dd6c40b1d0df827aed1d06edd8d895d546ac303e))

Add three optional backward-compatible fields to FeatureState: - epic_parent: parent epic issue
  number (int | None) - epic_position: 1-indexed position in sub-issue order (int | None) -
  epic_branch: shared branch name (str | None)

Fields default to None to maintain compatibility with existing state JSON. All 538 tests pass,
  including legacy deserialization tests confirming backward compatibility with state.json lacking
  these fields.

- Add EPIC_PAUSED label constant
  ([`113194c`](https://github.com/onpaj/harness/commit/113194cd0873bd09ad443835e88707add4020abf))

- Add feature_marker field to GitHubConfig
  ([`5be559a`](https://github.com/onpaj/harness/commit/5be559a19ebbf4fb77e43099a212a018141c6ff8))

- Add FeatureState.is_raw property for raw-feature detection
  ([`9dcbb21`](https://github.com/onpaj/harness/commit/9dcbb217801a912d1b9e44a99b306f1135f0687e))

- Add FeatureStatus.questioning, PipelineConfig analyst iteration fields, and
  with_analyst_iteration_incremented
  ([`291c3d6`](https://github.com/onpaj/harness/commit/291c3d6c3cb4d6b036cc49b6c38f51b974630e54))

- Add github backend dispatch to tui state loading, fix azure depth via protocol
  ([`74cb414`](https://github.com/onpaj/harness/commit/74cb414db8f97240f4d488b52f428377f6deec20))

Split _load_all_states and _load_queue_depths into backend-specific implementations
  (_load_states_azure/github, _load_depths_azure/github) with dispatchers that branch on
  config.storage_backend. Also replaces direct _client.get_queue_properties() access in the Azure
  path with the protocol-level get_depth() method.

- Add github backend path to brainstorm upload_brief and enqueue_planner
  ([`c8096b0`](https://github.com/onpaj/harness/commit/c8096b0559d1ddd0c668c50069e16be6b3838c7f))

- upload_brief() dispatches to _upload_brief_github() when storage_backend == "github": creates
  feature branch, commits brief.md, and creates initial FeatureState issue - enqueue_planner()
  dispatches to _enqueue_planner_github() when storage_backend == "github": uses create_task_queue
  to send analyst TaskMessage via GitHubTaskQueue - All existing Azure code paths unchanged - Unit
  tests in tests/test_brainstorm_github.py cover call ordering, artifact paths, and cleanup-on-error
  for both new functions

- Add GitHub labels for questioning and max_analyst_iterations config field
  ([`aa7a098`](https://github.com/onpaj/harness/commit/aa7a0980c7fbf60960a978246ec888f7f53092e5))

Task 4: Add FEAT_QUESTIONING and QUEUE_PRODUCT label constants to github_labels.py -
  FEAT_QUESTIONING = "feat:questioning" for the questioning state - QUEUE_PRODUCT = "queue:product"
  for the product queue - Updated FEAT_STATUS_LABELS frozenset to include FEAT_QUESTIONING - Updated
  QUEUE_NAME_TO_LABEL mapping to include product-queue - Updated FEATURE_STATUS_TO_LABEL to include
  FeatureStatus.questioning - LABEL_TO_QUEUE_NAME and LABEL_TO_FEATURE_STATUS auto-update via dict
  comprehension

Task 5: Add max_analyst_iterations field to Config class - New field: max_analyst_iterations: int =
  2 (defaults to 2 iterations) - Can be read from top-level config.json or set programmatically -
  Enables control over analyst questioning loop iterations

New tests added: - tests/test_github_labels.py: Round-trip tests for new label constants -
  tests/test_config.py: Config tests for max_analyst_iterations field - All 9 new tests pass, all 41
  existing tests continue to pass

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add github-storage skill for GitHub backend inspection
  ([`b24a6b6`](https://github.com/onpaj/harness/commit/b24a6b66579df27e07f85fcf501a8ea6da15ebba))

Adds a /github-storage Claude Code skill covering queue inspection via gh issue list,
  feature/artifact browsing on branches, dead-letter triage, brief upload via gh api, and state
  inspection via issue labels/body. Mirrors the structure of the existing azure-storage skill.

- Add github_artifacts.py git-branch artifact store and tests
  ([`c88feb8`](https://github.com/onpaj/harness/commit/c88feb862993ae8c862579103665cf06d0455f7d))

Implements ArtifactStorage protocol using a local git clone as a write-through cache.
  upload/download/exists use asyncio subprocesses for all git operations; get_work_dir() returns the
  implementation/ subdirectory for developer agents. Also adds clone_dir field to GitHubConfig
  (default ".runs-cache").

- Add github_client.py with REST wrapper and tests
  ([`0fdf0dd`](https://github.com/onpaj/harness/commit/0fdf0ddd5509f80af4abdaf323dd6a9bd852e360))

- Add github_labels.py with label constants
  ([`55a612b`](https://github.com/onpaj/harness/commit/55a612b78988a76cc9e656e1c7c9bc6e7bfc5a24))

- Add github_state.py issue-label state manager and tests
  ([`0967d56`](https://github.com/onpaj/harness/commit/0967d56a0a4dd45045a9c00c78c2cead4117c73d))

Implements GitHubStateManager (StateBackend protocol) that persists FeatureState as a fenced JSON
  block in a GitHub issue body, with a feat:* label as the authoritative source of truth for status.

16 unit tests cover create, get, update (with and without label swap), set_worktree_path,
  set_cleanup_warning, list_features, and from_config. All 288 existing tests continue to pass.

- Add GitHubStateManager.patch_existing_issue for raw-issue conversion
  ([`7cced5f`](https://github.com/onpaj/harness/commit/7cced5f97f786580d2486ffd4c66ecdbd4e2f6ef))

- Add list_sub_issues, get_parent_issue, draft PR support to GitHubClient
  ([`5d86e9b`](https://github.com/onpaj/harness/commit/5d86e9bd88b91a62072c0901fb664c4e3fee5313))

- Add product agent definition for analyst open-questions loop
  ([`39c5662`](https://github.com/onpaj/harness/commit/39c566201ac557d200c846bb94ae6edb838c6032))

- Aggregate token spend across all assistant stream events
  ([`967bf85`](https://github.com/onpaj/harness/commit/967bf85fd4ab43cbd5bbc4b3641aa4e9e5189ab7))

Replaces last-line-only parsing of claude -p stream-json with a single-pass aggregator that sums
  every assistant.message.usage block (parent + Task-subagent sidechains share the same shape).
  Cache field names are translated from the wire's *_input_tokens to the TokenUsage model's
  cache_*_tokens.

First passing test: single parent assistant + result event.

- Analyst emits Status line; reads prior answers in order
  ([`96bcfc5`](https://github.com/onpaj/harness/commit/96bcfc5576c6ea14214d7964ffcf0c385324fe8e))

- Auto-convert raw issues during enqueue_planner on GitHub backend
  ([`39dd1e0`](https://github.com/onpaj/harness/commit/39dd1e0beee62109a172beb7c78fb8ddcb451e4c))

- Auto-detect GitHub env vars in agentharness init
  ([`f606267`](https://github.com/onpaj/harness/commit/f6062679e1faac9ef99040292b739ae5efdcad2c))

Detects GITHUB_TOKEN via gh auth token and GITHUB_OWNER/GITHUB_RUNS_REPO from git remote origin.
  Prompts user to confirm, then writes .env directly. Replaces manual .env.example workflow.

- Auto-detect github owner and repo from git remote
  ([`9d8b422`](https://github.com/onpaj/harness/commit/9d8b4221cb6cba48c32127331a5157dfe758028c))

GITHUB_OWNER and GITHUB_RUNS_REPO are now optional — both fall back to parsing `git remote get-url
  origin` when not set. GITHUB_TOKEN is the only required env var for the GitHub backend.

- Cli gating for epic:paused parent before implement
  ([`27a15ba`](https://github.com/onpaj/harness/commit/27a15ba78d3d4746cd02ded8e0d354a131fe0fd0))

Prevent child features from being enqueued when their parent epic is paused due to a previous child
  failure. The implement command now checks if a feature has an epic_parent and if the parent issue
  has the epic:paused label.

Logic: - GitHub backend only (Azure backend skips the check) - If feature state not found
  (KeyError), proceed normally (raw issue) - If epic_parent is None, proceed normally (non-epic
  feature) - If epic_parent is set and parent has epic:paused label, exit with error and provide
  recovery instructions - Otherwise, proceed to enqueue_planner

Also includes 5 comprehensive tests: 1. Non-GitHub backend skips check 2. KeyError state proceeds
  normally 3. Non-epic feature proceeds normally 4. Epic with paused parent exits with error 5. Epic
  with non-paused parent proceeds normally

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Convertforagent skill
  ([`9b829d7`](https://github.com/onpaj/harness/commit/9b829d7b38cb179c64cff578cd824e05f1dae2fe))

- Epic branch parameterisation in _convert_raw_issue and _checkout_or_create
  ([`b7cf622`](https://github.com/onpaj/harness/commit/b7cf622ebb32af60f295cc08b7f3b1b35a9c0230))

- _convert_raw_issue: detect epic parent via get_parent_issue(); for child 1 create epic_branch from
  default branch; for child N>1 skip branch creation and verify previous sibling is done (raises
  ValueError if not); persist epic_parent, epic_position, epic_branch on FeatureState -
  _checkout_or_create: three-tier fallback — local checkout, remote tracking branch (for epic
  children 2..N where branch exists on remote only), then fresh local branch — preventing
  double-create failures on epic branches - Tests: 4 new epic branch tests in
  TestConvertRawIssueEpic; fix 3 existing tests to set get_parent_issue.return_value = None for
  non-epic cases

- Epic PR lifecycle, worktree retention, pause-on-failure in dispatcher
  ([`46b162b`](https://github.com/onpaj/harness/commit/46b162b3223a3cd2c9f274b3dbd1f4d964aabd7d))

- Add `epic_total` field to `FeatureState`; set from `len(sub_issues)` in `_convert_raw_issue` - Add
  `list_pull_requests()` to `GitHubClient` - Add `handle_epic_child_done()` to `GitHubStateManager`:
  opens draft PR on first child, ticks checklist on subsequent children, marks ready on last child -
  Add `handle_epic_child_failed()` to `GitHubStateManager`: applies `epic:paused` label to parent
  epic and posts a retry comment on the failing child issue - Add `_tick_epic_pr_checkbox()`
  module-level helper - Modify `run_terminal_cleanup()`: skip worktree removal for non-last epic
  children; call `handle_epic_child_failed()` on failed epic children - Modify `_open_feature_pr()`:
  route epic children to `handle_epic_child_done()` instead of `open_review()` - Add 15 tests in
  `tests/test_epic_dispatch.py` covering all new behaviors

- Github updates
  ([`3e5cd2a`](https://github.com/onpaj/harness/commit/3e5cd2a4c3aa1784afe6077419b8224feba0e0d3))

- Guard TUI state-change action against raw features
  ([`e7a0c29`](https://github.com/onpaj/harness/commit/e7a0c2919aa9a823121d7ef200bb3e3789977739))

- Implement github backend (issues-as-queue + feature branches)
  ([`2abc676`](https://github.com/onpaj/harness/commit/2abc676e1215ca27c3c9d764c6fb3db051d4694c))

Replaces Azure Blob Storage and Storage Queues with GitHub primitives: - Issues with labels as work
  queue (TaskQueue protocol) - Feature branches as artifact store (ArtifactStorage protocol) - Issue
  label + body JSON as state manager (StateBackend protocol)

Key new modules: github_client, github_queue, github_artifacts, github_state, github_labels.
  Pluggable via STORAGE_BACKEND=github env var. Azure backend unchanged and remains the default.

@claude

- Implement product-agent questioning loop and wire dispatch_after_completion analyst branching
  ([`81d0f1f`](https://github.com/onpaj/harness/commit/81d0f1f0a021a2700017c6e14f9f6ab9187848f0))

Implements Tasks 12-15 for the product-agent analyst loop:

Task 12: Add _dispatch_questioning helper to enqueue product agent for open questions Task 13: Add
  _dispatch_analyst_rerun helper to increment analyst iteration and re-enqueue Task 14: Wire
  dispatch_after_completion to branch on analyst status (COMPLETE/HAS_QUESTIONS) - Remove
  'analyzing' from _LINEAR_TRANSITIONS - Add _dispatch_linear_to helper for explicit destination
  dispatch - Route COMPLETE/cap-reached to architecting via _dispatch_linear_to - Route
  HAS_QUESTIONS (under cap) to questioning via _dispatch_questioning - Route questioning completion
  to analyst rerun via _dispatch_analyst_rerun Task 15: Update build_phase_task for questioning
  phase and revision-aware analyzing - analyzing task_id now uses r{N} format (e.g.,
  feat-x-analyzing-r2) - analyzing output artifact uses latest revision (spec.r{N}) - questioning
  phase fully supported with product agent role

All 75 dispatcher tests pass. Includes 15+ new test cases covering: - _dispatch_questioning
  first/second iteration - _dispatch_analyst_rerun incrementing logic - dispatch_after_completion
  branching (COMPLETE, HAS_QUESTIONS, cap scenarios) - build_phase_task revision awareness

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Improve PR Summary section clarity in developer prompt
  ([`d4d47fb`](https://github.com/onpaj/harness/commit/d4d47fb8a18aab572c6d8ce8decd49df4a50210e))

- Include questioning in TUI canonical state order
  ([`c5002a2`](https://github.com/onpaj/harness/commit/c5002a21f0b2ad4ba7720902aed62a21eff95916))

- Merge agentharness landing page
  ([`e48c9ab`](https://github.com/onpaj/harness/commit/e48c9ab3ed626c5c068336b0fa98aba060908e90))

- Open github PR when feature reaches done state
  ([`eaaf422`](https://github.com/onpaj/harness/commit/eaaf422b595f30fde35d5388c4eca5ce1f455488))

Add `_open_feature_pr` and `_build_pr_body` helpers to dispatcher.py. `_open_feature_pr` is called
  after state transitions to `FeatureStatus.done` and creates a PR via
  `GitHubClient.create_pull_request`; it is a no-op for non-GitHub backends. Tests in
  `tests/test_dispatcher_github.py` cover both the GitHub and azure backend paths, error resilience,
  and PR body content.

- Open_review accepts pr_title and pr_summary kwargs
  ([`65e22f4`](https://github.com/onpaj/harness/commit/65e22f4c0aedf811abce99095dde48825a10461a))

- Pass artifact store from run_task into dispatch chain
  ([`ee6dd0a`](https://github.com/onpaj/harness/commit/ee6dd0a68a7a3785883efb2c33c7a2182d921f30))

- Propagate max_analyst_iterations into PipelineConfig on feature creation
  ([`a870660`](https://github.com/onpaj/harness/commit/a87066048d47849a6497e9623963609d48fa3c99))

- Read feature_marker from config in observer
  ([`54fdb52`](https://github.com/onpaj/harness/commit/54fdb529da68de19e8c28783c1224227ef50f6d6))

- Read plan file artifact from writing-plans skill output
  ([`65cd41e`](https://github.com/onpaj/harness/commit/65cd41eb03fb4b927f6ae8b9cb14e37520944ea9))

The writing-plans skill saves the plan to docs/superpowers/plans/*.md and outputs only the execution
  handoff message. Add output_file_glob to AgentDefinition so run_task reads the saved file as the
  artifact instead of the agent's text response.

Planner agent keeps the writing-plans context file but notes it runs in an automated pipeline to
  suppress the execution handoff prompt.

- Register product-queue and max_analyst_iterations in pipeline config
  ([`24a75af`](https://github.com/onpaj/harness/commit/24a75af05eb1d298653f57b8bf263f302bd01d6e))

- Storage backend abstraction
  ([`4757223`](https://github.com/onpaj/harness/commit/4757223cc2f96f8a2bcb653516f10eaea6bacca3))

- Support labels parameter in create_pull_request
  ([`f28ba1e`](https://github.com/onpaj/harness/commit/f28ba1e2a9a0286090cd63d0e1ee348760a0a4d7))

- Synthesise raw issues in list_features instead of skipping
  ([`4e172cd`](https://github.com/onpaj/harness/commit/4e172cd7a0f680aa21cb4cf38e8539f2690db4ea))

- Thread artifact store through dispatch chain to PR open
  ([`7da069a`](https://github.com/onpaj/harness/commit/7da069a2c56e3dbcec7eedb2a3d4ac86b59deb93))

- Thread feature_marker into GitHubStateManager and apply to final PR
  ([`2fd9180`](https://github.com/onpaj/harness/commit/2fd91806f593e33af30677598e979e8680e0bb91))

- Thread feature_marker into GitHubTaskQueue via constructor
  ([`b9c5b09`](https://github.com/onpaj/harness/commit/b9c5b09d11f8a4de64529b387b15a49bd9a1969d))

- Tui renders questioning phase and analyst iteration counter
  ([`a8d5e0b`](https://github.com/onpaj/harness/commit/a8d5e0b267d75d34c4f9e3c19847971f37dc36f6))

- Use backend factory in observer and add stale-claim sweeper
  ([`f089481`](https://github.com/onpaj/harness/commit/f089481a526fbb38a15cd05133ac54f0e8c9dbab))

Replace hardcoded Azure setup in observe() with create_task_queue factory so the observer works with
  any storage backend. Add _sweep_stale_claims coroutine that periodically reclaims in-progress
  GitHub issues whose heartbeat timestamp has gone stale.

- **dispatcher**: Add build_phase_task() helper
  ([`e1f59e5`](https://github.com/onpaj/harness/commit/e1f59e52dba929c4390355f51217e416775a8069))

Centralizes TaskMessage construction for phase agents and developer-queue re-enqueue. Used by the
  manual state-change service to avoid the inline re-implementation that tui._resume_phase currently
  has.

- **dispatcher**: Add STATE_TO_QUEUE mapping and queue_for_state()
  ([`7863ae5`](https://github.com/onpaj/harness/commit/7863ae5e7489257dc4017e9ad7ce5eba3140aaaf))

Single source of truth for status→queue routing. Replaces duplication in tui._PHASE_TO_QUEUE and
  tui._resume_phase. Used by the new manual state-change service.

- **models**: Add FeatureState.with_tasks_cleared() helper
  ([`e3a8498`](https://github.com/onpaj/harness/commit/e3a8498bae1358f8d4f01288631ee37d42a7c1d9))

with_tasks_added([]) appends, not clears. Add a dedicated immutable helper for manual rollback flows
  that need to wipe the task list.

- **run_task**: Defensively drop orphan dev/review task messages
  ([`3fd6775`](https://github.com/onpaj/harness/commit/3fd67750d008338dff664bf62728715a2db8b6f5))

After a manual rollback, in-flight developer/review messages may reference a task_id that no longer
  exists in state.tasks. Drop them with a dropped_orphan_task audit event instead of crashing.
  Phase-agent messages are unaffected.

- **state-change**: Add headless apply_state_change service
  ([`2c0460a`](https://github.com/onpaj/harness/commit/2c0460a521af1d465ac6422bdf7989a3179e1482))

Atomic mutation via state_mgr.update closure (idempotent under lease retry) plus a single follow-up
  enqueue with retry-once-then-raise semantics. Used by the new TUI 'S' dialog and reusable from any
  non-Textual surface.

- **tui**: Add 'S' binding to open the state-change dialog
  ([`e46c370`](https://github.com/onpaj/harness/commit/e46c3707e590dff38b5f8b0b2baa8b8988802b7a))

Wires the headless apply_state_change service into the TUI through a new StateChangeModal. Uses
  pluggable storage factories (create_state_manager / create_task_queue) — does not duplicate the
  github-incompatible pattern in _resume_phase. Failed mode goes through the existing ConfirmScreen
  for a deliberate second keypress.

- **tui**: Add StateChangeModal for the manual state-change dialog
  ([`6d809ad`](https://github.com/onpaj/harness/commit/6d809addfbaa01b0865e125c5c03aae1a553d1a1))

Pure-UI modal lives in its own module to keep tui.py focused. The _options_for helper is pure and
  unit-tested; the rendering is covered by manual smoke testing in the dev loop.

### Refactoring

- Align GitHub backends to updated Protocol
  ([`0263b24`](https://github.com/onpaj/harness/commit/0263b2407d650ed835e7f77da81ae902f3db1174))

- github_queue.py: move _parse_task_from_body to GitHubTaskQueue as @staticmethod, remove
  connection_string param from move_to_dead_letter to match Protocol - github_state.py: add
  GitHubStateManager._parse_state_from_issue @staticmethod, update list_features to return
  list[FeatureState] (was list[tuple[str, int]]), add open_review(feature_id) method migrated from
  dispatcher._open_feature_pr, keep module-level parse_state_from_issue as shim pending observer
  refactor - tests/test_github_queue.py: update import and move_to_dead_letter call to match new
  signatures

- Clean up storage.py — drop Azure aliases, symmetric factories
  ([`839b979`](https://github.com/onpaj/harness/commit/839b9798c4b4a9f5db2fc7c3d2a7d0376d4d79b7))

- Remove ArtifactStore and PipelineQueue Azure-specific aliases - Remove aliases from __all__ -
  Replace inline BlobServiceClient construction in create_artifact_store with
  AzureArtifactStore.from_config(config) - create_state_manager already used
  AzureStateManager.from_config (Task 2 partial update)

- Collapse brainstorm.py to backend-agnostic factory calls
  ([`7a1322e`](https://github.com/onpaj/harness/commit/7a1322e05a6a8b602d591053b9aefb419101455f))

Replace the dual Azure/GitHub paths in upload_brief and enqueue_planner with single implementations
  using create_artifact_store, create_state_manager, and create_task_queue factories. Delete
  _upload_brief_github and _enqueue_planner_github helpers. Update tests to patch the factories
  directly.

- Delete legacy worker.py and test_worker.py
  ([`cafc0f2`](https://github.com/onpaj/harness/commit/cafc0f2b598e0e0000b8a2ded180f9a09a229a37))

Remove agentharness/worker.py (legacy Azure-only worker) and its test files (test_worker.py,
  test_worker_worktree.py). Update README to drop worker/start CLI entries and the legacy worker
  mode paragraph. Replace the broken import in cli.py worker command with a tombstone error message
  pointing users to `agentharness observe` (full command removal is Task 8).

- Extract slug_title helper shared by brainstorm and github_state
  ([`0313bf1`](https://github.com/onpaj/harness/commit/0313bf14827c680cafc11159b1868aeebbba70bf))

- Add `slug_title()` to github_state.py as single source of truth for URL-safe slugging - Algorithm:
  lowercase → replace non-[a-z0-9]+ with "-" → strip "-" → truncate 40 chars - Refactor
  `_slug_from_brief()` to delegate to `slug_title()` - Guarantees round-trip equality between
  brainstorm synthesis and github_state matching - Add TestSlugTitle (6 tests) and
  TestSlugFromBriefDelegates (3 tests) - All 39 tests pass (github_state, brainstorm_github,
  brainstorm_pipeline_config)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Fix error handling in AzureStateManager.list_features and move_to_dead_letter
  ([`e736afa`](https://github.com/onpaj/harness/commit/e736afa0aaf532512a6d8738af9cd1a572205aeb))

- Fix open_review error handling in GitHubStateManager
  ([`e93b991`](https://github.com/onpaj/harness/commit/e93b991d2f8a47a9b1e6db4958bd2f5e3a1716f5))

- Replace bare pr["number"] key access with pr.get("number", "?") to avoid a silently-swallowed
  KeyError when the GitHub API omits the field - Replace pr.get("html_url", "") + truthy-check with
  explicit pr.get("html_url") and a log.warning when the URL is absent, making the failure
  observable - Remove redundant local import of GitHubClient inside open_review (the type is already
  guarded by TYPE_CHECKING at module level)

- Remove backend-conditional branches from run_task.py
  ([`87b50e7`](https://github.com/onpaj/harness/commit/87b50e760be8ae8aa3391dec4699723575de8cc4))

- Remove hardcoded FEATURE_MARKER constant
  ([`e7db61c`](https://github.com/onpaj/harness/commit/e7db61c666584ea3f1628f1df0c82b076f3d5fe3))

- Remove unused _build_pr_body helper from dispatcher
  ([`9e00dec`](https://github.com/onpaj/harness/commit/9e00dec70d4f72a2e96b0cf1a58a68c3340f05cd))

- Replace backend-specific code in tui.py with storage factory calls
  ([`500656e`](https://github.com/onpaj/harness/commit/500656e762fabc978eaac7dc4ec75dce44b2d495))

Drop 5 backend-conditional branches and Azure SDK direct instantiation: - Import
  create_state_manager/create_task_queue instead of PipelineQueue - _do_resume_task: use
  create_state_manager factory; remove BlobServiceClient - _resume_phase: use create_task_queue; use
  module-level _PHASE_TO_QUEUE constant - _resume_dev_task: use create_task_queue; use module-level
  _PHASE_TO_QUEUE constant - _do_purge_queues: use create_task_queue per queue instead of
  PipelineQueue.from_connection_string - _load_all_states: collapse github/azure branch into single
  state_mgr.list_features() call; delete _load_states_azure and _load_states_from_cache helpers -
  _load_queue_depths: collapse github/azure branch into per-queue factory calls; delete
  _load_depths_azure and _derive_depths_from_cache helpers

- Replace direct SDK use in cli.py with storage factories, remove worker/start commands
  ([`a7f2991`](https://github.com/onpaj/harness/commit/a7f2991ba612a4d2ebb636a9d76026e08e3dfaf6))

- Replace PipelineQueue with TaskQueue and delegate PR opening to state_mgr
  ([`7074a11`](https://github.com/onpaj/harness/commit/7074a119386cdd1aaf92cba202e751293f2cce2f))

- Replace PipelineQueue import with TaskQueue from storage_protocol in dispatcher.py - Update all
  six function signatures to use dict[str, TaskQueue] - Thread state_mgr through
  dispatch_after_completion → _dispatch_review_result → _open_feature_pr - Replace _open_feature_pr
  body with single state_mgr.open_review(feature_id) delegation - Remove now-unused GitHubClient
  import and backend-conditional logic from dispatcher.py - Pass state_mgr to
  dispatch_after_completion in run_task.py - Update test_dispatcher.py and test_dispatcher_github.py
  to match new signatures

- Tighten Protocol surface in storage_protocol.py
  ([`1e5fb4a`](https://github.com/onpaj/harness/commit/1e5fb4ad68f2bf423bc891f6a002869c87dc41c6))

Add missing methods to all three Protocols so backend capabilities are fully declared at the
  contract level, eliminating the need for hasattr checks and backend-conditional imports in
  callers:

- ArtifactStorage: add get_work_dir() and commit_workdir_changes() - TaskQueue.move_to_dead_letter:
  remove connection_string param (stored at construction) - StateBackend.create: add optional
  brief_content param - StateBackend: add list_features() and open_review() - Import pathlib.Path

- Update Azure backends to implement new Protocol methods
  ([`a5ace34`](https://github.com/onpaj/harness/commit/a5ace346d6a84dc52b4b40f047f330e37c9d8d0b))

- AzureArtifactStore: add get_work_dir() → None and commit_workdir_changes() → False -
  AzureTaskQueue: store _connection_string at construction; drop connection_string param from
  move_to_dead_letter; add from_config() classmethod - StateManager renamed to AzureStateManager;
  backward-compat alias StateManager kept; add from_config(), brief_content param on create(),
  list_features(), open_review() - storage.py: use AzureStateManager.from_config() in
  create_state_manager()

- Use storage factory in run_task, remove direct azure import
  ([`353a866`](https://github.com/onpaj/harness/commit/353a8666870eec0cc01eb07bebc3f5428aa9d45b))

Replace direct BlobServiceClient construction and ArtifactStore/PipelineQueue instantiation with
  create_artifact_store, create_state_manager, and create_task_queue factory calls. Add GitHub
  backend work_dir resolution via store.get_work_dir(). Update
  _download_with_retry/_upload_task_contexts type hints to ArtifactStorage protocol. Remove
  blob_service.close() from finally block. Add factory-call verification tests.

- **tui**: Derive _PHASE_TO_QUEUE from dispatcher.STATE_TO_QUEUE
  ([`192bc11`](https://github.com/onpaj/harness/commit/192bc11b8f211495f19e8b951e8b4bdcc1062ef1))

Removes the second copy of the state→queue knowledge. The legacy _resume_phase still has its own
  inline copy because that flow has known backend-coupling issues outside this feature's scope;
  tracked as follow-up.

### Testing

- Add backend parity tests and parametrize test_run_task.py
  ([`d83faf2`](https://github.com/onpaj/harness/commit/d83faf2072b214ce88ab67bfd698229925cfcf82))

- New tests/test_backend_parity.py: 20 tests covering Protocol method presence for all six backend
  classes, Azure no-op contracts (get_work_dir→None, open_review→None), move_to_dead_letter
  signature parity, and signature alignment checks (brief_content param, list_features return
  annotation, get_work_dir sync, commit_workdir_changes async). - tests/test_run_task.py: extracted
  _make_run_task_fixtures helper, parametrized test_uses_create_artifact_store for both
  azure/github, and added TestRunTaskGetWorkDir with three cases verifying correct
  commit_workdir_changes invocation for None/Path × allowed_tools.

- Regression for sidechain (subagent) token aggregation
  ([`27d3e45`](https://github.com/onpaj/harness/commit/27d3e45d6991ad8dc259546288209a5b853f7ccb))

- Verify storage factories thread feature_marker into GitHub backends
  ([`3d2060a`](https://github.com/onpaj/harness/commit/3d2060a6397f029a0061f83e43af3c35034458e1))

- **dispatcher**: Add reviewing path test for build_phase_task
  ([`6d143aa`](https://github.com/onpaj/harness/commit/6d143aa508030b60e3eb126397321894a96d7d04))
