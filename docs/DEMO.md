# Demo GIF — storyboard (≤60 seconds)

A single screen recording for the README that shows the core loop: *photo of a
W-2 in → reviewable, cited 1040 draft out*, all local. Record at a readable
terminal/desktop size, trim to ≤60s, export as an optimized GIF (or MP4 with a
GIF poster). Target path referenced by the README: `docs/media/demo.gif`.

> Use the bundled **sample** documents, never real PII. A synthetic W-2 fixture
> is fine; the point is the flow, not real numbers.

## Beats

1. **0–6s — Install / connect (one line).**
   Show `claude mcp add taxfill -- uvx taxfill-mcp` (or the one-click `.mcpb`
   dragged into Claude Desktop). Cut to the tools appearing.

2. **6–16s — Drop a document.**
   In the client, attach a sample W-2 image and type: *"Help me start my 2023
   federal return."* Show the assistant calling `intake_checklist` /
   `state_scope` and asking to confirm the extracted figures (the confirm table —
   missing = blank, nothing invented).

3. **16–32s — Compute, with citations.**
   The assistant calls `estimate_refund` / `calc`. Highlight that each line shows
   its source (a `.gov` citation), and that an uncovered number triggers a
   "resolve from source first" rather than a guess.

4. **32–46s — Fill the official PDF.**
   `list_forms` → `fetch_blank` (downloads the blank from irs.gov) → `fill_form`.
   Then `render_form` to show page 1 of the filled 1040 as an image.

5. **46–58s — Review & file.**
   Scroll the rendered draft; show the disclaimer banner ("review draft — not
   tax advice, paper filing only"); show `file_and_pay` printing the mailing
   address + payment options.

6. **58–60s — Tagline card.**
   "TaxFill — local, cited, reviewable. Not a preparer." + repo URL.

## Capture notes

- Hide any personal info in the client window; use a fresh profile.
- Prefer a light, high-contrast terminal theme; bump font size.
- Keep the cursor movements deliberate; pause ~1s on each cited line and on the
  rendered PDF so a viewer can read them.
- `gifski` or `ffmpeg -i demo.mp4 -vf "fps=12,scale=1000:-1" demo.gif` then
  `gifsicle -O3` to keep it under a few MB.
