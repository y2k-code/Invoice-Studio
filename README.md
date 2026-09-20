# Invoice Studio  (v1.0)

A desktop studio for **invoices, quotes and receipts** - Python + Tkinter, light/dark theme,
live preview, PDF / PNG export, multi-currency, drafts and automatic backups.
Everything is stored locally in one SQLite file; nothing is uploaded anywhere.

## Run it (Windows)

1. Install Python 3.10+ from python.org (keep "tcl/tk and IDLE" ticked).
2. Double-click **`run_invoice_studio.bat`** (first start installs Pillow + reportlab into a private `.venv`).

Or by hand:

```bash
pip install -r requirements.txt
python main.py
```

Want a real `.exe`? Double-click **`build_exe.bat`** -> `dist\Invoice Studio\Invoice Studio.exe`.

## What's in v1

| Area | Details |
|---|---|
| **Documents** | Invoice, Quote, Receipt - each with its own number sequence and prefix |
| **Drafts** | Autosaved every 15 s and when you leave the editor; "Issue" locks in a snapshot of your business details |
| **Clients** | Saved client book (name, company, email, phone, address, tax ID, default currency, notes) |
| **Items** | Catalog of items/services with unit + price + currency; new items can be saved automatically |
| **Suggested search** | Type in the client or description box: ranked suggestions (prefix > word > partial > typo-tolerant), most-used first. Empty box shows your most-used. Same engine powers the list search |
| **Currencies** | 33 currencies with correct decimals (JPY 0, KWD 3). Switch an invoice's currency and choose to convert all amounts. Catalog prices convert on the fly. Live rates (free, no key) with manual per-currency overrides, plus a converter |
| **Money maths** | Per-line discount, invoice discount (% or fixed), any number of stacked taxes (negative = withholding), fees, partial payments, balance due; `Decimal` everywhere |
| **Export** | PDF (real text, vector) and PNG (200 dpi, multi-page -> `_page1.png`...) - identical layout to the live preview. Letter or A4, accent colour, light or dark paper, logo + signature |
| **Backups** | Auto backup on a timer (only when data changed) and on exit, keep-newest-N rotation, custom folder (OneDrive/USB), one-click restore (makes a safety copy first) |
| **Theme** | Light / Dark, remembered; dark title bar on Windows 10/11 |

Data lives in `%APPDATA%\InvoiceStudio\invoice_studio.db` (logo/signature are inside it, so a backup is a complete copy).
Set the environment variable `INVOICE_STUDIO_HOME` to use another folder.

## Notes

* Built-in exchange rates are rough fall-backs so the app works offline - press **Settings -> Currencies -> Update live rates**
  before invoicing in a foreign currency. Live data: open.er-api.com (ExchangeRate-API, attribution required, updated daily).
* Currency symbols other than $ EUR GBP JPY are printed as codes (`PKR 12,000.00`) so they render in any font.
* Issued documents keep their own copy of your business details; changing Settings later doesn't rewrite history.

## Ideas for v1.x

Multiple business profiles, recurring invoices, payment ledger with dates, reports, email sending, RTL/Urdu documents, more templates.
