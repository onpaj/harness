### task: scaffold-project-structure

**Goal:** Create the complete `/landingpage` directory structure with empty files in the correct cascade order so subsequent tasks can populate content without worrying about file existence or placement.

**Context:**
The landing page is architecturally isolated from AgentHarness Python codebase. No build step is required — files must work via `file://` direct open, any static file server, or GitHub Pages from `/landingpage` subdirectory. All asset paths must be relative (no leading `/`).

File structure required:
```
landingpage/
├── index.html
├── README.md
├── assets/
│   ├── css/
│   │   ├── reset.css
│   │   ├── tokens.css
│   │   ├── layout.css
│   │   ├── components.css
│   │   └── sections.css
│   ├── js/
│   │   ├── main.js
│   │   ├── animations.js
│   │   ├── copy.js
│   │   └── motion.js
│   ├── img/
│   │   └── icons/
│   └── fonts/
```

CSS load order is fixed: `reset.css` → `tokens.css` → `layout.css` → `components.css` → `sections.css`. Each file only references tokens defined upstream. JS uses native ES modules with `<script type="module">`.

**Files to create/modify:**
- `landingpage/index.html` — minimal valid HTML5 skeleton, will be filled in later tasks
- `landingpage/README.md` — brief: what the page is, how to view locally, how to deploy
- `landingpage/assets/css/reset.css` — empty placeholder (populated in later task)
- `landingpage/assets/css/tokens.css` — empty placeholder
- `landingpage/assets/css/layout.css` — empty placeholder
- `landingpage/assets/css/components.css` — empty placeholder
- `landingpage/assets/css/sections.css` — empty placeholder
- `landingpage/assets/js/main.js` — empty placeholder
- `landingpage/assets/js/animations.js` — empty placeholder
- `landingpage/assets/js/copy.js` — empty placeholder
- `landingpage/assets/js/motion.js` — empty placeholder
- `landingpage/assets/img/icons/.gitkeep` — placeholder so directory is tracked
- `landingpage/assets/fonts/.gitkeep` — placeholder so directory is tracked

**Implementation steps:**
1. Create `landingpage/` directory at repository root.
2. Create all subdirectories: `landingpage/assets/css/`, `landingpage/assets/js/`, `landingpage/assets/img/icons/`, `landingpage/assets/fonts/`.
3. Create empty CSS files: `reset.css`, `tokens.css`, `layout.css`, `components.css`, `sections.css` in `landingpage/assets/css/`. Each file should contain a single comment with its name (e.g., `/* reset.css */`).
4. Create empty JS files: `main.js`, `animations.js`, `copy.js`, `motion.js` in `landingpage/assets/js/`. Each file should contain a single comment with its name.
5. Create `.gitkeep` files in `assets/img/icons/` and `assets/fonts/` (empty files).
6. Create `landingpage/index.html` with this minimal valid skeleton:
   ```html
   <!DOCTYPE html>
   <html lang="en">
   <head>
     <meta charset="UTF-8">
     <meta name="viewport" content="width=device-width, initial-scale=1.0">
     <title>AgentHarness</title>
   </head>
   <body>
   </body>
   </html>
   ```
7. Create `landingpage/README.md` with the following content:
   ```markdown
   # AgentHarness Landing Page

   Static, single-page marketing site for AgentHarness.

   ## View locally

   - Open `index.html` directly in a browser (`file://`)
   - Or serve as static files: `python -m http.server` from this directory, then visit http://localhost:8000

   ## Deploy

   - GitHub Pages: configure to serve from `/landingpage`
   - Netlify / Vercel / any CDN: drag the `landingpage/` directory in or point to it
   - All paths are relative; no build step required.

   ## Structure

   - `index.html` — single-page entry
   - `assets/css/` — cascading stylesheets (reset → tokens → layout → components → sections)
   - `assets/js/` — ES modules (main, animations, copy, motion)
   - `assets/img/` — favicon, OG image, SVG icons
   - `assets/fonts/` — optional self-hosted fonts
   ```

**Tests to write:**
No automated tests for this task — file existence is verified manually.

Manual verification checklist:
- All directories listed above exist
- All listed files exist (even if empty/placeholder)
- `landingpage/index.html` opens in a browser without errors and shows a blank page titled "AgentHarness"
- No console errors when opening `index.html`

**Acceptance criteria:**
- Running `ls landingpage/` shows: `assets`, `index.html`, `README.md`
- Running `ls landingpage/assets/css/` shows: `components.css`, `layout.css`, `reset.css`, `sections.css`, `tokens.css`
- Running `ls landingpage/assets/js/` shows: `animations.js`, `copy.js`, `main.js`, `motion.js`
- Opening `landingpage/index.html` in Chrome, Firefox, and Safari produces no console errors
- The page title shown in the browser tab is "AgentHarness"

---

### task: css-reset-and-tokens

**Goal:** Implement the CSS reset and design token custom properties so all subsequent CSS can consume a consistent, theme-driven foundation.

**Context:**
Visual design tokens (palette, typography, spacing) are the single source of truth for theme. CSS custom properties work in all target browsers (last 2 versions of Chrome, Firefox, Safari) without a build step. The `:root.no-motion *` selector globally disables transitions/animations as a safety net for users with `prefers-reduced-motion: reduce`.

Palette:
```
--color-bg-base:     #0a0f1e   (deep navy)
--color-bg-mid:      #1e3a5f   (mid surface)
--color-bg-surface:  #162847   (lighter card variant)
--color-accent:      #00d4ff   (cyan)
--color-accent-dim:  rgba(0, 212, 255, 0.12)
--color-text:        #e6edf3
--color-text-dim:    #8b9bb4
--color-border:      rgba(255, 255, 255, 0.08)
--color-border-hover: rgba(0, 212, 255, 0.30)
```

Typography uses fluid `clamp()` for headlines, system stack as fallback when web fonts not loaded. Page is dark-only by design — `<body>` background is `--color-bg-base`, default text is `--color-text`.

**Files to create/modify:**
- `landingpage/assets/css/reset.css` — modern box-model reset
- `landingpage/assets/css/tokens.css` — CSS custom properties for the entire theme

**Implementation steps:**
1. Populate `landingpage/assets/css/reset.css` with a modern reset:
   ```css
   /* reset.css */
   *,
   *::before,
   *::after {
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
     -moz-osx-font-smoothing: grayscale;
     text-rendering: optimizeLegibility;
   }

   img,
   picture,
   video,
   canvas,
   svg {
     display: block;
     max-width: 100%;
   }

   input,
   button,
   textarea,
   select {
     font: inherit;
     color: inherit;
   }

   button {
     background: none;
     border: none;
     cursor: pointer;
   }

   p, h1, h2, h3, h4, h5, h6 {
     overflow-wrap: break-word;
   }

   a {
     color: inherit;
     text-decoration: none;
   }

   ul, ol {
     list-style: none;
   }

   @media (prefers-reduced-motion: reduce) {
     html {
       scroll-behavior: auto;
     }
   }
   ```

2. Populate `landingpage/assets/css/tokens.css` with the full token schema:
   ```css
   /* tokens.css */
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

     /* Spacing (4px base) */
     --space-1:  0.25rem;
     --space-2:  0.5rem;
     --space-3:  0.75rem;
     --space-4:  1rem;
     --space-6:  1.5rem;
     --space-8:  2rem;
     --space-12: 3rem;
     --space-16: 4rem;
     --space-24: 6rem;

     /* Layout */
     --container-max:     1280px;
     --section-padding-y: var(--space-24);

     /* Radii */
     --radius-sm: 4px;
     --radius-md: 8px;
     --radius-lg: 16px;

     /* Shadows */
     --shadow-card:  0 4px 16px rgba(0, 0, 0, 0.4);
     --shadow-hover: 0 8px 24px rgba(0, 212, 255, 0.12);

     /* Animation */
     --hero-play-state:  running;
     --duration-reveal:  0.5s;
     --duration-hover:   0.2s;
     --easing-reveal:    ease;
   }

   :root.no-motion *,
   :root.no-motion *::before,
   :root.no-motion *::after {
     animation: none !important;
     transition: none !important;
   }

   body {
     font-family: var(--font-display);
     font-size: var(--text-body);
     color: var(--color-text);
     background-color: var(--color-bg-base);
   }
   ```

3. Verify each file ends with a single trailing newline.

**Tests to write:**
Manual visual verification (no JS framework, no automated CSS test runner per project standards):
- Test case 1: Open `landingpage/index.html` in Chrome with `<link rel="stylesheet" href="assets/css/reset.css">` and `<link rel="stylesheet" href="assets/css/tokens.css">` added to head. Body should appear dark navy (`#0a0f1e`) with off-white text default.
- Test case 2: In DevTools, inspect `:root` computed styles. Verify `--color-bg-base` returns `#0a0f1e` and `--color-accent` returns `#00d4ff`.
- Test case 3: Add `<html class="no-motion">` and a test element with `transition: opacity 1s`. Hover and verify no transition runs.

**Acceptance criteria:**
- `reset.css` contains zero browser-default margins or paddings on `body`, `h1-h6`, `p`, `ul`, `ol`
- `tokens.css` defines every custom property listed in the design schema
- Loading both files in `index.html` makes the body background `#0a0f1e` and default text `#e6edf3`
- DevTools shows all custom properties resolvable on `:root`
- Adding `class="no-motion"` to `<html>` disables all transitions and animations site-wide
- No console errors or invalid CSS warnings in any browser

---

### task: css-layout-utilities

**Goal:** Implement the layout utilities (container, section padding, grid/flex helpers) that all sections will use to position content consistently.

**Context:**
Layout primitives must work without preprocessor. Container max width is `1280px` (from `--container-max`). Sections have vertical padding `--section-padding-y` (6rem). Responsive breakpoints (mobile 375px, tablet 768px, desktop 1024px, wide 1440px) primarily affect section internals — but the container handles horizontal padding adjustments.

Layout file is loaded after `tokens.css`, so all custom properties are available.

**Files to create/modify:**
- `landingpage/assets/css/layout.css` — container, section, grid, flex utilities

**Implementation steps:**
1. Populate `landingpage/assets/css/layout.css`:
   ```css
   /* layout.css */

   .container {
     width: 100%;
     max-width: var(--container-max);
     margin-inline: auto;
     padding-inline: var(--space-6);
   }

   @media (min-width: 768px) {
     .container {
       padding-inline: var(--space-8);
     }
   }

   @media (min-width: 1024px) {
     .container {
       padding-inline: var(--space-12);
     }
   }

   .section {
     padding-block: var(--section-padding-y);
   }

   .section--tight {
     padding-block: var(--space-16);
   }

   .stack > * + * {
     margin-top: var(--space-4);
   }

   .stack-lg > * + * {
     margin-top: var(--space-8);
   }

   .flex {
     display: flex;
   }

   .flex-col {
     display: flex;
     flex-direction: column;
   }

   .items-center {
     align-items: center;
   }

   .justify-between {
     justify-content: space-between;
   }

   .gap-2 { gap: var(--space-2); }
   .gap-4 { gap: var(--space-4); }
   .gap-6 { gap: var(--space-6); }
   .gap-8 { gap: var(--space-8); }

   .grid {
     display: grid;
   }

   .grid-cols-1 {
     grid-template-columns: 1fr;
   }

   @media (min-width: 768px) {
     .md\:grid-cols-2 {
       grid-template-columns: repeat(2, 1fr);
     }
   }

   @media (min-width: 1024px) {
     .lg\:grid-cols-3 {
       grid-template-columns: repeat(3, 1fr);
     }
   }

   .text-center {
     text-align: center;
   }

   .visually-hidden {
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

2. Verify file ends with single trailing newline.

**Tests to write:**
Manual visual verification:
- Test case 1: Add `<div class="container"><p>Text</p></div>` inside `<body>` and verify the div is centered horizontally and never wider than 1280px.
- Test case 2: Resize viewport from 375px to 1440px and verify `.container` horizontal padding is 1.5rem (375-767), 2rem (768-1023), 3rem (1024+).
- Test case 3: Add `<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3"><div>1</div><div>2</div><div>3</div></div>` and resize viewport — verify column count changes at 768px and 1024px breakpoints.
- Test case 4: Apply `.visually-hidden` to an element and verify it is invisible but readable by screen readers (use VoiceOver or NVDA briefly to confirm).

