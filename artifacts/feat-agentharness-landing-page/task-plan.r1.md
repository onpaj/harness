### task: scaffold-landingpage-folder

**Goal:** Create the `/landingpage` folder structure with all required subdirectories and a README documenting how to view the site locally.

**Context:**
The landing page is a self-contained static site with no build step. It must work via `file://` direct open, any static file server, or GitHub Pages from `/landingpage` subdirectory. All asset paths must be relative (no leading `/`).

The required structure (from spec):
```
landingpage/
├── index.html
├── assets/
│   ├── css/
│   ├── js/
│   ├── img/
│   │   └── icons/
│   └── fonts/
└── README.md
```

**Files to create/modify:**
- `landingpage/README.md` — how to view the site
- `landingpage/assets/css/.gitkeep` — placeholder
- `landingpage/assets/js/.gitkeep` — placeholder
- `landingpage/assets/img/.gitkeep` — placeholder
- `landingpage/assets/img/icons/.gitkeep` — placeholder
- `landingpage/assets/fonts/.gitkeep` — placeholder

**Implementation steps:**
1. Create the `landingpage/` directory at the repository root.
2. Create the subdirectories `landingpage/assets/css/`, `landingpage/assets/js/`, `landingpage/assets/img/`, `landingpage/assets/img/icons/`, `landingpage/assets/fonts/`.
3. Add a `.gitkeep` empty file in each of the directories so they are tracked by git.
4. Create `landingpage/README.md` with the following content:

```markdown
# AgentHarness Landing Page

Static, single-page marketing site. No build step required.

## View locally

**Option A — direct open:**
Double-click `index.html` or open via `file://` in any modern browser.
Note: Click-to-copy uses a fallback path under `file://`.

**Option B — local static server (recommended):**
```bash
cd landingpage
python3 -m http.server 8000
# then visit http://localhost:8000
```
or
```bash
npx serve landingpage
```

## Deploy

Works on GitHub Pages, Netlify, Vercel, or any static host. All asset paths are
relative — drop the `landingpage/` folder anywhere.

## Structure

```
landingpage/
├── index.html              Single-page entry
├── assets/
│   ├── css/                reset → tokens → layout → components → sections
│   ├── js/                 ES modules: main, animations, copy, motion
│   ├── img/                Favicon, OG image, icons
│   └── fonts/              Optional self-hosted fonts
└── README.md
```

## Browser support

Latest 2 versions of Chrome, Firefox, Safari. Page falls back gracefully without JS.
```

**Tests to write:**
No automated tests for scaffolding. Manual verification:
- Run `ls -la landingpage/assets/` — confirms all five subdirectories exist.
- Run `cat landingpage/README.md` — confirms README exists with the expected sections.

**Acceptance criteria:**
- The `landingpage/` directory exists at the repo root.
- All six subdirectories (`assets/css`, `assets/js`, `assets/img`, `assets/img/icons`, `assets/fonts`) exist and are git-tracked via `.gitkeep`.
- `landingpage/README.md` exists and contains a "View locally" section, a "Deploy" section, and a "Structure" section.

---

### task: css-reset

**Goal:** Create a modern CSS reset that normalizes browser defaults without imposing opinions on layout or color.

**Context:**
Per architecture decision, CSS files cascade in fixed order: `reset.css` → `tokens.css` → `layout.css` → `components.css` → `sections.css`. The reset must be the first CSS file loaded. It must not reference any custom properties (those are defined in `tokens.css`, which loads next).

The reset should:
- Use `box-sizing: border-box` everywhere
- Remove default margins
- Set `body` line-height baseline
- Make images responsive by default
- Inherit fonts on form elements
- Respect `prefers-reduced-motion` as a safety net
- Not set any colors or font families (those come from tokens)

**Files to create/modify:**
- `landingpage/assets/css/reset.css` — modern CSS reset

**Implementation steps:**
1. Create `landingpage/assets/css/reset.css` with the following content:

```css
/* Modern CSS reset — based on Andy Bell's reset, adapted */

*, *::before, *::after {
  box-sizing: border-box;
}

* {
  margin: 0;
  padding: 0;
}

html {
  -webkit-text-size-adjust: 100%;
  scroll-behavior: smooth;
}

body {
  min-height: 100vh;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

img, picture, video, canvas, svg {
  display: block;
  max-width: 100%;
}

input, button, textarea, select {
  font: inherit;
  color: inherit;
}

button {
  background: none;
  border: none;
  cursor: pointer;
}

a {
  color: inherit;
  text-decoration: none;
}

p, h1, h2, h3, h4, h5, h6 {
  overflow-wrap: break-word;
}

ul, ol {
  list-style: none;
}

#root, #__next {
  isolation: isolate;
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

**Tests to write:**
Manual visual test only:
- Open a browser and confirm default `<h1>` has no margin, `<button>` has no background, `<a>` has no underline.
- Open DevTools and verify `box-sizing: border-box` is applied to all elements.

**Acceptance criteria:**
- File `landingpage/assets/css/reset.css` exists.
- No custom property references (no `var(--...)`).
- Includes a `prefers-reduced-motion` media query that zeroes animations and transitions.
- File is under 80 lines.

---

### task: css-tokens

**Goal:** Define all design tokens as CSS custom properties on `:root` so the entire site reads palette, typography, spacing, and animation values from one source.

**Context:**
Tokens are the single source of truth for the visual design. The palette is dark-only (Vercel/Linear aesthetic). Typography uses fluid sizing via `clamp()`. Spacing uses a 4px base scale. The `--hero-play-state` custom property is dynamically toggled by JS on `visibilitychange` to pause the hero SVG animation when the tab is backgrounded.

The `:root.no-motion *` rule is a safety net: when `motion.js` adds the `no-motion` class to `<html>`, all animations and transitions are zeroed regardless of any other rule.

**Files to create/modify:**
- `landingpage/assets/css/tokens.css` — design tokens

**Implementation steps:**
1. Create `landingpage/assets/css/tokens.css` with the following exact content:

```css
:root {
  /* Color */
  --color-bg-base:      #0a0f1e;
  --color-bg-mid:       #1e3a5f;
  --color-bg-surface:   #162847;
  --color-accent:       #00d4ff;
  --color-accent-dim:   rgba(0, 212, 255, 0.12);
  --color-text:         #e6edf3;
  --color-text-dim:     #8b9bb4;
  --color-border:       rgba(255, 255, 255, 0.08);
  --color-border-hover: rgba(0, 212, 255, 0.30);

  /* Typography */
  --font-display: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono:    'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --text-hero:    clamp(2.5rem, 6vw, 5rem);
  --text-h2:      clamp(1.75rem, 3vw, 2.5rem);
  --text-h3:      clamp(1.25rem, 2vw, 1.5rem);
  --text-body:    1rem;
  --text-sm:      0.875rem;
  --text-xs:      0.75rem;
  --leading-tight: 1.15;
  --leading-body:  1.6;

  /* Spacing scale (4px base) */
  --space-1:  0.25rem;
  --space-2:  0.5rem;
  --space-3:  0.75rem;
  --space-4:  1rem;
  --space-6:  1.5rem;
  --space-8:  2rem;
  --space-12: 3rem;
  --space-16: 4rem;
  --space-20: 5rem;
  --space-24: 6rem;

  /* Layout */
  --container-max:     1280px;
  --container-padding: var(--space-6);
  --section-padding-y: var(--space-24);

  /* Radii */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 16px;
  --radius-pill: 999px;

  /* Shadows */
  --shadow-card:  0 4px 16px rgba(0, 0, 0, 0.4);
  --shadow-hover: 0 8px 24px rgba(0, 212, 255, 0.12);

  /* Animation */
  --hero-play-state: running;
  --duration-reveal: 0.5s;
  --duration-hover:  0.2s;
  --easing-reveal:   cubic-bezier(0.22, 0.61, 0.36, 1);
  --easing-hover:    ease;

  /* Body baseline */
  background: var(--color-bg-base);
  color: var(--color-text);
  font-family: var(--font-display);
  font-size: var(--text-body);
  line-height: var(--leading-body);
}

:root.no-motion * {
  animation: none !important;
  transition: none !important;
}

::selection {
  background: var(--color-accent);
  color: var(--color-bg-base);
}
```

**Tests to write:**
Manual:
- Open the page in a browser, inspect `<html>`, and confirm `getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim()` returns `#00d4ff`.
- Toggle `prefers-reduced-motion` in DevTools rendering panel; confirm the body still renders normally.

**Acceptance criteria:**
- File `landingpage/assets/css/tokens.css` exists.
- Defines exactly the palette values: `#0a0f1e`, `#1e3a5f`, `#162847`, `#00d4ff`, `#e6edf3`, `#8b9bb4`.
- Defines `--text-hero: clamp(2.5rem, 6vw, 5rem)` (fluid scaling).
- Defines `--hero-play-state: running` (toggled by JS later).
- Includes `:root.no-motion *` safety-net rule.
- Sets `background`, `color`, `font-family`, `font-size`, `line-height` on `:root` so the body inherits.

---

### task: css-layout

**Goal:** Create layout primitives — container, section padding, and grid utilities — that all sections compose from.

**Context:**
The site uses a max-width centered container (`1280px`) with responsive padding. Section vertical padding uses the `--section-padding-y` token. Grid utilities support the 3-column features grid (collapsing to 2 on tablet, 1 on mobile) and the 3-step horizontal flow (collapsing to vertical stack on mobile).

Breakpoints (mobile-first):
- mobile (default): up to 767px — 1 column
- tablet: 768px+ — 2 columns
- desktop: 1024px+ — 3 columns

This file depends on tokens being loaded (uses `var(--space-6)`, `var(--container-max)`, etc.).

**Files to create/modify:**
- `landingpage/assets/css/layout.css` — container, grid, flex utilities

**Implementation steps:**
1. Create `landingpage/assets/css/layout.css` with the following content:

```css
.container {
  width: 100%;
  max-width: var(--container-max);
  margin-inline: auto;
  padding-inline: var(--container-padding);
}

.section {
  padding-block: var(--section-padding-y);
  position: relative;
}

@media (max-width: 767px) {
  .section {
    padding-block: var(--space-16);
  }
}

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.stack-sm  { gap: var(--space-3); }
.stack-lg  { gap: var(--space-8); }
.stack-xl  { gap: var(--space-12); }

.row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.grid {
  display: grid;
  gap: var(--space-6);
  grid-template-columns: 1fr;
}

@media (min-width: 768px) {
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
}

@media (min-width: 1024px) {
  .grid-3 { grid-template-columns: repeat(3, 1fr); }
}

.split {
  display: grid;
  gap: var(--space-12);
  grid-template-columns: 1fr;
  align-items: center;
}

@media (min-width: 1024px) {
  .split {
    grid-template-columns: 1fr 1fr;
    gap: var(--space-16);
  }
}

.center-text { text-align: center; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

**Tests to write:**
Manual:
- Create a temporary HTML file with `<div class="container"><div class="grid grid-3">three children</div></div>`, open at desktop width, confirm 3 columns; resize to tablet, confirm 2 columns; resize to mobile, confirm 1 column.

**Acceptance criteria:**
- File `landingpage/assets/css/layout.css` exists.
- `.container` is centered with `max-width: var(--container-max)`.
- `.grid` defaults to 1 column; `.grid-2` activates 2 columns at 768px+; `.grid-3` activates 3 columns at 1024px+.
- `.split` is single column on mobile, two equal columns at 1024px+.
- `.section` uses `var(--section-padding-y)` on desktop, falls back to `var(--space-16)` on mobile.

---

### task: css-components

**Goal:** Style reusable UI components: buttons (primary/secondary), feature cards, copy-command widget, terminal block, toast/copied state, and noscript notice.

**Context:**
Components are visual primitives consumed by sections. Class names follow this contract:

- `.btn` — base button
- `.btn-primary` — accent CTA (filled cyan)
- `.btn-secondary` — outlined CTA
- `.btn-ghost` — minimal text-only button
- `.feature-card` — grid card with hover lift
- `.copy-command` — `<button>` wrapping `<code>` with copy icon
- `.terminal` — dark terminal block with monospace lines
- `.pipeline-line` — individual terminal line (animated by JS)
- `.noscript-notice` — banner shown when JS is disabled
- `.icon` — SVG icon size baseline (24×24)
- `.icon-lg` — larger icon (40×40 for feature/step illustrations)

JS applies these state classes:
- `.is-revealed` — after IntersectionObserver fires (handled in sections.css)
- `.is-copied` — after successful copy (handled here, transitions the copy icon to ✓)
- `.pipeline-line--visible` — when terminal line streams in (handled in sections.css)

Hover spec from design:
```css
.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 212, 255, 0.12);
  border-color: rgba(0, 212, 255, 0.3);
}
```

The `.copy-command` button shows two children — a `<code>` with the command, and a `<span class="copy-icon">` containing the ⎘ glyph. On `.is-copied`, swap the icon to ✓ and add a colored background tint.

**Files to create/modify:**
- `landingpage/assets/css/components.css` — buttons, cards, copy widget, terminal, noscript

**Implementation steps:**
1. Create `landingpage/assets/css/components.css` with the following content:

```css
/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-6);
  border-radius: var(--radius-md);
  font-family: var(--font-display);
  font-size: var(--text-body);
  font-weight: 600;
  line-height: 1;
  text-decoration: none;
  border: 1px solid transparent;
  transition: background var(--duration-hover) var(--easing-hover),
              border-color var(--duration-hover) var(--easing-hover),
              transform var(--duration-hover) var(--easing-hover),
              box-shadow var(--duration-hover) var(--easing-hover);
  white-space: nowrap;
  cursor: pointer;
}

