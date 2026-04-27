```markdown
# Specification: AgentHarness Landing Page

## Summary
A pure-static, single-page marketing site that converts developers into AgentHarness users by communicating the core value proposition — "delegate the implementation grind to autonomous Claude agents" — within 10 seconds of arrival. Built with vanilla HTML/CSS/JS plus GSAP for animations, optimized for fast load and a premium developer-native aesthetic (Vercel/Linear-inspired, dark blue palette).

## Background
AgentHarness is a distributed, event-driven pipeline that runs a chain of specialized Claude agents (analyst → architect → designer → planner → developer → reviewer) to autonomously implement features from a brief. Today there is no public-facing entry point that explains this value proposition; developers discovering the project on GitHub land on a README without visual or emotional hook. The landing page must (a) make the value prop undeniable to a Claude-Code-fluent developer, (b) provide enough technical credibility (pipeline visualization, terminal-style agent activity) to earn trust, and (c) be polished enough to share on X / Hacker News / Reddit without embarrassment.

## Functional Requirements

### FR-1: Hero Section
The first viewport-height section the visitor sees. Must communicate the core message in under 10 seconds.

**Content:**
- Bold headline (one line, max 8 words) — e.g. *"Ship features while you sleep."*
- Subheadline (1–2 sentences) — explains AgentHarness orchestrates Claude agents to design, build, and review code autonomously.
- Two CTAs: primary *"Get Started"* (anchors to CTA section / GitHub), secondary *"How it works"* (smooth-scrolls to FR-2).
- Animated background visual: looping terminal-style animation showing agent names (`analyst`, `architect`, `designer`, `planner`, `developer`, `reviewer`) appearing with status indicators (`running…`, `✓ done`), evoking parallel autonomous work.

**Acceptance criteria:**
- Headline and subheadline visible without scrolling at 1280×720, 1440×900, 375×667, and 768×1024 viewports.
- Hero animation begins within 500ms of `DOMContentLoaded` and loops indefinitely without layout shift.
- Both CTAs are keyboard-focusable, have visible focus state, and respond to Enter/Space.
- No layout shift (CLS < 0.05) during animation.

### FR-2: How It Works Section
Visualizes the 3-step user journey.

**Content:**
- Section heading (e.g. *"From idea to merged code in three steps"*).
- Three numbered cards laid out horizontally on desktop, stacked on mobile:
  1. **Brainstorm** — describe your feature in a conversation; AgentHarness writes the brief.
  2. **Agents Work** — the pipeline runs analyst → architect → designer → planner → developer → reviewer autonomously.
  3. **Code Ships** — implementation lands in your repo on a feature branch, ready to review.
- Subtle scroll-triggered reveal: each card fades + slides into view as the user scrolls.
- Connecting line / arrow between cards on desktop.

**Acceptance criteria:**
- Each card animates in once when 30% visible in viewport (IntersectionObserver-driven, not on every scroll).
- Animation runs in ≤ 600ms per card; cards animate sequentially with ~150ms stagger.
- On mobile (<768px), cards stack vertically; connecting line/arrow is hidden or rotated.
- Animations respect `prefers-reduced-motion: reduce` (instant reveal, no transform/opacity transition).

### FR-3: Features Section
Highlights key differentiators with an icon + short title + 1–2 sentence description per feature.

**Required features to highlight:**
- **Multi-agent pipeline** — specialized agents for each phase (analyst, architect, designer, planner, developer, reviewer).
- **Per-task review loop** — every developer task is reviewed; revisions happen automatically until PASS.
- **Pluggable backends** — runs on Azure Blob + Storage Queues or GitHub Issues + branches.
- **Zero babysitting** — fan-out planner, serial dispatch, automatic dead-letter handling.
- **Claude-native** — built on Claude Code CLI; uses the latest Claude models per agent.
- **Open source** — MIT licensed, self-hostable, transparent.

**Acceptance criteria:**
- Six feature cards in a responsive grid (3×2 desktop, 2×3 tablet, 1×6 mobile).
- Each card has an SVG icon (inline, no external requests), a title, and a description ≤ 140 chars.
- Cards have a subtle hover state (border glow or lift) that does not depend on JS.

### FR-4: Pipeline Visualization Section (Social Proof / Credibility)
Animated diagram or terminal-style block that demonstrates the pipeline running, providing technical credibility.

**Content (one of the two — recommend both, terminal as primary):**
- **Terminal-style animation:** mock terminal showing realistic CLI output — `agentharness brainstorm` → brief upload → `analyst` running → spec generated → `planner` fan-out → 3 developer tasks dispatched serially → reviewer PASS → done. Auto-types and replays on loop.
- **Pipeline diagram:** SVG showing nodes for each agent with animated tokens flowing along edges (analyst → architect → designer → planner → fan-out to developers → reviewer).

**Acceptance criteria:**
- Terminal animation auto-types at a believable speed (≈ 30–60ms per char) and pauses 2s before looping.
- Animation pauses when section is out of viewport (IntersectionObserver) to save CPU.
- Pipeline SVG is < 30KB inline; tokens flow continuously when in viewport.
- Section gracefully degrades to a static screenshot/SVG when JS is disabled.

### FR-5: CTA Section
Final call-to-action, positioned before the footer.

**Content:**
- Strong closing headline (e.g. *"Stop writing boilerplate. Start shipping."*).
- Primary CTA button → opens GitHub repo URL (`https://github.com/onpaj/AgentHarness` or configured value) in a new tab.
- A copyable quick-start command block, e.g.:
  ```
  pip install agentharness
  agentharness init
  agentharness brainstorm
  ```
