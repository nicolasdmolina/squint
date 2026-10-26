---
version: 1
slug: "src-app-tsx"
primary_target: "src/App.tsx"
related_targets: []
---

## Scope and mode

Squint web app: checker (Operate, primary), Accuracy and How it works (Read), password gate. Phone and desktop, light and dark. Full redesign (2026-10-25). Anti-references: the optician's reading card (tinted ground, pill nav, explanatory sentence under every element) and the older bench-instrument look.

Audience and job: a student, teacher or writer at a desk or on a phone pastes one piece of writing to learn whether it reads as AI-written, how sure Squint is, and which words drove it, without mistaking it for proof.

Governing rule (Nicky): cut taglines, helper text and secondary labels; if a screen needs them, fix the layout.

## Direction contract

THESIS: Squint marks writing the way a copy editor marks a galley proof: the text is the page, evidence goes in pencil and in the margin, and the reading is the editor's note. It refuses the detector default of a white card with a percentage gauge and highlighter over every sentence.

OWN-WORLD: Cool proof-white ground, bright white galley sheet with a 1px rule, graphite ink. Shell is a non-repro blue band. Two pencils carry evidence only: blue (AI-like, solid underline plus a pale wash) and orange (human-like, dotted underline). Archivo for Squint's voice at a few steps, Source Serif 4 for the writer's text at one reading size. Square-ish corners (4px controls, 2px marks), no shadows except the floating lens. Numbers tabular. Dark theme: the proof desk at night, graphite sheet on near-black, same pencils lifted.

STORY: The visitor pastes text into the galley, presses Check, watches progress written in the margin, reads the verdict as a large editor's note with one plain sentence, sees flagged passages bracketed in the margin, and opens any word to see what the model expected.

FIRST VIEWPORT: Blue rail: Squint wordmark left, Check / Accuracy / How it works as underline tabs, theme toggle and lock right. Below, a two-column proof: the galley sheet (about 2/3) holding the textarea at reading size with word count and Check text in its foot; the margin column (1/3) holding only the length stops (Verdict 50 · Share 150 · Limit 2,500) and later the queries. After a check: verdict at 56px in the galley head, one sentence, the marked text with margin brackets on flagged passages; margin holds numbers in one tabular column and the known gap as a single query.

FORM: Copy editor's galley proof with blue-pencil queries, grounded list position 7 of 7 (1 graded paper, 2 highlighter study notes, 3 composition notebook, 4 dictionary entry, 5 scantron answer sheet, 6 library due-date card, 7 galley proof). seed:df86068ee0cbb1a7. Chosen by Nicky on 2026-10-25.
Raise from zoo guide map: one region owns each state; the galley is the screen before and after a check.
Raise from orienteering map: one reserved colour above the marks; only the word in focus gets the ink box.
Raise from ticket wallet: progress writes itself into the margin instead of a separate status panel.
Raise from acetate manual: one reading size for the text; Squint's own type uses few sizes.
Raise from datamatics: figures sit in one tight tabular column, not inside sentences.
Signature interaction: margin brackets. Each flagged passage gets a blue bracket in the margin aligned to its lines; clicking a bracket scrolls and outlines that passage. The word lens opens on hover, tap or arrow keys.
Motion grammar: one moment, the brackets draw in once (scaleY, 240ms ease-out) when a result lands; nothing moves under reduced motion.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Claude Design prototypes of the checker are a follow-up for Nicky to compare.
