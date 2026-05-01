# Postal Vote Tally Helper

**Date:** 2026-04-15
**Status:** Draft

## Problem

When postal votes are received, the chairman or operator reads each letter and must manually count votes per candidate, then enter the totals into the postal votes page. This is tedious and error-prone for more than a few letters.

## Solution

A client-side tally helper page that presents a ballot-style interface. The operator ticks candidates for each postal letter, hits "Record", and running counters accumulate automatically. When all letters are processed, "Apply to Postal Votes" navigates to the existing postal votes form with the tallied counts pre-filled.

## Design

### New Route

`GET /admin/election/<id>/postal-tally`

- Admin-only (uses `@admin_required`)
- Read-only — serves the page with offices and candidates from the database
- No POST handler needed; all counting is client-side JavaScript
- Always accessible — no lock based on voting state or round number

### Page Layout

The page has two sections side by side (or stacked on narrow screens):

**Left/Top: Ballot Area**
- Grouped by office, each office shows its candidates as checkboxes
- Enforces `max_selections` per office (same validation as the voter ballot — extra ticks are blocked)
- "Record Letter" button at the bottom
- On Record: increments per-candidate counters in JS, increments letter count, clears all checkboxes for the next letter

**Right/Bottom: Running Tally**
- "Letters processed: N"
- Table per office showing each candidate's accumulated count
- "Apply to Postal Votes" button

### Apply to Postal Votes

Navigates to the existing postal votes page via query string:

```
/admin/election/<id>/postal-votes?prefill=1&postal_voter_count=12&postal_3=5&postal_7=8
```

The existing postal votes page reads these query parameters on GET and pre-fills the form inputs. The operator reviews and saves as normal. If the postal votes page is locked (voting open), the form will be read-only as it already is — the operator can see the pre-filled values but can't save until the lock is lifted.

### No Database Changes

- No new tables or columns
- The tally page does not write to the database
- All persistence happens through the existing postal votes save flow
- Browser state is ephemeral — refreshing the tally page resets the counts

### Navigation

- Add a "Tally Helper" link on the election manage page, near the existing "Postal Votes" link
- The tally page has a "Back" link to the manage page and the "Apply" button that goes to the postal votes page

### Constraints

- max_selections enforcement matches the voter ballot exactly
- No undo/delete — mistakes are corrected on the postal votes totals page before saving
- Client-side only — no server round-trips during tallying for speed

## Files Changed

1. **`app.py`** — New route `admin_postal_tally` (GET only, ~20 lines). Modify `admin_postal_votes` GET handler to read query string prefill values.
2. **`templates/admin/postal_tally.html`** — New template with ballot-style layout and JavaScript counting logic.
3. **`templates/admin/postal_votes.html`** — Add JS snippet to read `?prefill=` query params and populate form fields.
4. **`templates/admin/manage.html`** — Add "Tally Helper" link next to "Postal Votes".
5. **`static/css/style.css`** — Minor styles for the tally page layout (reuse existing ballot styles where possible).