.btn:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.btn-primary {
  background: var(--color-accent);
  color: var(--color-bg-base);
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(0, 212, 255, 0.3);
}

.btn-secondary {
  background: transparent;
  color: var(--color-text);
  border-color: var(--color-border);
}

.btn-secondary:hover {
  border-color: var(--color-border-hover);
  background: var(--color-accent-dim);
}

.btn-ghost {
  background: transparent;
  color: var(--color-text-dim);
  padding: var(--space-2) var(--space-3);
}

.btn-ghost:hover { color: var(--color-text); }

/* Feature card */
.feature-card {
  background: var(--color-bg-mid);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  transition: transform var(--duration-hover) var(--easing-hover),
              box-shadow var(--duration-hover) var(--easing-hover),
              border-color var(--duration-hover) var(--easing-hover);
}

.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-hover);
  border-color: var(--color-border-hover);
}

.feature-card .icon-lg { color: var(--color-accent); }

.feature-card h3 {
  font-size: var(--text-h3);
  line-height: var(--leading-tight);
  font-weight: 600;
}

.feature-card p {
  color: var(--color-text-dim);
  font-size: var(--text-sm);
}

/* Copy-command widget */
.copy-command {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text);
  cursor: pointer;
  transition: background var(--duration-hover) var(--easing-hover),
              border-color var(--duration-hover) var(--easing-hover);
  position: relative;
  max-width: 100%;
  text-align: left;
}

.copy-command:hover {
  border-color: var(--color-border-hover);
}

