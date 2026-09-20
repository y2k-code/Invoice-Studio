"""Run with:  python -m unittest discover -s tests -v   (no display needed)"""
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sample import sample_invoice  # noqa: E402
from invoice_studio import core, currency, search  # noqa: E402
from invoice_studio.db import Database  # noqa: E402
from invoice_studio.render import build_document, export_pdf, export_png, render_png  # noqa: E402


class Money(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(currency.D("1,250.50"), Decimal("1250.50"))
        self.assertEqual(currency.D("abc"), Decimal(0))
        self.assertEqual(currency.D("NaN"), Decimal(0))

    def test_format(self):
        self.assertEqual(currency.format_money("1234.5", "USD"), "$1,234.50")
        self.assertEqual(currency.format_money("-10", "PKR"), "-PKR 10.00")
        self.assertEqual(currency.format_money("1234.5", "JPY"), "¥1,235")
        self.assertEqual(currency.format_money("1", "KWD"), "KWD 1.000")

    def test_convert_round_trip(self):
        rb = currency.RateBook()
        pkr = rb.convert("100", "USD", "PKR")
        self.assertEqual(rb.convert(pkr, "PKR", "USD"), Decimal("100.00"))
        rb.set_manual("PKR", 300)
        self.assertEqual(rb.convert("1", "USD", "PKR"), Decimal("300.00"))
        rb.set_manual("PKR", None)
        self.assertEqual(rb.rate("PKR"), Decimal("280.0"))


class Totals(unittest.TestCase):
    def test_full_example(self):
        inv, _ = sample_invoice()
        t = core.compute_totals(inv)
        self.assertEqual(t["subtotal"], Decimal("1229.90"))
        self.assertEqual(t["discount"], Decimal("61.50"))
        self.assertEqual(t["tax_total"], Decimal("198.63"))
        self.assertEqual(t["total"], Decimal("1387.03"))
        self.assertEqual(t["balance"], Decimal("1287.03"))

    def test_fixed_discount_never_exceeds_subtotal(self):
        inv, _ = sample_invoice(n_items=1)
        inv.update(discount_type="amount", discount_value="99999", taxes=[], shipping="")
        self.assertEqual(core.compute_totals(inv)["total"], Decimal("0.00"))

    def test_withholding_tax(self):
        inv, _ = sample_invoice(n_items=1)
        inv.update(discount_value="", shipping="", taxes=[{"name": "WHT", "rate": "-10"}])
        t = core.compute_totals(inv)
        self.assertEqual(t["total"], Decimal("112.95"))

    def test_status(self):
        inv, _ = sample_invoice()
        self.assertEqual(core.payment_status(inv), "partial")
        inv["amount_paid"] = "0"
        inv["due_date"] = "2000-01-01"
        self.assertEqual(core.payment_status(inv), "overdue")
        inv["amount_paid"] = "5000"
        self.assertEqual(core.payment_status(inv), "paid")
        inv["status"] = "draft"
        self.assertEqual(core.payment_status(inv), "draft")

    def test_currency_switch_converts_everything(self):
        inv, _ = sample_invoice(n_items=1)
        rb = currency.RateBook()
        core.convert_invoice_currency(inv, "USD", "PKR", rb)
        self.assertEqual(inv["currency"], "PKR")
        self.assertEqual(inv["items"][0]["price"], "35140.00")


class Numbers(unittest.TestCase):
    def test_next(self):
        self.assertEqual(core.next_number([], ""), "0001")
        self.assertEqual(core.next_number(["0001", "0009"], ""), "0010")
        self.assertEqual(core.next_number(["QT-0002", "0500"], "QT-"), "QT-0003")
        self.assertEqual(core.next_number(["INV-9999"], "INV-"), "INV-10000")


class Search(unittest.TestCase):
    rows = [{"name": "Website design", "use_count": 0}, {"name": "Logo design", "use_count": 5},
            {"name": "Hosting (annual)", "use_count": 1}, {"name": "Consulting", "use_count": 0}]

    def names(self, q):
        return [r["name"] for r in search.rank(q, self.rows, ("name",), boost=search.usage_boost)]

    def test_prefix_beats_substring(self):
        self.assertEqual(self.names("log")[0], "Logo design")

    def test_multiple_words_and_fuzzy(self):
        self.assertEqual(self.names("web des"), ["Website design"])
        self.assertIn("Consulting", self.names("consulting"))
        self.assertIn("Consulting", self.names("conslting"))

    def test_empty_query_returns_most_used_first(self):
        self.assertEqual(self.names("")[0], "Logo design")

    def test_no_match(self):
        self.assertEqual(self.names("zzzz"), [])


class Storage(unittest.TestCase):
    def test_backup_rotation_and_restore(self):
        tmp = Path(tempfile.mkdtemp())
        db = Database(tmp / "a.db")
        db.save_client({"name": "Acme"})
        for _ in range(4):
            db.backup_to(tmp / "bk", keep=3)
        files = Database.list_backups(tmp / "bk")
        self.assertEqual(len(files), 3)
        db.delete_client(db.all_clients()[0]["id"])
        self.assertEqual(db.all_clients(), [])
        db.restore_from(files[0], tmp / "bk")
        self.assertEqual(len(db.all_clients()), 1)
        with self.assertRaises(ValueError):
            bad = tmp / "bad.db"
            bad.write_text("nope")
            db.restore_from(bad, tmp / "bk")

    def test_invoice_roundtrip_and_numbers(self):
        db = Database(Path(tempfile.mkdtemp()) / "b.db")
        inv, _ = sample_invoice()
        iid = db.save_invoice(inv, "1387.03", "100")
        self.assertEqual(db.get_invoice(iid)["items"][0]["qty"], "1")
        self.assertTrue(db.number_taken("invoice", "0001"))
        self.assertFalse(db.number_taken("invoice", "0001", exclude_id=iid))


class Rendering(unittest.TestCase):
    def test_pdf_png_and_pagination(self):
        tmp = Path(tempfile.mkdtemp())
        inv, biz = sample_invoice()
        doc = build_document(inv, biz)
        self.assertEqual(len(doc.pages), 1)
        pdf = export_pdf(doc, tmp / "a.pdf", "t")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertEqual(render_png(doc, 0, dpi=50).size, (425, 550))
        big, biz = sample_invoice(n_items=40)
        doc2 = build_document(big, biz, page_size="a4")
        self.assertGreater(len(doc2.pages), 1)
        files = export_png(doc2, tmp / "b.png", dpi=40)
        self.assertEqual(len(files), len(doc2.pages))
        self.assertTrue(all(f.exists() for f in files))

    def test_every_doc_type_and_theme_renders(self):
        for doc_type in ("invoice", "quote", "receipt"):
            for theme in ("light", "dark"):
                inv, biz = sample_invoice(doc_type=doc_type, doc_theme=theme, currency="PKR")
                doc = build_document(inv, biz)
                render_png(doc, 0, dpi=40)


if __name__ == "__main__":
    unittest.main()
