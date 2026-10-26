---
name: Squint
description: A private, honest reader of whether writing looks AI-written, set as a copy editor's galley proof.
colors:
  desk: "light-dark(#eef0ed, #0e1114)"
  proof-sheet: "light-dark(#ffffff, #161a1e)"
  sheet-sunk: "light-dark(#f5f6f4, #12161a)"
  graphite-ink: "light-dark(#17191c, #e7eaec)"
  graphite-2: "light-dark(#40464d, #bac1c7)"
  muted: "light-dark(#5b6269, #8f989f)"
  rule: "light-dark(#dcdfdb, #262c32)"
  rule-strong: "light-dark(#b9beb9, #3a424a)"
  selection: "light-dark(#cfe2f6, #234569)"
  nonrepro-rail: "light-dark(#d7e6f4, #132538)"
  rail-rule: "light-dark(#b4cde6, #21405f)"
  blue-pencil: "light-dark(#1d68b5, #79b6f2)"
  blue-wash: "light-dark(#dce9f8, #1a3048)"
  blue-wash-strong: "light-dark(#c3d9f2, #22405f)"
  orange-pencil: "light-dark(#a8530d, #f2a865)"
  orange-mark: "light-dark(#c4620f, #f2a865)"
  orange-wash: "light-dark(#fcebdc, #33241a)"
  orange-wash-strong: "light-dark(#f7d8bb, #47311f)"
typography:
  verdict:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "3.5rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 118"
  title:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 118"
  section:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "-0.02em"
    fontVariation: "'wdth' 110"
  wordmark:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontVariation: "'wdth' 125"
  body:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 550
    lineHeight: 1.2
  small:
    fontFamily: "Archivo Variable, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 550
    lineHeight: 1.45
  reading:
    fontFamily: "Source Serif 4 Variable, Source Serif 4, Iowan Old Style, Georgia, serif"
    fontSize: "1.1875rem"
    fontWeight: 400
    lineHeight: 1.85
rounded:
  page: "0px"
  sheet: "2px"
  mark: "2px"
  control: "4px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
  s8: "64px"
  gutter: "40px"
  margin-column: "300px"
components:
  button-primary:
    backgroundColor: "{colors.graphite-ink}"
    textColor: "{colors.proof-sheet}"
    rounded: "{rounded.control}"
    typography: "{typography.label}"
  button-secondary:
    backgroundColor: "{colors.proof-sheet}"
    textColor: "{colors.graphite-ink}"
    rounded: "{rounded.control}"
    typography: "{typography.label}"
  rail:
    backgroundColor: "{colors.nonrepro-rail}"
    textColor: "{colors.graphite-ink}"
    height: "56px"
  rail-tab:
    textColor: "{colors.graphite-2}"
    typography: "{typography.label}"
  rail-tab-active:
    textColor: "{colors.graphite-ink}"
  galley:
    backgroundColor: "{colors.proof-sheet}"
    rounded: "{rounded.sheet}"
    padding: "32px 48px"
  word-lens:
    backgroundColor: "{colors.proof-sheet}"
    textColor: "{colors.graphite-ink}"
    rounded: "{rounded.control}"
    width: "360px"
    padding: "16px 24px"
---

# Design System: Squint

## Overview

**Creative North Star: "The Galley Proof"**

Squint marks writing the way a copy editor marks a galley proof. The writer's text is the page: a bright white proof sheet with a 1px rule, lying on a cool desk. Squint's evidence goes on it in pencil and in the margin, and the reading is the editor's note at the head of the sheet. Every control and everything Squint says is in graphite ink. The shell is a pale non-repro blue band, the colour an editor's pencil uses because it doesn't print.

Density is calm and editorial. The sheet carries the writing at one reading size in a serif. A narrow margin column beside it holds numbers in one tabular column, the length stops and the editor's queries. There are no explanatory sentences under elements: if a screen needs one, the layout is wrong. Dark theme is the proof desk at night: a graphite sheet on near-black, the same two pencils lifted for contrast.

