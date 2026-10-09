# Product

<!-- impeccable:product-schema 1 -->

> Written by the web UI agent from the orchestrator's brief, `README.md` and `docs/api-contract.md`.
> No interview round was possible from the sub-agent (no question channel to Nicky). Facts marked
> *(inferred)* come from the brief's wording, not from Nicky directly; correct them here.

## Platform

web

## Stack

Delegated by the orchestrator to the UI stack router: React 19.3.0 with Astryx
(`@astryxdesign/core` 0.1.9) as the product system, locked in `web/ui-stack.lock.json`.
Built with Vite into `web/dist/`, served by the Python server at `/` with the API under `/api`.

## Users

- Nicky and a small group of people he shares the private password with *(inferred)*.
- The job: paste or upload a piece of writing (an essay, a cover letter, a post, a student's
  homework) and find out whether it was likely written by AI, and why.
- Some users are judging someone else's writing (a teacher, a reviewer, a parent) *(inferred)*.
  A wrong answer can hurt a real person, so the product must read as evidence, never a ruling.
- Used on desktop and on phones.

## Product Purpose

Squint ("squint at it") runs Binoculars locally: two related language models (Falcon-7B and
Falcon-7B-Instruct, 4-bit) read the text, and it compares how predictable each word was against
how predictable the models expected it to be. It returns a verdict band (Likely human /
Uncertain / Likely AI), a share of the text that looks AI-written (from 150 words), the raw
score against its cutoffs, and the evidence word by word.

Success: a user leaves knowing what the tool thinks, how sure it is, and exactly which words
drove that, and does not mistake it for proof.

## Positioning

Most AI detectors return a single percentage and a scary label. Squint shows its working: every
word carries the model's top five guesses, the rank the actual word got, and its surprise
against what was expected. The thresholds are tuned so wrongly flagged human writing stays at
or below about 1%, with non-native writers measured separately, and the accuracy report is
public inside the app.

## Operating Context

- One text at a time; 20 words minimum for a verdict, 150 for the percentage, 2500 maximum.
- Text arrives by paste/typing or by uploading .docx, .pdf or .txt (text lands in the editor
  for review first).
- Checks are queued on one Mac mini; the first check after idle waits ~10-30 s for the models.
- Nothing is stored; results live in server memory for 10 minutes.
- Private behind a shared password; a public launch at `squint.nickymolina.com` is undecided
  and waits for the accuracy report and Nicky's approval.

## Capabilities and Constraints

- API contract: `docs/api-contract.md` (source of truth). Calibration may not exist yet: the
  UI must handle `uncalibrated` verdicts and a 404 accuracy report gracefully.
- Rate limited (30 checks per hour by default).
- Both the band and the percentage are shown (Nicky's explicit choice).
- Undecided: public launch, final accuracy numbers.
- Known gap (docs/known-gaps.md, 2026-10-08): Binoculars on the Falcon pair mostly misses
  ChatGPT writing (1 of 12 caught in a spot check at the ≤1% false-flag setting); Claude text
  separates well; Gemini is untested. The UI states this near every verdict and on the
  accuracy page, and a "Likely human" reading must never read as clearing a text.

## Brand Commitments

- Name: **Squint**. Tagline idea "squint at it" (from the brief).
- Voice: playful in wording, credible and calm in presentation. Never an accusation machine.
- Light and dark themes. Fully responsive.

## Evidence on Hand

- No real accuracy numbers yet (calibration is in progress). The UI must not invent any; the
  accuracy page renders whatever `/api/accuracy` returns and a "not tuned yet" state otherwise.
- Development fixtures are synthetic and live only in the dev-only mock API.
- No logo, illustration or photography assets exist.

## Product Principles

1. Evidence, not a verdict machine: always show why, and always say it is not proof.
2. Honest about uncertainty: short text, uncalibrated thresholds, and known blind spots are
   stated plainly where they matter, not buried.
3. Show the model's working at word level; the heat map is the product.
4. Private by default: say that nothing is stored, and mean it.
5. Fast and light: one text in, one clear answer out, on a phone too.

## Accessibility & Inclusion

- WCAG 2.2 AA. The heat map must never rely on colour alone (colour-blind-safe diverging
  palette plus a non-colour channel and a text summary).
- Every word's details are reachable by keyboard, not only on hover.
- Non-native English writers are a named group in the accuracy report; copy must not imply
  that plain or formulaic writing is cheating.
