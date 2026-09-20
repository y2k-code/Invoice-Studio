"""List of saved documents (all / drafts) with search, filters and quick actions."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..core import DOC_TYPES, STATUS_LABELS, duplicate_invoice, payment_status
from ..currency import D, format_money, plain
from ..search import rank
from . import theme
from .widgets import AutocompleteEntry, make_tree

STATUS_FILTERS = {"All statuses": None, "Draft": "draft", "Unpaid": "unpaid", "Partially paid": "partial",
                  "Overdue": "overdue", "Paid": "paid", "Issued (quotes)": "sent"}
TYPE_FILTERS = {"All types": None, "Invoices": "invoice", "Quotes": "quote", "Receipts": "receipt"}


class InvoicesPage(ttk.Frame):
    def __init__(self, parent, app, mode: str = "all"):
        super().__init__(parent)
        self.app = app
        self.mode = mode
        self.rows: list[dict] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", padx=theme.px(24), pady=(theme.px(18), theme.px(8)))
        ttk.Label(head, text="Drafts" if self.mode == "drafts" else "All documents", style="Title.TLabel").pack(side="left")
        self.count_lbl = ttk.Label(head, text="", style="Muted.TLabel")
        self.count_lbl.pack(side="left", padx=14)
        ttk.Button(head, text="＋  New", style="Accent.TButton", command=lambda: self.app.new_document("invoice")).pack(side="right")

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=theme.px(24), pady=(0, theme.px(8)))
        self.v_search = tk.StringVar()
        self.search = AutocompleteEntry(bar, suggest=self._suggest, on_pick=self._picked, textvariable=self.v_search, width=34)
        self.search.pack(side="left")
        self.v_search.trace_add("write", lambda *a: self._fill())
        self.v_type = tk.StringVar(value="All types")
        ttk.Combobox(bar, textvariable=self.v_type, values=list(TYPE_FILTERS), state="readonly", width=12).pack(side="left", padx=8)
        self.v_status = tk.StringVar(value="All statuses")
        if self.mode != "drafts":
            ttk.Combobox(bar, textvariable=self.v_status, values=list(STATUS_FILTERS), state="readonly", width=16).pack(side="left")
        for cb in bar.winfo_children():
            if isinstance(cb, ttk.Combobox):
                cb.bind("<<ComboboxSelected>>", lambda e: self._fill())

        cols = [("number", "No.", 90), ("type", "Type", 80), ("client", "Client", 240), ("issued", "Issued", 100),
                ("due", "Due", 100), ("total", "Total", 120), ("balance", "Balance", 120), ("status", "Status", 120)]
        frame, self.tree = make_tree(self, cols, right_cols=("total", "balance"), stretch="client")
        frame.grid(row=2, column=0, sticky="nsew", padx=theme.px(24))
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())

        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", padx=theme.px(24), pady=theme.px(12))
        ttk.Button(actions, text="Open", command=self.open_selected).pack(side="left")
        ttk.Button(actions, text="Duplicate", command=self.duplicate).pack(side="left", padx=6)
        ttk.Button(actions, text="Export PDF", command=lambda: self.export("pdf")).pack(side="left")
        ttk.Button(actions, text="Export PNG", command=lambda: self.export("png")).pack(side="left", padx=6)
        ttk.Button(actions, text="Mark paid", command=self.mark_paid).pack(side="left")
        ttk.Button(actions, text="Delete", style="Danger.TButton", command=self.delete).pack(side="right")

    # ------------------------------------------------------------ data
    def on_show(self, **_kw) -> None:
        self.refresh()

    def on_theme(self) -> None:
        self._fill()

    def refresh(self) -> None:
        rows = self.app.db.list_invoices()
        for r in rows:
            total, paid = D(r["total"]), D(r["paid"])
            status = payment_status(r, {"total": total, "paid": paid, "balance": total - paid})
            r["_status"] = status
            r["_status_label"] = STATUS_LABELS.get(status, status)
            r["_total"] = format_money(total, r["currency"])
            r["_balance"] = format_money(total - paid, r["currency"]) if r["doc_type"] == "invoice" and r["status"] != "draft" else ""
            r["_type"] = DOC_TYPES.get(r["doc_type"], r["doc_type"])
        self.rows = rows
        self._fill()

    def _visible(self) -> list[dict]:
        rows = self.rows
        if self.mode == "drafts":
            rows = [r for r in rows if r["_status"] == "draft"]
        t = TYPE_FILTERS.get(self.v_type.get())
        if t:
            rows = [r for r in rows if r["doc_type"] == t]
        s = STATUS_FILTERS.get(self.v_status.get()) if self.mode != "drafts" else None
        if s:
            rows = [r for r in rows if r["_status"] == s]
        q = self.v_search.get().strip()
        if q:
            rows = rank(q, rows, ("number", "client_name", "_type", "_status_label", "_total"), limit=None)
        return rows

    def _fill(self) -> None:
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        rows = self._visible()
        for st in ("overdue", "paid", "draft", "partial"):
            self.tree.tag_configure(st, foreground=theme.status_color(st))
        for r in rows:
            self.tree.insert("", "end", iid=str(r["id"]), tags=(r["_status"],), values=(
                r["number"], r["_type"], r["client_name"], r["issue_date"], r["due_date"] if r["doc_type"] != "receipt" else "",
                r["_total"], r["_balance"], r["_status_label"]))
        if keep and self.tree.exists(keep[0]):
            self.tree.selection_set(keep[0])
        self.count_lbl.configure(text=f"{len(rows)} shown" if rows or self.rows else "Nothing here yet - create your first document")

    def _suggest(self, q: str):
        rows = rank(q, self.rows, ("number", "client_name", "_type", "_total"), limit=7)
        return [(f"{r['number']}   ·   {r['client_name'] or 'No client'}   ·   {r['_total']}", r) for r in rows]

    def _picked(self, row: dict) -> None:
        self.v_search.set("")
        self.app.open_document(row["id"])

    # ------------------------------------------------------------ actions
    def _selected(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Invoice Studio", "Select a document in the list first.", parent=self)
            return None
        return int(sel[0])

    def open_selected(self) -> None:
        iid = self._selected()
        if iid:
            self.app.open_document(iid)

    def duplicate(self) -> None:
        iid = self._selected()
        if not iid:
            return
        inv = self.app.db.get_invoice(iid)
        if inv:
            self.app.show("editor", invoice=duplicate_invoice(inv, self.app.next_number(inv["doc_type"])))
            self.app.notify("Duplicated as a new draft.")

    def export(self, kind: str) -> None:
        iid = self._selected()
        if iid:
            inv = self.app.db.get_invoice(iid)
            if inv:
                self.app.export_invoice(inv, kind)

    def mark_paid(self) -> None:
        iid = self._selected()
        if not iid:
            return
        inv = self.app.db.get_invoice(iid)
        if not inv or inv["doc_type"] != "invoice" or inv["status"] != "issued":
            messagebox.showinfo("Invoice Studio", "Only issued invoices can be marked as paid.", parent=self)
            return
        from ..core import compute_totals
        T = compute_totals(inv)
        inv["amount_paid"] = plain(T["total"])
        self.app.db.save_invoice(inv, T["total"], T["total"])
        self.app.data_changed()
        self.app.notify(f"Invoice {inv['number']} marked as paid.")

    def delete(self) -> None:
        iid = self._selected()
        if not iid:
            return
        row = next((r for r in self.rows if r["id"] == iid), None)
        label = f"{row['_type']} {row['number']}" if row else "this document"
        if messagebox.askyesno("Delete", f"Delete {label}? This cannot be undone (except from a backup).", parent=self):
            self.app.db.delete_invoice(iid)
            self.app.data_changed()
            self.app.notify(f"Deleted {label}.")
