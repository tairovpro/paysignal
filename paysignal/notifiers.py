"""Destinations: Slack (incoming webhook) and Google Sheets (Apps Script web app).

Each notifier returns (status, detail):
  "sent"     delivered
  "preview"  no URL configured, so the message was rendered for the dashboard only
  "failed"   the destination rejected it or was unreachable (can be retried)
"""

import json

import requests

from .events import Record, format_money

TIMEOUT_SECONDS = 5

STYLE = {
    "payment": (":white_check_mark:", "Payment received"),
    "failed":  (":warning:", "Payment failed"),
    "refund":  (":leftwards_arrow_with_hook:", "Refund issued"),
    "dispute": (":rotating_light:", "Chargeback opened"),
}

NEXT_STEP = {
    "failed":  "Reach out to the customer for another card before the job is released.",
    "dispute": "Upload the signed work order and photos in the Stripe dashboard before the deadline.",
}


def slack_message(rec: Record, dashboard_base: str = "https://dashboard.stripe.com") -> dict:
    emoji, title = STYLE[rec.kind]
    money = format_money(rec.amount, rec.currency)
    mode = "" if rec.livemode else "test/"
    link = f"{dashboard_base}/{mode}payments/{rec.stripe_object_id}" if rec.kind in ("payment", "failed") \
        else f"{dashboard_base}/{mode}search?query={rec.stripe_object_id}"

    fields = [
        {"type": "mrkdwn", "text": f"*Amount*\n{money}"},
        {"type": "mrkdwn", "text": f"*Customer*\n{rec.customer}"},
    ]
    if rec.description:
        fields.append({"type": "mrkdwn", "text": f"*For*\n{rec.description}"})
    fields.append({"type": "mrkdwn", "text": f"*Details*\n{rec.detail}"})

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{title}: {money}"}},
        {"type": "section", "fields": fields},
    ]
    if rec.kind in NEXT_STEP:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": f"*Next step:* {NEXT_STEP[rec.kind]}"}})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": f"<{link}|Open in Stripe> · `{rec.event_type}` · {rec.event_id}"}]})

    # `text` is the fallback shown in push notifications
    return {"text": f"{emoji} {title}: {money} from {rec.customer}", "blocks": blocks}


def sheet_row(rec: Record) -> dict:
    sign = -1 if rec.kind in ("refund", "dispute") else 1
    counted = 0 if rec.kind == "failed" else sign * rec.amount
    return {
        "date": rec.occurred_at,
        "type": rec.kind,
        "customer": rec.customer,
        "description": rec.description,
        "amount": rec.amount,
        "net_effect": counted,
        "currency": rec.currency.upper(),
        "detail": rec.detail,
        "stripe_id": rec.stripe_object_id,
        "event_id": rec.event_id,
    }


def _post(url: str, body: dict) -> tuple[str, str]:
    try:
        resp = requests.post(url, data=json.dumps(body),
                             headers={"Content-Type": "application/json"}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return "failed", f"network error: {exc.__class__.__name__}"
    if 200 <= resp.status_code < 300:
        return "sent", f"HTTP {resp.status_code}"
    return "failed", f"HTTP {resp.status_code}: {resp.text[:200]}"


def send_slack(url: str | None, message: dict) -> tuple[str, str]:
    if not url:
        return "preview", "SLACK_WEBHOOK_URL not set; rendered on dashboard only"
    return _post(url, message)


def send_sheet(url: str | None, row: dict) -> tuple[str, str]:
    if not url:
        return "preview", "SHEETS_WEBHOOK_URL not set; row kept in local ledger"
    return _post(url, row)