- A "Copy" button on the command block that copies all three lines to the clipboard and shows a confirmation toast.

**Acceptance criteria:**
- Copy button uses `navigator.clipboard.writeText()` with a fallback to `document.execCommand('copy')` for older browsers.
- On copy success, button text changes to "Copied!" for 1.5s, then reverts.
- GitHub link opens in a new tab with `rel="noopener noreferrer"`.

### FR-6: Footer
Minimal footer with project name, GitHub link, and license note.

**Acceptance criteria:**
- Contains: AgentHarness wordmark, GitHub icon link, "MIT License" text, current year (computed via JS).
- Footer is < 80px tall on desktop.

### FR-7: Smooth Scroll & Scroll-Triggered Animations
All in-page anchor links (e.g. *"How it works"* CTA) smooth-scroll to their targets. Scroll-triggered reveals use GSAP ScrollTrigger or IntersectionObserver.

**Acceptance criteria:**
- Anchor clicks smooth-scroll over ~600ms with easing.
- Each scroll-triggered animation runs only once per page load.
- `prefers-reduced-motion: reduce` disables all motion (instant reveals, no parallax, no looping animations).

### FR-8: Mobile Responsive Layout
The page is fully usable and visually polished on mobile.

**Acceptance criteria:**
- Three breakpoints: mobile (< 768px), tablet (768–1024px), desktop (> 1024px).
- No horizontal scroll at 320px viewport width.
- Touch targets (buttons, links) are ≥ 44×44 px.
- Hero headline scales down to a readable size (≥ 32px) on mobile without overflowing.
- Heavy looping animations are simplified or replaced with static visuals on mobile to preserve battery.

### FR-9: Cross-Browser Compatibility
Page renders and animates correctly on the latest two stable releases of Chrome, Firefox, and Safari (desktop and iOS).

**Acceptance criteria:**
- All sections render with no console errors on target browsers.
- Animations run smoothly (≥ 30fps subjective) on M1 MacBook Air baseline hardware.
- No use of CSS or JS APIs unsupported in target browsers without polyfill.

## Non-Functional Requirements

### NFR-1: Performance
- First Contentful Paint < 1.0s on Fast 3G (simulated).
- Total page weight (HTML + CSS + JS + assets) < 500KB excluding self-hosted fonts; < 1MB total including fonts.
- Lighthouse Performance score ≥ 90 on desktop, ≥ 85 on mobile.
- No render-blocking external requests; GSAP loaded as deferred local file (not from CDN, to keep it self-contained).
- Cumulative Layout Shift (CLS) < 0.1.

### NFR-2: Security
- No external script tags (no third-party trackers, no remote analytics, no fonts from CDNs that could be compromised).
- All external links use `rel="noopener noreferrer"`.
- No user input collected → no XSS / CSRF surface.
- All assets served via relative paths; no hardcoded HTTP URLs (use HTTPS or relative).

### NFR-3: Accessibility
- WCAG 2.1 AA compliance for color contrast (text on `#0a0f1e` background must have ≥ 4.5:1 ratio).
- All interactive elements keyboard-navigable with visible focus indicators.
- Semantic HTML5 (`<header>`, `<main>`, `<section>`, `<footer>`, `<nav>`).
- All decorative SVGs have `aria-hidden="true"`; meaningful icons have `aria-label`.
- Animations respect `prefers-reduced-motion`.

### NFR-4: Build & Deployment
- Zero build step — works by opening `index.html` directly in a browser or serving via any static file server.
- All dependencies (GSAP, fonts, icons) vendored locally in the `/landingpage` folder.
- Total folder size < 2MB.

