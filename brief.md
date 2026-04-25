# Feature Brief: AgentHarness Landing Page

## Problem Statement
Engineers on the team already use Claude Code, but they still spend significant time babysitting it — guiding decisions, correcting mistakes, debugging outputs, and context-switching between tasks. There's still too much human in the loop. The landing page exists to show colleagues that AgentHarness solves exactly this: you describe the feature once, and the autonomous pipeline handles the rest.

## Goals
- Convince engineer colleagues to try AgentHarness by clearly communicating the "before vs after" value proposition
- Communicate what AgentHarness is, what it does, and how to get started — in under 2 minutes of reading

## Functional Requirements
- Hero section: punchy headline + subheadline focused on "remove yourself from the loop"
- Problem section: relatable "you're using Claude Code but still babysitting it" framing
- How it works: visual pipeline walkthrough (brainstorm → planner → architect → designer → developer(s) → reviewer → done)
- Key benefits: save hours, no guiding, no correcting, no context-switching
- Quick start / how to use: minimal steps to get started (brainstorm skill, implement command)
- Footer with project context

## Non-Functional Requirements
- Fully static — no backend, no build step required (plain HTML + CSS + minimal JS)
- Loads fast, no heavy frameworks
- Looks polished enough to take seriously

## Technical Constraints
- Single HTML file preferred (self-contained, easy to share and host)
- No React, no npm, no build pipeline — it's a landing page, not an app
- Can use a CDN-hosted CSS library if needed (Tailwind CDN, or hand-rolled)

## Out of Scope
- Authentication or login
- Interactive demo
- Documentation site (this is a marketing/intro page only)
- Internationalization

## Success Criteria
- A colleague reads it and says "I want to try this"
- The pipeline steps are clear without needing to read the README
- Page looks professional: minimal, clean, dark blue color scheme

## Additional Context
AgentHarness is a distributed, event-driven pipeline running specialized Claude agents in sequence: planner → architect → designer → developer(s) → reviewer. Users interact via Claude Code skills (`/brainstorm`, `/implement`) or CLI commands. The target audience is engineers already familiar with Claude Code who want to stop babysitting it.
