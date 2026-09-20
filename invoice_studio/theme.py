"""Light / dark themes for ttk (clam) plus helpers that re-colour plain tk widgets."""
from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PALETTES = {
    "light": dict(
        bg="#F5F6FA", sidebar="#ECEEF5", sidebar_fg="#374151", hover="#E3E6F0", btn="#FFFFFF",
        input_bg="#FFFFFF", border="#D9DDE7", fg="#111827", muted="#6B7280",
        accent="#4F46E5", accent_hover="#4338CA", accent_fg="#FFFFFF", select_bg="#E0E7FF",
        success="#16A34A", danger="#DC2626", warning="#D97706", chart="#6366F1",
    ),
    "dark": dict(
        bg="#12151D", sidebar="#0C0F15", sidebar_fg="#C9CEDB", hover="#1D2230", btn="#1B202C",
        input_bg="#1A1F2B", border="#2B3243", fg="#E8EAF0", muted="#8E96AB",
        accent="#6D74F5", accent_hover="#858CFF", accent_fg="#FFFFFF", select_bg="#2A3157",
        success="#34D399", danger="#F87171", warning="#FBBF24", chart="#7C83FF",
    ),
}

PAL: dict = dict(PALETTES["light"])
SCALE = 1.0
FAMILY = "TkDefaultFont"


def px(n: float) -> int:
    return int(round(n * SCALE))


def init(root: tk.Tk) -> None:
    global SCALE, FAMILY
    try:
        SCALE = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:
        SCALE = 1.0
    fams = set(tkfont.families(root))
    for cand in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans"):
        if cand in fams:
            FAMILY = cand
            break
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=FAMILY, size=10)
        except tk.TclError:
            pass


def status_color(status: str) -> str:
    return {"overdue": PAL["danger"], "paid": PAL["success"], "draft": PAL["warning"],
            "partial": PAL["warning"]}.get(status, PAL["fg"])


