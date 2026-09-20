"""Clients and Items: master list on the left, editor on the right."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..currency import D, currency_codes, format_money, plain
from ..search import rank, usage_boost
from . import theme
from .widgets import Card, get_text, make_tree, set_text


class RecordPage(ttk.Frame):
    title = ""
    noun = ""
    columns: list = []
    right_cols: tuple = ()
    search_keys: tuple = ()
    fields: list = []  # (key, label, kind, col, span)

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.rows: list[dict] = []
        self.current_id: int | None = None
        self.vars: dict[str, tk.StringVar] = {}
        self.texts: dict[str, tk.Text] = {}
        self._build()

    # subclasses
    def all_rows(self) -> list[dict]: raise NotImplementedError
    def row_values(self, r: dict) -> tuple: raise NotImplementedError
    def save_row(self, rec: dict) -> int: raise NotImplementedError
    def delete_row(self, rid: int) -> None: raise NotImplementedError
    def get_row(self, rid: int) -> dict | None: raise NotImplementedError
    def blank(self) -> dict: return {}
    def validate(self, rec: dict) -> str: return "" if rec.get("name") else "Please enter a name."
    def extra_buttons(self, bar: ttk.Frame) -> None: pass

    def _build(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2, minsize=theme.px(380))
        self.rowconfigure(1, weight=1)
        head = ttk.Frame(self)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=theme.px(24), pady=(theme.px(18), theme.px(8)))
        ttk.Label(head, text=self.title, style="Title.TLabel").pack(side="left")
        ttk.Button(head, text=f"＋  New {self.noun}", style="Accent.TButton", command=self.new).pack(side="right")

        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(theme.px(24), theme.px(10)), pady=(0, theme.px(16)))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        self.v_search = tk.StringVar()
        ttk.Entry(left, textvariable=self.v_search).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.v_search.trace_add("write", lambda *a: self._fill())
        frame, self.tree = make_tree(left, self.columns, right_cols=self.right_cols, stretch=self.columns[0][0])
        frame.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._selected)

        card = Card(self)
        card.grid(row=1, column=1, sticky="nsew", padx=(theme.px(10), theme.px(24)), pady=(0, theme.px(16)))
        body = card.body
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        self.form_title = ttk.Label(body, text="", style="H2.TLabel")
        self.form_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        r = 1
        for key, label, kind, col, span in self.fields:
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=r, column=col, columnspan=span, sticky="w")
            if kind == "text":
                w = tk.Text(body, height=3, wrap="word", relief="flat", borderwidth=0, highlightthickness=1)
                self.texts[key] = w
            else:
                v = tk.StringVar()
                self.vars[key] = v
                if kind == "currency":
                    w = ttk.Combobox(body, textvariable=v, values=[""] + currency_codes(), state="readonly")
                else:
                    w = ttk.Entry(body, textvariable=v, justify="right" if kind == "money" else "left")
            w.grid(row=r + 1, column=col, columnspan=span, sticky="ew", padx=(0, 8 if col == 0 and span == 1 else 0), pady=(2, 10))
            if col + span >= 2:
                r += 2
        self.info = ttk.Label(body, text="", style="Muted.TLabel")
        self.info.grid(row=r, column=0, columnspan=2, sticky="w")
        bar = ttk.Frame(body)
        bar.grid(row=r + 1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(bar, text="Save", style="Accent.TButton", command=self.save).pack(side="left")
        self.extra_buttons(bar)
        ttk.Button(bar, text="Delete", style="Danger.TButton", command=self.delete).pack(side="right")

    # ------------------------------------------------------------ data
    def on_show(self, **_kw) -> None:
        self.refresh()
        if self.current_id is None and not any(v.get() for v in self.vars.values()):
            self.new()

    def refresh(self) -> None:
        self.rows = self.all_rows()
        self._fill()

    def reload(self) -> None:
        self.current_id = None
        self.refresh()
        self.new()

    def _fill(self) -> None:
        q = self.v_search.get().strip()
        rows = rank(q, self.rows, self.search_keys, limit=None, boost=usage_boost) if q else self.rows
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", iid=str(r["id"]), values=self.row_values(r))
        if self.current_id and self.tree.exists(str(self.current_id)):
            self.tree.selection_set(str(self.current_id))

    def _selected(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        rec = self.get_row(int(sel[0]))
        if rec:
            self._load(rec)

    def _load(self, rec: dict) -> None:
        self.current_id = rec.get("id")
        for k, v in self.vars.items():
            v.set(str(rec.get(k, "") or ""))
        for k, t in self.texts.items():
            set_text(t, str(rec.get(k, "") or ""))
        self.form_title.configure(text=f"Edit {self.noun}" if self.current_id else f"New {self.noun}")
        self.info.configure(text=self.describe(rec))

    def describe(self, rec: dict) -> str:
        n = int(rec.get("use_count") or 0)
        return f"Used on {n} issued document{'s' if n != 1 else ''}." if self.current_id else ""

    def new(self) -> None:
        self.current_id = None
        if self.tree.selection():
            self.tree.selection_remove(*self.tree.selection())
        self._load(self.blank())
        self.form_title.configure(text=f"New {self.noun}")

    def _gather(self) -> dict:
        rec = {k: v.get().strip() for k, v in self.vars.items()}
        rec.update({k: get_text(t) for k, t in self.texts.items()})
        rec["id"] = self.current_id
        return rec

    def save(self) -> None:
        rec = self._gather()
        problem = self.validate(rec)
        if problem:
            messagebox.showwarning("Invoice Studio", problem, parent=self)
            return
        self.current_id = self.save_row(rec)
        self.app.db.dirty = True
        self.refresh()
        self.tree.selection_set(str(self.current_id))
        self.form_title.configure(text=f"Edit {self.noun}")
        self.app.notify(f"{self.noun.capitalize()} saved.")

    def delete(self) -> None:
        if not self.current_id:
            return
        if messagebox.askyesno("Delete", f"Delete this {self.noun}? Existing documents keep their own copy of the details.", parent=self):
            self.delete_row(self.current_id)
            self.current_id = None
            self.refresh()
            self.new()
            self.app.notify(f"{self.noun.capitalize()} deleted.")


class ClientsPage(RecordPage):
    title = "Clients"
    noun = "client"
    columns = [("name", "Name", 200), ("company", "Company", 180), ("email", "Email", 200), ("currency", "Currency", 80), ("use_count", "Used", 60)]
    right_cols = ("use_count",)
    search_keys = ("name", "company", "email", "phone", "tax_id")
    fields = [("name", "Contact name", "entry", 0, 2), ("company", "Company", "entry", 0, 2),
              ("email", "Email", "entry", 0, 1), ("phone", "Phone", "entry", 1, 1),
              ("tax_id", "Tax / registration no.", "entry", 0, 1), ("currency", "Default currency", "currency", 1, 1),
              ("address", "Address", "text", 0, 2), ("notes", "Private notes", "text", 0, 2)]

    def all_rows(self): return self.app.db.all_clients()
    def get_row(self, rid): return self.app.db.get_client(rid)
    def save_row(self, rec): return self.app.db.save_client(rec)
    def delete_row(self, rid): self.app.db.delete_client(rid)

    def row_values(self, r):
        return (r["name"], r["company"], r["email"], r["currency"], r["use_count"])

    def validate(self, rec):
        return "" if (rec.get("name") or rec.get("company")) else "Enter a contact name or a company."

    def extra_buttons(self, bar):
        ttk.Button(bar, text="New invoice for client", command=self.invoice_for).pack(side="left", padx=8)

    def invoice_for(self) -> None:
        if not self.current_id:
            messagebox.showinfo("Invoice Studio", "Save the client first.", parent=self)
            return
        client = self.app.db.get_client(self.current_id)
        if client:
            self.app.new_document("invoice", client=client)


class ItemsPage(RecordPage):
    title = "Items"
    noun = "item"
    columns = [("name", "Item / service", 260), ("unit", "Unit", 70), ("price", "Price", 110), ("currency", "Cur.", 60), ("use_count", "Used", 60)]
    right_cols = ("price", "use_count")
    search_keys = ("name", "notes")
    fields = [("name", "Item or service name", "entry", 0, 2), ("unit", "Unit (hrs, pcs, ...)", "entry", 0, 1),
              ("price", "Default price", "money", 1, 1), ("currency", "Currency", "currency", 0, 2),
              ("notes", "Private notes", "text", 0, 2)]

    def all_rows(self): return self.app.db.all_items()
    def get_row(self, rid): return self.app.db.get_item(rid)
    def save_row(self, rec):
        rec["price"] = plain(D(rec.get("price"))) if rec.get("price") else "0"
        rec["currency"] = rec.get("currency") or self.app.business.get("default_currency", "USD")
        return self.app.db.save_item(rec)
    def delete_row(self, rid): self.app.db.delete_item(rid)

    def row_values(self, r):
        return (r["name"], r["unit"], format_money(r["price"], r["currency"]) if D(r["price"]) else "", r["currency"], r["use_count"])

    def blank(self):
        return {"currency": self.app.business.get("default_currency", "USD"), "price": ""}
