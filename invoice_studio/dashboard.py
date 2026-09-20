"""Home page: quick actions, key numbers, a 6-month chart and recent documents."""
from __future__ import annotations

import datetime as dt
import tkinter as tk
from decimal import Decimal
from tkinter import ttk

from ..core import DOC_TYPES, STATUS_LABELS, parse_date, payment_status
from ..currency import D, format_money
from . import theme
from .widgets import Card, make_tree


class DashboardPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._chart: list[tuple[str, Decimal]] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", padx=theme.px(24), pady=(theme.px(18), theme.px(4)))
        ttk.Label(head, text="Dashboard", style="Title.TLabel").pack(side="left")
        self.sub = ttk.Label(head, text="", style="Muted.TLabel")
        self.sub.pack(side="left", padx=14)
        actions = ttk.Frame(head)
        actions.pack(side="right")
        ttk.Button(actions, text="＋  Invoice", style="Accent.TButton", command=lambda: self.app.new_document("invoice")).pack(side="left")
        ttk.Button(actions, text="＋  Quote", command=lambda: self.app.new_document("quote")).pack(side="left", padx=6)
        ttk.Button(actions, text="＋  Receipt", command=lambda: self.app.new_document("receipt")).pack(side="left")

        stats = ttk.Frame(self)
        stats.grid(row=1, column=0, sticky="ew", padx=theme.px(24), pady=theme.px(12))
        self.stat_labels: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        for i, (key, caption) in enumerate((("out", "Outstanding"), ("late", "Overdue"), ("paid", "Collected"), ("drafts", "Drafts"))):
            stats.columnconfigure(i, weight=1, uniform="s")
            card = Card(stats)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else theme.px(6), 0 if i == 3 else theme.px(6)))
            ttk.Label(card.body, text=caption, style="Muted.TLabel").pack(anchor="w")
            value = ttk.Label(card.body, text="-", style="Stat.TLabel")
            value.pack(anchor="w", pady=(4, 0))
            note = ttk.Label(card.body, text="", style="Muted.TLabel")
            note.pack(anchor="w")
            self.stat_labels[key] = (value, note)

        ttk.Label(self, text="Invoiced per month", style="H2.TLabel").grid(row=2, column=0, sticky="w", padx=theme.px(24))
        lower = ttk.Frame(self)
        lower.grid(row=3, column=0, sticky="nsew", padx=theme.px(24), pady=(theme.px(6), theme.px(16)))
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=1)
        chart_card = Card(lower, padding=8)
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, theme.px(8)))
        self.canvas = tk.Canvas(chart_card.body, highlightthickness=0, height=theme.px(220))
        self.canvas.bgkey = "bg"
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw())
        recent = ttk.Frame(lower)
        recent.grid(row=0, column=1, sticky="nsew", padx=(theme.px(8), 0))
        recent.rowconfigure(1, weight=1)
        recent.columnconfigure(0, weight=1)
        ttk.Label(recent, text="Recent documents", style="H2.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        frame, self.tree = make_tree(recent, [("number", "No.", 70), ("client", "Client", 140), ("total", "Total", 100), ("status", "Status", 90)],
                                     height=8, right_cols=("total",), stretch="client")
        frame.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._open)

    def on_show(self, **_kw) -> None:
        self.refresh()

    def on_theme(self) -> None:
        self.refresh()

    def _open(self, _e=None) -> None:
        sel = self.tree.selection()
        if sel:
            self.app.open_document(int(sel[0]))

    def refresh(self) -> None:
        app, base = self.app, self.app.prefs.get("base_currency", "USD")
        conv = lambda amount, cur: app.rates.convert(amount, cur, base)  # noqa: E731
        rows = app.db.list_invoices()
        outstanding = overdue = collected = Decimal(0)
        n_open = n_late = 0
        months: dict[str, Decimal] = {}
        today = dt.date.today()
        for r in rows:
            total, paid = D(r["total"]), D(r["paid"])
            status = payment_status(r, {"total": total, "paid": paid, "balance": total - paid})
            r["_status"] = status
            if r["doc_type"] != "invoice" or r["status"] != "issued":
                continue
            balance = total - paid
            collected += conv(paid, r["currency"])
            if balance > 0:
                outstanding += conv(balance, r["currency"])
                n_open += 1
                if status == "overdue":
                    overdue += conv(balance, r["currency"])
                    n_late += 1
            d = parse_date(r["issue_date"])
            if d:
                months[f"{d.year}-{d.month:02d}"] = months.get(f"{d.year}-{d.month:02d}", Decimal(0)) + conv(total, r["currency"])
        drafts = sum(1 for r in rows if r["status"] == "draft")
        m = lambda v: format_money(v, base)  # noqa: E731
        self.stat_labels["out"][0].configure(text=m(outstanding))
        self.stat_labels["out"][1].configure(text=f"{n_open} open invoice{'s' if n_open != 1 else ''}")
        self.stat_labels["late"][0].configure(text=m(overdue))
        self.stat_labels["late"][1].configure(text=f"{n_late} past due")
        self.stat_labels["paid"][0].configure(text=m(collected))
        self.stat_labels["paid"][1].configure(text="all time")
        self.stat_labels["drafts"][0].configure(text=str(drafts))
        self.stat_labels["drafts"][1].configure(text="waiting to be issued" if drafts else "all caught up")
        self.sub.configure(text=f"Totals shown in {base} - converted with your saved rates")

        series = []
        y, mo = today.year, today.month
        keys = []
        for _ in range(6):
            keys.append((y, mo))
            mo -= 1
            if mo == 0:
                y, mo = y - 1, 12
        for y, mo in reversed(keys):
            series.append((dt.date(y, mo, 1).strftime("%b"), months.get(f"{y}-{mo:02d}", Decimal(0))))
        self._chart = series
        self._draw()

        self.tree.delete(*self.tree.get_children())
        for r in rows[:8]:
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["number"], r["client_name"] or DOC_TYPES.get(r["doc_type"], ""), format_money(r["total"], r["currency"]),
                STATUS_LABELS.get(r["_status"], r["_status"])))

    def _draw(self) -> None:
        c, p = self.canvas, theme.PAL
        c.configure(bg=p["bg"])
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 80 or h < 80 or not self._chart:
            return
        pad, top, bottom = theme.px(16), theme.px(26), theme.px(28)
        slot = (w - 2 * pad) / len(self._chart)
        bw = slot * 0.5
        peak = max((v for _, v in self._chart), default=Decimal(0))
        c.create_line(pad, h - bottom, w - pad, h - bottom, fill=p["border"])
        for i, (label, value) in enumerate(self._chart):
            x0 = pad + i * slot + (slot - bw) / 2
            bar_h = (h - top - bottom) * float(value / peak) if peak > 0 else 0
            if bar_h > 0:
                c.create_rectangle(x0, h - bottom - bar_h, x0 + bw, h - bottom, fill=p["chart"], outline="")
                c.create_text(x0 + bw / 2, h - bottom - bar_h - 10, text=f"{float(value):,.0f}", fill=p["muted"], font=(theme.FAMILY, 8))
            c.create_text(x0 + bw / 2, h - bottom + 14, text=label, fill=p["muted"], font=(theme.FAMILY, 9))