**Acceptance criteria:**
- `.container` centers content with max-width 1280px
- `.container` horizontal padding adjusts at 768px and 1024px breakpoints
- `.section` applies vertical padding of `--section-padding-y` (6rem)
- `.grid-cols-1`, `.md:grid-cols-2`, `.lg:grid-cols-3` produce 1/2/3 columns at correct breakpoints
- `.visually-hidden` removes element from visual layout but keeps it accessible
- No console errors; CSS validates as well-formed

---

### task: css-components-buttons-cards

**Goal:** Implement reusable component styles (buttons, cards, code blocks, copy widgets, toast states) consumed by all sections.

**Context:**
Components are theme-consuming primitives. Buttons follow primary/secondary patterns; primary uses `--color-accent`. Feature cards have hover lift effect:
```css
.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 212, 255, 0.12);
  border-color: rgba(0, 212, 255, 0.3);
}
```

Copy-to-clipboard button has two states: default (shows code text + ⎘ icon) and `.is-copied` (icon swaps to ✓, background shifts to `--color-accent-dim`, "Copied!" text appears via `::after` for 2000ms).

All interactive elements must have visible focus states (WCAG 2.1 AA). Touch targets ≥44×44px for mobile.

Reveal pattern for `[data-reveal]` elements:
```
opacity: 0; transform: translateY(20px); transition: opacity 0.5s ease, transform 0.5s ease;
```
On `.is-revealed`: `opacity: 1; transform: translateY(0);`

**Files to create/modify:**
- `landingpage/assets/css/components.css` — buttons, cards, code blocks, copy widgets, reveal base

**Implementation steps:**
1. Populate `landingpage/assets/css/components.css`:
   ```css
   /* components.css */

   /* ---- Buttons ---- */
   .btn {
     display: inline-flex;
     align-items: center;
     justify-content: center;
     gap: var(--space-2);
     min-height: 44px;
     padding: var(--space-3) var(--space-6);
     border-radius: var(--radius-md);
     font-family: var(--font-display);
     font-weight: 600;
     font-size: var(--text-body);
     text-decoration: none;
     transition: background-color var(--duration-hover) ease,
                 border-color var(--duration-hover) ease,
                 color var(--duration-hover) ease,
                 transform var(--duration-hover) ease;
   }

   .btn:focus-visible {
     outline: 2px solid var(--color-accent);
     outline-offset: 2px;
   }

   .btn--primary {
     background-color: var(--color-accent);
     color: var(--color-bg-base);
     border: 1px solid var(--color-accent);
   }

   .btn--primary:hover {
     background-color: transparent;
     color: var(--color-accent);
   }

   .btn--secondary {
     background-color: transparent;
     color: var(--color-text);
     border: 1px solid var(--color-border);
   }

   .btn--secondary:hover {
     border-color: var(--color-border-hover);
     color: var(--color-accent);
   }

   /* ---- Cards ---- */
   .card {
     background-color: var(--color-bg-mid);
     border: 1px solid var(--color-border);
     border-radius: var(--radius-lg);
     padding: var(--space-6);
   }

   .feature-card {
     background-color: var(--color-bg-mid);
     border: 1px solid var(--color-border);
     border-radius: var(--radius-lg);
     padding: var(--space-6);
     transition: transform var(--duration-hover) ease,
                 box-shadow var(--duration-hover) ease,
                 border-color var(--duration-hover) ease;
   }

   .feature-card:hover {
     transform: translateY(-4px);
     box-shadow: var(--shadow-hover);
     border-color: var(--color-border-hover);
   }

   .feature-card__icon {
     width: 32px;
     height: 32px;
     color: var(--color-accent);
     margin-bottom: var(--space-4);
   }

   .feature-card__title {
     font-size: var(--text-h3);
     font-weight: 600;
     margin-bottom: var(--space-3);
     color: var(--color-text);
   }

   .feature-card__desc {
     color: var(--color-text-dim);
     font-size: var(--text-body);
     line-height: 1.6;
   }

   /* ---- Code blocks ---- */
   .code-inline {
     font-family: var(--font-mono);
     font-size: var(--text-sm);
     color: var(--color-accent);
   }

   /* ---- Copy command widget ---- */
   .copy-cmd {
     display: inline-flex;
     align-items: center;
     gap: var(--space-3);
     min-height: 44px;
     padding: var(--space-3) var(--space-4);
     background-color: var(--color-bg-mid);
     border: 1px solid var(--color-border);
     border-radius: var(--radius-md);
     font-family: var(--font-mono);
     font-size: var(--text-sm);
     color: var(--color-text);
     cursor: pointer;
     transition: background-color var(--duration-hover) ease,
                 border-color var(--duration-hover) ease;
     position: relative;
   }

   .copy-cmd:hover {
     border-color: var(--color-border-hover);
   }

   .copy-cmd:focus-visible {
     outline: 2px solid var(--color-accent);
     outline-offset: 2px;
   }

   .copy-cmd code {
     font-family: inherit;
     color: inherit;
     background: none;
   }

   .copy-cmd__icon {
     width: 16px;
     height: 16px;
     color: var(--color-text-dim);
     transition: color var(--duration-hover) ease;
     flex-shrink: 0;
   }

   .copy-cmd.is-copied {
     background-color: var(--color-accent-dim);
     border-color: var(--color-border-hover);
   }

   .copy-cmd.is-copied .copy-cmd__icon {
     color: var(--color-accent);
   }

   .copy-cmd.is-copied::after {
     content: attr(data-copy-feedback, 'Copied!');
     position: absolute;
     top: -2.25rem;
     left: 50%;
     transform: translateX(-50%);
     padding: var(--space-1) var(--space-3);
     background-color: var(--color-accent);
     color: var(--color-bg-base);
     border-radius: var(--radius-sm);
     font-family: var(--font-display);
     font-size: var(--text-xs);
     font-weight: 600;
     white-space: nowrap;
     pointer-events: none;
   }

   /* ---- Reveal base ---- */
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

   /* When JS is not loaded or reduced-motion, render at final state */
   :root:not(.js-loaded) [data-reveal],
   :root.no-motion [data-reveal] {
     opacity: 1;
     transform: none;
   }

   /* ---- Noscript notice ---- */
   .noscript-notice {
     padding: var(--space-3) var(--space-4);
     background-color: var(--color-bg-mid);
     color: var(--color-text-dim);
     text-align: center;
     font-size: var(--text-sm);
     border-bottom: 1px solid var(--color-border);
   }
   ```

2. Verify file ends with single trailing newline.

**Tests to write:**
Manual visual verification:
- Test case 1: Add `<a class="btn btn--primary" href="#">Test</a>` to body, hover and verify background inverts (cyan → transparent, text inverts).
- Test case 2: Add `<button class="btn btn--secondary">Test</button>`, tab to it with keyboard and verify a 2px cyan focus ring appears with 2px offset.
- Test case 3: Add `<div class="feature-card"><h3 class="feature-card__title">Test</h3><p class="feature-card__desc">Desc</p></div>`, hover and verify card lifts 4px, accent shadow appears, border becomes cyan-tinted.
- Test case 4: Add `<button class="copy-cmd" data-copy-feedback="Copied!"><code>$ test</code></button>`, manually toggle the `is-copied` class via DevTools and verify background turns cyan-dim, "Copied!" tooltip appears above.
- Test case 5: Add `<div data-reveal>Test</div>` and verify it starts at `opacity: 0` and `translateY(20px)`. Add `is-revealed` class via DevTools and verify it transitions to fully visible.
- Test case 6: Without `class="js-loaded"` on `<html>`, verify `[data-reveal]` elements render at full opacity (graceful degradation).

**Acceptance criteria:**
- `.btn--primary` shows cyan background with dark text, inverts on hover
- `.btn--secondary` shows transparent background with thin border, accent on hover
- All buttons have visible focus rings via `:focus-visible`
- Touch targets are ≥44px in height (verify via DevTools computed styles)
- `.feature-card:hover` lifts the card 4px with accent glow
- `.copy-cmd.is-copied` shows accent-dim background and tooltip with `data-copy-feedback` text
- `[data-reveal]` elements start hidden, become visible when `.is-revealed` is added
- Without `.js-loaded` on `<html>`, `[data-reveal]` elements are visible by default (no-JS fallback)

---

### task: html-skeleton-and-meta

**Goal:** Build the complete `index.html` document with semantic structure, head metadata (SEO/OG/Twitter), CSS link tags in correct cascade order, and the deferred ES module script tag.

**Context:**
Single-file HTML, ~400-500 lines. Sections: header, hero, how-it-works, features, pipeline, cta, footer. CSS load order is fixed: reset → tokens → layout → components → sections. JS uses `<script type="module" src="assets/js/main.js" defer>`. All paths relative for `file://` and GitHub Pages compatibility.

Required head metadata:
- `<meta charset="UTF-8">`, viewport, title, description
- Open Graph: `og:type`, `og:title`, `og:description`, `og:image`, `og:url`
- Twitter Card: `twitter:card=summary_large_image`, twitter:title/description/image
- Canonical URL
- Favicon links (ico, svg, apple-touch-icon)
- `<link rel="canonical" href="https://github.com/onpaj/AgentHarness">`

Required body structure:
- `<noscript>` notice immediately after `<body>` open
- `<header>` with sticky nav (wordmark + GitHub CTA)
- `<main>` with sections `#hero`, `#how-it-works`, `#features`, `#pipeline`, `#cta`
- `<footer>`
- `<body>` has `data-repo-url="https://github.com/onpaj/AgentHarness"` attribute

The page is dark-only by design. `<html lang="en">`. Body has `data-repo-url` so JS can project the URL into all CTA hrefs.

**Files to create/modify:**
- `landingpage/index.html` — complete document structure (sections will be empty `<section>` shells with comments; later tasks fill content)

**Implementation steps:**
1. Replace `landingpage/index.html` content with the full skeleton:
   ```html
   <!DOCTYPE html>
   <html lang="en">
   <head>
     <meta charset="UTF-8">
     <meta name="viewport" content="width=device-width, initial-scale=1.0">
     <title>AgentHarness — Delegate the grind. Reclaim your time.</title>
     <meta name="description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
     <link rel="canonical" href="https://github.com/onpaj/AgentHarness">

     <!-- Open Graph -->
     <meta property="og:type" content="website">
     <meta property="og:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
     <meta property="og:description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
     <meta property="og:image" content="assets/img/og-image.png">
     <meta property="og:url" content="https://github.com/onpaj/AgentHarness">

     <!-- Twitter Card -->
     <meta name="twitter:card" content="summary_large_image">
     <meta name="twitter:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
     <meta name="twitter:description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
     <meta name="twitter:image" content="assets/img/og-image.png">

     <!-- Favicon -->
     <link rel="icon" type="image/x-icon" href="assets/img/favicon.ico">
     <link rel="icon" type="image/svg+xml" href="assets/img/favicon.svg">
     <link rel="apple-touch-icon" href="assets/img/apple-touch-icon.png">

     <!-- Stylesheets (cascade order) -->
     <link rel="stylesheet" href="assets/css/reset.css">
     <link rel="stylesheet" href="assets/css/tokens.css">
     <link rel="stylesheet" href="assets/css/layout.css">
     <link rel="stylesheet" href="assets/css/components.css">
     <link rel="stylesheet" href="assets/css/sections.css">
   </head>
   <body data-repo-url="https://github.com/onpaj/AgentHarness">
     <noscript>
       <div class="noscript-notice">
         JavaScript is disabled — animations are off, but all content and links work normally.
       </div>
     </noscript>

     <header class="site-header">
       <!-- Header content filled by section task -->
     </header>

     <main>
       <section id="hero" class="hero section">
         <!-- Hero content filled by section task -->
       </section>

       <section id="how-it-works" class="how-it-works section">
         <!-- How-it-works content filled by section task -->
       </section>

       <section id="features" class="features section">
         <!-- Features content filled by section task -->
       </section>

       <section id="pipeline" class="pipeline section">
         <!-- Pipeline content filled by section task -->
       </section>

       <section id="cta" class="cta section">
         <!-- CTA content filled by section task -->
       </section>
     </main>

     <footer class="site-footer">
       <!-- Footer content filled by section task -->
     </footer>

     <script type="module" src="assets/js/main.js" defer></script>
   </body>
   </html>
   ```

