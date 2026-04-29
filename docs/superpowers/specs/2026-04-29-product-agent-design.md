# Specification: Product Agent — Analyst Open Questions Loop

## Summary

When the analyst agent produces a spec with unresolved open questions, a new product agent (Opus model) answers those questions, and the analyst re-runs incorporating the answers. This loop is capped at a configurable number of iterations. If the analyst signals completion without questions, the pipeline skips the product agent entirely.

## Background

The analyst currently emits an `## Open Questions` section in its spec for anything the brief left unclear. Nothing in the pipeline acts on these questions — downstream agents receive an incomplete spec and must make assumptions. The product agent closes this gap by answering questions before the spec is handed to the architect.

## Functional Requirements

### FR-1: Analyst Status Signal

The analyst must end its output with one of:

```
## Status: COMPLETE
```
or
```
## Status: HAS_QUESTIONS
```

`HAS_QUESTIONS` is emitted when `## Open Questions` contains at least one question. `COMPLETE` is emitted when the section is empty or absent.

**Acceptance criteria:**
- Analyst output without a status line is treated as `COMPLETE` (safe default)
- Parser extracts `COMPLETE` or `HAS_QUESTIONS` from a `## Status:` line

### FR-2: Conditional Product Agent Dispatch

After `analyzing` completes:

- Signal `COMPLETE` → transition to `architecting` (unchanged path)
- Signal `HAS_QUESTIONS` + iterations < `max_analyst_iterations` → transition to `questioning`, enqueue product agent
- Signal `HAS_QUESTIONS` + iterations >= `max_analyst_iterations` → proceed to `architecting` (cap reached)

**Acceptance criteria:**
- Product agent is never enqueued when analyst signals `COMPLETE`
- Pipeline always advances past `analyzing` after cap is reached
- `current_analyst_iteration` is incremented each time the analyst re-runs

### FR-3: Product Agent

A new agent `.agents/product.md` with model `claude-opus-4-7`:

- Reads the latest `spec.r{N}.md` as input
- Writes `answers.r{N}.md` containing structured answers to every question in `## Open Questions`
- Output format: markdown, one section per question answered

**Acceptance criteria:**
- Product agent output is stored at `artifacts/{feature_id}/answers.r{N}.md`
- Agent definition has `output_file_glob: answers.md` mapped to the revision-named artifact

### FR-4: Analyst Re-Run With Answers

After the product agent completes (`questioning` → `analyzing`):

- Dispatcher enqueues the analyst with all accumulated inputs:
  - `brief.md`
  - All previous `spec.r1..N.md` files
  - All previous `answers.r1..N.md` files
- Analyst prompt instructs it to read all available `answers.r{N}.md` files and incorporate every answer before producing the revised spec
- Analyst produces `spec.r{N+1}.md`

**Acceptance criteria:**
- Analyst re-run receives the full artifact history, not just the latest revision
- Revised spec has `## Open Questions` empty or absent when all questions are answered

### FR-5: Iteration Cap

`FeatureStateConfig` gains two fields:

```python
max_analyst_iterations: int = 2       # from config.json
current_analyst_iteration: int = 0    # runtime counter
```

`config.json` gains a top-level key:
```json
{ "max_analyst_iterations": 2 }
```

**Acceptance criteria:**
- Default is 2 if key absent from `config.json`
- When cap is reached, pipeline proceeds to `architecting` with whatever spec exists

## State Machine

```
analyzing → [COMPLETE]       → architecting → ...
          → [HAS_QUESTIONS,
              iter < max]    → questioning  → analyzing (re-run, iter++)
          → [HAS_QUESTIONS,
              iter >= max]   → architecting
```

New `FeatureStatus` value: `questioning`
New queue key: `product-queue`

## Artifact Naming

```
artifacts/{feature_id}/brief.md
artifacts/{feature_id}/spec.r1.md          # first analyst pass
artifacts/{feature_id}/answers.r1.md       # product agent — iteration 1
artifacts/{feature_id}/spec.r2.md          # analyst re-run — iteration 2
artifacts/{feature_id}/answers.r2.md       # product agent — iteration 2 (if needed)
artifacts/{feature_id}/spec.r{N}.md        # final clean spec (used by architect onward)
```

Downstream agents (architect, designer, planner) receive the highest-revision `spec.r{N}.md` as their spec input.

## Dispatcher Changes

| Location | Change |
|---|---|
| `_LINEAR_TRANSITIONS` | Remove `"analyzing"` entry (branching logic replaces it) |
| `STATE_TO_QUEUE` | Add `FeatureStatus.questioning: "product-queue"` |
| `dispatch_after_completion` | Add `analyzing` branch (parse status, check cap, dispatch) |
| `dispatch_after_completion` | Add `questioning` branch (increment counter, re-enqueue analyst) |
| `_parse_analyst_status()` | New helper mirroring `_parse_developer_status` |
| `build_phase_task` | Handle `questioning` phase and `analyzing` re-runs with revision artifacts |
| `_artifacts_for_phase` | Update `analyzing` entry to include all `answers.r{N}.md` files |

## Agent Definition

`.agents/product.md` frontmatter:

```yaml
id: product
display_name: "Product Agent"
model: claude-opus-4-7
phase: questioning
max_turns: 1
allowed_tools: []
output_format: markdown
visibility_timeout: 300
retry_limit: 3
output_parsing: none
output_file_glob: answers.md
```

System prompt: reads the spec, finds `## Open Questions`, provides a direct authoritative answer to each question drawing on the codebase context files.

## Non-Functional Requirements

### NFR-1: Transparency

- `questioning` phase is visible in TUI alongside other phases
- Each iteration appears as a distinct phase entry (e.g. `questioning r1`, `analyzing r2`)

### NFR-2: Cost

- Product agent uses Opus only when questions exist — no Opus calls for complete briefs
- Cap prevents unbounded Opus token spend

## Out of Scope

- Product agent interacting with the user directly (it answers autonomously)
- Product agent reading external sources beyond the spec and codebase context files
- Retroactively re-running the product agent on existing features

## Open Questions

None.
