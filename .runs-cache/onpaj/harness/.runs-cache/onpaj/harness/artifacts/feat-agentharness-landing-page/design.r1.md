# Design: AgentHarness Landing Page

## UX/UI Design

### Page Layout (Single-page, anchor navigation)

```
┌─────────────────────────────────────────────────────┐
│ NAVBAR                                              │
│ [AgentHarness logo]    Features  How It Works  Docs │
│                                        [GitHub ★]   │
├─────────────────────────────────────────────────────┤
│ HERO  (#hero)                                       │
│                                                     │
│   Autonomous AI development,                        │
│   end to end.                                       │
│                                                     │
│   [Brief description — 1–2 lines]                   │
│                                                     │
│   [Get Started →]  [View on GitHub]                 │
│                                                     │
│   ┌─────────────────────────────────────────────┐   │
│   │  $ agentharness brainstorm                  │   │
│   │  > Describe your feature...                 │   │
│   │  ✓ Brief uploaded: feat-20260427-abc123     │   │
│   │  $ agentharness implement feat-20260427-... │   │
│   └─────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│ FEATURES  (#features)                               │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ [icon]   │  │ [icon]   │  │ [icon]   │          │
│  │ Fully    │  │ Pluggable│  │ Per-task │          │
│  │ Autonomous│  │ Backends │  │ Review   │          │
│  │ ...      │  │ ...      │  │ ...      │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ [icon]   │  │ [icon]   │  │ [icon]   │          │
│  │ Serial   │  │ Real-time│  │ Extensible│         │
│  │ Dispatch │  │ TUI      │  │ Agents   │          │
│  └──────────┘  └──────────┘  └──────────┘          │
├─────────────────────────────────────────────────────┤
│ HOW IT WORKS  (#how-it-works)                       │
│                                                     │
│  Step pipeline — horizontal on desktop,             │
│  vertical stack on mobile                           │
│                                                     │
│  [1 Brief] → [2 Analyze] → [3 Architect]           │
│           → [4 Plan] → [5 Develop] → [6 Review]    │
│                                                     │
│  Each step: icon + label + short description        │
├─────────────────────────────────────────────────────┤
│ QUICK START  (#quickstart)                          │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │  # Install                                  │   │
│  │  pip install agentharness                   │   │
│  │                                             │   │
│  │  # Start a feature                          │   │
│  │  agentharness brainstorm                    │   │
│  │  agentharness implement feat-...            │   │
│  │  agentharness observe                       │   │
│  └─────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│ GITHUB CTA  (#cta)                                  │
│                                                     │
│   Open source and self-hostable.                   │
│   [Star on GitHub ★]  [Read the Docs]              │
├─────────────────────────────────────────────────────┤
│ FOOTER                                              │
│  AgentHarness  MIT License  GitHub  Docs            │
└─────────────────────────────────────────────────────┘
```

### Responsive breakpoints

| Breakpoint | Behaviour |
|---|---|
| `sm` (640px) | Single-column features grid; pipeline steps stack vertically |
| `md` (768px) | Two-column features grid |
| `lg` (1024px) | Three-column features grid; pipeline steps horizontal |

### Design tokens

```
Background:    #0a0a0a  (near-black)
Surface:       #111111  (card backgrounds)
Border:        #1f1f1f
Text primary:  #f5f5f5
Text muted:    #888888
Accent:        #4f8ef7  (blue — links, CTAs, step numbers)
Code bg:       #0d0d0d
Font body:     Inter (system-ui fallback)
Font mono:     JetBrains Mono, monospace
```

### Key interactions

- Navbar: transparent on hero, solid `surface` on scroll (CSS `position: sticky` + JS scroll listener)
- Anchor links: `scroll-behavior: smooth` via CSS
- Code blocks: syntax-highlighted via `shiki` (static, zero runtime cost)
- GitHub CTA button: opens `https://github.com/pajgrtondrej/AgentHarness` in new tab

---

## Component Design

```
app/
  layout.tsx          Root layout — HTML shell, fonts, global CSS
  page.tsx            Composes all section components in order

components/
  layout/
    Navbar.tsx        Sticky nav, scroll-aware opacity, anchor links
    Footer.tsx        Links and license line

  sections/
    Hero.tsx          Headline, sub-copy, CTAs, terminal animation
    Features.tsx      Renders FeatureCard grid from static data
    HowItWorks.tsx    Pipeline step sequence from static data
    QuickStart.tsx    Multi-line code block with copy button
    GitHubCta.tsx     Star/docs CTA banner

  ui/
    FeatureCard.tsx   Icon + title + description card
    PipelineStep.tsx  Numbered step with connector line
    CodeBlock.tsx     Pre-formatted block, optional copy-to-clipboard
    Button.tsx        Variant="primary" | "outline" | "ghost"
    Badge.tsx         Small label chip (used in pipeline steps)
```

### Component contracts

**`FeatureCard`**
```ts
interface FeatureCardProps {
  icon: React.ReactNode
  title: string
  description: string
}
```

**`PipelineStep`**
```ts
interface PipelineStepProps {
  step: number
  label: string
  description: string
  isLast?: boolean   // hides connector line
}
```

**`CodeBlock`**
```ts
interface CodeBlockProps {
  code: string
  language?: string  // default 'bash'
  showCopy?: boolean // default true
}
```

**`Button`**
```ts
interface ButtonProps {
  variant: 'primary' | 'outline' | 'ghost'
  href?: string      // renders <a> when set
  onClick?: () => void
  children: React.ReactNode
}
```

**`Navbar`** — no props; reads scroll position via internal `useScrolled` hook.

### Static data files

```
lib/
  features.ts     FeatureItem[] — icon key, title, description
  pipeline.ts     PipelineStepData[] — step, label, description
```

All page content lives in these files, not inline in JSX, so copy edits don't touch component logic.

---

## Data Schemas

This is a fully static site — no database, no runtime API, no authentication.

### Build-time data shapes

```ts
// lib/features.ts
interface FeatureItem {
  iconKey: string        // maps to Lucide icon name
  title: string
  description: string
}

// lib/pipeline.ts
interface PipelineStepData {
  step: number
  label: string
  description: string
}
```

### Next.js static export config

```ts
// next.config.ts
const nextConfig: NextConfig = {
  output: 'export',       // generates /out directory
  trailingSlash: true,    // GitHub Pages compatibility
  images: { unoptimized: true },  // no Next image server in static export
}
```

### GitHub Pages deployment

```yaml
# .github/workflows/deploy.yml (shape)
on: push to main
jobs:
  build:
    - npm ci
    - npm run build          # writes to /out
  deploy:
    - actions/upload-pages-artifact (path: out)
    - actions/deploy-pages
```

No environment variables required at build time. The GitHub repo URL is the only external reference and is hardcoded as a named constant in `lib/constants.ts`.

```ts
// lib/constants.ts
export const GITHUB_REPO_URL = 'https://github.com/pajgrtondrej/AgentHarness'
export const DOCS_URL = 'https://github.com/pajgrtondrej/AgentHarness#readme'
```