.copy-command code {
  font-family: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.copy-command .copy-icon {
  color: var(--color-text-dim);
  font-size: var(--text-body);
  flex-shrink: 0;
}

.copy-command.is-copied {
  background: var(--color-accent-dim);
  border-color: var(--color-border-hover);
}

.copy-command.is-copied .copy-icon::before { content: "✓"; color: var(--color-accent); }
.copy-command:not(.is-copied) .copy-icon::before { content: "⎘"; }
.copy-command .copy-icon { font-size: 0; }
.copy-command .copy-icon::before { font-size: var(--text-body); }

.copy-command.is-copied::after {
  content: attr(data-copy-feedback);
  position: absolute;
  top: -2.25rem;
  right: 0;
  background: var(--color-accent);
  color: var(--color-bg-base);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-family: var(--font-display);
  font-size: var(--text-xs);
  font-weight: 600;
  pointer-events: none;
}

/* Terminal block */
.terminal {
  background: #06091a;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow-x: auto;
  box-shadow: var(--shadow-card);
}

.terminal-prompt {
  color: var(--color-accent);
  margin-bottom: var(--space-4);
}

/* Icon sizing */
.icon {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.icon-lg {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
}

.icon-sm {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

/* Noscript banner */
.noscript-notice {
  background: var(--color-bg-mid);
  color: var(--color-text);
  padding: var(--space-3) var(--space-6);
  text-align: center;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
}
```

**Tests to write:**
Manual:
- Create test HTML with `<button class="btn btn-primary">Test</button>` — confirm cyan background, dark text, hover lifts the button.
- Create `<button class="copy-command" data-copy="ls" data-copy-feedback="Copied!"><code>$ ls</code><span class="copy-icon"></span></button>` — confirm code is monospace, ⎘ icon visible. Add `.is-copied` class manually in DevTools — confirm icon swaps to ✓ and "Copied!" toast appears top-right.
- Create `<div class="feature-card"><h3>Test</h3><p>desc</p></div>` — confirm card has dark background, border; on hover it lifts.

**Acceptance criteria:**
- File `landingpage/assets/css/components.css` exists.
- All component classes (`.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.feature-card`, `.copy-command`, `.terminal`, `.icon`, `.icon-lg`, `.noscript-notice`) are defined.
- `.copy-command.is-copied` swaps icon to ✓, applies `--color-accent-dim` background, and shows a "Copied!" toast via `::after` positioned above the button.
- Buttons have visible `:focus-visible` outline using `--color-accent`.
- All sizes/colors reference custom properties only — no hardcoded hex except the terminal background `#06091a`.

---

### task: css-sections

**Goal:** Style each page section: header, hero (with split layout and SVG), how-it-works (3-step flow with connectors), features (grid), pipeline (terminal animation), CTA, footer, plus the `.is-revealed` reveal transition.

**Context:**
Section IDs and structure (from design):

| Section ID | Element |
|---|---|
| `header` (`.site-header`) | sticky nav: wordmark + GitHub CTA |
| `#hero` | value prop + animated SVG, full viewport |
| `#how-it-works` | 3-step flow |
| `#features` | 6-card grid |
| `#pipeline` | terminal animation on dark surface |
| `#cta` | final conversion |
| `footer` (`.site-footer`) | links, license |

Reveal pattern (consumed by `[data-reveal]` elements):
```css
[data-reveal] {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity var(--duration-reveal) var(--easing-reveal),
              transform var(--duration-reveal) var(--easing-reveal);
}
[data-reveal].is-revealed {
  opacity: 1;
  transform: translateY(0);
}
```

But: per the design, JS sets `.js-loaded` on `<html>` before reveals run. Without JS, elements must show at full opacity. Therefore the hidden initial state is gated on `:root.js-loaded [data-reveal]`.

Hero is full viewport on desktop (`min-height: 100vh`). On mobile, hero stacks vertically.

How-it-works has 3 step cards on a horizontal row at desktop (768px+); on mobile they stack vertically with a vertical connector arrow between them.

Pipeline section has a dark surface (`var(--color-bg-base)`) and a terminal block with monospace lines. Each `.pipeline-line` starts with `opacity: 0` and animates to `opacity: 1` with a stagger of 400ms per line index.

The hero SVG nodes have a 6-step pulse animation, sequenced via `animation-delay`. The CSS `animation-play-state` reads `var(--hero-play-state)` so JS can pause it via custom property.

**Files to create/modify:**
- `landingpage/assets/css/sections.css` — per-section styles + reveal transitions

**Implementation steps:**
1. Create `landingpage/assets/css/sections.css` with the following content:

```css
/* ===== Reveal transitions ===== */
:root.js-loaded [data-reveal] {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity var(--duration-reveal) var(--easing-reveal),
              transform var(--duration-reveal) var(--easing-reveal);
}

:root.js-loaded [data-reveal].is-revealed {
  opacity: 1;
  transform: translateY(0);
}

/* ===== Site header ===== */
.site-header {
  position: sticky;
  top: 0;
  z-index: 50;
  padding: var(--space-4) 0;
  background: rgba(10, 15, 30, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border);
}

.site-header .container {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.wordmark {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.125rem;
  letter-spacing: -0.01em;
  color: var(--color-text);
}

.wordmark span { color: var(--color-accent); }

/* ===== Hero ===== */
.hero {
  min-height: calc(100vh - 64px);
  display: flex;
  align-items: center;
  padding-block: var(--space-16);
}

.hero-headline {
  font-size: var(--text-hero);
  line-height: var(--leading-tight);
  letter-spacing: -0.02em;
  font-weight: 700;
}

.hero-headline .accent { color: var(--color-accent); }

.hero-sub {
  font-size: clamp(1rem, 1.5vw, 1.25rem);
  color: var(--color-text-dim);
  max-width: 36rem;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
  margin-top: var(--space-4);
}

.hero-visual {
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 320px;
}

.hero-svg {
  width: 100%;
  max-width: 560px;
  height: auto;
}

@media (max-width: 1023px) {
  .hero { min-height: auto; }
  .hero-visual { margin-top: var(--space-12); min-height: 240px; }
  .hero-svg { max-width: 360px; }
}

/* Hero SVG node pulse — 6 nodes, sequenced */
.hero-node {
  fill: var(--color-bg-mid);
  stroke: var(--color-border-hover);
  stroke-width: 1.5;
  animation: node-pulse 6s linear infinite;
  animation-play-state: var(--hero-play-state);
  transform-origin: center;
  transform-box: fill-box;
}

.hero-node:nth-of-type(1) { animation-delay: 0s; }
.hero-node:nth-of-type(2) { animation-delay: 1s; }
.hero-node:nth-of-type(3) { animation-delay: 2s; }
.hero-node:nth-of-type(4) { animation-delay: 3s; }
.hero-node:nth-of-type(5) { animation-delay: 4s; }
.hero-node:nth-of-type(6) { animation-delay: 5s; }

@keyframes node-pulse {
  0%, 100% { fill: var(--color-bg-mid); filter: none; }
  10%      { fill: var(--color-accent); filter: drop-shadow(0 0 8px var(--color-accent)); }
  30%      { fill: var(--color-bg-mid); filter: none; }
}

.hero-edge {
  stroke: var(--color-border-hover);
  stroke-width: 1;
}

.hero-label {
  fill: var(--color-text-dim);
  font-family: var(--font-mono);
  font-size: 10px;
  text-anchor: middle;
}

/* ===== How it works ===== */
.how-it-works {
  background: var(--color-bg-base);
}

.steps {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-8);
  margin-top: var(--space-12);
}

@media (min-width: 768px) {
  .steps {
    grid-template-columns: 1fr auto 1fr auto 1fr;
    align-items: center;
    gap: var(--space-6);
  }
}

.step {
  background: var(--color-bg-mid);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  text-align: center;
  align-items: center;
}

.step-number {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-accent);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.step .icon-lg { color: var(--color-accent); }

.step h3 {
  font-size: var(--text-h3);
  line-height: var(--leading-tight);
}

.step p {
  color: var(--color-text-dim);
  font-size: var(--text-sm);
}

.step-connector {
  display: none;
  color: var(--color-text-dim);
  font-size: 1.5rem;
}

@media (min-width: 768px) {
  .step-connector { display: block; }
}

/* ===== Features ===== */
.features {
  background: var(--color-bg-base);
}

.features-header {
  text-align: center;
  max-width: 36rem;
  margin: 0 auto var(--space-12);
}

.features-header h2 {
  font-size: var(--text-h2);
  line-height: var(--leading-tight);
}

.features-header p {
  color: var(--color-text-dim);
  margin-top: var(--space-3);
}

/* ===== Pipeline ===== */
.pipeline {
  background: var(--color-bg-base);
}

.pipeline-header {
  text-align: center;
  max-width: 36rem;
  margin: 0 auto var(--space-12);
}

.pipeline-header h2 {
  font-size: var(--text-h2);
  line-height: var(--leading-tight);
}

.pipeline-header p {
  color: var(--color-text-dim);
  margin-top: var(--space-3);
}

.pipeline-line {
  white-space: pre;
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.pipeline-line--visible {
  opacity: 1;
  transform: translateY(0);
}

.pipeline-line .ts      { color: var(--color-text-dim); }
.pipeline-line .agent   { color: var(--color-accent); }
.pipeline-line .ok      { color: #5cffa6; }
.pipeline-line .arrow   { color: var(--color-text-dim); }
.pipeline-cursor::after {
  content: "█";
  color: var(--color-accent);
  animation: blink 1s step-end infinite;
  margin-left: 0.25rem;
}

@keyframes blink {
  0%, 50%   { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* ===== CTA ===== */
.cta {
  background: var(--color-bg-base);
  text-align: center;
}

.cta h2 {
  font-size: var(--text-h2);
  line-height: var(--leading-tight);
  max-width: 32rem;
  margin: 0 auto;
}

.cta-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-4);
  margin-top: var(--space-8);
}

/* ===== Footer ===== */
.site-footer {
  border-top: 1px solid var(--color-border);
  padding-block: var(--space-8);
  color: var(--color-text-dim);
  font-size: var(--text-sm);
}

.site-footer .container {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.site-footer a {
  color: var(--color-text-dim);
  transition: color var(--duration-hover) var(--easing-hover);
}
.site-footer a:hover { color: var(--color-text); }
```

**Tests to write:**
Manual:
- Confirm `:root.js-loaded [data-reveal]` rule does not hide content when `<html>` lacks `.js-loaded` class (no-JS path).
- Add `.is-revealed` to a `[data-reveal]` element manually in DevTools → confirm it transitions to `opacity: 1`.
- Inspect `.hero-node` and confirm `animation-play-state: var(--hero-play-state)`. Set `--hero-play-state: paused` on `:root` in DevTools → animation pauses.

**Acceptance criteria:**
- File `landingpage/assets/css/sections.css` exists.
- Reveal initial state is gated on `:root.js-loaded` so non-JS users see content immediately.
- `.hero` is `min-height: calc(100vh - 64px)` on desktop; auto on mobile (`max-width: 1023px`).
- `.steps` is single column on mobile; horizontal grid with auto-width connectors at 768px+.
- `.pipeline-line` transitions opacity from 0 → 1; `.pipeline-line--visible` is the active state.
- `.hero-node` uses `animation-play-state: var(--hero-play-state)` (driven by JS visibilitychange).
- Sticky `.site-header` uses `backdrop-filter: blur(12px)`.

---

### task: js-motion

**Goal:** Implement the motion module that detects `prefers-reduced-motion`, applies a `no-motion` class to `<html>`, and exposes preference change listeners.

**Context:**
JS module contracts (from arch review):

```js
// motion.js
export const prefersReducedMotion: () => boolean
export const onMotionPreferenceChange: (cb: (reduced: boolean) => void) => void
export const initMotionGate: () => void   // sets/removes .no-motion on <html>
```

`initMotionGate` runs once on page load. It adds `.no-motion` to `<html>` if the user prefers reduced motion, and listens for changes via `MediaQueryList.addEventListener('change', ...)`.

Other modules call `prefersReducedMotion()` to short-circuit animations entirely.

The CSS safety net `:root.no-motion *` (in `tokens.css`) zeros all transitions/animations when this class is present — so even if a JS module forgets to check the preference, animations still don't run.

**Files to create/modify:**
- `landingpage/assets/js/motion.js` — motion preference module

**Implementation steps:**
1. Create `landingpage/assets/js/motion.js` with the following content:

```js
const MEDIA_QUERY = '(prefers-reduced-motion: reduce)';
const NO_MOTION_CLASS = 'no-motion';

const mq = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia(MEDIA_QUERY)
  : null;

export function prefersReducedMotion() {
  return mq ? mq.matches : false;
}

export function onMotionPreferenceChange(callback) {
  if (!mq) return;
  const handler = (event) => callback(event.matches);
  if (typeof mq.addEventListener === 'function') {
    mq.addEventListener('change', handler);
  } else if (typeof mq.addListener === 'function') {
    mq.addListener(handler);
  }
}

function applyMotionClass(reduced) {
  const root = document.documentElement;
  if (reduced) {
    root.classList.add(NO_MOTION_CLASS);
  } else {
    root.classList.remove(NO_MOTION_CLASS);
  }
}

export function initMotionGate() {
  applyMotionClass(prefersReducedMotion());
  onMotionPreferenceChange(applyMotionClass);
}
```

**Tests to write:**
Manual:
- Open the page in a browser. In DevTools → Rendering → Emulate CSS media feature `prefers-reduced-motion: reduce`. Confirm `<html>` gains the `no-motion` class.
- Toggle back to `no-preference`. Confirm `no-motion` class is removed.
- In console, run `import('./motion.js').then(m => console.log(m.prefersReducedMotion()))`. Confirm it returns `true`/`false` matching the emulated state.

**Acceptance criteria:**
- File `landingpage/assets/js/motion.js` exists.
- Exports `prefersReducedMotion`, `onMotionPreferenceChange`, `initMotionGate`.
- `initMotionGate()` adds `no-motion` class to `<html>` when preference is reduce; removes it otherwise.
- Listens for runtime preference changes via `MediaQueryList.addEventListener('change')` with fallback to `addListener` for older browsers.
- No console errors when imported.

---

### task: js-copy

**Goal:** Implement the click-to-copy module that wires all `[data-copy]` elements with Clipboard API + `execCommand` fallback and toggles the `.is-copied` state for 2000ms.

**Context:**
Contract:

```js
// copy.js
export const initCopyButtons: () => void
//   Wires all [data-copy] elements. On click, copies data-copy attribute value
//   and shows .is-copied state on the trigger for 2000ms.
```

The Clipboard API (`navigator.clipboard.writeText`) requires HTTPS or localhost. When the page is opened via `file://`, it fails — so we need a `document.execCommand('copy')` fallback using a temporary textarea.

State management:
- Only one button can be in `.is-copied` at a time (global `activeButton` + `clearTimer`).
- New click while another button is "copied" cancels the previous timer and clears that button's state immediately.
- The optional `data-copy-feedback` attribute overrides the toast text (CSS reads it via `attr(data-copy-feedback)`).
- If neither attribute exists, default to "Copied!".

The CSS `.copy-command::after { content: attr(data-copy-feedback); }` requires `data-copy-feedback` to exist on the button. So if not specified, the init code should set it to "Copied!" so the toast renders.

**Files to create/modify:**
- `landingpage/assets/js/copy.js` — click-to-copy module

**Implementation steps:**
1. Create `landingpage/assets/js/copy.js` with the following content:

```js
const COPIED_CLASS = 'is-copied';
const COPIED_DURATION_MS = 2000;
const DEFAULT_FEEDBACK = 'Copied!';

let activeButton = null;
let clearTimer = null;

async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to legacy fallback
    }
  }
  return copyViaExecCommand(text);
}

function copyViaExecCommand(text) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'absolute';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  document.body.appendChild(textarea);
  textarea.select();
  textarea.setSelectionRange(0, text.length);
  let success = false;
  try {
    success = document.execCommand('copy');
  } catch {
    success = false;
  }
  document.body.removeChild(textarea);
  return success;
}

function clearCopiedState() {
  if (activeButton) {
    activeButton.classList.remove(COPIED_CLASS);
    activeButton = null;
  }
  if (clearTimer) {
    clearTimeout(clearTimer);
    clearTimer = null;
  }
}

function showCopiedState(button) {
  clearCopiedState();
  button.classList.add(COPIED_CLASS);
  activeButton = button;
  clearTimer = window.setTimeout(() => {
    button.classList.remove(COPIED_CLASS);
    if (activeButton === button) activeButton = null;
    clearTimer = null;
  }, COPIED_DURATION_MS);
}

async function handleCopyClick(event) {
  const button = event.currentTarget;
  const text = button.dataset.copy;
  if (!text) return;
  const ok = await copyToClipboard(text);
  if (ok) showCopiedState(button);
}

export function initCopyButtons() {
  const buttons = document.querySelectorAll('[data-copy]');
  buttons.forEach((button) => {
    if (!button.dataset.copyFeedback) {
      button.dataset.copyFeedback = DEFAULT_FEEDBACK;
    }
    button.addEventListener('click', handleCopyClick);
  });
}
```

**Tests to write:**
Manual:
- Add `<button data-copy="hello world"><code>$ echo hello</code><span class="copy-icon"></span></button>` to the page, run `initCopyButtons()`, click the button. Confirm clipboard contains "hello world" (paste into another field) and button gains `.is-copied` for 2 seconds.
- Open the page via `file://` and click a copy button — confirm it still works via `execCommand` fallback.
- Click two different copy buttons quickly — confirm only the most recently clicked has `.is-copied`.

**Acceptance criteria:**
- File `landingpage/assets/js/copy.js` exists.
- Exports `initCopyButtons`.
- Uses `navigator.clipboard.writeText` only when `window.isSecureContext` is true; otherwise falls back to `document.execCommand('copy')` via a hidden textarea.
- Adds `.is-copied` class for exactly 2000ms.
- Cancels prior copied state when a new button is clicked.
- Defaults `data-copy-feedback` to "Copied!" if not set.
- No `console.error` on click in either path.

---

### task: js-animations

**Goal:** Implement scroll-triggered reveals (`initReveals`), hero SVG lifecycle (`initHeroAnimation`), and pipeline terminal animation (`initPipelineAnimation`).

**Context:**
Contract:

```js
export function initReveals(options?: { rootMargin?: string, threshold?: number }): void
//   Selects [data-reveal], attaches IntersectionObserver, adds .is-revealed
//   once per element. Reads data-reveal-delay (ms) and applies it as
//   transition-delay inline. Disconnects per-element after first trigger.
//   If prefersReducedMotion(): adds .is-revealed to all immediately, no observer.

export function initHeroAnimation(): void
//   Hero SVG animation is CSS-driven. JS only manages document.visibilitychange
//   to toggle the --hero-play-state custom property between 'running'/'paused'.
//   If prefersReducedMotion(): never starts.

export function initPipelineAnimation(): void
//   Attaches IntersectionObserver to #pipeline. On entry: removes .pipeline-line--visible
//   from each .pipeline-line, then re-adds with a 400ms stagger. Restarts on each entry.
//   If prefersReducedMotion(): adds .pipeline-line--visible to all immediately, no observer.
```

Reveal observer defaults (per arch review amendment):
- `rootMargin: '0px 0px -10% 0px'`
- `threshold: 0.15`

For pipeline restart-on-each-entry: the observer should NOT disconnect, and re-trigger every time the section re-enters viewport (per design spec FR-4: "Animation loops or restarts when scrolled into view").

Stagger logic for pipeline lines:
```js
lines.forEach((line, i) => {
  setTimeout(() => line.classList.add('pipeline-line--visible'), i * 400);
});
```

Reveal delay logic: read `data-reveal-delay` (ms), set element's `style.transitionDelay = '${delay}ms'` before adding `.is-revealed`.

**Files to create/modify:**
- `landingpage/assets/js/animations.js` — reveals + hero + pipeline animations

**Implementation steps:**
1. Create `landingpage/assets/js/animations.js` with the following content:

```js
import { prefersReducedMotion } from './motion.js';

const REVEALED_CLASS = 'is-revealed';
const PIPELINE_LINE_CLASS = 'pipeline-line';
const PIPELINE_VISIBLE_CLASS = 'pipeline-line--visible';
const PIPELINE_STAGGER_MS = 400;
const HERO_PLAY_PROPERTY = '--hero-play-state';

const DEFAULT_REVEAL_OPTIONS = {
  rootMargin: '0px 0px -10% 0px',
  threshold: 0.15,
};

export function initReveals(options = {}) {
  const targets = document.querySelectorAll('[data-reveal]');
  if (targets.length === 0) return;

  if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
    targets.forEach((el) => el.classList.add(REVEALED_CLASS));
    return;
  }

  const config = { ...DEFAULT_REVEAL_OPTIONS, ...options };
  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      const delay = el.dataset.revealDelay;
      if (delay) el.style.transitionDelay = `${delay}ms`;
      el.classList.add(REVEALED_CLASS);
      obs.unobserve(el);
    });
  }, config);

  targets.forEach((el) => observer.observe(el));
}

export function initHeroAnimation() {
  if (prefersReducedMotion()) {
    document.documentElement.style.setProperty(HERO_PLAY_PROPERTY, 'paused');
    return;
  }

  const setPlayState = (state) => {
    document.documentElement.style.setProperty(HERO_PLAY_PROPERTY, state);
  };

  setPlayState('running');

  document.addEventListener('visibilitychange', () => {
    setPlayState(document.hidden ? 'paused' : 'running');
  });
}

export function initPipelineAnimation() {
  const section = document.getElementById('pipeline');
  if (!section) return;
  const lines = section.querySelectorAll(`.${PIPELINE_LINE_CLASS}`);
  if (lines.length === 0) return;

  if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
    lines.forEach((line) => line.classList.add(PIPELINE_VISIBLE_CLASS));
    return;
  }

  const timers = new Set();

  const playSequence = () => {
    timers.forEach((t) => clearTimeout(t));
    timers.clear();
    lines.forEach((line) => line.classList.remove(PIPELINE_VISIBLE_CLASS));
    lines.forEach((line, i) => {
      const t = window.setTimeout(() => {
        line.classList.add(PIPELINE_VISIBLE_CLASS);
        timers.delete(t);
      }, i * PIPELINE_STAGGER_MS);
      timers.add(t);
    });
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) playSequence();
    });
  }, { threshold: 0.3 });

  observer.observe(section);
}
```

**Tests to write:**
Manual:
- Add `<div data-reveal>Test</div>` below the fold. Scroll into view. Confirm element transitions from invisible to visible (`.is-revealed` added).
- Add `<div data-reveal data-reveal-delay="200">Delayed</div>` and a sibling without delay. Scroll into view. Confirm delayed one appears 200ms after sibling.
- Set `prefers-reduced-motion: reduce` in DevTools, reload. Confirm all `[data-reveal]` elements show immediately at full opacity (no transition).
- Switch tabs and back. Confirm `<html>` style attribute toggles `--hero-play-state` between `paused` and `running`.
- Scroll past `#pipeline` and back. Confirm `.pipeline-line` elements lose `.pipeline-line--visible` then re-gain it with 400ms stagger.

**Acceptance criteria:**
- File `landingpage/assets/js/animations.js` exists.
- Exports `initReveals`, `initHeroAnimation`, `initPipelineAnimation`.
- `initReveals` uses `IntersectionObserver` with `rootMargin: '0px 0px -10% 0px'` and `threshold: 0.15`; calls `unobserve()` after first reveal per element.
- `initHeroAnimation` toggles `--hero-play-state` via `document.documentElement.style.setProperty` on `visibilitychange`; sets `paused` and exits early under reduced motion.
- `initPipelineAnimation` re-triggers on every re-entry into viewport (does NOT call `unobserve`) with a 400ms stagger between lines.
- Under reduced motion, all reveal targets and pipeline lines render immediately; hero animation is paused.

---

### task: js-main

**Goal:** Create the entry-point JS module that runs on `DOMContentLoaded`, sets the `.js-loaded` class on `<html>` (so reveal initial-state CSS activates only when JS is present), projects shared constants (`REPO_URL`, `QUICKSTART_CMD`) into the DOM, and initializes all submodules in the correct order.

**Context:**
Boot order (from architecture review):
1. Set `.js-loaded` on `<html>` (so `:root.js-loaded [data-reveal] { opacity: 0; ... }` rule activates).
2. `initMotionGate()` — sets `.no-motion` if needed.
3. `initReveals()` — wires reveals.
4. `initHeroAnimation()` — starts hero SVG, attaches visibilitychange.
5. `initPipelineAnimation()` — wires terminal section observer.
6. `initCopyButtons()` — wires `[data-copy]`.

Single source of truth for repo URL and quick-start command (per arch amendment): constants at top of `main.js`, projected into the DOM at init time. The HTML uses `[data-href="repo"]` on links and `[data-copy-target="quickstart"]` on copy buttons; `main.js` rewrites `href` on the former and `data-copy` (plus the inner `<code>` text) on the latter.

```js
const REPO_URL = 'https://github.com/onpaj/AgentHarness';
const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';
```

The page must be functional even with JS disabled. Therefore, HTML authors include real `href` URLs and real text in the copy buttons as fallback. JS overwrites them only when present.

**Files to create/modify:**
- `landingpage/assets/js/main.js` — entry point

**Implementation steps:**
1. Create `landingpage/assets/js/main.js` with the following content:

```js
import { initMotionGate } from './motion.js';
import { initReveals, initHeroAnimation, initPipelineAnimation } from './animations.js';
import { initCopyButtons } from './copy.js';

const REPO_URL = 'https://github.com/onpaj/AgentHarness';
const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';

function projectConstants() {
  document.body.dataset.repoUrl = REPO_URL;

  document.querySelectorAll('[data-href="repo"]').forEach((el) => {
    el.setAttribute('href', REPO_URL);
  });

  document.querySelectorAll('[data-copy-target="quickstart"]').forEach((el) => {
    el.dataset.copy = QUICKSTART_CMD;
    const code = el.querySelector('code');
    if (code) code.textContent = `$ ${QUICKSTART_CMD}`;
  });
}

function init() {
  document.documentElement.classList.add('js-loaded');
  initMotionGate();
  projectConstants();
  initReveals();
  initHeroAnimation();
  initPipelineAnimation();
  initCopyButtons();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init, { once: true });
} else {
  init();
}
```

**Tests to write:**
Manual:
- Open page in browser, inspect `<html>` — confirm `.js-loaded` class is present.
- Inspect `<body>` — confirm `data-repo-url="https://github.com/onpaj/AgentHarness"`.
- Inspect any `<a data-href="repo">` element — confirm `href` is rewritten to the repo URL.
- Inspect any `<button data-copy-target="quickstart">` — confirm `data-copy` is set to `pip install agentharness && agentharness brainstorm` and inner `<code>` shows `$ pip install agentharness && agentharness brainstorm`.
- Disable JS, reload page — confirm fallback `href` and code text are still present and functional (hardcoded in HTML).

**Acceptance criteria:**
- File `landingpage/assets/js/main.js` exists.
- Imports `motion.js`, `animations.js`, `copy.js` as ES modules.
- Init order: `js-loaded` class → `initMotionGate` → `projectConstants` → `initReveals` → `initHeroAnimation` → `initPipelineAnimation` → `initCopyButtons`.
- Constants `REPO_URL` and `QUICKSTART_CMD` declared at top.
- Projects `data-repo-url` onto `<body>`, rewrites `href` on `[data-href="repo"]`, sets `data-copy` and inner `<code>` text on `[data-copy-target="quickstart"]`.
- Runs immediately if DOM is already loaded; otherwise waits for `DOMContentLoaded`.
- No console errors on load.

---

### task: html-shell-and-head

**Goal:** Create `landingpage/index.html` with the document shell — `<head>` (meta, SEO, OG, favicon, CSS load order), `<noscript>` notice, sticky `<header>`, empty `<main>` with section placeholders, and an empty `<footer>`. Subsequent tasks fill in each section's content.

**Context:**
The HTML is a single semantic document (~400-600 lines when complete). Load order in `<head>`:

```html
<link rel="stylesheet" href="assets/css/reset.css">
<link rel="stylesheet" href="assets/css/tokens.css">
<link rel="stylesheet" href="assets/css/layout.css">
<link rel="stylesheet" href="assets/css/components.css">
<link rel="stylesheet" href="assets/css/sections.css">
```

The script tag is `<script type="module" src="assets/js/main.js" defer></script>` placed just before `</body>` (or in `<head>` since `defer` is implicit for modules — placement at end of body is also fine and more universally compatible).

Meta from design spec:
- `<title>AgentHarness — Delegate the grind. Reclaim your time.</title>`
- description: "AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship."
- canonical: `https://github.com/onpaj/AgentHarness`
- OG type: website, OG image: `assets/img/og-image.png`
- Twitter card: `summary_large_image`
- favicon: `assets/img/favicon.svg`, fallback `assets/img/favicon.ico`, `assets/img/apple-touch-icon.png`
- `<html lang="en">`

Header structure:
```html
<header class="site-header">
  <div class="container">
    <a href="#" class="wordmark">Agent<span>Harness</span></a>
    <a class="btn btn-secondary" data-href="repo" href="https://github.com/onpaj/AgentHarness" target="_blank" rel="noopener noreferrer">
      View on GitHub
      <svg class="icon-sm" ...arrow...></svg>
    </a>
  </div>
</header>
```

Section placeholders use these IDs and classes (filled in by subsequent tasks):
- `<section id="hero" class="hero section"><div class="container"></div></section>`
- `<section id="how-it-works" class="how-it-works section"><div class="container"></div></section>`
- `<section id="features" class="features section"><div class="container"></div></section>`
- `<section id="pipeline" class="pipeline section"><div class="container"></div></section>`
- `<section id="cta" class="cta section"><div class="container"></div></section>`

Footer placeholder is the empty `<footer class="site-footer">` (filled later).

The `<noscript>` notice goes immediately after `<body>` open tag.

**Files to create/modify:**
- `landingpage/index.html` — full document shell

**Implementation steps:**
1. Create `landingpage/index.html` with the following content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgentHarness — Delegate the grind. Reclaim your time.</title>
  <meta name="description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
  <meta name="theme-color" content="#0a0f1e">
  <link rel="canonical" href="https://github.com/onpaj/AgentHarness">

  <meta property="og:type" content="website">
  <meta property="og:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
  <meta property="og:description" content="A chain of Claude agents builds your features autonomously. Describe it once. Watch it ship.">
  <meta property="og:image" content="assets/img/og-image.png">
  <meta property="og:url" content="https://github.com/onpaj/AgentHarness">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
  <meta name="twitter:description" content="A chain of Claude agents builds your features autonomously.">
  <meta name="twitter:image" content="assets/img/og-image.png">

  <link rel="icon" type="image/svg+xml" href="assets/img/favicon.svg">
  <link rel="icon" type="image/x-icon" href="assets/img/favicon.ico">
  <link rel="apple-touch-icon" href="assets/img/apple-touch-icon.png">

  <link rel="stylesheet" href="assets/css/reset.css">
  <link rel="stylesheet" href="assets/css/tokens.css">
  <link rel="stylesheet" href="assets/css/layout.css">
  <link rel="stylesheet" href="assets/css/components.css">
  <link rel="stylesheet" href="assets/css/sections.css">
</head>
<body>
  <noscript>
    <div class="noscript-notice">
      JavaScript is disabled — animations are off, but all content and links work normally.
    </div>
  </noscript>

  <header class="site-header">
    <div class="container">
      <a href="#" class="wordmark">Agent<span>Harness</span></a>
      <a class="btn btn-secondary"
         data-href="repo"
         href="https://github.com/onpaj/AgentHarness"
         target="_blank"
         rel="noopener noreferrer"
         aria-label="View AgentHarness on GitHub">
        View on GitHub
        <svg class="icon-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M7 17L17 7"/>
          <path d="M7 7h10v10"/>
        </svg>
      </a>
    </div>
  </header>

  <main>
    <section id="hero" class="hero section" aria-labelledby="hero-title">
      <div class="container"></div>
    </section>

    <section id="how-it-works" class="how-it-works section" aria-labelledby="how-title">
      <div class="container"></div>
    </section>

    <section id="features" class="features section" aria-labelledby="features-title">
      <div class="container"></div>
    </section>

    <section id="pipeline" class="pipeline section" aria-labelledby="pipeline-title">
      <div class="container"></div>
    </section>

    <section id="cta" class="cta section" aria-labelledby="cta-title">
      <div class="container"></div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container"></div>
  </footer>

  <script type="module" src="assets/js/main.js" defer></script>
</body>
</html>
```

**Tests to write:**
Manual:
- Open `landingpage/index.html` in a browser. Confirm:
  - Page loads with no console errors.
  - `<html>` gains `.js-loaded` class.
  - Sticky header is visible at top.
  - `<head>` contains all meta tags (open-graph, twitter, favicon, canonical).
  - View page source: 5 CSS link tags load in order: reset → tokens → layout → components → sections.
  - Disable JS, reload. The "JavaScript is disabled" banner appears at top.

**Acceptance criteria:**
- File `landingpage/index.html` exists.
- `<html lang="en">`.
- All five CSS files linked in correct order.
- ES module script tag points to `assets/js/main.js` with `type="module"` and `defer`.
- Sticky header contains wordmark and "View on GitHub" CTA with `data-href="repo"`, `target="_blank"`, `rel="noopener noreferrer"`.
- `<main>` contains 5 empty `<section>` elements with the correct IDs (`hero`, `how-it-works`, `features`, `pipeline`, `cta`).
- `<noscript>` notice present immediately after `<body>`.
- All asset paths are relative (no leading `/`).

---

### task: html-hero-section

**Goal:** Populate the `#hero` section in `landingpage/index.html` with headline, subhead, CTAs, copy-command, and the animated SVG pipeline glyph.

**Context:**
The hero takes the full viewport on desktop. Two-column split layout (text left, SVG right) at ≥1024px, stacked on mobile.

Headline and subhead copy (from design):
- Headline: "Delegate the grind. Reclaim your time." with "Reclaim your time." in `--color-accent`.
- Subhead: "A chain of Claude agents builds your features while you focus on what matters."

CTAs:
- Primary: "Get started on GitHub" → repo URL, opens in new tab.
- Secondary copy command: `$ pip install agentharness && agentharness brainstorm`

Hero SVG glyph (per design): six nodes (analyst → architect → designer → planner → developer → reviewer) connected by horizontal edges. Each node is a `<circle class="hero-node">` so the CSS can sequence-pulse them. Edges are `<line class="hero-edge">`. Labels below each node use `<text class="hero-label">`.

The CSS in `sections.css` already styles `.hero-node` and `.hero-edge` and animates them via `@keyframes node-pulse` with staggered `animation-delay`.

The `[data-reveal]` attribute should NOT be applied to the hero text — the hero must be visible immediately on load (no fade-in delay above the fold). However, the SVG can pulse via its own CSS animation immediately.

The copy button uses `data-copy-target="quickstart"` so `main.js` projects the constant text. Hardcoded fallback in HTML matches.

The hero must be inside the existing `<div class="container">` of the section.

**Files to create/modify:**
- `landingpage/index.html` — fill in `#hero` `<div class="container">` content

**Implementation steps:**
1. Locate the `<section id="hero" class="hero section">` element in `landingpage/index.html`.
2. Replace its `<div class="container"></div>` with:

```html
      <div class="container">
        <div class="split">
          <div class="stack stack-lg">
            <h1 id="hero-title" class="hero-headline">
              Delegate the grind.<br>
              <span class="accent">Reclaim your time.</span>
            </h1>
            <p class="hero-sub">
              A chain of Claude agents — analyst, architect, planner, developer, reviewer —
              builds your features autonomously while you focus on what matters.
            </p>
            <div class="hero-actions">
              <a class="btn btn-primary"
                 data-href="repo"
                 href="https://github.com/onpaj/AgentHarness"
                 target="_blank"
                 rel="noopener noreferrer">
                Get started on GitHub
                <svg class="icon-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M7 17L17 7"/>
                  <path d="M7 7h10v10"/>
                </svg>
              </a>
              <button class="copy-command"
                      type="button"
                      data-copy="pip install agentharness &amp;&amp; agentharness brainstorm"
                      data-copy-target="quickstart"
                      data-copy-feedback="Copied!"
                      aria-label="Copy quick-start command">
                <code>$ pip install agentharness &amp;&amp; agentharness brainstorm</code>
                <span class="copy-icon" aria-hidden="true"></span>
              </button>
            </div>
          </div>

          <div class="hero-visual" aria-hidden="true">
            <svg class="hero-svg" viewBox="0 0 560 200" xmlns="http://www.w3.org/2000/svg">
              <title>Agent pipeline visualization</title>
              <desc>Six agents — analyst, architect, designer, planner, developer, reviewer — pulse left to right, connected by edges.</desc>

              <line class="hero-edge" x1="60"  y1="80" x2="140" y2="80"/>
              <line class="hero-edge" x1="160" y1="80" x2="220" y2="80"/>
              <line class="hero-edge" x1="240" y1="80" x2="300" y2="80"/>
              <line class="hero-edge" x1="320" y1="80" x2="380" y2="80"/>
              <line class="hero-edge" x1="400" y1="80" x2="460" y2="80"/>

              <circle class="hero-node" cx="40"  cy="80" r="14"/>
              <circle class="hero-node" cx="140" cy="80" r="14"/>
              <circle class="hero-node" cx="240" cy="80" r="14"/>
              <circle class="hero-node" cx="320" cy="80" r="14"/>
              <circle class="hero-node" cx="420" cy="80" r="14"/>
              <circle class="hero-node" cx="520" cy="80" r="14"/>

              <text class="hero-label" x="40"  y="118">analyst</text>
              <text class="hero-label" x="140" y="118">architect</text>
              <text class="hero-label" x="240" y="118">designer</text>
              <text class="hero-label" x="320" y="118">planner</text>
              <text class="hero-label" x="420" y="118">developer</text>
              <text class="hero-label" x="520" y="118">reviewer</text>
            </svg>
          </div>
        </div>
      </div>
```

**Tests to write:**
Manual:
- Open in browser at desktop width: hero takes full viewport, headline left, SVG right.
- "Reclaim your time." is rendered in cyan (`#00d4ff`).
- Resize to <1024px: text stacks above SVG.
- Six SVG circles pulse in sequence (one every second, looping every 6s).
- Hover over "Get started on GitHub" — button lifts.
- Click the copy command — clipboard contains `pip install agentharness && agentharness brainstorm` (verified by pasting), button shows ✓ and "Copied!" toast for 2s.
- Click "Get started on GitHub" — opens repo in new tab.

**Acceptance criteria:**
- `#hero` contains `.split` layout with text left, SVG right.
- Headline uses `<h1 id="hero-title" class="hero-headline">` with the second line wrapped in `<span class="accent">`.
- Primary CTA has `data-href="repo"`, `target="_blank"`, `rel="noopener noreferrer"`.
- Copy button has `data-copy-target="quickstart"` and a hardcoded fallback `data-copy` value matching the constant in `main.js`.
- SVG contains 6 `<circle class="hero-node">` and 5 `<line class="hero-edge">` plus 6 `<text class="hero-label">`.
- SVG includes `<title>` and `<desc>` for accessibility.
- `aria-hidden="true"` on the visual wrapper since the text already conveys meaning.

---

### task: html-how-it-works-section

**Goal:** Populate the `#how-it-works` section with three step cards (Brainstorm → Agents work → Code ships) including inline Lucide-style SVG icons, separated by connector arrows. Each step has `[data-reveal]` with staggered delay.

**Context:**
Three-step horizontal flow on desktop (≥768px), stacked vertically on mobile. Steps reveal sequentially via `data-reveal-delay` (100ms, 200ms, 300ms).

Step content:

1. **Brainstorm** — "Describe your feature in a guided conversation. The brainstorm skill captures requirements and writes a brief." Icon: `message-square` (Lucide).
2. **Agents work** — "An autonomous chain — analyst, architect, designer, planner, developer, reviewer — builds and reviews your feature without further input." Icon: `cpu`.
3. **Code ships** — "Implementation lands as a branch and PR, ready to merge. You review the result, not the keystrokes." Icon: `git-pull-request`.

Connectors (between cards) are `<div class="step-connector" aria-hidden="true">→</div>`. CSS hides them on mobile and shows on tablet+.

The grid template `1fr auto 1fr auto 1fr` accommodates: card | arrow | card | arrow | card.

Inline SVG icons (24×24, simplified Lucide-style with stroke attributes — match the Lucide visual style; exact path data may be approximate but must look like the named icon):

- `message-square`: rounded rectangle with one corner notch
- `cpu`: square with internal pins on all 4 sides
- `git-pull-request`: two circles connected by a line with a branch arrow

Use `class="icon-lg"` (40×40) on the icon SVG so it fills the card's icon slot.

**Files to create/modify:**
- `landingpage/index.html` — fill in `#how-it-works` `<div class="container">` content

**Implementation steps:**
1. Locate `<section id="how-it-works" class="how-it-works section">` and replace its empty container with:

```html
      <div class="container">
        <div class="features-header" data-reveal>
          <h2 id="how-title">From idea to shipped feature in three steps.</h2>
          <p>You describe what you want. AgentHarness handles the rest.</p>
        </div>

        <div class="steps">
          <div class="step" data-reveal data-reveal-delay="0">
            <span class="step-number">Step 1</span>
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <h3>Brainstorm</h3>
            <p>Describe your feature in a guided conversation. The brainstorm skill captures requirements and writes a brief.</p>
          </div>

          <div class="step-connector" aria-hidden="true">→</div>

          <div class="step" data-reveal data-reveal-delay="150">
            <span class="step-number">Step 2</span>
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="4" y="4" width="16" height="16" rx="2"/>
              <rect x="9" y="9" width="6" height="6"/>
              <line x1="9"  y1="2"  x2="9"  y2="4"/>
              <line x1="15" y1="2"  x2="15" y2="4"/>
              <line x1="9"  y1="20" x2="9"  y2="22"/>
              <line x1="15" y1="20" x2="15" y2="22"/>
              <line x1="20" y1="9"  x2="22" y2="9"/>
              <line x1="20" y1="15" x2="22" y2="15"/>
              <line x1="2"  y1="9"  x2="4"  y2="9"/>
              <line x1="2"  y1="15" x2="4"  y2="15"/>
            </svg>
            <h3>Agents work</h3>
            <p>An autonomous chain — analyst, architect, designer, planner, developer, reviewer — builds and reviews your feature without further input.</p>
          </div>

          <div class="step-connector" aria-hidden="true">→</div>

          <div class="step" data-reveal data-reveal-delay="300">
            <span class="step-number">Step 3</span>
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="6"  cy="6"  r="3"/>
              <circle cx="6"  cy="18" r="3"/>
              <circle cx="18" cy="18" r="3"/>
              <line x1="6" y1="9" x2="6" y2="15"/>
              <path d="M18 9a6 6 0 0 0-6-6h-3"/>
              <polyline points="9,1 6,3 9,5"/>
            </svg>
            <h3>Code ships</h3>
            <p>Implementation lands as a branch and PR, ready to merge. You review the result, not the keystrokes.</p>
          </div>
        </div>
      </div>
```

**Tests to write:**
Manual:
- Desktop width (≥768px): three step cards in a row separated by → arrows.
- Mobile width (<768px): three cards stacked vertically, no arrows visible.
- Scroll into view: cards fade-up with stagger (Step 1 → Step 2 → Step 3).
- Set `prefers-reduced-motion: reduce`: cards appear immediately at full opacity, no transition.
- Each card shows step number, icon (cyan), heading, paragraph.

**Acceptance criteria:**
- `#how-it-works` contains a `.features-header` block with `<h2 id="how-title">` and a lead paragraph.
- Three `.step` blocks with `data-reveal` and `data-reveal-delay` of 0, 150, 300.
- Each step has: `.step-number` span, an inline SVG icon (`class="icon-lg"`, `currentColor` stroke), `<h3>`, `<p>`.
- Two `.step-connector` divs between the three steps with `aria-hidden="true"`.
- All inline SVG icons use stroke-based Lucide style with `stroke="currentColor"`.

---

### task: html-features-section

**Goal:** Populate the `#features` section with six feature cards (Multi-agent pipeline, Per-task review loop, Pluggable backends, Zero babysitting, Per-agent context files, Serial task dispatch) in a responsive grid with inline Lucide-style icons and `[data-reveal]` staggered delays.

**Context:**
Six feature cards in a responsive grid: 1 column on mobile, 2 on tablet (768px+), 3 on desktop (1024px+). Each card has icon + title + 2-3 sentence description and the `.feature-card` hover lift.

The grid uses the `.grid .grid-2 .grid-3` utility classes from `layout.css`.

Card content (copy aligned with AgentHarness CLAUDE.md):

1. **Multi-agent pipeline** — `workflow` icon — "Specialized agents — analyst, architect, designer, planner, developer, reviewer — chain together. Each one is a focused Claude with a system prompt and a job."
2. **Per-task review loop** — `repeat` icon — "Every developer task goes through its own reviewer. Failed reviews trigger a revision cycle until the work meets the bar — or hits the max revision limit."
3. **Pluggable backends** — `layers` icon — "Run on Azure Blob Storage and Storage Queues, or use GitHub Issues and branches. Same pipeline, swap the backend with one env var."
4. **Zero babysitting** — `bot` icon — "An observer process polls all queues and spawns workers per message. Start it and walk away — the pipeline runs itself end-to-end."
5. **Per-agent context files** — `file-text` icon — "Each agent gets curated context — the docs, schemas, or examples it needs. No more dumping the entire repo into every prompt."
6. **Serial task dispatch** — `list-ordered` icon — "Developer tasks run one at a time to prevent same-file conflicts. The planner emits the full plan; tasks queue serially as each passes review."

Header above the grid:
- `<h2 id="features-title">Built for developers who'd rather ship.</h2>`
- subtitle: "Six things AgentHarness gets right, so you don't have to."

Inline SVG for each icon (Lucide-style 24×24 stroke icons; `class="icon-lg"` for 40×40 sizing):

| Icon | Approximate paths |
|---|---|
| `workflow` | three rounded rects connected by lines |
| `repeat` | circular arrow (two arcs with arrowheads) |
| `layers` | three stacked diamonds/parallelograms |
| `bot` | rectangle (head) with antenna and two dot-eyes |
| `file-text` | document with horizontal lines |
| `list-ordered` | numbered list lines (1. 2. 3.) |

**Files to create/modify:**
- `landingpage/index.html` — fill in `#features` `<div class="container">` content

**Implementation steps:**
1. Locate `<section id="features" class="features section">` and replace its empty container with:

```html
      <div class="container">
        <div class="features-header" data-reveal>
          <h2 id="features-title">Built for developers who'd rather ship.</h2>
          <p>Six things AgentHarness gets right, so you don't have to.</p>
        </div>

        <div class="grid grid-2 grid-3">
          <article class="feature-card" data-reveal data-reveal-delay="0">
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="3"  y="3"  width="6" height="6" rx="1"/>
              <rect x="15" y="3"  width="6" height="6" rx="1"/>
              <rect x="9"  y="15" width="6" height="6" rx="1"/>
              <path d="M6 9v3a2 2 0 0 0 2 2h2"/>
              <path d="M18 9v3a2 2 0 0 1-2 2h-2"/>
            </svg>
            <h3>Multi-agent pipeline</h3>
            <p>Specialized agents — analyst, architect, designer, planner, developer, reviewer — chain together. Each is a focused Claude with a system prompt and a job.</p>
          </article>

          <article class="feature-card" data-reveal data-reveal-delay="100">
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polyline points="17,1 21,5 17,9"/>
              <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
              <polyline points="7,23 3,19 7,15"/>
              <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
            </svg>
            <h3>Per-task review loop</h3>
            <p>Every developer task goes through its own reviewer. Failed reviews trigger a revision cycle until the work meets the bar — or hits the max revision limit.</p>
          </article>

          <article class="feature-card" data-reveal data-reveal-delay="200">
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polygon points="12,2 22,7 12,12 2,7"/>
              <polyline points="2,17 12,22 22,17"/>
              <polyline points="2,12 12,17 22,12"/>
            </svg>
            <h3>Pluggable backends</h3>
            <p>Run on Azure Blob Storage and Storage Queues, or use GitHub Issues and branches. Same pipeline, swap the backend with one env var.</p>
          </article>

          <article class="feature-card" data-reveal data-reveal-delay="0">
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="3" y="11" width="18" height="10" rx="2"/>
              <circle cx="12" cy="5" r="2"/>
              <path d="M12 7v4"/>
              <line x1="8"  y1="16" x2="8"  y2="16"/>
              <line x1="16" y1="16" x2="16" y2="16"/>
            </svg>
            <h3>Zero babysitting</h3>
            <p>An observer process polls all queues and spawns workers per message. Start it and walk away — the pipeline runs itself end-to-end.</p>
          </article>

          <article class="feature-card" data-reveal data-reveal-delay="100">
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
              <line x1="8"  y1="13" x2="16" y2="13"/>
              <line x1="8"  y1="17" x2="16" y2="17"/>
              <line x1="8"  y1="9"  x2="10" y2="9"/>
            </svg>
            <h3>Per-agent context files</h3>
            <p>Each agent gets curated context — the docs, schemas, or examples it needs. No more dumping the entire repo into every prompt.</p>
          </article>

          <article class="feature-card" data-reveal data-reveal-delay="200">
            <svg class="icon-lg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="10" y1="6"  x2="21" y2="6"/>
              <line x1="10" y1="12" x2="21" y2="12"/>
              <line x1="10" y1="18" x2="21" y2="18"/>
              <path d="M4 6h1v4"/>
              <path d="M4 10h2"/>
              <path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>
            </svg>
            <h3>Serial task dispatch</h3>
            <p>Developer tasks run one at a time to prevent same-file conflicts. The planner emits the full plan; tasks queue serially as each passes review.</p>
          </article>
        </div>
      </div>
```

**Tests to write:**
Manual:
- Desktop ≥1024px: 3-column grid of 6 cards (2 rows).
- Tablet 768-1023px: 2-column grid (3 rows).
- Mobile <768px: 1-column stack (6 rows).
- Hover any card: lifts 4px, gains cyan border, shadow appears.
- Scroll into view: cards fade-up with row stagger (0/100/200ms).
- Each card shows icon (cyan), heading, paragraph.

**Acceptance criteria:**
- `#features` contains `.features-header` with `<h2 id="features-title">` and intro paragraph.
- Six `<article class="feature-card">` blocks inside `.grid.grid-2.grid-3`.
- Each card has `data-reveal`; delays alternate 0/100/200/0/100/200 across the two rows.
- Each card has an inline SVG with `class="icon-lg"` and `stroke="currentColor"`.
- Card content matches the six titles + descriptions exactly as specified.
- All SVGs are `aria-hidden="true"` since the heading conveys meaning.

---

### task: html-pipeline-section

**Goal:** Populate the `#pipeline` section with a header, an animated terminal block showing simulated `agentharness observe` output (9 lines + cursor), each with `class="pipeline-line"` so JS can stream them in with a 400ms stagger.

**Context:**
The terminal block is on the dark `--color-bg-base` surface. Inside, a `.terminal` element shows monospaced lines. The first line is the prompt `$ agentharness observe`. The rest are status lines from the design's canonical schema:

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

Plus a final blinking cursor line `█`.

Each line is wrapped in a `<div class="pipeline-line">` with inline `<span>` markers for color groups defined in `sections.css`:
- `.ts` — timestamp (dim)
- `.agent` — agent name (accent)
- `.ok` — green check status
- `.arrow` — dim arrow

The JS `initPipelineAnimation` re-triggers visibility on each scroll-into-view.

The cursor line uses `<div class="pipeline-line pipeline-cursor">` — the `::after` in CSS provides the blinking `█`.

To preserve the column alignment, use `white-space: pre` on `.pipeline-line` and use ASCII spaces inside the spans.

The header above the terminal:
- `<h2 id="pipeline-title">See it run.</h2>`
- subtitle: "A real `agentharness observe` session — agents progress through the pipeline, reviewers gate each step, the next task auto-dispatches."

**Files to create/modify:**
- `landingpage/index.html` — fill in `#pipeline` `<div class="container">` content

**Implementation steps:**
1. Locate `<section id="pipeline" class="pipeline section">` and replace its empty container with:

```html
      <div class="container">
        <div class="pipeline-header" data-reveal>
          <h2 id="pipeline-title">See it run.</h2>
          <p>A real <code>agentharness observe</code> session — agents progress through the pipeline, reviewers gate each step, the next task auto-dispatches.</p>
        </div>

        <div class="terminal" data-reveal aria-label="Simulated agentharness observe output" role="img">
          <div class="terminal-prompt">$ agentharness observe</div>

          <div class="pipeline-line"><span class="ts">[12:01:04]</span>  <span class="agent">analyst       </span>  <span class="arrow">→</span> analyzing        feat-abc123</div>
          <div class="pipeline-line"><span class="ts">[12:01:22]</span>  <span class="agent">analyst       </span>  <span class="ok">✓</span> complete         18s</div>
          <div class="pipeline-line"><span class="ts">[12:01:23]</span>  <span class="agent">architect     </span>  <span class="arrow">→</span> analyzing</div>
          <div class="pipeline-line"><span class="ts">[12:01:55]</span>  <span class="agent">architect     </span>  <span class="ok">✓</span> complete         32s</div>
          <div class="pipeline-line"><span class="ts">[12:01:56]</span>  <span class="agent">planner       </span>  <span class="arrow">→</span> planning</div>
          <div class="pipeline-line"><span class="ts">[12:02:14]</span>  <span class="agent">planner       </span>  <span class="ok">✓</span> complete         18s  3 tasks</div>
          <div class="pipeline-line"><span class="ts">[12:02:15]</span>  <span class="agent">developer[1]  </span>  <span class="arrow">→</span> in_progress</div>
          <div class="pipeline-line"><span class="ts">[12:03:44]</span>  <span class="agent">reviewer[1]   </span>  <span class="ok">✓</span> PASS</div>
          <div class="pipeline-line"><span class="ts">[12:03:45]</span>  <span class="agent">developer[2]  </span>  <span class="arrow">→</span> in_progress</div>
          <div class="pipeline-line pipeline-cursor"></div>
        </div>
      </div>
```

**Tests to write:**
Manual:
- Scroll the pipeline section into view: lines stream in one-by-one with ~400ms gap between each. Cursor appears blinking after the last line.
- Scroll away and back: animation restarts (lines reset to invisible, then re-appear in sequence).
- Set `prefers-reduced-motion: reduce`: all lines visible immediately, no blink.
- Color check: timestamps dim, agent names cyan, ✓ green, → dim.
- On mobile (375px): terminal block scrolls horizontally without breaking layout.

**Acceptance criteria:**
- `#pipeline` contains `.pipeline-header` with `<h2 id="pipeline-title">` and lead paragraph.
- `.terminal` block has `role="img"` and `aria-label` describing it (since it's decorative animation).
- First child of terminal is `.terminal-prompt` with `$ agentharness observe`.
- 9 `.pipeline-line` divs with the canonical content from the schema, plus 1 `.pipeline-line.pipeline-cursor` final line.
- Each line uses inline `<span class="ts/agent/ok/arrow">` for color groups.
- `[data-reveal]` on header and terminal block so they fade-in on scroll (terminal lines additionally stream via `initPipelineAnimation`).

---

### task: html-cta-and-footer

**Goal:** Populate the `#cta` section (final conversion block) and the `<footer>` (links, license, wordmark).

**Context:**
CTA section content:
- Headline: "Stop writing boilerplate. Start shipping."
- Primary CTA: "View on GitHub" → repo URL.
- Secondary copy command: `$ pip install agentharness && agentharness brainstorm` (uses `data-copy-target="quickstart"` so `main.js` overwrites it from the constant).

Footer content:
- Wordmark left
- Right side: links to GitHub repo and license note
- License: "MIT License"

The CTA inherits the `.cta` and `.section` classes; CSS already centers content.

The footer is structured with `.container` already in the shell — fill in the inner content.

External links must have `target="_blank"` and `rel="noopener noreferrer"`.

**Files to create/modify:**
- `landingpage/index.html` — fill in `#cta` and `<footer>` content

**Implementation steps:**
1. Locate `<section id="cta" class="cta section">` and replace its empty container with:

```html
      <div class="container">
        <h2 id="cta-title" data-reveal>Stop writing boilerplate.<br>Start shipping.</h2>
        <div class="cta-actions" data-reveal data-reveal-delay="100">
          <a class="btn btn-primary"
             data-href="repo"
             href="https://github.com/onpaj/AgentHarness"
             target="_blank"
             rel="noopener noreferrer">
            View on GitHub
            <svg class="icon-sm" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M7 17L17 7"/>
              <path d="M7 7h10v10"/>
            </svg>
          </a>
          <button class="copy-command"
                  type="button"
                  data-copy="pip install agentharness &amp;&amp; agentharness brainstorm"
                  data-copy-target="quickstart"
                  data-copy-feedback="Copied!"
                  aria-label="Copy quick-start command">
            <code>$ pip install agentharness &amp;&amp; agentharness brainstorm</code>
            <span class="copy-icon" aria-hidden="true"></span>
          </button>
        </div>
      </div>
```

2. Locate `<footer class="site-footer">` and replace its empty container with:

```html
      <div class="container">
        <a href="#" class="wordmark">Agent<span>Harness</span></a>
        <nav aria-label="Footer">
          <a data-href="repo"
             href="https://github.com/onpaj/AgentHarness"
             target="_blank"
             rel="noopener noreferrer">GitHub</a>
          <span aria-hidden="true"> · </span>
          <span>MIT License</span>
        </nav>
      </div>
```

**Tests to write:**
Manual:
- CTA section: headline centered, two-line break visible, primary CTA + copy command on one row (centered).
- Click "View on GitHub" — opens repo in new tab.
- Click copy command — clipboard filled, ✓ + "Copied!" feedback for 2s.
- Footer: wordmark left, "GitHub · MIT License" right.
- Scroll page to bottom: CTA `<h2>` and `.cta-actions` reveal-fade with 100ms stagger.

**Acceptance criteria:**
- `#cta` contains `<h2 id="cta-title" data-reveal>` with the headline split across two lines via `<br>`.
- `.cta-actions` contains primary CTA (`data-href="repo"`) and copy-command button (`data-copy-target="quickstart"`) with hardcoded fallback text.
- Footer contains wordmark and a `<nav aria-label="Footer">` with a GitHub link and "MIT License" text.
- All external links use `target="_blank"` and `rel="noopener noreferrer"`.

---

### task: assets-favicon-and-og-placeholder

**Goal:** Add a minimal favicon (SVG + ICO) and a placeholder OG image so all referenced asset paths resolve and the page passes Lighthouse meta checks.

**Context:**
The `<head>` references:
- `assets/img/favicon.svg`
- `assets/img/favicon.ico`
- `assets/img/apple-touch-icon.png`
- `assets/img/og-image.png` (1200×630)

Per arch review risk table: "OG image missing at launch breaks social sharing" — the launch blocker is the final designed image, but during build a placeholder generated from the hero SVG is acceptable.

The favicon SVG can be a simple cyan circle representing a node — small, distinctive, matches palette.

For binary placeholders (favicon.ico, apple-touch-icon.png, og-image.png), produce minimal valid files:
- `favicon.ico`: copy the SVG bytes as a fallback won't work; instead, produce a 1×1 transparent ICO using a known template OR use ImageMagick/a tiny script. For a no-build-step project, the simplest path is to commit a tiny pre-made placeholder.
- `apple-touch-icon.png`: a 180×180 PNG with the AgentHarness wordmark or a single cyan circle.
- `og-image.png`: a 1200×630 PNG with dark background + headline text + accent color.

Since this is a static site with no build pipeline available, generate the placeholder PNGs and ICO using Python's `Pillow` library (pre-installed in dev env, or invoke via system Python). Embed the generation in the implementation steps so a future re-run rebuilds them.

If `Pillow` is unavailable, the developer must commit any minimally valid PNG bytes as placeholders (e.g., a 1×1 transparent PNG referenced at the right paths) so the page does not 404 and Lighthouse passes.

**Files to create/modify:**
- `landingpage/assets/img/favicon.svg` — inline SVG favicon
- `landingpage/assets/img/favicon.ico` — small placeholder
- `landingpage/assets/img/apple-touch-icon.png` — 180×180 placeholder
- `landingpage/assets/img/og-image.png` — 1200×630 placeholder

**Implementation steps:**
1. Create `landingpage/assets/img/favicon.svg` with the following content:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#0a0f1e"/>
  <circle cx="32" cy="32" r="14" fill="#00d4ff"/>
  <circle cx="32" cy="32" r="6" fill="#0a0f1e"/>
</svg>
```

2. Generate the binary placeholders using Python with Pillow. Run this script (or the equivalent) once; commit the resulting binary files:

```python
from PIL import Image, ImageDraw, ImageFont
import os

base = 'landingpage/assets/img'
os.makedirs(base, exist_ok=True)

# Apple touch icon — 180×180
apple = Image.new('RGB', (180, 180), '#0a0f1e')
d = ImageDraw.Draw(apple)
d.rounded_rectangle((20, 20, 160, 160), radius=20, fill='#00d4ff')
d.ellipse((68, 68, 112, 112), fill='#0a0f1e')
apple.save(f'{base}/apple-touch-icon.png', 'PNG')

# Favicon ICO — 32×32 PNG saved as ICO
fav = Image.new('RGBA', (32, 32), (10, 15, 30, 255))
d = ImageDraw.Draw(fav)
d.ellipse((6, 6, 26, 26), fill=(0, 212, 255, 255))
d.ellipse((12, 12, 20, 20), fill=(10, 15, 30, 255))
fav.save(f'{base}/favicon.ico', sizes=[(32, 32)])

# OG image — 1200×630
og = Image.new('RGB', (1200, 630), '#0a0f1e')
d = ImageDraw.Draw(og)
# Headline text
try:
    font_h = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 72)
    font_s = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 32)
except OSError:
    font_h = ImageFont.load_default()
    font_s = ImageFont.load_default()
d.text((80, 200), 'AgentHarness', font=font_h, fill='#e6edf3')
d.text((80, 290), 'Delegate the grind.', font=font_h, fill='#e6edf3')
d.text((80, 370), 'Reclaim your time.', font=font_h, fill='#00d4ff')
d.text((80, 470), 'A chain of Claude agents builds your features.', font=font_s, fill='#8b9bb4')
# Pipeline glyph on the right
for i, x in enumerate([880, 950, 1020, 1090]):
    color = '#00d4ff' if i == 2 else '#1e3a5f'
    d.ellipse((x-20, 295, x+20, 335), fill=color)
    if i < 3:
        d.line((x+20, 315, x+50, 315), fill='#1e3a5f', width=2)
og.save(f'{base}/og-image.png', 'PNG', optimize=True)

print('Placeholder assets generated.')
```

3. Run the script: `python3 path/to/script.py` (or inline via `python3 -c "..."`).
4. Verify all four files exist in `landingpage/assets/img/`.

**Tests to write:**
Manual:
- `ls -la landingpage/assets/img/` — confirms `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `og-image.png` all exist.
- `file landingpage/assets/img/og-image.png` — confirms it is a PNG image, 1200×630.
- Open `landingpage/index.html` in browser, check Network tab — confirms favicon and OG image fetch with 200 status (no 404s).
- View page source, copy `og:image` URL into a debugger like opengraph.xyz — confirms OG image loads.

**Acceptance criteria:**
- All four files exist at the specified paths.
- `favicon.svg` is a valid SVG with the cyan circle motif on dark background.
- `favicon.ico` is a valid ICO file (32×32).
- `apple-touch-icon.png` is a 180×180 PNG.
- `og-image.png` is a 1200×630 PNG with dark background, AgentHarness wordmark, headline text, and pipeline glyph.
- Browser DevTools Network tab shows no 404s for any image asset on page load.