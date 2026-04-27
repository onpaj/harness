```markdown
# Architecture Review: AgentHarness Landing Page

## Architectural Fit Assessment

The landing page is intentionally decoupled from the core AgentHarness Python pipeline. It lives in a self-contained `/landingpage` directory at the repo root and shares no runtime, build tooling, or dependencies with the rest of the project. This isolation is correct — marketing surface and orchestration runtime have nothing to gain from coupling.

The only integration points are:
1. **Repo-relative hosting**: the page must be servable as static files (GitHub Pages, Netlify, Vercel, or `python -m http.server`).
2. **Outbound links**: GitHub repo URL, install/quick-start command — both copied as static text, no API calls.
3. **Asset locality**: every CSS, JS, font, and image must use relative paths so the page works whether opened via `file://` or served from any subpath.

The brief mandates "no build step, no framework, vanilla JS" — this aligns with the project's "minimal infra" sensibility (Python stdlib + httpx, no heavy frameworks). The architecture should preserve that ethos: zero npm, zero bundler, zero generated artifacts checked into git.

## Proposed Architecture

### Component Overview

```
landingpage/
├── index.html              # Single-page document; semantic sections
├── assets/
│   ├── css/
│   │   ├── reset.css       # Minimal modern reset (box-sizing, margins)
│   │   ├── tokens.css      # Design tokens: colors, spacing, type scale
│   │   ├── base.css        # Typography, body, layout primitives
│   │   └── sections.css    # Per-section styles (hero, how-it-works, etc.)
│   ├── js/
│   │   ├── main.js         # Entry point: imports + initializes modules
│   │   ├── scroll-reveal.js   # IntersectionObserver-based reveal animations
│   │   ├── pipeline-anim.js   # Pipeline flow diagram animation (SVG/canvas)
│   │   ├── terminal-anim.js   # Terminal-style agent activity playback
│   │   └── parallax.js        # Scroll-driven parallax for hero
│   ├── img/                # SVG logos, icons (prefer SVG over raster)
│   └── fonts/              # Self-hosted woff2 (optional; system font stack acceptable)
└── README.md               # How to view/deploy

         Browser
            │
            ▼
   ┌─────────────────┐
   │   index.html    │  ← Semantic HTML, all sections present at load
   └────────┬────────┘
            │ links/loads
            ├──► assets/css/*.css   (cascade: reset → tokens → base → sections)
            └──► assets/js/main.js  (type="module"; imports submodules)
                        │
                        ├──► scroll-reveal.js   (IntersectionObserver)
                        ├──► pipeline-anim.js   (SVG <use> + CSS keyframes / requestAnimationFrame)
                        ├──► terminal-anim.js   (typewriter effect, setInterval)
                        └──► parallax.js        (scroll listener, transform: translate3d)
```

### Key Design Decisions

#### Decision 1: Native ES Modules vs. single concatenated JS file
**Options considered:**
- (A) Single `main.js` with everything inlined.
- (B) ES Modules (`<script type="module">`), one file per concern.
- (C) GSAP or another animation library.

**Chosen approach:** ES Modules (B), no animation library, vanilla JS only.

**Rationale:** Modules give cohesion (one file = one animation responsibility) without requiring a bundler — modern browsers (Chrome/Firefox/Safari, all supported targets) load `import` natively. GSAP is overkill; CSS keyframes + `IntersectionObserver` + `requestAnimationFrame` cover every animation in the brief. Avoiding GSAP saves ~70 KB and a license decision.

#### Decision 2: Animation strategy
**Options considered:**
- CSS-only animations (keyframes, transitions).
- JS-driven (rAF loops, timeline libraries).
- Hybrid: CSS for transitions, JS only for orchestration/triggering.

**Chosen approach:** Hybrid — CSS owns the visual definition (keyframes, easing); JS owns *when* animations start (`IntersectionObserver` adds an `.is-visible` class, CSS handles the rest). Two exceptions: pipeline flow animation and terminal typewriter need imperative control, so they use `requestAnimationFrame` and `setInterval` respectively.

**Rationale:** CSS animations are GPU-accelerated and degrade gracefully if JS fails. JS-driven orchestration keeps logic testable and decoupled from styling. Hybrid is the standard pattern for Vercel/Linear-class marketing sites.

#### Decision 3: Pipeline diagram rendering
**Options considered:**
- Inline SVG (hand-authored).
- Canvas-drawn diagram.
- HTML/CSS box layout.

