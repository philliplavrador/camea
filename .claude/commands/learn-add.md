---
description: Add a new section to a learn/ plain-language explainer in the house style, then republish it
argument-hint: <topic> [-- what to cover] [-- into <file.html>]
---

Add a new section to a `learn/` explainer, in the beginner-friendly house style the user loves.

$ARGUMENTS

**First, read [`learn/README.md`](../../learn/README.md)** — it defines the house style, the
component kit (the exact HTML/CSS classes to reuse), the hard invariants, and the publish/verify
steps. Follow it exactly. Default target file: `learn/spectralign_placement.html` (unless the user
named another after `into`).

Then:

1. **Understand the topic well enough to teach it simply.** If it concerns spectralign, the
   mosaic pipeline, or the acquisition, ground yourself first in `utils/knowledge/` (start at
   `INDEX.md`), the vendored source under `utils/vendor/spectralign/`, and `analysis/mosaic/`.
   Use real numbers from an actual run where you can — never placeholders.
2. **Draft the section in the house style:** open with a real-world **analogy**, explain in plain
   language, and only then introduce jargon — defining each new term inline as a `.term` hover
   tooltip. Put any maths in an optional, dashed `.peek` box with every symbol translated. Assume
   the reader (a biologist) has little maths/stats.
3. **Insert it** as a new `<section class="stage">` block, copied from an existing one, placed
   where it reads naturally. Number it only if it belongs to a genuine sequence; otherwise give it
   a non-numeric marker (like the "the problem" section uses `&middot;`).
4. **Add every new jargon word to the glossary** (`<dl class="glist">`) so nothing relies on hover.
5. **Respect the invariants** (from the README): pure-ASCII (entities/escapes — no raw non-ASCII),
   all content visible (no scroll-reveal), self-contained, theme-token colours, SVG colours via
   `style="…"`.
6. **Verify in a browser** before finishing: serve `learn/` over `http.server` (the browser tool
   can't open `file://`), then screenshot the full page (confirm no blank sections), a tooltip, and
   dark theme. Fix anything that looks wrong. Delete any screenshots left in the repo root.
7. **Republish to the SAME artifact link.** Update the file in place and republish the same file
   path. From a fresh session, pass the existing URL
   (`https://claude.ai/code/artifact/f0a2ead9-68e8-4698-9257-69a13481ef78`) to the Artifact tool's
   `url` parameter so it updates in place instead of minting a new link.
8. **Log it:** add a one-line note to the top entry of `utils/knowledge/worklog.md`.

Hard rules:
- **Never break the invariants** in `learn/README.md` — especially *pure-ASCII* and *no hidden
  content*.
- **Never mint a new artifact URL** — always update the existing one in place.
- **Explain, don't impress.** Plain language and a good analogy beat precision the reader can't
  follow. When in doubt, simpler.
