"""The invoice editor: form on the left, live preview on the right."""
from __future__ import annotations

import copy
import datetime as dt
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageTk

from ..core import (DOC_TYPES, TERMS, add_days, blank_line, compute_totals, convert_invoice_currency,
                    has_content, parse_date, today_iso)
from ..currency import D, currency_codes, currency_name, format_money, plain
from ..render import render_preview, valid_hex
from ..search import rank, usage_boost
from . import theme
from .widgets import AutocompleteEntry, Card, ScrollFrame, get_text, set_text

TYPE_NAMES = ["Invoice", "Quote", "Receipt"]
DISC_TYPES = ["Percent (%)", "Fixed amount"]
SWATCHES = ["#4F46E5", "#2563EB", "#0D9488", "#059669", "#EA580C", "#E11D48", "#7C3AED", "#334155"]
KNOWN_KEYS = {"id", "doc_type", "status", "number", "issue_date", "due_date", "terms", "currency", "client_id",
              "client", "items", "discount_type", "discount_value", "taxes", "shipping", "amount_paid", "notes",
              "terms_text", "payment_details", "accent", "doc_theme"}
AUTOSAVE_MS = 15_000


class LineRow:
    """One row of the items table."""

    def __init__(self, table: "LineItems", data: dict):
        self.table = table
        self.v_desc = tk.StringVar(value=data.get("description", ""))
        self.v_qty = tk.StringVar(value=str(data.get("qty", "1")))
        self.v_unit = tk.StringVar(value=data.get("unit", ""))
        self.v_price = tk.StringVar(value=str(data.get("price", "")))
        self.v_disc = tk.StringVar(value=str(data.get("discount", "")))
        self.v_amount = tk.StringVar(value="")
        f = table
        self.desc = AutocompleteEntry(f, suggest=table.editor.suggest_items, on_pick=self.pick,
                                      textvariable=self.v_desc, width=22)
        self.qty = ttk.Entry(f, textvariable=self.v_qty, width=5, justify="right")
        self.unit = ttk.Entry(f, textvariable=self.v_unit, width=5)
        self.price = ttk.Entry(f, textvariable=self.v_price, width=9, justify="right")
        self.disc = ttk.Entry(f, textvariable=self.v_disc, width=5, justify="right")
        self.amount = ttk.Label(f, textvariable=self.v_amount, width=12, anchor="e")
        self.remove = ttk.Button(f, text="✕", width=3, style="Ghost.TButton", command=lambda: table.remove(self))
        self.widgets = [self.desc, self.qty, self.unit, self.price, self.disc, self.amount, self.remove]
        for var in (self.v_desc, self.v_qty, self.v_unit, self.v_price, self.v_disc):
            var.trace_add("write", lambda *a: table.editor.changed())
        for entry in (self.price, self.disc):
            entry.bind("<Return>", lambda e: table.enter_pressed(self))

    def grid(self, row: int) -> None:
        pads = (0, 4)
        for col, w in enumerate(self.widgets):
            w.grid(row=row, column=col, sticky="ew" if col == 0 else "e", padx=pads, pady=2)

    def destroy(self) -> None:
        for w in self.widgets:
            w.destroy()

    def pick(self, item: dict) -> None:
        ed = self.table.editor
        cur = ed.v_currency.get()
        self.v_desc.set(item["name"])
        self.v_unit.set(item.get("unit", "") or "")
        price = D(item.get("price"))
        if price != 0:
            price = ed.app.rates.convert(price, item.get("currency") or cur, cur)
        self.v_price.set(plain(price) if price != 0 else "")
        if not self.v_qty.get().strip():
            self.v_qty.set("1")
        self.qty.focus_set()
        self.qty.select_range(0, "end")

    def data(self) -> dict:
        return {"description": self.v_desc.get().strip(), "qty": self.v_qty.get().strip(),
                "unit": self.v_unit.get().strip(), "price": self.v_price.get().strip(),
                "discount": self.v_disc.get().strip()}


