# Architecture Review: AgentHarness Landing Page

## Architectural Fit Assessment

This feature is architecturally **isolated** from the rest of AgentHarness. The existing codebase is a Python async pipeline (agents, queues, storage backends); the landing page is a pure static asset bundle living in `/landingpage` with zero coupling to the runtime. There are no shared modules, no Python imports, no build pipeline integration.

**Integration points are minimal and one-directional:**
1. **Repo URL references** — CTAs link out to the GitHub repo (one-way, no backend handshake).
2. **Quick-start command text** — must stay in sync with the project README's install instructions (documentation drift risk, not technical coupling).
3. **Hosting** — served as static files from the repo (GitHub Pages compatible) or any CDN; no AgentHarness runtime touches it.

The architecture must therefore optimize for **self-containment, portability, and zero build complexity**, not for integration with the Python codebase. Treat `/landingpage` as a sibling project that happens to share a repo.

## Proposed Architecture

### Component Overview

```
landingpage/
│
├── index.html ─────────────────────── single document, semantic sections
│       │
│       ├── <head>
│       │     ├── meta (SEO, OG, Twitter)
│       │     ├── preload critical fonts/CSS
│       │     └── <link> CSS (load order: reset → tokens → layout → components → sections)
│       │
│       └── <body>
│             ├── <header>       (nav + logo, optional)
│             ├── <main>
│             │     ├── #hero
│             │     ├── #how-it-works
│             │     ├── #features
│             │     ├── #pipeline
│             │     └── #cta
│             ├── <footer>
│             └── <script type="module" src="js/main.js" defer>
│
├── assets/
│   ├── css/  (cascading load, no preprocessor)
│   │     reset → tokens → layout → components → sections
│   │
│   ├── js/   (ES modules, no bundler)
│   │     main.js ──┬── animations.js   (IntersectionObserver reveals + hero loop)
│   │               ├── copy.js          (clipboard handler with toast)
│   │               └── motion.js        (prefers-reduced-motion gate, RAF helpers)
│   │
│   └── img/, fonts/
│
└── README.md (how to view, deploy targets)
```

### Key Design Decisions

#### Decision 1: No Build Step, ES Modules Native

**Options considered:**
- (A) Vite/esbuild bundler with HMR
- (B) Single concatenated `bundle.js` + `bundle.css`
- (C) Native ES modules + plain CSS files loaded via `<link>`

**Chosen approach:** **(C)** — Native ES modules with `<script type="module">` and individual CSS files.

**Rationale:** The brief and spec explicitly require no build step and `file://` viewing. ES modules are supported in all target browsers (last 2 versions of Chrome/Firefox/Safari). Browsers can parallelize CSS link downloads. This keeps the contributor onboarding cost at zero and matches the "static site you can drag onto Netlify" requirement. The marginal performance gain from bundling is irrelevant at <500 KB total weight.

#### Decision 2: Vanilla CSS + IntersectionObserver as Default; GSAP Only as Progressive Enhancement

**Options considered:**
- (A) GSAP-first for all animations
- (B) Pure CSS animations + IntersectionObserver toggling classes
- (C) Hybrid: CSS for entrance/hover, GSAP only for the hero/pipeline complex sequencing

**Chosen approach:** **(B) as the baseline; (C) only if a specific animation cannot be expressed in CSS keyframes.**

**Rationale:** GSAP adds ~70 KB and a CDN dependency. 90% of the spec's animations (fade-up reveals, hover lifts, sequential step entrance, connecting line draw via `stroke-dashoffset`) are trivial CSS transitions toggled by IntersectionObserver-applied classes. The hero "agents working" visual and the pipeline animation can both be implemented as a self-contained `<canvas>` or animated SVG with `requestAnimationFrame` — not enough complexity to justify GSAP. **Default to no GSAP.** If during implementation a sequencing problem genuinely needs it, load via CDN with SRI and feature-detect.

#### Decision 3: Hero Visual = Animated SVG, Not Canvas

**Options considered:**
- (A) `<canvas>` with particle physics (cool but 200+ lines of JS)
- (B) Animated SVG with CSS keyframes on `<circle>` and `<path>` elements
- (C) CSS-only with `::before`/`::after` pseudo-elements
- (D) Lottie / pre-rendered video

**Chosen approach:** **(B)** — Inline SVG with CSS-driven animations.

**Rationale:** SVG is accessible (can have `<title>`/`<desc>`), scales perfectly across breakpoints, animates via CSS without JS, degrades gracefully under `prefers-reduced-motion` (just remove the `animation` property), and weighs <5 KB. Canvas requires JS, has no semantic meaning for assistive tech, and forces manual handling of `visibilitychange` for tab-backgrounding. The spec calls for "particle/node graph" or "pipeline glyph" — both are SVG-natural.

#### Decision 4: Single `index.html`, No Section Includes

