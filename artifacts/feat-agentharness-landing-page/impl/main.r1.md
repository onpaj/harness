# Implementation: AgentHarness Landing Page

## Status
DONE

All 17 subtasks implemented. The complete static landing page lives in `landingpage/` with no build step required.

## What was built

| Layer | Files |
|---|---|
| **HTML** | `index.html` (335 lines) — shell, all 5 sections (hero, how-it-works, features, pipeline, cta), footer |
| **CSS** | `reset.css` → `tokens.css` → `layout.css` → `components.css` → `sections.css` |
| **JS** | `motion.js`, `copy.js`, `animations.js`, `main.js` (ES modules, no bundler) |
| **Assets** | `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `og-image.png` (placeholder) |

## Key behaviors

- **Scroll reveals** — `IntersectionObserver` fires once per `[data-reveal]` element; skipped under `prefers-reduced-motion`
- **Hero animation** — 6 SVG nodes pulse sequentially via CSS `@keyframes node-pulse`, pauses on tab-hidden via `--hero-play-state` custom property
- **Pipeline terminal** — 9 lines stream in with 400ms stagger on scroll-into-view, restarts on each re-entry
- **Click-to-copy** — Clipboard API with `execCommand` fallback for `file://` users; 2s `.is-copied` state
- **No-JS fallback** — `.js-loaded` gates reveal initial state so content is always readable without JS
- **Single constant source** — `REPO_URL` and `QUICKSTART_CMD` in `main.js` are projected into all CTAs at init

## One note

`og-image.png` and `apple-touch-icon.png` are solid dark-blue placeholder PNGs (Pillow unavailable). They satisfy the no-404 requirement but need a designed replacement before launch.