2. Confirm the file uses LF line endings and ends with a single newline.

**Tests to write:**
Manual verification:
- Test case 1: Open `landingpage/index.html` in Chrome and check the document title is "AgentHarness — Delegate the grind. Reclaim your time."
- Test case 2: View page source and verify the five `<link rel="stylesheet">` tags appear in the order: reset, tokens, layout, components, sections.
- Test case 3: In DevTools, inspect `<body>` and confirm `data-repo-url` attribute equals `https://github.com/onpaj/AgentHarness`.
- Test case 4: Disable JS in DevTools and reload. The `<noscript>` notice should display at the top of the page.
- Test case 5: Verify HTML validates via the W3C validator (paste the file content into validator.w3.org/nu/) — expect zero errors.
- Test case 6: Use a meta-tag inspector (e.g., metatags.io) by serving the page locally — confirm OG and Twitter Card metadata is detected.

**Acceptance criteria:**
- `index.html` is valid HTML5 (passes W3C validator)
- All five CSS files are linked in correct cascade order
- Document has proper semantic structure: `<header>`, `<main>`, `<section>` × 5, `<footer>`
- All meta tags (OG, Twitter, canonical, favicon) are present
- `<html lang="en">` and `<body data-repo-url="...">` are set
- `<script type="module" src="assets/js/main.js" defer>` is the only script tag
- `<noscript>` notice displays when JS is disabled
- No console errors when opened in Chrome, Firefox, or Safari

---

### task: js-motion-module

**Goal:** Implement `motion.js` to detect `prefers-reduced-motion`, set the `.no-motion` class on `<html>`, and expose helpers for other modules to gate animations.

**Context:**
NFR-3: Respects `prefers-reduced-motion: reduce`. When reduced motion is preferred, page shows a static representative frame of all animations — no scroll reveals (elements appear in final state immediately), no hero animation, no terminal streaming.

`motion.js` is the central source of truth — `animations.js` and other modules import `prefersReducedMotion()` to gate their behavior. The `:root.no-motion *` CSS selector (already defined in `tokens.css`) is the safety net that disables all transitions/animations globally.

JS module contract:
```js
// motion.js
export const prefersReducedMotion: () => boolean
export const initMotionGate: () => void
//   Sets .no-motion on <html> if reduced motion preferred.
//   Listens for preference change and toggles class.
export const onMotionPreferenceChange: (cb: (reduced: boolean) => void) => void
```

**Files to create/modify:**
- `landingpage/assets/js/motion.js` — motion preference detection and gating

**Implementation steps:**
1. Replace `landingpage/assets/js/motion.js` with:
   ```js
   // motion.js — prefers-reduced-motion gate

   const MEDIA_QUERY = '(prefers-reduced-motion: reduce)';

   const getMediaQueryList = () => window.matchMedia(MEDIA_QUERY);

   export const prefersReducedMotion = () => getMediaQueryList().matches;

   const applyMotionClass = (reduced) => {
     const root = document.documentElement;
     if (reduced) {
       root.classList.add('no-motion');
     } else {
       root.classList.remove('no-motion');
     }
   };

   export const initMotionGate = () => {
     const mql = getMediaQueryList();
     applyMotionClass(mql.matches);
     const handler = (event) => applyMotionClass(event.matches);
     if (typeof mql.addEventListener === 'function') {
       mql.addEventListener('change', handler);
     } else if (typeof mql.addListener === 'function') {
       mql.addListener(handler);
     }
   };

   export const onMotionPreferenceChange = (cb) => {
     const mql = getMediaQueryList();
     const handler = (event) => cb(event.matches);
     if (typeof mql.addEventListener === 'function') {
       mql.addEventListener('change', handler);
     } else if (typeof mql.addListener === 'function') {
       mql.addListener(handler);
     }
   };
   ```

2. Verify file ends with single trailing newline.

**Tests to write:**
Manual verification (no automated JS test framework set up for static page):
- Test case 1: In Chrome DevTools, open the Rendering panel (More tools → Rendering). Set "Emulate CSS prefers-reduced-motion" to "reduce". Open `index.html`, then in console run `document.documentElement.classList.contains('no-motion')`. Expected: `true`.
- Test case 2: With emulation set to "no-preference", reload. Console: `document.documentElement.classList.contains('no-motion')`. Expected: `false`.
- Test case 3: With emulation set to "no-preference", in console execute:
   ```js
   import('./assets/js/motion.js').then(m => console.log(m.prefersReducedMotion()))
   ```
   Expected: `false`. Switch emulation to "reduce" and re-run — expected: `true`.
- Test case 4: Toggle emulation between "reduce" and "no-preference" while page is open and verify the `.no-motion` class on `<html>` toggles in real time (DevTools Elements panel).

**Acceptance criteria:**
- Calling `prefersReducedMotion()` returns `true` when OS/browser reduced-motion preference is on, `false` otherwise
- `initMotionGate()` adds `.no-motion` class to `<html>` immediately when reduced motion is preferred
- The class toggles automatically when the user changes their preference at runtime
- `onMotionPreferenceChange(cb)` invokes the callback with the new `reduced` boolean when preference changes
- No console errors in any browser
- Module exports are accessible via `import { prefersReducedMotion, initMotionGate, onMotionPreferenceChange } from './motion.js'`

---

### task: js-copy-module

**Goal:** Implement `copy.js` to handle click-to-copy on `[data-copy]` elements with Clipboard API + execCommand fallback and visual confirmation.

**Context:**
Copy interaction:
```
1. Read element.dataset.copy
2. copyToClipboard(text):
     try navigator.clipboard.writeText(text)
     catch: execCommand fallback (textarea + selection + document.execCommand('copy'))
3. Add .is-copied to element
4. setTimeout 2000ms → remove .is-copied
```

The `.is-copied` class triggers visual feedback (cyan-dim background, ✓ icon swap, "Copied!" tooltip via `::after`) — already implemented in `components.css`. Tooltip text comes from `data-copy-feedback` attribute or defaults to "Copied!".

Clipboard API requires HTTPS or localhost. For `file://` users, we need execCommand fallback.

JS module contract:
```js
// copy.js
export const initCopyButtons: () => void
//   Wires all [data-copy] elements. Reads data-copy text, copies, shows .is-copied for 2s.
```

**Files to create/modify:**
- `landingpage/assets/js/copy.js` — click-to-copy logic with fallback

**Implementation steps:**
1. Replace `landingpage/assets/js/copy.js` with:
   ```js
   // copy.js — click-to-copy with Clipboard API + execCommand fallback

   const COPIED_DURATION_MS = 2000;
   const DEFAULT_FEEDBACK = 'Copied!';

   const copyViaClipboardApi = async (text) => {
     if (!navigator.clipboard || !navigator.clipboard.writeText) {
       throw new Error('Clipboard API unavailable');
     }
     await navigator.clipboard.writeText(text);
   };

   const copyViaExecCommand = (text) => {
     const textarea = document.createElement('textarea');
     textarea.value = text;
     textarea.setAttribute('readonly', '');
     textarea.style.position = 'fixed';
     textarea.style.opacity = '0';
     textarea.style.pointerEvents = 'none';
     document.body.appendChild(textarea);
     textarea.select();
     let succeeded = false;
     try {
       succeeded = document.execCommand('copy');
     } catch (err) {
       succeeded = false;
     }
     document.body.removeChild(textarea);
     if (!succeeded) {
       throw new Error('execCommand copy failed');
     }
   };

   const copyToClipboard = async (text) => {
     try {
       await copyViaClipboardApi(text);
     } catch (err) {
       copyViaExecCommand(text);
     }
   };

   const ensureFeedbackAttr = (button) => {
     if (!button.hasAttribute('data-copy-feedback')) {
       button.setAttribute('data-copy-feedback', DEFAULT_FEEDBACK);
     }
   };

   const handleCopyClick = async (event) => {
     const button = event.currentTarget;
     const text = button.dataset.copy;
     if (!text) return;
     try {
       await copyToClipboard(text);
     } catch (err) {
       console.warn('Copy failed:', err);
       return;
     }
     ensureFeedbackAttr(button);
     button.classList.add('is-copied');
     if (button._copyTimer) {
       clearTimeout(button._copyTimer);
     }
     button._copyTimer = setTimeout(() => {
       button.classList.remove('is-copied');
       button._copyTimer = null;
     }, COPIED_DURATION_MS);
   };

   export const initCopyButtons = () => {
     const buttons = document.querySelectorAll('[data-copy]');
     buttons.forEach((button) => {
       button.addEventListener('click', handleCopyClick);
     });
   };
   ```

2. Verify file ends with single trailing newline.

**Tests to write:**
Manual verification:
- Test case 1: Add `<button class="copy-cmd" data-copy="hello world"><code>hello world</code></button>` to body. Click and paste into a text editor — verify "hello world" is pasted.
- Test case 2: After clicking, verify the button gains `is-copied` class. Wait 2 seconds and verify class is removed.
- Test case 3: Open page via `file://` protocol. Click the copy button — verify execCommand fallback is used and clipboard still receives the text. (Confirm by paste.)
- Test case 4: Add a button with `data-copy-feedback="Yay!"` and click. The CSS tooltip should display "Yay!" text.
- Test case 5: Click two different copy buttons in quick succession. Only the second one should remain in `is-copied` state after 2 seconds (each manages its own timer).
- Test case 6: With `data-copy=""` (empty string) click — verify no copy attempt is made and no `is-copied` class is applied.

**Acceptance criteria:**
- Clicking any `[data-copy]` element copies its `data-copy` value to the clipboard
- Works in HTTPS/localhost contexts via Clipboard API
- Works in `file://` context via execCommand fallback
- `.is-copied` class is added on success and removed after 2000ms
- `data-copy-feedback` attribute is honored by CSS tooltip (default "Copied!" when omitted)
- Multiple rapid clicks on the same element reset the timer correctly
- No console errors during normal operation; warning logged on failure

---

### task: js-animations-module

**Goal:** Implement `animations.js` to handle scroll-triggered reveals, hero SVG visibility-based pause/resume, and pipeline terminal animation re-trigger.

**Context:**
IntersectionObserver options per arch-review FR-6 amendment: `rootMargin: '0px 0px -10% 0px'`, `threshold: 0.15`. Each observer disconnects per-element after first trigger (one-shot for reveals).

Hero animation pauses on `document.visibilitychange` by toggling `--hero-play-state` CSS custom property between `running` and `paused`. CSS animation reads `animation-play-state: var(--hero-play-state)`.

Pipeline animation differs from one-shot reveals: it restarts every time `#pipeline` re-enters the viewport. The terminal lines have CSS animations driven by `animation-delay` increments; restart by removing then re-adding a class.

When `prefersReducedMotion()` is true:
- `initReveals()` adds `.is-revealed` to all `[data-reveal]` immediately, skips observer
- `initHeroAnimation()` skips entirely (CSS `:root.no-motion *` already disables animation)
- `initPipelineAnimation()` shows all lines immediately, no blink

JS module contract:
```js
export const initReveals: (options?) => void
export const initHeroAnimation: () => void
export const initPipelineAnimation: () => void
```

The `data-reveal-delay` attribute (in ms) sets `transition-delay` for staggered reveals.

**Files to create/modify:**
- `landingpage/assets/js/animations.js` — IntersectionObserver reveals, hero lifecycle, pipeline restart

