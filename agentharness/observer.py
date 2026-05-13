"""Observer: polls all queues and spawns a subprocess per task message."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from agentharness.config import Config
from agentharness.github_state import ensure_child_branch, ensure_epic_branch
from agentharness.models import FeatureStatus, TaskMessage
from agentharness.storage import create_task_queue
from agentharness.storage_protocol import RawMessage, TaskQueue

log = logging.getLogger(__name__)

_RENEWAL_INTERVAL = 60      # seconds between visibility renewals
_VISIBILITY_TIMEOUT = 150   # seconds of visibility granted per renewal

_ACTIVE_STATUSES: frozenset[FeatureStatus] = frozenset({
    FeatureStatus.analyzing,
    FeatureStatus.questioning,
    FeatureStatus.architecting,
    FeatureStatus.designing,
    FeatureStatus.planning,
    FeatureStatus.developing,
    FeatureStatus.reviewing,
    FeatureStatus.dev_revision,
})

_STALE_CLAIM_TIMEOUT = 600  # seconds before a claimed task is reclaimed
_SWEEP_INTERVAL = 60        # seconds between sweeps
_STATE_CACHE_INTERVAL = 30  # seconds between local state cache writes (GitHub backend)
STATE_CACHE_PATH = Path("logs/state-cache.json")

async def observe(config: Config) -> None:
    """Poll all queues and spawn a subprocess per message."""
    from agentharness import auto_mode
    if config.auto_mode:
        auto_mode.enable()
        log.info("Auto-mode enabled via config.")

    queue_names = config.queue_names()

    if config.storage_backend == "github":
        from agentharness.github_queue import GitHubTaskQueue
        await GitHubTaskQueue.ensure_all_queues(config, queue_names)
        queues: dict[str, TaskQueue] = {
            q_name: create_task_queue(config, q_name) for q_name in queue_names
        }
    else:
        queues = {}
        for q_name in queue_names:
            q = create_task_queue(config, q_name)
            await q.ensure_exists()
            queues[q_name] = q

    log.info("Observer started — watching %d queues: %s", len(queues), ", ".join(queues))
    exe = str(Path(sys.executable).parent / "agentharness")

    active_procs: dict[str, asyncio.Process] = {}

    is_github = config.storage_backend == "github"

    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        log.info("Observer shutting down — terminating %d active subprocess(es)", len(active_procs))
        for task_id, proc in list(active_procs.items()):
            try:
                proc.terminate()
                log.info("Sent SIGTERM to subprocess for task %s (pid %d)", task_id, proc.pid)
            except ProcessLookupError:
                pass
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT, _shutdown)

    try:
        if is_github:
            poll_tasks = [_unified_github_poll(queues, config, exe, active_procs)]
        else:
            poll_interval = config.defaults.poll_interval_seconds
            poll_tasks = [
                _poll_queue(q_name, q, config, exe, active_procs, poll_interval)
                for q_name, q in queues.items()
            ]
        poll_tasks.append(_auto_mode_loop(config))
        await asyncio.gather(*poll_tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for q in queues.values():
            await q.close()


async def _auto_mode_loop(config: Config) -> None:
    """When the auto-mode toggle is on, start the oldest eligible issue.

    Eligible issues are:
    - FeatureState features in *brainstormed* status.
    - For GitHub backend: open issues carrying the feature-marker label that
      have no pipeline state yet (no feat:/state:/queue: labels).

    Only one feature is started per cycle. The loop waits until nothing is
    actively running before picking the next candidate.
    """
    from agentharness import auto_mode
    from agentharness.brainstorm import enqueue_planner
    from agentharness.storage import create_state_manager

    interval = config.auto_mode_poll_seconds
    log.info("Auto-mode loop started (interval=%.1fs)", interval)
    state_mgr = create_state_manager(config)

    is_github = config.storage_backend == "github"
    client = None
    if is_github:
        from agentharness.github_client import GitHubClient
        client = GitHubClient.from_config(config)

    try:
        while True:
            if not auto_mode.is_enabled():
                await asyncio.sleep(interval)
                continue

            try:
                features = await state_mgr.list_features()
            except Exception as exc:
                log.warning("Auto-mode list_features failed: %s", exc)
                await asyncio.sleep(interval)
                continue

            if any(f.status in _ACTIVE_STATUSES for f in features):
                await asyncio.sleep(interval)
                continue

            # Build candidate list: (sort_key, feature_id_or_None, raw_issue_or_None)
            # sort_key uses GH issue number so both groups sort by ascending ID.
            # "feat-" prefix keeps known brainstormed features ranked before "raw-" untracked issues.
            candidates: list[tuple[str, str | None, dict | None]] = [
                (f"feat-{f.state_issue_number or 0:010d}", f.feature_id, None)
                for f in features
                if f.status == FeatureStatus.brainstormed
            ]

            if client is not None:
                tracked = {f.state_issue_number for f in features if f.state_issue_number is not None}
                raw_issues = await _collect_raw_candidates(client, tracked, config)
                for raw in raw_issues:
                    candidates.append((f"raw-{raw.get('number', 0):010d}", None, raw))

            if not candidates:
                await asyncio.sleep(interval)
                continue

            candidates.sort(key=lambda t: t[0])
            _, feature_id, raw_issue = candidates[0]

            try:
                if feature_id is not None:
                    log.info("Auto-mode starting %s", feature_id)
                    await enqueue_planner(feature_id, config)
                else:
                    number = raw_issue["number"]  # type: ignore[index]
                    log.info("Auto-mode bootstrapping issue #%d", number)
                    feature_id = await _bootstrap_github_issue(client, raw_issue, config)
                    await enqueue_planner(feature_id, config)
                    await client.create_comment(number, f"Feature `{feature_id}` auto-started by observer.")
                    await client.update_issue(number, state="closed")
            except Exception as exc:
                log.error("Auto-mode failed to start candidate: %s", exc)

            await asyncio.sleep(interval)
    finally:
        if client is not None:
            await client.close()
        await state_mgr.close()


async def _poll_queue(
    queue_name: str,
    queue: TaskQueue,
    config: Config,
    exe: str,
    active_procs: dict[str, asyncio.Process],
    poll_interval: float,
) -> None:
    log.info("Polling %s (interval=%.1fs)", queue_name, poll_interval)
    while True:
        result = await queue.receive_task(visibility_timeout=_VISIBILITY_TIMEOUT)
        if result is None:
            await asyncio.sleep(poll_interval)
            continue
        task, raw_msg = result
        log.info("Received task %s from %s", task.task_id, queue_name)
        asyncio.create_task(
            _run_subprocess(queue_name, task, raw_msg, queue, exe, active_procs),
            name=f"task-{task.task_id}",
        )


async def _unified_github_poll(
    queues: dict[str, TaskQueue],
    config: Config,
    exe: str,
    active_procs: dict[str, asyncio.Process],
) -> None:
    """Single-search poller for GitHub: one API call per cycle handles polling, sweeping, and state cache."""
    import json
    import time

    from agentharness.github_client import GitHubClient
    from agentharness.github_labels import IMPLEMENT_LABEL, LABEL_TO_QUEUE_NAME, STATE_IN_PROGRESS, STATE_QUEUED
    from agentharness.github_queue import GitHubTaskQueue
    poll_interval = config.defaults.github_poll_interval_seconds
    client = GitHubClient.from_config(config)
    last_sweep = 0.0
    last_cache = 0.0
    bootstrapping: set[int] = set()
    log.info("GitHub unified poller started (interval=%.1fs)", poll_interval)
    try:
        while True:
            now = time.monotonic()

            # 0. Bootstrap issues labeled 'implement'
            try:
                implement_issues = await client.list_issues(labels=[IMPLEMENT_LABEL])
            except Exception as exc:
                log.warning("GitHub implement-label search failed: %s", exc)
                implement_issues = []

            for issue in implement_issues:
                issue_number: int = issue["number"]
                if issue_number in bootstrapping:
                    continue
                bootstrapping.add(issue_number)
                asyncio.create_task(
                    _handle_implement_issue(client, issue, config, bootstrapping),
                    name=f"bootstrap-{issue_number}",
                )

            try:
                feat_issues, subtask_issues = await asyncio.gather(
                    client.list_issues(labels=[config.github.feature_marker]),
                    client.list_issues(labels=[config.github.subtask_marker]),
                )
                seen: dict[int, dict] = {issue["number"]: issue for issue in feat_issues}
                for issue in subtask_issues:
                    seen.setdefault(issue["number"], issue)
                issues = list(seen.values())
            except Exception as exc:
                log.warning("GitHub unified poll failed: %s", exc)
                await asyncio.sleep(poll_interval)
                continue

            # 1. Dispatch queued tasks
            dispatched: set[str] = set()
            for issue in issues:
                label_names = {lbl["name"] for lbl in issue.get("labels", [])}
                if STATE_QUEUED not in label_names:
                    continue
                queue_name = next(
                    (LABEL_TO_QUEUE_NAME[lbl] for lbl in label_names if lbl in LABEL_TO_QUEUE_NAME),
                    None,
                )
                if not queue_name or queue_name in dispatched or queue_name not in queues:
                    continue
                dispatched.add(queue_name)
                queue = queues[queue_name]
                if not isinstance(queue, GitHubTaskQueue):
                    continue
                try:
                    task, raw_msg = await queue.claim_issue(issue)
                except Exception as exc:
                    log.warning("Failed to claim issue #%s for %s: %s", issue["number"], queue_name, exc)
                    continue
                log.info("Claimed task %s from %s", task.task_id, queue_name)
                asyncio.create_task(
                    _run_subprocess(queue_name, task, raw_msg, queue, exe, active_procs),
                    name=f"task-{task.task_id}",
                )

            # 2. Sweep stale in-progress claims
            if now - last_sweep >= _SWEEP_INTERVAL:
                last_sweep = now
                utcnow = datetime.now(UTC)
                for issue in issues:
                    label_names = {lbl["name"] for lbl in issue.get("labels", [])}
                    if STATE_IN_PROGRESS not in label_names:
                        continue
                    updated_at_str = issue.get("updated_at") or ""
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if (utcnow - updated_at).total_seconds() > _STALE_CLAIM_TIMEOUT:
                        try:
                            local_task = GitHubTaskQueue._parse_task_from_body(issue.get("body") or "")
                            if local_task.task_id in active_procs:
                                log.debug(
                                    "Skipping reclaim of issue #%d — task %s still active locally",
                                    issue["number"], local_task.task_id,
                                )
                                continue
                        except Exception:
                            pass
                        await _reclaim_issue(client, issue)

            # 3. Write state cache
            if now - last_cache >= _STATE_CACHE_INTERVAL:
                last_cache = now
                states = await _collect_states(client, issues, config)
                try:
                    STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    STATE_CACHE_PATH.write_text(json.dumps(states))
                    log.debug("State cache written: %d features", len(states))
                except Exception as exc:
                    log.warning("State cache write failed: %s", exc)

            await asyncio.sleep(poll_interval)
    finally:
        await client.close()


async def _bootstrap_github_issue(
    client: "GitHubClient",
    issue: dict,
    config: Config,
) -> str:
    """Create branch + brief.md + FeatureState(brainstormed) for a raw GitHub issue.

    Returns the computed feature_id. Raises on any error. Does NOT enqueue or
    close/comment on the original issue — callers do that based on their context.

    When the issue is a GitHub sub-issue (has an epic parent), the child branch
    is created off the epic branch instead of the default branch.
    """
    import base64

    from agentharness.github_state import GitHubStateManager, slug_title
    from agentharness.models import FeatureState, FeatureStatus, PipelineConfig

    title: str = issue.get("title") or "untitled"
    body: str = issue.get("body") or ""
    number: int = issue["number"]

    feature_id = f"feat-{slug_title(title)}"
    branch_name = feature_id  # child branch = feature_id for both epic and non-epic
    log.info("Bootstrapping feature %s from issue #%d", feature_id, number)

    default_branch = await client.get_default_branch()
    main_sha = (await client.get_ref(f"heads/{default_branch}"))["object"]["sha"]

    # Detect epic parent
    parent_issue = await client.get_parent_issue(number)
    epic_parent: int | None = None
    epic_branch: str | None = None

    if parent_issue is not None:
        epic_parent = int(parent_issue["number"])
        epic_branch = "epic-" + slug_title(parent_issue.get("title") or "")
        log.info(
            "Issue #%d is a sub-issue of #%d — using epic branch %s",
            number, epic_parent, epic_branch,
        )
        epic_sha = await ensure_epic_branch(client, epic_branch, main_sha)
        await ensure_child_branch(client, branch_name, epic_branch, epic_sha)
    else:
        try:
            await client.create_ref(f"refs/heads/{branch_name}", main_sha)
        except Exception as exc:
            raise RuntimeError(f"Failed to create branch {branch_name!r}: {exc}") from exc

    brief_blob_path = f"artifacts/{feature_id}/brief.md"
    await client.put_content(
        path=brief_blob_path,
        message=f"feat: add brief for {feature_id}",
        content=base64.b64encode(body.encode()).decode(),
        sha=None,
        branch=branch_name,
    )

    now = datetime.now(UTC)
    state = FeatureState(
        feature_id=feature_id,
        status=FeatureStatus.brainstormed,
        created_at=now,
        updated_at=now,
        config=PipelineConfig(
            max_revisions=config.defaults.max_revisions,
            max_analyst_iterations=config.max_analyst_iterations,
        ),
        branch_name=branch_name,
        epic_parent=epic_parent,
        epic_branch=epic_branch,
    )
    await GitHubStateManager(client, feature_marker=config.github.feature_marker).create(state, body)
    return feature_id


async def _handle_implement_issue(
    client: "GitHubClient",
    issue: dict,
    config: Config,
    bootstrapping: set[int],
) -> None:
    """Bootstrap the pipeline from a GitHub issue labeled 'implement'.

    Saves the issue body as brief.md, creates the feature state in brainstormed
    status, and leaves it for the user (or auto-mode) to start the pipeline.
    The original issue is closed with a reference comment.
    """
    from agentharness.github_labels import IMPLEMENT_LABEL

    number: int = issue["number"]
    try:
        # Remove 'implement' label first to prevent double-processing
        try:
            await client.remove_label(number, IMPLEMENT_LABEL)
        except Exception as exc:
            log.debug("Issue #%d implement label already removed or missing: %s", number, exc)
            return

        feature_id = await _bootstrap_github_issue(client, issue, config)
        await client.create_comment(
            number,
            f"Feature `{feature_id}` created — press **i** in the TUI (or run `agentharness implement {feature_id}`) to start the pipeline.",
        )
        await client.update_issue(number, state="closed")
        log.info("Feature %s created in brainstormed state", feature_id)

    except Exception as exc:
        log.error("Failed to bootstrap feature from issue #%d: %s", number, exc, exc_info=True)
        try:
            await client.create_comment(number, f"⚠️ Failed to start pipeline: {exc}")
        except Exception:
            pass
    finally:
        bootstrapping.discard(number)


async def _collect_raw_candidates(
    client: "GitHubClient",
    tracked_issue_numbers: set[int],
    config: Config,
) -> list[dict]:
    """Return open agent-labeled issues that have no pipeline state yet.

    Excludes any issue whose number is in *tracked_issue_numbers* (already
    a FeatureState) and any issue that carries a feat:*, state:*, or queue:*
    label (already in the pipeline or finished).
    """
    from agentharness.github_labels import FEAT_STATUS_LABELS, QUEUE_NAME_TO_LABEL, TASK_STATE_LABELS

    skip_labels = FEAT_STATUS_LABELS | TASK_STATE_LABELS | frozenset(QUEUE_NAME_TO_LABEL.values())
    try:
        all_issues = await client.list_issues(labels=[config.github.feature_marker])
    except Exception as exc:
        log.warning("Auto-mode raw issue fetch failed: %s", exc)
        return []

    result = []
    for issue in all_issues:
        if issue["number"] in tracked_issue_numbers:
            continue
        label_names = {lbl["name"] for lbl in issue.get("labels", [])}
        if label_names & skip_labels:
            continue
        result.append(issue)
    return result


async def _collect_states(client: "GitHubClient", issues: list[dict], config: Config) -> list[dict]:
    """Parse FeatureState from tracking issues only, skipping task queue issues.

    Deduplicates by feature_id, keeping the highest-numbered issue per feature.
    """
    from agentharness.github_labels import TASK_STATE_LABELS
    from agentharness.github_state import GitHubStateManager, parse_state_from_issue

    seen: dict[str, tuple[int, dict]] = {}  # feature_id -> (issue_number, state_dict)
    for issue in issues:
        label_names = {lbl["name"] for lbl in issue.get("labels", [])}
        if label_names & TASK_STATE_LABELS:
            continue  # task queue issue, not a tracking issue
        state = parse_state_from_issue(issue)
        if state is None:
            try:
                mgr = GitHubStateManager(client, feature_marker=config.github.feature_marker)
                state = await mgr._state_from_issue(issue)
            except Exception:
                continue
        issue_number: int = issue.get("number", 0)
        existing = seen.get(state.feature_id)
        if existing is None or issue_number > existing[0]:
            seen[state.feature_id] = (issue_number, state.model_dump(mode="json"))
    return [entry[1] for entry in seen.values()]


async def _run_subprocess(
    queue_name: str,
    task: TaskMessage,
    raw_msg: RawMessage,
    queue: TaskQueue,
    exe: str,
    active_procs: dict[str, asyncio.Process],
) -> None:
    log_dir = Path("logs") / queue_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{task.task_id}.log"

    task_json = task.model_dump_json()
    log.info("Spawning subprocess for %s → %s", task.task_id, log_file)

    try:
        with open(log_file, "a") as fh:
            from datetime import datetime
            fh.write(f"\n--- run {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            proc = await asyncio.create_subprocess_exec(
                exe, "run-task", queue_name,
                stdin=asyncio.subprocess.PIPE,
                stdout=fh,
                stderr=fh,
            )
            active_procs[task.task_id] = proc
            log.info("Task %s running as pid %d", task.task_id, proc.pid)

            proc.stdin.write(task_json.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            final_raw = await _wait_with_renewal(proc, task.task_id, raw_msg, queue)

    except Exception as exc:
        log.error("Subprocess management failed for %s: %s", task.task_id, exc)
        return
    finally:
        active_procs.pop(task.task_id, None)

    if proc.returncode == 0:
        try:
            await queue.delete_message(final_raw)
            log.info("Task %s done — message deleted", task.task_id)
        except Exception as exc:
            log.error("Could not delete message for %s: %s", task.task_id, exc)
    else:
        log.error(
            "Task %s failed (exit %d) — logs: %s — deleting message (no retry)",
            task.task_id, proc.returncode, log_file,
        )
        try:
            await queue.delete_message(final_raw)
        except Exception as exc:
            log.warning("Could not delete failed message for %s: %s", task.task_id, exc)


async def _wait_with_renewal(proc: asyncio.Process, task_id: str, raw_msg: RawMessage, queue: TaskQueue) -> RawMessage:
    """Wait for subprocess, renewing queue message visibility every _RENEWAL_INTERVAL seconds.

    Returns the latest RawMessage (with updated pop_receipt) for deletion.
    """
    current = raw_msg

    while True:
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=_RENEWAL_INTERVAL)
            return current
        except asyncio.TimeoutError:
            try:
                current = await queue.extend_visibility(current, _VISIBILITY_TIMEOUT)
                log.debug("Renewed visibility for %s", task_id)
            except Exception as exc:
                err_str = str(exc)
                if "MessageNotFound" in err_str:
                    log.debug("Message for %s already deleted — task completed before renewal", task_id)
                    return current
                log.warning("Could not renew visibility for %s: %s — message may be re-queued", task_id, exc)


async def _reclaim_issue(client, issue: dict) -> None:
    """Remove stale claim labels and requeue the issue."""
    from agentharness.github_labels import STATE_IN_PROGRESS, STATE_QUEUED, is_claimed_by_label
    from agentharness.github_queue import _update_body_status
    number = issue["number"]
    labels_to_remove = [
        lbl["name"] for lbl in issue.get("labels", [])
        if is_claimed_by_label(lbl["name"]) or lbl["name"] == STATE_IN_PROGRESS
    ]
    for label in labels_to_remove:
        try:
            await client.remove_label(number, label)
        except Exception:
            pass
    await client.add_labels(number, [STATE_QUEUED])
    body = _update_body_status(issue.get("body") or "", "queued")
    await client.update_issue(number, body=body)
    await client.create_comment(number, "⚠️ Reclaimed: stale claim (observer restart or crash)")
    log.info("Reclaimed stale issue #%d", number)
