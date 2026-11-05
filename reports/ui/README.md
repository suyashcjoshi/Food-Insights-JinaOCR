# Phone UI: screenshots and what changed

All shots are 390×844, headless Chrome, light mode unless the
name ends in `_dark`. Regenerate with `scripts/ui_screenshots.py` (see its docstring).

| File | State |
|---|---|
| `capture.png` | Capture, nothing chosen yet |
| `capture_photo.png` | A photo previewed inside the frame; the button now says "Read label" |
| `capture_reading.png` | "Reading…" with the idle warning |
| `why_framing.png` | The "Why framing matters" sheet (three lines) |
| `barcode_sheet.png` | "Scan barcode (optional)" |
| `developer.png` | Developer section with the switch on and the prompt selector showing |
| `result_top.png` | Result sheet right after a read; hero is above the fold |
| `result_scrolled.png`, `result_bottom.png` | Result scrolled: unverified card, allergens, telemetry, raw drawer |
| `result_expanded.png` | "More" and "Show all" open |
| `result_developer.png` | Developer on: raw drawer on the Request tab, prompt used, re-read button |
| `result_matched.png`, `result_mismatch.png` | Cross-check chip yellow (agrees) and amber (disagrees) |
| `result_from_library.png` | A Result opened from the Library |
| `library_filled.png`, `library_allergens.png` | Library with 55 labels; allergen bars and footer |
| `library_empty.png` | Library with no labels |
| `capture_dark.png`, `library_dark.png`, `result_dark.png` | Dark tokens |
| `desktop_column.png` | 1280×800: the same app in a 480 px centred column |

## Measured, not eyeballed

- Capture: scroll height 788 = client height 788, so no scrolling. The viewfinder is 506 px of 844 (60%).
- Result: the carbohydrate hero ends at y = 260; the fixed action bar starts at y = 736.
- No console errors or warnings across the whole run.

## What changed from the previous build

**Structure.** The three links at the top (Capture / Result / Library) are gone. There is a fixed
bottom tab bar with two tabs, Capture and Library. Result is no longer a page: it is a full-height
sheet that opens over whatever is showing, with a back arrow (also Escape and the phone's back
button), and its own fixed bottom bar: "Read another label" and "Open in library".

**Capture.** Was a form: photo box, barcode, language, product name, prompt select, a paragraph of
framing advice, a footer. Now: a viewfinder (60% of the height, dashed frame, four corner marks,
one line), one caption ("Reads the label, never advises."), one "Why framing matters" link, a
yellow "Take photo" button and two text buttons. Barcode, language and name moved to editable
chips on the Result. The prompt selector moved to the Developer section (gear icon), off by
default and remembered in `localStorage` (`fi.dev`, `fi.prompt`).

**Result.** Was a two-column card layout with an all-caps "AS READ" tag, monospace ingredients and
many coloured chips. Now one column: thumbnail, editable name and "Read in 2.9 s"; a cross-check
chip (yellow agrees, grey nothing to compare, amber disagrees) and a language chip; the
carbohydrate number at 56 px on a highlighter background with its basis underneath; one card of
nutrient rows (six visible, "More" for the rest) with a green "Verified" and an "Adds up" line;
an amber "Unverified, check the pack" card in the body font (markdown stripped, six lines then
"Show all") with allergens in two rows, Contains and May contain, still labelled "as read"; a plain
telemetry line; a "Show raw" drawer (Output and Request, monospace, 12 px, scrolls sideways, at
most 40% of the screen).

**Library.** Was a search bar, a language select, a kind select and a side panel of facets. Now a
sticky search, a single-select chip row (All, the languages present, Unverified), a three-column
grid of square thumbnails with name, language and an amber dot for unverified, then the
"Allergen mentions, as read" list with bars (strong = contains, pale = may contain; tap a name or
a bar to filter) and the one footer line. Empty state: "No labels yet. Photograph one to start."

**Look.** Design tokens on `:root` with dark values under `prefers-color-scheme`. One family
(Inter Tight), the five sizes from the brief, sentence case, 8 px grid, 12 px card radius, 24 px
primary button, one shadow (the bottom bars). Yellow only on the hero number and the primary
button; green only on the word "Verified"; amber only for unverified. Removed: all-caps labels,
middle-dot strings, monospace outside the raw drawer, the other greens, blues and reds.
Safe-area insets, visible focus rings and `prefers-reduced-motion` are handled.

**Behaviour kept.** Every API call is unchanged: `/api/health`, `/api/warmup`, `/api/capture`,
`/api/search`, `/api/aggs`, `/api/doc/{id}`. The prompt toggle and re-read still exist (Developer
only), as does the allergen filter by name and by kind.

## Two additions the design needed

- `PATCH /api/doc/{id}`: the name, language and barcode chips have to save somewhere. A new
  barcode re-runs the Open Food Facts check.
- A library with no index yet (before the first capture) is now an empty library, not an error.

## Notes

- The five-colour mark in the Library footer is a stand-in built from the Elastic brand colours,
  not the official logo. Swap in the real asset before publishing.
- "Scan from a photo" in the barcode sheet only appears where the browser has `BarcodeDetector`
  (Chrome and Android); everywhere else you type the digits.
- The 5 "Unnamed label" tiles in `library_filled.png` are captures made while testing the app.