**Implementation steps:**
1. Replace `landingpage/assets/js/animations.js` with:
   ```js
   // animations.js — IntersectionObserver reveals, hero lifecycle, pipeline restart

   import { prefersReducedMotion } from './motion.js';

   const DEFAULT_OBSERVER_OPTIONS = {
     rootMargin: '0px 0px -10% 0px',
     threshold: 0.15,
   };

   const HERO_PLAY_PROP = '--hero-play-state';
   const PIPELINE_VISIBLE_CLASS = 'is-running';

   const applyRevealDelay = (element) => {
     const delay = element.dataset.revealDelay;
     if (!delay) return;
     element.style.transitionDelay = `${delay}ms`;
   };

   const revealAll = (elements) => {
     elements.forEach((element) => {
       applyRevealDelay(element);
       element.classList.add('is-revealed');
     });
   };

   export const initReveals = (options = {}) => {
     const observerOptions = { ...DEFAULT_OBSERVER_OPTIONS, ...options };
     const targets = document.querySelectorAll('[data-reveal]');
     if (targets.length === 0) return;

     if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
       revealAll(targets);
       return;
     }

     const observer = new IntersectionObserver((entries, obs) => {
       entries.forEach((entry) => {
         if (!entry.isIntersecting) return;
         applyRevealDelay(entry.target);
         entry.target.classList.add('is-revealed');
         obs.unobserve(entry.target);
       });
     }, observerOptions);

     targets.forEach((target) => observer.observe(target));
   };

   const setHeroPlayState = (state) => {
     document.documentElement.style.setProperty(HERO_PLAY_PROP, state);
   };

   export const initHeroAnimation = () => {
     if (prefersReducedMotion()) return;
     setHeroPlayState('running');
     document.addEventListener('visibilitychange', () => {
       setHeroPlayState(document.hidden ? 'paused' : 'running');
     });
   };

   const restartPipelineLines = (container) => {
     const lines = container.querySelectorAll('.pipeline-line');
     lines.forEach((line) => {
       line.classList.remove('pipeline-line--visible');
     });
     // Force reflow so re-adding the class restarts the animation
     // eslint-disable-next-line no-unused-expressions
     container.offsetWidth;
     lines.forEach((line) => {
       line.classList.add('pipeline-line--visible');
     });
   };

   export const initPipelineAnimation = () => {
     const pipeline = document.querySelector('#pipeline');
     if (!pipeline) return;
     const terminal = pipeline.querySelector('.pipeline-terminal');
     if (!terminal) return;

     if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
       const lines = terminal.querySelectorAll('.pipeline-line');
       lines.forEach((line) => line.classList.add('pipeline-line--visible'));
       return;
     }

     const observer = new IntersectionObserver((entries) => {
       entries.forEach((entry) => {
         if (entry.isIntersecting) {
           restartPipelineLines(terminal);
           terminal.classList.add(PIPELINE_VISIBLE_CLASS);
         } else {
           terminal.classList.remove(PIPELINE_VISIBLE_CLASS);
         }
       });
     }, DEFAULT_OBSERVER_OPTIONS);

     observer.observe(pipeline);
   };
   ```

2. Verify file ends with single trailing newline.

**Tests to write:**
Manual verification:
- Test case 1: Add `<div data-reveal style="height:100px;background:red"></div>` 200vh down the page. Reload, scroll down — at 85% viewport (10% rootMargin), the element should fade in and `is-revealed` class should appear in DevTools.
- Test case 2: Add `<div data-reveal data-reveal-delay="300" style="height:100px"></div>` and verify on reveal that `transition-delay: 300ms` is set on the element via inline style.
- Test case 3: With reduced-motion enabled (DevTools rendering panel), reload. All `[data-reveal]` elements should have `is-revealed` immediately on load (no observer used).
- Test case 4: Confirm `--hero-play-state` is `running` on `:root` after page load. Switch to another tab, switch back — verify the property toggles to `paused` then `running`.
- Test case 5: With pipeline section visible, scroll away (so `#pipeline` exits viewport), then scroll back. Verify pipeline lines restart their animations (each line should re-stream in).
- Test case 6: Verify after a reveal fires, the element is no longer observed (scroll-up-and-back should not re-trigger any animation; the class persists).

**Acceptance criteria:**
- All `[data-reveal]` elements gain `.is-revealed` when entering viewport (with rootMargin -10% bottom, threshold 0.15)
- Each `[data-reveal]` is unobserved after first reveal (one-shot)
- `data-reveal-delay="N"` adds `transition-delay: Nms` inline
- `initHeroAnimation()` sets `--hero-play-state: running` on load and toggles between `running`/`paused` on `visibilitychange`
- `initPipelineAnimation()` restarts terminal lines when `#pipeline` enters viewport (re-trigger)
- When `prefersReducedMotion()` returns true, all elements appear in final state immediately and no observer is created
- No console errors

---

### task: js-main-orchestrator

**Goal:** Implement `main.js` to orchestrate module initialization, set the `js-loaded` class on `<html>`, project repo URL into CTAs, and wire up the page on `DOMContentLoaded`.

**Context:**
`main.js` is the only orchestrator imported via `<script type="module" src="assets/js/main.js" defer>`. It:
1. Sets `js-loaded` class on `<html>` (so `[data-reveal]` initial-hidden state applies; without this, no-JS users see content at full opacity).
2. Initializes motion gate FIRST (before reveals run, so reveals can check reduced motion preference).
3. Initializes reveals, hero, pipeline animation, copy buttons.
4. Projects `REPO_URL` and `QUICKSTART_CMD` into elements with `[data-repo-url]` and `[data-quickstart-cmd]` attributes — single source of truth.

Since `<script type="module">` is deferred by default, the script runs after parsing. We can wire up immediately or wait for `DOMContentLoaded` (already fired for deferred modules — use immediate execution).

Constants:
```js
const REPO_URL = 'https://github.com/onpaj/AgentHarness';
const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';
```

Projection contract:
- Any element with `[data-repo-url]` (other than `<body>`) gets its `href` (if `<a>`) or `data-copy` set to `REPO_URL`. `<body data-repo-url="...">` already has the value but other elements may use `[data-repo-url=""]` as a marker.
- Any element with `[data-quickstart-cmd]` gets its `data-copy` set to `QUICKSTART_CMD` and its inner code text content set to `$ ` + `QUICKSTART_CMD`.

This way, if URL or command changes, only `main.js` needs editing.

**Files to create/modify:**
- `landingpage/assets/js/main.js` — entry orchestrator

**Implementation steps:**
1. Replace `landingpage/assets/js/main.js` with:
   ```js
   // main.js — entry orchestrator

   import { initMotionGate } from './motion.js';
   import {
     initReveals,
     initHeroAnimation,
     initPipelineAnimation,
   } from './animations.js';
   import { initCopyButtons } from './copy.js';

   const REPO_URL = 'https://github.com/onpaj/AgentHarness';
   const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';

   const projectRepoUrl = () => {
     const elements = document.querySelectorAll('[data-repo-url]');
     elements.forEach((element) => {
       if (element.tagName === 'BODY') return;
       if (element.tagName === 'A') {
         element.setAttribute('href', REPO_URL);
       }
       if (element.hasAttribute('data-copy')) {
         element.setAttribute('data-copy', REPO_URL);
       }
     });
   };

   const projectQuickstart = () => {
     const elements = document.querySelectorAll('[data-quickstart-cmd]');
     elements.forEach((element) => {
       element.setAttribute('data-copy', QUICKSTART_CMD);
       const codeNode = element.querySelector('code');
       if (codeNode) {
         codeNode.textContent = `$ ${QUICKSTART_CMD}`;
       }
     });
   };

   const markJsLoaded = () => {
     document.documentElement.classList.add('js-loaded');
   };

   const init = () => {
     markJsLoaded();
     initMotionGate();
     projectRepoUrl();
     projectQuickstart();
     initReveals();
     initHeroAnimation();
     initPipelineAnimation();
     initCopyButtons();
   };

   if (document.readyState === 'loading') {
     document.addEventListener('DOMContentLoaded', init);
   } else {
     init();
   }
   ```

2. Verify file ends with single trailing newline.

**Tests to write:**
Manual verification:
- Test case 1: Open `index.html` in Chrome and check console for errors. Verify `<html>` has `js-loaded` class via Elements panel.
- Test case 2: Add `<a data-repo-url href="">Test</a>` to body, reload. Verify the `href` attribute is set to `https://github.com/onpaj/AgentHarness`.
- Test case 3: Add `<button data-quickstart-cmd data-copy=""><code></code></button>`, reload. Verify `data-copy` becomes the quick-start command and the `<code>` text is `$ pip install agentharness && agentharness brainstorm`.
- Test case 4: Click the projected `data-quickstart-cmd` button — verify clipboard receives the quick-start command (paste to confirm).
- Test case 5: With `<body data-repo-url="...">`, verify the body's attribute is NOT mutated by the projection logic.
- Test case 6: Disable JS in DevTools and reload — verify `js-loaded` class is NOT on `<html>`, all `[data-reveal]` elements are visible (graceful degradation).

**Acceptance criteria:**
- `js-loaded` class is added to `<html>` immediately on page load (when JS executes)
- All `[data-repo-url]` elements (except `<body>`) have their href/data-copy set to `https://github.com/onpaj/AgentHarness`
- All `[data-quickstart-cmd]` elements have `data-copy` set to the quick-start command and inner `<code>` shows `$ pip install agentharness && agentharness brainstorm`
- `initMotionGate()` runs before reveals so reduced-motion users get correct behavior
- All five init functions are called in correct order
- No console errors
- Without JS: `js-loaded` class absent, `[data-reveal]` elements still visible (no-JS fallback works)

---

### task: section-header-and-footer

**Goal:** Implement the sticky header (wordmark + GitHub CTA) and the footer (links, license, wordmark) with their CSS.

**Context:**
Header is sticky with transparent background that gains `backdrop-filter: blur(12px)` when scrolled past hero. Wordmark on left, single "View on GitHub ↗" button on right. On mobile, button may collapse to icon-only with `aria-label`.

Footer has: project tagline, GitHub link, MIT license note, AgentHarness wordmark/typographic mark.

External links use `rel="noopener noreferrer"` and `target="_blank"`.

The arch review specified that all repo URLs centralize via `[data-repo-url]` attributes; `main.js` populates `href` at runtime.

**Files to create/modify:**
- `landingpage/index.html` — fill `<header class="site-header">` and `<footer class="site-footer">` blocks
- `landingpage/assets/css/sections.css` — append header and footer styles

**Implementation steps:**
1. In `landingpage/index.html`, replace the contents of `<header class="site-header">` with:
   ```html
   <div class="container site-header__inner">
     <a href="#" class="site-header__brand" aria-label="AgentHarness home">
       <span class="site-header__wordmark">AgentHarness</span>
     </a>
     <nav class="site-header__nav">
       <a class="btn btn--secondary site-header__cta"
          data-repo-url
          href=""
          target="_blank"
          rel="noopener noreferrer">
         <span>View on GitHub</span>
         <span aria-hidden="true">↗</span>
       </a>
     </nav>
   </div>
   ```

2. In `landingpage/index.html`, replace the contents of `<footer class="site-footer">` with:
   ```html
   <div class="container site-footer__inner">
     <div class="site-footer__brand">
       <span class="site-footer__wordmark">AgentHarness</span>
       <span class="site-footer__tagline">Delegate the grind. Reclaim your time.</span>
     </div>
     <ul class="site-footer__links">
       <li>
         <a data-repo-url
            href=""
            target="_blank"
            rel="noopener noreferrer">GitHub</a>
       </li>
       <li>
         <span class="site-footer__license">MIT License</span>
       </li>
     </ul>
   </div>
   ```

