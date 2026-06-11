# Projector display: fill the screen on sparse content

Date: 2026-06-11

## Goal

Make every projector display screen use the full screen height when there
is little content. A round that elects one or two brothers, or a small
slate, currently leaves the bottom half of the screen blank, which is hard
to read from the back of the church and looks unfinished. Content should
scale up and centre so each screen reads well whether a round elects one
brother or a dozen.

## Background

The display has six templates ([templates/display/](../../../templates/display/)).
An audit of all six for wasted vertical space found that five of the six
under-fill on a projector; only `phone.html` is correctly excluded (it is
the phone-only voter view, capped at 480px width, and never renders on the
projector).

The layout container is shared: `.display-body` is `height: 100vh; display:
flex; flex-direction: column` and `.display-main` is `flex: 1` (it already
fills the height left below the topbar). The under-fill comes from content
sitting top-anchored inside that filled container, or from auto-scalers
that cap too low.

Two templates already have an auto-scaler:
- `projector.html` (`autoSizeOffices`, `--proj-scale`) scales the live
  results grid; single-office cap 2.2x, rotating cap 3.4x, floor 0.6.
- `rules.html` (`autoSizeRules`, `--rules-scale`) scales the rules layout;
  cap 2.0x, but also constrained by a horizontal no-wrap limit so long
  candidate names do not wrap, and it deliberately falls back to page
  scrolling (`display-body` overridden to `height: auto`).

## Non-goals

- No shared/extracted JS helper. Each template is fixed in place. The
  proven `autoSizeOffices` scaler ran the 7 June 2026 election; keeping
  changes local limits blast radius. Some scaler logic is duplicated by
  design.
- No change to phone rendering. Every JS change is gated at
  `innerWidth <= 720`; existing `@media (max-width: 720px)` layouts and
  `phone.html` are untouched.
- No new database columns, routes, or API changes. Display-only.
- No change to the rotating-office behaviour, the 0.6 shrink floor, or the
  `rules.html` no-wrap and scroll-fallback design.

## Approach

Two mechanisms, chosen per template by whether it already scales:

- **Scale then centre** for templates with no scaler and fixed sizes
  (`final.html`, `welcome.html`): a one-shot JS scaler measures natural
  content height against the available height, sets a CSS variable that
  multiplies the font sizes, capped, floored at 1.0 (never shrink), and the
  block is vertically centred so any leftover space splits top and bottom.
  Runs once on load and on `resize`. Guarded at `innerWidth <= 720`.
- **Tune the existing scaler / centre in CSS** for templates that already
  scale or need only alignment (`projector.html`, `rules.html`,
  `waiting.html`).

## Part 1: Final Results (final.html)

No scaler today; `justify-content: flex-start` pins content to the top.

- Override the inline style on `.display-main` from
  `justify-content: flex-start` to `justify-content: center` so the
  title + offices + note block centres in the already-filled container.
- Add a one-shot inline script: measure the summed natural height of the
  `.display-main` children (title, subtitle, offices, note) against
  `.display-main` `clientHeight`, set `--final-scale` that multiplies the
  font sizes (title, office heading, vacancy line, names, note).
- Run on load and `resize`. No polling: `final.html` only re-checks the
  phase every 5s and reloads on a phase change.
- Scale **cap 1.9x**, **floor 1.0**. Skip when `innerWidth <= 720`.

## Part 2: Live results (projector.html)

Has the `autoSizeOffices` scaler. Two changes:

