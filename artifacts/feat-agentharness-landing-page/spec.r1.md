```markdown
# Specification: AgentHarness Landing Page

## Summary
A static, single-page marketing site for AgentHarness that converts developer visitors by communicating the "delegate the grind to autonomous Claude agents" value proposition within 10 seconds. Built as pure HTML/CSS/vanilla JS (with optional GSAP for animations) in a self-contained `/landingpage` folder, requiring no build step or backend.

## Background
Developers discovering AgentHarness on GitHub or via shared links have no compelling entry point that visualizes what the project does or why it matters. The README explains the architecture but doesn't sell the outcome. AgentHarness's target audience — developers already using Claude Code — needs to grasp the autonomous-agent value prop emotionally and immediately, then be funneled to the GitHub repo and quick-start command. The page must feel premium and developer-native (Vercel/Linear aesthetic) so it can be shared on X/HN/Reddit without embarrassment.

## Functional Requirements

### FR-1: Hero Section
The first viewport-sized section the user sees on load. Communicates the core value proposition immediately.

**Content:**
- Bold headline (e.g., "Ship features while you sleep" or "Delegate the grind. Reclaim your time.") — final copy chosen by designer
- Subheadline (1-2 sentences) explaining: a chain of Claude agents builds your features autonomously
- Primary CTA button: "Get started on GitHub" → links to AgentHarness repo
- Secondary CTA: copyable quick-start command (e.g., `pip install agentharness && agentharness brainstorm`)
- Animated visual element evoking "autonomous agents working" — e.g., particle/node graph, animated pipeline glyph, or subtle terminal-style ticker

**Acceptance criteria:**
- Hero fills viewport on desktop (≥1024px) without scroll
- Headline + subheadline + CTA visible above the fold on mobile (≥375px width)
- Visual animation runs at ≥30fps and pauses when tab is backgrounded
- CTA button has hover/focus states; link opens in new tab with `rel="noopener noreferrer"`
- Quick-start command is selectable/copyable; click-to-copy with visual confirmation

### FR-2: How-It-Works Section
Three-step visual flow communicating the user journey from idea to shipped code.

**Content:**
- Step 1: "Brainstorm" — developer describes feature in conversation
- Step 2: "Agents work" — analyst → architect → designer → planner → developer → reviewer chain runs autonomously
- Step 3: "Code ships" — implementation lands as a PR or branch
- Each step has: icon/illustration, short title, 1-2 sentence description

**Acceptance criteria:**
- Steps appear horizontally on desktop (≥768px), stacked vertically on mobile
- Scroll-triggered animation reveals each step sequentially (fade + slide-up)
- Animation triggers once per page load; subsequent scrolls don't re-trigger
- Connecting line/arrow between steps animates in after step appears
- Reduced-motion users see static layout (respect `prefers-reduced-motion: reduce`)

### FR-3: Features Section
Highlights key technical differentiators that build credibility with developers.

**Content (4-6 feature cards):**
- Multi-agent pipeline (analyst → architect → designer → planner → developer → reviewer)
- Per-task review loop (each developer task reviewed; revision cycles up to N rounds)
- Pluggable backends (Azure Blob Storage + Queues, or GitHub Issues + branches)
- Zero babysitting (observer process runs the whole pipeline autonomously)
- Per-agent context files (each agent gets curated context)
- Serial task dispatch (prevents same-file conflicts in parallel work)

**Acceptance criteria:**
- Cards arranged in a responsive grid: 3 columns on desktop, 2 on tablet, 1 on mobile
- Each card has icon, title, 2-3 sentence description
- Cards have subtle hover effect (lift, glow, or border color shift)
- Scroll-triggered fade-in on entry into viewport

### FR-4: Pipeline / Credibility Section
Visual or terminal-style animation showing the agent pipeline running, building developer trust.

**Content (one of, designer's choice):**
- Animated pipeline diagram: nodes representing agents light up in sequence, edges show flow
- Terminal-style animation: simulated `agentharness observe` output — agent names, statuses, timestamps stream in
- Code/log block showing realistic agent activity (e.g., "analyst: complete (12s)", "developer[task-1]: in_progress")

**Acceptance criteria:**
- Animation loops or restarts when scrolled into view
- Animation is purely visual — no real backend connection
- Renders on a dark surface that matches palette
- Uses monospace font for any terminal text

### FR-5: CTA Section (Footer)
Final conversion prompt before the user leaves the page.

**Content:**
- Closing headline (e.g., "Stop writing boilerplate. Start shipping.")
- Primary CTA: "View on GitHub" → repo URL
- Secondary CTA: copyable quick-start command
- Footer links: GitHub, docs (if exists), license note
- Project tagline + small AgentHarness wordmark/logo

**Acceptance criteria:**
- Section is the last visible content before page end
- All external links open in new tab with `rel="noopener noreferrer"`
- Click-to-copy on quick-start command with visual confirmation

### FR-6: Smooth Scroll & Scroll-Triggered Animations
Polished scroll behavior throughout the page.

**Acceptance criteria:**
- Smooth scroll enabled via CSS (`scroll-behavior: smooth`) or JS for unsupported browsers
- Section reveals use `IntersectionObserver` for performance (no scroll event listeners with heavy work)
- Optional parallax on hero visual (subtle, not seasick-inducing)
- All animations disabled when `prefers-reduced-motion: reduce` is set

### FR-7: Mobile Responsive
Page works on phones, tablets, and desktop.

**Acceptance criteria:**
- Breakpoints at 375px (mobile), 768px (tablet), 1024px (desktop), 1440px (wide)
- No horizontal scroll on any breakpoint
- Touch targets ≥44×44px
- Typography scales fluidly (e.g., `clamp()` for hero headline)
- Hero visual degrades gracefully on mobile (smaller, lighter animation)

### FR-8: Browser Compatibility
Works on the three major evergreen browsers.

**Acceptance criteria:**
- Renders and animates correctly on latest Chrome, Firefox, Safari (last 2 versions each)
- No console errors on page load
- Graceful fallback if GSAP fails to load (page still readable, animations skipped)

## Non-Functional Requirements

### NFR-1: Performance
- Initial page load: <2s on a 3G-throttled connection
- Lighthouse performance score ≥90 on desktop, ≥85 on mobile
- Total page weight (HTML + CSS + JS + assets): <500 KB gzipped (excluding optional GSAP CDN, which is ~70 KB)
- First Contentful Paint <1.5s
- No layout shifts (CLS <0.1)
- Animations run at 60fps; use `transform` and `opacity` only (avoid layout-triggering properties)

### NFR-2: Security
- No backend, no user data collection — minimal attack surface
- All external links use `rel="noopener noreferrer"`
- No inline event handlers in HTML; all JS in dedicated files
- If GSAP loaded from CDN, use SRI (Subresource Integrity) hash
- No tracking pixels, analytics, or third-party scripts

### NFR-3: Accessibility
- WCAG 2.1 AA compliance for color contrast (palette already uses high-contrast dark blue + bright accent)
- Semantic HTML (`<header>`, `<main>`, `<section>`, `<footer>`, proper heading hierarchy)
- All interactive elements keyboard-navigable with visible focus states
- Alt text on all images; `aria-label` on icon-only buttons
- Respects `prefers-reduced-motion` and `prefers-color-scheme` (page is dark-only by design, but no light-mode flicker)

### NFR-4: Maintainability
- All HTML in single `index.html` (or split per section if it exceeds ~600 lines)
- CSS organized by section; uses CSS custom properties for palette and spacing tokens
- JS modular — one file per concern (animations, copy-to-clipboard, scroll observer)
- No build step required — works when opened via `file://` or served as static files
- Code commented only where the WHY is non-obvious

