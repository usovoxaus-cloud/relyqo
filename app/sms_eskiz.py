"""Eskiz domestic SMS transport. No credentials or message bodies are logged."""

import hashlib
import json
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .config import settings
from .password_recovery import NoMailRedirect

_lock = threading.Lock()
_token = ""
_credentials_digest = ""
_expires = 0.0


def configured():
    template = settings.eskiz_message_template
    # One short GSM-compatible SMS keeps the initial send budget predictable.
    return bool(
        settings.eskiz_email
        and settings.eskiz_password
        and re.fullmatch(r"[A-Za-z0-9]{1,11}", settings.eskiz_sender)
        and len(settings.sms_otp_secret) >= 32
        and template.count("{code}") == 1
        and re.fullmatch(
            r"[A-Za-z0-9 .,:'!?()\-]+", template.replace("{code}", "000000")
        )
        and len(template.replace("{code}", "000000")) <= 160
    )


def request(path, fields, token=None):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(
        "https://notify.eskiz.uz/api/" + path,
        data=urlencode(fields).encode("ascii"),
        headers=headers,
        method="POST",
    )
    with build_opener(NoMailRedirect()).open(req, timeout=10) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Invalid SMS provider response")
    return result


def access_token():
    global _token, _credentials_digest, _expires
    credentials_digest = hashlib.sha256(
        json.dumps([settings.eskiz_email, settings.eskiz_password]).encode()
    ).hexdigest()
    with _lock:
        if (
            _token
            and _credentials_digest == credentials_digest
            and time.monotonic() < _expires
        ):
            return _token
        result = request(
            "auth/login",
            {"email": settings.eskiz_email, "password": settings.eskiz_password},
        )
        token = (result.get("data") or {}).get("token")
        if not isinstance(token, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]{20,4096}", token
        ):
            raise ValueError("SMS provider authentication failed")
        _token, _credentials_digest = token, credentials_digest
        _expires = time.monotonic() + 86400
        return token


def send_code(phone, code):
    global _token
    if (
        not configured()
        or not re.fullmatch(r"\+998[0-9]{9}", phone)
        or not re.fullmatch(r"[0-9]{6}", code)
    ):
        raise ValueError("Invalid SMS configuration or recipient")
    token = access_token()
    try:
        result = request(
            "message/sms/send",
            {
                "mobile_phone": phone[1:],
                "message": settings.eskiz_message_template.replace("{code}", code),
                "from": settings.eskiz_sender,
            },
            token,
        )
    except HTTPError as error:
        if error.code == 401:
            with _lock:
                if _token == token:
                    _token = ""
        # Never automatically retry a send: a timeout may already have incurred a charge.
        raise
    if (
        result.get("status") != "waiting"
        or not isinstance(result.get("id"), str)
        or not result["id"]
    ):
        raise ValueError("SMS provider did not accept message")
