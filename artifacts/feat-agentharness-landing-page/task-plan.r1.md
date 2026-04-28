### task: scaffold-directory-and-readme

**Goal:** Create the `landingpage/` directory structure and a minimal README documenting how to view/deploy the page.

**Context:**
The landing page is a self-contained static asset bundle living in `/landingpage` with zero coupling to the Python codebase. It must work via three deployment paths without modification: (a) `file://` direct open, (b) any static file server (Python `http.server`, `npx serve`), (c) GitHub Pages from `/landingpage` subdirectory. All asset paths must be relative (no leading `/`).

Required directory structure:
```
landingpage/
├── index.html
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
│   │   ├── icons/
│   │   └── og-image.png   (placeholder; final asset delivered by designer)
│   └── fonts/             (optional, empty for now)
└── README.md
```

**Files to create/modify:**
- `landingpage/README.md` — brief: what it is, how to view locally, deployment paths
- `landingpage/assets/css/.gitkeep` — placeholder so empty dir is tracked (delete once real CSS files land in subsequent tasks)
- `landingpage/assets/js/.gitkeep` — placeholder
- `landingpage/assets/img/icons/.gitkeep` — placeholder
- `landingpage/assets/fonts/.gitkeep` — placeholder

**Implementation steps:**
1. Create directories: `landingpage/`, `landingpage/assets/css/`, `landingpage/assets/js/`, `landingpage/assets/img/`, `landingpage/assets/img/icons/`, `landingpage/assets/fonts/`.
2. Add `.gitkeep` placeholder files in each currently-empty subdirectory listed above so git tracks them.
3. Write `landingpage/README.md` with the following content:

```markdown
# AgentHarness Landing Page

Static, single-page marketing site for AgentHarness. Pure HTML/CSS/vanilla JS — no build step, no backend.

## View locally

Open directly:
```
open landingpage/index.html
```

Or serve with any static server:
```
python -m http.server -d landingpage 8000
# or
npx serve landingpage
```

Then visit http://localhost:8000.

## Deploy

The `landingpage/` directory is deployment-target-agnostic. All asset paths are relative.

- **GitHub Pages:** point Pages at `/landingpage` subdirectory of the repo.
- **Netlify / Vercel:** publish directory = `landingpage`.
- **Any static host:** copy the `landingpage/` directory.

## Structure

```
landingpage/
├── index.html              Single-page entry
├── assets/
│   ├── css/                Cascading load: reset → tokens → layout → components → sections
│   ├── js/                 ES modules: main.js orchestrates animations.js, copy.js, motion.js
│   ├── img/                Icons (SVG, inlined into HTML at author time), OG image, favicon
│   └── fonts/              Optional self-hosted display + monospace fonts
└── README.md
```

## Editing repo URL or quick-start command

Both live as constants at the top of `assets/js/main.js`:
```
const REPO_URL = 'https://github.com/onpaj/AgentHarness';
const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';
```
A single edit propagates to every CTA on the page.
```

**Tests to write:**
No automated tests for scaffolding. Manual verification only:
- Verify all directories exist with `ls -la landingpage/assets/{css,js,img,img/icons,fonts}`.
- Verify README.md renders correctly (Markdown preview).

**Acceptance criteria:**
- `landingpage/README.md` exists and documents view/deploy paths.
- All listed subdirectories exist and are tracked by git (via `.gitkeep` placeholders).
- No HTML/CSS/JS files yet — those land in subsequent tasks.

---

### task: css-reset-and-tokens

**Goal:** Implement the CSS reset and design tokens (custom properties) as the foundation for all later CSS.

**Context:**
CSS load order is fixed: `reset.css` → `tokens.css` → `layout.css` → `components.css` → `sections.css`. Each file only references tokens defined upstream. CSS custom properties are the single source of truth for theme.

Required tokens:
```css
:root {
  /* Color */
  --color-bg-base:     #0a0f1e;
  --color-bg-mid:      #1e3a5f;
  --color-bg-surface:  #162847;
  --color-accent:      #00d4ff;
  --color-accent-dim:  rgba(0, 212, 255, 0.12);
  --color-text:        #e6edf3;
  --color-text-dim:    #8b9bb4;
  --color-border:      rgba(255, 255, 255, 0.08);
  --color-border-hover: rgba(0, 212, 255, 0.30);

  /* Typography */
  --font-display:  'Inter', system-ui, sans-serif;
  --font-mono:     'JetBrains Mono', ui-monospace, monospace;
  --text-hero:     clamp(2.5rem, 6vw, 5rem);
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

WCAG 2.1 AA color contrast must be respected (palette already chosen for high contrast). Body sets `background: var(--color-bg-base); color: var(--color-text); font-family: var(--font-display);`.

**Files to create/modify:**
- `landingpage/assets/css/reset.css` — modern CSS reset (box-sizing, margins, list defaults, image defaults)
- `landingpage/assets/css/tokens.css` — `:root` custom properties + `.no-motion` global override

**Implementation steps:**
1. Write `reset.css`:
```css
*, *::before, *::after { box-sizing: border-box; }

* { margin: 0; padding: 0; }

html { -webkit-text-size-adjust: 100%; -webkit-font-smoothing: antialiased; }

html:focus-within { scroll-behavior: smooth; }

body {
  min-height: 100vh;
  line-height: 1.5;
  text-rendering: optimizeSpeed;
}

img, picture, video, canvas, svg { display: block; max-width: 100%; }

input, button, textarea, select { font: inherit; color: inherit; }

button { background: none; border: none; cursor: pointer; }

a { color: inherit; text-decoration: none; }

ul, ol { list-style: none; }

p, h1, h2, h3, h4, h5, h6 { overflow-wrap: break-word; }

