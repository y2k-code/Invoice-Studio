"""Reusable widgets: cards, scroll frame, suggestion entry, sortable tables."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from . import theme


class Card(tk.Frame):
    """Bordered panel. Children should be ttk widgets (they share the page background)."""

    def __init__(self, parent, padding: int = 14, **kw):
        super().__init__(parent, bg=theme.PAL["bg"], highlightthickness=1,
                         highlightbackground=theme.PAL["border"], highlightcolor=theme.PAL["border"], **kw)
        self.bgkey = "bg"
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class ScrollFrame(ttk.Frame):
    """Vertically scrolling container; put content in `.inner`."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, yscrollincrement=theme.px(20))
        self.canvas.bgkey = "bg"
        self.canvas.configure(bg=theme.PAL["bg"])
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _inside(self, widget) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _wheel(self, event) -> None:
        try:
            under = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        if under is None or not self._inside(under):
            return
        if under.winfo_class() in ("Text", "Listbox", "Treeview"):
            return
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return
        self.canvas.yview_scroll(-2 if event.delta > 0 else 2, "units")


class AutocompleteEntry(ttk.Frame):
    """Entry with a ranked suggestion dropdown.

    suggest(query) -> list of (label, payload). Picking a row puts `label` in the
    box and calls on_pick(payload). Shows the top suggestions when focused & empty.
    """

    SKIP_KEYS = {"Up", "Down", "Return", "Escape", "Tab", "ISO_Left_Tab", "Left", "Right", "Home", "End",
                 "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Caps_Lock"}

    def __init__(self, parent, suggest, on_pick=None, textvariable=None, width: int = 30):
        super().__init__(parent)
        self.var = textvariable or tk.StringVar()
        self.suggest = suggest
        self.on_pick = on_pick
        self._items: list[tuple] = []
        self._popup: tk.Toplevel | None = None
        self._lb: tk.Listbox | None = None
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(fill="x", expand=True)
        self.entry.bind("<KeyRelease>", self._key_release, add="+")
        self.entry.bind("<Down>", self._down)
        self.entry.bind("<Up>", self._up)
        self.entry.bind("<Return>", self._enter)
        self.entry.bind("<Escape>", lambda e: self._hide())
        self.entry.bind("<FocusIn>", self._focus_in, add="+")
        self.entry.bind("<FocusOut>", lambda e: self.after(200, self._hide_if_lost), add="+")

    # public
    def get(self) -> str:
        return self.var.get()

    def set(self, text: str) -> None:
        self.var.set(text)

    def focus_entry(self) -> None:
        self.entry.focus_set()

    # internals
    def _ensure_popup(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            return
        p = theme.PAL
        self._popup = tk.Toplevel(self)
        self._popup.wm_overrideredirect(True)
        self._popup.configure(bg=p["border"])
        try:
            self._popup.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._lb = tk.Listbox(self._popup, activestyle="none", exportselection=False, borderwidth=0,
                              highlightthickness=0, bg=p["input_bg"], fg=p["fg"], selectbackground=p["accent"],
                              selectforeground=p["accent_fg"], height=6)
        self._lb.pack(fill="both", expand=True, padx=1, pady=1)
        self._lb.bind("<ButtonPress-1>", self._click)
        self._popup.withdraw()

    def _visible(self) -> bool:
        return bool(self._popup is not None and self._popup.winfo_exists() and self._popup.winfo_viewable())

    def _hide(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.withdraw()

    def _has_focus(self) -> bool:
        try:
            return self.focus_get() is self.entry
        except (KeyError, tk.TclError):  # Tk quirk when focus sits in a combobox popdown
            return False

    def _hide_if_lost(self) -> None:
        if not self._has_focus():
            self._hide()

    def _focus_in(self, _e=None) -> None:
        if not self.var.get().strip():
            self.after(80, lambda: self._refresh() if self._has_focus() else None)

    def _key_release(self, e) -> None:
        if e.keysym not in self.SKIP_KEYS:
            self._refresh()

    def _refresh(self) -> None:
        try:
            self._items = list(self.suggest(self.var.get()))
        except Exception:
            self._items = []
        if not self._items:
            self._hide()
            return
        self._ensure_popup()
        assert self._lb is not None and self._popup is not None
        self._lb.delete(0, "end")
        for label, _ in self._items:
            self._lb.insert("end", "  " + label)
        self._lb.configure(height=min(len(self._items), 8))
        self._lb.selection_clear(0, "end")
        self._lb.selection_set(0)
        self._lb.activate(0)
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height() + 1
        w = max(self.entry.winfo_width(), theme.px(300))
        self._popup.update_idletasks()
        self._popup.geometry(f"{w}x{self._lb.winfo_reqheight() + 2}+{x}+{y}")
        self._popup.deiconify()
        self._popup.lift()

    def _move(self, step: int) -> str:
        if not self._visible():
            self._refresh()
            return "break"
        assert self._lb is not None
        cur = self._lb.curselection()
        idx = (cur[0] if cur else -1) + step
        idx = max(0, min(len(self._items) - 1, idx))
        self._lb.selection_clear(0, "end")
        self._lb.selection_set(idx)
        self._lb.activate(idx)
        self._lb.see(idx)
        return "break"

    def _down(self, _e) -> str:
        return self._move(1)

    def _up(self, _e) -> str:
        return self._move(-1)

    def _enter(self, _e):
        if self._visible() and self._lb is not None and self._lb.curselection():
            self._pick(self._lb.curselection()[0])
            return "break"
        return None

    def _click(self, e) -> str:
        assert self._lb is not None
        self._pick(self._lb.nearest(e.y))
        return "break"

    def _pick(self, idx: int) -> None:
        if not (0 <= idx < len(self._items)):
            return
        label, payload = self._items[idx]
        self.var.set(label)
        self._hide()
        self.entry.focus_set()
        self.entry.icursor("end")
        if self.on_pick:
            self.on_pick(payload)


# ---------------------------------------------------------------- tables
def sort_tree(tree: ttk.Treeview, col: str) -> None:
    state = getattr(tree, "sort_state", {})
    reverse = not state.get(col, True)
    rows = [(tree.set(k, col), k) for k in tree.get_children("")]

    def key(item):
        cleaned = re.sub(r"[^0-9.\-]", "", item[0])
        try:
            return (0, float(cleaned), "")
        except ValueError:
            return (1, 0.0, item[0].lower())

    rows.sort(key=key, reverse=reverse)
    for i, (_, k) in enumerate(rows):
        tree.move(k, "", i)
    tree.sort_state = {col: reverse}


def make_tree(parent, columns: list[tuple[str, str, int]], height: int = 12, right_cols: tuple = (),
              stretch: str | None = None):
    """columns: (id, heading, width). Returns (frame, tree)."""
    frame = ttk.Frame(parent)
    ids = [c[0] for c in columns]
    tree = ttk.Treeview(frame, columns=ids, show="headings", selectmode="browse", height=height)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    for cid, head, width in columns:
        tree.heading(cid, text=head, command=lambda c=cid: sort_tree(tree, c))
        tree.column(cid, width=theme.px(width), minwidth=theme.px(40),
                    anchor="e" if cid in right_cols else "w", stretch=(cid == stretch))
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return frame, tree


def get_text(widget: tk.Text) -> str:
    return widget.get("1.0", "end").strip()


def set_text(widget: tk.Text, value: str) -> None:
    widget.delete("1.0", "end")
    widget.insert("1.0", value or "")
