# Delete Election Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Delete Election" button to the admin dashboard with GitHub-style name-confirmation, cascading all dependent data removal.

**Architecture:** New POST route deletes election and all dependents in FK-safe order within a single transaction. Dashboard template gets an inline JS-revealed confirmation form per election card. Three test cases cover success, rejection, and cascade.

**Tech Stack:** Flask, SQLite3, Jinja2, vanilla JavaScript

---

### Task 1: Write failing tests for delete election

**Files:**
- Modify: `voting-app/tests/test_app.py` (append after line 652)

- [ ] **Step 1: Write the three failing tests**

Append this test class to the end of `voting-app/tests/test_app.py`:

```python


# ---------------------------------------------------------------------------
# Delete election tests
# ---------------------------------------------------------------------------

class TestDeleteElection:
    def test_delete_election_with_correct_name(self, admin_client):
        """Deleting an election with the correct name should remove it."""
        admin_client.post("/admin/election/new", data={
            "name": "To Be Deleted",
            "max_rounds": "2"
        })
        # Verify election exists
        with app.app_context():
            db = get_db()
            assert db.execute("SELECT COUNT(*) FROM elections WHERE name = 'To Be Deleted'").fetchone()[0] == 1

        resp = admin_client.post("/admin/election/1/delete", data={
            "confirm_name": "To Be Deleted"
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"deleted" in resp.data.lower()

        with app.app_context():
            db = get_db()
            assert db.execute("SELECT COUNT(*) FROM elections WHERE name = 'To Be Deleted'").fetchone()[0] == 0

    def test_delete_election_wrong_name_rejected(self, admin_client):
        """Deleting with the wrong name should be rejected."""
        admin_client.post("/admin/election/new", data={
            "name": "Keep This",
            "max_rounds": "2"
        })

        resp = admin_client.post("/admin/election/1/delete", data={
            "confirm_name": "Wrong Name"
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"does not match" in resp.data.lower()

        with app.app_context():
            db = get_db()
            assert db.execute("SELECT COUNT(*) FROM elections WHERE name = 'Keep This'").fetchone()[0] == 1

    def test_delete_election_cascades_all_data(self, election_with_codes):
        """Deleting should remove all dependent data (offices, candidates, codes, votes)."""
        client = election_with_codes

        # Cast a vote so we have data in the votes table
        client.post("/admin/election/1/manage", data={"action": "toggle_voting"})
        client.post("/admin/election/1/manage", data={
            "action": "set_participants",
            "participants": "10",
            "paper_ballot_count": "0"
        })

        # Get a code and vote
        with app.app_context():
            db = get_db()
            code_row = db.execute("SELECT code_hash FROM codes WHERE election_id = 1 LIMIT 1").fetchone()
            # We need the actual code, not the hash — generate a fresh one for testing
            candidates = db.execute(
                "SELECT c.id FROM candidates c JOIN offices o ON c.office_id = o.id WHERE o.election_id = 1"
            ).fetchall()
            # Insert a vote directly for test purposes
            db.execute(
                "INSERT INTO votes (election_id, candidate_id, round_number, source) VALUES (1, ?, 1, 'digital')",
                (candidates[0]["id"],)
            )
            # Insert a paper vote
            db.execute(
                "INSERT INTO paper_votes (election_id, candidate_id, round_number, count) VALUES (1, ?, 1, 3)",
                (candidates[0]["id"],)
            )
            # Insert a postal vote
            db.execute(
                "INSERT INTO postal_votes (election_id, candidate_id, count) VALUES (1, ?, 2)",
                (candidates[0]["id"],)
            )
            db.commit()

        # Verify data exists before delete
        with app.app_context():
            db = get_db()
            assert db.execute("SELECT COUNT(*) FROM offices WHERE election_id = 1").fetchone()[0] > 0
            assert db.execute("SELECT COUNT(*) FROM candidates WHERE office_id IN (SELECT id FROM offices WHERE election_id = 1)").fetchone()[0] > 0
            assert db.execute("SELECT COUNT(*) FROM codes WHERE election_id = 1").fetchone()[0] > 0
            assert db.execute("SELECT COUNT(*) FROM votes WHERE election_id = 1").fetchone()[0] > 0
            assert db.execute("SELECT COUNT(*) FROM paper_votes WHERE election_id = 1").fetchone()[0] > 0
            assert db.execute("SELECT COUNT(*) FROM postal_votes WHERE election_id = 1").fetchone()[0] > 0

        # Delete the election
        resp = client.post("/admin/election/1/delete", data={
            "confirm_name": "Test Election"
        }, follow_redirects=True)
        assert resp.status_code == 200

        # Verify ALL dependent data is gone
        with app.app_context():
            db = get_db()
            assert db.execute("SELECT COUNT(*) FROM elections WHERE id = 1").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM offices WHERE election_id = 1").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM candidates WHERE office_id IN (SELECT id FROM offices WHERE election_id = 1)").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM codes WHERE election_id = 1").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM votes WHERE election_id = 1").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM paper_votes WHERE election_id = 1").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM postal_votes WHERE election_id = 1").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM round_counts WHERE election_id = 1").fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd voting-app && python -m pytest tests/test_app.py::TestDeleteElection -v`
