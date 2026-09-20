"""Invoice data model helpers: defaults, totals, numbering, status."""
from __future__ import annotations

import copy
import datetime as dt
import re
from decimal import Decimal

from .currency import D, plain, quantize

DOC_TYPES = {"invoice": "Invoice", "quote": "Quote", "receipt": "Receipt"}
TERMS = [("Due on receipt", 0), ("Net 7", 7), ("Net 14", 14), ("Net 30", 30), ("Net 60", 60), ("Custom", None)]
STATUS_LABELS = {
    "draft": "Draft", "unpaid": "Unpaid", "partial": "Partially paid",
    "overdue": "Overdue", "paid": "Paid", "sent": "Issued",
}

DEFAULT_PREFS = {
    "theme": "light",
    "page_size": "letter",
    "accent": "#4F46E5",
    "doc_theme": "light",
    "base_currency": "USD",
    "auto_backup": True,
    "backup_minutes": 10,
    "backup_keep": 30,
    "backup_dir": "",
    "save_new_items": True,
    "save_new_clients": True,
    "open_after_export": True,
    "prefix_invoice": "",
    "prefix_quote": "QT-",
    "prefix_receipt": "RC-",
    "number_width": 4,
}

DEFAULT_BUSINESS = {
    "name": "", "address": "", "email": "", "phone": "", "website": "", "tax_id": "",
    "payment_details": "", "notes": "Thank you for your business!", "terms": "",
    "default_currency": "USD", "payment_days": 14, "taxes": [],
}


# ---------------------------------------------------------------- dates
def today_iso() -> str:
    return dt.date.today().isoformat()


def parse_date(text) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(text).strip())
    except (ValueError, TypeError):
        return None


def add_days(iso: str, days: int) -> str:
    d = parse_date(iso) or dt.date.today()
    return (d + dt.timedelta(days=days)).isoformat()


def nice_date(iso: str) -> str:
    d = parse_date(iso)
    return f"{d.day} {d:%b %Y}" if d else (iso or "")


# ---------------------------------------------------------------- numbers
def prefix_for(prefs: dict, doc_type: str) -> str:
    return str(prefs.get(f"prefix_{doc_type}", "") or "")


def next_number(existing: list[str], prefix: str, width: int = 4) -> str:
    """Highest trailing number among numbers that start with `prefix`, plus one."""
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    for num in existing:
        m = pat.match(num or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1:0{max(1, int(width))}d}"


# ---------------------------------------------------------------- invoice
def blank_line() -> dict:
    return {"description": "", "qty": "1", "unit": "", "price": "", "discount": ""}


def new_invoice(business: dict, prefs: dict, number: str, doc_type: str = "invoice") -> dict:
    today = today_iso()
    days = int(business.get("payment_days") or 0)
    return {
        "id": None,
        "doc_type": doc_type,
        "status": "draft",
        "number": number,
        "issue_date": today,
        "due_date": add_days(today, days),
        "terms": next((n for n, d in TERMS if d == days), "Custom"),
        "currency": business.get("default_currency") or "USD",
        "client_id": None,
        "client": {"name": "", "company": "", "email": "", "phone": "", "address": "", "tax_id": ""},
        "items": [blank_line()],
        "discount_type": "percent",
        "discount_value": "",
        "taxes": copy.deepcopy(business.get("taxes") or []),
        "shipping": "",
        "amount_paid": "",
        "notes": business.get("notes", ""),
        "terms_text": business.get("terms", ""),
        "payment_details": business.get("payment_details", ""),
        "accent": prefs.get("accent", "#4F46E5"),
        "doc_theme": prefs.get("doc_theme", "light"),
    }


def duplicate_invoice(inv: dict, number: str) -> dict:
    new = copy.deepcopy(inv)
    for key in ("id", "business"):
        new.pop(key, None)
    new["id"] = None
    new["status"] = "draft"
    new["number"] = number
    new["issue_date"] = today_iso()
    new["amount_paid"] = ""
    days = next((d for n, d in TERMS if n == new.get("terms")), None)
    new["due_date"] = add_days(new["issue_date"], days if days is not None else 14)
    return new