**Chosen approach:** Inline SVG with CSS-animated `stroke-dashoffset` for flow lines and CSS class toggles for node "active" states.

**Rationale:** SVG is crisp at any DPI, accessible (text labels are real text), themeable via CSS variables, and small. Canvas would force pixel work and break a11y. The pipeline has fixed topology (analyst → architect → designer → planner → developer → reviewer) so a hand-authored SVG is simpler than a generative approach.

#### Decision 4: Terminal animation
**Chosen approach:** Pre-scripted "transcript" defined as a JS array of `{ agent, line, delayMs }` objects, played back with `setTimeout`. No real subprocess, no streaming. Cycle the loop after a final-state pause so users arriving mid-animation still see meaningful content.

**Rationale:** The brief explicitly excludes "live pipeline connection". A scripted transcript is deterministic, lightweight, and visually identical to a real run for the page's purpose.

#### Decision 5: Design tokens via CSS custom properties
**Chosen approach:** Define `:root { --color-bg, --color-mid, --color-accent, --space-*, --font-*, --radius-* }` in `tokens.css`. All other CSS references variables only.

**Rationale:** Single source of truth, trivial dark-mode-only enforcement, and frictionless tweaking during design polish.

#### Decision 6: No JS framework, no transpilation
**Chosen approach:** Modern syntax (ES2022) targeted directly at evergreen browsers. No Babel, no TypeScript, no PostCSS.

**Rationale:** Brief mandates "no build step". The supported browser matrix (Chrome, Firefox, Safari — current) handles native modules, optional chaining, and modern CSS without polyfills.

## Implementation Guidance

### Directory / Module Structure

Create exactly the tree shown above under `/landingpage`. Do not introduce `package.json`, lockfiles, or config files. A short `README.md` documents how to preview (`python -m http.server 8000` from `/landingpage`).

### Interfaces and Contracts

**JS module contract — every animation module exports a single `init()` function:**

```js
// assets/js/scroll-reveal.js
export function init(rootEl = document) { /* attach observers */ }
```

```js
// assets/js/main.js
import { init as initScrollReveal } from './scroll-reveal.js';
import { init as initPipeline }     from './pipeline-anim.js';
import { init as initTerminal }     from './terminal-anim.js';
import { init as initParallax }     from './parallax.js';

document.addEventListener('DOMContentLoaded', () => {
  initScrollReveal();
  initPipeline();
  initTerminal();
  initParallax();
});
```

**HTML contract — sections use stable IDs and `data-*` hooks:**

| Section | `<section id>` | Purpose |
|---------|----------------|---------|
| Hero | `hero` | Headline + parallax visual |
| How it works | `how-it-works` | 3-step flow |
| Features | `features` | Differentiator grid |
| Pipeline visual | `pipeline` | SVG + terminal |
| CTA | `cta` | GitHub link + quick-start |

Reveal-on-scroll elements carry `data-reveal` (optional `data-reveal-delay="200"`). The scroll-reveal module queries `[data-reveal]` and adds `.is-visible` when intersecting.

**CSS contract — BEM-lite class naming, no nesting beyond two levels:**

```
.hero, .hero__title, .hero__cta
.feature-card, .feature-card--accent
.pipeline-node, .pipeline-node.is-active
```

**Reduced-motion contract:** wrap all non-essential animations in `@media (prefers-reduced-motion: no-preference)`. Static fallback must convey the same information.

### Data Flow

**Page load → first paint:**
1. Browser parses `index.html`, requests CSS in cascade order (blocking).
2. Critical above-the-fold styles render hero immediately.
3. `main.js` (deferred via `type="module"`) loads, fires `DOMContentLoaded` handler.
4. Each `init()` attaches its observers/timers and exits.

**Scroll → reveal:**
1. User scrolls; `IntersectionObserver` fires for each `[data-reveal]` element.
2. Module adds `.is-visible`; CSS transition fades/translates the element in.
3. Observer disconnects per-element after first reveal (one-shot).

**Pipeline animation loop:**
1. On viewport entry, `pipeline-anim.js` starts a state machine: highlight node N for `T ms`, animate stroke from N→N+1, advance.
2. After full cycle, pause `T_pause`, restart. Cancellable via `IntersectionObserver` exit.

