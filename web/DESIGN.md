---
name: Squint
description: A private, honest reader of whether writing looks AI-written, built as an optician's reading card.
colors:
  ground: "light-dark(#eef1f0, #11161a)"
  card: "light-dark(#fcfdfc, #182025)"
  card-sunk: "light-dark(#f4f6f5, #141b1f)"
  graphite-ink: "light-dark(#16191d, #e6eaec)"
  graphite-2: "light-dark(#454b53, #b8c0c6)"
  muted: "light-dark(#5f666e, #949da4)"
  line: "light-dark(#dbe0de, #273137)"
  line-strong: "light-dark(#b4bcb9, #3b464d)"
  lens-teal: "light-dark(#0a6870, #63c7c6)"
  duochrome-rose: "light-dark(#ad2f4f, #f291a8)"
  neutral-mid: "light-dark(#e6e9e8, #232c31)"
typography:
  headline:
    fontFamily: "Archivo Variable"
    fontSize: "28px (24px under 720px)"
    fontWeight: 650
    lineHeight: 1.15
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Archivo Variable"
    fontSize: "23px"
    fontWeight: 650
    lineHeight: 1.2
  body:
    fontFamily: "Archivo Variable"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Archivo Variable"
    fontSize: "13px / 14px"
    fontWeight: 500
  reading:
    fontFamily: "Source Serif 4 Variable"
    fontSize: "19px (17px under 720px)"
    lineHeight: 1.8
  lede:
    fontFamily: "Archivo Variable"
    fontSize: "1.0625rem"
    lineHeight: 1.55
  wordmark:
    fontFamily: "Archivo Variable"
    fontSize: "1.1875rem"
    fontWeight: 650
  micro:
    fontFamily: "Archivo Variable"
    fontSize: "0.75rem"
    fontWeight: 500
  tag:
    fontFamily: "Archivo Variable"
    fontSize: "0.6875rem"
    fontWeight: 600
  specimen:
    fontFamily: "Source Serif 4 Variable"
    fontSize: "clamp(2.25rem, 4vw, 2.75rem)"
rounded:
  hairline: 1px
  needle: 2px
  key: 6px
  mark: 4px
  control: 10px
  card: 16px
  sheet: 20px
  pill: 999px
spacing:
  s1: 4px
  s2: 8px
  s3: 12px
  s4: 16px
  s5: 24px
  s6: 32px
  s7: 48px
  s8: 64px
components:
  button-primary:
    backgroundColor: "{colors.graphite-ink}"
    textColor: "{colors.card}"
    rounded: "{rounded.control}"
  button-secondary:
    backgroundColor: "{colors.card}"
    textColor: "{colors.graphite-ink}"
    rounded: "{rounded.control}"
  reading-card:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.card}"
---

# Design System: Squint

## Overview

**Creative North Star: "The optician's reading card"**

Squint reads text the way an optician reads eyes. The person holds one card at reading distance: their own words, set in a reading serif on matte card stock. A two-sided duochrome comparison follows, where neither side is the bad side. Then a lens lets them look closer at any word. Every control is graphite. Colour appears only where there is evidence.

The surface is a calm work tool for anxious people: a student, a teacher, a writer. It is dense where it explains and quiet where it waits. It deliberately refuses the detector default of a red percentage gauge and an alarm highlighter over a white SaaS card. It also rejects the previous Squint look as an anti-reference: a bench instrument with chart-paper grid, condensed caps, square corners and cobalt/amber.

**Key Characteristics:**
- One reading card per view: the composer before a check, the marked text after it.
- A duochrome pair, teal for AI-like and rose for human-like. It is used only on evidence and always paired with a non-colour cue.
- Graphite for every control. Errors are written in ink with an icon and words, with no alarm red.
- One grotesque (Archivo) for the interface and one serif (Source Serif 4) for the writer's own text. No caps, no mono, no eyebrows.
- One moving element per view: the needle (220ms), the active stage ring or the lens. Nothing moves under reduced motion.

## Colors

The palette is a cool, faintly tinted near-white ground (never cream) carrying graphite ink. The two duochrome hues are reserved for marks.

