import csv
import io
import json
import logging
import os
import re

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from . import notifiers
from .events import Record, format_money, normalize
from .store import Store
from .stripe_signature import SignatureError, verify

log = logging.getLogger("paysignal")


def mrkdwn(text: str) -> Markup:
    """Render the small subset of Slack mrkdwn we use, for the dashboard's Slack preview."""
    html = str(escape(text))
    html = re.sub(r"&lt;(https?://[^|]+?)\|(.+?)&gt;", r'<a href="\1" target="_blank" rel="noopener">\2</a>', html)
    html = re.sub(r"\*(.+?)\*", r"<b>\1</b>", html)
    html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)
    for code, char in {":white_check_mark:": "✅", ":warning:": "⚠️",
                       ":leftwards_arrow_with_hook:": "↩️", ":rotating_light:": "🚨"}.items():
        html = html.replace(code, char)
    return Markup(html.replace("\n", "<br>"))


def create_app(config: dict | None = None) -> Flask:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"))
    app.config.update(
        STRIPE_WEBHOOK_SECRET=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        SLACK_WEBHOOK_URL=os.environ.get("SLACK_WEBHOOK_URL") or None,
        SHEETS_WEBHOOK_URL=os.environ.get("SHEETS_WEBHOOK_URL") or None,
        DATABASE=os.environ.get("PAYSIGNAL_DB", os.path.join(root, "paysignal.db")),
        BUSINESS_NAME=os.environ.get("BUSINESS_NAME", "Three Rivers Wheel & Tire"),
        DEMO_TOOLS=os.environ.get("DEMO_TOOLS", "1") == "1",
    )
    app.config.update(config or {})
    if not app.config["STRIPE_WEBHOOK_SECRET"]:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is required (see .env.example)")

    store = Store(app.config["DATABASE"])
    app.extensions["store"] = store

    app.add_template_filter(mrkdwn)

    def deliver(record) -> None:
        """Send one record to every destination and log each attempt."""
        message = notifiers.slack_message(record)
        status, detail = notifiers.send_slack(app.config["SLACK_WEBHOOK_URL"], message)
        store.add_delivery(record.event_id, "slack", message, status, detail)

        row = notifiers.sheet_row(record)
        status, detail = notifiers.send_sheet(app.config["SHEETS_WEBHOOK_URL"], row)
        store.add_delivery(record.event_id, "sheets", row, status, detail)

    @app.post("/webhooks/stripe")
    def stripe_webhook():
        payload = request.get_data()  # raw bytes: the signature covers the exact body
        try:
            verify(payload, request.headers.get("Stripe-Signature"), app.config["STRIPE_WEBHOOK_SECRET"])
        except SignatureError as exc:
            log.warning("rejected webhook: %s", exc)
            store.log_request("rejected", None, str(exc))
            return jsonify(error=str(exc)), 400

        event = json.loads(payload)
        record = normalize(event)
        is_new = store.insert_event(event, record.as_dict() if record else None)

        if not is_new:
            # Stripe delivers at least once; a retry must never double-post to Slack.
            store.log_request("duplicate", event["id"], f"{event['type']} already processed, skipped")
            return jsonify(status="duplicate", event_id=event["id"]), 200
        if record is None:
            store.log_request("ignored", event["id"], f"{event['type']} is not a type we act on")
            return jsonify(status="ignored", event_type=event["type"]), 200

        # Downstream failures are recorded and retryable, so we still answer 200:
        # returning 5xx would make Stripe re-send an event we already stored.
        deliver(record)
        store.log_request("processed", event["id"], f"{event['type']} -> {record.kind}")
        return jsonify(status="processed", event_id=event["id"], kind=record.kind), 200

    @app.post("/deliveries/<int:delivery_id>/retry")
    def retry_delivery(delivery_id: int):
        d = store.get_delivery(delivery_id)
        if d is None:
            abort(404)
        payload = json.loads(d["payload_json"])
        send = notifiers.send_slack if d["channel"] == "slack" else notifiers.send_sheet
        url = app.config["SLACK_WEBHOOK_URL"] if d["channel"] == "slack" else app.config["SHEETS_WEBHOOK_URL"]
        status, detail = send(url, payload)
        store.update_delivery(delivery_id, status, detail)
        return redirect(url_for("dashboard"))

    @app.get("/")
    def dashboard():
        records = store.records()
        totals = {"payment": 0.0, "refund": 0.0, "dispute": 0.0, "failed": 0.0}
        counts = dict.fromkeys(totals, 0)
        for r in records:
            totals[r["kind"]] += r["amount"]
            counts[r["kind"]] += 1
        net = totals["payment"] - totals["refund"] - totals["dispute"]
        feed = store.feed()
        return render_template(
            "dashboard.html",
            business=app.config["BUSINESS_NAME"],
            feed=feed,
            counts=counts,
            money=lambda v: format_money(v, "usd"),
            totals=totals,
            net=net,
            slack_live=bool(app.config["SLACK_WEBHOOK_URL"]),
            sheets_live=bool(app.config["SHEETS_WEBHOOK_URL"]),
            demo_tools=app.config["DEMO_TOOLS"],
            request_log=store.request_log(),
            version=store.version(),
        )

    @app.get("/api/version")
    def api_version():
        return {"version": store.version()}

    @app.get("/ledger.csv")
    def ledger_csv():
        buf = io.StringIO()
        rows = [notifiers.sheet_row(Record(**r)) for r in store.records()]
        fields = list(rows[0].keys()) if rows else ["date", "type", "customer", "amount"]
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=paysignal-ledger.csv"})

    @app.post("/demo/reset")
    def demo_reset():
        if not app.config["DEMO_TOOLS"]:
            abort(404)
        store.reset()
        return redirect(url_for("dashboard"))

    @app.get("/health")
    def health():
        return {"ok": True}

    return app