3. Append the following to `landingpage/assets/css/sections.css`:
   ```css
   /* sections.css */

   /* ---- Header ---- */
   .site-header {
     position: sticky;
     top: 0;
     z-index: 100;
     background-color: rgba(10, 15, 30, 0.6);
     backdrop-filter: blur(12px);
     -webkit-backdrop-filter: blur(12px);
     border-bottom: 1px solid var(--color-border);
   }

   .site-header__inner {
     display: flex;
     align-items: center;
     justify-content: space-between;
     min-height: 64px;
     padding-block: var(--space-3);
   }

   .site-header__brand {
     display: inline-flex;
     align-items: center;
     gap: var(--space-2);
     color: var(--color-text);
     text-decoration: none;
   }

   .site-header__wordmark {
     font-family: var(--font-display);
     font-weight: 700;
     font-size: 1.125rem;
     letter-spacing: -0.01em;
   }

   .site-header__cta {
     padding: var(--space-2) var(--space-4);
     min-height: 40px;
     font-size: var(--text-sm);
   }

   /* ---- Footer ---- */
   .site-footer {
     border-top: 1px solid var(--color-border);
     padding-block: var(--space-12);
     color: var(--color-text-dim);
   }

   .site-footer__inner {
     display: flex;
     flex-direction: column;
     gap: var(--space-4);
     align-items: center;
     text-align: center;
   }

   @media (min-width: 768px) {
     .site-footer__inner {
       flex-direction: row;
       justify-content: space-between;
       align-items: center;
       text-align: left;
     }
   }

   .site-footer__brand {
     display: flex;
     flex-direction: column;
     gap: var(--space-1);
   }

   .site-footer__wordmark {
     font-family: var(--font-display);
     font-weight: 700;
     color: var(--color-text);
   }

   .site-footer__tagline {
     font-size: var(--text-sm);
   }

   .site-footer__links {
     display: flex;
     gap: var(--space-6);
     align-items: center;
   }

   .site-footer__links a {
     color: var(--color-text-dim);
     transition: color var(--duration-hover) ease;
   }

   .site-footer__links a:hover {
     color: var(--color-accent);
   }

   .site-footer__links a:focus-visible {
     outline: 2px solid var(--color-accent);
     outline-offset: 2px;
   }
   ```

**Tests to write:**
Manual verification:
- Test case 1: Open `index.html`. Header should display with wordmark "AgentHarness" on left and "View on GitHub ↗" button on right. Background semi-transparent dark with blur.
- Test case 2: Scroll down — header remains sticky at top with backdrop blur visible over content beneath.
- Test case 3: Hover the GitHub CTA — border should turn cyan-tinted.
- Test case 4: Click the GitHub CTA — should open `https://github.com/onpaj/AgentHarness` in a new tab. Verify `target="_blank"` and `rel="noopener noreferrer"` on the link.
- Test case 5: Resize to 375px — header should still display wordmark + CTA without horizontal overflow. Verify nothing wraps awkwardly.
- Test case 6: Footer should display below all sections. On mobile (375px), footer items stack centered. On desktop (≥768px), wordmark+tagline left, links right.
- Test case 7: Check footer GitHub link opens repo in new tab.
- Test case 8: Run Lighthouse accessibility audit — header CTA must have accessible name "View on GitHub" (or similar), footer links must be keyboard-navigable.

**Acceptance criteria:**
- Header is sticky at top with backdrop blur effect
- Header shows wordmark left, "View on GitHub ↗" CTA right
- Footer shows wordmark + tagline and GitHub + MIT License links
- All external links open in new tab with `rel="noopener noreferrer"`
- Header and footer are responsive at 375px and 1440px
- All interactive elements have visible focus states (keyboard-navigable)
- Header CTA `href` is populated by `main.js` to `https://github.com/onpaj/AgentHarness` at runtime
- No horizontal scroll at any breakpoint

---

### task: section-hero

**Goal:** Build the hero section: headline, subheadline, primary CTA, copyable quick-start command, and animated SVG pipeline glyph (six pulsing nodes connected by edges).

**Context:**
Hero fills viewport on desktop (≥1024px) without scroll. Above-the-fold on mobile (≥375px width).

Headline: "Delegate the grind. Reclaim your time."
Subheadline: "A chain of Claude agents builds your features while you focus on what matters."
Primary CTA: "Get started on GitHub" (links to repo).
Secondary: copyable `pip install agentharness && agentharness brainstorm`.

Hero SVG: six nodes (analyst → architect → designer → planner → developer → reviewer), each a `<circle>`. Edges as `<line>` between nodes. CSS keyframe animation pulses each node sequentially (brighten to `--color-accent`, dim back). 6-step loop.

```css
.hero-svg__node { animation: hero-pulse 3.6s linear infinite; animation-play-state: var(--hero-play-state); }
.hero-svg__node:nth-child(1) { animation-delay: 0s; }
.hero-svg__node:nth-child(2) { animation-delay: 0.6s; }
... up to nth-child(6) { animation-delay: 3.0s; }
```

Static frame (reduced-motion): all nodes at 40% opacity, edges fully drawn, no animation property — handled via `:root.no-motion *` from tokens.css already.

Layout: split on desktop (text left, SVG right), stacked on mobile (text top, smaller SVG below).

Quick-start widget uses `data-quickstart-cmd` attribute so `main.js` projects the command.

**Files to create/modify:**
- `landingpage/index.html` — fill `<section id="hero">`
- `landingpage/assets/css/sections.css` — append hero styles

**Implementation steps:**
1. In `landingpage/index.html`, replace contents of `<section id="hero" class="hero section">` with:
   ```html
   <div class="container hero__inner">
     <div class="hero__content">
       <h1 class="hero__headline" data-reveal>Delegate the grind.<br>Reclaim your time.</h1>
       <p class="hero__subheadline" data-reveal data-reveal-delay="100">
         A chain of Claude agents builds your features while you focus on what matters.
       </p>
       <div class="hero__ctas" data-reveal data-reveal-delay="200">
         <a class="btn btn--primary"
            data-repo-url
            href=""
            target="_blank"
            rel="noopener noreferrer">
           <span>Get started on GitHub</span>
           <span aria-hidden="true">↗</span>
         </a>
         <button class="copy-cmd"
                 data-quickstart-cmd
                 data-copy=""
                 data-copy-feedback="Copied!"
                 type="button"
                 aria-label="Copy quick-start command">
           <code>$ pip install agentharness &amp;&amp; agentharness brainstorm</code>
           <svg class="copy-cmd__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
             <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
           </svg>
         </button>
       </div>
     </div>
     <div class="hero__visual" data-reveal data-reveal-delay="150">
       <svg class="hero-svg" viewBox="0 0 600 200" role="img" aria-labelledby="hero-svg-title hero-svg-desc">
         <title id="hero-svg-title">AgentHarness pipeline</title>
         <desc id="hero-svg-desc">Six agents — analyst, architect, designer, planner, developer, reviewer — connected in a pipeline that pulses left to right.</desc>
         <line class="hero-svg__edge" x1="60"  y1="100" x2="160" y2="100"></line>
         <line class="hero-svg__edge" x1="160" y1="100" x2="260" y2="100"></line>
         <line class="hero-svg__edge" x1="260" y1="100" x2="360" y2="100"></line>
         <line class="hero-svg__edge" x1="360" y1="100" x2="460" y2="100"></line>
         <line class="hero-svg__edge" x1="460" y1="100" x2="540" y2="100"></line>
         <circle class="hero-svg__node" cx="60"  cy="100" r="14"></circle>
         <circle class="hero-svg__node" cx="160" cy="100" r="14"></circle>
         <circle class="hero-svg__node" cx="260" cy="100" r="14"></circle>
         <circle class="hero-svg__node" cx="360" cy="100" r="14"></circle>
         <circle class="hero-svg__node" cx="460" cy="100" r="14"></circle>
         <circle class="hero-svg__node" cx="540" cy="100" r="14"></circle>
         <text class="hero-svg__label" x="60"  y="140" text-anchor="middle">analyst</text>
         <text class="hero-svg__label" x="160" y="140" text-anchor="middle">architect</text>
         <text class="hero-svg__label" x="260" y="140" text-anchor="middle">designer</text>
         <text class="hero-svg__label" x="360" y="140" text-anchor="middle">planner</text>
         <text class="hero-svg__label" x="460" y="140" text-anchor="middle">developer</text>
         <text class="hero-svg__label" x="540" y="140" text-anchor="middle">reviewer</text>
       </svg>
     </div>
   </div>
   ```

2. Append to `landingpage/assets/css/sections.css`:
   ```css
   /* ---- Hero ---- */
   .hero {
     min-height: calc(100vh - 64px);
     display: flex;
     align-items: center;
   }

   .hero__inner {
     display: flex;
     flex-direction: column;
     gap: var(--space-12);
     align-items: center;
   }

   @media (min-width: 1024px) {
     .hero__inner {
       flex-direction: row;
       gap: var(--space-16);
     }
     .hero__content,
     .hero__visual {
       flex: 1;
     }
   }

   .hero__headline {
     font-size: var(--text-hero);
     font-weight: 800;
     line-height: 1.05;
     letter-spacing: -0.02em;
     color: var(--color-text);
     margin-bottom: var(--space-6);
   }

   .hero__subheadline {
     font-size: clamp(1.125rem, 1.5vw, 1.25rem);
     line-height: 1.5;
     color: var(--color-text-dim);
     margin-bottom: var(--space-8);
     max-width: 36rem;
   }

   .hero__ctas {
     display: flex;
     flex-direction: column;
     gap: var(--space-4);
     align-items: flex-start;
   }

   @media (min-width: 640px) {
     .hero__ctas {
       flex-direction: row;
       align-items: center;
       flex-wrap: wrap;
     }
   }

   .hero__visual {
     width: 100%;
     max-width: 600px;
   }

   .hero-svg {
     width: 100%;
     height: auto;
   }

   .hero-svg__edge {
     stroke: var(--color-border);
     stroke-width: 2;
   }

   .hero-svg__node {
     fill: var(--color-bg-mid);
     stroke: var(--color-text-dim);
     stroke-width: 2;
     animation: hero-pulse 3.6s linear infinite;
     animation-play-state: var(--hero-play-state);
   }

   .hero-svg__node:nth-of-type(1) { animation-delay: 0s; }
   .hero-svg__node:nth-of-type(2) { animation-delay: 0.6s; }
   .hero-svg__node:nth-of-type(3) { animation-delay: 1.2s; }
   .hero-svg__node:nth-of-type(4) { animation-delay: 1.8s; }
   .hero-svg__node:nth-of-type(5) { animation-delay: 2.4s; }
   .hero-svg__node:nth-of-type(6) { animation-delay: 3.0s; }

   @keyframes hero-pulse {
     0%, 100% {
       fill: var(--color-bg-mid);
       stroke: var(--color-text-dim);
     }
     16% {
       fill: var(--color-accent);
       stroke: var(--color-accent);
     }
     50% {
       fill: var(--color-bg-mid);
       stroke: var(--color-text-dim);
     }
   }

   .hero-svg__label {
     font-family: var(--font-mono);
     font-size: 12px;
     fill: var(--color-text-dim);
   }

   :root.no-motion .hero-svg__node {
     fill: var(--color-bg-mid);
     stroke: var(--color-text-dim);
     opacity: 0.6;
   }

   @media (max-width: 767px) {
     .hero-svg__label {
       display: none;
     }
   }
   ```

**Tests to write:**
Manual verification:
- Test case 1: Open `index.html` at desktop 1280px width. Hero fills the viewport (no scroll needed to see CTA). Text on left, SVG on right.
- Test case 2: Resize to 375px mobile. Headline + subheadline + CTA fit above fold. SVG appears below content, scaled down. Labels are hidden under the SVG nodes on mobile.
- Test case 3: Watch the SVG for 4 seconds — six nodes pulse cyan in left-to-right sequence, each lighting up 0.6s after the previous.
- Test case 4: Switch tabs and back — verify SVG animation pauses while tab is hidden (inspect `--hero-play-state` on `:root` via DevTools).
- Test case 5: Click the copy command — verify `pip install agentharness && agentharness brainstorm` is on clipboard, `is-copied` class appears for 2s with "Copied!" tooltip.
- Test case 6: Click "Get started on GitHub" — verify it opens `https://github.com/onpaj/AgentHarness` in new tab.
- Test case 7: Enable reduced motion in DevTools → reload. SVG nodes are static at ~60% opacity, edges drawn, no pulse animation. Reveal targets show in final state.
- Test case 8: Run Lighthouse — hero animation should not cause CLS (no layout shifts as it loads).
- Test case 9: Tab through hero — focus should move between primary CTA and copy button with visible cyan focus ring.