@media (prefers-reduced-motion: reduce) {
  html:focus-within { scroll-behavior: auto; }
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

2. Write `tokens.css` with the full `:root { ... }` block above, plus base body styles:
```css
body {
  background: var(--color-bg-base);
  color: var(--color-text);
  font-family: var(--font-display);
  font-size: var(--text-body);
}

::selection {
  background: var(--color-accent);
  color: var(--color-bg-base);
}
```

3. Verify both files have no syntax errors (open in browser dev tools, no CSS warnings).

**Tests to write:**
Manual verification:
- Open a blank HTML page that links these two CSS files. Body background must be `#0a0f1e`. Default text color must be `#e6edf3`. Inspecting `:root` in dev tools must show all custom properties.
- Toggle "Emulate CSS prefers-reduced-motion" in dev tools. No errors; reset.css media query should reduce animation/transition durations.

**Acceptance criteria:**
- `reset.css` zeroes browser defaults and includes a `prefers-reduced-motion` safety override.
- `tokens.css` defines every custom property listed in the Context section above.
- `:root.no-motion *` rule disables animation/transition with `!important`.
- No console warnings when files are loaded.

---

### task: css-layout-and-components

**Goal:** Implement reusable layout utilities and component-level styles (buttons, cards, code blocks, copy widget, toast states).

**Context:**
Load order continues: `reset.css` → `tokens.css` → **`layout.css` → `components.css`** → `sections.css`. Layout = container, grid utilities, flex helpers, section padding. Components = buttons, feature cards, copy-command widget, toast/feedback states.

Container max-width: `1280px` (from `--container-max`). Section vertical padding: `--section-padding-y` (6rem).

Feature card hover spec:
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

Reveal pattern (initial state for `[data-reveal]`, applied here so it works as soon as `js-loaded` is set):
```css
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
```

Copy button states:
- default → shows code text + ⎘ icon
- `.is-copied` → icon swaps to ✓ (handled in HTML markup; CSS only swaps display), background = `var(--color-accent-dim)`, "Copied!" appears via `::after` for 2000ms

All interactive elements must have visible focus states (WCAG). Touch targets ≥44×44px.

**Files to create/modify:**
- `landingpage/assets/css/layout.css` — container, grid, flex, section padding
- `landingpage/assets/css/components.css` — buttons (primary/secondary/icon), feature card, copy-command widget, toast feedback, code block, noscript notice, reveal initial state, focus rings

**Implementation steps:**

1. Write `layout.css`:
```css
.container {
  width: 100%;
  max-width: var(--container-max);
  margin-inline: auto;
  padding-inline: var(--space-6);
}

@media (min-width: 1024px) {
  .container { padding-inline: var(--space-8); }
}

section {
  padding-block: var(--section-padding-y);
}

.grid { display: grid; gap: var(--space-6); }

.grid--features {
  grid-template-columns: 1fr;
}
@media (min-width: 768px) {
  .grid--features { grid-template-columns: repeat(2, 1fr); gap: var(--space-8); }
}
@media (min-width: 1024px) {
  .grid--features { grid-template-columns: repeat(3, 1fr); }
}

.flex { display: flex; }
.flex--center { align-items: center; justify-content: center; }
.flex--between { align-items: center; justify-content: space-between; }
.flex--col { flex-direction: column; }
.gap-2 { gap: var(--space-2); }
.gap-4 { gap: var(--space-4); }
.gap-6 { gap: var(--space-6); }
```

2. Write `components.css`:
```css
/* Focus rings (global, accessibility) */
:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-6);
  min-height: 44px;
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: var(--text-body);
  transition: background var(--duration-hover) ease,
              transform var(--duration-hover) ease,
              border-color var(--duration-hover) ease;
}

.btn--primary {
  background: var(--color-accent);
  color: var(--color-bg-base);
}
.btn--primary:hover {
  transform: translateY(-1px);
  background: #1de1ff;
}

.btn--secondary {
  background: transparent;
  color: var(--color-text);
  border: 1px solid var(--color-border);
}
.btn--secondary:hover {
  border-color: var(--color-border-hover);
  background: var(--color-accent-dim);
}

.btn--icon {
  width: 44px;
  height: 44px;
  padding: 0;
  justify-content: center;
}

/* Feature card */
.feature-card {
  background: var(--color-bg-mid);
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
  color: var(--color-accent);
  width: 32px;
  height: 32px;
  margin-bottom: var(--space-4);
}
.feature-card__title {
  font-size: 1.25rem;
  font-weight: 600;
  margin-bottom: var(--space-2);
}
.feature-card__desc {
  color: var(--color-text-dim);
  font-size: var(--text-sm);
  line-height: 1.6;
}

/* Code block / copy widget */
.copy-cmd {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  min-height: 44px;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text);
  position: relative;
  transition: background var(--duration-hover) ease,
              border-color var(--duration-hover) ease;
}
.copy-cmd:hover {
  border-color: var(--color-border-hover);
}
.copy-cmd code {
  font-family: inherit;
  background: none;
  padding: 0;
  color: inherit;
}
.copy-cmd__icon {
  width: 18px;
  height: 18px;
  color: var(--color-text-dim);
  flex-shrink: 0;
}
.copy-cmd__icon--check { display: none; color: var(--color-accent); }

.copy-cmd.is-copied {
  background: var(--color-accent-dim);
  border-color: var(--color-border-hover);
}
.copy-cmd.is-copied .copy-cmd__icon--copy { display: none; }
.copy-cmd.is-copied .copy-cmd__icon--check { display: inline-block; }
.copy-cmd.is-copied::after {
  content: attr(data-copy-feedback, 'Copied!');
  position: absolute;
  top: -28px;
  right: 0;
  padding: var(--space-1) var(--space-2);
  background: var(--color-accent);
  color: var(--color-bg-base);
  font-size: var(--text-xs);
  font-family: var(--font-display);
  font-weight: 600;
  border-radius: var(--radius-sm);
  pointer-events: none;
}

/* Reveal initial state — only when JS is loaded so noscript users see content */
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

/* Noscript */
.noscript-notice {
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-mid);
  color: var(--color-text-dim);
  font-size: var(--text-sm);
  text-align: center;
}
```

3. Note: the `attr()` fallback `attr(data-copy-feedback, 'Copied!')` has limited browser support; if necessary, set the toast text via JS. Implementation may simplify to `content: 'Copied!';` as a default and rely on `data-copy-feedback` being read by JS to update the pseudo via a CSS variable. Use the simpler approach:

Replace the `::after` rule with:
```css
.copy-cmd.is-copied::after {
  content: var(--copy-feedback, 'Copied!');
  /* …unchanged positioning/styles… */
}
```

JS will set `element.style.setProperty('--copy-feedback', '"' + text + '"')` when it adds `.is-copied` (handled in copy.js task).

**Tests to write:**
Manual verification (no automated test framework):
- Render a temporary HTML page with one `.btn--primary`, one `.btn--secondary`, one `.feature-card`, one `.copy-cmd`. Verify hover states match spec (lift, glow, color shift).
- Tab through interactive elements; focus ring (cyan, 2px outline-offset 2px) appears on each.
- Inspect `.feature-card` hover in dev tools: `transform: translateY(-4px)`, `box-shadow` matches `--shadow-hover`.

**Acceptance criteria:**
- `layout.css` provides `.container`, responsive `.grid--features`, and section padding.
- `components.css` defines `.btn`, `.btn--primary`, `.btn--secondary`, `.btn--icon`, `.feature-card`, `.copy-cmd` (with `.is-copied` state), `.noscript-notice`, and the `[data-reveal]`/`.is-revealed` reveal pattern (gated by `:root.js-loaded`).
- All interactive elements have a visible focus ring via `:focus-visible`.
- Touch targets are ≥44px tall/wide where applicable.

---

### task: motion-module

**Goal:** Implement `motion.js` to gate all animation on `prefers-reduced-motion` and expose preference helpers.

**Context:**
Reduced-motion users see static layout. The `motion.js` module sets `.no-motion` on `<html>` if the user prefers reduced motion. Other modules (`animations.js`) consume `prefersReducedMotion()` to decide whether to attach observers / start animations.

Module contract:
```js
// motion.js
export const prefersReducedMotion: () => boolean
export const onMotionPreferenceChange: (cb: (reduced: boolean) => void) => void
```

Side effect: must add/remove `no-motion` class on `<html>` reactively when the user toggles their OS preference.

CSS (already in `tokens.css`) handles `:root.no-motion * { animation: none !important; transition: none !important; }`.

**Files to create/modify:**
- `landingpage/assets/js/motion.js` — exports `prefersReducedMotion`, `onMotionPreferenceChange`, `initMotionGate`

**Implementation steps:**

1. Write `motion.js`:
```js
const MEDIA_QUERY = '(prefers-reduced-motion: reduce)';

const getMediaQueryList = () => {
  if (typeof window === 'undefined' || !window.matchMedia) return null;
  return window.matchMedia(MEDIA_QUERY);
};

export const prefersReducedMotion = () => {
  const mql = getMediaQueryList();
  return mql ? mql.matches : false;
};

const applyMotionClass = (reduced) => {
  const root = document.documentElement;
  if (reduced) {
    root.classList.add('no-motion');
  } else {
    root.classList.remove('no-motion');
  }
};

export const onMotionPreferenceChange = (cb) => {
  const mql = getMediaQueryList();
  if (!mql) return;
  const handler = (event) => cb(event.matches);
  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', handler);
  } else if (typeof mql.addListener === 'function') {
    mql.addListener(handler);
  }
};

export const initMotionGate = () => {
  applyMotionClass(prefersReducedMotion());
  onMotionPreferenceChange(applyMotionClass);
};
```

2. Verify the file uses ES module syntax (`export const`) compatible with `<script type="module">`.

**Tests to write:**
Manual verification:
- Open the page in Chrome dev tools → Rendering → "Emulate CSS media feature prefers-reduced-motion" → "reduce". Verify `<html>` gains `no-motion` class. Toggle off; class is removed.
- Console: `import('./assets/js/motion.js').then(m => console.log(m.prefersReducedMotion()))` returns `true` when emulation is on, `false` otherwise.

**Acceptance criteria:**
- `motion.js` exports `prefersReducedMotion()`, `onMotionPreferenceChange(cb)`, and `initMotionGate()`.
- `initMotionGate()` adds `no-motion` to `<html>` if user prefers reduced motion, and updates the class reactively when the preference changes.
- Falls back safely if `window.matchMedia` is undefined (no crash).
- Uses `addEventListener('change', …)` with `addListener` fallback for older Safari.

---

### task: animations-module

**Goal:** Implement `animations.js` providing scroll-triggered reveals, hero SVG lifecycle, and pipeline terminal animation.

**Context:**
`animations.js` imports from `motion.js` to skip animations when reduced motion is preferred.

Module contract:
```js
// animations.js
export const initReveals: (options?) => void
//   options: { rootMargin = '0px 0px -10% 0px', threshold = 0.15 }
//   - Select all [data-reveal]
//   - Attach one IntersectionObserver
//   - On entry: add .is-revealed; apply data-reveal-delay (ms) as inline transition-delay
//   - Disconnect per-element after first trigger (one-shot per spec FR-2)
//   - If prefersReducedMotion(): add .is-revealed immediately, skip observer

export const initHeroAnimation: () => void
//   - Hero SVG animation runs via CSS (animation-play-state: var(--hero-play-state))
//   - On document.visibilitychange: pause when hidden, resume when visible
//   - Skip if prefersReducedMotion()

export const initPipelineAnimation: () => void
//   - IntersectionObserver on #pipeline (does NOT disconnect — restarts on re-entry)
//   - On entry: add .is-running to #pipeline; on exit, remove it (so re-entry restarts)
//   - Reduced motion: add .is-running immediately, skip observer
```

IntersectionObserver settings (from arch-review FR-6 amendment):
- `rootMargin: '0px 0px -10% 0px'`
- `threshold: 0.15`

Hero pause mechanism: set CSS custom property `--hero-play-state` on `document.documentElement` to `'paused'` or `'running'`. The hero SVG CSS uses `animation-play-state: var(--hero-play-state)`.

**Files to create/modify:**
- `landingpage/assets/js/animations.js` — exports `initReveals`, `initHeroAnimation`, `initPipelineAnimation`

**Implementation steps:**

1. Write `animations.js`:
```js
import { prefersReducedMotion } from './motion.js';

const DEFAULT_REVEAL_OPTIONS = {
  rootMargin: '0px 0px -10% 0px',
  threshold: 0.15,
};

export const initReveals = (options = {}) => {
  const config = { ...DEFAULT_REVEAL_OPTIONS, ...options };
  const elements = document.querySelectorAll('[data-reveal]');

  if (prefersReducedMotion()) {
    elements.forEach((el) => el.classList.add('is-revealed'));
    return;
  }

  if (typeof IntersectionObserver === 'undefined') {
    elements.forEach((el) => el.classList.add('is-revealed'));
    return;
  }

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      const delay = el.dataset.revealDelay;
      if (delay) {
        el.style.transitionDelay = `${delay}ms`;
      }
      el.classList.add('is-revealed');
      obs.unobserve(el);
    });
  }, config);

  elements.forEach((el) => observer.observe(el));
};

const setHeroPlayState = (state) => {
  document.documentElement.style.setProperty('--hero-play-state', state);
};

export const initHeroAnimation = () => {
  if (prefersReducedMotion()) {
    setHeroPlayState('paused');
    return;
  }
  setHeroPlayState('running');
  document.addEventListener('visibilitychange', () => {
    setHeroPlayState(document.hidden ? 'paused' : 'running');
  });
};

export const initPipelineAnimation = () => {
  const pipeline = document.querySelector('#pipeline');
  if (!pipeline) return;

  if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
    pipeline.classList.add('is-running');
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        pipeline.classList.remove('is-running');
        // force reflow to restart CSS animation
        void pipeline.offsetWidth;
        pipeline.classList.add('is-running');
      } else {
        pipeline.classList.remove('is-running');
      }
    });
  }, { threshold: 0.25 });

  observer.observe(pipeline);
};
```

2. Verify ES module syntax. Confirm `import { prefersReducedMotion } from './motion.js';` resolves at runtime (relative path with `.js` extension is required for native modules).

**Tests to write:**
Manual verification with a temporary stub HTML:
- Place 3 `<div data-reveal>…</div>` blocks below the fold. Scroll to them; each gains `.is-revealed` once and stops re-triggering on subsequent scrolls.
- Use `data-reveal-delay="200"` on one element; verify inline `transition-delay: 200ms` is applied.
- Toggle `prefers-reduced-motion: reduce` in dev tools and reload. All `[data-reveal]` elements should have `.is-revealed` immediately at load.
- Hide the tab (cmd+T); verify `--hero-play-state` becomes `'paused'`. Return to tab; verify `'running'`.
- Place a `<section id="pipeline">` and verify `.is-running` toggles when entering/leaving viewport.

**Acceptance criteria:**
- `initReveals` adds `.is-revealed` once per element (one-shot via `obs.unobserve`).
- `data-reveal-delay` value is applied as inline `transition-delay` in ms.
- Reduced-motion users get `.is-revealed` immediately on all `[data-reveal]` elements.
- `initHeroAnimation` toggles `--hero-play-state` on `<html>` based on tab visibility, and pauses entirely under reduced motion.
- `initPipelineAnimation` toggles `.is-running` on `#pipeline` when it enters/leaves the viewport (re-triggers each entry).
- Module imports resolve without errors when loaded via `<script type="module">`.

---

### task: copy-module

**Goal:** Implement `copy.js` for click-to-copy on `[data-copy]` elements with Clipboard API + `execCommand` fallback and 2-second feedback toast.

**Context:**
Module contract:
```js
// copy.js
export const initCopyButtons: () => void
//   - Select all [data-copy]
//   - On click:
//       1. Read element.dataset.copy
//       2. copyToClipboard(text):
//            try navigator.clipboard.writeText(text)
//            catch: execCommand fallback
//       3. Add .is-copied to element; set --copy-feedback CSS var to data-copy-feedback or 'Copied!'
//       4. setTimeout 2000ms → remove .is-copied
//   - feedback text from data-copy-feedback or default "Copied!"
```

The fallback path matters: Clipboard API requires HTTPS or localhost; `file://` users hit restrictions. `execCommand('copy')` is deprecated but universal.

CSS toast uses `content: var(--copy-feedback, 'Copied!')`. JS sets `element.style.setProperty('--copy-feedback', '"' + text + '"')` (quotes required for CSS `content`).

Feedback duration: 2000ms exactly.

**Files to create/modify:**
- `landingpage/assets/js/copy.js` — exports `initCopyButtons`

**Implementation steps:**

1. Write `copy.js`:
```js
const FEEDBACK_DURATION_MS = 2000;
const DEFAULT_FEEDBACK = 'Copied!';

const copyViaExecCommand = (text) => {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'absolute';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  let succeeded = false;
  try {
    succeeded = document.execCommand('copy');
  } catch {
    succeeded = false;
  }
  document.body.removeChild(textarea);
  return succeeded;
};

const copyToClipboard = async (text) => {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to execCommand
    }
  }
  return copyViaExecCommand(text);
};

const showCopiedState = (element, feedback) => {
  element.style.setProperty('--copy-feedback', `"${feedback}"`);
  element.classList.add('is-copied');
  if (element._copyTimer) {
    clearTimeout(element._copyTimer);
  }
  element._copyTimer = setTimeout(() => {
    element.classList.remove('is-copied');
    element._copyTimer = null;
  }, FEEDBACK_DURATION_MS);
};

export const initCopyButtons = () => {
  const buttons = document.querySelectorAll('[data-copy]');
  buttons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      const text = btn.dataset.copy;
      if (!text) return;
      const feedback = btn.dataset.copyFeedback || DEFAULT_FEEDBACK;
      const success = await copyToClipboard(text);
      if (success) {
        showCopiedState(btn, feedback);
      }
    });
  });
};
```

2. Verify ES module syntax.

**Tests to write:**
Manual verification with a stub:
- HTML: `<button class="copy-cmd" data-copy="hello world"><code>hello world</code></button>`
- Click button → `.is-copied` added, "Copied!" toast appears for 2s, then disappears. Clipboard contains "hello world".
- Add `data-copy-feedback="Got it!"` → toast shows "Got it!".
- Open via `file://`: click still copies (via execCommand fallback) and shows feedback.
- Repeated click before 2s elapses: timer resets, toast stays visible 2s from latest click.

**Acceptance criteria:**
- `initCopyButtons()` attaches click handlers to every `[data-copy]` element.
- On click, copies `dataset.copy` value via Clipboard API, falling back to `execCommand` on failure or insecure context.
- Adds `.is-copied` for exactly 2000ms; sets `--copy-feedback` CSS var to the feedback text (escaped with quotes for CSS `content`).
- Repeated clicks before timeout reset the timer cleanly (no stuck `.is-copied`).
- Empty `data-copy` value is a no-op.

---

### task: main-entry

**Goal:** Implement `main.js` as the entry point that orchestrates module init and projects repo URL / quick-start command into the DOM.

**Context:**
Module orchestration order (from design):
1. `initMotionGate()` (motion.js)
2. `initReveals()` (animations.js)
3. `initHeroAnimation()` (animations.js)
4. `initPipelineAnimation()` (animations.js)
5. `initCopyButtons()` (copy.js)

Constants live at the top of `main.js` as the single source of truth:
```js
const REPO_URL = 'https://github.com/onpaj/AgentHarness';
const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';
```

These constants must be projected into the DOM at init:
- All elements with `data-repo-url` attribute get `href = REPO_URL`.
- All elements with `data-quickstart` attribute get their `data-copy` and inner `<code>` text set to `QUICKSTART_CMD`.

Before init, set `document.documentElement.classList.add('js-loaded')` so the reveal initial state (opacity:0, translateY) only applies when JS is running. This ensures noscript users see content normally.

DOMContentLoaded gating: the script tag is `defer` so the DOM is ready when the module executes.

**Files to create/modify:**
- `landingpage/assets/js/main.js` — entry point

**Implementation steps:**

1. Write `main.js`:
```js
import { initMotionGate } from './motion.js';
import { initReveals, initHeroAnimation, initPipelineAnimation } from './animations.js';
import { initCopyButtons } from './copy.js';

const REPO_URL = 'https://github.com/onpaj/AgentHarness';
const QUICKSTART_CMD = 'pip install agentharness && agentharness brainstorm';

const projectRepoUrl = () => {
  document.querySelectorAll('[data-repo-url]').forEach((el) => {
    el.setAttribute('href', REPO_URL);
  });
};

const projectQuickstartCommand = () => {
  document.querySelectorAll('[data-quickstart]').forEach((el) => {
    el.setAttribute('data-copy', QUICKSTART_CMD);
    const code = el.querySelector('code');
    if (code) {
      code.textContent = `$ ${QUICKSTART_CMD}`;
    }
  });
};

const init = () => {
  document.documentElement.classList.add('js-loaded');
  projectRepoUrl();
  projectQuickstartCommand();
  initMotionGate();
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

2. Note: `projectQuickstartCommand` must run before `initCopyButtons` so `data-copy` attributes are populated before click handlers attach.

**Tests to write:**
Manual verification:
- Stub HTML with `<a data-repo-url>GitHub</a>` and `<button data-quickstart><code></code></button>`. Open in browser. The `<a>` href becomes the repo URL; the `<button>` gets `data-copy` set and `<code>` text becomes `$ pip install agentharness && agentharness brainstorm`.
- Verify `<html>` has `js-loaded` class after page load.
- Disable JS in dev tools and reload — no `js-loaded` class; `[data-reveal]` initial state from `:root.js-loaded` selector does not apply, so all content is visible.

**Acceptance criteria:**
- `main.js` imports and orchestrates all four init functions in the documented order.
- `REPO_URL` and `QUICKSTART_CMD` constants live at the top of the file (single source of truth).
- `js-loaded` class is added to `<html>` before reveal observers attach.
- Repo URL is projected to all `[data-repo-url]` elements as `href`.
- Quick-start command is projected to all `[data-quickstart]` elements (sets `data-copy` and inner `<code>` text with `$ ` prefix).
- Init runs after DOMContentLoaded (or immediately if already past that state).

---

### task: section-styles

**Goal:** Implement section-specific CSS for header, hero, how-it-works, features, pipeline, cta, footer.

**Context:**
Final CSS file in load order. Section padding already comes from `section { padding-block: var(--section-padding-y); }` in layout.css.

Layout per design wireframes:

**Header:** Sticky top, transparent → `backdrop-filter: blur(12px)` when scrolled past hero. Wordmark left, GitHub CTA right.

**Hero:** 100vh on desktop. Two-column grid (text left, SVG right) at ≥1024px; stacked on mobile. Headline uses `var(--text-hero)` clamp. Subheadline `var(--color-text-dim)`. Primary CTA + copy-cmd row.

**How-it-works:** Three steps. On desktop (≥768px) horizontal flex with arrows between; on mobile (<768px) vertical stack with downward arrows. Stagger reveals via `data-reveal-delay`: 0, 100, 200, 300 (arrows alternate with steps).

**Features:** Uses `.grid--features` from layout.css (1/2/3 columns by breakpoint).

**Pipeline:** Dark `var(--color-bg-surface)` panel, monospace font, terminal-style. Lines stream in via CSS keyframes when `#pipeline.is-running` is set. Cursor blink animation. Pre-formatted whitespace; horizontally scrollable on mobile.

**CTA section:** Centered headline + button + copy-cmd.

**Footer:** Single row links + license note.

Hero SVG animation: six nodes (analyst → architect → designer → planner → developer → reviewer). Each `<circle>` pulses brightening to `var(--color-accent)` then dimming, with 0.5s offsets between nodes, looping. `animation-play-state: var(--hero-play-state, running)`. Static frame under reduced motion: 40% opacity, edges fully drawn.

Pipeline terminal lines: each `.pipeline-line` starts with `opacity: 0; transform: translateY(4px);`. When `#pipeline.is-running .pipeline-line` is matched, `animation: stream-in 0.3s forwards; animation-delay: calc(var(--line-index) * 400ms);`. Cursor `.pipeline-cursor::after` blinks via `animation: blink 1s step-end infinite`.

Responsive breakpoints: 375 / 768 / 1024 / 1440.

**Files to create/modify:**
- `landingpage/assets/css/sections.css` — header, hero, how-it-works, features, pipeline, cta, footer, hero SVG animation, pipeline animation keyframes

**Implementation steps:**

1. Write `sections.css`:
```css
/* ---------- Header ---------- */
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
.site-header__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.site-header__wordmark {
  font-weight: 700;
  font-size: 1.125rem;
  letter-spacing: -0.01em;
}

/* ---------- Hero ---------- */
.hero {
  min-height: 100vh;
  display: flex;
  align-items: center;
  padding-block: var(--space-16);
}
.hero__inner {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-12);
  align-items: center;
}
@media (min-width: 1024px) {
  .hero__inner {
    grid-template-columns: 1.1fr 1fr;
    gap: var(--space-16);
  }
}
.hero__headline {
  font-size: var(--text-hero);
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.02em;
  margin-bottom: var(--space-6);
}
.hero__sub {
  font-size: 1.125rem;
  color: var(--color-text-dim);
  line-height: 1.6;
  margin-bottom: var(--space-8);
  max-width: 38rem;
}
.hero__ctas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: center;
}
.hero__visual {
  width: 100%;
  max-width: 520px;
  margin-inline: auto;
}
@media (max-width: 1023px) {
  .hero__visual { transform: scale(0.85); transform-origin: center; }
}

/* ---------- Hero SVG animation ---------- */
.hero-pipeline-node {
  fill: var(--color-bg-mid);
  stroke: var(--color-accent);
  stroke-width: 1.5;
  opacity: 0.4;
  animation: hero-node-pulse 4s ease-in-out infinite;
  animation-play-state: var(--hero-play-state, running);
}
.hero-pipeline-node:nth-child(1) { animation-delay: 0s; }
.hero-pipeline-node:nth-child(2) { animation-delay: 0.5s; }
.hero-pipeline-node:nth-child(3) { animation-delay: 1.0s; }
.hero-pipeline-node:nth-child(4) { animation-delay: 1.5s; }
.hero-pipeline-node:nth-child(5) { animation-delay: 2.0s; }
.hero-pipeline-node:nth-child(6) { animation-delay: 2.5s; }
.hero-pipeline-edge {
  stroke: var(--color-border);
  stroke-width: 1.5;
  fill: none;
}
@keyframes hero-node-pulse {
  0%, 100% { opacity: 0.4; fill: var(--color-bg-mid); }
  50%      { opacity: 1;   fill: var(--color-accent); }
}
:root.no-motion .hero-pipeline-node {
  opacity: 0.4;
  animation: none;
}

/* ---------- How it works ---------- */
.steps {
  display: grid;
  gap: var(--space-8);
  grid-template-columns: 1fr;
}
@media (min-width: 768px) {
  .steps {
    grid-template-columns: 1fr auto 1fr auto 1fr;
    align-items: stretch;
  }
}
.step-card {
  background: var(--color-bg-mid);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
}
.step-card__icon {
  color: var(--color-accent);
  width: 32px;
  height: 32px;
  margin-bottom: var(--space-4);
}
.step-card__title {
  font-size: 1.25rem;
  font-weight: 600;
  margin-bottom: var(--space-2);
}
.step-card__desc {
  color: var(--color-text-dim);
  font-size: var(--text-sm);
  line-height: 1.6;
}
.step-arrow {
  color: var(--color-text-dim);
  align-self: center;
  display: flex;
  align-items: center;
  justify-content: center;
}
@media (max-width: 767px) {
  .step-arrow { transform: rotate(90deg); justify-self: center; }
}

/* ---------- Section heading ---------- */
.section-heading {
  font-size: var(--text-h2);
  font-weight: 700;
  letter-spacing: -0.01em;
  margin-bottom: var(--space-4);
  text-align: center;
}
.section-sub {
  color: var(--color-text-dim);
  text-align: center;
  margin-bottom: var(--space-12);
  max-width: 40rem;
  margin-inline: auto;
}

/* ---------- Pipeline (terminal) ---------- */
.pipeline-terminal {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow-x: auto;
  white-space: pre;
  line-height: 1.7;
}
.pipeline-line {
  opacity: 0;
  transform: translateY(4px);
}
#pipeline.is-running .pipeline-line {
  animation: stream-in 0.3s forwards;
  animation-delay: calc(var(--line-index, 0) * 400ms);
}
.pipeline-line__status--ok { color: var(--color-accent); }
.pipeline-line__status--progress { color: var(--color-text-dim); }
.pipeline-cursor {
  color: var(--color-accent);
  animation: blink 1s step-end infinite;
}
@keyframes stream-in {
  to { opacity: 1; transform: translateY(0); }
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
:root.no-motion .pipeline-line { opacity: 1; transform: none; animation: none; }
:root.no-motion .pipeline-cursor { animation: none; opacity: 1; }

/* ---------- CTA ---------- */
.cta {
  text-align: center;
}
.cta__headline {
  font-size: var(--text-h2);
  font-weight: 700;
  letter-spacing: -0.01em;
  margin-bottom: var(--space-8);
}
.cta__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: center;
  justify-content: center;
}

/* ---------- Footer ---------- */
.site-footer {
  border-top: 1px solid var(--color-border);
  padding-block: var(--space-8);
  color: var(--color-text-dim);
  font-size: var(--text-sm);
}
.site-footer__inner {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: center;
  justify-content: space-between;
}
```

**Tests to write:**
Manual verification at each breakpoint (375, 768, 1024, 1440):
- Hero is full-viewport height on ≥1024px. Headline uses fluid `clamp()` sizing.
- Steps render horizontally on ≥768px with arrows between; vertically stacked on <768px with downward arrow.
- Features grid is 1/2/3 columns by breakpoint.
- Pipeline section renders on `--color-bg-surface` with monospace font, no horizontal overflow on the body (pipeline itself scrolls internally on mobile).
- Hero SVG nodes pulse in sequence at 0.5s offsets; under reduced motion they hold at 40% opacity.
- Pipeline lines stream in when `#pipeline.is-running` is applied; cursor blinks.

**Acceptance criteria:**
- All seven section blocks have CSS rules: header, hero, how-it-works, features (uses existing `.grid--features`), pipeline, cta, footer.
- Hero animation uses `--hero-play-state` for play/pause control.
- Pipeline animation uses `#pipeline.is-running` selector to gate keyframes.
- Reduced-motion overrides freeze hero nodes at 40% opacity, render pipeline lines fully visible without animation, stop cursor blink.
- No horizontal scrolling on the body at any breakpoint between 375px and 1440px.

---

### task: index-html

**Goal:** Build the single `index.html` containing semantic markup for header, hero, how-it-works, features, pipeline, cta, footer, plus head meta tags, inlined hero SVG, inlined feature/step icons, and noscript notice.

**Context:**
Single file, target ~400-500 lines, max 600 (per arch decision). Semantic HTML: `<header>`, `<main>`, `<section>`, `<footer>`. Proper heading hierarchy.

`<head>` meta schema:
```html
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgentHarness — Delegate the grind. Reclaim your time.</title>
<meta name="description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
<link rel="canonical" href="https://github.com/onpaj/AgentHarness">
<meta property="og:type"  content="website">
<meta property="og:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
<meta property="og:description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
<meta property="og:image" content="assets/img/og-image.png">
<meta property="og:url"   content="https://github.com/onpaj/AgentHarness">
<meta name="twitter:card"  content="summary_large_image">
<meta name="twitter:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
<meta name="twitter:description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
<meta name="twitter:image" content="assets/img/og-image.png">
<link rel="icon" type="image/x-icon"  href="assets/img/favicon.ico">
<link rel="icon" type="image/svg+xml" href="assets/img/favicon.svg">
<link rel="apple-touch-icon"          href="assets/img/apple-touch-icon.png">
```

CSS link order in `<head>`:
```html
<link rel="stylesheet" href="assets/css/reset.css">
<link rel="stylesheet" href="assets/css/tokens.css">
<link rel="stylesheet" href="assets/css/layout.css">
<link rel="stylesheet" href="assets/css/components.css">
<link rel="stylesheet" href="assets/css/sections.css">
```

Script tag (just before `</body>`):
```html
<script type="module" src="assets/js/main.js" defer></script>
```

`<html lang="en">` and `data-repo-url` projection target on `<body>` (the script populates `[data-repo-url]` href values; for `<body>` itself we'll add a `data-repo-url=""` attribute to make the URL discoverable in DOM).

Noscript block immediately after `<body>` open tag:
```html
<noscript>
  <div class="noscript-notice">
    JavaScript is disabled — animations are off, but all content and links work normally.
  </div>
</noscript>
```

External links must use `target="_blank" rel="noopener noreferrer"`.

Hero SVG (inlined): six `<circle class="hero-pipeline-node">` nodes connected by edges, ordered analyst → architect → designer → planner → developer → reviewer. Wrapped in a labelled `<svg>` with `<title>` and `<desc>` for accessibility.

Feature card content (6 cards):
1. Multi-agent pipeline — "Analyst, architect, designer, planner, developer, reviewer. A purpose-built chain of Claude agents picks up the work where each handoff makes sense."
2. Per-task review loop — "Every developer task is reviewed before the next one starts. Revisions cycle until the work meets the bar — or the feature fails fast."
3. Pluggable backends — "Run on Azure Blob Storage and Queues, or use GitHub Issues and branches as your work queue. Switch with one env var."
4. Zero babysitting — "A single observer process polls all queues, spawns isolated subprocesses per task, and runs the whole pipeline autonomously."
5. Per-agent context files — "Each agent gets curated context — relevant docs, code, and constraints — without bloating every prompt."
6. Serial task dispatch — "Developer tasks run one at a time so they never collide on the same file. Parallelism happens between features, not within them."

Step content (3 steps):
1. Brainstorm — "Describe the feature in a short conversation. AgentHarness writes it up as a brief and submits it to the pipeline."
2. Agents work — "An analyst, architect, designer, planner, developers, and reviewer take it from there. Each agent has a clear job and clear hand-off."
3. Code ships — "Implementation lands as commits on a branch ready for review. You read the diff, not write it."

Pipeline terminal lines (canonical):
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

Lucide icons (MIT) inlined as SVG, using `currentColor`:
- workflow → multi-agent pipeline
- repeat → per-task review
- layers → pluggable backends
- bot → zero babysitting
- file-text → context files
- list-ordered → serial dispatch
- message-square → step 1
- cpu → step 2
- git-pull-request → step 3

CTAs (primary buttons + copy-cmd buttons) use `[data-repo-url]` and `[data-quickstart]` projection. The `<a>` for "View on GitHub" must include `target="_blank" rel="noopener noreferrer"` and a placeholder `href="#"` (overwritten by main.js).

**Files to create/modify:**
- `landingpage/index.html` — single-page document
- `landingpage/assets/img/icons/.gitkeep` — keep dir; icons are inlined into HTML, not loaded as files (per arch decision)

**Implementation steps:**

1. Write `index.html` with the following structure (~450 lines total):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgentHarness — Delegate the grind. Reclaim your time.</title>
  <meta name="description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
  <link rel="canonical" href="https://github.com/onpaj/AgentHarness">

  <meta property="og:type"  content="website">
  <meta property="og:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
  <meta property="og:description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
  <meta property="og:image" content="assets/img/og-image.png">
  <meta property="og:url"   content="https://github.com/onpaj/AgentHarness">

  <meta name="twitter:card"  content="summary_large_image">
  <meta name="twitter:title" content="AgentHarness — Delegate the grind. Reclaim your time.">
  <meta name="twitter:description" content="AgentHarness runs a chain of Claude agents — analyst, architect, planner, developer, reviewer — to build your features autonomously. Describe it once. Watch it ship.">
  <meta name="twitter:image" content="assets/img/og-image.png">

  <link rel="icon" type="image/x-icon"  href="assets/img/favicon.ico">
  <link rel="icon" type="image/svg+xml" href="assets/img/favicon.svg">
  <link rel="apple-touch-icon"          href="assets/img/apple-touch-icon.png">

  <link rel="stylesheet" href="assets/css/reset.css">
  <link rel="stylesheet" href="assets/css/tokens.css">
  <link rel="stylesheet" href="assets/css/layout.css">
  <link rel="stylesheet" href="assets/css/components.css">
  <link rel="stylesheet" href="assets/css/sections.css">
</head>
<body data-repo-url="">
  <noscript>
    <div class="noscript-notice">
      JavaScript is disabled — animations are off, but all content and links work normally.
    </div>
  </noscript>

  <header class="site-header">
    <div class="container site-header__inner">
      <a href="#hero" class="site-header__wordmark">AgentHarness</a>
      <a class="btn btn--secondary"
         href="#"
         data-repo-url
         target="_blank"
         rel="noopener noreferrer"
         aria-label="View AgentHarness on GitHub">
        View on GitHub
        <!-- inline arrow icon -->
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 17L17 7M17 7H8M17 7v9"/></svg>
      </a>
    </div>
  </header>

  <main>
    <!-- ============ HERO ============ -->
    <section id="hero" class="hero">
      <div class="container hero__inner">
        <div class="hero__copy">
          <h1 class="hero__headline" data-reveal>Delegate the grind.<br>Reclaim your time.</h1>
          <p class="hero__sub" data-reveal data-reveal-delay="100">
            A chain of Claude agents builds your features while you focus on what matters.
            Brainstorm, hand off, ship.
          </p>
          <div class="hero__ctas" data-reveal data-reveal-delay="200">
            <a class="btn btn--primary"
               href="#"
               data-repo-url
               target="_blank"
               rel="noopener noreferrer">
              Get started on GitHub
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 17L17 7M17 7H8M17 7v9"/></svg>
            </a>
            <button class="copy-cmd"
                    type="button"
                    data-quickstart
                    data-copy=""
                    aria-label="Copy quick-start command">
              <code>$ pip install agentharness && agentharness brainstorm</code>
              <svg class="copy-cmd__icon copy-cmd__icon--copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <svg class="copy-cmd__icon copy-cmd__icon--check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
          </div>
        </div>

        <div class="hero__visual" data-reveal data-reveal-delay="100">
          <svg viewBox="0 0 520 120" role="img" aria-labelledby="heroVizTitle heroVizDesc" xmlns="http://www.w3.org/2000/svg">
            <title id="heroVizTitle">Agent pipeline animation</title>
            <desc id="heroVizDesc">Six agent nodes — analyst, architect, designer, planner, developer, reviewer — pulse in sequence to visualize the autonomous pipeline.</desc>
            <line class="hero-pipeline-edge" x1="40"  y1="60" x2="120" y2="60"/>
            <line class="hero-pipeline-edge" x1="120" y1="60" x2="200" y2="60"/>
            <line class="hero-pipeline-edge" x1="200" y1="60" x2="280" y2="60"/>
            <line class="hero-pipeline-edge" x1="280" y1="60" x2="360" y2="60"/>
            <line class="hero-pipeline-edge" x1="360" y1="60" x2="440" y2="60"/>
            <circle class="hero-pipeline-node" cx="40"  cy="60" r="14"/>
            <circle class="hero-pipeline-node" cx="120" cy="60" r="14"/>
            <circle class="hero-pipeline-node" cx="200" cy="60" r="14"/>
            <circle class="hero-pipeline-node" cx="280" cy="60" r="14"/>
            <circle class="hero-pipeline-node" cx="360" cy="60" r="14"/>
            <circle class="hero-pipeline-node" cx="440" cy="60" r="14"/>
          </svg>
        </div>
      </div>
    </section>

    <!-- ============ HOW IT WORKS ============ -->
    <section id="how-it-works">
      <div class="container">
        <h2 class="section-heading" data-reveal>How it works</h2>
        <p class="section-sub" data-reveal data-reveal-delay="100">
          Three steps from idea to shipped code.
        </p>
        <div class="steps">
          <div class="step-card" data-reveal data-reveal-delay="0">
            <!-- lucide message-square -->
            <svg class="step-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <h3 class="step-card__title">1. Brainstorm</h3>
            <p class="step-card__desc">Describe the feature in a short conversation. AgentHarness writes it up as a brief and submits it to the pipeline.</p>
          </div>
          <span class="step-arrow" aria-hidden="true" data-reveal data-reveal-delay="150">
            <svg width="32" height="16" viewBox="0 0 32 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M0 8h28M22 2l6 6-6 6"/></svg>
          </span>
          <div class="step-card" data-reveal data-reveal-delay="200">
            <!-- lucide cpu -->
            <svg class="step-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></svg>
            <h3 class="step-card__title">2. Agents work</h3>
            <p class="step-card__desc">An analyst, architect, designer, planner, developers, and reviewer take it from there. Each agent has a clear job and clear hand-off.</p>
          </div>
          <span class="step-arrow" aria-hidden="true" data-reveal data-reveal-delay="350">
            <svg width="32" height="16" viewBox="0 0 32 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M0 8h28M22 2l6 6-6 6"/></svg>
          </span>
          <div class="step-card" data-reveal data-reveal-delay="400">
            <!-- lucide git-pull-request -->
            <svg class="step-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
            <h3 class="step-card__title">3. Code ships</h3>
            <p class="step-card__desc">Implementation lands as commits on a branch ready for review. You read the diff, not write it.</p>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ FEATURES ============ -->
    <section id="features">
      <div class="container">
        <h2 class="section-heading" data-reveal>Built for autonomy</h2>
        <p class="section-sub" data-reveal data-reveal-delay="100">
          Six design choices that make the pipeline reliable enough to leave alone.
        </p>
        <div class="grid grid--features">
          <!-- Card 1 -->
          <article class="feature-card" data-reveal data-reveal-delay="0">
            <svg class="feature-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><path d="M9 6h12M9 18h6M15 6v12"/></svg>
            <h3 class="feature-card__title">Multi-agent pipeline</h3>
            <p class="feature-card__desc">Analyst, architect, designer, planner, developer, reviewer. A purpose-built chain of Claude agents picks up the work where each handoff makes sense.</p>
          </article>
          <!-- Card 2 -->
          <article class="feature-card" data-reveal data-reveal-delay="100">
            <svg class="feature-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
            <h3 class="feature-card__title">Per-task review loop</h3>
            <p class="feature-card__desc">Every developer task is reviewed before the next one starts. Revisions cycle until the work meets the bar — or the feature fails fast.</p>
          </article>
          <!-- Card 3 -->
          <article class="feature-card" data-reveal data-reveal-delay="200">
            <svg class="feature-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
            <h3 class="feature-card__title">Pluggable backends</h3>
            <p class="feature-card__desc">Run on Azure Blob Storage and Queues, or use GitHub Issues and branches as your work queue. Switch with one env var.</p>
          </article>
          <!-- Card 4 -->
          <article class="feature-card" data-reveal data-reveal-delay="0">
            <svg class="feature-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>
            <h3 class="feature-card__title">Zero babysitting</h3>
            <p class="feature-card__desc">A single observer process polls all queues, spawns isolated subprocesses per task, and runs the whole pipeline autonomously.</p>
          </article>
          <!-- Card 5 -->
          <article class="feature-card" data-reveal data-reveal-delay="100">
            <svg class="feature-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
            <h3 class="feature-card__title">Per-agent context files</h3>
            <p class="feature-card__desc">Each agent gets curated context — relevant docs, code, and constraints — without bloating every prompt.</p>
          </article>
          <!-- Card 6 -->
          <article class="feature-card" data-reveal data-reveal-delay="200">
            <svg class="feature-card__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="10" y1="6" x2="21" y2="6"/><line x1="10" y1="12" x2="21" y2="12"/><line x1="10" y1="18" x2="21" y2="18"/><path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/></svg>
            <h3 class="feature-card__title">Serial task dispatch</h3>
            <p class="feature-card__desc">Developer tasks run one at a time so they never collide on the same file. Parallelism happens between features, not within them.</p>
          </article>
        </div>
      </div>
    </section>

    <!-- ============ PIPELINE ============ -->
    <section id="pipeline">
      <div class="container">
        <h2 class="section-heading" data-reveal>The pipeline at work</h2>
        <p class="section-sub" data-reveal data-reveal-delay="100">
          Live output from a real <code>agentharness observe</code> run.
        </p>
        <div class="pipeline-terminal" data-reveal>
<div class="pipeline-line" style="--line-index:0"><span class="pipeline-line__status--progress">[12:01:04]  analyst         → analyzing        feat-abc123</span></div>
<div class="pipeline-line" style="--line-index:1"><span class="pipeline-line__status--ok">[12:01:22]  analyst         ✓ complete         18s</span></div>
<div class="pipeline-line" style="--line-index:2"><span class="pipeline-line__status--progress">[12:01:23]  architect       → analyzing</span></div>
<div class="pipeline-line" style="--line-index:3"><span class="pipeline-line__status--ok">[12:01:55]  architect       ✓ complete         32s</span></div>
<div class="pipeline-line" style="--line-index:4"><span class="pipeline-line__status--progress">[12:01:56]  planner         → planning</span></div>
<div class="pipeline-line" style="--line-index:5"><span class="pipeline-line__status--ok">[12:02:14]  planner         ✓ complete         18s  3 tasks</span></div>
<div class="pipeline-line" style="--line-index:6"><span class="pipeline-line__status--progress">[12:02:15]  developer[1]    → in_progress</span></div>
<div class="pipeline-line" style="--line-index:7"><span class="pipeline-line__status--ok">[12:03:44]  reviewer[1]     ✓ PASS</span></div>
<div class="pipeline-line" style="--line-index:8"><span class="pipeline-line__status--progress">[12:03:45]  developer[2]    → in_progress</span></div>
<div class="pipeline-line" style="--line-index:9"><span class="pipeline-cursor">█</span></div>
        </div>
      </div>
    </section>

    <!-- ============ CTA ============ -->
    <section id="cta" class="cta">
      <div class="container">
        <h2 class="cta__headline" data-reveal>Stop writing boilerplate. Start shipping.</h2>
        <div class="cta__row" data-reveal data-reveal-delay="100">
          <a class="btn btn--primary"
             href="#"
             data-repo-url
             target="_blank"
             rel="noopener noreferrer">
            View on GitHub
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 17L17 7M17 7H8M17 7v9"/></svg>
          </a>
          <button class="copy-cmd"
                  type="button"
                  data-quickstart
                  data-copy=""
                  aria-label="Copy quick-start command">
            <code>$ pip install agentharness && agentharness brainstorm</code>
            <svg class="copy-cmd__icon copy-cmd__icon--copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <svg class="copy-cmd__icon copy-cmd__icon--check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
          </button>
        </div>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container site-footer__inner">
      <span>AgentHarness · MIT License</span>
      <a href="#" data-repo-url target="_blank" rel="noopener noreferrer">GitHub ↗</a>
    </div>
  </footer>

  <script type="module" src="assets/js/main.js" defer></script>
</body>
</html>
```

2. Sanity-check that the file is below 600 lines. If it exceeds, the spec/arch decision says split — but with this content, it should land around 350-450 lines.

3. Place a placeholder `assets/img/og-image.png` (1×1 transparent PNG or any placeholder) so the `<meta property="og:image">` doesn't 404 in development. Real designer asset replaces it before launch.

**Tests to write:**
Manual verification:
- Open `landingpage/index.html` directly in browser (`file://`). Page renders without console errors.
- HTML validator (https://validator.w3.org/) passes with zero errors.
- Heading hierarchy: one `<h1>` (hero), `<h2>` for each section heading, `<h3>` for cards. No skipped levels.
- All external links have `target="_blank" rel="noopener noreferrer"`.
- View source: no inline `style=""` (except `--line-index` values which are required) and no inline `onclick=""`.
- Disable JavaScript: page renders all content, headings, links, and copy buttons (clicking does nothing without JS, but text is selectable). Noscript notice appears.
- Lighthouse audit (desktop): performance ≥90, accessibility ≥90, best practices ≥90, SEO ≥90.

**Acceptance criteria:**
- `index.html` contains semantic `<header>`, `<main>` with five `<section>` blocks (`#hero`, `#how-it-works`, `#features`, `#pipeline`, `#cta`), and `<footer>`.
- All meta tags from the head schema are present and use the documented copy.
- Five CSS files linked in correct cascade order: reset → tokens → layout → components → sections.
- Single `<script type="module" src="assets/js/main.js" defer>` at end of body.
- Hero SVG inlined with `<title>`/`<desc>` for accessibility, six nodes, five connecting edges.
- Six feature cards with inlined Lucide-style SVG icons colored via `currentColor`.
- Three step cards with arrows between, on horizontal layout for desktop, stacked for mobile.
- Pipeline section contains the nine canonical terminal lines with `--line-index` set per line, plus blinking cursor line.
- All `[data-quickstart]` buttons have empty `data-copy=""` (populated by main.js at init).
- All `[data-repo-url]` anchors have `href="#"` placeholder (populated by main.js at init).
- Noscript notice immediately follows `<body>` open tag.
- Total line count under 600 lines.
- No HTML validation errors.
- Page is fully readable with JavaScript disabled.

---

### task: og-image-and-favicons

**Goal:** Add placeholder OG image and favicon assets so meta references resolve and social previews don't 404.

**Context:**
Spec NFR-5 requires `<title>`, meta description, OG tags, Twitter Card tags, and favicons (16, 32, 180 sizes for Apple touch). OG image is 1200×630 PNG. Risk register flags missing OG image at launch as a medium-severity issue and proposes shipping a placeholder generated from the hero SVG to a 1200×630 PNG.

This task ships **placeholders** so the meta references resolve cleanly. Final designer-delivered assets replace them before launch (out-of-band, not blocking).

Files referenced in `index.html`:
- `assets/img/og-image.png` — 1200×630
- `assets/img/favicon.ico`
- `assets/img/favicon.svg`
- `assets/img/apple-touch-icon.png` — 180×180

**Files to create/modify:**
- `landingpage/assets/img/og-image.png` — 1200×630 dark navy placeholder with white "AgentHarness" wordmark
- `landingpage/assets/img/favicon.ico` — multi-size ICO (16, 32, 48)
- `landingpage/assets/img/favicon.svg` — single SVG mark
- `landingpage/assets/img/apple-touch-icon.png` — 180×180 PNG

**Implementation steps:**

1. Create `favicon.svg` with a minimal mark — a single accent-colored "A" or pipeline glyph. Inline content:
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#0a0f1e"/>
  <circle cx="16" cy="32" r="6" fill="#00d4ff"/>
  <circle cx="32" cy="32" r="6" fill="#00d4ff" opacity="0.7"/>
  <circle cx="48" cy="32" r="6" fill="#00d4ff" opacity="0.4"/>
</svg>
```

2. Generate `og-image.png` (1200×630). Two acceptable approaches:
   - **Option A (preferred):** use a one-off Python script (e.g., `Pillow`) or a headless Chrome screenshot of an HTML template to generate the PNG. Commit the generated PNG; do not commit the generator.
   - **Option B (faster):** create a 1200×630 PNG with a flat `#0a0f1e` background, the wordmark "AgentHarness" in white sans-serif at the top-left, and the headline "Delegate the grind. Reclaim your time." centered. Three accent cyan dots on the right half evoke the pipeline.

   The placeholder must be a real PNG (not a 1×1 stub) so social-share previews render correctly during development. Approximate file size: 30-80 KB.

3. Generate `favicon.ico` from `favicon.svg`. Convert with ImageMagick or a similar one-off tool; commit only the ICO. Sizes embedded: 16×16, 32×32, 48×48.

4. Generate `apple-touch-icon.png` (180×180 PNG) from `favicon.svg`.

5. Verify all four files exist and are referenced correctly from `index.html`.

**Tests to write:**
Manual verification:
- Open `landingpage/index.html` in browser. No 404s in network panel for `og-image.png`, `favicon.ico`, `favicon.svg`, `apple-touch-icon.png`.
- Drop the page URL into a social-share preview tool (e.g., https://www.opengraph.xyz/) — image renders, headline and description appear.
- Browser tab shows the favicon (cyan pipeline dots on dark background).
- iOS "Add to Home Screen" preview shows the apple-touch-icon (verify in Safari device emulator).

**Acceptance criteria:**
- `assets/img/og-image.png` is a 1200×630 PNG, valid file (not 0 bytes), under 200 KB.
- `assets/img/favicon.svg` is a valid SVG with viewBox 0 0 64 64.
- `assets/img/favicon.ico` is a multi-resolution ICO file.
- `assets/img/apple-touch-icon.png` is 180×180.
- All four files load without 404 when `index.html` is opened.
- A README or commit message notes that final designer-delivered assets must replace placeholders before launch.

---

### task: cross-browser-and-lighthouse-validation

**Goal:** Validate the finished page against the spec's NFR thresholds (performance, accessibility, browser compatibility) and document any deviations.

**Context:**
Spec NFRs:
- NFR-1: Lighthouse performance ≥90 desktop, ≥85 mobile. FCP <1.5s. CLS <0.1. Total weight <500 KB gzipped (excluding optional GSAP). Animations at 60fps; only `transform`/`opacity`.
- NFR-3: WCAG 2.1 AA color contrast. Semantic HTML. Keyboard-navigable with visible focus. Alt text / aria-labels. Respects `prefers-reduced-motion`.
- FR-8: Renders on latest Chrome, Firefox, Safari (last 2 versions each). No console errors. Graceful fallback if GSAP fails to load (page still readable, animations skipped).

This task is the final QA gate before the page is considered done. It does **not** introduce new code unless validation fails — in which case minimal targeted fixes are scoped within this task.

**Files to create/modify:**
- `landingpage/VALIDATION.md` — record of test results, any deviations, screenshots/notes
- (Conditional) targeted fixes to existing files if validation surfaces failures

**Implementation steps:**

1. Run Lighthouse against the page (Chrome DevTools → Lighthouse → "Mobile" preset, then "Desktop"). Record scores for performance, accessibility, best practices, SEO.
   - If performance <90 desktop or <85 mobile, identify the top contributors in the Lighthouse report and address them. Common likely fixes: oversized OG image (compress), missing image dimensions (set `width`/`height` attributes if any `<img>` are added), unused CSS (none expected at this size).

2. Verify WCAG 2.1 AA contrast for every text/background pair:
   - `--color-text` (#e6edf3) on `--color-bg-base` (#0a0f1e): contrast ratio ~14:1. Pass.
   - `--color-text-dim` (#8b9bb4) on `--color-bg-base`: ~6:1. Pass for normal text.
   - `--color-accent` (#00d4ff) on `--color-bg-base`: ~10:1. Pass.
   - Verify with a contrast checker (e.g., https://webaim.org/resources/contrastchecker/) — paste any pair that looks borderline.

3. Keyboard navigation walk-through:
   - Tab from page top to bottom. Every interactive element receives focus in document order.
   - Focus ring is visible (cyan, 2px outline-offset 2px) on each.
   - Enter activates anchors; Space/Enter activates buttons.
   - Copy buttons trigger Clipboard API on Enter/Space — verify with screen reader if available.

4. Cross-browser smoke test:
   - **Chrome (latest):** open page, scroll through, click each CTA, click each copy button. No console errors. Animations play smoothly.
   - **Firefox (latest):** same. Note: `backdrop-filter` requires `-webkit-backdrop-filter` fallback (already set in sections.css).
   - **Safari (latest):** same. Pay extra attention to MediaQueryList listener compatibility (already handled with `addListener` fallback in motion.js).
   - Capture screenshots at 1440px and 375px in each browser.

5. Reduced-motion test:
   - Toggle `prefers-reduced-motion: reduce` in dev tools.
   - Hero SVG nodes hold at 40% opacity (no pulse).
   - Pipeline lines render at full opacity immediately, no streaming, no cursor blink.
   - All `[data-reveal]` content is visible immediately at page load.

6. Tab-backgrounding test:
   - Open page, watch hero animation, switch to another tab for 5 seconds, return.
   - Verify hero animation paused (`--hero-play-state: paused` set on `<html>`) while hidden and resumes on return.

7. JavaScript-disabled test:
   - Disable JS in browser settings.
   - Reload page. Noscript notice appears at top.
   - All sections, headings, copy, and links are visible and functional.
   - Copy buttons render but click does nothing (acceptable per FR-8).

8. Page weight audit:
   - DevTools → Network → reload with cache disabled.
   - Sum all transferred bytes (HTML + 5 CSS + 4 JS + favicon + og-image).
   - Verify total <500 KB. (Expected: ~80-150 KB total without web fonts.)

9. Layout shift (CLS) check:
   - Lighthouse reports CLS in performance audit.
   - Verify CLS <0.1.

10. Write `landingpage/VALIDATION.md` recording all results:
```markdown
# Validation Results — AgentHarness Landing Page

Tested on YYYY-MM-DD against commit <sha>.

## Lighthouse
- Desktop: performance XX, accessibility XX, best practices XX, SEO XX
- Mobile:  performance XX, accessibility XX, best practices XX, SEO XX

## WCAG 2.1 AA
- All foreground/background pairs verified ≥4.5:1 (or ≥3:1 for large text). See contrast-check screenshots.

## Keyboard navigation
- Tab order verified. Focus ring visible on every interactive element.

## Cross-browser
- Chrome (vXXX): pass
- Firefox (vXXX): pass
- Safari (vXX): pass

## Reduced motion
- Pass: hero static at 40% opacity, pipeline static, no streaming, all reveals visible immediately.

## Tab backgrounding
- Pass: hero animation pauses when tab hidden, resumes on return.

## No-JavaScript
- Pass: noscript notice shown, all content readable, links functional.

## Page weight
- Total transferred: XX KB. Under 500 KB threshold.

## CLS
- XX (target <0.1).
```

11. If any test fails, fix the underlying issue in the appropriate file (CSS, JS, or HTML) and re-run the failing test until it passes. Document the fix in VALIDATION.md.

**Tests to write:**
This task IS the test phase. The validation steps above are the tests. No automated unit tests are added.

**Acceptance criteria:**
- `landingpage/VALIDATION.md` exists and records every test result with concrete numbers, not "ok"/"pass".
- Lighthouse desktop performance ≥90.
- Lighthouse mobile performance ≥85.
- WCAG 2.1 AA contrast verified for every text/background pair on the page.
- Page renders without console errors on latest Chrome, Firefox, and Safari.
- Reduced-motion behavior matches spec (static hero, no streaming, all reveals immediate).
- Tab-backgrounding pauses and resumes hero animation.
- JavaScript-disabled page is fully readable with noscript notice visible.
- Page total transferred weight <500 KB.
- CLS <0.1.