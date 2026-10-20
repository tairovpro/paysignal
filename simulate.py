"""Send realistic, correctly signed Stripe webhook events to a running PaySignal.

Works without a Stripe account, so the demo runs anywhere. With a Stripe
account, use the Stripe CLI instead (see README): the app treats both the same.

    python simulate.py story              # a day at the shop, one event every 2s
    python simulate.py payment            # a single scenario
    python simulate.py story --delay 0    # all at once
"""

import argparse
import json
import os
import random
import string
import sys
import time

import requests
from dotenv import load_dotenv

from paysignal.stripe_signature import build_header

load_dotenv()


def _id(prefix: str) -> str:
    return prefix + "_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _event(event_type: str, obj: dict) -> dict:
    return {
        "id": _id("evt"),
        "object": "event",
        "api_version": "2024-06-20",
        "created": int(time.time()),
        "livemode": False,
        "type": event_type,
        "data": {"object": obj},
    }


def payment(amount, email, description):
    return _event("payment_intent.succeeded", {
        "id": _id("pi"), "object": "payment_intent", "amount": amount, "amount_received": amount,
        "currency": "usd", "receipt_email": email, "description": description, "status": "succeeded"})


def failed(amount, email, description, decline_code="insufficient_funds",
           message="Your card has insufficient funds."):
    return _event("payment_intent.payment_failed", {
        "id": _id("pi"), "object": "payment_intent", "amount": amount, "amount_received": 0,
        "currency": "usd", "receipt_email": email, "description": description,
        "status": "requires_payment_method",
        "last_payment_error": {"type": "card_error", "code": "card_declined",
                               "decline_code": decline_code, "message": message}})


def refund(amount, refunded, email, description):
    return _event("charge.refunded", {
        "id": _id("ch"), "object": "charge", "amount": amount, "amount_refunded": refunded,
        "currency": "usd", "receipt_email": email, "description": description, "refunded": amount == refunded})


def dispute(amount, reason="product_not_received", description="Charge for 2 wheel straightenings"):
    return _event("charge.dispute.created", {
        "id": _id("dp"), "object": "dispute", "amount": amount, "currency": "usd", "reason": reason,
        "charge": _id("ch"), "status": "needs_response", "description": description,
        "metadata": {"customer_name": "Dan K. (walk-in)"},
        "evidence_details": {"due_by": int(time.time()) + 7 * 86400}})


def ignored():
    return _event("customer.created", {"id": _id("cus"), "object": "customer", "email": "new.customer@example.com"})


SCENARIOS = {
    "payment": lambda: payment(48000, "alicia.r@example.com", "4 wheels refinished, 2019 Honda Accord"),
    "fleet": lambda: payment(125000, "service@northhills-auto.example.com", "Dealer account: 6 curb-rash repairs"),
    "failed": lambda: failed(64000, "mike.t@example.com", "Powder coat, 4 wheels, gloss black"),
    "refund": lambda: refund(48000, 8000, "jen.o@example.com", "4 wheels refinished, 2021 RAV4"),
    "dispute": lambda: dispute(35000),
    "ignored": ignored,
}


def send(url: str, secret: str, event: dict, tamper: bool = False) -> None:
    body = json.dumps(event).encode()
    header = build_header(secret, body)
    if tamper:
        # Simulate an attacker editing the amount after signing.
        body = body.replace(b'"amount": ', b'"amount": 9', 1)
    resp = requests.post(url, data=body, timeout=10,
                         headers={"Content-Type": "application/json", "Stripe-Signature": header})
    print(f"{event['type']:<32} -> {resp.status_code} {resp.text.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=["story", "duplicate", "forged", *SCENARIOS])
    parser.add_argument("--url", default=os.environ.get("PAYSIGNAL_URL", "http://127.0.0.1:5050/webhooks/stripe"))
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between events in the story")
    args = parser.parse_args()

    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        sys.exit("Set STRIPE_WEBHOOK_SECRET (copy .env.example to .env).")

    try:
        if args.scenario == "story":
            first = SCENARIOS["payment"]()
            steps = [(first, False), (SCENARIOS["fleet"](), False), (SCENARIOS["ignored"](), False),
                     (SCENARIOS["failed"](), False), (SCENARIOS["refund"](), False),
                     (SCENARIOS["dispute"](), False),
                     (first, False),                       # Stripe retries the first event
                     (SCENARIOS["payment"](), True)]       # forged request
            for i, (event, tamper) in enumerate(steps):
                if i:
                    time.sleep(args.delay)
                send(args.url, secret, event, tamper)
        elif args.scenario == "duplicate":
            event = SCENARIOS["payment"]()
            send(args.url, secret, event)
            send(args.url, secret, event)
        elif args.scenario == "forged":
            send(args.url, secret, SCENARIOS["payment"](), tamper=True)
        else:
            send(args.url, secret, SCENARIOS[args.scenario]())
    except requests.ConnectionError:
        sys.exit(f"Could not reach {args.url}. Is the app running? (python run.py)")


if __name__ == "__main__":
    main()
