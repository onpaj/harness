# Feature Brief: AgentHarness Landing Page

## Problem Statement
Developer colleagues don't know AgentHarness exists or what it can do for them. They need a compelling, fast-loading page that convinces them to try it — written for developers, by a developer who uses it.

## Goals
- Communicate the core value proposition in under 10 seconds of reading
- Motivate developer colleagues to request access or start using it
- Convey the "fire and forget" autonomous workflow clearly

## Functional Requirements
- Static HTML single-page site (no build step, no framework required)
- Hero section with punchy headline and subheading capturing the "you can sleep meanwhile" angle
- What it is section: brief explanation of the pipeline (brief → analyst → architect → designer → planner → developer → reviewer → done)
- Why use it section: key benefits (async, autonomous, no babysitting required)
- How it works section: step-by-step flow a developer would follow (brainstorm → submit → walk away)
- Call to action: encourages colleagues to try it or reach out

## Non-Functional Requirements
- Fast load — no external JS frameworks, minimal dependencies
- Works offline / from file system (no server needed)
- Readable on desktop (primary target); mobile acceptable but not priority

## Technical Constraints
- Single `index.html` file (inline CSS, no separate stylesheets required)
- No backend, no build pipeline
- Can reference CDN fonts (e.g. Google Fonts) for typography

## Out of Scope
- Authentication or gating
- Live demo or interactive sandbox
- Analytics or tracking
- Documentation or API reference

## Success Criteria
- A developer colleague reads it and immediately understands what AgentHarness does
- They ask how to get access or try it themselves
- The page communicates autonomy: describe → submit → sleep → wake up to a PR

## Additional Context
Design direction: dark background, deep blue accent color, bold modern typography, high contrast. Tone: confident, concise, developer-native — no fluff. Think of it as a pitch from one engineer to another.
