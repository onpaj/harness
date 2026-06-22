# Handoff: switch Anela.Heblo to symlinked AgentHarness skills

This describes changes to apply **in the Anela.Heblo repo** to stop committing copies of
AgentHarness agents/skills and instead symlink them from the pip-installed package.

## Why

`agentharness init` (default) copies the harness's agents/skills/pipeline into the repo,
and those copies get committed. They go stale and drift from the installed package
(Anela.Heblo currently has Jun-1 copies, is missing `chopchop`/`oneshot`, and still
carries the deprecated `implement` skill).

The harness now supports `agentharness init --symlink`: it links each shipped item into
the repo from the installed package and adds those paths to a managed `.gitignore` block.
Upgrading the package then refreshes the linked content automatically — nothing to
re-commit.

> Requires an AgentHarness build that includes `init --symlink` (this change). Install
> from git: `pip install git+https://github.com/onpaj/harness@master`.

## What `--symlink` does / does not touch

- It manages **only the items the installed package currently ships** (8 agents, 1
  claude-agent `orchestrator.md`, 1 `pipeline/config.json`, 7 skills: `azure-storage,
  brainstorm, chopchop, convertforagent, github-storage, oneshot, submit`).
- It creates **per-item** symlinks, so the repo's own agents/skills in the same dirs
  (e.g. `.claude/agents/code-reviewer.md`, skills like `absorb`, `backmerge-prs`)
  are left untouched.
- It **cannot** clean up deprecated ex-harness items that are no longer shipped (e.g.
  `implement`) — those are invisible to it. See "Manual triage" below.

## 1. One-time migration (run by a human, once)

From the repo root, drop the currently committed harness copies from git tracking, then
recreate them as symlinks:

```bash
# Ensure a current harness is installed:
pip install --upgrade --break-system-packages "git+https://github.com/onpaj/harness@master"

# Stop tracking the committed harness copies (keep nothing — init recreates as symlinks):
git rm -r --cached --ignore-unmatch \
  .agents \
  .pipeline/config.json \
  .claude/agents/orchestrator.md \
  .claude/skills/azure-storage \
  .claude/skills/brainstorm \
  .claude/skills/convertforagent \
  .claude/skills/github-storage \
  .claude/skills/submit

# Recreate everything the package ships as symlinks + write the .gitignore block:
agentharness init --symlink --force

git add -A
git commit -m "chore: symlink AgentHarness skills instead of committing copies"
```

`init --force` also converts any remaining real copies in place (it runs `git rm
--cached` + removes the file before linking).

## 2. Manual triage of non-shipped skills

These exist in `.claude/skills/` but are **not** shipped by the harness, so `init` never
manages them. Decide per item:

- `implement` — deprecated harness skill (renamed to `oneshot`). **Delete** unless you
  still rely on it.
- `brainstorming`, `subagent-driven-development`, `using-git-worktrees`, `writing-plans`,
  etc. — keep if genuinely repo-owned (e.g. superpowers skills), delete if they were
  stale harness copies. Verify before deleting.

## 3. Wire into `scripts/setup-cloud-env.sh`

Add two idempotent steps (the script uses `set -euo pipefail`, so keep them tolerant).

```bash
install_agentharness() {
  log "Installing AgentHarness"
  command -v pip >/dev/null 2>&1 || apt-get install -y python3-pip || true
  pip install --upgrade --break-system-packages \
    "git+https://github.com/onpaj/harness@master" || true
}

init_agentharness() {
  log "Linking AgentHarness skills (symlink mode)"
  agentharness init --symlink --force --dir "${REPO_ROOT}" || true
}
```

Wire into `main()` — `install_agentharness` after `install_gh`, and `init_agentharness`
after `require_repo` (it needs the repo present):

```bash
  install_gh
  install_agentharness
  require_repo
  init_agentharness
  restore_backend
  ...
```

`--symlink --force` keeps the cloud box current on every provision: `pip install
--upgrade` refreshes the package, and `init` relinks (idempotent no-op when unchanged).

## 4. Clean up the stale local install (developer machines)

If `agentharness --version` resolves to an old `uv tool` install (e.g. `~/.local/bin`):

```bash
uv tool upgrade agentharness    # or: uv tool uninstall agentharness
```

## Notes / caveats

- **Symlink discovery (go/no-go):** confirm Claude Code lists a symlinked skill dir
  before relying on this in the cloud — start Claude Code in the repo after step 1 and
  verify `oneshot`/`chopchop` appear under skills. (OS-level dir-symlink traversal makes
  this work in practice, but verify once.)
- **Dangling links:** uninstalling the package leaves the symlinks dangling (skills
  silently missing). Re-installing fixes them. After a package upgrade that renames/adds
  skills, re-run `agentharness init --symlink --force` to refresh links + the `.gitignore`
  block — the cloud script does this automatically.
- **Windows:** `init` falls back to copying (with a warning) if the OS refuses symlinks;
  copied items are not gitignored.