It turns down the usual detector look of a white card with a percentage gauge and highlighter over every sentence. It also turns down Squint's previous look, the optician's reading card: tinted ground, pill nav and a helper sentence under everything.

**Key Characteristics:**
- Proof-white sheet on a cool desk, 1px rules, square-cut corners (2px sheet, 4px controls).
- Graphite ink for all text and every control, including the primary button.
- Two pencils: blue (AI-like) and orange (human-like). Neither ever fills a control.
- Archivo for Squint's voice, Source Serif 4 for the writer's words.
- Figures in tabular numerals, gathered in the margin.
- No resting shadows. Only floating surfaces lift.

## Colors

A near-monochrome proof in graphite on white, with a pale blue rail and two pencil colours kept for marking.

### Primary
- **Graphite Ink** (graphite-ink): all text, every control fill (primary button, active tab underline, focus ring, current-word outline), the rate bars on the accuracy page. Errors are graphite too, with an icon and words.

### Secondary
- **Blue Pencil** (blue-pencil): the editor's pencil. Solid underlines under AI-like words, the margin brackets and their numbers, query text in the margin, the 2px rule over the known-gap block, length-stop ticks, active progress marks, step counters, the text caret and the drop-zone border. Its pale washes, **Blue Wash** and **Blue Wash Strong**, sit only under ink text on words that lean hard and in the AI zone of the score ruler.
- **Non-repro Rail** (nonrepro-rail) with **Rail Rule** (rail-rule): the sticky top band and its bottom hairline. Nothing else is filled with it.

### Tertiary
- **Orange Pencil** (orange-pencil): text-level orange, used only for the human-like lean label in the word lens and the human-like specimen note. **Orange Mark** (orange-mark) is the dotted underline under human-like words. **Orange Wash** and **Orange Wash Strong** sit under strongly human-like words and in the human zone of the ruler.

### Neutral
- **Desk** (desk): the page ground behind the sheet.
- **Proof Sheet** (proof-sheet): the galley, reading-page sheets, the lens, the phone bottom sheet, secondary button fill.
- **Sheet Sunk** (sheet-sunk): recessed wells such as the file note, the specimen frame and empty bar tracks.
- **Graphite 2** (graphite-2): secondary text, inactive tabs, prose on reading pages.
- **Muted** (muted): counts, placeholders, unreached stops, metadata.
- **Rule** (rule) and **Rule Strong** (rule-strong): 1px dividers. The strong rule opens each margin block and list; the plain rule separates rows.
- **Selection** (selection): text selection only.

### Named Rules
**The Pencil Never Fills a Control Rule.** Blue and orange mark evidence and editor's notes. Buttons, tabs, toggles and focus rings are graphite. Orange is stricter still: it appears only where something reads as human-like.

**The No Alarm Colour Rule.** Errors speak in graphite with an icon and a plain sentence. There is no red anywhere, because the page is often about a real person.

**The Two Channels Rule.** Direction never relies on colour alone. AI-like is a solid underline and human-like is a dotted one. The underline's weight shows strength (1px to 3px), and a wash appears only at the two strongest levels.

## Typography

**Display Font:** Archivo Variable, using its width axis (with Archivo, ui-sans-serif, system-ui)
**Body Font:** Archivo Variable
**Reading Font:** Source Serif 4 Variable with optical sizing (with Iowan Old Style, Georgia)

**Character:** Archivo is Squint talking: heavy and slightly widened at display sizes, plain at text sizes. Source Serif 4 is only ever the writer's own words, or a word the model guessed.

### Hierarchy
- **Verdict** (800, 56px, 1, wdth 118): the reading at the head of the galley. 40px under 760px.
- **Title** (800, 40px, 1.05, wdth 118): page titles on Accuracy, How it works and the password gate. 32px under 760px. The 48px accuracy headline number uses the same cut.
- **Section** (750, 22px, 1.2, wdth 110): section titles and the known-gap title. The lead margin figure shares this size, at 750 and wdth 112.
- **Body** (400, 16px, 1.5): interface text. Prose on reading pages runs 1.6 line height at a 68ch measure.
- **Label** (550 to 650, 15px): tabs, buttons, row labels, the margin column.
- **Small** (550 to 650, 13px): counts, metadata, query tags, stage notes, legend.
- **Reading** (400, 19px, 1.85 serif): the writer's text in the composer and the marked printout. 17px under 760px. 68ch measure.

