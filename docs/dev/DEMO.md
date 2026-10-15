# Demo GIF — storyboard (≤60 seconds)

A single screen recording for the README that shows the core loop: *photo of a
W-2 in → reviewable, cited 1040 draft out*, all local. Record at a readable
terminal/desktop size, trim to ≤60s, export as an optimized GIF (or MP4 with a
GIF poster). Target path referenced by the README: `docs/media/demo.gif`.

> Use the sample W-2, never real PII: [`docs/samples/w2_2025_synthetic.png`](../samples/w2_2025_synthetic.png)
> (or the [PDF](../samples/w2_2025_synthetic.pdf)), a demo persona's 2025 W-2 with a SAMPLE watermark
> (Jordan Q. Taxpayer, SSN 999-88-0425, single, Washington all year; every name and number is fictitious).
> `scripts/make_sample_w2.py` generates it; the figures below are what the tools return for it, the same
> ones the user guide's walkthrough quotes.

## Beats

1. **0–6s — Install / connect (one line).**
   Show `claude mcp add taxfill -- uvx taxfill-mcp` (or the one-click `.mcpb`
   dragged into Claude Desktop). Cut to the tools appearing.

2. **6–16s — Drop a document.**
   In the client, attach `w2_2025_synthetic.png` and type: *"Help me start my 2025
   federal return."* Show the assistant calling `intake_checklist` /
   `extract_document` / `state_scope` and asking to confirm the extracted figures —
   **wages $168,100** and **federal tax withheld $30,487** (the confirm table:
   missing = blank, nothing invented; Washington: no state return).

3. **16–32s — Compute, with citations.**
   The assistant calls `estimate_refund` / `calc`: **a refund of about $1,076**
   (2025 tax $29,411 on $152,350 of taxable income). Highlight that each line shows
   its source (a `.gov` citation), and that an uncovered number triggers a
   "resolve from source first" rather than a guess.

4. **32–46s — Fill the official PDF.**
   `list_forms` → `fetch_blank` (downloads the blank from irs.gov) → `fill_form`.
   Then `render_form` to show page 1 of the filled 2025 Form 1040 as an image.

5. **46–58s — Review & file.**
   Scroll the rendered draft; show the disclaimer banner ("review draft — not
   tax advice, paper filing only"); show `filing_summary` ("Federal 2025: refund
   $1,076") and `file_and_pay` printing the mailing address (Ogden, UT 84201-0002)
   + refund options.

6. **58–60s — Tagline card.**
   "TaxFill — local, cited, reviewable. Not a preparer." + repo URL.

## Capture notes

- Hide any personal info in the client window; use a fresh profile.
- Prefer a light, high-contrast terminal theme; bump font size.
- Keep the cursor movements deliberate; pause ~1s on each cited line and on the
  rendered PDF so a viewer can read them.
- `gifski` or `ffmpeg -i demo.mp4 -vf "fps=12,scale=1000:-1" demo.gif` then
  `gifsicle -O3` to keep it under a few MB.
