# PaySignal: 3-minute demo script

Same structure as the RentWise video: **the customer's problem → the product live → why it's safe to run → what it changes for them.**
Practice it twice before recording. Don't read it word for word; hit the beats.

## Before you hit record (5 min)

1. Terminal 1:
   ```bash
   cd ~/Desktop/paysignal && source .venv/bin/activate
   python run.py
   ```
2. Open http://127.0.0.1:5050 in Chrome and click **Reset demo data** so it starts empty. Zoom the browser to 110–125% so text reads on video.
3. Terminal 2 (same folder, venv activated): type `python simulate.py story` but **don't press Enter yet**.
4. Lay out the screen: browser on the left ~2/3, terminal 2 on the right ~1/3.
5. Optional but impressive: if you set up a real Slack webhook (README, Option B), have Slack open on `#payments` too. The dashboard's Slack panel then says "posted to Slack".
6. Recorder: Loom or QuickTime (File → New Screen Recording), mic on, camera bubble optional.

## The script

### 0:00–0:30 | The problem (empty dashboard on screen)

> "Hi, I'm Mukhammed. By day I sell a wheel-repair service to dealerships and tire shops, and when I talk to those shop owners, the same problem keeps coming up: they take card payments through Stripe, but nobody is watching Stripe. A card fails and the car leaves unpaid. A chargeback email sits in the owner's inbox until the deadline passes. And at month end, someone re-types every payment into a spreadsheet.
> They already work in Slack and Google Sheets all day. So instead of asking them to log into one more tool, I built PaySignal, which brings the money events to where they already are."

### 0:30–1:30 | Live walkthrough (press Enter on `python simulate.py story`)

Events arrive one every 2 seconds. Narrate as they land:

> "These are real Stripe webhook payloads, signed the way Stripe signs them."

- **First payment:** "A walk-in pays $480 for four refinished wheels. Here's the message the front desk gets in Slack: amount, customer, the job, and a link straight to the payment in Stripe."
- **Dealer payment:** "A dealership pays its monthly invoice. Same thing, and it's already a row in the ledger."
- **Ignored event:** "Stripe sends lots of events the shop doesn't care about, like a new customer record. We store those for audit but keep them out of Slack, so the channel stays useful."
- **Failed card:** "Now the important one: a $640 card is declined for insufficient funds. The alert says *why*, and gives the next step: get another card before you release the wheels. That's the money this shop was losing."
- **Refund:** "An $80 partial refund comes off net revenue."
- **Chargeback:** "And a chargeback: the reason, the evidence deadline, and what to upload. That deadline used to get missed."

Point at the KPI cards: "Up top the owner sees net collected, and what needs follow-up: $990 at risk right now."

### 1:30–2:20 | Why it's safe to run (point to the Webhook request log)

> "The last two events are the ones a technical buyer asks about."

- **Duplicate:** "Stripe guarantees *at least once* delivery, so it sometimes sends the same event twice. Here it re-sent the first payment. PaySignal recognized the event ID and skipped it, so there's no double alert and no double row in the books."
- **Rejected:** "This one was forged: someone changed the amount after the request was signed. Every request is verified with an HMAC signature and a five-minute timestamp window, so it was rejected with a 400."
- "And if Slack or Google Sheets is down, the event is already saved. It shows as failed here with a retry button. Nothing is lost." *(Optional: point to the test that proves it, or skip.)*

### 2:20–2:50 | What it changes + how it's built

Click **Download ledger (CSV)** and open it.

> "This is what the bookkeeper gets: every payment, refund and chargeback with its net effect, already in a spreadsheet. With the Google Sheets connection on, it builds itself live.
> Under the hood it's a small Python and Flask service: Stripe webhooks in, Slack Block Kit and a Google Apps Script out, SQLite for the event log, and 19 tests. To go live, the shop adds one webhook URL in Stripe and one in Slack. Setup takes about 15 minutes."

### 2:50–3:00 | Close

> "So: the card that would have walked out the door gets caught, the chargeback gets answered on time, and month end takes minutes instead of hours. The code and setup guide are on my GitHub at tairovpro/paysignal. Thanks for watching."

## After recording

- Upload to LinkedIn (native video does better than a YouTube link). Suggested post:
  > Built a small integration for the kind of shops I sell to: Stripe payment events → Slack alerts + a self-building Google Sheets ledger. Failed cards and chargebacks come with a next step, Stripe's duplicate deliveries are deduplicated, and every webhook is signature-verified. 3-minute demo below. Code: github.com/tairovpro/paysignal
- Also upload it to YouTube (unlisted is fine) and paste the link into the README where it says "Demo video: _coming soon_".
- Tell me the link and I'll update the README and add the project to your resume.
