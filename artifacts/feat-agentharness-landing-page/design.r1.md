# Design: AgentHarness Landing Page

## UX/UI Design

### Visual Language

Dark-first, developer-native aesthetic — Vercel/Linear tone. High contrast, minimal chrome, purposeful motion.

```
Palette (from tokens):
  Background:  #0a0f1e  (deep navy)
  Surface:     #1e3a5f  (card/section mid)
  Accent:      #00d4ff  (cyan — CTAs, highlights, glow)
  Text:        #e6edf3  (primary)
  Text-dim:    #8b9bb4  (secondary/metadata)
  Border:      rgba(255,255,255,0.08)
```

Typography:
```
  Display: 'Inter', system-ui, sans-serif
  Mono:    'JetBrains Mono', ui-monospace, monospace
  Fallback: system stack only (web fonts opt-in, not default)
```

---

### Wireframes

#### Layout: Full Page (Desktop 1440px)

```
┌─────────────────────────────────────────────────────────────────┐
│  <header>  AgentHarness    [View on GitHub ↗]                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  #hero  (100vh)                                                 │
│  ┌───────────────────────┐  ┌──────────────────────────────┐   │
│  │  Delegate the grind.  │  │   [animated SVG pipeline]    │   │
│  │  Reclaim your time.   │  │                              │   │
│  │                       │  │  ●──●──●──●──●──●            │   │
│  │  A chain of Claude    │  │  analyst → reviewer          │   │
│  │  agents builds your   │  │  (nodes pulse in sequence)   │   │
│  │  features while you   │  │                              │   │
│  │  focus on what        │  └──────────────────────────────┘   │
│  │  matters.             │                                     │
│  │                       │                                     │
│  │  [Get started ↗]      │                                     │
│  │  $ pip install…  [⎘]  │                                     │
│  └───────────────────────┘                                     │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  #how-it-works                                                  │
│                                                                 │
│   [1. Brainstorm] ──→ [2. Agents work] ──→ [3. Code ships]     │
│    icon + title         icon + title         icon + title       │
│    1-2 sentences        1-2 sentences        1-2 sentences      │
│    (fade+slide in)      (delayed)            (delayed)          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  #features                                                      │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ [icon]       │  │ [icon]       │  │ [icon]       │         │
│  │ Multi-agent  │  │ Per-task     │  │ Pluggable    │         │
│  │ pipeline     │  │ review loop  │  │ backends     │         │
│  │ …desc…       │  │ …desc…       │  │ …desc…       │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Zero babysit │  │ Context files│  │ Serial tasks │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  #pipeline  (dark surface, monospace)                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  $ agentharness observe                                 │   │
│  │  [12:01:04] analyst       → analyzing   (feat-abc123)   │   │
│  │  [12:01:22] analyst       ✓ complete    (18s)           │   │
│  │  [12:01:23] architect     → analyzing                   │   │
│  │  [12:01:55] architect     ✓ complete    (32s)           │   │
│  │  [12:01:56] planner       → planning                    │   │
│  │  [12:02:14] planner       ✓ complete    (18s)  3 tasks  │   │
│  │  [12:02:15] developer[1]  → in_progress                 │   │
│  │  [12:03:44] reviewer[1]   ✓ PASS                        │   │
│  │  [12:03:45] developer[2]  → in_progress                 │   │
│  │  █                        (cursor blinks)               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  #cta                                                           │
│                                                                 │
│  Stop writing boilerplate. Start shipping.                     │
│                                                                 │
│  [View on GitHub ↗]    $ pip install agentharness  [⎘]         │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  <footer>  AgentHarness · GitHub · MIT License                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Mobile Layout (375px)

```
┌──────────────────────┐
│ AgentHarness    [≡]  │
├──────────────────────┤
│  #hero               │
│                      │
│  Delegate the grind. │
│  Reclaim your time.  │
│                      │
│  A chain of Claude   │
│  agents builds your  │
│  features while you  │
│  focus on what       │
│  matters.            │
│                      │
│  [Get started ↗]     │
│  $ pip install… [⎘]  │
│                      │
│  [SVG pipeline glyph │
│   simplified,        │
│   smaller scale]     │
├──────────────────────┤
│  #how-it-works       │
│                      │
│  [1. Brainstorm]     │
│  icon + title        │
│  desc                │
│       ↓              │
│  [2. Agents work]    │
│       ↓              │
│  [3. Code ships]     │
├──────────────────────┤
│  #features  (1-col)  │
│  ┌──────────────┐    │
│  │ Multi-agent  │    │
│  └──────────────┘    │
│  ┌──────────────┐    │
│  │ Review loop  │    │
│  └──────────────┘    │
│  …                   │
├──────────────────────┤
│  #pipeline           │
│  [terminal block     │
│   horizontally       │
│   scrollable]        │
├──────────────────────┤
│  #cta                │
│  Stop writing…       │
│  [View on GitHub ↗]  │
│  $ pip install… [⎘]  │
├──────────────────────┤
│ AgentHarness · GitHub│
└──────────────────────┘
```

---

### Hero SVG: Agent Pipeline Glyph

Six nodes (analyst → architect → designer → planner → developer → reviewer) connected by edges. Nodes pulse left-to-right in a 6-step loop, each brightening to `--color-accent` then dimming. Edges draw via `stroke-dashoffset` animation on a `<path>` delayed to follow the trailing node.

```
  ●━━━●━━━●━━━●━━━●━━━●
  A   Ar  D   P   Dev R
  (each ● is a <circle>, edges are <line> or <path>)
