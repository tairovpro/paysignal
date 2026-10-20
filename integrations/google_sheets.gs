/**
 * PaySignal -> Google Sheets receiver (no service account or API keys needed).
 *
 * Setup (about 3 minutes):
 *  1. Create a Google Sheet. Extensions > Apps Script. Paste this file. Save.
 *  2. Deploy > New deployment > type "Web app".
 *     Execute as: Me.  Who has access: Anyone.
 *  3. Copy the Web app URL into SHEETS_WEBHOOK_URL in .env and restart PaySignal.
 *
 * Each POST appends one row. Re-sent rows are skipped by event_id, so a retry
 * from PaySignal never creates a duplicate line in the books.
 */
const HEADERS = ["date", "type", "customer", "description", "amount", "net_effect",
                 "currency", "detail", "stripe_id", "event_id"];

function doPost(e) {
  const row = JSON.parse(e.postData.contents);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
  }

  const eventIdCol = HEADERS.indexOf("event_id") + 1;
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    const seen = sheet.getRange(2, eventIdCol, lastRow - 1, 1).getValues().flat();
    if (seen.includes(row.event_id)) {
      return ContentService.createTextOutput(JSON.stringify({ status: "duplicate" }))
        .setMimeType(ContentService.MimeType.JSON);
    }
  }

  sheet.appendRow(HEADERS.map((h) => row[h] ?? ""));
  return ContentService.createTextOutput(JSON.stringify({ status: "ok" }))
    .setMimeType(ContentService.MimeType.JSON);
}
