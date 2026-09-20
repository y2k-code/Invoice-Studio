"""Settings: business profile, invoicing defaults, currencies, backups, appearance."""
from __future__ import annotations

import datetime as dt
import io
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image

from .. import APP_NAME, __version__
from ..currency import (CURRENCIES, D, RATES_URL, currency_codes, currency_name, fetch_live_rates,
                        format_number)
from ..core import TERMS
from ..db import Database
from ..render import valid_hex
from . import theme
from .widgets import Card, ScrollFrame, get_text, make_tree, set_text

SWATCHES = ["#4F46E5", "#2563EB", "#0D9488", "#059669", "#EA580C", "#E11D48", "#7C3AED", "#334155"]
TAB_INDEX = {"business": 0, "invoicing": 1, "currencies": 2, "backups": 3, "appearance": 4}


class SettingsPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.tax_rows: list[dict] = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="Settings", style="Title.TLabel").grid(row=0, column=0, sticky="w", padx=theme.px(24), pady=(theme.px(18), theme.px(6)))
        self.nb = ttk.Notebook(self)
        self.nb.grid(row=1, column=0, sticky="nsew", padx=theme.px(16), pady=(0, theme.px(12)))
        self.tab_business = self._tab("Business")
        self.tab_invoicing = self._tab("Invoicing")
        self.tab_currencies = self._tab("Currencies")
        self.tab_backups = self._tab("Backups")
        self.tab_appearance = self._tab("Appearance & About")
        self._build_business(self.tab_business)
        self._build_invoicing(self.tab_invoicing)
        self._build_currencies(self.tab_currencies)
        self._build_backups(self.tab_backups)
        self._build_appearance(self.tab_appearance)
        self.reload()

    def _tab(self, title: str) -> ttk.Frame:
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text=title)
        sf.inner.columnconfigure(0, weight=1)
        return sf.inner

    def _card(self, parent, title: str, row: int) -> ttk.Frame:
        card = Card(parent)
        card.grid(row=row, column=0, sticky="ew", padx=theme.px(8), pady=(theme.px(8), 0))
        ttk.Label(card.body, text=title, style="H2.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for c in range(4):
            card.body.columnconfigure(c, weight=1, uniform="c")
        return card.body

    @staticmethod
    def _field(parent, label: str, widget, row: int, col: int = 0, span: int = 2) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(row=row, column=col, columnspan=span, sticky="w")
        widget.grid(row=row + 1, column=col, columnspan=span, sticky="ew", padx=(0, 8), pady=(2, 10))

    @staticmethod
    def _text(parent, height: int = 3) -> tk.Text:
        return tk.Text(parent, height=height, wrap="word", relief="flat", borderwidth=0, highlightthickness=1)

    def on_show(self, tab: str | None = None, **_kw) -> None:
        if tab in TAB_INDEX:
            self.nb.select(TAB_INDEX[tab])
        self._refresh_rates()
        self._refresh_backups()

    # ================================================================ business
    def _build_business(self, tab) -> None:
        body = self._card(tab, "Your business (printed on every document)", 0)
        self.b_vars = {k: tk.StringVar() for k in ("name", "email", "phone", "website", "tax_id")}
        self._field(body, "Business name", ttk.Entry(body, textvariable=self.b_vars["name"]), 1, 0, 4)
        self._field(body, "Email", ttk.Entry(body, textvariable=self.b_vars["email"]), 3, 0, 2)
        self._field(body, "Phone", ttk.Entry(body, textvariable=self.b_vars["phone"]), 3, 2, 2)
        self._field(body, "Website", ttk.Entry(body, textvariable=self.b_vars["website"]), 5, 0, 2)
        self._field(body, "Tax / registration no.", ttk.Entry(body, textvariable=self.b_vars["tax_id"]), 5, 2, 2)
        self.b_address = self._text(body)
        self._field(body, "Address", self.b_address, 7, 0, 4)

        art = self._card(tab, "Logo & signature", 1)
        self.logo_lbl = ttk.Label(art, text="", style="Muted.TLabel")
        self.sig_lbl = ttk.Label(art, text="", style="Muted.TLabel")
        ttk.Button(art, text="Choose logo...", command=lambda: self._pick_image("logo", (700, 300))).grid(row=1, column=0, sticky="w")
        ttk.Button(art, text="Remove", command=lambda: self._clear_image("logo")).grid(row=1, column=1, sticky="w")
        self.logo_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 10))
        ttk.Button(art, text="Choose signature...", command=lambda: self._pick_image("signature", (500, 200))).grid(row=1, column=2, sticky="w")
        ttk.Button(art, text="Remove", command=lambda: self._clear_image("signature")).grid(row=1, column=3, sticky="w")
        self.sig_lbl.grid(row=2, column=2, columnspan=2, sticky="w", pady=(4, 10))

        txt = self._card(tab, "Default text for new documents", 2)
        self.b_payment = self._text(txt, 4)
        self.b_notes = self._text(txt)
        self.b_terms = self._text(txt)
        self._field(txt, "Payment details (bank, IBAN, wallet...)", self.b_payment, 1, 0, 4)
        self._field(txt, "Notes", self.b_notes, 3, 0, 4)
        self._field(txt, "Terms & conditions", self.b_terms, 5, 0, 4)
        ttk.Button(tab, text="Save business details", style="Accent.TButton", command=self.save_business).grid(
            row=3, column=0, sticky="w", padx=theme.px(8), pady=theme.px(14))

    def save_business(self) -> None:
        biz = self.app.business
        for k, v in self.b_vars.items():
            biz[k] = v.get().strip()
        biz["address"] = get_text(self.b_address)
        biz["payment_details"] = get_text(self.b_payment)
        biz["notes"] = get_text(self.b_notes)
        biz["terms"] = get_text(self.b_terms)
        self.app.save_business()
        self.app.notify("Business details saved. New documents will use them; issued documents keep their own copy.")

    def _pick_image(self, name: str, max_size: tuple[int, int]) -> None:
        path = filedialog.askopenfilename(parent=self, title=f"Choose {name}",
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
            img = img.convert("RGBA")
            img.thumbnail(max_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "PNG")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not read that image:\n{exc}", parent=self)
            return
        self.app.db.set_image(name, buf.getvalue())
        self.app.images_changed()
        self._refresh_images()
        self.app.notify(f"{name.capitalize()} saved.")

    def _clear_image(self, name: str) -> None:
        self.app.db.set_image(name, None)
        self.app.images_changed()
        self._refresh_images()

    def _refresh_images(self) -> None:
        imgs = self.app.images()
        self.logo_lbl.configure(text=f"Logo set ({imgs['logo'].size[0]}x{imgs['logo'].size[1]})" if imgs["logo"] else "No logo")
        self.sig_lbl.configure(text=f"Signature set ({imgs['signature'].size[0]}x{imgs['signature'].size[1]})" if imgs["signature"] else "No signature")

    # ================================================================ invoicing
    def _build_invoicing(self, tab) -> None:
        d = self._card(tab, "Defaults for new documents", 0)
        self.v_cur = tk.StringVar()
        self.v_base = tk.StringVar()
        self.v_days = tk.StringVar()
        self._field(d, "Default currency", ttk.Combobox(d, textvariable=self.v_cur, values=currency_codes(), state="readonly"), 1, 0, 1)
        self._field(d, "Dashboard totals in", ttk.Combobox(d, textvariable=self.v_base, values=currency_codes(), state="readonly"), 1, 1, 1)
        self._field(d, "Payment terms", ttk.Combobox(d, textvariable=self.v_days, values=[t for t, days in TERMS if days is not None], state="readonly"), 1, 2, 1)
        ttk.Label(d, text="Default taxes", style="Muted.TLabel").grid(row=3, column=0, columnspan=4, sticky="w")
        self.tax_frame = ttk.Frame(d)
        self.tax_frame.grid(row=4, column=0, columnspan=4, sticky="ew")
        ttk.Button(d, text="＋  Add tax", command=lambda: self._add_tax()).grid(row=5, column=0, sticky="w", pady=(4, 6))

        n = self._card(tab, "Numbering", 1)
        self.v_pre = {k: tk.StringVar() for k in ("invoice", "quote", "receipt")}
        self.v_width = tk.StringVar()
        self._field(n, "Invoice prefix", ttk.Entry(n, textvariable=self.v_pre["invoice"]), 1, 0, 1)
        self._field(n, "Quote prefix", ttk.Entry(n, textvariable=self.v_pre["quote"]), 1, 1, 1)
        self._field(n, "Receipt prefix", ttk.Entry(n, textvariable=self.v_pre["receipt"]), 1, 2, 1)
        self._field(n, "Digits", ttk.Spinbox(n, from_=1, to=8, textvariable=self.v_width, width=4), 1, 3, 1)
        ttk.Label(n, text="The next number is the highest existing one plus one, so drafts and deletions never cause duplicates.",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=4, sticky="w")

        o = self._card(tab, "Documents & exports", 2)
        self.v_page = tk.StringVar()
        self.v_accent = tk.StringVar()
        self.v_paper = tk.StringVar()
        self.v_open = tk.BooleanVar()
        self.v_save_clients = tk.BooleanVar()
        self.v_save_items = tk.BooleanVar()
        self._field(o, "Page size", ttk.Combobox(o, textvariable=self.v_page, values=["Letter", "A4"], state="readonly"), 1, 0, 1)
        sw = ttk.Frame(o)
        sw.grid(row=1, column=1, columnspan=3, sticky="w")
        ttk.Label(sw, text="Default accent colour", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(sw)
        row.pack(anchor="w", pady=(4, 0))
        for color in SWATCHES:
            box = tk.Frame(row, width=theme.px(22), height=theme.px(22), bg=color, cursor="hand2", highlightthickness=1, highlightbackground="#9CA3AF")
            box.keep_colors = True
            box.pack(side="left", padx=3)
            box.bind("<Button-1>", lambda e, c=color: self.v_accent.set(c))
        ttk.Entry(row, textvariable=self.v_accent, width=9).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(o, text="Light paper by default", value="light", variable=self.v_paper).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Radiobutton(o, text="Dark paper by default", value="dark", variable=self.v_paper).grid(row=3, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(o, text="Save new clients to my client list by default", variable=self.v_save_clients).grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Checkbutton(o, text="Save new items to my catalog by default", variable=self.v_save_items).grid(row=5, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(o, text="Open the file after exporting", variable=self.v_open).grid(row=6, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Button(tab, text="Save invoicing settings", style="Accent.TButton", command=self.save_invoicing).grid(
            row=3, column=0, sticky="w", padx=theme.px(8), pady=theme.px(14))

    def _add_tax(self, name: str = "", rate: str = "") -> None:
        frame = ttk.Frame(self.tax_frame)
        frame.pack(fill="x", pady=2)
        v_name, v_rate = tk.StringVar(value=name), tk.StringVar(value=str(rate))
        ttk.Entry(frame, textvariable=v_name, width=26).pack(side="left")
        ttk.Entry(frame, textvariable=v_rate, width=8, justify="right").pack(side="left", padx=6)
        ttk.Label(frame, text="%").pack(side="left")
        entry = {"frame": frame, "name": v_name, "rate": v_rate}
        ttk.Button(frame, text="✕", width=3, style="Ghost.TButton", command=lambda: self._remove_tax(entry)).pack(side="left", padx=6)
        self.tax_rows.append(entry)

    def _remove_tax(self, entry: dict) -> None:
        entry["frame"].destroy()
        self.tax_rows.remove(entry)

    def save_invoicing(self) -> None:
        app = self.app
        app.business["default_currency"] = self.v_cur.get() or "USD"
        days = dict(TERMS).get(self.v_days.get())
        app.business["payment_days"] = 14 if days is None else days
        app.business["taxes"] = [{"name": t["name"].get().strip(), "rate": t["rate"].get().strip()}
                                 for t in self.tax_rows if t["name"].get().strip() or t["rate"].get().strip()]
        app.save_business()
        p = app.prefs
        p["base_currency"] = self.v_base.get() or "USD"
        for k, v in self.v_pre.items():
            p[f"prefix_{k}"] = v.get().strip()
        try:
            p["number_width"] = max(1, min(8, int(self.v_width.get())))
        except ValueError:
            p["number_width"] = 4
        p["page_size"] = "a4" if self.v_page.get() == "A4" else "letter"
        p["accent"] = valid_hex(self.v_accent.get())
        p["doc_theme"] = self.v_paper.get() or "light"
        p["open_after_export"] = bool(self.v_open.get())
        p["save_new_clients"] = bool(self.v_save_clients.get())
        p["save_new_items"] = bool(self.v_save_items.get())
        app.save_prefs()
        app.notify("Invoicing settings saved.")
        app.data_changed()

    # ================================================================ currencies
    def _build_currencies(self, tab) -> None:
        conv = self._card(tab, "Quick converter", 0)
        self.c_amount = tk.StringVar(value="100")
        self.c_from = tk.StringVar(value="USD")
        self.c_to = tk.StringVar(value="PKR")
        self._field(conv, "Amount", ttk.Entry(conv, textvariable=self.c_amount, justify="right"), 1, 0, 1)
        self._field(conv, "From", ttk.Combobox(conv, textvariable=self.c_from, values=currency_codes(), state="readonly"), 1, 1, 1)
        self._field(conv, "To", ttk.Combobox(conv, textvariable=self.c_to, values=currency_codes(), state="readonly"), 1, 2, 1)
        self.c_result = ttk.Label(conv, text="", style="H2.TLabel")
        self.c_result.grid(row=1, column=3, rowspan=2, sticky="w")
        for v in (self.c_amount, self.c_from, self.c_to):
            v.trace_add("write", lambda *a: self._convert())

        box = self._card(tab, "Exchange rates (units per 1 USD)", 1)
        self.rate_info = ttk.Label(box, text="", style="Muted.TLabel")
        self.rate_info.grid(row=1, column=0, columnspan=4, sticky="w")
        frame, self.rate_tree = make_tree(box, [("code", "Code", 70), ("name", "Currency", 220), ("rate", "Rate", 120), ("source", "Source", 90)],
                                          height=11, right_cols=("rate",), stretch="name")
        frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=8)
        bar = ttk.Frame(box)
        bar.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.btn_live = ttk.Button(bar, text="Update live rates", style="Accent.TButton", command=self.update_live)
        self.btn_live.pack(side="left")
        ttk.Button(bar, text="Set manual rate...", command=self.set_manual).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear manual rate", command=self.clear_manual).pack(side="left")
        ttk.Label(box, text=f"Live rates come from open.er-api.com (ExchangeRate-API, free, updated daily). Manual rates always win.\nBuilt-in rates are rough fall-backs so the app works offline - update them before invoicing.",
                  style="Muted.TLabel", justify="left").grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _convert(self) -> None:
        try:
            res = self.app.rates.convert(D(self.c_amount.get()), self.c_from.get(), self.c_to.get())
            self.c_result.configure(text=f"= {format_number(res, self.c_to.get())} {self.c_to.get()}")
        except Exception:
            self.c_result.configure(text="")

    def _refresh_rates(self) -> None:
        rb = self.app.rates
        self.rate_tree.delete(*self.rate_tree.get_children())
        for code in currency_codes():
            self.rate_tree.insert("", "end", iid=code, values=(code, currency_name(code), f"{float(rb.rate(code)):,.4f}", rb.origin(code)))
        self.rate_info.configure(text=f"Last live update: {rb.updated}" if rb.source == "live" and rb.updated else "Using built-in fall-back rates (no live update yet).")
        self._convert()

    def update_live(self) -> None:
        self.btn_live.state(["disabled"])
        self.app.notify("Downloading rates...")

        def done(ok: bool, value) -> None:
            self.btn_live.state(["!disabled"])
            if not ok:
                messagebox.showerror(APP_NAME, f"Could not download rates (are you online?):\n{value}", parent=self)
                return
            n = self.app.rates.apply_live(value)
            self.app.save_rates()
            self._refresh_rates()
            self.app.notify(f"Updated {n} exchange rates.")

        self.app.run_async(fetch_live_rates, done)

    def set_manual(self) -> None:
        sel = self.rate_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a currency in the list first.", parent=self)
            return
        code = sel[0]
        val = simpledialog.askfloat("Manual rate", f"1 USD = ? {code}", parent=self, initialvalue=float(self.app.rates.rate(code)), minvalue=0.000001)
        if val:
            self.app.rates.set_manual(code, val)
            self.app.save_rates()
            self._refresh_rates()

    def clear_manual(self) -> None:
        sel = self.rate_tree.selection()
        if sel:
            self.app.rates.set_manual(sel[0], None)
            self.app.save_rates()
            self._refresh_rates()

    # ================================================================ backups
    def _build_backups(self, tab) -> None:
        a = self._card(tab, "Automatic backups", 0)
        self.k_auto = tk.BooleanVar()
        self.k_min = tk.StringVar()
        self.k_keep = tk.StringVar()
        self.k_dir = tk.StringVar()
        ttk.Checkbutton(a, text="Back up automatically (only when something changed, and when you close the app)", variable=self.k_auto).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self._field(a, "Every (minutes)", ttk.Spinbox(a, from_=1, to=1440, textvariable=self.k_min, width=6), 2, 0, 1)
        self._field(a, "Keep the newest", ttk.Spinbox(a, from_=1, to=500, textvariable=self.k_keep, width=6), 2, 1, 1)
        ttk.Label(a, text="Backup folder (blank = the app's own folder). Point it at OneDrive / Google Drive / a USB drive for extra safety.",
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=4, sticky="w")
        ttk.Entry(a, textvariable=self.k_dir).grid(row=5, column=0, columnspan=3, sticky="ew", padx=(0, 8), pady=(2, 10))
        ttk.Button(a, text="Browse...", command=self._browse_backup).grid(row=5, column=3, sticky="w", pady=(2, 10))
        bar = ttk.Frame(a)
        bar.grid(row=6, column=0, columnspan=4, sticky="w")
        ttk.Button(bar, text="Save backup settings", style="Accent.TButton", command=self.save_backups).pack(side="left")
        ttk.Button(bar, text="Back up now", command=self._backup_now).pack(side="left", padx=6)

        lst = self._card(tab, "Backups on disk", 1)
        frame, self.bk_tree = make_tree(lst, [("name", "File", 300), ("when", "Created", 150), ("size", "Size", 80)], height=8, right_cols=("size",), stretch="name")
        frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        bar2 = ttk.Frame(lst)
        bar2.grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Button(bar2, text="Restore selected", command=self._restore_selected).pack(side="left")
        ttk.Button(bar2, text="Restore from file...", command=self._restore_file).pack(side="left", padx=6)
        ttk.Button(bar2, text="Open folder", command=lambda: self.app.open_path(self.app.backup_dir())).pack(side="left")

    def _browse_backup(self) -> None:
        d = filedialog.askdirectory(parent=self, title="Choose the backup folder")
        if d:
            self.k_dir.set(d)

    def save_backups(self) -> None:
        p = self.app.prefs
        p["auto_backup"] = bool(self.k_auto.get())
        for key, var, default in (("backup_minutes", self.k_min, 10), ("backup_keep", self.k_keep, 30)):
            try:
                p[key] = max(1, int(var.get()))
            except ValueError:
                p[key] = default
        p["backup_dir"] = self.k_dir.get().strip()
        self.app.save_prefs()
        self._refresh_backups()
        self.app.notify("Backup settings saved.")

    def _backup_now(self) -> None:
        self.save_backups()
        self.app.backup_now()
        self._refresh_backups()

    def _refresh_backups(self) -> None:
        self.bk_tree.delete(*self.bk_tree.get_children())
        for f in Database.list_backups(self.app.backup_dir()):
            st = f.stat()
            self.bk_tree.insert("", "end", iid=str(f), values=(f.name, dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"), f"{st.st_size / 1024:,.0f} KB"))

    def _restore(self, path: Path) -> None:
        if not messagebox.askyesno(
                "Restore backup",
                f"Replace ALL current data with:\n{path.name}\n\nA safety copy of your current data is made first. Continue?", parent=self):
            return
        try:
            self.app.db.restore_from(path, self.app.backup_dir())
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Restore failed:\n{exc}", parent=self)
            return
        self.app.reload_after_restore()
        self.app.notify("Backup restored.")
        self.app.show("dashboard")

    def _restore_selected(self) -> None:
        sel = self.bk_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a backup in the list first.", parent=self)
            return
        self._restore(Path(sel[0]))

    def _restore_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose a backup file", filetypes=[("Invoice Studio backup", "*.db"), ("All files", "*.*")])
        if path:
            self._restore(Path(path))

    # ================================================================ appearance
    def _build_appearance(self, tab) -> None:
        a = self._card(tab, "Theme", 0)
        self.v_theme = tk.StringVar()
        ttk.Radiobutton(a, text="Light", value="light", variable=self.v_theme, command=lambda: self.app.set_theme("light")).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(a, text="Dark", value="dark", variable=self.v_theme, command=lambda: self.app.set_theme("dark")).grid(row=1, column=1, sticky="w")
        ttk.Label(a, text="You can also switch from the button at the bottom of the sidebar. This is the theme of the app; each document has its own light/dark paper.",
                  style="Muted.TLabel", wraplength=theme.px(700)).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        about = self._card(tab, "About", 1)
        ttk.Label(about, text=f"{APP_NAME} {__version__}", style="H2.TLabel").grid(row=1, column=0, columnspan=4, sticky="w")
        ttk.Label(about, style="Muted.TLabel", justify="left", wraplength=theme.px(700), text=(
            f"Your data lives in {self.app.db.path}\n"
            "Fonts: Poppins (SIL Open Font License).\n"
            f"Live exchange rates: {RATES_URL} (Rates by Exchange Rate API - https://www.exchangerate-api.com)")).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

    # ================================================================ load
    def reload(self) -> None:
        app = self.app
        biz, p = app.business, app.prefs
        for k, v in self.b_vars.items():
            v.set(biz.get(k, ""))
        set_text(self.b_address, biz.get("address", ""))
        set_text(self.b_payment, biz.get("payment_details", ""))
        set_text(self.b_notes, biz.get("notes", ""))
        set_text(self.b_terms, biz.get("terms", ""))
        self._refresh_images()
        self.v_cur.set(biz.get("default_currency", "USD"))
        self.v_base.set(p.get("base_currency", "USD"))
        self.v_days.set(next((n for n, d in TERMS if d == int(biz.get("payment_days", 14) or 0)), "Net 14"))
        for t in list(self.tax_rows):
            t["frame"].destroy()
        self.tax_rows = []
        for t in biz.get("taxes", []):
            self._add_tax(t.get("name", ""), t.get("rate", ""))
        for k, v in self.v_pre.items():
            v.set(p.get(f"prefix_{k}", ""))
        self.v_width.set(str(p.get("number_width", 4)))
        self.v_page.set("A4" if p.get("page_size") == "a4" else "Letter")
        self.v_accent.set(p.get("accent", "#4F46E5"))
        self.v_paper.set(p.get("doc_theme", "light"))
        self.v_open.set(bool(p.get("open_after_export", True)))
        self.v_save_clients.set(bool(p.get("save_new_clients", True)))
        self.v_save_items.set(bool(p.get("save_new_items", True)))
        self.k_auto.set(bool(p.get("auto_backup", True)))
        self.k_min.set(str(p.get("backup_minutes", 10)))
        self.k_keep.set(str(p.get("backup_keep", 30)))
        self.k_dir.set(p.get("backup_dir", ""))
        self.v_theme.set(p.get("theme", "light"))
        self._refresh_rates()
        self._refresh_backups()