**Acceptance criteria:**
- Hero fills viewport (≥calc(100vh - 64px)) on desktop without requiring scroll
- All hero content above the fold on mobile (375px)
- Headline uses `clamp()` for fluid scaling
- SVG pipeline glyph displays six nodes pulsing in sequence at ~30fps+
- Animation pauses when tab is backgrounded (via `--hero-play-state`)
- Quick-start command is copyable; click shows visual confirmation
- Primary CTA opens repo in new tab
- Reduced-motion users see static SVG (60% opacity nodes, no animation)
- All elements keyboard-navigable with visible focus states

---

### task: section-how-it-works

**Goal:** Build the three-step "How it works" section showing Brainstorm → Agents work → Code ships with icons, descriptions, staggered reveal animations, and a connecting arrow between steps on desktop.

**Context:**
Three steps appear horizontally on desktop (≥768px), stacked vertically on mobile. Scroll-triggered animation reveals each step sequentially via `data-reveal` and `data-reveal-delay` (0ms, 150ms, 300ms). One-shot per page load.

Connecting line/arrow between steps on desktop animates after step appears. Use `↓` (mobile) or `→` (desktop) glyph or simple SVG line.

Icons via Lucide SVG inline (MIT licensed):
- Step 1: Brainstorm → `message-square`
- Step 2: Agents work → `cpu`
- Step 3: Code ships → `git-pull-request`

Reduced-motion: static layout, all reveals show in final state immediately (handled by `[data-reveal]` reveal logic in animations.js).

**Files to create/modify:**
- `landingpage/index.html` — fill `<section id="how-it-works">`
- `landingpage/assets/css/sections.css` — append how-it-works styles

**Implementation steps:**
1. In `landingpage/index.html`, replace contents of `<section id="how-it-works" class="how-it-works section">` with:
   ```html
   <div class="container">
     <header class="section-heading" data-reveal>
       <h2 class="section-heading__title">How it works</h2>
       <p class="section-heading__subtitle">From brainstorm to shipped code — autonomously.</p>
     </header>
     <ol class="steps">
       <li class="step" data-reveal data-reveal-delay="0">
         <div class="step__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
           </svg>
         </div>
         <h3 class="step__title">1. Brainstorm</h3>
         <p class="step__desc">Describe your feature in conversation. The brainstorm agent shapes it into a brief.</p>
       </li>
       <li class="step__connector" aria-hidden="true">
         <svg viewBox="0 0 40 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
           <line x1="2" y1="12" x2="34" y2="12"></line>
           <polyline points="28,6 36,12 28,18"></polyline>
         </svg>
       </li>
       <li class="step" data-reveal data-reveal-delay="150">
         <div class="step__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
             <rect x="9" y="9" width="6" height="6"></rect>
             <line x1="9" y1="1" x2="9" y2="4"></line>
             <line x1="15" y1="1" x2="15" y2="4"></line>
             <line x1="9" y1="20" x2="9" y2="23"></line>
             <line x1="15" y1="20" x2="15" y2="23"></line>
             <line x1="20" y1="9" x2="23" y2="9"></line>
             <line x1="20" y1="14" x2="23" y2="14"></line>
             <line x1="1" y1="9" x2="4" y2="9"></line>
             <line x1="1" y1="14" x2="4" y2="14"></line>
           </svg>
         </div>
         <h3 class="step__title">2. Agents work</h3>
         <p class="step__desc">Analyst → architect → designer → planner → developer → reviewer. The chain runs autonomously.</p>
       </li>
       <li class="step__connector" aria-hidden="true">
         <svg viewBox="0 0 40 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
           <line x1="2" y1="12" x2="34" y2="12"></line>
           <polyline points="28,6 36,12 28,18"></polyline>
         </svg>
       </li>
       <li class="step" data-reveal data-reveal-delay="300">
         <div class="step__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <circle cx="18" cy="18" r="3"></circle>
             <circle cx="6" cy="6" r="3"></circle>
             <path d="M13 6h3a2 2 0 0 1 2 2v7"></path>
             <line x1="6" y1="9" x2="6" y2="21"></line>
           </svg>
         </div>
         <h3 class="step__title">3. Code ships</h3>
         <p class="step__desc">Implementation lands as a PR or branch. You review, you merge, you move on.</p>
       </li>
     </ol>
   </div>
   ```

2. Append to `landingpage/assets/css/sections.css`:
   ```css
   /* ---- Section heading ---- */
   .section-heading {
     text-align: center;
     margin-bottom: var(--space-16);
     max-width: 40rem;
     margin-inline: auto;
   }

   .section-heading__title {
     font-size: var(--text-h2);
     font-weight: 700;
     letter-spacing: -0.01em;
     margin-bottom: var(--space-3);
   }

   .section-heading__subtitle {
     color: var(--color-text-dim);
     font-size: 1.125rem;
   }

   /* ---- How it works ---- */
   .steps {
     display: flex;
     flex-direction: column;
     gap: var(--space-8);
     align-items: stretch;
   }

   .step {
     flex: 1;
     padding: var(--space-6);
     background-color: var(--color-bg-mid);
     border: 1px solid var(--color-border);
     border-radius: var(--radius-lg);
   }

   .step__icon {
     width: 40px;
     height: 40px;
     color: var(--color-accent);
     margin-bottom: var(--space-4);
   }

   .step__icon svg {
     width: 100%;
     height: 100%;
   }

   .step__title {
     font-size: var(--text-h3);
     font-weight: 600;
     margin-bottom: var(--space-2);
     color: var(--color-text);
   }

   .step__desc {
     color: var(--color-text-dim);
     line-height: 1.6;
   }

   .step__connector {
     display: flex;
     justify-content: center;
     align-items: center;
     color: var(--color-text-dim);
   }

   .step__connector svg {
     width: 40px;
     height: 24px;
     transform: rotate(90deg);
   }

   @media (min-width: 768px) {
     .steps {
       flex-direction: row;
       align-items: center;
     }
     .step__connector {
       flex: 0 0 auto;
     }
     .step__connector svg {
       transform: none;
     }
   }
   ```

**Tests to write:**
Manual verification:
- Test case 1: At desktop 1024px+, three steps display horizontally with arrow connectors between them.
- Test case 2: At 375px mobile, steps stack vertically with downward arrow connectors.
- Test case 3: Scroll the section into view — step 1 appears immediately, step 2 reveals 150ms later, step 3 reveals 300ms after step 1.
- Test case 4: Scroll past, scroll back — animations should not re-fire (one-shot).
- Test case 5: Each step shows its icon (cyan accent color) above title and description.
- Test case 6: With reduced-motion enabled, all steps display in final state immediately on page load.
- Test case 7: Section heading "How it works" + subtitle visible above the steps.
- Test case 8: All text is readable; verify color contrast for WCAG AA via DevTools Lighthouse.

**Acceptance criteria:**
- Three steps display horizontally on ≥768px, vertically on <768px
- Arrows/connectors rotate 90° on mobile, horizontal on desktop
- Each step has a distinct icon, numbered title, and description
- Reveal staggered: 0ms, 150ms, 300ms
- One-shot per page load (no re-trigger on scroll back)
- Reduced-motion users see static layout immediately
- Color contrast meets WCAG 2.1 AA
- No console errors

---

### task: section-features

**Goal:** Build the features section with six feature cards (multi-agent pipeline, per-task review, pluggable backends, zero babysitting, context files, serial dispatch) in a responsive grid (1 col mobile, 2 col tablet, 3 col desktop).

**Context:**
Six feature cards in responsive grid: 3 columns desktop (≥1024px), 2 columns tablet (≥768px), 1 column mobile. Each card: icon, title, 2-3 sentence description. Hover lift (already in components.css). Scroll-triggered fade-in on entry.

Feature → icon mapping (Lucide):
- Multi-agent pipeline → `workflow`
- Per-task review loop → `repeat`
- Pluggable backends → `layers`
- Zero babysitting → `bot`
- Per-agent context files → `file-text`
- Serial task dispatch → `list-ordered`

Icons inlined as SVG, colored via `currentColor` (so feature-card__icon `color: var(--color-accent)` cascades).

**Files to create/modify:**
- `landingpage/index.html` — fill `<section id="features">`
- `landingpage/assets/css/sections.css` — append features styles

**Implementation steps:**
1. In `landingpage/index.html`, replace contents of `<section id="features" class="features section">` with:
   ```html
   <div class="container">
     <header class="section-heading" data-reveal>
       <h2 class="section-heading__title">Built for autonomous shipping</h2>
       <p class="section-heading__subtitle">Every piece designed to run without you.</p>
     </header>
     <div class="features__grid">
       <article class="feature-card" data-reveal data-reveal-delay="0">
         <div class="feature-card__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <rect x="3" y="3" width="6" height="6" rx="1"></rect>
             <rect x="15" y="3" width="6" height="6" rx="1"></rect>
             <rect x="9" y="15" width="6" height="6" rx="1"></rect>
             <path d="M6 9v3a3 3 0 0 0 3 3h0"></path>
             <path d="M18 9v3a3 3 0 0 1-3 3h0"></path>
           </svg>
         </div>
         <h3 class="feature-card__title">Multi-agent pipeline</h3>
         <p class="feature-card__desc">Analyst, architect, designer, planner, developer, and reviewer agents — each specialized, all chained.</p>
       </article>
       <article class="feature-card" data-reveal data-reveal-delay="50">
         <div class="feature-card__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <polyline points="17,1 21,5 17,9"></polyline>
             <path d="M3 11V9a4 4 0 0 1 4-4h14"></path>
             <polyline points="7,23 3,19 7,15"></polyline>
             <path d="M21 13v2a4 4 0 0 1-4 4H3"></path>
           </svg>
         </div>
         <h3 class="feature-card__title">Per-task review loop</h3>
         <p class="feature-card__desc">Every developer task is reviewed independently. Revisions cycle until the work passes — or the limit is hit.</p>
       </article>
       <article class="feature-card" data-reveal data-reveal-delay="100">
         <div class="feature-card__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <polygon points="12,2 2,7 12,12 22,7 12,2"></polygon>
             <polyline points="2,17 12,22 22,17"></polyline>
             <polyline points="2,12 12,17 22,12"></polyline>
           </svg>
         </div>
         <h3 class="feature-card__title">Pluggable backends</h3>
         <p class="feature-card__desc">Run on Azure (Blob Storage + Queues) or GitHub (Issues + branches). Swap with one env var.</p>
       </article>
       <article class="feature-card" data-reveal data-reveal-delay="0">
         <div class="feature-card__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <rect x="3" y="11" width="18" height="10" rx="2"></rect>
             <circle cx="12" cy="5" r="2"></circle>
             <path d="M12 7v4"></path>
             <line x1="8" y1="16" x2="8" y2="16"></line>
             <line x1="16" y1="16" x2="16" y2="16"></line>
           </svg>
         </div>
         <h3 class="feature-card__title">Zero babysitting</h3>
         <p class="feature-card__desc">A single observer process drives the whole pipeline. Start it, walk away, come back to working code.</p>
       </article>
       <article class="feature-card" data-reveal data-reveal-delay="50">
         <div class="feature-card__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
             <polyline points="14,2 14,8 20,8"></polyline>
             <line x1="16" y1="13" x2="8" y2="13"></line>
             <line x1="16" y1="17" x2="8" y2="17"></line>
             <polyline points="10,9 9,9 8,9"></polyline>
           </svg>
         </div>
         <h3 class="feature-card__title">Per-agent context files</h3>
         <p class="feature-card__desc">Each agent gets curated context — only what it needs. No prompt bloat, no missed details.</p>
       </article>
       <article class="feature-card" data-reveal data-reveal-delay="100">
         <div class="feature-card__icon">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
             <line x1="10" y1="6" x2="21" y2="6"></line>
             <line x1="10" y1="12" x2="21" y2="12"></line>
             <line x1="10" y1="18" x2="21" y2="18"></line>
             <path d="M4 6h1v4"></path>
             <path d="M4 10h2"></path>
             <path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"></path>
           </svg>
         </div>
         <h3 class="feature-card__title">Serial task dispatch</h3>
         <p class="feature-card__desc">Developer tasks run one at a time on the same feature. No parallel-edit conflicts, no merge headaches.</p>
       </article>
     </div>
   </div>
   ```