Expected: All 3 tests FAIL (404 on the delete route since it doesn't exist yet)

- [ ] **Step 3: Commit failing tests**

```bash
git add voting-app/tests/test_app.py
git commit -m "test: add failing tests for delete election feature"
```

---

### Task 2: Implement the delete election route

**Files:**
- Modify: `voting-app/app.py` — insert new route after the `admin_hard_reset` function (after line 1302)

- [ ] **Step 1: Add the delete election route**

Insert this code after line 1302 in `app.py` (after the `admin_hard_reset` function, before the `# Member import routes` comment):

```python


@app.route("/admin/election/<int:election_id>/delete", methods=["POST"])
@admin_required
def admin_election_delete(election_id):
    """Delete an election and all its dependent data."""
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    confirm_name = request.form.get("confirm_name", "").strip()
    if confirm_name != election["name"]:
        flash("Deletion cancelled — election name does not match.", "error")
        return redirect(url_for("admin_dashboard"))

    # Cascade delete in FK-safe order
    db.execute("DELETE FROM votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM paper_votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM postal_votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM codes WHERE election_id = ?", (election_id,))
    db.execute(
        "DELETE FROM candidates WHERE office_id IN (SELECT id FROM offices WHERE election_id = ?)",
        (election_id,)
    )
    db.execute("DELETE FROM offices WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM round_counts WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM elections WHERE id = ?", (election_id,))
    db.commit()

    flash(f"Election \"{election['name']}\" deleted.", "success")
    return redirect(url_for("admin_dashboard"))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd voting-app && python -m pytest tests/test_app.py::TestDeleteElection -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add voting-app/app.py
git commit -m "feat: add delete election route with cascade delete"
```

---

### Task 3: Add the delete button and confirmation form to the dashboard

**Files:**
- Modify: `voting-app/templates/admin/dashboard.html` — add form inside the election card loop (after line 38, before the closing `</div>` of the card)

- [ ] **Step 1: Add the delete UI to each election card**

In `voting-app/templates/admin/dashboard.html`, insert the following after line 38 (the `</div>` closing the Dual-Sided Ballots btn-row) and before line 39 (the `</div>` closing the card):

```html
        <div style="margin-top: 8px;">
            <button type="button" class="btn btn-danger btn-small" onclick="toggleDeleteForm({{ election.id }})">Delete</button>
        </div>
        <div id="delete-form-{{ election.id }}" style="display: none; margin-top: 12px; padding: 12px; border: 1px solid var(--red); border-radius: 4px;">
            <form method="POST" action="{{ url_for('admin_election_delete', election_id=election.id) }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <p style="font-size: 14px; margin-bottom: 8px;">
                    This will permanently delete <strong>{{ election.name }}</strong> and all its votes, codes, offices, and candidates. <strong>This cannot be undone.</strong>
                </p>
                <div class="form-group">
                    <label for="confirm_name_{{ election.id }}">Type <strong>{{ election.name }}</strong> to confirm</label>
                    <input type="text" id="confirm_name_{{ election.id }}" name="confirm_name"
                           autocomplete="off" placeholder="{{ election.name }}" style="max-width: 300px;">
                </div>
                <button type="submit" class="btn btn-danger btn-small">Confirm Delete</button>
                <button type="button" class="btn btn-outline btn-small" onclick="toggleDeleteForm({{ election.id }})" style="margin-left: 4px;">Cancel</button>
            </form>
        </div>
```

- [ ] **Step 2: Add the JavaScript toggle function**

In the same file, add a `{% block scripts %}` section at the end (after `{% endblock %}` on line 138):

```html
{% block scripts %}
<script>
function toggleDeleteForm(electionId) {
    var form = document.getElementById('delete-form-' + electionId);
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
}
</script>
{% endblock %}
```

Note: If the base template (`base.html`) does not have a `{% block scripts %}` block, place the `<script>` tag inline just before `{% endblock %}` (the content endblock) instead.

- [ ] **Step 3: Verify the base template supports a scripts block**

Check `voting-app/templates/base.html` for `{% block scripts %}`. If it doesn't exist, use the inline approach: place the `<script>` tag inside the `{% block content %}` block at the very end, just before `{% endblock %}`.

- [ ] **Step 4: Run all tests to verify nothing is broken**

Run: `cd voting-app && python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add voting-app/templates/admin/dashboard.html
git commit -m "feat: add delete election button with name confirmation to dashboard"
```
