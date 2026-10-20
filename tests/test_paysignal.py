import json

import pytest

import simulate
from paysignal import notifiers
from paysignal.app import create_app
from paysignal.events import normalize
from paysignal.stripe_signature import SignatureError, build_header, verify

SECRET = "whsec_test_secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    sent = []

    def fake_post(url, body):
        sent.append((url, body))
        return ("failed", "HTTP 500: down") if "broken" in url else ("sent", "HTTP 200")

    monkeypatch.setattr(notifiers, "_post", fake_post)
    app = create_app({"STRIPE_WEBHOOK_SECRET": SECRET, "DATABASE": str(tmp_path / "t.db"),
                      "SLACK_WEBHOOK_URL": "https://hooks.slack.test/ok", "SHEETS_WEBHOOK_URL": None})
    c = app.test_client()
    c.sent = sent
    c.app = app
    return c


def post(client, event, secret=SECRET, body=None):
    body = body or json.dumps(event).encode()
    return client.post("/webhooks/stripe", data=body,
                       headers={"Stripe-Signature": build_header(secret, json.dumps(event).encode())})


# --- signature -------------------------------------------------------------

def test_valid_signature_passes():
    body = b'{"id":"evt_1"}'
    verify(body, build_header(SECRET, body), SECRET)


@pytest.mark.parametrize("header", [None, "", "v1=abc", "t=123", "t=abc,v1=abc"])
def test_malformed_headers_rejected(header):
    with pytest.raises(SignatureError):
        verify(b"{}", header, SECRET)


def test_wrong_secret_rejected():
    body = b"{}"
    with pytest.raises(SignatureError):
        verify(body, build_header("whsec_other", body), SECRET)


def test_old_timestamp_rejected():
    body = b"{}"
    with pytest.raises(SignatureError, match="tolerance"):
        verify(body, build_header(SECRET, body, timestamp=1_000), SECRET)


# --- normalization -----------------------------------------------------------

def test_payment_normalized_to_dollars():
    rec = normalize(simulate.SCENARIOS["payment"]())
    assert rec.kind == "payment" and rec.amount == 480.0 and rec.customer == "alicia.r@example.com"


def test_failed_payment_carries_decline_reason():
    rec = normalize(simulate.SCENARIOS["failed"]())
    assert rec.kind == "failed" and "insufficient_funds" in rec.detail


def test_partial_refund():
    rec = normalize(simulate.SCENARIOS["refund"]())
    assert rec.amount == 80.0 and rec.detail == "Partial refund"


def test_unhandled_type_is_ignored():
    assert normalize(simulate.ignored()) is None


def test_zero_decimal_currency():
    event = simulate.payment(5000, "a@example.com", "x")
    event["data"]["object"]["currency"] = "jpy"
    assert normalize(event).amount == 5000


# --- webhook endpoint --------------------------------------------------------

def test_payment_posts_to_slack_once(client):
    event = simulate.SCENARIOS["payment"]()
    r = post(client, event)
    assert r.status_code == 200 and r.json["status"] == "processed"
    assert len(client.sent) == 1
    assert "Payment received: $480.00" in client.sent[0][1]["blocks"][0]["text"]["text"]


def test_stripe_retry_is_not_double_posted(client):
    event = simulate.SCENARIOS["payment"]()
    post(client, event)
    r = post(client, event)
    assert r.json["status"] == "duplicate"
    assert len(client.sent) == 1


def test_tampered_body_rejected(client):
    event = simulate.SCENARIOS["payment"]()
    tampered = json.dumps(event).replace('"amount": 48000', '"amount": 1').encode()
    r = post(client, event, body=tampered)
    assert r.status_code == 400 and client.sent == []


def test_ignored_event_acknowledged(client):
    r = post(client, simulate.ignored())
    assert r.status_code == 200 and r.json["status"] == "ignored" and client.sent == []


def test_failed_delivery_still_acks_and_can_be_retried(client):
    client.app.config["SLACK_WEBHOOK_URL"] = "https://hooks.slack.test/broken"
    r = post(client, simulate.SCENARIOS["dispute"]())
    assert r.status_code == 200  # Stripe should not retry; we own the retry
    feed = client.app.extensions["store"].feed()
    slack = next(d for d in feed[0]["deliveries"] if d["channel"] == "slack")
    assert slack["status"] == "failed"

    client.app.config["SLACK_WEBHOOK_URL"] = "https://hooks.slack.test/ok"
    client.post(f"/deliveries/{slack['id']}/retry")
    slack = next(d for d in client.app.extensions["store"].feed()[0]["deliveries"] if d["channel"] == "slack")
    assert slack["status"] == "sent" and slack["attempts"] == 2


def test_dashboard_and_ledger_render(client):
    for name in ("payment", "failed", "refund", "dispute"):
        post(client, simulate.SCENARIOS[name]())
    page = client.get("/").get_data(as_text=True)
    assert "Net collected" in page and "$50.00" in page  # 480 - 80 refund - 350 dispute
    csv_text = client.get("/ledger.csv").get_data(as_text=True)
    assert csv_text.count("\n") == 5  # header + 4 rows
