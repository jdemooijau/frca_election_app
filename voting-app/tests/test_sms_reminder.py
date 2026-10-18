"""Tests for the SMS reminder step. SMSGlobal is faked; nothing is sent."""

import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db, compute_sidebar_state
import app as app_module
import sms_gateway

CSV_HEADER = '"Last name","First name","Age","Full address","Email","Mobile phone","Membership status"\n'


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client
    app_module.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def fake_smsglobal(monkeypatch):
    """Replace the HTTP layer. Records every call; responses are scriptable."""
    calls = []
    state = {"sms_status": 200}

    def fake_request(key, secret, method, path, body=None, timeout=20):
        calls.append({"method": method, "path": path, "body": body})
        if path == sms_gateway.BALANCE_PATH:
            return 200, {"balance": 14.6, "currency": "AUD"}
        if state["sms_status"] != 200:
            return state["sms_status"], {"errors": "nope"}
        return 200, {"messages": [{"outgoing_id": 1000 + len(calls), "status": "Pending"}]}

    monkeypatch.setattr(sms_gateway, "_request", fake_request)
    return calls, state


@pytest.fixture
def election(client):
    client.post("/admin/login", data={"password": "admin"})
    client.post("/admin/election/new", data={
        "name": "E", "max_rounds": "2", "election_date": "18 October 2026",
    })
    rows = (
        '"Aa","One","","","","0400 000 001","Member"\n'
        '"Bb","Two","","","","400000002","Member"\n'
        '"Cc","Three","","","","","Member"\n'
        '"Dd","Four","","","","0400000001","Member"\n'
        '"Ee","Five","","","","07 4600 0000","Member"\n'
    )
    client.post("/admin/members", data={
        "csv_file": (io.BytesIO((CSV_HEADER + rows).encode()), "members.csv"),
    }, content_type="multipart/form-data")
    with app.app_context():
        # Past the first-run wizard, so Settings saves without a new password.
        app_module.set_setting("setup_complete", "1")
    return client


def configure(client, secret="s3cret"):
    client.post("/admin/setup", data={
        "congregation_name": "FRC", "smsglobal_key": "k1", "smsglobal_secret": secret,
    })


def future_time(days=2):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def sms_calls(calls):
    return [c for c in calls if c["path"] == sms_gateway.SMS_PATH]


def test_to_international_handles_stored_forms():
    assert sms_gateway.to_international("0400 000 001") == "61400000001"
    assert sms_gateway.to_international("400000002") == "61400000002"
    assert sms_gateway.to_international("+61 400 000 001") == "61400000001"
    assert sms_gateway.to_international("07 4600 0000") is None
    assert sms_gateway.to_international("") is None


def test_mac_header_signs_the_documented_base_string():
    header = sms_gateway.mac_header("key", "secret", "POST", "/v2/sms", ts="1325376000", nonce="n")
    assert header.startswith('MAC id="key", ts="1325376000", nonce="n", mac="')
    import base64, hashlib, hmac
    base = "1325376000\nn\nPOST\n/v2/sms\napi.smsglobal.com\n443\n\n"
    expected = base64.b64encode(hmac.new(b"secret", base.encode(), hashlib.sha256).digest()).decode()
    assert header.endswith(f'mac="{expected}"')


def test_blank_secret_keeps_saved_secret(election):
    configure(election)
    configure(election, secret="")
    with app.app_context():
        assert app_module.get_setting("smsglobal_secret") == "s3cret"
        assert app_module.get_setting("smsglobal_key") == "k1"


def test_step_defaults_to_message_and_day_before_at_six(election, fake_smsglobal):
    configure(election)
    body = election.get("/admin/election/1/step/sms").get_data(as_text=True)
    assert "Office Bearer Election this Sunday" in body
    assert 'value="2026-10-17T18:00"' in body
    assert "14.60 AUD" in body
    # Two usable numbers (one is a duplicate), a landline and a blank are skipped.
    assert "<strong>2</strong> members" in body
    assert "same number as" in body
    assert "no mobile" in body


def test_step_without_settings_prompts_for_them(election, fake_smsglobal):
    body = election.get("/admin/election/1/step/sms").get_data(as_text=True)
    assert "SMSGlobal not set up" in body
    calls, _ = fake_smsglobal
    assert calls == []


def test_schedule_sends_one_per_number_with_local_offset(election, fake_smsglobal):
    configure(election)
    calls, _ = fake_smsglobal
    send_at = future_time()
    rv = election.post("/admin/election/1/sms/schedule", data={
        "message": "Hello", "send_at": send_at,
    }, follow_redirects=True)
    assert "Scheduled 2 messages" in rv.get_data(as_text=True)
    sent = sms_calls(calls)
    assert sorted(c["body"]["destination"] for c in sent) == ["61400000001", "61400000002"]
    expected = datetime.strptime(send_at, "%Y-%m-%dT%H:%M").astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    assert all(c["body"]["scheduledDateTime"] == expected for c in sent)
    assert all("origin" not in c["body"] for c in sent)
    with app.app_context():
        row = get_db().execute("SELECT * FROM sms_sends").fetchone()
        assert (row["recipients"], row["accepted"]) == (2, 2)
        assert len(json.loads(row["details"])) == 2
        state = compute_sidebar_state(1)
    setup = next(g for g in state["groups"] if g["label"] == "Setup")
    assert {i["slug"]: i["state"] for i in setup["entries"]}["sms"] == "done"


def test_second_schedule_needs_confirmation(election, fake_smsglobal):
    configure(election)
    calls, _ = fake_smsglobal
    election.post("/admin/election/1/sms/schedule", data={"message": "Hi", "send_at": future_time()})
    rv = election.post("/admin/election/1/sms/schedule", data={
        "message": "Hi", "send_at": future_time(),
    }, follow_redirects=True)
    assert "already scheduled" in rv.get_data(as_text=True)
    assert len(sms_calls(calls)) == 2
    election.post("/admin/election/1/sms/schedule", data={
        "message": "Hi", "send_at": future_time(), "confirm_resend": "1",
    })
    assert len(sms_calls(calls)) == 4


def test_past_time_is_rejected(election, fake_smsglobal):
    configure(election)
    calls, _ = fake_smsglobal
    rv = election.post("/admin/election/1/sms/schedule", data={
        "message": "Hi", "send_at": future_time(days=-1),
    }, follow_redirects=True)
    assert "must be in the future" in rv.get_data(as_text=True)
    assert sms_calls(calls) == []


def test_first_failure_stops_the_run(election, fake_smsglobal):
    configure(election)
    calls, state = fake_smsglobal
    state["sms_status"] = 400
    rv = election.post("/admin/election/1/sms/schedule", data={
        "message": "Hi", "send_at": future_time(),
    }, follow_redirects=True)
    body = rv.get_data(as_text=True)
    assert "Scheduled 0 of 2" in body
    assert "1 not tried" in body
    assert len(sms_calls(calls)) == 1
    with app.app_context():
        state_ = compute_sidebar_state(1)
    setup = next(g for g in state_["groups"] if g["label"] == "Setup")
    assert {i["slug"]: i["state"] for i in setup["entries"]}["sms"] != "done"


def test_sms_step_is_not_the_landing_step(election):
    with app.app_context():
        state = compute_sidebar_state(1)
    assert state["current_step"] == "offices"
