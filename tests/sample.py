import copy
from invoice_studio.core import DEFAULT_BUSINESS, DEFAULT_PREFS, new_invoice


def sample_invoice(n_items=4, **over):
    biz = dict(DEFAULT_BUSINESS, name="Y2K Studio", address="12 Mall Road\nLahore, Pakistan",
               email="hello@y2k.example", phone="+XX XXX XXXXXX", website="y2k.example", tax_id="1234567-8",
               payment_details="Bank: Example Bank\nIBAN: PK00 EXAM 0000 0000 0000 0000\nAccount title: Y2K Studio",
               terms="Payment due within 14 days. Late payments may incur a 2% monthly fee.")
    inv = new_invoice(biz, dict(DEFAULT_PREFS), "0001")
    inv["client"] = {"name": "Sara Khan", "company": "Acme Trading Ltd", "email": "sara@acme.example",
                     "phone": "+92 42 111 000 000", "address": "45 Gulberg III\nLahore", "tax_id": "NTN 998877"}
    inv["items"] = [
        {"description": f"Website design — landing page section {i+1} with responsive layout and copy edits", "qty": str(i + 1),
         "unit": "hrs", "price": "125.50", "discount": "10" if i == 1 else ""} for i in range(n_items)]
    inv["taxes"] = [{"name": "GST", "rate": "17"}]
    inv["discount_value"] = "5"
    inv["shipping"] = "20"
    inv["status"] = "issued"
    inv["amount_paid"] = "100"
    inv.update(over)
    return inv, biz