**Options considered:**
- (A) Split sections into separate HTML files, fetched at runtime
- (B) Server-side includes (requires a server)
- (C) Single monolithic `index.html`

**Chosen approach:** **(C)** — single file, ~400-500 lines.

**Rationale:** No build = no template engine. Runtime fetching of HTML fragments adds complexity, breaks `file://` viewing, and creates a flash-of-empty-content. The spec already permits up to ~600 lines. Five clearly-commented `<section>` blocks in one file is more maintainable than five files plus orchestration. **Constraint:** if `index.html` exceeds 600 lines during implementation, that's the signal to extract — not a default.

#### Decision 5: CSS Custom Properties as the Single Source of Truth for Theme

**Options considered:**
- (A) Sass variables (requires build)
- (B) Hardcoded hex throughout
- (C) CSS custom properties in `tokens.css`, consumed everywhere

**Chosen approach:** **(C)**.

**Rationale:** Native CSS custom properties work in all target browsers, require no build, and let `prefers-reduced-motion`/`prefers-color-scheme` queries override them at runtime if ever needed. Centralizes the palette and spacing scale.

#### Decision 6: Click-to-Copy via `navigator.clipboard.writeText` with `document.execCommand` Fallback

**Options considered:**
- (A) Modern Clipboard API only
- (B) `document.execCommand('copy')` only (deprecated but universal)
- (C) Feature-detect Clipboard API, fall back to `execCommand`

**Chosen approach:** **(C)**.

**Rationale:** Clipboard API requires HTTPS or localhost; if a user opens via `file://`, it fails. The fallback covers that. Both wrapped in a single `copyToClipboard(text)` function in `copy.js`.

## Implementation Guidance

### Directory / Module Structure

Follow the spec's file layout exactly. Critical conventions:

- **CSS load order is fixed:** `reset.css` → `tokens.css` → `layout.css` → `components.css` → `sections.css`. Each file only references tokens defined upstream. No circular references.
- **JS entry is `main.js`** which imports `animations.js`, `copy.js`, `motion.js`. Each module exports named init functions: `initReveals()`, `initCopyButtons()`, `initMotionGate()`. `main.js` is the only orchestrator.
- **No `style="..."` attributes in HTML** (NFR-2 forbids inline handlers; extend the rule to inline styles for consistency).
- **Icons in `assets/img/icons/` as individual SVG files**, inlined into HTML at author time (not via JS). Inlining lets CSS color them via `currentColor`.

### Interfaces and Contracts

#### JS module contracts

```js
// motion.js
export const prefersReducedMotion: () => boolean
export const onMotionPreferenceChange: (cb: (reduced: boolean) => void) => void

// animations.js
export const initReveals: (options?: { rootMargin?: string, threshold?: number }) => void
//   Selects [data-reveal] elements, attaches IntersectionObserver,
//   adds .is-revealed class once. Skips entirely if prefersReducedMotion().

export const initHeroAnimation: () => void
//   Starts hero SVG animation. Pauses on document.visibilitychange.
//   Skips if prefersReducedMotion().

// copy.js
export const initCopyButtons: () => void
//   Wires all [data-copy] elements. On click, copies data-copy attribute value
//   and shows .is-copied state on the trigger for 2000ms.
```

#### HTML data-attribute contract

| Attribute | Where | Purpose |
|---|---|---|
| `data-reveal` | Any element to fade-in on scroll | Picked up by `initReveals` |
| `data-reveal-delay="100"` | Optional, in ms | Stagger reveals within a section |
| `data-copy="pip install agentharness"` | Button or `<code>` wrapped in button | Text to copy |
| `data-copy-feedback="Copied!"` | Optional | Override default toast text |

This contract is the only API surface developers must respect. Adding new animated elements = add `data-reveal`. Adding new copyable commands = add `data-copy`.

#### CSS class contract

- `.is-revealed` — applied by JS when an element enters viewport. CSS handles the actual transition.
- `.is-copied` — applied by JS for 2 seconds after a successful copy.
- `.no-motion` — applied to `<html>` if `prefers-reduced-motion: reduce`. CSS uses `:root.no-motion *` to disable transitions/animations globally as a safety net.

### Data Flow

**Page load:**
```
HTML parsed → CSS files load in cascade order → DOMContentLoaded
  → main.js executes (deferred module)
    → motion.js sets .no-motion on <html> if needed
    → animations.js attaches IntersectionObserver to [data-reveal]
    → animations.js starts hero SVG (CSS-driven, JS only toggles play state)
    → copy.js attaches click handlers to [data-copy]
```

**Scroll reveal:**
```
User scrolls → IntersectionObserver fires for entering element
  → JS adds .is-revealed class
  → CSS transition runs (opacity + transform)
  → Observer disconnects from that element (one-shot per spec FR-2)
```