- Raise the single-office (non-rotating) cap from **2.2x to 3.0x** at
  [projector.html:809](../../../templates/display/projector.html#L809).
  Lets a sparse live screen grow without reaching the rotating cap (3.4x).
- Vertically centre each office's content **within the results region**
  (the `.display-office` cell), for both rotating and non-rotating modes,
  so when the scaler hits its cap the leftover space is balanced rather
  than dumped at the bottom. This centres only the results grid; the fixed
  summary panel (ballot counts, progress bar) above it is unaffected.
- Leave the rotating cap (3.4x) and the 0.6 floor unchanged.

## Part 3: "Voting will begin shortly" panel (projector.html)

The pre-open panel at
[projector.html:212-227](../../../templates/display/projector.html#L212-L227).
Fixed content, so larger hand-tuned sizes plus centring, no JS.

- Centre the panel vertically in the available height. When it shows, the
  results area below is empty (no ballots yet), so it can own the screen.
- Bump fixed sizes to projector scale: heading 32px -> ~56px; instruction
  line and WiFi text 20px -> ~32px.
- CSS only. Centring is scoped to the panel's own wrapper so it is inert
  once voting opens and the summary panel renders. The panel only renders
  when `not voting_open and total_ballots == 0 and display_phase != 4`.

## Part 4: Congregation welcome (welcome.html)

Phase 1, the first screen the congregation sees. Already centred
(`justify-content: center; align-items: center`), no scaler. Round 1 has a
large phone-instructions card; round 2+ is sparse (a heading, office
cards, a short note).

- Add a one-shot scale-to-fit script matching Part 1: measure
  `.display-main` natural content height against its `clientHeight`, set
  `--welcome-scale` multiplying the inline font sizes via a small set of
  scoped CSS rules, **cap 1.6x**, **floor 1.0**, guard `innerWidth <= 720`.
- The template already vertically centres, so no alignment change. The
  scaler only grows sparse content to fill; with floor 1.0 it never shrinks
  the content-heavy round-1 card (it computes ~1.0 when already full, so no
  clipping against `display-main` `overflow: hidden`).
- The existing `<meta refresh 5>` reloads the page every 5s; the
  on-load scaler re-runs each reload, same as `rules.html` does today.

## Part 5: No-active-election screen (waiting.html)

`.display-waiting` uses fixed `padding: 100px 40px` and never fills; it is
a direct child of `body.display-body` (no topbar, no `.display-main`).

- CSS-only change in [style.css:864](../../../static/css/style.css#L864):
  make `.display-waiting` `flex: 1; display: flex; flex-direction: column;
  justify-content: center; align-items: center` and reduce the fixed
  padding so content centres in the full viewport.
- No JS. Content is small and static; centring is enough.

## Part 6: Rules screen (rules.html)

Medium severity. Already has `autoSizeRules` (cap 2.0x, vertical buffer
0.94) but is constrained by a horizontal no-wrap limit (candidate names
must fit one line) and deliberately scrolls when content is tall
(`display-body` overridden to `height: auto; overflow: visible`).

- Conservative tune only: raise the vertical buffer from **0.94 to 0.96**
  and the cap from **2.0x to 2.4x** at
  [rules.html:291-296](../../../templates/display/rules.html#L291-L296).
- Keep the no-wrap horizontal constraint and the scroll-fallback. Do **not**
  force vertical centring: the page is intentionally `height: auto` so it
  can scroll, and there is no fixed-height container to centre within.
- Note: the residual empty band on `rules.html` is partly intrinsic. When
  a long candidate name is the binding constraint, the scale cannot rise
  without wrapping the name, so some bottom space is unavoidable. This part
  reduces the band, it does not eliminate it.

## Summary

| Screen | Phase | Change | Mechanism |
| --- | --- | --- | --- |
| final.html | 4 Final Results | Scale-to-fit + centre | New one-shot JS scaler, cap 1.9x |
| projector.html (results) | 3/5 live results | Raise cap, centre in region | Cap 2.2x -> 3.0x + CSS centring |
| projector.html (welcome panel) | 3 pre-open | Bigger sizes + centre | CSS only |
| welcome.html | 1 congregation welcome | Scale-to-fit | New one-shot JS scaler, cap 1.6x |
| waiting.html | no active election | Centre + fill | CSS only (style.css) |
| rules.html | 2 rules | Tune existing scaler | Buffer 0.94 -> 0.96, cap 2.0x -> 2.4x |

`phone.html` is unchanged (phone-only voter view).

## Testing

Layout and scaling run client-side, so the test split is:

- **Automated (pytest, render-level):** assert the right route renders the
  right template with the new structural hooks present, so a future edit
  cannot silently remove them. For example: `/display` at phase 4 renders
  `final.html` containing `justify-content: center` and the `--final-scale`
  scaler script; the welcome panel markup carries its centring wrapper;
  `style.css` `.display-waiting` block contains the flex-centring rule;
  `projector.html` contains the 3.0 cap; `rules.html` contains the tuned
  0.96 / 2.4 constants. These guard against regressions in wiring and
  constants, not against visual correctness.
- **Manual (run the app at projector resolution):** confirm fill and that
  nothing clips for:
  - final.html: 1 office / 1 name; 1 office / many names; several offices;
    the no-appointments case.
  - projector.html live results: 1 office / 1-2 candidates (sparse); many
    offices (rotating); a long single-office candidate list (shrink-to-fit).
  - projector.html welcome panel: with and without a WiFi password.
  - welcome.html: round 1 (content-heavy) and round 2 (sparse).
  - waiting.html: with and without WiFi info.
  - rules.html: short slate and long slate (verify no name wraps).
  - A phone-width viewport on each, to confirm the `<= 720` guards hold and
    the mobile layouts are unchanged.
- The live-results display is re-verified specifically because Part 2 edits
  code that ran a real election.
