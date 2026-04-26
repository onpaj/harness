# AgentHarness Landing Page

Single-file static landing page pitching AgentHarness — the autonomous brief-to-PR multi-agent pipeline.

## Open

Open `index.html` directly in any modern browser:

- macOS: `open index.html`
- Linux: `xdg-open index.html`
- Windows: `start index.html`

The page works fully offline via the `file://` protocol. Google Fonts load over the network when available; if blocked, the system font stack is used.

## Before publishing

Two placeholders must be filled in before this page is shared:

1. **Contact destination.** The primary CTA links to `mailto:TODO@TODO.dev`. Replace it. To find unfilled placeholders, run:

   ```
   grep -n 'data-todo' index.html
   ```

2. **Optional source link.** The CTA section has a commented-out secondary `<a class="btn btn--ghost">` block. Uncomment and set `href` if a public/internal repo link should appear.

## Constraints

- Single `index.html`, all CSS inline.
- Zero JavaScript.
- ≤800 lines total, ≤100 KB excluding fonts.
- WCAG AA contrast for body text.
- Honors `prefers-reduced-motion: reduce`.
