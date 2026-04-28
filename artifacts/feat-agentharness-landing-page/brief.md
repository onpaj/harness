# Feature Brief: AgentHarness Landing Page

## Problem Statement
Developers discovering AgentHarness have no compelling entry point that communicates the core value proposition: you can delegate the implementation grind to autonomous Claude agents and reclaim your time for design, architecture, and creative work.

## Goals
- Convert developer visitors into users by making the value prop undeniable in under 10 seconds
- Communicate the "ship faster by delegating the grind" message visually and emotionally
- Provide enough technical credibility that developers trust the project

## Functional Requirements
- Hero section: bold headline + animated/dynamic visual that evokes autonomous agents working in the background
- How-it-works section: 3-step visual flow (brainstorm → agents work → code ships) with subtle JS animation
- Features section: highlight key differentiators (multi-agent pipeline, per-task review loop, GitHub/Azure backends, zero babysitting)
- Social proof / credibility section: pipeline diagram or terminal-style animation showing agents running
- CTA section: "Get started" pointing to GitHub repo + quick-start command
- Smooth scroll, parallax or scroll-triggered animations (JS-driven)
- Mobile responsive

## Non-Functional Requirements
- Pure static site: HTML + CSS + vanilla JS (or minimal JS library like GSAP for animations)
- No build step required — works by opening index.html directly or serving as static files
- Fast load: no heavy frameworks, no React/Vue/etc.
- Dark blue color palette (#0a0f1e base, #1e3a5f mid, #00d4ff accent), bold typography

## Technical Constraints
- Lives in `/landingpage` folder in the AgentHarness repo
- No backend, no API calls
- Self-contained: all assets relative paths

## Out of Scope
- Documentation site / full docs
- Interactive demo or live pipeline connection
- Authentication or user accounts
- Analytics integration

## Success Criteria
- A developer landing on the page immediately understands: "Claude agents build my features while I do other things"
- Page looks polished enough to share on X/HN/Reddit without embarrassment
- Loads and animates correctly on Chrome, Firefox, Safari

## Additional Context
AgentHarness is a distributed, event-driven pipeline that autonomously processes development tasks using specialized Claude agents. A user describes a feature via brainstorm, uploads a brief, and a chain of agents (analyst → architect → designer → planner → developer → reviewer) produces the implementation without further human input. Target audience: developers already comfortable with Claude Code who want to scale their output. Design direction: dark blue (#0a0f1e base, #00d4ff accent), bold modern typography, Vercel/Linear aesthetic — premium, fast, developer-native. Animations encouraged: scroll-triggered reveals, terminal-style agent activity, pipeline flow diagram.