2. Append to `landingpage/assets/css/sections.css`:
   ```css
   /* ---- Features ---- */
   .features__grid {
     display: grid;
     grid-template-columns: 1fr;
     gap: var(--space-6);
   }

   @media (min-width: 768px) {
     .features__grid {
       grid-template-columns: repeat(2, 1fr);
     }
   }

   @media (min-width: 1024px) {
     .features__grid {
       grid-template-columns: repeat(3, 1fr);
     }
   }
   ```

**Tests to write:**
Manual verification:
- Test case 1: At 1280px desktop, six cards display in 3 columns × 2 rows.
- Test case 2: At 800px tablet, six cards display in 2 columns × 3 rows.
- Test case 3: At 375px mobile, six cards display in 1 column × 6 rows.
- Test case 4: Hover any card — verify lift (translateY -4px), accent shadow, accent border.
- Test case 5: Scroll the section into view — cards fade in sequentially with 50ms stagger between rows.
- Test case 6: Each card shows its Lucide icon in cyan accent at top.
- Test case 7: All card titles and descriptions are readable; verify WCAG AA contrast.
- Test case 8: Tab through cards — `<article>` is not focusable; this is correct (cards are not interactive). If we add hover interactions later, ensure they are keyboard-accessible.
- Test case 9: With reduced-motion enabled, all six cards appear in final state on load with no fade-in.

**Acceptance criteria:**
- Six feature cards rendered in responsive grid: 1/2/3 columns at 375/768/1024px
- Each card has icon (cyan), title, 2-3 sentence description
- Hover lifts card 4px with accent shadow and border
- Scroll-triggered fade-in with stagger
- One-shot reveals (no re-trigger on scroll back)
- Reduced-motion: static layout
- All text WCAG 2.1 AA compliant
- Icons render as inline SVG inheriting `currentColor`

---

### task: section-pipeline-terminal

**Goal:** Build the pipeline section showing a simulated `agentharness observe` terminal output with streaming lines and a blinking cursor, restarting when scrolled into view.

**Context:**
Terminal-style animation showing realistic agent activity:
```
$ agentharness observe
[12:01:04]  analyst         → analyzing        feat-abc123
[12:01:22]  analyst         ✓ complete         18s
[12:01:23]  architect       → analyzing
[12:01:55]  architect       ✓ complete         32s
[12:01:56]  planner         → planning
[12:02:14]  planner         ✓ complete         18s  3 tasks
[12:02:15]  developer[1]    → in_progress
[12:03:44]  reviewer[1]     ✓ PASS
[12:03:45]  developer[2]    → in_progress
█  (blinking cursor)
```

Each line uses CSS animation with staggered `animation-delay` based on `--line-index` custom property. Lines slide/fade in 400ms apart.

Animation restarts each time `#pipeline` enters viewport (handled by `initPipelineAnimation` in animations.js — it adds/removes `.pipeline-line--visible` class to lines).

Container has dark surface, monospace font. Cursor blinks via `@keyframes blink`.

Reduced-motion: all lines visible immediately, no blink.

**Files to create/modify:**
- `landingpage/index.html` — fill `<section id="pipeline">`
- `landingpage/assets/css/sections.css` — append pipeline terminal styles

**Implementation steps:**
1. In `landingpage/index.html`, replace contents of `<section id="pipeline" class="pipeline section">` with:
   ```html
   <div class="container">
     <header class="section-heading" data-reveal>
       <h2 class="section-heading__title">See it in action</h2>
       <p class="section-heading__subtitle">A real <code class="code-inline">agentharness observe</code> session, step by step.</p>
     </header>
     <div class="pipeline-terminal" role="img" aria-label="Simulated terminal output of agentharness observe showing the agent pipeline running">
       <div class="pipeline-terminal__header">
         <span class="pipeline-terminal__dot"></span>
         <span class="pipeline-terminal__dot"></span>
         <span class="pipeline-terminal__dot"></span>
         <span class="pipeline-terminal__title">agentharness</span>
       </div>
       <div class="pipeline-terminal__body">
         <div class="pipeline-line pipeline-line--prompt" style="--line-index: 0;">$ agentharness observe</div>
         <div class="pipeline-line" style="--line-index: 1;"><span class="pipeline-line__time">[12:01:04]</span>  analyst         <span class="pipeline-line__arrow">→</span> analyzing        feat-abc123</div>
         <div class="pipeline-line" style="--line-index: 2;"><span class="pipeline-line__time">[12:01:22]</span>  analyst         <span class="pipeline-line__check">✓</span> complete         18s</div>
         <div class="pipeline-line" style="--line-index: 3;"><span class="pipeline-line__time">[12:01:23]</span>  architect       <span class="pipeline-line__arrow">→</span> analyzing</div>
         <div class="pipeline-line" style="--line-index: 4;"><span class="pipeline-line__time">[12:01:55]</span>  architect       <span class="pipeline-line__check">✓</span> complete         32s</div>
         <div class="pipeline-line" style="--line-index: 5;"><span class="pipeline-line__time">[12:01:56]</span>  planner         <span class="pipeline-line__arrow">→</span> planning</div>
         <div class="pipeline-line" style="--line-index: 6;"><span class="pipeline-line__time">[12:02:14]</span>  planner         <span class="pipeline-line__check">✓</span> complete         18s  3 tasks</div>
         <div class="pipeline-line" style="--line-index: 7;"><span class="pipeline-line__time">[12:02:15]</span>  developer[1]    <span class="pipeline-line__arrow">→</span> in_progress</div>
         <div class="pipeline-line" style="--line-index: 8;"><span class="pipeline-line__time">[12:03:44]</span>  reviewer[1]     <span class="pipeline-line__check">✓</span> PASS</div>
         <div class="pipeline-line" style="--line-index: 9;"><span class="pipeline-line__time">[12:03:45]</span>  developer[2]    <span class="pipeline-line__arrow">→</span> in_progress</div>
         <div class="pipeline-cursor" aria-hidden="true">█</div>
       </div>
     </div>
   </div>
   ```

2. Append to `landingpage/assets/css/sections.css`:
   ```css
   /* ---- Pipeline terminal ---- */
   .pipeline-terminal {
     background-color: #060912;
     border: 1px solid var(--color-border);
     border-radius: var(--radius-lg);
     overflow: hidden;
     font-family: var(--font-mono);
     box-shadow: var(--shadow-card);
     max-width: 64rem;
     margin-inline: auto;
   }

   .pipeline-terminal__header {
     display: flex;
     align-items: center;
     gap: var(--space-2);
     padding: var(--space-3) var(--space-4);
     background-color: rgba(255, 255, 255, 0.03);
     border-bottom: 1px solid var(--color-border);
   }

   .pipeline-terminal__dot {
     width: 12px;
     height: 12px;
     border-radius: 50%;
     background-color: var(--color-border);
   }

   .pipeline-terminal__title {
     margin-left: auto;
     margin-right: auto;
     padding-right: 36px;
     font-size: var(--text-sm);
     color: var(--color-text-dim);
     font-family: var(--font-display);
   }

   .pipeline-terminal__body {
     padding: var(--space-6);
     overflow-x: auto;
     min-height: 24rem;
   }

   .pipeline-line {
     font-size: 0.8125rem;
     line-height: 1.8;
     color: var(--color-text);
     white-space: pre;
     opacity: 0;
     transform: translateY(4px);
     transition: opacity 0.3s ease, transform 0.3s ease;
     transition-delay: calc(var(--line-index, 0) * 400ms);
   }

   .pipeline-line--visible {
     opacity: 1;
     transform: translateY(0);
   }

   .pipeline-line--prompt {
     color: var(--color-accent);
     margin-bottom: var(--space-3);
   }

   .pipeline-line__time {
     color: var(--color-text-dim);
   }

   .pipeline-line__arrow {
     color: var(--color-accent);
   }

   .pipeline-line__check {
     color: #4ade80;
   }

   .pipeline-cursor {
     display: inline-block;
     color: var(--color-accent);
     animation: pipeline-blink 1s step-end infinite;
     margin-top: var(--space-2);
     font-size: 1rem;
     line-height: 1;
   }

   @keyframes pipeline-blink {
     0%, 50% { opacity: 1; }
     51%, 100% { opacity: 0; }
   }

   :root.no-motion .pipeline-line {
     opacity: 1;
     transform: none;
     transition-delay: 0s;
   }

   :root.no-motion .pipeline-cursor {
     animation: none;
   }
   ```