```

Static frame (reduced-motion): all nodes at 40% opacity, edges fully drawn, no animation property.

On mobile: collapse to a single horizontal strip, node labels hidden, scale 0.6.

---

### Scroll-Triggered Reveal Pattern

All `[data-reveal]` elements start at:
```css
opacity: 0;
transform: translateY(20px);
transition: opacity 0.5s ease, transform 0.5s ease;
```

On `.is-revealed`:
```css
opacity: 1;
transform: translateY(0);
```

Step cards in `#how-it-works` stagger by `--reveal-delay` (100ms, 200ms, 300ms). Connecting arrows animate after their preceding step card via an additional `--reveal-delay`.

---

### Copy-to-Clipboard Interaction

```
<button data-copy="pip install agentharness && agentharness brainstorm">
  <code>$ pip install agentharness && agentharness brainstorm</code>
  <span class="copy-icon">⎘</span>
</button>

States:
  default  → shows code text + ⎘ icon
  .is-copied → icon swaps to ✓, button background shifts to #00d4ff at 20% opacity
               "Copied!" text appears via ::after for 2000ms then reverts
```

---

### Feature Card Hover

```css
.feature-card {
  background: var(--color-bg-mid);
  border: 1px solid var(--color-border);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 212, 255, 0.12);
  border-color: rgba(0, 212, 255, 0.3);
}
```

---

### Pipeline Terminal Animation

Lines stream in one-by-one using a CSS keyframe that steps through `max-height: 0 → auto` per line, timed with `animation-delay` increments (0.4s per line). The blinking cursor (`█`) is a `::after` pseudo-element with `animation: blink 1s step-end infinite`.

Animation restarts when `#pipeline` re-enters viewport (IntersectionObserver resets classes and re-applies).

---

### Responsive Breakpoints

| Breakpoint | Width   | Key changes |
|---|---|---|
| mobile     | 375px+  | 1-col layout, hero stack vertical, SVG glyph scaled down |
| tablet     | 768px+  | Steps horizontal, features 2-col, full SVG visible |
| desktop    | 1024px+ | Hero split (text left, SVG right), features 3-col |
| wide       | 1440px+ | Max-width container 1280px centered, generous padding |

---

### Navigation

Minimal sticky header: wordmark left, single "View on GitHub ↗" button right. Transparent background with `backdrop-filter: blur(12px)` when scrolled past hero. No hamburger menu on mobile — single CTA button collapses to icon (GitHub mark SVG).

---

## Component Design

### HTML Sections

| Section ID | Element | Responsibility |
|---|---|---|
| `header` | `<header>` | Sticky nav: wordmark + GitHub CTA |
| `#hero` | `<section>` | Value prop, SVG animation, primary CTA, copy command |
| `#how-it-works` | `<section>` | 3-step flow with staggered reveal |
| `#features` | `<section>` | 6 feature cards in responsive grid |
| `#pipeline` | `<section>` | Terminal animation, dark surface |
| `#cta` | `<section>` | Final conversion prompt |
| `footer` | `<footer>` | Links, license, wordmark |

---

### JS Modules

#### `motion.js`

```
Responsibility: gate all animation on prefers-reduced-motion
Exports:
  prefersReducedMotion() → boolean
  onMotionPreferenceChange(cb) → void   // MediaQueryList listener
Side effects:
  Sets class "no-motion" on <html> if reduced motion preferred
```

#### `animations.js`

