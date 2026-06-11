# Projector display: fill the screen on sparse content

Date: 2026-06-11

## Goal

Make the projector display use the full screen height when there is
little content. A round that elects one or two brothers currently leaves
the bottom half of the screen blank, which is hard to read from the back
of the church and looks unfinished. Content should scale up and centre so
the screen reads well whether a round elects one brother or a dozen.

## Background

The live results display ([projector.html](../../../templates/display/projector.html))
already has an auto-scaler (`autoSizeOffices`) that grows the offices grid
to fit the available height. Three display states do not benefit from it:

1. **Final Results** ([final.html](../../../templates/display/final.html)),
   the phase-4 screen. Fixed font sizes, top-anchored, no scaling at all.
   This is the worst case and the screen the congregation looks at longest.
2. **Welcome panel** ("Voting will begin shortly") in
   [projector.html](../../../templates/display/projector.html). Fixed sizes,
   top-anchored, shown to a full room before voting opens.
3. **Live results, sparse rounds.** The auto-scaler caps a single
   non-rotating office at 2.2x, so a 1-office / 1-2-candidate round hits
   the cap and still leaves whitespace during counting.

## Non-goals

- No shared/extracted JS helper. Each template is fixed in place to keep
  risk away from the proven live-results scaler (it ran the 7 June 2026
  election). Some logic is duplicated by design.
- No change to phone rendering. Every change is gated so it does not fire
  at `innerWidth <= 720`; the existing `@media (max-width: 720px)` mobile
  layouts are untouched.
- No new database columns, routes, or API changes. Display-only.
- No change to the rotating-office behaviour or the 0.6 shrink floor.

## Part 1: Final Results screen (final.html)

Behaviour: scale up to a cap, then vertically centre the remainder.

- `.display-main` becomes a fixed-height flex column
  (`height` = viewport minus topbar, `display: flex; flex-direction:
  column; justify-content: center`). This vertically centres the
  title + offices + note block so empty space splits top and bottom.
- A one-shot inline script measures the natural height of the content
  block against the available height and sets a `--final-scale` CSS
  variable that multiplies the font sizes (title, office heading,
  vacancy line, names, closing note).
- Runs once on load and on `resize`. No polling: `final.html` only
  re-checks the phase every 5s and reloads on a phase change.
- Scale **cap 1.9x**, **floor 1.0** (never shrink below the current
  design; many-office rounds already wrap across the flex row).
- Skip scaling when `innerWidth <= 720`.

Net effect for the single-Deacon screenshot: the card and name scale
toward 1.9x and the whole block centres, filling the screen.

## Part 2: Welcome panel (projector.html)

The welcome content is fixed and predictable, so it gets larger
hand-tuned sizes plus centring rather than a measure-and-scale script.

- Centre the panel vertically in the available height. When it shows, the
  summary/results area below is empty (no ballots yet), so it can own the
  screen.
- Bump fixed sizes to projector scale: heading 32px -> ~56px; instruction
  line and WiFi text 20px -> ~32px.
- CSS only, no JS. Gated by the existing `@media (max-width: 720px)` rules.
- Centring is scoped to the welcome panel's own wrapper so it is inert
  once voting opens and the live summary panel renders. The welcome panel
  only renders when `not voting_open and total_ballots == 0 and
  display_phase != 4`.

## Part 3: Live-results cap for sparse rounds (projector.html)

A deliberately small change to proven code.

- Raise the single-office cap from **2.2x to 3.0x** at
  [projector.html:809](../../../templates/display/projector.html#L809). Lets
  a sparse live screen grow without reaching the rotating cap (3.4x),
  which is tuned for full-width one-office-at-a-time display.
- Leave the rotating cap (3.4x) and the 0.6 floor unchanged.
- No centring here. The fixed summary panel (ballot counts, progress bar)
  anchors the top third, so the results grid filling downward is correct.
  Centring would fight the summary panel. This screen is "scale only".

## Summary

| Screen | Change | Mechanism |
| --- | --- | --- |
| Final Results (final.html) | Scale-to-fit + vertical centre | One-shot JS scaler, cap 1.9x, flex-centre |
| Welcome panel (projector.html) | Bigger fixed sizes + centre | CSS only |
| Live results (projector.html) | Fill sparse screens | Single-office cap 2.2x -> 3.0x |

## Testing

- Existing display tests must still pass.
- Manual verification on a projector-sized viewport (and a phone-sized
  viewport to confirm the guards hold) for:
  - Final Results: 1 office / 1 name; 1 office / many names; several
    offices; the no-appointments case.
  - Welcome panel: with and without a WiFi password.
  - Live results: 1 office / 1-2 candidates (sparse); many offices
    (rotating); a long single-office candidate list (shrink-to-fit).
- The live-results display is re-verified specifically because Part 3
  edits code that ran a real election.