class LineItems(ttk.Frame):
    HEADS = ["Description", "Qty", "Unit", "Price", "Disc %", "Amount", ""]

    def __init__(self, parent, editor: "EditorPage"):
        super().__init__(parent)
        self.editor = editor
        self.rows: list[LineRow] = []
        self.columnconfigure(0, weight=1)
        for i, head in enumerate(self.HEADS):
            ttk.Label(self, text=head, style="Muted.TLabel", anchor="e" if 0 < i < 6 and i != 2 else "w").grid(
                row=0, column=i, sticky="ew", padx=(0, 4))

    def add(self, data: dict | None = None, focus: bool = False) -> LineRow:
        row = LineRow(self, data or blank_line())
        self.rows.append(row)
        self.regrid()
        if focus:
            row.desc.focus_entry()
        return row

    def regrid(self) -> None:
        for i, row in enumerate(self.rows, 1):
            row.grid(i)

    def remove(self, row: LineRow) -> None:
        if len(self.rows) == 1:  # always keep one row
            row.v_desc.set("")
            row.v_price.set("")
            row.v_qty.set("1")
            row.v_disc.set("")
            row.v_unit.set("")
            return
        self.rows.remove(row)
        row.destroy()
        self.regrid()
        self.editor.changed()

    def enter_pressed(self, row: LineRow) -> None:
        if row is self.rows[-1]:
            self.add(focus=True)
        else:
            self.rows[self.rows.index(row) + 1].desc.focus_entry()

    def set_items(self, items: list[dict]) -> None:
        for row in self.rows:
            row.destroy()
        self.rows = []
        for it in (items or [blank_line()]):
            self.rows.append(LineRow(self, it))
        self.regrid()

    def get_items(self) -> list[dict]:
        return [r.data() for r in self.rows]


class EditorPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.inv_id: int | None = None
        self.status = "draft"
        self.extra: dict = {}
        self.client_id: int | None = None
        self.dirty = False
        self._loading = False
        self._cur = "USD"
        self._type = "invoice"
        self._auto_number = True
        self._auto_due = False
        self._picking = False
        self._picked_name = ""
        self._preview_job = None
        self._photo = None
        self._last_box = (0, 0)
        self.doc = None
        self.page_idx = 0
        self.tax_rows: list[dict] = []
        self._build()
        self.after(AUTOSAVE_MS, self._autosave_tick)

    # ================================================================ build
    def _build(self) -> None:
        self.columnconfigure(0, weight=3, minsize=theme.px(590))
        self.columnconfigure(1, weight=2, minsize=theme.px(420))
        self.rowconfigure(1, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=theme.px(20), pady=(theme.px(16), theme.px(8)))
        self.title_lbl = ttk.Label(bar, text="New invoice", style="Title.TLabel")
        self.title_lbl.pack(side="left")
        self.state_lbl = ttk.Label(bar, text="", style="Muted.TLabel")
        self.state_lbl.pack(side="left", padx=14)
        self.btn_issue = ttk.Button(bar, text="Issue  ▸", style="Accent.TButton", command=lambda: self.save(issue=True))
        self.btn_paid = ttk.Button(bar, text="Mark paid", command=self.mark_paid)
        self.btn_png = ttk.Button(bar, text="Export PNG", command=lambda: self.export("png"))
        self.btn_pdf = ttk.Button(bar, text="Export PDF", command=lambda: self.export("pdf"))
        self.btn_save = ttk.Button(bar, text="Save draft", command=self.save)
        for b in (self.btn_issue, self.btn_save, self.btn_png, self.btn_pdf):
            b.pack(side="right", padx=(6, 0))
        self.btn_paid.pack(side="right", padx=(6, 0))

        scroll = ScrollFrame(self)
        scroll.grid(row=1, column=0, sticky="nsew", padx=(theme.px(20), theme.px(8)), pady=(0, theme.px(10)))
        form = scroll.inner
        form.columnconfigure(0, weight=1)
        self._build_document(form)
        self._build_client(form)
        self._build_items(form)
        self._build_adjust(form)
        self._build_notes(form)
        self._build_style(form)

        box = ttk.Frame(self)
        box.grid(row=1, column=1, sticky="nsew", padx=(theme.px(8), theme.px(20)), pady=(0, theme.px(10)))
        box.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)
        nav = ttk.Frame(box)
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(nav, text="Live preview", style="H2.TLabel").pack(side="left")
        ttk.Button(nav, text="▶", width=3, style="Ghost.TButton", command=lambda: self.turn_page(1)).pack(side="right")
        self.page_lbl = ttk.Label(nav, text="", style="Muted.TLabel")
        self.page_lbl.pack(side="right", padx=4)
        ttk.Button(nav, text="◀", width=3, style="Ghost.TButton", command=lambda: self.turn_page(-1)).pack(side="right")
        self.preview_box = ttk.Frame(box)
        self.preview_box.grid(row=1, column=0, sticky="nsew")
        self.preview_box.pack_propagate(False)
        self.preview = ttk.Label(self.preview_box, anchor="center")
        self.preview.pack(fill="both", expand=True)
        self.preview_box.bind("<Configure>", self._box_resized)

    def _bind(self, var: tk.Variable) -> None:
        var.trace_add("write", lambda *a: self.changed())

    def _bind_text(self, txt: tk.Text) -> None:
        txt.bind("<KeyRelease>", lambda e: self.changed())
        txt.bind("<<Paste>>", lambda e: self.after(20, self.changed))
        txt.bind("<<Cut>>", lambda e: self.after(20, self.changed))

    def _card(self, parent, title: str, row: int) -> ttk.Frame:
        card = Card(parent)
        card.grid(row=row, column=0, sticky="ew", pady=(0, theme.px(12)))
        ttk.Label(card.body, text=title, style="H2.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for c in range(4):
            card.body.columnconfigure(c, weight=1, uniform="c")
        return card.body

    @staticmethod
    def _labeled(parent, text: str, widget, row: int, col: int, span: int = 1) -> None:
        ttk.Label(parent, text=text, style="Muted.TLabel").grid(row=row, column=col, columnspan=span, sticky="w")
        widget.grid(row=row + 1, column=col, columnspan=span, sticky="ew", padx=(0, 8), pady=(2, 10))

    def _build_document(self, parent) -> None:
        body = self._card(parent, "Document", 0)
        self.v_type = tk.StringVar(value="Invoice")
        self.v_number = tk.StringVar()
        self.v_currency = tk.StringVar(value="USD")
        self.v_issue = tk.StringVar()
        self.v_terms = tk.StringVar()
        self.v_due = tk.StringVar()
        self.cb_type = ttk.Combobox(body, textvariable=self.v_type, values=TYPE_NAMES, state="readonly", width=12)
        self.cb_cur = ttk.Combobox(body, textvariable=self.v_currency, values=currency_codes(), state="readonly", width=8)
        self.cb_terms = ttk.Combobox(body, textvariable=self.v_terms, values=[t for t, _ in TERMS], state="readonly", width=14)
        self._labeled(body, "Type", self.cb_type, 1, 0)
        self._labeled(body, "Number", ttk.Entry(body, textvariable=self.v_number), 1, 1)
        self._labeled(body, "Currency", self.cb_cur, 1, 2)
        self.cur_name = ttk.Label(body, text="", style="Muted.TLabel")
        self.cur_name.grid(row=2, column=3, sticky="w", pady=(2, 10))
        self._labeled(body, "Issue date (YYYY-MM-DD)", ttk.Entry(body, textvariable=self.v_issue), 3, 0)
        self._labeled(body, "Payment terms", self.cb_terms, 3, 1)
        self.due_label = ttk.Label(body, text="Due date", style="Muted.TLabel")
        self.due_label.grid(row=3, column=2, sticky="w")
        self.due_entry = ttk.Entry(body, textvariable=self.v_due)
        self.due_entry.grid(row=4, column=2, sticky="ew", padx=(0, 8), pady=(2, 10))
        for v in (self.v_number, self.v_issue, self.v_due):
            self._bind(v)
        self.v_number.trace_add("write", lambda *a: self._number_edited())
        self.v_issue.trace_add("write", lambda *a: self._issue_edited())
        self.v_due.trace_add("write", lambda *a: self._due_edited())
        self.cb_type.bind("<<ComboboxSelected>>", lambda e: self._type_changed())
        self.cb_cur.bind("<<ComboboxSelected>>", lambda e: self._currency_changed())
        self.cb_terms.bind("<<ComboboxSelected>>", lambda e: self._terms_changed())

    def _build_client(self, parent) -> None:
        body = self._card(parent, "Client", 1)
        self.v_client = tk.StringVar()
        self.v_company = tk.StringVar()
        self.v_email = tk.StringVar()
        self.v_phone = tk.StringVar()
        self.v_taxid = tk.StringVar()
        self.v_save_client = tk.BooleanVar(value=True)
        self.client_entry = AutocompleteEntry(body, suggest=self.suggest_clients, on_pick=self.pick_client,
                                              textvariable=self.v_client)
        self._labeled(body, "Client name - start typing to search your saved clients", self.client_entry, 1, 0, 4)
        self._labeled(body, "Company", ttk.Entry(body, textvariable=self.v_company), 3, 0, 2)
        self._labeled(body, "Email", ttk.Entry(body, textvariable=self.v_email), 3, 2, 2)
        self._labeled(body, "Phone", ttk.Entry(body, textvariable=self.v_phone), 5, 0, 2)
        self._labeled(body, "Tax / registration no.", ttk.Entry(body, textvariable=self.v_taxid), 5, 2, 2)
        self.txt_address = tk.Text(body, height=3, wrap="word", relief="flat", borderwidth=0, highlightthickness=1)
        self._labeled(body, "Address", self.txt_address, 7, 0, 4)
        ttk.Checkbutton(body, text="Save / update this client in my client list", variable=self.v_save_client).grid(
            row=9, column=0, columnspan=4, sticky="w")
        for v in (self.v_company, self.v_email, self.v_phone, self.v_taxid):
            self._bind(v)
        self._bind_text(self.txt_address)
        self.v_client.trace_add("write", lambda *a: self._client_name_edited())
        self._bind(self.v_client)

    def _build_items(self, parent) -> None:
        body = self._card(parent, "Items", 2)
        body.columnconfigure(0, weight=1)
        self.lines = LineItems(body, self)
        self.lines.grid(row=1, column=0, columnspan=4, sticky="ew")
        row = ttk.Frame(body)
        row.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(row, text="＋  Add line", command=lambda: self.lines.add(focus=True)).pack(side="left")
        self.v_save_items = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Save new items to my catalog", variable=self.v_save_items).pack(side="left", padx=14)
        ttk.Label(body, text="Tip: click an empty description to see your most-used items; press Enter in the price box for a new line.",
                  style="Muted.TLabel", wraplength=theme.px(600)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_adjust(self, parent) -> None:
        body = self._card(parent, "Discount, tax & payment", 3)
        self.v_disc_type = tk.StringVar(value=DISC_TYPES[0])
        self.v_disc = tk.StringVar()
        self.v_ship = tk.StringVar()
        self.v_paid = tk.StringVar()
        cb = ttk.Combobox(body, textvariable=self.v_disc_type, values=DISC_TYPES, state="readonly", width=14)
        cb.bind("<<ComboboxSelected>>", lambda e: self.changed())
        self._labeled(body, "Discount type", cb, 1, 0)
        self._labeled(body, "Discount", ttk.Entry(body, textvariable=self.v_disc, justify="right"), 1, 1)
        self._labeled(body, "Shipping / fees", ttk.Entry(body, textvariable=self.v_ship, justify="right"), 1, 2)
        for v in (self.v_disc, self.v_ship, self.v_paid):
            self._bind(v)
        ttk.Label(body, text="Taxes (a negative rate works as a withholding deduction)", style="Muted.TLabel").grid(
            row=3, column=0, columnspan=4, sticky="w")
        self.tax_frame = ttk.Frame(body)
        self.tax_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(2, 4))
        ttk.Button(body, text="＋  Add tax", command=lambda: self.add_tax(focus=True)).grid(row=5, column=0, sticky="w", pady=(0, 10))
        self.paid_label = ttk.Label(body, text="Amount paid so far", style="Muted.TLabel")
        self.paid_label.grid(row=6, column=0, sticky="w")
        self.paid_entry = ttk.Entry(body, textvariable=self.v_paid, justify="right")
        self.paid_entry.grid(row=7, column=0, sticky="ew", padx=(0, 8), pady=(2, 10))
        # live totals
        self.sum_frame = ttk.Frame(body)
        self.sum_frame.grid(row=6, column=1, columnspan=3, rowspan=2, sticky="e")
        self.sum_labels: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        for i, key in enumerate(("Subtotal", "Discount", "Tax", "Fees", "Total", "Balance due")):
            a = ttk.Label(self.sum_frame, text=key, style="Muted.TLabel")
            b = ttk.Label(self.sum_frame, text="", anchor="e", width=16,
                          style="H2.TLabel" if key in ("Total", "Balance due") else "TLabel")
            a.grid(row=i, column=0, sticky="w", padx=(0, 16))
            b.grid(row=i, column=1, sticky="e")
            self.sum_labels[key] = (a, b)

    def _build_notes(self, parent) -> None:
        body = self._card(parent, "Notes & payment details", 4)
        self.txt_payment = tk.Text(body, height=4, wrap="word", relief="flat", borderwidth=0, highlightthickness=1)
        self.txt_notes = tk.Text(body, height=3, wrap="word", relief="flat", borderwidth=0, highlightthickness=1)
        self.txt_terms = tk.Text(body, height=3, wrap="word", relief="flat", borderwidth=0, highlightthickness=1)
        self._labeled(body, "Payment details (bank, IBAN, wallet...)", self.txt_payment, 1, 0, 4)
        self._labeled(body, "Notes", self.txt_notes, 3, 0, 4)
        self._labeled(body, "Terms & conditions", self.txt_terms, 5, 0, 4)
        for t in (self.txt_payment, self.txt_notes, self.txt_terms):
            self._bind_text(t)

    def _build_style(self, parent) -> None:
        body = self._card(parent, "Look of this document", 5)
        self.v_accent = tk.StringVar(value="#4F46E5")
        self.v_paper = tk.StringVar(value="light")
        sw = ttk.Frame(body)
        sw.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(sw, text="Accent colour", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        for color in SWATCHES:
            box = tk.Frame(sw, width=theme.px(22), height=theme.px(22), bg=color, cursor="hand2",
                           highlightthickness=1, highlightbackground="#9CA3AF")
            box.keep_colors = True
            box.pack(side="left", padx=3)
            box.bind("<Button-1>", lambda e, c=color: self.v_accent.set(c))
        ttk.Entry(sw, textvariable=self.v_accent, width=9).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(body, text="Light paper", value="light", variable=self.v_paper, command=self.changed).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(body, text="Dark paper", value="dark", variable=self.v_paper, command=self.changed).grid(row=2, column=1, sticky="w")
        self._bind(self.v_accent)

    # ================================================================ taxes
    def add_tax(self, name: str = "", rate: str = "", focus: bool = False) -> None:
        frame = ttk.Frame(self.tax_frame)
        frame.pack(fill="x", pady=2)
        v_name, v_rate = tk.StringVar(value=name), tk.StringVar(value=str(rate))
        e_name = ttk.Entry(frame, textvariable=v_name, width=24)
        e_rate = ttk.Entry(frame, textvariable=v_rate, width=8, justify="right")
        e_name.pack(side="left")
        e_rate.pack(side="left", padx=6)
        ttk.Label(frame, text="%").pack(side="left")
        entry = {"frame": frame, "name": v_name, "rate": v_rate}
        ttk.Button(frame, text="✕", width=3, style="Ghost.TButton", command=lambda: self.remove_tax(entry)).pack(side="left", padx=6)
        self._bind(v_name)
        self._bind(v_rate)
        self.tax_rows.append(entry)
        if focus:
            e_name.focus_set()
        self.changed()

    def remove_tax(self, entry: dict) -> None:
        entry["frame"].destroy()
        self.tax_rows.remove(entry)
        self.changed()

    def set_taxes(self, taxes: list[dict]) -> None:
        for e in list(self.tax_rows):
            e["frame"].destroy()
        self.tax_rows = []
        for t in taxes or []:
            self.add_tax(t.get("name", ""), t.get("rate", ""))

    # ================================================================ suggestions
    def suggest_items(self, query: str) -> list[tuple]:
        cur = self.v_currency.get()
        rows = rank(query, self.app.db.all_items(), ("name",), limit=8, boost=usage_boost)
        out = []
        for r in rows:
            price = D(r.get("price"))
            if price != 0:
                price = self.app.rates.convert(price, r.get("currency") or cur, cur)
            out.append((f"{r['name']}   ·   {format_money(price, cur)}" if price != 0 else r["name"], r))
        return out

    def suggest_clients(self, query: str) -> list[tuple]:
        rows = rank(query, self.app.db.all_clients(), ("name", "company", "email"), limit=8, boost=usage_boost)
        return [(r["name"] + (f"   ·   {r['company']}" if r.get("company") else ""), r) for r in rows]

    def pick_client(self, c: dict) -> None:
        self._picking = True
        try:
            self.client_id = c["id"]
            self._picked_name = c["name"]
            self.v_client.set(c["name"])
            self.v_company.set(c.get("company", ""))
            self.v_email.set(c.get("email", ""))
            self.v_phone.set(c.get("phone", ""))
            self.v_taxid.set(c.get("tax_id", ""))
            set_text(self.txt_address, c.get("address", ""))
        finally:
            self._picking = False
        cur = c.get("currency")
        empty = not any(row.v_price.get().strip() for row in self.lines.rows)
        if cur and cur != self.v_currency.get() and empty:
            self.v_currency.set(cur)
            self._cur = cur
            self._refresh_cur_name()
        self.changed()

    def _client_name_edited(self) -> None:
        if not (self._loading or self._picking) and self.v_client.get() != self._picked_name:
            self.client_id = None

    # ================================================================ document field logic
    def type_key(self) -> str:
        return self.v_type.get().strip().lower() or "invoice"

    def _number_edited(self) -> None:
        if not self._loading and not getattr(self, "_setting_number", False):
            self._auto_number = False

    def _set_number(self, value: str) -> None:
        self._setting_number = True
        try:
            self.v_number.set(value)
        finally:
            self._setting_number = False

    def _type_changed(self) -> None:
        new = self.type_key()
        if new == self._type:
            return
        self._type = new
        if self._auto_number and self.inv_id is None:
            self._set_number(self.app.next_number(new))
        self._apply_type_ui()
        self.changed()

    def _apply_type_ui(self) -> None:
        t = self._type
        self.due_label.configure(text={"quote": "Valid until", "receipt": "Payment date"}.get(t, "Due date"))
        self.due_entry.state(["disabled"] if t == "receipt" else ["!disabled"])
        self.cb_terms.state(["disabled"] if t == "receipt" else ["!disabled", "readonly"])
        if t == "quote":
            self.paid_label.grid_remove()
            self.paid_entry.grid_remove()
        else:
            self.paid_label.grid()
            self.paid_entry.grid()
        self.paid_label.configure(text="Amount received (blank = full total)" if t == "receipt" else "Amount paid so far")
        self._update_title()

    def _terms_changed(self) -> None:
        days = dict(TERMS).get(self.v_terms.get())
        if days is not None:
            self._set_due(add_days(self.v_issue.get(), days))
        self.changed()

    def _issue_edited(self) -> None:
        if self._loading:
            return
        days = dict(TERMS).get(self.v_terms.get())
        if days is not None and parse_date(self.v_issue.get()):
            self._set_due(add_days(self.v_issue.get(), days))

    def _due_edited(self) -> None:
        if not (self._loading or self._auto_due) and self.v_terms.get() != "Custom":
            self.v_terms.set("Custom")

    def _set_due(self, value: str) -> None:
        self._auto_due = True
        try:
            self.v_due.set(value)
        finally:
            self._auto_due = False

    def _refresh_cur_name(self) -> None:
        self.cur_name.configure(text=currency_name(self.v_currency.get()))

    def _currency_changed(self) -> None:
        new, old = self.v_currency.get(), self._cur
        if new == old:
            return
        inv = self.collect()
        has_amounts = any(D(i.get("price")) != 0 for i in inv["items"]) or D(inv.get("shipping")) != 0 or D(inv.get("amount_paid")) != 0
        if has_amounts:
            ans = messagebox.askyesnocancel(
                "Change currency",
                f"Convert the amounts from {old} to {new} using your current rates?\n\n"
                f"Yes  = convert the numbers\nNo   = keep the numbers as they are\nCancel = go back",
                parent=self)
            if ans is None:
                self.v_currency.set(old)
                return
            if ans:
                convert_invoice_currency(inv, old, new, self.app.rates)
                self._loading = True
                try:
                    self.lines.set_items(inv["items"])
                    self.v_ship.set(inv.get("shipping", ""))
                    self.v_paid.set(inv.get("amount_paid", ""))
                    self.v_disc.set(inv.get("discount_value", ""))
                finally:
                    self._loading = False
        self._cur = new
        self._refresh_cur_name()
        self.changed()

    # ================================================================ data <-> form
    def collect(self) -> dict:
        inv = dict(self.extra)
        inv.update({
            "id": self.inv_id,
            "doc_type": self.type_key(),
            "status": self.status,
            "number": self.v_number.get().strip(),
            "issue_date": self.v_issue.get().strip(),
            "due_date": self.v_due.get().strip(),
            "terms": self.v_terms.get(),
            "currency": self.v_currency.get(),
            "client_id": self.client_id,
            "client": {"name": self.v_client.get().strip(), "company": self.v_company.get().strip(),
                       "email": self.v_email.get().strip(), "phone": self.v_phone.get().strip(),
                       "address": get_text(self.txt_address), "tax_id": self.v_taxid.get().strip()},
            "items": self.lines.get_items(),
            "discount_type": "percent" if self.v_disc_type.get() == DISC_TYPES[0] else "amount",
            "discount_value": self.v_disc.get().strip(),
            "taxes": [{"name": t["name"].get().strip(), "rate": t["rate"].get().strip()} for t in self.tax_rows],
            "shipping": self.v_ship.get().strip(),
            "amount_paid": self.v_paid.get().strip(),
            "notes": get_text(self.txt_notes),
            "terms_text": get_text(self.txt_terms),
            "payment_details": get_text(self.txt_payment),
            "accent": valid_hex(self.v_accent.get()),
            "doc_theme": self.v_paper.get(),
        })
        return inv

    def load(self, inv: dict) -> None:
        self._loading = True
        try:
            self.inv_id = inv.get("id")
            self.status = inv.get("status", "draft")
            self.extra = {k: copy.deepcopy(v) for k, v in inv.items() if k not in KNOWN_KEYS}
            self._type = inv.get("doc_type", "invoice")
            self.v_type.set(DOC_TYPES.get(self._type, "Invoice"))
            self._set_number(inv.get("number", ""))
            self._auto_number = self.inv_id is None
            self.v_issue.set(inv.get("issue_date", today_iso()))
            self.v_terms.set(inv.get("terms") or "Custom")
            self._set_due(inv.get("due_date", ""))
            self.v_currency.set(inv.get("currency", "USD"))
            self._cur = self.v_currency.get()
            self._refresh_cur_name()
            c = inv.get("client", {})
            self.client_id = inv.get("client_id")
            self._picked_name = c.get("name", "")
            self.v_client.set(c.get("name", ""))
            self.v_company.set(c.get("company", ""))
            self.v_email.set(c.get("email", ""))
            self.v_phone.set(c.get("phone", ""))
            self.v_taxid.set(c.get("tax_id", ""))
            set_text(self.txt_address, c.get("address", ""))
            self.v_save_client.set(bool(self.app.prefs.get("save_new_clients", True)))
            self.v_save_items.set(bool(self.app.prefs.get("save_new_items", True)))
            self.lines.set_items(inv.get("items") or [blank_line()])
            self.v_disc_type.set(DISC_TYPES[0] if inv.get("discount_type", "percent") == "percent" else DISC_TYPES[1])
            self.v_disc.set(inv.get("discount_value", ""))
            self.v_ship.set(inv.get("shipping", ""))
            self.v_paid.set(inv.get("amount_paid", ""))
            self.set_taxes(inv.get("taxes", []))
            set_text(self.txt_notes, inv.get("notes", ""))
            set_text(self.txt_terms, inv.get("terms_text", ""))
            set_text(self.txt_payment, inv.get("payment_details", ""))
            self.v_accent.set(inv.get("accent", "#4F46E5"))
            self.v_paper.set(inv.get("doc_theme", "light"))
        finally:
            self._loading = False
        self.dirty = False
        self.page_idx = 0
        self._apply_type_ui()
        self._update_buttons()
        self._update_totals()
        self._schedule_preview(30)

    def on_show(self, invoice: dict | None = None, **_kw) -> None:
        if invoice is not None:
            self.load(invoice)
        elif self.doc is None and self.inv_id is None and not self.v_number.get():
            self.app.new_document("invoice")

    # ================================================================ state
    def changed(self) -> None:
        if self._loading:
            return
        self.dirty = True
        self._update_totals()
        self._schedule_preview()

    def _update_title(self) -> None:
        name = DOC_TYPES.get(self._type, "Invoice")
        num = self.v_number.get().strip()
        self.title_lbl.configure(text=f"{name} {num}".strip() if self.inv_id else f"New {name.lower()} {num}".strip())

    def _update_buttons(self) -> None:
        draft = self.status == "draft"
        self.btn_save.configure(text="Save draft" if draft else "Save changes")
        if draft:
            self.btn_issue.pack(side="right", padx=(6, 0), before=self.btn_save)
            self.btn_issue.configure(text={"quote": "Issue quote  ▸", "receipt": "Issue receipt  ▸"}.get(self._type, "Issue invoice  ▸"))
            self.btn_paid.pack_forget()
        else:
            self.btn_issue.pack_forget()
            if self._type == "invoice":
                self.btn_paid.pack(side="right", padx=(6, 0))
            else:
                self.btn_paid.pack_forget()
        self.state_lbl.configure(text="Draft" if draft else "Issued")
        self._update_title()

    def _update_totals(self) -> None:
        inv = self.collect()
        self._update_title()
        try:
            T = compute_totals(inv)
        except Exception:
            return
        cur = T["currency"]
        m = lambda v: format_money(v, cur)  # noqa: E731
        for row, line in zip(self.lines.rows, T["lines"]):
            d = row.data()
            row.v_amount.set(m(line["net"]) if (d["description"] or D(d["price"]) != 0) else "")
        vals = {"Subtotal": m(T["subtotal"]), "Discount": "-" + m(T["discount"]) if T["discount"] else "-",
                "Tax": m(T["tax_total"]) if T["taxes"] else "-", "Fees": m(T["shipping"]) if T["shipping"] else "-",
                "Total": m(T["total"]), "Balance due": m(T["balance"])}
        for key, (_, val) in self.sum_labels.items():
            val.configure(text=vals[key])

    # ================================================================ preview
    def _box_resized(self, e) -> None:
        if abs(e.width - self._last_box[0]) > 8 or abs(e.height - self._last_box[1]) > 8:
            self._last_box = (e.width, e.height)
            self._schedule_preview(150)

    def _schedule_preview(self, delay: int = 350) -> None:
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(delay, self._render_preview)

    def _render_preview(self) -> None:
        self._preview_job = None
        try:
            self.doc = self.app.make_document(self.collect())
            self.page_idx = max(0, min(self.page_idx, len(self.doc.pages) - 1))
            w = max(280, self.preview_box.winfo_width() - 12)
            h = max(360, self.preview_box.winfo_height() - 8)
            img = render_preview(self.doc, self.page_idx, w, h)
        except Exception as exc:
            self.preview.configure(image="", text=f"Preview unavailable:\n{exc}")
            return
        self._photo = ImageTk.PhotoImage(img)
        self.preview.configure(image=self._photo, text="")
        n = len(self.doc.pages)
        self.page_lbl.configure(text=f"Page {self.page_idx + 1} of {n}" if n > 1 else "")

    def turn_page(self, step: int) -> None:
        if self.doc is None:
            return
        self.page_idx = max(0, min(len(self.doc.pages) - 1, self.page_idx + step))
        self._render_preview()

    # ================================================================ saving
    def _write(self, inv: dict, quiet: bool = False) -> None:
        T = compute_totals(inv)
        self.inv_id = self.app.db.save_invoice(inv, T["total"], T["paid"])
        self.dirty = False
        self._update_title()
        if quiet:
            self.state_lbl.configure(text=f"Draft autosaved {dt.datetime.now():%H:%M:%S}")
            self.app._update_counts()
        else:
            self.app.data_changed()

    def _autosave_tick(self) -> None:
        try:
            if self.dirty and self.status == "draft" and self.app.current == "editor":
                inv = self.collect()
                if has_content(inv):
                    self._write(inv, quiet=True)
        except Exception:
            pass
        finally:
            self.after(AUTOSAVE_MS, self._autosave_tick)

    def _save_client(self, inv: dict) -> None:
        c = inv["client"]
        if not self.v_save_client.get() or not (c["name"] or c["company"]):
            return
        db = self.app.db
        rec = (db.get_client(self.client_id) if self.client_id else None) or {"currency": inv["currency"]}
        rec.update({k: c[k] for k in ("name", "company", "email", "phone", "address", "tax_id")})
        if not rec.get("name"):
            rec["name"] = c["company"]
        self.client_id = db.save_client(rec)
        inv["client_id"] = self.client_id

    def _save_items(self, inv: dict, issuing: bool) -> None:
        db = self.app.db
        for it in inv["items"]:
            name = it["description"]
            if not name:
                continue
            found = db.find_item_by_name(name)
            if found:
                if issuing:
                    db.bump_item(found["id"])
            elif self.v_save_items.get() and D(it["price"]) != 0:
                iid = db.save_item({"name": name, "unit": it["unit"], "price": it["price"], "currency": inv["currency"]})
                if issuing:
                    db.bump_item(iid)

    def save(self, issue: bool = False) -> bool:
        inv = self.collect()
        issuing = issue or inv["status"] == "issued"
        if not inv["number"]:
            messagebox.showwarning("Invoice Studio", "Please enter a document number.", parent=self)
            return False
        if parse_date(inv["issue_date"]) is None or (inv["doc_type"] != "receipt" and inv["due_date"] and parse_date(inv["due_date"]) is None):
            messagebox.showwarning("Invoice Studio", "Dates must look like 2026-09-30 (year-month-day).", parent=self)
            return False
        if issuing:
            if not any(i["description"] for i in inv["items"]):
                messagebox.showwarning("Invoice Studio", "Add at least one item before issuing.", parent=self)
                return False
            c = inv["client"]
            if issue and not (c["name"] or c["company"]):
                if not messagebox.askyesno("Invoice Studio", "No client is set. Issue anyway?", parent=self):
                    return False
        if self.app.db.number_taken(inv["doc_type"], inv["number"], self.inv_id):
            if not messagebox.askyesno("Invoice Studio", f"Number {inv['number']} is already used by another {inv['doc_type']}.\nSave anyway?", parent=self):
                return False
        if issue:
            inv["status"] = "issued"
            inv["business"] = copy.deepcopy(self.app.business)
        self._save_client(inv)
        self._save_items(inv, issue)
        if issue:
            if inv.get("client_id"):
                self.app.db.bump_client(inv["client_id"])
        self._write(inv)
        self.status = inv["status"]
        if "business" in inv:
            self.extra["business"] = inv["business"]
        self._update_buttons()
        name = DOC_TYPES.get(inv["doc_type"], "Invoice")
        self.app.notify(f"{name} {inv['number']} issued." if issue else f"{name} {inv['number']} saved.")
        return True

    def mark_paid(self) -> None:
        T = compute_totals(self.collect())
        self.v_paid.set(plain(T["total"]))
        self.save()

    def export(self, kind: str) -> None:
        self.app.export_invoice(self.collect(), kind)

    # ================================================================ leaving
    def confirm_leave(self) -> bool:
        if not self.dirty:
            return True
        inv = self.collect()
        if self.status == "draft":
            if has_content(inv):
                self._write(inv, quiet=True)
                self.app.notify("Draft saved automatically.")
            self.dirty = False
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", f"Save your changes to {DOC_TYPES.get(inv['doc_type'], 'Invoice')} {inv['number']}?", parent=self)
        if ans is None:
            return False
        if ans:
            return self.save()
        self.dirty = False
        return True

    def finish(self) -> bool:
        return self.confirm_leave() if self.app.current == "editor" else True

    def on_theme(self) -> None:
        self._schedule_preview(50)