**Tests to write:**
Manual verification:
- Test case 1: Open the page and scroll to the pipeline section. Lines should stream in one by one with ~400ms delay between each.
- Test case 2: After all lines are visible, the `█` cursor blinks at ~1Hz.
- Test case 3: Scroll down past the pipeline, then scroll back up — animations should restart (lines re-stream).
- Test case 4: At 375px mobile, terminal body scrolls horizontally without breaking layout.
- Test case 5: Terminal header shows three traffic-light dots with `agentharness` title centered.
- Test case 6: Status icons: arrow (`→`) is cyan, check (`✓`) is green, timestamp `[HH:MM:SS]` is dim.
- Test case 7: With reduced-motion enabled, all lines display immediately on load and cursor does not blink.
- Test case 8: Run Lighthouse — no CLS issues, font loaded with system fallback.
- Test case 9: The `pipeline-terminal` has `role="img"` and `aria-label` for assistive tech (since it's decorative animation).

**Acceptance criteria:**
- Terminal renders with dark surface (#060912), monospace font, three header dots, and "agentharness" title
- Ten content lines display in canonical format (timestamp, agent name, status glyph, status text, optional detail)
- Lines stream in via CSS animation with 400ms stagger when section enters viewport
- Animation restarts each time section re-enters viewport (handled by `initPipelineAnimation`)
- Cursor blinks at 1Hz
- Mobile: horizontal scroll on overflow, no layout break
- Reduced-motion: instant display, no blink
- Accessible via `role="img"` + `aria-label`
- Status icons colored correctly (arrow cyan, check green, timestamp dim)

---

### task: section-cta-footer

**Goal:** Build the final CTA section with closing headline, primary GitHub CTA, and copyable quick-start command — the last visible content before the footer.

**Context:**
Closing conversion prompt: "Stop writing boilerplate. Start shipping."
- Primary CTA: "View on GitHub" (links to repo)
- Secondary CTA: copyable `pip install agentharness && agentharness brainstorm` (uses `data-quickstart-cmd` so `main.js` populates value)

Section sits before `<footer>` (already implemented in section-header-and-footer task). Click-to-copy works via existing `copy.js`.

**Files to create/modify:**
- `landingpage/index.html` — fill `<section id="cta">`
- `landingpage/assets/css/sections.css` — append CTA section styles

**Implementation steps:**
1. In `landingpage/index.html`, replace contents of `<section id="cta" class="cta section">` with:
   ```html
   <div class="container cta__inner">
     <header class="section-heading" data-reveal>
       <h2 class="section-heading__title cta__headline">Stop writing boilerplate.<br>Start shipping.</h2>
     </header>
     <div class="cta__actions" data-reveal data-reveal-delay="100">
       <a class="btn btn--primary"
          data-repo-url
          href=""
          target="_blank"
          rel="noopener noreferrer">
         <span>View on GitHub</span>
         <span aria-hidden="true">↗</span>
       </a>
       <button class="copy-cmd"
               data-quickstart-cmd
               data-copy=""
               data-copy-feedback="Copied!"
               type="button"
               aria-label="Copy quick-start command">
         <code>$ pip install agentharness &amp;&amp; agentharness brainstorm</code>
         <svg class="copy-cmd__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
           <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
           <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
         </svg>
       </button>
     </div>
   </div>
   ```

2. Append to `landingpage/assets/css/sections.css`:
   ```css
   /* ---- Final CTA ---- */
   .cta {
     padding-block: var(--space-24);
   }

   .cta__inner {
     text-align: center;
   }

   .cta__headline {
     max-width: 28rem;
     margin-inline: auto;
   }

   .cta__actions {
     display: flex;
     flex-direction: column;
     gap: var(--space-4);
     align-items: center;
     justify-content: center;
     margin-top: var(--space-8);
   }

   @media (min-width: 640px) {
     .cta__actions {
       flex-direction: row;
       flex-wrap: wrap;
     }
   }
   ```

**Tests to write:**
Manual verification:
- Test case 1: Scroll to bottom of page. CTA section displays before the footer with centered closing headline.
- Test case 2: Headline renders on two lines: "Stop writing boilerplate." then "Start shipping."
- Test case 3: Primary CTA "View on GitHub ↗" opens repo in new tab.
- Test case 4: Click the copy command — verify `pip install agentharness && agentharness brainstorm` is on clipboard with "Copied!" tooltip.
- Test case 5: Verify the `data-quickstart-cmd` projection works: the displayed code is `$ pip install agentharness && agentharness brainstorm` (populated by `main.js`).
- Test case 6: At 375px mobile, primary CTA and copy widget stack vertically. At ≥640px, they align horizontally.
- Test case 7: Tab through the CTA — primary CTA and copy button both keyboard-focusable with cyan focus rings.
- Test case 8: With reduced-motion enabled, headline appears immediately without fade.
- Test case 9: Footer is visible immediately below the CTA section.

**Acceptance criteria:**
- CTA section displays "Stop writing boilerplate. Start shipping." headline
- Primary CTA links to repo, opens new tab with `rel="noopener noreferrer"`
- Quick-start command is copyable and shows "Copied!" feedback
- Layout: stacked at <640px, horizontal at ≥640px
- Both CTAs keyboard-navigable with visible focus
- `data-quickstart-cmd` projection populates command text from `main.js` constants
- Reduced-motion users see static layout

---

### task: launch-readiness-and-verification

**Goal:** Final integration: add placeholder OG image and favicon, verify cross-browser rendering, run Lighthouse audits, fix any console errors, and validate all spec acceptance criteria.

**Context:**
At this stage all sections, CSS, and JS modules are implemented. This task verifies the complete page meets all spec NFRs:
- Performance: <2s on 3G, Lighthouse ≥90 desktop / ≥85 mobile, total weight <500KB gzipped
- Accessibility: WCAG 2.1 AA, keyboard navigable, prefers-reduced-motion respected
- Browser compat: latest Chrome, Firefox, Safari (last 2 versions)
- SEO: meta tags valid, OG/Twitter cards work
- No backend, no analytics, no inline event handlers, no console errors

OG image is a launch blocker per arch-review risk register. Until designer delivers, ship a placeholder (a simple 1200×630 PNG generated locally or a static SVG converted to PNG).

Favicon: simple SVG (cyan node on dark background) suffices for placeholder.

This task does NOT create new components — it places assets, runs verification, and produces a launch-readiness report.

**Files to create/modify:**
- `landingpage/assets/img/favicon.svg` — placeholder SVG favicon
- `landingpage/assets/img/og-image.png` — placeholder OG image (1200×630 PNG)
- `landingpage/assets/img/apple-touch-icon.png` — placeholder 180×180 PNG (can be derived from favicon)
- `landingpage/assets/img/favicon.ico` — placeholder ICO (can be the same SVG converted)
- `landingpage/README.md` — append a "Launch checklist" section
- (No JS or CSS modifications expected; only fixes if verification reveals issues)

**Implementation steps:**
1. Create `landingpage/assets/img/favicon.svg` with placeholder content:
   ```xml
   <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
     <rect width="64" height="64" fill="#0a0f1e"/>
     <circle cx="32" cy="32" r="14" fill="#00d4ff"/>
     <circle cx="32" cy="32" r="14" fill="none" stroke="#00d4ff" stroke-width="2" opacity="0.4"/>
   </svg>
   ```

2. Generate placeholder rasters using a small Python script (no extra deps required; uses only stdlib via PIL if installed, else use the cairosvg approach). Run in terminal from the repo root:
   ```bash
   cd landingpage/assets/img
   # If `cairosvg` is not installed, install in a venv:
   # python -m pip install --user cairosvg
   python -c "
   import cairosvg
   cairosvg.svg2png(url='favicon.svg', write_to='favicon-32.png', output_width=32, output_height=32)
   cairosvg.svg2png(url='favicon.svg', write_to='apple-touch-icon.png', output_width=180, output_height=180)
   "
   # ICO: copy 32px PNG and rename (browsers accept PNG-in-ICO containers; for true ICO format,
   # designer can replace later)
   cp favicon-32.png favicon.ico
   rm favicon-32.png
   ```
   If `cairosvg` is unavailable, document this in the README's launch checklist as a TODO and ship the SVG-only favicon (most modern browsers support it via the `image/svg+xml` link tag already in the HTML).

3. Create placeholder OG image. Write a small SVG-based placeholder at `landingpage/assets/img/og-image.svg` and convert to PNG:
   ```xml
   <!-- og-image.svg -->
   <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
     <rect width="1200" height="630" fill="#0a0f1e"/>
     <text x="80" y="120" font-family="Inter, sans-serif" font-size="36" font-weight="700" fill="#e6edf3">AgentHarness</text>
     <text x="80" y="320" font-family="Inter, sans-serif" font-size="80" font-weight="800" fill="#e6edf3">Delegate the grind.</text>
     <text x="80" y="420" font-family="Inter, sans-serif" font-size="80" font-weight="800" fill="#e6edf3">Reclaim your time.</text>
     <g transform="translate(80, 510)">
       <line x1="0" y1="20" x2="900" y2="20" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
       <circle cx="0"   cy="20" r="14" fill="#00d4ff"/>
       <circle cx="180" cy="20" r="14" fill="#00d4ff" opacity="0.7"/>
       <circle cx="360" cy="20" r="14" fill="#00d4ff" opacity="0.5"/>
       <circle cx="540" cy="20" r="14" fill="#1e3a5f" stroke="#8b9bb4" stroke-width="2"/>
       <circle cx="720" cy="20" r="14" fill="#1e3a5f" stroke="#8b9bb4" stroke-width="2"/>
       <circle cx="900" cy="20" r="14" fill="#1e3a5f" stroke="#8b9bb4" stroke-width="2"/>
     </g>
   </svg>
   ```
   Convert to PNG (same approach as favicon):
   ```bash
   python -c "
   import cairosvg
   cairosvg.svg2png(url='og-image.svg', write_to='og-image.png', output_width=1200, output_height=630)
   "
   ```

4. Run cross-browser verification. For each browser (Chrome latest, Firefox latest, Safari latest):
   - Open `landingpage/index.html` directly via `file://`
   - Open DevTools → Console → confirm zero errors and zero warnings (acceptable: any warnings about CDN-loaded fonts if added later)
   - Open the page via local server: `cd landingpage && python -m http.server 8000`, then visit http://localhost:8000
   - Resize to 375px, 768px, 1024px, 1440px — verify no horizontal scroll appears at any width

5. Run Lighthouse audit:
   - In Chrome DevTools, open Lighthouse panel
   - Run audit for Desktop with categories: Performance, Accessibility, Best Practices, SEO
   - Expected scores: Performance ≥90, Accessibility ≥95, Best Practices ≥95, SEO ≥95
   - Run audit for Mobile: Performance ≥85, others same as desktop
   - Document any failed metric in `README.md` launch checklist

6. Verify accessibility:
   - Tab through the entire page from header to footer — every interactive element must be reachable and visibly focused
   - Open with VoiceOver (macOS: `Cmd+F5`) or NVDA (Windows): wordmark, headlines, links should announce correctly
   - Toggle reduced-motion (DevTools → Rendering → Emulate CSS prefers-reduced-motion: reduce) and verify all animations are disabled

7. Verify external link safety: every `<a>` with `target="_blank"` must have `rel="noopener noreferrer"`. Open DevTools console and run:
   ```js
   Array.from(document.querySelectorAll('a[target="_blank"]'))
     .filter(a => !a.rel.includes('noopener') || !a.rel.includes('noreferrer'))
   ```
   Result should be `[]` (empty array).

8. Append a "Launch checklist" section to `landingpage/README.md`:
   ```markdown
   ## Launch checklist

   ### Required before launch
   - [ ] Designer-provided OG image at `assets/img/og-image.png` (1200×630, replaces placeholder)
   - [ ] Designer-provided favicon variants (16×16, 32×32 ICO; 180×180 PNG)
   - [ ] Confirm GitHub repo URL — currently: `https://github.com/onpaj/AgentHarness`
   - [ ] Confirm quick-start command matches README install instructions: `pip install agentharness && agentharness brainstorm`
   - [ ] Final headline copy approved
   - [ ] Lighthouse Desktop Performance ≥90
   - [ ] Lighthouse Mobile Performance ≥85
   - [ ] Lighthouse Accessibility ≥95

   ### Verified
   - [ ] No console errors (Chrome, Firefox, Safari)
   - [ ] All external links have rel="noopener noreferrer"
   - [ ] Tab order works end-to-end
   - [ ] prefers-reduced-motion honored
   - [ ] No horizontal scroll at 375px / 768px / 1024px / 1440px

   ### Centralized
   - Repo URL: `assets/js/main.js` constant `REPO_URL`
   - Quick-start command: `assets/js/main.js` constant `QUICKSTART_CMD`
   ```

9. If any verification step fails (e.g., Lighthouse score below threshold, console error, missing focus state), fix the underlying issue (most likely candidates: missing `loading="lazy"` on images if added later, or untranslated `data-reveal-delay` style timing) before declaring the task complete. Document each fix briefly in a commit message.

**Tests to write:**
This task is verification-focused. The "tests" are the manual checks above. Required passing checks:

1. **Cross-browser smoke test**: Page loads with no console errors in Chrome, Firefox, Safari.
2. **Responsive smoke test**: No horizontal overflow at 375px, 768px, 1024px, 1440px.
3. **Lighthouse Desktop**: Performance ≥90, Accessibility ≥95, Best Practices ≥95, SEO ≥95.
4. **Lighthouse Mobile**: Performance ≥85, Accessibility ≥95, Best Practices ≥95, SEO ≥95.
5. **External link safety**: `Array.from(document.querySelectorAll('a[target="_blank"]')).filter(a => !a.rel.includes('noopener') || !a.rel.includes('noreferrer'))` returns `[]`.
6. **Keyboard navigation**: Tab order: header CTA → hero primary CTA → hero copy button → CTA section primary → CTA section copy button → footer GitHub link. Each shows a visible focus ring.
7. **Reduced motion**: With `prefers-reduced-motion: reduce`, no animations run; all content is visible at full opacity in final state.
8. **Total page weight**: `du -sh landingpage/` should be under 500 KB excluding optional CDN assets.
9. **OG image present**: `landingpage/assets/img/og-image.png` exists and dimensions are 1200×630 (verify with `file landingpage/assets/img/og-image.png`).
10. **Favicon present**: `landingpage/assets/img/favicon.svg` exists and renders in browser tab.

**Acceptance criteria:**
- Placeholder OG image (1200×630 PNG) exists at `landingpage/assets/img/og-image.png`
- Placeholder favicon SVG exists at `landingpage/assets/img/favicon.svg`; favicon renders in browser tab
- Apple touch icon (180×180) exists at `landingpage/assets/img/apple-touch-icon.png`
- Page loads without any console errors in Chrome, Firefox, Safari
- Lighthouse Desktop: Performance ≥90, Accessibility ≥95, Best Practices ≥95, SEO ≥95
- Lighthouse Mobile: Performance ≥85, Accessibility ≥95
- No horizontal scroll at any tested breakpoint (375/768/1024/1440px)
- All `target="_blank"` links have `rel="noopener noreferrer"` (zero exceptions)
- Keyboard tab order is logical and every interactive element has a visible focus ring
- `prefers-reduced-motion: reduce` disables all animations site-wide
- Total page weight (excluding optional CDN assets) <500 KB
- README includes a launch checklist that calls out designer-blocking items (final OG image, final headline copy, finalized icons)