"""Main window: sidebar navigation, shared services, backups, exports."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import APP_NAME, __version__
from ..core import DEFAULT_BUSINESS, DEFAULT_PREFS, DOC_TYPES, new_invoice, next_number, prefix_for, safe_filename
from ..currency import RateBook
from ..db import Database
from ..paths import data_dir
from ..render import build_document, export_pdf, export_png
from . import theme
from .dashboard import DashboardPage
from .editor import EditorPage
from .people import ClientsPage, ItemsPage
from .records import InvoicesPage
from .settings import SettingsPage

NAV = [("dashboard", "Dashboard"), ("invoices", "All documents"), ("drafts", "Drafts"),
       ("clients", "Clients"), ("items", "Items"), ("settings", "Settings")]


class InvoiceStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title(f"{APP_NAME}")
        self.db = Database(data_dir() / "invoice_studio.db")
        self.prefs: dict = {**DEFAULT_PREFS, **(self.db.get_json("prefs", {}) or {})}
        self.business: dict = {**DEFAULT_BUSINESS, **(self.db.get_json("business", {}) or {})}
        self.rates = RateBook(self.db.get_json("rates"))
        self.last_backup = ""
        self._image_cache: dict | None = None
        self._status_job = None

        theme.init(self)
        theme.apply(self, self.prefs.get("theme", "light"))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(theme.px(1480), sw - 60), min(theme.px(920), sh - 90)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        self.minsize(min(theme.px(1260), sw), min(theme.px(700), sh))

        self._build()
        self.bind_all("<Control-n>", lambda e: self.new_document("invoice"))
        self.bind_all("<Control-s>", lambda e: self.pages["editor"].save() if self.current == "editor" else None)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show("dashboard")
        self.deiconify()
        self._schedule_backup()
        if not (self.business.get("name") or "").strip():
            self.after(300, self._first_run)

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        side = ttk.Frame(self, style="Sidebar.TFrame", width=theme.px(236))
        side.grid(row=0, column=0, sticky="ns")
        side.pack_propagate(False)
        ttk.Label(side, text=APP_NAME, style="Brand.TLabel").pack(anchor="w", padx=theme.px(18), pady=(theme.px(20), 0))
        ttk.Label(side, text=f"v{__version__}", style="SidebarMuted.TLabel").pack(anchor="w", padx=theme.px(18))
        ttk.Button(side, text="＋  New invoice", style="Accent.TButton",
                   command=lambda: self.new_document("invoice")).pack(fill="x", padx=theme.px(14), pady=theme.px(16))
        self.nav_buttons: dict[str, ttk.Button] = {}
        for key, label in NAV:
            btn = ttk.Button(side, text=label, style="Nav.TButton", command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=theme.px(8), pady=1)
            self.nav_buttons[key] = btn
        bottom = ttk.Frame(side, style="Sidebar.TFrame")
        bottom.pack(side="bottom", fill="x", padx=theme.px(12), pady=theme.px(12))
        self.backup_label = ttk.Label(bottom, text="No backup yet", style="SidebarMuted.TLabel", wraplength=theme.px(200))
        self.backup_label.pack(anchor="w", pady=(0, theme.px(8)))
        self.theme_btn = ttk.Button(bottom, style="Nav.TButton", command=self.toggle_theme)
        self.theme_btn.pack(fill="x")

        main = ttk.Frame(self)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        self.container = ttk.Frame(main)
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.status = ttk.Label(main, text="", style="Muted.TLabel", anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", padx=theme.px(20), pady=(0, theme.px(6)))

        self.pages: dict[str, ttk.Frame] = {
            "dashboard": DashboardPage(self.container, self),
            "editor": EditorPage(self.container, self),
            "invoices": InvoicesPage(self.container, self, mode="all"),
            "drafts": InvoicesPage(self.container, self, mode="drafts"),
            "clients": ClientsPage(self.container, self),
            "items": ItemsPage(self.container, self),
            "settings": SettingsPage(self.container, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.current = ""
        self._update_theme_button()
        theme.retheme(self)  # colour the plain tk widgets that were just created

    # ------------------------------------------------------------ navigation
    def show(self, name: str, **kw) -> bool:
        if self.current == "editor" and name != "editor":
            if not self.pages["editor"].confirm_leave():
                return False
        self.current = name
        page = self.pages[name]
        page.tkraise()
        page.on_show(**kw)
        for key, btn in self.nav_buttons.items():
            btn.configure(style="NavActive.TButton" if key == name else "Nav.TButton")
        self._update_counts()
        return True

    def new_document(self, doc_type: str = "invoice", client: dict | None = None) -> None:
        inv = new_invoice(self.business, self.prefs, self.next_number(doc_type), doc_type)
        if client:
            inv["client_id"] = client.get("id")
            inv["client"] = {k: client.get(k, "") or "" for k in ("name", "company", "email", "phone", "address", "tax_id")}
            if client.get("currency"):
                inv["currency"] = client["currency"]
        self.show("editor", invoice=inv)

    def open_document(self, iid: int) -> None:
        inv = self.db.get_invoice(iid)
        if inv is None:
            messagebox.showerror(APP_NAME, "That document no longer exists.")
            return
        self.show("editor", invoice=inv)

    def data_changed(self) -> None:
        self._update_counts()
        page = self.pages.get(self.current)
        if page is not None and hasattr(page, "refresh") and self.current != "editor":
            page.refresh()

    def _update_counts(self) -> None:
        drafts = sum(1 for r in self.db.list_invoices() if r["status"] == "draft")
        self.nav_buttons["drafts"].configure(text=f"Drafts ({drafts})" if drafts else "Drafts")

    # ------------------------------------------------------------ theme
    def _update_theme_button(self) -> None:
        dark = self.prefs.get("theme") == "dark"
        self.theme_btn.configure(text="☀  Switch to light" if dark else "☾  Switch to dark")

    def set_theme(self, name: str) -> None:
        self.prefs["theme"] = name
        self.save_prefs()
        theme.apply(self, name)
        self._update_theme_button()
        for page in self.pages.values():
            if hasattr(page, "on_theme"):
                page.on_theme()

    def toggle_theme(self) -> None:
        self.set_theme("light" if self.prefs.get("theme") == "dark" else "dark")

    # ------------------------------------------------------------ persistence
    def save_prefs(self) -> None:
        self.db.set_json("prefs", self.prefs)

    def save_business(self) -> None:
        self.db.set_json("business", self.business)

    def save_rates(self) -> None:
        self.db.set_json("rates", self.rates.to_state())

    def images(self) -> dict:
        if self._image_cache is None:
            self._image_cache = {"logo": self.db.get_image("logo"), "signature": self.db.get_image("signature")}
        return self._image_cache

    def images_changed(self) -> None:
        self._image_cache = None

    def next_number(self, doc_type: str) -> str:
        return next_number(self.db.numbers(doc_type), prefix_for(self.prefs, doc_type), self.prefs.get("number_width", 4))

    # ------------------------------------------------------------ documents / export
    def make_document(self, inv: dict):
        return build_document(inv, inv.get("business") or self.business, self.images(),
                              self.prefs.get("page_size", "letter"))

    def export_invoice(self, inv: dict, kind: str) -> Path | None:
        try:
            doc = self.make_document(inv)
        except Exception as exc:  # layout problems should never crash the app
            messagebox.showerror(APP_NAME, f"Could not build the document:\n{exc}")
            return None
        client = (inv.get("client", {}).get("company") or inv.get("client", {}).get("name") or "").strip()
        base = safe_filename(f"{DOC_TYPES.get(inv.get('doc_type', 'invoice'), 'Invoice')}-{inv.get('number', '')}-{client}".strip("-"))
        ext, label = (".pdf", "PDF document") if kind == "pdf" else (".png", "PNG image")
        start = self.prefs.get("export_dir") or str(Path.home() / "Documents" if (Path.home() / "Documents").exists() else Path.home())
        path = filedialog.asksaveasfilename(parent=self, title=f"Export as {kind.upper()}", defaultextension=ext,
                                            filetypes=[(label, f"*{ext}")], initialfile=base + ext, initialdir=start)
        if not path:
            return None
        try:
            if kind == "pdf":
                out = [export_pdf(doc, path, title=f"{base}", author=self.business.get("name", ""))]
            else:
                out = export_png(doc, path, dpi=200)
        except PermissionError:
            messagebox.showerror(APP_NAME, "Could not write the file. If it is open in another program, close it and try again.")
            return None
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Export failed:\n{exc}")
            return None
        self.prefs["export_dir"] = str(Path(path).parent)
        self.save_prefs()
        self.notify(f"Exported {out[0].name}" + (f" (+{len(out) - 1} more pages)" if len(out) > 1 else ""))
        if self.prefs.get("open_after_export", True):
            self.open_path(out[0])
        return out[0]

    @staticmethod
    def open_path(path: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    # ------------------------------------------------------------ backups
    def backup_dir(self) -> Path:
        custom = (self.prefs.get("backup_dir") or "").strip()
        return Path(custom) if custom else data_dir() / "backups"

    def backup_now(self, silent: bool = False) -> Path | None:
        try:
            dest = self.db.backup_to(self.backup_dir(), keep=int(self.prefs.get("backup_keep", 30)))
        except Exception as exc:
            self.backup_label.configure(text="Backup failed - check the backup folder")
            if not silent:
                messagebox.showerror(APP_NAME, f"Backup failed:\n{exc}")
            return None
        self.last_backup = dest.name
        import datetime as dt
        self.backup_label.configure(text=f"Last backup {dt.datetime.now():%H:%M}")
        if not silent:
            self.notify(f"Backup saved: {dest.name}")
        return dest

    def _schedule_backup(self) -> None:
        minutes = max(1, int(self.prefs.get("backup_minutes", 10) or 10))
        self.after(minutes * 60_000, self._backup_tick)

    def _backup_tick(self) -> None:
        if self.prefs.get("auto_backup", True) and self.db.dirty:
            self.backup_now(silent=True)
        self._schedule_backup()

    def reload_after_restore(self) -> None:
        self.prefs = {**DEFAULT_PREFS, **(self.db.get_json("prefs", {}) or {})}
        self.business = {**DEFAULT_BUSINESS, **(self.db.get_json("business", {}) or {})}
        self.rates = RateBook(self.db.get_json("rates"))
        self.images_changed()
        theme.apply(self, self.prefs.get("theme", "light"))
        self._update_theme_button()
        for page in self.pages.values():
            if hasattr(page, "reload"):
                page.reload()
        self._update_counts()

    # ------------------------------------------------------------ helpers
    def notify(self, message: str, ms: int = 6000) -> None:
        self.status.configure(text=message)
        if self._status_job is not None:
            self.after_cancel(self._status_job)
        self._status_job = self.after(ms, lambda: self.status.configure(text=""))

    def run_async(self, fn, done) -> None:
        """Run fn() in a thread; call done(ok, value_or_exception) on the UI thread."""
        q: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                q.put((True, fn()))
            except Exception as exc:  # noqa: BLE001
                q.put((False, exc))

        threading.Thread(target=work, daemon=True).start()

        def poll() -> None:
            try:
                ok, value = q.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            done(ok, value)

        self.after(150, poll)

    def _first_run(self) -> None:
        self.show("settings", tab="business")
        self.notify("Welcome to Invoice Studio! Add your business details first - they appear on every document.", 15000)

    def on_close(self) -> None:
        if not self.pages["editor"].finish():
            return
        if self.prefs.get("auto_backup", True) and self.db.dirty:
            self.backup_now(silent=True)
        self.db.close()
        self.destroy()
