"""Member lists sort by surname, then first name, ignoring case."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db, _sms_recipients

# Surname order: Aalders, Bos, Smit, van Dijk ('v' sorts last, case-insensitive).
# By first name the order would be Anna, Peter, Yvonne, Zacharias.
MEMBERS = [
    ("Smit", "Anna", "0412 000 001"),
    ("van Dijk", "Gary", "0412 000 002"),
    ("Bos", "Zacharias", "0412 000 003"),
    ("Aalders", "Peter", "0412 000 004"),
]
SURNAME_ORDER = ["Peter Aalders", "Zacharias Bos", "Anna Smit", "Gary van Dijk"]


@pytest.fixture
def admin_client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    import app as app_module
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with app.test_client() as client:
        with app.app_context():
            init_db()
            db = get_db()
            db.executemany(
                "INSERT INTO members (last_name, first_name, mobile_phone) VALUES (?, ?, ?)",
                MEMBERS)
            db.commit()
        client.post("/admin/login", data={"password": "admin"})
        yield client
    app_module.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)


def _positions(body, names):
    return [body.index(name) for name in names]


def test_members_page_sorts_by_surname(admin_client):
    body = admin_client.get("/admin/members").get_data(as_text=True)
    surnames = ["Aalders", "Bos", "Smit", "van Dijk"]
    positions = _positions(body, surnames)
    assert positions == sorted(positions)


def test_sms_recipients_sort_by_surname(admin_client):
    with app.app_context():
        recipients, _ = _sms_recipients(get_db())
    names = [r["name"] for r in recipients]
    assert names == SURNAME_ORDER
