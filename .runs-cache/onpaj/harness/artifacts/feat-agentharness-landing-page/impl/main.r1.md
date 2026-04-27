## Status: DONE

The AgentHarness landing page is implemented at `/Users/pajgrtondrej/Work/GitHub/AgentHarness/landingpage/`.

**Files created:**
- `index.html` (296 lines) — 7 sections: navbar, hero, features, how-it-works, pipeline terminal, quickstart CTA, footer
- `styles.css` (454 lines) — dark blue design tokens, responsive grid, scroll-reveal, `prefers-reduced-motion`
- `main.js` (248 lines) — terminal animations (both loops fixed for cancel safety + no double-start), scroll reveal, clipboard copy with fallback, navbar scroll effect
- `favicon.svg` — "AH" monogram in accent cyan

**Issues fixed from review:**
- Orphaned `typeCharacters` timers now check `isActiveRef()` — no CPU leak on scroll-out
- Double-start race condition eliminated with `running` guard
- Clipboard copy now has `execCommand` fallback for `file://` and HTTP origins
- Pipeline terminal has `<noscript>` static fallback
- `ANIMATION_END_BUFFER_MS` constant replaces magic `500`
- `.code-wrap` uses `min-width: 0` for correct flex shrink behavior