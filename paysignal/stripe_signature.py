"""Verify the Stripe-Signature header without the Stripe SDK.

Stripe signs every webhook as HMAC-SHA256(secret, f"{timestamp}.{raw_body}")
and sends it as:  Stripe-Signature: t=1700000000,v1=<hex>[,v1=<hex>...]
See https://docs.stripe.com/webhooks#verify-manually
"""

import hashlib
import hmac
import time

DEFAULT_TOLERANCE_SECONDS = 300  # Stripe's recommended replay window


class SignatureError(Exception):
    pass


def compute_signature(secret: str, timestamp: int, payload: bytes) -> str:
    signed = f"{timestamp}.".encode() + payload
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def build_header(secret: str, payload: bytes, timestamp: int | None = None) -> str:
    """Build a header the same way Stripe does (used by the simulator and tests)."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    return f"t={timestamp},v1={compute_signature(secret, timestamp, payload)}"


def verify(payload: bytes, header: str | None, secret: str,
           tolerance: int = DEFAULT_TOLERANCE_SECONDS, now: int | None = None) -> None:
    """Raise SignatureError unless the header is a valid, fresh Stripe signature."""
    if not header:
        raise SignatureError("missing Stripe-Signature header")

    timestamp = None
    candidates = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            candidates.append(value)

    if timestamp is None or not timestamp.isdigit():
        raise SignatureError("no timestamp in header")
    if not candidates:
        raise SignatureError("no v1 signature in header")

    expected = compute_signature(secret, int(timestamp), payload)
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise SignatureError("signature does not match payload")

    now = int(time.time()) if now is None else now
    if abs(now - int(timestamp)) > tolerance:
        raise SignatureError("timestamp outside tolerance (possible replay)")