### NFR-5: SEO & Meta
- `<title>`, `<meta name="description">`, Open Graph tags, Twitter Card tags
- OG image (1200×630) showing the hero or pipeline visual
- Canonical URL set
- `lang="en"` on `<html>`
- Favicon (multiple sizes: 16, 32, 180 for Apple touch)

## Data Model
No persistent data model — page is purely static. The only dynamic state is client-side UI state:
- Animation triggered/not-triggered flags (managed by IntersectionObserver)
- Copy-to-clipboard "copied!" toast state (transient)
- Scroll position (browser-managed)

## API / Interface Design

### File Structure
```
landingpage/
├── index.html              # Single-page entry point
├── assets/
│   ├── css/
│   │   ├── reset.css       # Modern CSS reset
│   │   ├── tokens.css      # Custom properties: colors, spacing, typography
│   │   ├── layout.css      # Grid, flex utilities, container
│   │   ├── components.css  # Buttons, cards, code blocks
│   │   └── sections.css    # Section-specific styles
│   ├── js/
│   │   ├── main.js         # Entry — initializes observers, copy handlers
│   │   ├── animations.js   # Scroll-triggered reveals, hero animation
│   │   └── copy.js         # Click-to-copy logic
│   ├── img/
│   │   ├── og-image.png    # 1200×630 social share image
│   │   ├── favicon.ico
│   │   └── icons/          # SVG icons for features/steps
│   └── fonts/              # Self-hosted display + monospace fonts (optional)
└── README.md               # Brief: what it is, how to view locally
```

