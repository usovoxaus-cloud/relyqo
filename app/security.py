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


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32
    )
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(
            digest_text + "=" * (-len(digest_text) % 4)
        )
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


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