### Named Rules
**The Two Voices Rule.** Serif means the writer's words; sans means Squint's. Never set Squint's interface copy in the serif, and never set the writer's text in the sans.

**The One Reading Size Rule.** On the galley, the writer's text has exactly one size. Larger serif appears only off the galley, in the lens headword (40px) and the How it works specimen (22px).

**The Tabular Figures Rule.** Every number that can sit next to another number uses tabular numerals: counts, stops, figures, rates, timings, ranks.

## Layout

The checker is a two-column proof inside a 1280px frame with 40px gutters. On the left is the galley sheet. On the right is a 300px margin column, 48px away, which sticks under the rail. The margin holds only the length stops (Word marks 20, Verdict 50, AI-written share 150, Limit 2,500) before a check. During a check, progress writes itself there in stage rows. After a check it holds the figures column, the flagged-passage queries, the "What stood out" disclosure and the known-gap query. The build ships four stops where the direction named three. One region owns each state: the galley is the screen both before and after a check.

Reading pages (Accuracy, How it works) are a single sheet, at most 880px wide, padded 48/64px. Label-and-value rows use a 210px label column.

The spacing scale is a 4px base (4, 8, 12, 16, 24, 32, 48, 64). Rows inside lists are separated by rules rather than gaps.

Responsive changes:
- 1040px and below: margin narrows to 260px, galley padding drops to 24/32px.
- 860px and below: the margin stacks under the galley and stops sticking. The AI-written share moves out of the figures table to sit under the verdict. The tabs move to a second 44px rail row.
- 760px and below: gutter 16px, rail 52px, type steps down (reading 17px, title 32px, verdict 40px). Rows collapse to one column, verdict buttons go full width, and the word lens becomes a bottom sheet.

## Elevation & Depth

Flat by default. Depth comes from the white sheet sitting on the darker desk, edged with a 1px rule. Secondary buttons and the accuracy rate-bar tracks draw their edge with a 1px inset shadow; that is a border, not elevation.

### Shadow Vocabulary
- **Lift** (light `0 14px 36px -10px rgba(15, 22, 30, 0.28)`, dark `0 14px 36px -10px rgba(0, 0, 0, 0.75)`): only the floating word lens and the phone bottom sheet.

### Named Rules
**The No Resting Elevation Rule.** Nothing that sits in the page casts a shadow: sheets, buttons, cards and the rail stay flat. Only a surface that floats over the text lifts.

## Shapes

Proof stock is cut square and pencils leave thin marks. The page has no radius. Sheets and evidence marks use 2px, and controls use 4px. Small checkbox-like stop marks use 1px. Margin brackets are a 2.5px blue stroke open on the left with 2px outer corners (8px wide with a 2px stroke on phones). Dividers are 1px. The only thicker rules are the 2px active-tab underline and the 2px blue rule over the known-gap block. Disclosure chevrons are drawn with borders, and icons are one drawn set: a 20px grid, 1.5px stroke, round caps.

## Components

### Buttons
Astryx buttons, repainted to graphite.
- **Shape:** gently squared (4px).
- **Primary:** a solid graphite ink fill with sheet-coloured text, weight 600. In dark theme it inverts to a light fill with dark text.
- **Secondary:** sheet fill with a 1px inset graphite edge. Hover and press lay the hover and press tints over it; it never turns into a grey fill.
- **Text and icon buttons:** an underlined graphite text button, and a 32px icon button that gains the hover tint.

### Navigation
- **Rail:** sticky, 56px high, filled non-repro blue with a rail-rule hairline. Left to right: the "Squint" wordmark (800, wdth 125), then the routes as underline tabs, then the theme toggle and Lock pushed right.
- **Tabs:** 15px at weight 550 in graphite-2. The active tab turns graphite ink with a 2px ink underline; there are no pills. Below 860px the tabs move to a 44px second row, and the Lock label becomes visually hidden.