```
Responsibility: IntersectionObserver reveals + hero SVG lifecycle
Imports: motion.js
Exports:
  initReveals(options?) → void
    options: { rootMargin = '0px 0px -10% 0px', threshold = 0.15 }
    Behavior:
      - Select all [data-reveal]
      - Attach one IntersectionObserver
      - On entry: add .is-revealed, apply data-reveal-delay as style
      - Disconnect per-element after first trigger (one-shot)
      - If prefersReducedMotion(): add .is-revealed immediately, skip observer

  initHeroAnimation() → void
    Behavior:
      - Start hero SVG via CSS custom property
        --hero-play-state: 'running'
      - document.addEventListener('visibilitychange'):
          hidden → set --hero-play-state: 'paused'
          visible → set --hero-play-state: 'running'
      - If prefersReducedMotion(): skip entirely

  initPipelineAnimation() → void
    Behavior:
      - Attach IntersectionObserver to #pipeline
      - On entry: reset animation classes on terminal lines, re-apply
      - Does not disconnect (restarts on each entry)
      - If prefersReducedMotion(): show all lines immediately, no blink
```

#### `copy.js`

```
Responsibility: click-to-copy on [data-copy] elements
Exports:
  initCopyButtons() → void
    Behavior:
      - Select all [data-copy]
      - On click:
          1. Read element.dataset.copy
          2. copyToClipboard(text):
               try navigator.clipboard.writeText(text)
               catch: execCommand fallback
          3. Add .is-copied to element
          4. setTimeout 2000ms → remove .is-copied
      - feedback text from data-copy-feedback or default "Copied!"

  copyToClipboard(text: string) → Promise<void>  // internal, not exported
```

#### `main.js`

```
Responsibility: entry point, orchestration only
Imports: animations.js, copy.js, motion.js
Behavior (DOMContentLoaded):
  1. initMotionGate()      // from motion.js (sets .no-motion if needed)
  2. initReveals()
  3. initHeroAnimation()
  4. initPipelineAnimation()
  5. initCopyButtons()

Constants (top of file):
  REPO_URL = 'https://github.com/onpaj/AgentHarness'
  QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm'
  // Project these into [data-copy] and [data-repo-url] on <body> at init
  // so a single edit propagates everywhere
```

---

### CSS Files

| File | Scope |
|---|---|
| `reset.css` | Modern box-model reset, remove browser defaults |
| `tokens.css` | Custom properties: colors, spacing scale, typography, radii, shadows |
| `layout.css` | Container, grid utilities, flex helpers, section padding |
| `components.css` | Buttons, cards, code blocks, copy-command widget, toast states |
| `sections.css` | Per-section rules: hero split, how-it-works connector, features grid, pipeline terminal, CTA |

Load order enforced via `<link>` sequence in `<head>` — later files override earlier only within their scope (section-specific rules never bleed into components).

---

### HTML Data-Attribute Contract

| Attribute | Host element | Consumed by |
|---|---|---|
| `data-reveal` | Any reveal target | `animations.js → initReveals` |
| `data-reveal-delay="N"` | Reveal target | `initReveals` — sets CSS `transition-delay: Nms` |
| `data-copy="<text>"` | Button wrapping `<code>` | `copy.js → initCopyButtons` |
| `data-copy-feedback="<text>"` | Same button | `copy.js` — overrides "Copied!" label |
| `data-repo-url` | `<body>` | `main.js` — projected to all CTA hrefs at init |

---

### CSS Class Contract

| Class | Applied by | Meaning |
|---|---|---|
| `.is-revealed` | `animations.js` | Element has entered viewport; CSS transition runs |
| `.is-copied` | `copy.js` | Copy succeeded; shows ✓ feedback for 2000ms |
| `.no-motion` | `motion.js` | On `<html>`; CSS uses `:root.no-motion *` to zero transitions |
| `.pipeline-line--visible` | `animations.js` | On each terminal line when it streams in |

---

### `<noscript>` Block

Placed immediately after `<body>` open tag:

```html
<noscript>
  <div class="noscript-notice">
    JavaScript is disabled — animations are off, but all content and links work normally.
  </div>
</noscript>
```

All content, links, and CTAs are fully readable without JS. `.is-revealed` is not required for readable state — elements render at `opacity: 1` without JS (JS adds the hidden initial state via a `.js-loaded` class on `<html>` set by `main.js` before init).

---

### Icon Set

Lucide Icons (MIT, SVG). Mapping:

| Feature | Icon name |
|---|---|
| Multi-agent pipeline | `workflow` |
| Per-task review loop | `repeat` |
| Pluggable backends | `layers` |
| Zero babysitting | `bot` |
| Per-agent context files | `file-text` |
| Serial task dispatch | `list-ordered` |
| Step 1: Brainstorm | `message-square` |
| Step 2: Agents work | `cpu` |
| Step 3: Code ships | `git-pull-request` |

Icons inlined as SVG directly in `index.html`, colored via `currentColor` so they inherit from parent text color.

---

## Data Schemas

### Client-Side State (no persistence)