**Copy interaction:**
```
User clicks [data-copy] → copy.js reads data-copy value
  → navigator.clipboard.writeText() (or execCommand fallback)
  → adds .is-copied class to button
  → setTimeout 2000ms → removes .is-copied class
```

**Tab backgrounded:**
```
document.visibilitychange fires → animations.js pauses hero SVG via
  document.documentElement.style.setProperty('--hero-play-state', 'paused')
  (CSS animation-play-state reads this custom property)
```

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| GSAP CDN failure breaks animations | Medium | Default to no GSAP. If introduced later, feature-detect `window.gsap` and fall back to CSS path. SRI hash prevents tampering. |
| Hero SVG animation runs on low-end mobile and tanks battery | Medium | Cap animation to `prefers-reduced-motion` users seeing static frame. Pause on `visibilitychange`. Use only `transform`/`opacity` to keep on compositor thread. |
| Quick-start command text drifts from README | Medium | Single source of truth: include a comment in `index.html` linking to the README line. Add a checklist item to release docs. (Out-of-band; can't be enforced by code without a build step.) |
| `file://` users hit Clipboard API restrictions | Low | `execCommand('copy')` fallback in `copy.js`. |
| Web fonts cause FOIT/FOUT | Low | Use system font stack first. If web fonts added later, `font-display: swap` mandatory. |
| OG image missing at launch breaks social sharing | Medium | Make OG image a launch blocker. Until designer delivers, ship a placeholder generated from the hero SVG to a 1200×630 PNG. |
| `IntersectionObserver` not supported on very old browsers | Low | Spec targets last 2 versions of evergreen browsers — all support it. No polyfill needed. If feature-detect fails, just add `.is-revealed` to all `[data-reveal]` elements at load (graceful degradation). |
| Repo URL changes (org rename, repo move) | Low | Centralize all repo URLs in a single JS constant or HTML data attribute on `<body data-repo-url="...">` so a single edit propagates. |

## Specification Amendments

1. **Amend FR-1:** The hero "animated visual" should be implemented as **inline animated SVG**, not canvas, unless the designer specifies a particle effect that genuinely requires canvas. Lock this choice early to avoid mid-build pivots.

2. **Amend NFR-4:** Add a contract that **all repo URLs and the quick-start command live in one place** — either as `data-*` attributes on `<body>` or as constants at the top of `main.js`, then projected into the DOM. This prevents the "five places to edit when the URL changes" problem.

3. **Amend FR-6:** Specify that the IntersectionObserver should use `rootMargin: '0px 0px -10% 0px'` and `threshold: 0.15` so reveals trigger slightly before the element fully enters view — feels more responsive. Each observer disconnects per-element after first trigger (one-shot).

4. **Amend Open Question 3 (GSAP):** Resolved — **start without GSAP. Do not introduce it unless a specific animation explicitly fails in vanilla CSS/JS during implementation.** Document the fallback path if it is added.

5. **Amend Open Question 10 (reduced motion):** Resolved — **show a static representative frame** of the hero (single first-frame SVG state with no `animation` property). All scroll reveals appear in their final state immediately. No hidden content under `prefers-reduced-motion`.

6. **Add NFR-6 (Deployability):** Page must work via three deployment paths without modification: (a) `file://` direct open, (b) any static file server (Python `http.server`, `npx serve`), (c) GitHub Pages from `/landingpage` subdirectory. All asset paths must be relative (no leading `/`).

7. **Add to FR-8:** Add a `<noscript>` block that displays a brief notice ("Best experienced with JavaScript enabled") but ensures all content (hero text, sections, CTAs) is fully readable and links work without JS. Animations skip; static layout shows.

## Prerequisites

Before implementation can start, the following must be confirmed:

1. **GitHub repository URL** — confirmed as `https://github.com/onpaj/AgentHarness` (verify with project owner; this powers every CTA on the page).
2. **Quick-start command exact text** — read current README and lock the install/run command. Spec assumes `pip install agentharness && agentharness brainstorm`; verify or correct.
3. **Headline copy** — designer or PM picks final headline from candidates before developer starts; placeholder copy is acceptable for build but must be replaced before launch.
4. **Logo/wordmark decision** — confirm whether a logo exists or whether a typographic wordmark is the launch artifact.
5. **OG image** — design deliverable; can be placeholder during build, must be final before launch.
6. **Hosting target** — confirm GitHub Pages vs. Netlify vs. Vercel. Affects only the relative-path constraint, which is already enforced. No code changes required to switch.
7. **Icon set source** — feature card and step icons. Recommend Lucide or Heroicons (MIT-licensed, SVG, optically consistent). Designer to specify mapping (e.g., feature: "Multi-agent pipeline" → which icon).
8. **Font decision** — confirm system font stack is acceptable, or specify Inter + JetBrains Mono with self-hosted vs. CDN. Self-hosted preferred for offline `file://` support.

No infrastructure, migrations, or backend prerequisites — the page is pure static content.