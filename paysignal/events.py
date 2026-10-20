"""Turn raw Stripe events into one flat record the business actually cares about."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone

# Currencies Stripe does not express in cents. https://docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
                "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}

# Stripe event type -> what it means for the shop owner
KINDS = {
    "payment_intent.succeeded": "payment",
    "payment_intent.payment_failed": "failed",
    "charge.refunded": "refund",
    "charge.dispute.created": "dispute",
}


@dataclass
class Record:
    event_id: str
    event_type: str
    kind: str              # payment | failed | refund | dispute
    occurred_at: str       # ISO 8601, UTC
    amount: float          # in major units (dollars), always positive
    currency: str
    customer: str          # email or name, whichever Stripe gave us
    description: str
    detail: str            # failure reason, refund note, dispute reason...
    stripe_object_id: str
    livemode: bool

    def as_dict(self):
        return asdict(self)


def to_major_units(amount_minor: int | None, currency: str) -> float:
    if amount_minor is None:
        return 0.0
    return float(amount_minor) if currency.lower() in ZERO_DECIMAL else amount_minor / 100


def format_money(amount: float, currency: str) -> str:
    cur = currency.upper()
    if currency.lower() in ZERO_DECIMAL:
        return f"{amount:,.0f} {cur}"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$"}.get(cur)
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {cur}"


def _customer_of(obj: dict) -> str:
    billing = obj.get("billing_details") or {}
    return (obj.get("receipt_email")
            or billing.get("email")
            or billing.get("name")
            or (obj.get("metadata") or {}).get("customer_name")
            or obj.get("customer")
            or "unknown customer")


def normalize(event: dict) -> Record | None:
    """Return a Record for event types we handle, or None to ignore the event."""
    kind = KINDS.get(event.get("type"))
    if kind is None:
        return None

    obj = event["data"]["object"]
    currency = obj.get("currency", "usd")
    occurred = datetime.fromtimestamp(event.get("created", 0), tz=timezone.utc).isoformat()

    if kind == "payment":
        amount = obj.get("amount_received") or obj.get("amount")
        detail = "Paid in full"
    elif kind == "failed":
        amount = obj.get("amount")
        err = obj.get("last_payment_error") or {}
        reason = err.get("decline_code") or err.get("code") or "unknown"
        detail = f"{err.get('message', 'Payment failed')} ({reason})"
    elif kind == "refund":
        amount = obj.get("amount_refunded")
        full = obj.get("amount_refunded") == obj.get("amount")
        detail = "Full refund" if full else "Partial refund"
    else:  # dispute
        amount = obj.get("amount")
        due = (obj.get("evidence_details") or {}).get("due_by")
        due_txt = datetime.fromtimestamp(due, tz=timezone.utc).strftime("%b %d") if due else "soon"
        detail = f"Reason: {obj.get('reason', 'unknown').replace('_', ' ')}. Evidence due {due_txt}"

    return Record(
        event_id=event["id"],
        event_type=event["type"],
        kind=kind,
        occurred_at=occurred,
        amount=to_major_units(amount, currency),
        currency=currency,
        customer=_customer_of(obj),
        description=obj.get("description") or "",
        detail=detail,
        stripe_object_id=obj.get("id", ""),
        livemode=bool(event.get("livemode")),
    )