**Terminal animation:**
1. Scripted transcript array iterated with `setTimeout` chain (not `setInterval` — avoids drift).
2. Lines appended to a `<pre>` with monospace styling; cursor `<span>` blinks via CSS.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Janky scroll on low-end mobile from too many parallax/reveal listeners | High | Use `IntersectionObserver` (not scroll event listeners); throttle parallax via `requestAnimationFrame`; respect `prefers-reduced-motion`. |
| FOUC (flash of unstyled content) before CSS loads | Medium | Inline critical hero CSS in `<head>`; mark fold-below CSS `media="print" onload="this.media='all'"` only if needed — usually unnecessary for a single-page site. |
| Animations running while tab is hidden, wasting battery | Medium | Pause loops on `document.visibilitychange === 'hidden'`. |
| Native ES modules fail on `file://` in Chrome (CORS for module imports) | Medium | Document in `README.md` that local preview requires a static server (`python -m http.server`). Brief says "open index.html directly" — clarify this is for non-module assets; modules need a server. **Spec amendment proposed below.** |
| SVG pipeline diagram unreadable on small screens | Medium | Use `viewBox` + `preserveAspectRatio`; switch to vertical stacked layout under 768 px via CSS. |
| Self-hosted fonts bloat first paint | Low | Default to a system font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif`). Only self-host if a specific bold display face is selected during design. |
| Accessibility regressions from animation-heavy design | High | All sections must be navigable and comprehensible without JS. Use semantic HTML (`<header>`, `<section>`, `<nav>`, `<main>`). All decorative SVGs `aria-hidden="true"`; meaningful ones get `<title>`. Color contrast against `#0a0f1e` base must hit WCAG AA (4.5:1 for body, 3:1 for large text). |
| Dead JS imports increase load time as page grows | Low | Keep each module under ~150 lines; lazy-import non-critical modules with dynamic `import()` only if measured load time exceeds 1s. |

## Specification Amendments

1. **Local preview requires a static server, not just `file://`.** The brief states "works by opening index.html directly". With ES modules this is browser-policy-blocked. Either (a) inline all JS into `<script>` tags (no modules, single file) or (b) clarify that previewing requires `python -m http.server` / equivalent. **Recommend (b)** — preserves modular architecture, documented in `landingpage/README.md`. Static hosting (GitHub Pages, etc.) is unaffected.

2. **Add an `accessibility` requirement** to the spec: WCAG AA contrast, `prefers-reduced-motion` honored, semantic landmarks, keyboard-navigable CTA. Brief is silent on a11y but a "polished enough to share on HN" page will be roasted without it.

3. **Performance budget**: total page weight ≤ 250 KB (HTML + CSS + JS, excluding fonts), Largest Contentful Paint < 1.5 s on a fast 3G profile. Codifies "fast load" non-functional requirement.

4. **Asset paths**: explicitly require relative paths (`./assets/...`), not root-relative (`/assets/...`), so the page works under any subpath (e.g., `username.github.io/AgentHarness/landingpage/`).

5. **Out-of-scope addition**: SEO meta tags beyond a sensible `<title>`, OG image, and description are out of scope unless the brief is amended. A polished but minimal `<head>` is in scope.

## Prerequisites

Before implementation begins:

1. **Design tokens locked**: confirm color palette (`#0a0f1e`, `#1e3a5f`, `#00d4ff`) and pick exactly one display font + one body font (or commit to system stack). Without this, sections.css will churn.
2. **Pipeline diagram structure decided**: confirm the six-node sequence (analyst → architect → designer → planner → developer → reviewer) is what the page should depict, including whether to show the per-task review loop arrow.
3. **Terminal transcript scripted**: write the ~10–20 line scripted agent transcript before implementing `terminal-anim.js`. Treat this as copywriting, not code.
4. **Quick-start command finalized**: the CTA section needs the exact one-liner (`pip install agentharness && agentharness brainstorm` or similar). Confirm with maintainer.
5. **GitHub URL confirmed**: canonical repo URL for the "Get started" CTA.
6. **Hosting target chosen**: GitHub Pages vs. Netlify vs. embedded in repo only. Affects whether a `CNAME` or `404.html` is needed and whether asset paths must be repo-subpath-aware.
7. **No new tooling installed**: confirm `/landingpage` will not be linted/built by repo-level tooling; if pre-commit hooks exist for the Python codebase, ensure they ignore `/landingpage/**`.
```