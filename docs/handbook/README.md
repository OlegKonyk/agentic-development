# Handbook — the printable overviews

Three self-contained pages that explain this project without requiring you to
read the code. Each exists twice: a **PDF** for reading and sharing, and the
**HTML source** it was rendered from, which opens offline in any browser with no
network access and no build step.

| | Read this to learn |
|---|---|
| **[01-lab-review.pdf](01-lab-review.pdf)** (11pp) | What was built and what it found — the apparatus, the six seats, three rounds of measured results, and the findings ledger. Start here. |
| **[02-system-map.pdf](02-system-map.pdf)** (8pp) | How the machine works — every trigger, every guard, and the incident behind each one. Read this when you want to build something like it. |
| **[03-round-3-preflight.pdf](03-round-3-preflight.pdf)** (4pp) | The operator checklist for onboarding a real team, including the GitHub access model. |

The HTML versions are the originals (`review.html`, `system-map.html`,
`round-3-preflight.html`). They are theme-aware, they contain no external
requests, and the pre-flight page is interactive — its checkboxes persist in
your browser's local storage.

## Regenerating the PDFs

The pages render with Chromium via Playwright, which the QA suite already
depends on:

```bash
uv run playwright install chromium          # once, if you don't have it
uv run python scripts/render_handbook.py    # writes the three PDFs
```

## A note on the diagrams

The published web versions of these pages use Mermaid, which the hosting
runtime renders natively. The copies committed here replace those blocks with
static text diagrams so they render identically in a plain browser and in
print — no JavaScript, no CDN, no silent blank box. The live Mermaid source for
the pipeline flow is in [`../sdlc.md`](../sdlc.md), which GitHub renders on the
web.
