import base64
import hashlib
import hmac
import json
import secrets
import time
from .config import settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(branch_id: str, ttl: int = 10800) -> tuple[str, int]:
    exp = int(time.time()) + ttl
    payload = _b64(
        json.dumps(
            {"branch_id": branch_id, "exp": exp, "nonce": secrets.token_urlsafe(12)},
            separators=(",", ":"),
        ).encode()
    )
    sig = _b64(
        hmac.new(settings.qr_secret.encode(), payload.encode(), hashlib.sha256).digest()
    )
    return f"{payload}.{sig}", exp


def verify_signature(token: str) -> dict:
    payload, sig = token.split(".", 1)
    expected = _b64(
        hmac.new(settings.qr_secret.encode(), payload.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        raise ValueError("invalid signature")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    if data["exp"] < time.time():
        raise ValueError("expired token")
    return data