def apply(root: tk.Tk, name: str) -> None:
    PAL.clear()
    PAL.update(PALETTES[name])
    p, fam = PAL, FAMILY
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=p["bg"])

    style.configure(".", background=p["bg"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], troughcolor=p["bg"],
                    focuscolor=p["bg"], insertcolor=p["fg"], selectbackground=p["select_bg"],
                    selectforeground=p["fg"], font=(fam, 10))
    style.configure("TFrame", background=p["bg"])
    style.configure("Sidebar.TFrame", background=p["sidebar"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Muted.TLabel", foreground=p["muted"])
    style.configure("Title.TLabel", font=(fam, 18, "bold"))
    style.configure("H2.TLabel", font=(fam, 11, "bold"))
    style.configure("Stat.TLabel", font=(fam, 20, "bold"))
    style.configure("Sidebar.TLabel", background=p["sidebar"], foreground=p["sidebar_fg"])
    style.configure("Brand.TLabel", background=p["sidebar"], foreground=p["fg"], font=(fam, 15, "bold"))
    style.configure("SidebarMuted.TLabel", background=p["sidebar"], foreground=p["muted"], font=(fam, 9))
    style.configure("Danger.TLabel", foreground=p["danger"])
    style.configure("Good.TLabel", foreground=p["success"])
    style.configure("TSeparator", background=p["border"])

    style.configure("TButton", background=p["btn"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["btn"], darkcolor=p["btn"], focusthickness=0, focuscolor=p["btn"],
                    padding=(px(12), px(6)), relief="flat")
    style.map("TButton", background=[("active", p["hover"]), ("disabled", p["bg"])],
              foreground=[("disabled", p["muted"])], lightcolor=[("active", p["hover"])],
              darkcolor=[("active", p["hover"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"], bordercolor=p["accent"],
                    lightcolor=p["accent"], darkcolor=p["accent"], font=(fam, 10, "bold"))
    style.map("Accent.TButton", background=[("active", p["accent_hover"]), ("disabled", p["border"])],
              lightcolor=[("active", p["accent_hover"])], darkcolor=[("active", p["accent_hover"])],
              bordercolor=[("active", p["accent_hover"])])
    style.configure("Danger.TButton", foreground=p["danger"])
    style.configure("Ghost.TButton", background=p["bg"], bordercolor=p["bg"], lightcolor=p["bg"], darkcolor=p["bg"])
    style.map("Ghost.TButton", background=[("active", p["hover"])], lightcolor=[("active", p["hover"])],
              darkcolor=[("active", p["hover"])], bordercolor=[("active", p["hover"])])
    for nav, bg, fg, weight in (("Nav.TButton", p["sidebar"], p["sidebar_fg"], "normal"),
                                ("NavActive.TButton", p["select_bg"], p["accent"], "bold")):
        style.configure(nav, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg, darkcolor=bg,
                        borderwidth=0, anchor="w", padding=(px(16), px(9)), font=(fam, 10, weight))
    style.map("Nav.TButton", background=[("active", p["hover"])], lightcolor=[("active", p["hover"])],
              darkcolor=[("active", p["hover"])], bordercolor=[("active", p["hover"])])
    style.map("NavActive.TButton", background=[("active", p["select_bg"])], lightcolor=[("active", p["select_bg"])],
              darkcolor=[("active", p["select_bg"])], bordercolor=[("active", p["select_bg"])])

    for w in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(w, fieldbackground=p["input_bg"], foreground=p["fg"], background=p["btn"],
                        bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"],
                        insertcolor=p["fg"], arrowcolor=p["fg"], padding=px(5),
                        selectbackground=p["accent"], selectforeground=p["accent_fg"])
        style.map(w, bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
                  darkcolor=[("focus", p["accent"])])
    style.map("TCombobox", fieldbackground=[("readonly", p["input_bg"])], foreground=[("readonly", p["fg"])],
              selectbackground=[("readonly", p["input_bg"])], selectforeground=[("readonly", p["fg"])])

    style.configure("Treeview", background=p["input_bg"], fieldbackground=p["input_bg"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"], rowheight=px(30))
    style.map("Treeview", background=[("selected", p["select_bg"])], foreground=[("selected", p["fg"])])
    style.configure("Treeview.Heading", background=p["bg"], foreground=p["muted"], relief="flat",
                    padding=(px(8), px(6)), font=(fam, 9, "bold"), bordercolor=p["border"])
    style.map("Treeview.Heading", background=[("active", p["hover"])])

    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=p["btn"], troughcolor=p["bg"], bordercolor=p["bg"],
                        arrowcolor=p["muted"], lightcolor=p["btn"], darkcolor=p["btn"], gripcount=0)
        style.map(f"{orient}.TScrollbar", background=[("active", p["hover"])])

    for w in ("TCheckbutton", "TRadiobutton"):
        style.configure(w, background=p["bg"], foreground=p["fg"], indicatorcolor=p["input_bg"],
                        bordercolor=p["border"], lightcolor=p["input_bg"], darkcolor=p["input_bg"])
        style.map(w, indicatorcolor=[("selected", p["accent"]), ("!selected", p["input_bg"])],
                  background=[("active", p["bg"])])

    style.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], padding=(px(16), px(8)),
                    borderwidth=0, font=(fam, 10, "bold"))
    style.map("TNotebook.Tab", foreground=[("selected", p["accent"])], background=[("selected", p["bg"])])

    root.option_add("*TCombobox*Listbox.background", p["input_bg"])
    root.option_add("*TCombobox*Listbox.foreground", p["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])
    retheme(root)
    set_titlebar(root, name == "dark")


def retheme(widget: tk.Misc) -> None:
    """Re-colour the plain tk widgets (ttk ones follow the style automatically)."""
    p = PAL
    for child in widget.winfo_children():
        retheme(child)
    if getattr(widget, "keep_colors", False):  # e.g. colour swatches
        return
    cls = widget.winfo_class()
    try:
        if cls == "Text":
            widget.configure(bg=p["input_bg"], fg=p["fg"], insertbackground=p["fg"],
                             selectbackground=p["select_bg"], selectforeground=p["fg"],
                             highlightbackground=p["border"], highlightcolor=p["accent"])
        elif cls == "Listbox":
            widget.configure(bg=p["input_bg"], fg=p["fg"], selectbackground=p["accent"],
                             selectforeground=p["accent_fg"], highlightbackground=p["border"],
                             highlightcolor=p["accent"])
        elif cls == "Canvas":
            widget.configure(bg=p[getattr(widget, "bgkey", "bg")])
        elif cls == "Frame":  # plain tk.Frame (cards)
            widget.configure(bg=p[getattr(widget, "bgkey", "bg")], highlightbackground=p["border"])
        elif cls == "Toplevel":
            widget.configure(bg=p["border"])
        elif cls == "TCombobox":
            popdown = widget.tk.eval(f"ttk::combobox::PopdownWindow {widget}")
            widget.tk.call(f"{popdown}.f.l", "configure", "-background", p["input_bg"], "-foreground", p["fg"],
                           "-selectbackground", p["accent"], "-selectforeground", p["accent_fg"])
    except tk.TclError:
        pass


def set_titlebar(root: tk.Tk, dark: bool) -> None:
    """Dark title bar on Windows 10/11 (silently ignored elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer / older builds)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass
