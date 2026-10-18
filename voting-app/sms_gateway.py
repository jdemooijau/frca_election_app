"""SMSGlobal REST client: send (optionally scheduled) SMS and read the balance.

SMSGlobal signs each request with a MAC header: an HMAC-SHA256 over the
timestamp, nonce, method, path, host and port, keyed with the API secret.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

import requests

HOST = "api.smsglobal.com"
PORT = 443
SMS_PATH = "/v2/sms"
BALANCE_PATH = "/v2/user/credit-balance"

# Errors that mean the account itself cannot send; no point trying the
# remaining recipients.
ACCOUNT_ERRORS = (401, 402, 403, 429)


def to_international(mobile):
    """Return an Australian mobile as 614xxxxxxxx, or None if it is not one.

    Accepts "0400 000 001", "400000001" (leading 0 lost in a spreadsheet)
    and "+61 400 000 001".
    """
    digits = "".join(ch for ch in (mobile or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("04"):
        return "61" + digits[1:]
    if len(digits) == 9 and digits.startswith("4"):
        return "61" + digits
    if len(digits) == 11 and digits.startswith("614"):
        return digits
    return None


def mac_header(key, secret, method, path, ts=None, nonce=None):
    ts = ts or str(int(time.time()))
    nonce = nonce or secrets.token_hex(16)
    base = f"{ts}\n{nonce}\n{method}\n{path}\n{HOST}\n{PORT}\n\n"
    digest = hmac.new(secret.encode(), base.encode(), hashlib.sha256).digest()
    mac = base64.b64encode(digest).decode()
    return f'MAC id="{key}", ts="{ts}", nonce="{nonce}", mac="{mac}"'


def _request(key, secret, method, path, body=None, timeout=20):
    """Return (http_status, parsed_json_or_text). Network errors give status 0."""
    headers = {
        "Authorization": mac_header(key, secret, method, path),
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = requests.request(
            method, f"https://{HOST}{path}",
            data=json.dumps(body) if body is not None else None,
            headers=headers, timeout=timeout,
        )
    except requests.RequestException as err:
        return 0, str(err)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


def credit_balance(key, secret):
    """Return e.g. "14.60 AUD", or None when it cannot be read."""
    status, data = _request(key, secret, "GET", BALANCE_PATH, timeout=5)
    if status != 200 or not isinstance(data, dict) or "balance" not in data:
        return None
    return f"{float(data['balance']):.2f} {data.get('currency', '')}".strip()


def send_sms(key, secret, destination, message, scheduled=None, origin=None):
    """Send one SMS. `scheduled` is "YYYY-MM-DD HH:MM:SS +HHMM" or None.

    Returns (ok, http_status, outgoing_id_or_error_text).
    """
    body = {"destination": destination, "message": message}
    if scheduled:
        body["scheduledDateTime"] = scheduled
    if origin:
        body["origin"] = origin
    status, data = _request(key, secret, "POST", SMS_PATH, body)
    if status == 200 and isinstance(data, dict) and data.get("messages"):
        return True, status, str(data["messages"][0].get("outgoing_id", ""))
    error = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    return False, status, error