### External Dependencies
- **Optional:** GSAP via CDN for advanced animations (load with SRI hash); fall back gracefully if absent.
- **Optional:** Self-hosted or system fonts. If using web fonts, use `font-display: swap` to avoid FOIT.

### Visual Design Tokens
```
--color-bg-base:   #0a0f1e   /* Deep dark blue background */
--color-bg-mid:    #1e3a5f   /* Mid-tone for cards/surfaces */
--color-accent:    #00d4ff   /* Bright cyan for CTAs and highlights */
--color-text:      #e6edf3   /* High-contrast off-white */
--color-text-dim:  #8b9bb4   /* Secondary text */
--font-display:    'Inter', system-ui, sans-serif    /* Or similar geometric sans */
--font-mono:       'JetBrains Mono', ui-monospace, monospace
```

### User Flows
1. **First-time visitor:** Lands → reads hero → scrolls → sees how-it-works → reads features → sees pipeline animation → clicks GitHub CTA.
2. **Quick-start visitor:** Lands → copies quick-start command from hero → leaves to terminal.
3. **Skeptical developer:** Lands → scrolls past hero → reads features + pipeline section → clicks GitHub.

## Dependencies
- **AgentHarness GitHub repository** — CTAs link here; URL must be confirmed before launch.
- **GSAP (optional)** — for animations, loaded via CDN. Page must function without it.
- **Web fonts (optional)** — Inter, JetBrains Mono, or similar. Fall back to system stack.
- **No runtime dependencies** — no API, database, or backend service.

## Out of Scope
- Full documentation site (`/docs`)
- Interactive live demo or real pipeline connection
- User authentication, accounts, or sign-up flow
- Analytics, tracking, or telemetry
- Blog, changelog, or news section
- Multi-language / i18n support
- Light mode (page is dark-only by design)
- Newsletter signup or email capture
- A/B testing infrastructure
- Server-side rendering or SSG framework integration
- Video content or autoplay media

## Open Questions

1. **Final headline copy** — designer/PM to choose between candidates (e.g., "Ship features while you sleep" vs. "Delegate the grind"). Assumption: copywriter or designer will finalize during design phase.
2. **Pipeline section format** — terminal animation vs. node-graph diagram. Assumption: designer chooses based on visual impact; both are acceptable.
3. **GSAP vs. vanilla JS animations** — brief allows either. Assumption: start with vanilla CSS + IntersectionObserver; introduce GSAP only if needed for complex sequencing.
4. **Self-hosted vs. CDN fonts** — performance vs. simplicity tradeoff. Assumption: use system font stack first; add web fonts only if brand requires.
5. **Confirmation of GitHub repo URL** — exact URL for CTAs. Assumption: `https://github.com/onpaj/AgentHarness` based on repo context; verify before launch.
6. **Quick-start command exact text** — does `pip install agentharness` work, or is it currently install-from-source? Assumption: use whatever the current README recommends; align with README at launch.
7. **Logo/wordmark asset** — does AgentHarness have an existing logo? Assumption: use a typographic wordmark if no logo exists.
8. **Hosting target** — GitHub Pages, Vercel, Netlify, or just static-served from repo? Assumption: works as static files anywhere; no hosting-specific config required.
9. **OG image content** — needs design. Assumption: hero visual + headline rendered to a 1200×630 PNG by designer.
10. **Reduced-motion fallback fidelity** — should the page show a single static frame of the hero animation, or hide it entirely? Assumption: show a static representative frame.
```