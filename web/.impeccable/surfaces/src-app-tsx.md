---
version: 1
slug: "src-app-tsx"
primary_target: "src/App.tsx"
related_targets: []
---

## Scope and mode

Squint web app: checker (Operate, primary), How accurate is this? and How it works (Read), password gate. Phone and desktop, light and dark. Full redesign; the previous bench-instrument look (chart-paper grid, condensed caps, square corners, cobalt/amber) is the anti-reference.

Audience and job: a student, teacher or writer at a desk or on a phone, often anxious, pastes or uploads one piece of writing to learn whether it reads as AI-written, how sure the tool is, and which words drove it, without mistaking it for proof.

## Direction contract

THESIS: Squint reads text the way an optician reads eyes: one card held at reading distance, a two-sided duochrome comparison where neither side is the bad side, and a lens for looking closer. It refuses the detector default of a red percentage gauge and alarm highlighter over a white SaaS card.

OWN-WORLD: Matte card stock on a cool, faintly tinted near-white ground (never cream); graphite ink for every control. Duochrome pair used only on evidence: rose (#c23b61 family) for human-like, lens teal (#0b6f78 family) for AI-like, each with a non-colour cue (dotted underline vs solid underlay). Archivo at normal width, sentence case, for all UI; the user's own text set in Source Serif 4 like a reading-card paragraph. Soft rounded radii (card 16, control 10, pill), two soft shadow tiers, 1px borders. Dark theme is the dimmed exam room: deep blue-grey, same grammar.

STORY: The visitor sees what they will get at this length, runs the check with honest stage-by-stage progress, reads the band and the plain caveat (ChatGPT is often missed), then looks closer through the lens, word by word.

FIRST VIEWPORT: Slim top bar: Squint wordmark, three routes (Check, Accuracy, How it works), theme, lock. Below, one wide reading card: textarea with an attached-file chip inside the composer, a length line (20 / 150 / 2,500), Check text primary bottom-right. After a run: verdict line (band in words, h1 at most 32px), the duochrome scale with needle and cutoffs, % AI-written only at 150+, then the marked text with a side column of reasons and passages on wide screens. Phone: bottom pill nav, stacked, word lens as a bottom sheet.

FORM: Optician's reading card with duochrome test, grounded list position 7 of 7 (1 highlighter on a photocopy, 2 field-guide plate, 3 weather forecast, 4 proofreader galley marks, 5 music dynamics marks, 6 tide almanac, 7 optician's reading card). Seed key a0c58abc. Decision page probed once unattended (no answer); assigned direction built.
Raise from variable-font specimen: the word lens shows the selected word at specimen scale with its ranked guesses beneath.
Raise from boarding pass and gate board (competitive): queue, warm-up and scoring rows restyle in place and stay lit until the next stage lands.
Raise from design annual plate section: one grotesque carries display and caption alike; the ground is tinted, never pure white.
Signature interaction: the lens. Hover, tap or arrow-key onto any word and a round-cornered lens opens with that word large, its rank, surprise against expected, and the top five guesses; arrows step word to word, Up/Down by sentence.
Motion grammar: one moving element per view; the needle eases to its reading in 220ms ease-out; stage rows restyle in place; nothing moves under reduced motion.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Direction chosen unattended (decision page probed once, unanswered); Nicky may re-roll.
- Real accuracy numbers do not exist yet; the accuracy page renders only what the API returns.