```
AnimationState {
  revealedElements: Set<Element>   // elements that have fired; prevents re-trigger
  heroPlayState:    'running' | 'paused'   // driven by visibilitychange
  pipelineRunning:  boolean        // true while terminal animation is active
}

CopyState {
  activeButton:   Element | null   // button currently in .is-copied state
  clearTimer:     number | null    // setTimeout handle for reset
}
```

No serialization, no localStorage, no cookies. State is ephemeral — page reload resets everything by design.

---

### CSS Custom Properties Schema (`tokens.css`)

```css
:root {
  /* Color */
  --color-bg-base:     #0a0f1e;
  --color-bg-mid:      #1e3a5f;
  --color-bg-surface:  #162847;   /* slightly lighter card variant */
  --color-accent:      #00d4ff;
  --color-accent-dim:  rgba(0, 212, 255, 0.12);
  --color-text:        #e6edf3;
  --color-text-dim:    #8b9bb4;
  --color-border:      rgba(255, 255, 255, 0.08);
  --color-border-hover: rgba(0, 212, 255, 0.30);

  /* Typography */
  --font-display:  'Inter', system-ui, sans-serif;
  --font-mono:     'JetBrains Mono', ui-monospace, monospace;
  --text-hero:     clamp(2.5rem, 6vw, 5rem);   /* fluid hero headline */
  --text-h2:       clamp(1.75rem, 3vw, 2.5rem);
  --text-body:     1rem;
  --text-sm:       0.875rem;
  --text-xs:       0.75rem;

  /* Spacing scale (4px base) */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --space-16: 4rem;
  --space-24: 6rem;

  /* Layout */
  --container-max: 1280px;
  --section-padding-y: var(--space-24);

  /* Radii */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 16px;

  /* Shadows */
  --shadow-card:  0 4px 16px rgba(0, 0, 0, 0.4);
  --shadow-hover: 0 8px 24px rgba(0, 212, 255, 0.12);

  /* Animation */
  --hero-play-state: running;
  --duration-reveal:   0.5s;
  --duration-hover:    0.2s;
  --easing-reveal:     ease;
}

:root.no-motion * {
  animation: none !important;
  transition: none !important;
}
```

---

### HTML Meta Schema (`<head>`)

```html
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgentHarness — Delegate the grind. Reclaim your time.</title>
<meta name="description"
  content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
<link rel="canonical" href="https://github.com/onpaj/AgentHarness">

<!-- Open Graph -->
<meta property="og:type"        content="website">
<meta property="og:title"       content="AgentHarness — Delegate the grind. Reclaim your time.">
<meta property="og:description" content="…same as meta description…">
<meta property="og:image"       content="assets/img/og-image.png">
<meta property="og:url"         content="https://github.com/onpaj/AgentHarness">

<!-- Twitter Card -->
<meta name="twitter:card"        content="summary_large_image">
<meta name="twitter:title"       content="AgentHarness — Delegate the grind. Reclaim your time.">
<meta name="twitter:description" content="…">
<meta name="twitter:image"       content="assets/img/og-image.png">

<!-- Favicon -->
<link rel="icon" type="image/x-icon"  href="assets/img/favicon.ico">
<link rel="icon" type="image/svg+xml" href="assets/img/favicon.svg">
<link rel="apple-touch-icon"          href="assets/img/apple-touch-icon.png">
```

---

### OG Image Spec

```
Dimensions:   1200 × 630 px
Format:       PNG
Content:      Dark (#0a0f1e) background
              AgentHarness wordmark (top-left, white)
              Hero headline text (white, ~60px)
              Pipeline SVG glyph (right half, accent cyan nodes)
              No photography, no raster assets
File:         assets/img/og-image.png
```

---

### Terminal Animation Line Schema

Each terminal line is a `<div class="pipeline-line" data-line-delay="N">` where `N` is milliseconds. CSS uses `animation-delay: calc(var(--line-index) * 400ms)`.

Canonical line format (monospace, rendered in HTML):

```
[HH:MM:SS]  {agent-name:<14}  {status-glyph} {status-text:<16}  {detail}
```

Hardcoded lines (static content, no backend):
```
[12:01:04]  analyst         → analyzing        feat-abc123
[12:01:22]  analyst         ✓ complete         18s
[12:01:23]  architect       → analyzing
[12:01:55]  architect       ✓ complete         32s
[12:01:56]  planner         → planning
[12:02:14]  planner         ✓ complete         18s  3 tasks
[12:02:15]  developer[1]    → in_progress
[12:03:44]  reviewer[1]     ✓ PASS
[12:03:45]  developer[2]    → in_progress
```
Cursor line appended: `█` with blink animation.