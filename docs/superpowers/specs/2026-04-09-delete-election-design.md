# Delete Election Feature

## Summary

Add a "Delete Election" button to the admin dashboard that permanently removes an individual election and all its dependent data. Confirmation requires typing the election name (GitHub-style).

## UI

### Dashboard (election card)

- Add a red "Delete" button to each election card on the dashboard
- Clicking "Delete" reveals an inline confirmation form below the card:
  - Label: `Type "<election name>" to confirm deletion`
  - Text input field
  - "Confirm Delete" button (red/destructive styling)
  - "Cancel" link/button to hide the form
- The reveal/hide is handled with JavaScript (no page reload)
- Form submits via POST to `/admin/election/<id>/delete`

### Interaction flow

1. Admin clicks "Delete" on an election card
2. Inline form appears asking to type the election name
3. Admin types the name and clicks "Confirm Delete"
4. Server validates the name matches
5. On match: cascade delete all data, flash success, redirect to dashboard
6. On mismatch: flash error ("Election name does not match"), redirect to dashboard

## Backend

### New route

```
POST /admin/election/<int:election_id>/delete
```

- Protected by `@admin_required`
- Accepts form field `confirm_name`
- Fetches election by ID; 404 if not found
- Compares `confirm_name` against `election.name` (exact match)
- On mismatch: flash error, redirect to dashboard
- On match: cascade delete, flash success, redirect to dashboard

### Cascade delete order

Delete in this order to respect foreign key constraints:

1. `DELETE FROM votes WHERE election_id = ?`
2. `DELETE FROM paper_votes WHERE election_id = ?`
3. `DELETE FROM postal_votes WHERE election_id = ?`
4. `DELETE FROM codes WHERE election_id = ?`
5. `DELETE FROM candidates WHERE office_id IN (SELECT id FROM offices WHERE election_id = ?)`
6. `DELETE FROM offices WHERE election_id = ?`
7. `DELETE FROM round_counts WHERE election_id = ?`
8. `DELETE FROM elections WHERE id = ?`

All within a single transaction (commit once at the end).

### No restrictions

- Deletion is allowed regardless of election state (voting open, results shown, etc.)
- The typed-name confirmation is sufficient protection

## Tests

Add to `test_app.py`:

1. **Delete succeeds with correct name** - Create election, delete with matching name, verify 302 redirect and election gone from DB
2. **Delete rejected with wrong name** - Create election, attempt delete with wrong name, verify election still exists and error flashed
3. **Cascade deletes all dependent data** - Create election with offices, candidates, codes, votes; delete election; verify all related rows removed from all tables