### NFR-5: Maintainability
- Single `index.html` ≤ 800 lines; split CSS into `styles.css` and JS into `main.js` (+ `animations.js` if needed).
- All copy (headlines, descriptions) lives in HTML — no JS-based content rendering.
- CSS uses custom properties for colors, spacing, and typography (defined in `:root`).

## Data Model
Not applicable — the landing page has no data persistence, no API calls, and no state beyond ephemeral UI state (e.g. "Copied!" toast).

Static content constants (defined inline in HTML, referenced once):
- **Brand palette:** `--color-bg: #0a0f1e`, `--color-mid: #1e3a5f`, `--color-accent: #00d4ff`, plus derived shades for text and borders.
- **Typography:** one display font (e.g. Inter, Geist, or Space Grotesk — vendored as WOFF2) and one monospace font for code/terminal sections (e.g. JetBrains Mono).
- **Agent list (for hero/pipeline animation):** `["analyst", "architect", "designer", "planner", "developer", "reviewer"]`.
- **GitHub repo URL:** single source of truth in HTML, referenced by all CTAs.

## API / Interface Design
No backend. The page is purely client-rendered with these UI flows:

**Flow 1 — First-time visitor (desktop):**
1. Hero loads with looping terminal animation in background.
2. Visitor reads headline, scrolls down.
3. "How it works" cards reveal sequentially.
4. Features grid renders.
5. Pipeline visualization auto-plays when scrolled into view.
6. CTA section presents quick-start command + GitHub button.

**Flow 2 — Visitor clicks "Get Started" in hero:**
1. Smooth-scroll to CTA section.
2. Visitor copies quick-start command or clicks GitHub button.

**Flow 3 — Visitor on mobile:**
1. Same content, stacked vertically.
2. Heavy looping animations replaced with static SVG/screenshot.
3. All CTAs fully tappable.

**File structure (in `/landingpage`):**
```
landingpage/
  index.html
  styles.css
  main.js
  vendor/
    gsap.min.js          # vendored, optional if IntersectionObserver suffices
  fonts/
    inter-variable.woff2
    jetbrains-mono.woff2
  assets/
    icons/               # inline SVGs preferred; fallback PNGs only if needed
    og-image.png         # 1200×630 social card image
  favicon.svg
```

## Dependencies
- **GSAP (optional):** vendored locally if scroll-triggered/parallax animations exceed what IntersectionObserver + CSS transitions can deliver. License-compatible standard version.
- **Fonts:** Inter (or equivalent), JetBrains Mono — vendored as WOFF2 with `font-display: swap`.
- **No npm, no bundler, no framework.** Pure HTML/CSS/JS.

## Out of Scope
- Full documentation site / API reference.
- Interactive live demo connecting to a real AgentHarness pipeline.
- Authentication, user accounts, or sign-up forms.
- Analytics integration (Google Analytics, Plausible, etc.).
- Blog, changelog, or pricing pages.
- Newsletter signup.
- Internationalization / multi-language support.
- A/B testing infrastructure.
- Server-side rendering or build-time generation (Next.js, Astro, etc.).
- Dark/light theme toggle (page is dark-only by design).

## Open Questions
1. **GitHub repo URL** — assumption: `https://github.com/onpaj/AgentHarness`. Confirm the canonical public URL.
2. **Quick-start command** — assumption: `pip install agentharness && agentharness init && agentharness brainstorm`. Confirm whether `pip install agentharness` actually publishes the package, or whether the install path should reference cloning the repo (`git clone …`) instead.
3. **Hero headline copy** — placeholder *"Ship features while you sleep."* is provided as a starting point; the brief asks for "bold" but doesn't specify exact wording. Final copy is a marketing decision.
4. **Font choice** — Inter is suggested as a Vercel/Linear-aligned default, but a more distinctive display font (e.g. Geist, Space Grotesk) could reinforce the premium aesthetic. Awaiting design direction.
5. **OG / social card image** — the page should include `og:image` meta for X/HN/Reddit sharing. Assumption: a static 1200×630 PNG showing the hero with pipeline graphic. Needs design.
6. **Pipeline visualization preference** — terminal-style animation vs. SVG node diagram vs. both. Assumption (taken in FR-4): terminal-style as primary with optional SVG diagram secondary.
7. **GSAP vs. vanilla** — assumption: start with IntersectionObserver + CSS transitions; add GSAP only if specific effects (parallax, complex timelines) require it. Decision can be made during implementation.
8. **Domain & hosting** — out of scope for this spec, but the page must work both at the eventual canonical URL and when opened locally as `file://`.
9. **Favicon design** — assumption: a simple monogram or logo mark using the accent color. Needs design.
10. **Telemetry** — confirmed out of scope per brief, but worth re-confirming that no privacy-respecting analytics (e.g. simple page-view counter) are desired.
```