def has_content(inv: dict) -> bool:
    c = inv.get("client", {})
    if any((c.get(k) or "").strip() for k in ("name", "company", "email")):
        return True
    for it in inv.get("items", []):
        if (it.get("description") or "").strip() or D(it.get("price")) != 0:
            return True
    return False  # default notes / terms alone don't count as content


def compute_totals(inv: dict) -> dict:
    """All money maths lives here (Decimal, rounded per currency)."""
    cur = inv.get("currency") or "USD"
    q = lambda v: quantize(v, cur)  # noqa: E731
    lines = []
    subtotal = Decimal(0)
    for it in inv.get("items", []):
        qty, price = D(it.get("qty")), D(it.get("price"))
        disc = min(max(D(it.get("discount")), Decimal(0)), Decimal(100))
        gross = q(qty * price)
        net = q(qty * price * (Decimal(100) - disc) / Decimal(100))
        lines.append({"gross": gross, "net": net, "discount": disc})
        subtotal += net
    dval = max(D(inv.get("discount_value")), Decimal(0))
    if inv.get("discount_type", "percent") == "percent":
        dval = min(dval, Decimal(100))
        discount = q(subtotal * dval / Decimal(100))
    else:
        discount = min(q(dval), subtotal)
    taxable = subtotal - discount
    taxes = []
    for t in inv.get("taxes", []):
        rate = D(t.get("rate"))
        if not (t.get("name") or "").strip() and rate == 0:
            continue
        taxes.append({"name": (t.get("name") or "Tax").strip() or "Tax", "rate": rate, "amount": q(taxable * rate / Decimal(100))})
    tax_total = sum((t["amount"] for t in taxes), Decimal(0))
    shipping = q(D(inv.get("shipping")))
    total = taxable + tax_total + shipping
    paid = q(D(inv.get("amount_paid")))
    if inv.get("doc_type") == "receipt" and paid == 0:
        paid = total
    return {
        "currency": cur, "lines": lines, "subtotal": subtotal, "discount": discount,
        "discount_value": dval, "taxable": taxable, "taxes": taxes, "tax_total": tax_total,
        "shipping": shipping, "total": total, "paid": paid, "balance": total - paid,
    }


def payment_status(inv: dict, totals: dict | None = None, today: dt.date | None = None) -> str:
    """draft | sent | unpaid | partial | overdue | paid"""
    if inv.get("status", "draft") == "draft":
        return "draft"
    t = totals or compute_totals(inv)
    doc_type = inv.get("doc_type", "invoice")
    if doc_type == "receipt":
        return "paid"
    if doc_type == "quote":
        return "sent"
    if t["total"] > 0 and t["balance"] <= 0:
        return "paid"
    due = parse_date(inv.get("due_date"))
    late = bool(due and due < (today or dt.date.today()))
    if late and t["balance"] > 0:
        return "overdue"
    if t["paid"] > 0:
        return "partial"
    return "unpaid"


def fmt_qty(value) -> str:
    d = D(value)
    s = format(d.normalize(), "f")
    return s if "." not in s else s.rstrip("0").rstrip(".")


def safe_filename(text: str) -> str:
    text = re.sub(r"[^\w\-. ]+", "", text or "").strip().replace(" ", "_")
    return text[:80] or "document"


def convert_invoice_currency(inv: dict, old: str, new: str, rates) -> None:
    """Convert every amount on the invoice in place (prices, fees, fixed discount, paid)."""
    for it in inv.get("items", []):
        if D(it.get("price")) != 0:
            it["price"] = plain(rates.convert(it["price"], old, new))
    for key in ("shipping", "amount_paid"):
        if D(inv.get(key)) != 0:
            inv[key] = plain(rates.convert(inv[key], old, new))
    if inv.get("discount_type") == "amount" and D(inv.get("discount_value")) != 0:
        inv["discount_value"] = plain(rates.convert(inv["discount_value"], old, new))
    inv["currency"] = new