### Primary
- **Graphite Ink** (#16191d / #e6eaec): every control, heading, primary button, focus ring, the needle and the active nav pill.

### Evidence pair
- **Lens Teal** (#0a6870 / #63c7c6): AI-like, meaning more predictable than expected. It marks a solid underline in four tint steps, `--ai-1..4`.
- **Duochrome Rose** (#ad2f4f / #f291a8): human-like, meaning more surprising than expected. It marks a dotted underline in four tint steps, `--hu-1..4`.

### Neutral
- **Ground** (#eef1f0 / #11161a): the page.
- **Card** (#fcfdfc / #182025): the reading card, the lens and the sheets.
- **Card Sunk** (#f4f6f5 / #141b1f): notices, the active stage row and the nav track.
- **Graphite 2 / Muted** (#454b53 / #5f666e, with dark equivalents): secondary and tertiary text. Both pass 4.5:1 on the ground and on the card.
- **Line / Line Strong** (#dbe0de / #b4bcb9): 1px dividers and control outlines.

### Named Rules
**The Evidence-Only Rule.** Teal and rose never touch a control, a heading or an error. If something is coloured, it is a measurement.

**The Two-Cues Rule.** Every colour meaning repeats without colour. Solid underline means AI-like and dotted means human-like. Underline weight carries strength. The flagged-share bar is striped. Zone labels sit on the scale.

## Typography

**Interface Font:** Archivo Variable, falling back to system-ui.
**Reading Font:** Source Serif 4 Variable with optical sizing, falling back to Iowan Old Style and Georgia.

**Character:** A plain, slightly wide grotesque speaks for Squint. A bookish serif carries the writer's words, so it is always clear whose text is whose.

### Hierarchy
- **Headline** (650, 28px, 1.15, -0.025em): one h1 per screen. On a result, the band in words is the h1.
- **Title** (650, 23px, 1.2): section titles, the known-gap title and the headline numbers.
- **Body** (400, 16px, 1.55): ledes, explanations, prose capped at 64ch.
- **Label** (500–600, 13–14px): field labels, meter stops, stage names and legend text.
- **Reading** (Source Serif 4, 19px, 1.8, 66ch): the composer and the marked text. The lens shows the selected word at specimen scale (36–44px).

### Named Rules
**The Two Voices Rule.** There are only two text treatments: Archivo for Squint and Source Serif for the person. No caps labels, no monospace, no tracked eyebrows.

## Layout

- **Container:** max 1200px with a 32px gutter (16px under 720px). The top bar is sticky at 60px (56px on phones).
- **Checker, composing:** the main column holds the composer, the length meter and the progress or model note. A 280px aside of three short facts sits beside it and stacks under it below 1040px.
- **Checker, result:**
  - The readout is capped at 880px.
  - "Look closer" puts the marked text beside a 300px side column of reasons and passages. That column is sticky below the bar from 1040px up.
- **Phone:**
  - The routes move to a fixed bottom pill in the thumb zone, and the main area gets 96px of bottom padding.
  - The lens becomes a bottom sheet with a handle.
  - The theme switch and an icon-only Lock stay in the top bar.
- **Rhythm:** an 8px spacing scale (4 to 64). Sections are separated by 1px rules, not boxes.

## Elevation & Depth

The page is a hybrid of tonal layering and two soft shadow tiers. Cards sit on the ground with a 1px line and `shadow-1`. Only floating things get `shadow-2`: the lens, the sheet and the bottom nav.

### Shadow Vocabulary
- **shadow-1** (`0 1px 2px rgba(20,30,34,.06)`; dark `0 1px 2px rgba(0,0,0,.4)`): resting cards.
- **shadow-2** (`0 18px 40px -12px rgba(20,30,34,.22)`; dark `... rgba(0,0,0,.7)`): the lens, the sheet and the bottom nav.

## Shapes

Soft rounded corners throughout:
- reading card and lens: 16px
- controls: 10px
- word marks: 4px
- phone sheet top: 20px
- nav and pills: 999px

Borders are 1px and neutral. No coloured side borders.

## Components

### Buttons
- **Primary:** graphite fill with card-coloured text and a 10px radius. Astryx handles loading and focus.
- **Secondary:** card fill with a 1px line-strong inset outline. Hover adds the hover tint.
- **Ghost / text buttons:** underlined graphite text with a 1px underline that darkens on hover.

### Reading card (composer and printout)
A card-coloured, 16px, 1px-line, shadow-1 sheet. The composer holds a label row, a serif textarea, the attached-file chip and a foot row with Upload, file types, the ⌘/Ctrl Enter hint (desktop only) and Check text. While a check runs, the textarea folds to 9.5em so the stage rows come up into view.

### Length meter
A 4px track with three named stops: Verdict 20, AI-written share 150 and Limit 2,500. The fill is graphite, and a stop fills once it is reached. The guide sentence underneath says what the reader will get at the current length.

### Stage rows
Queue, Warm-up and Scoring each restyle in place: pending (dot), active (sunk row, spinning ring), done (check) or skipped (dash). The active row stays lit until the next stage lands. A polite live region announces the current stage.

### Duochrome scale (signature)
- A 44px field with three zones: Likely AI (teal), Uncertain (neutral) and Likely human (rose). The zone holding the score deepens one tint step; there is no outline box.
- A graphite needle with a value pill eases from the centre to the score once, over 220ms ease-out.
- Zone names sit in a row under the field, centred on each zone. The current zone's name is bold, and the outer names edge-align when their zone is narrow, so all three are always named, on phones too. The "More predictable / More surprising" ends sit beneath.
- When Squint is untuned, the field is a soft gradient with no zones, plus a sentence saying so.
- The whole figure has an `aria-label` that states the score and cutoffs.

### Lens (signature)
- **Desktop:** a 344px card with shadow-2 that opens on hover, tap or arrow key. It shows the word at serif specimen scale, a lean pill, its rank, the odds against what is typical, the top-five table with "written" marking the user's word, the surprise numbers and the sentence lean.
- **Phone:** a bottom sheet with prev/next word buttons and a "Word n of N" count.

### Navigation
- **Desktop:** a pill track in the top bar. The current route gets a card-coloured pill with shadow-1 and `aria-current="page"`.
- **Phone:** a fixed bottom pill whose current tab is filled graphite.

## Do's and Don'ts

### Do:
- **Do** keep teal and rose for evidence, with solid vs dotted underlines carrying direction.
- **Do** put the ChatGPT gap next to every verdict and at the top of the Accuracy page.
- **Do** cap h1 at 28px (24px on phones) and keep one h1 per screen.
- **Do** render only what `/api/accuracy` returns. Untested models read "Untested", with a dashed bar.

### Don't:
- **Don't** use red or amber for errors or for "AI". Errors are ink with an icon and words.
- **Don't** add uppercase eyebrows, monospace numerals or card grids.
- **Don't** animate more than one element per view, and nothing under `prefers-reduced-motion`.

---

## Design process receipts

This redesign was run through the documented workflow. Each step below names what was run and the evidence it left.

### impeccable

| Step | What happened | Evidence |
|---|---|---|
| context | Read `PRODUCT.md` and the previous surface brief. Updated `PRODUCT.md`: known-gap capability, WCAG 2.2 AA. | `PRODUCT.md` diff |
| new-work (REDESIGN) | Treated as a full redesign with the old bench-instrument look as anti-reference. A grounded list of 7 physical-world forms (highlighter on a photocopy, field-guide plate, weather forecast, proofreader galley marks, music dynamics, tide almanac, optician's reading card). | `.impeccable/surfaces/src-app-tsx.md` (FORM) |
| concept-seed | `impeccable concept-seed` returned key `a0c58abc`, assigned index 7, the optician's reading card. Challengers: variable-font specimen, boarding pass/gate board, design annual, streaming wall, Saville sleeve, star atlas. Raises kept: specimen-scale word in the lens, stage rows that restyle in place, one grotesque on a tinted ground. | surface brief FORM section |
| decision page | `serve-question` started once (port 54238). There was no answer within 60s and the session is unattended, so the assigned direction was built. Recorded as Unresolved: Nicky may re-roll. | `.impeccable/decision/direction-payload.json`, `.impeccable/questions/` |
| direction contract | THESIS / OWN-WORLD / STORY / FIRST VIEWPORT / FORM / FINISH written with `surface-brief write` and read back. | `.impeccable/surfaces/src-app-tsx.md` |
| craft-floor | Applied `reference/craft-floor.md`. No eyebrows, no coloured side borders over 1px, no card grids, no gradient text, tracking ≥ -0.025em, one h1, real focus states, no em-dash-as-decoration copy. | `src/styles/app.css` |
| detect | `impeccable detect --json` over `app.css`, `tokens.css`, `App.tsx`, every component and screen, and `index.html` returned `[]` (zero findings). | command output |
| finish review | A fresh general-purpose reviewer subagent was given the request, the code, the contract, the craft-floor and the screenshot set. Its verdict and the fixes applied are recorded under "Finish review" below. | this file |
| document | This `DESIGN.md` and `.impeccable/design.json`. | these files |

### frontend-skill: references (browsed with headless Chrome)

| URL | Principle adapted | Where it shows up |
|---|---|---|
| https://collectui.com/designs/file-upload-ui-design-inspiration | A chat-composer upload: the attached file is a chip inside the composer, next to a single action. | `.file-chip` inside `.composer`. Upload sits in the composer foot beside Check text. |
| https://collectui.com/designs/notepad-ui-design-inspiration | One writing sheet floated on a soft field, with the text as the primary object. | The reading card: `.composer` before a check, `.printout` after it, on the tinted `--ground`. |
| https://recent.design/i/x6k4i8j-effort-slider-microinteraction | A track with named discrete stops whose value label morphs in place. | `LengthMeter` (Verdict 20 / AI-written share 150 / Limit 2,500) and the duochrome scale's labelled zones with the needle's value pill. |
| https://www.designers-machines.com/ (via https://www.landing.love/sites/designers-machines/) | A human-vs-machine theme: muted greys, one saturated line, and a compact pill nav at the bottom in the thumb zone. | `.nav-bottom` on phones, and colour reserved for evidence only. |

Also browsed and not adopted:
- landing.love home
- antimetal.com: a cream-and-serif hero, a trap for an app surface
- the recent.design interface and typography indexes: these fetched empty
- the Collect UI empty-states and tabs pages

### frontend-skill: app-surface rules and anti-template checklist

| Item | Result | Note |
|---|---|---|
| No hero / marketing banner | PASS | The first viewport is the working composer under a 28px h1. |
| h1 ≤ 32px | PASS | 28px desktop, 24px phone (`--t-xl`). |
| Real navigation | PASS | Hash routes with `aria-current`. Top pill on desktop, bottom pill on phones. |
| ≤ 2 text treatments | PASS | Archivo for the interface, Source Serif 4 for the user's text. No caps, no mono. |
| Tokens, not literals | PASS | All colour, radius, space and motion come from `tokens.css` and `theme.ts`. |
| Mobile as its own layout | PASS | Bottom nav, lens as a bottom sheet, stacked aside, icon-only Lock, no keyboard-shortcut hint. |
| Cardless (no dashboard cards) | PASS with a note | There are no card grids. The only cards are the reading card itself, the lens and the known-gap panel on Accuracy, which is deliberately emphasised. Facts, reasons, rates and rows are divided by rules. |
| No purple/blue SaaS gradient | PASS | Graphite with a duochrome used only on evidence. |
| No generic icon-tile feature grid | PASS | The aside is three rule-separated text blocks. |
| No uppercase eyebrow labels | PASS | Sentence case everywhere. |
| No coloured side-stripe callouts | PASS | Notices use a full 1px neutral border with a sunk fill. |
| No fake numbers | PASS | Accuracy renders only API data. Untested models say "Untested". |

### ui-ux-pro-max

- **Declined:** the suggested indigo-and-Lora "wellness" system, because it conflicts with the evidence-only colour rule.
- **Taken:**
  - Colour is never the only carrier of meaning, and text contrast is at least 4.5:1.
  - Visible progress for multi-step work (stage rows).
  - Click or tap, never hover-only: the lens opens on tap and arrow keys.
  - Tab order matches visual order. Targets are at least 44px on phones with at least 8px gaps.
  - `aria-live` / `role="alert"` for status and errors. Submit feedback is a loading button plus stage rows.
  - Reduced motion is honoured, at most 1–2 animated elements, ease-out curves.
  - A diverging heat scale with a legend and a non-colour pattern.
  - Memoised word rendering with stable keys (kept in `HeatText`).

### ux-audit: perfection checklist

| Area | Result | Proof |
|---|---|---|
| Buttons: one primary per view, clear labels, loading state, ≥44px on touch | PASS | `06-ready150-*`, `07-queued-*`. The loading primary keeps its accessible label. |
| Inputs: visible label, word count, length guidance, error tied by `aria-describedby` / `aria-invalid` | PASS | `04-under20-*`, `05-20to149-*`, `Checker.tsx` textarea |
| Navigation: current route marked, reachable on phone, skip link | PASS | `18-accuracy-*`, `19-how-it-works-mobile-*`. `.skip` appears on focus. |
| Visual coherence: one radius family, two shadows, two type voices, graphite controls | PASS | The whole `.qa/web/redesign/` set |
| Mobile: no horizontal overflow at 390, bottom nav, lens sheet, readable 17px serif | PASS | Overflow measured 0 on all 76 captures; `11-word-detail-mobile-*` |
| Feedback: progress, errors, rate limit and warm-up each say what happened and what to do | PASS | `07`, `08`, `13`, `14` |
| States: empty, short, partial, full, loading, error, rate-limited, uncalibrated, accuracy 404 | PASS | `03`–`17` |
| Polish (spacing rhythm, alignment, copy tone) | PASS with notes | See "Finish review" for the remaining items. |

### Accessibility (WCAG 2.2 AA)

- **Heat contrast:**
  - Ink on the strongest tints is about 10:1 in light (#16191d on #94cdcd) and about 7:1 in dark (#e6eaec on #215559 and #642c3e).
  - Underline colours on their tints exceed 3:1.
  - Direction also carries through underline style: solid vs dotted.
- **Keyboard:**
  - Every word is reachable: tab into the text, arrows step word to word, Up/Down move by sentence, Escape closes the lens.
  - The lens on phones has prev/next buttons.
- **Focus:** a 2px graphite or ink `:focus-visible` outline on every interactive element. On a result, focus moves to the verdict h1, which scrolls clear of the sticky bar.
- **Screen readers:**
  - The verdict h1 includes ", low confidence" when it applies.
  - The duochrome figure has a full `aria-label`.
  - The printout has a label and a hint.
  - Stage changes are announced politely; errors use `role="alert"`.
- **Motion:** `prefers-reduced-motion` cuts every animation and transition to near zero, and the needle simply appears in place.
- **Forced colours:** heat tints keep their colours, and current-state elements get an outline.

### ui-stack-router

There were no dependency changes. The stack stays on React 19.3 + Astryx 0.1.9 + StyleX, with Fontsource Archivo and Source Serif 4 already installed. No router receipt was needed, because nothing was added or removed in `package.json`.

### frontend-visual-qa

- **Capture:** `npm run dev:mock` (port 5317). A Playwright script drove the `/__mock/state` switches and fixtures.
- **Coverage:** 19 states × 1440/390 × light/dark = 76 captures, in `/Users/nicky/workspace/projects/squint/.qa/web/redesign/`.
- **Checks on every capture:**
  - Horizontal overflow: 0 everywhere.
  - Console: only the expected 401 (wrong password), 429 (rate limit) and 404 (accuracy not tuned) responses.
- **Round 1 fixes:**
  - The needle crossed the "Uncertain" label; zone labels were lifted above the needle, then moved under the bar after the finish review.
  - The result h1 hid under the sticky bar; added a scroll margin.
  - Progress and errors landed below the fold; they now scroll into view, and the composer folds while running.
  - The keyboard-shortcut hint was hidden on touch.
  - Inline links in How it works no longer break the line.
  - Accuracy rate notes now sit on their own line.
- **Round 2:** the full set was recaptured and inspected.
- **Review copies:** `.impeccable/review/desktop.png` and `.impeccable/review/mobile.png`.

### Finish review

A fresh general-purpose subagent reviewed 16 screenshots across both widths and themes, plus the code, against the contract and the craft-floor.

**Verdict: SHIP WITH FIXES.** It found the build on contract: tinted ground, graphite controls, the two type voices, the duochrome with solid vs dotted underlines, and the dim exam-room dark theme. The phone lens sheet was called strong.

**Fixed after review (recaptured as round 3):**
1. **Heat density.** The faintest step (`ai1`, `hu1`) is now underline only, so fill marks only words that clearly lean.
2. **Scale labels.** Zone names moved under the bar and are never hidden. Before, the "Likely AI" name disappeared on short results on phones.
3. **Active zone.** The 2px ink box was replaced by a deeper tint. The needle now eases over 220ms, per the contract.
4. **Duplicate copy.**
   - The aside heading is now "One clue, not a verdict".
   - The privacy aside was dropped, because the footer already says it.
   - The Uncertain band line no longer repeats the explanation.
5. **Accuracy page.** Paragraph spacing in "Not tuned yet" fixed, and the notes list aligned.
6. **Lens word size.** Raised to specimen scale.
7. **Honesty.**
   - The mock's ChatGPT catch rate now reads "about 1 in 12", matching the gap card.
   - Untuned results get a callout variant that doesn't mention a "Likely human" verdict that isn't there.

**Declined, with reasons:**
- **Striped flagged-share bar.** Kept as the non-colour cue for "flagged".
- **Spinner-only primary while loading.** Astryx sets `aria-label` to the button label and `aria-busy` while loading. The stage rows directly below say what is happening.
- **Disabling Check text while rate-limited.** Kept enabled so a retry is possible once the window passes; the error states the wait.