### Galley (signature)
The white sheet holding the writer's text. Before a check, its head carries a "Your text" label with the word count, the body is the serif composer with no visible field border, and the foot (above a 1px rule) holds Upload and the primary Check text button. After a check, the head is the verdict: a slug line of figures only ("327 words · 2.5 s"), the verdict, one plain sentence and the actions. Below that, a tools row holds the Clear leans / Every word segmented control and the mark legend, followed by the marked printout.

### Evidence marks (signature)
Each word is a span. AI-like words get a solid blue underline; human-like words get a dotted orange one. The underline weight steps from 1px to 3px with strength, and the two strongest levels add a wash. The default Clear leans view hides the two weakest levels, so the page shows where to look. The word in focus or open in the lens gets a 2px ink outline, the only box on the page.

### Margin brackets (signature)
Each flagged passage gets a blue bracket in the galley's right margin, aligned to its lines, with a small tabular number beside it. Clicking one scrolls to the passage and outlines it. Brackets draw in once when a result lands (scaleY from the top, 240ms, ease-out) and turn ink on hover.

### Margin column
- **Figures:** a single tabular table under a strong rule. Labels sit left in graphite-2 and values right at weight 650. The lead row (AI-written share) is set at 22px.
- **Queries:** a blue-pencil note under a strong rule. A passage query is its own content: the passage range ("Words 76–225") is the clickable button.
- **Length stops and progress stages:** ruled rows with an 18px mark column. Stops tick off in blue as the text grows, and the limit stop's mark is dashed. Stages show a blue spinner while active and a blue check when done.

### Word lens
A 360px floating sheet with a 1px ink border, 4px radius and the lift shadow. It holds the word as a 40px serif headword, its lean (with a blue or orange swatch), its rank and odds, then a table of the model's top five guesses with ink bars, and the actual word tagged with an ink-outlined chip. It opens on hover, tap or arrow keys. On phones it becomes a bottom sheet with an ink top border, at most 56dvh tall.

### Inputs
The composer is borderless serif text on the sheet. The password field is an Astryx text input with the graphite border token. Focus anywhere is a 2px ink outline offset 2px.

### Accuracy rows
Label, a tabular value at weight 700 and a 6px ink bar on a sunk track. Untested rows show a muted value and a dashed 2px line instead of a bar. The binoculars-only score ruler is a 10px sunk track with blue and orange zones, rule-strong cutoffs and a 2px ink needle.

## Do's and Don'ts

### Do:
- **Do** set the writer's text in Source Serif 4 at the single reading size, and everything Squint says in Archivo.
- **Do** put figures in the margin's one tabular column, not inside sentences.
- **Do** carry direction with both colour and underline style: solid blue for AI-like, dotted orange for human-like.
- **Do** keep every control graphite: ink fill for primary, a 1px inset ink edge on sheet for secondary.
- **Do** separate rows with 1px rules and open each margin block with the strong rule.
- **Do** keep motion to the single bracket draw-in and short state fades (140ms), and none under reduced motion.

### Don't:
- **Don't** fill a button, tab or toggle with blue or orange, or use orange for anything that isn't human-like evidence.
- **Don't** use red or any alarm colour for errors or for a Likely AI verdict.
- **Don't** add pill navigation, a tinted page ground, rounded cards over 4px, or a helper sentence under elements. Those belong to the replaced reading-card look.
- **Don't** put a small category tag above a heading or above a sentence that already says the same thing.
- **Don't** give resting surfaces a shadow. Lift is only for the lens and the bottom sheet.
- **Don't** highlight every word. The default view marks only strong leans.

## Provenance

The Galley Proof was chosen by Nicky on 2026-10-25 (seed:df86068ee0cbb1a7). After two fix rounds, the finish review's disposition was ship. Axe found zero violations at 1440px and 390px, in light and dark.
