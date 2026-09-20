"""Turns an invoice into pages of drawing operations, then into PDF or PNG.

The layout is computed once (backend-neutral operations in points, origin at the
top-left) so the PDF and the PNG are identical and the live preview matches both.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .core import DOC_TYPES, compute_totals, fmt_qty, nice_date, payment_status
from .currency import D, format_money
from .paths import app_dir

PAGE_SIZES = {"letter": (612.0, 792.0), "a4": (595.276, 841.89)}
DEFAULT_ACCENT = "#4F46E5"

_FONT_FILES = {
    "regular": ["Poppins-Regular.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "medium": ["Poppins-Medium.ttf", "segoeuisl.ttf", "seguisb.ttf"],
    "bold": ["Poppins-Bold.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
}


def _font_dirs() -> list[Path]:
    dirs = [app_dir() / "fonts"]
    win = os.environ.get("WINDIR")
    if win:
        dirs.append(Path(win) / "Fonts")
    dirs += [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
             Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path.home() / ".fonts"]
    return dirs


class FontBook:
    """Finds the TTF files once and measures text with them."""

    def __init__(self) -> None:
        self.paths: dict[str, Path] = {}
        dirs = _font_dirs()
        for style, names in _FONT_FILES.items():
            for name in names:
                found = next((d / name for d in dirs if (d / name).is_file()), None)
                if found:
                    self.paths[style] = found
                    break
        if "regular" not in self.paths:
            raise RuntimeError("No usable font found. Put a .ttf named Poppins-Regular.ttf in the fonts folder.")
        self.paths.setdefault("bold", self.paths["regular"])
        self.paths.setdefault("medium", self.paths["bold"] if self.paths["bold"] != self.paths["regular"] else self.paths["regular"])
        self._pil: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._registered = False

    def pil(self, style: str, px: int) -> ImageFont.FreeTypeFont:
        key = (style, max(1, int(px)))
        if key not in self._pil:
            self._pil[key] = ImageFont.truetype(str(self.paths[style]), key[1])
        return self._pil[key]

    def width(self, text: str, style: str, size: float) -> float:
        return self.pil(style, 100).getlength(text) * size / 100.0

    def register_pdf(self) -> None:
        if self._registered:
            return
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for style, path in self.paths.items():
            name = f"IS-{style}"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
        self._registered = True


_FONTS: FontBook | None = None


def get_fonts() -> FontBook:
    global _FONTS
    if _FONTS is None:
        _FONTS = FontBook()
    return _FONTS


# ---------------------------------------------------------------- colours
def valid_hex(value, default: str = DEFAULT_ACCENT) -> str:
    v = str(value or "").strip()
    return v.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def _luma(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def palette(theme: str, accent: str) -> dict:
    accent = valid_hex(accent)
    on_accent = "#FFFFFF" if _luma(accent) < 0.62 else "#111827"
    if theme == "dark":
        return dict(paper="#111827", text="#F3F4F6", muted="#9CA3AF", line="#374151",
                    alt="#1A2233", accent=accent, on_accent=on_accent)
    return dict(paper="#FFFFFF", text="#111827", muted="#6B7280", line="#E5E7EB",
                alt="#F8FAFC", accent=accent, on_accent=on_accent)


STATUS_COLORS = {"draft": "#D97706", "paid": "#16A34A", "partial": "#EA580C", "overdue": "#DC2626"}
STATUS_TEXT = {"draft": "DRAFT", "paid": "PAID", "partial": "PARTIALLY PAID", "overdue": "OVERDUE"}


# ---------------------------------------------------------------- document
@dataclass
class Document:
    width: float
    height: float
    pages: list[list[tuple]] = field(default_factory=list)
    totals: dict = field(default_factory=dict)


class _Builder:
    M = 44.0

    def __init__(self, W: float, H: float, pal: dict, fonts: FontBook):
        self.W, self.H, self.pal, self.fonts = W, H, pal, fonts
        self.limit = H - 62.0  # content must stay above this line
        self.pages: list[list[tuple]] = []
        self.ops: list[tuple] = []
        self.new_page()

    def new_page(self) -> None:
        self.ops = []
        self.pages.append(self.ops)
        self.ops.append(("rect", 0, 0, self.W, self.H, self.pal["paper"], None, 0, 0))

    # primitives -------------------------------------------------------
    def text(self, x, baseline, s, style="regular", size=9.5, color=None, align="l"):
        self.ops.append(("text", x, baseline, s, style, size, color or self.pal["text"], align))

    def rect(self, x, y, w, h, fill=None, stroke=None, radius=0, lw=0.7):
        self.ops.append(("rect", x, y, w, h, fill, stroke, radius, lw))

    def line(self, x1, y1, x2, y2, color=None, lw=0.6):
        self.ops.append(("line", x1, y1, x2, y2, color or self.pal["line"], lw))

    def image(self, img, x, y, w, h):
        self.ops.append(("image", img, x, y, w, h))

    def wrap(self, s: str, style: str, size: float, maxw: float) -> list[str]:
        out: list[str] = []
        width = self.fonts.width
        for para in str(s).split("\n"):
            cur = ""
            for word in para.split(" "):
                trial = word if not cur else f"{cur} {word}"
                if width(trial, style, size) <= maxw:
                    cur = trial
                    continue
                if cur:
                    out.append(cur)
                while width(word, style, size) > maxw and len(word) > 1:
                    k = len(word)
                    while k > 1 and width(word[:k], style, size) > maxw:
                        k -= 1
                    out.append(word[:k])
                    word = word[k:]
                cur = word
            out.append(cur)
        return out


def _fit(size: tuple[int, int], max_w: float, max_h: float) -> tuple[float, float]:
    w, h = size
    k = min(max_w / w, max_h / h, 1e9)
    return w * k, h * k


def build_document(inv: dict, business: dict | None = None, images: dict | None = None,
                   page_size: str = "letter") -> Document:
    business = business or {}
    images = images or {}
    fonts = get_fonts()
    W, H = PAGE_SIZES.get(page_size, PAGE_SIZES["letter"])
    pal = palette(inv.get("doc_theme", "light"), inv.get("accent"))
    b = _Builder(W, H, pal, fonts)
    T = compute_totals(inv)
    cur = T["currency"]
    money = lambda v: format_money(v, cur)  # noqa: E731
    doc_type = inv.get("doc_type", "invoice")
    status = payment_status(inv, T)
    M, right = b.M, W - b.M
    cw = W - 2 * M
    muted, accent, on_accent = pal["muted"], pal["accent"], pal["on_accent"]

    # ---- header: business (left) and title (right)
    y = M
    ly = y
    logo = images.get("logo")
    if logo is not None:
        lw, lh = _fit(logo.size, 160, 58)
        b.image(logo, M, y, lw, lh)
        ly = y + lh + 9
    if business.get("name"):
        b.text(M, ly + 12, business["name"], "bold", 12.5)
        ly += 20
    contact = "  ·  ".join(x for x in (business.get("email"), business.get("phone"), business.get("website")) if x)
    info_lines: list[str] = []
    for chunk in (business.get("address", ""), contact,
                  f"Tax ID: {business['tax_id']}" if business.get("tax_id") else ""):
        if chunk:
            info_lines += b.wrap(chunk, "regular", 8.8, cw * 0.55)
    for line in info_lines:
        b.text(M, ly + 9, line, "regular", 8.8, muted)
        ly += 12.5

    title = DOC_TYPES.get(doc_type, "Invoice").upper()
    b.text(right, y + 26, title, "bold", 28, accent, "r")
    b.text(right, y + 46, f"No. {inv.get('number', '')}", "medium", 11, muted, "r")
    ry = y + 54
    if status in STATUS_TEXT:
        label = STATUS_TEXT[status]
        bw = fonts.width(label, "bold", 8) + 18
        b.rect(right - bw, ry, bw, 18, STATUS_COLORS[status], None, 9)
        b.text(right - bw / 2, ry + 12.4, label, "bold", 8, "#FFFFFF", "c")
        ry += 18
    y = max(ly, ry) + 14
    b.line(M, y, right, y)
    y += 20

    # ---- bill-to (left) and dates (right)
    client = inv.get("client", {}) or {}
    label = {"quote": "PREPARED FOR", "receipt": "RECEIVED FROM"}.get(doc_type, "BILL TO")
    b.text(M, y + 8, label, "bold", 8, muted)
    cy = y + 22
    if client.get("company"):
        b.text(M, cy + 9, client["company"], "bold", 11)
        cy += 16
    if client.get("name"):
        b.text(M, cy + 9, client["name"], "regular" if client.get("company") else "bold", 10.5 if not client.get("company") else 9.5)
        cy += 15
    for chunk in (client.get("address", ""), client.get("email", ""), client.get("phone", ""),
                  f"Tax ID: {client['tax_id']}" if client.get("tax_id") else ""):
        if chunk:
            for line in b.wrap(chunk, "regular", 9, cw * 0.48):
                b.text(M, cy + 9, line, "regular", 9, muted)
                cy += 12.8

    meta = [("Issue date" if doc_type != "receipt" else "Date", nice_date(inv.get("issue_date", "")))]
    if doc_type == "invoice":
        meta.append(("Due date", nice_date(inv.get("due_date", ""))))
    elif doc_type == "quote":
        meta.append(("Valid until", nice_date(inv.get("due_date", ""))))
    meta.append(("Currency", cur))
    my = y + 8
    for k, v in meta:
        b.text(right - 170, my, k, "regular", 9, muted)
        b.text(right, my, v, "medium", 9.5, None, "r")
        my += 17
    y = max(cy, my) + 16

    # ---- items table
    items = [it for it in inv.get("items", []) if (it.get("description") or "").strip() or D(it.get("price")) != 0]
    has_disc = any(D(it.get("discount")) != 0 for it in items)
    edge = right - 10
    cols: dict[str, float] = {"amount": edge}
    edge -= 86
    cols["rate"] = edge
    edge -= 80
    if has_disc:
        cols["disc"] = edge
        edge -= 52
    cols["qty"] = edge
    edge -= 74
    desc_w = edge - (M + 10)

    def table_header(top: float) -> float:
        b.rect(M, top, cw, 23, accent, None, 4)
        base = top + 15.6
        b.text(M + 10, base, "DESCRIPTION", "bold", 7.8, on_accent)
        b.text(cols["qty"], base, "QTY", "bold", 7.8, on_accent, "r")
        b.text(cols["rate"], base, "RATE", "bold", 7.8, on_accent, "r")
        if has_disc:
            b.text(cols["disc"], base, "DISC", "bold", 7.8, on_accent, "r")
        b.text(cols["amount"], base, "AMOUNT", "bold", 7.8, on_accent, "r")
        return top + 23

    y = table_header(y)
    for idx, it in enumerate(items):
        lines = b.wrap(it.get("description") or "", "regular", 9.5, desc_w)
        rh = len(lines) * 13.6 + 13
        if y + rh > b.limit:
            b.new_page()
            y = table_header(M)
        if idx % 2 == 1:
            b.rect(M, y, cw, rh, pal["alt"])
        base = y + 6.5 + 9.5
        for i, line in enumerate(lines):
            b.text(M + 10, base + i * 13.6, line, "regular", 9.5)
        qty = fmt_qty(it.get("qty"))
        unit = (it.get("unit") or "").strip()
        b.text(cols["qty"], base, f"{qty} {unit}".strip(), "regular", 9.5, None, "r")
        b.text(cols["rate"], base, money(D(it.get("price"))), "regular", 9.5, None, "r")
        if has_disc:
            d = D(it.get("discount"))
            b.text(cols["disc"], base, f"{fmt_qty(d)}%" if d else "", "regular", 9.5, muted, "r")
        b.text(cols["amount"], base, money(T["lines"][inv["items"].index(it)]["net"]), "medium", 9.5, None, "r")
        b.line(M, y + rh, right, y + rh, pal["line"], 0.5)
        y += rh
    if not items:
        b.text(M + 10, y + 20, "No items yet", "regular", 9.5, muted)
        y += 34
    y += 14

    # ---- totals block
    rows: list[tuple[str, str]] = [("Subtotal", money(T["subtotal"]))]
    if T["discount"] > 0:
        dl = "Discount"
        if inv.get("discount_type", "percent") == "percent":
            dl += f" ({fmt_qty(T['discount_value'])}%)"
        rows.append((dl, "-" + money(T["discount"])))
    for t in T["taxes"]:
        rows.append((f"{t['name']} ({fmt_qty(t['rate'])}%)", money(t["amount"])))
    if T["shipping"] != 0:
        rows.append(("Shipping / fees", money(T["shipping"])))
    if doc_type == "invoice":
        if T["paid"] > 0:
            rows += [("Total", money(T["total"])), ("Paid", "-" + money(T["paid"]))]
            band = ("Balance due", T["balance"])
        else:
            band = ("Total due", T["total"])
    elif doc_type == "receipt":
        rows.append(("Total", money(T["total"])))
        band = ("Amount paid", T["paid"])
    else:
        band = ("Total", T["total"])

    bw_total = 244.0
    tx = right - bw_total
    need = len(rows) * 18 + 40
    if y + need > b.limit:
        b.new_page()
        y = M
    top = y
    ty = y
    for lab, val in rows:
        b.text(tx + 8, ty + 12, lab, "regular", 9.5, muted)
        b.text(right - 8, ty + 12, val, "regular", 9.5, None, "r")
        ty += 18
    ty += 4
    b.rect(tx, ty, bw_total, 30, accent, None, 5)
    b.text(tx + 12, ty + 19.5, band[0], "bold", 10.5, on_accent)
    b.text(right - 12, ty + 20, money(band[1]), "bold", 12.5, on_accent, "r")
    totals_end = ty + 30

    # ---- notes / payment details (left of totals; may continue on the next page)
    sections = [("PAYMENT DETAILS", inv.get("payment_details", "")), ("NOTES", inv.get("notes", "")),
                ("TERMS", inv.get("terms_text", ""))]
    lx, lwid = M, cw - bw_total - 26
    ly = top
    page_at_start = len(b.pages)
    for head, body in sections:
        if not (body or "").strip():
            continue
        if ly + 30 > b.limit:
            b.new_page()
            ly, lx, lwid = M, M, cw
        b.text(lx, ly + 8, head, "bold", 8, muted)
        ly += 16
        for line in b.wrap(body.strip(), "regular", 9, lwid):
            if ly + 13 > b.limit:
                b.new_page()
                ly, lx, lwid = M, M, cw
            b.text(lx, ly + 9, line, "regular", 9)
            ly += 12.6
        ly += 8
    y = ly if len(b.pages) > page_at_start else max(ly, totals_end)
    y += 16

    # ---- signature
    sig = images.get("signature")
    if sig is not None:
        sw, sh = _fit(sig.size, 150, 52)
        if y + sh + 30 > b.limit:
            b.new_page()
            y = M
        b.image(sig, right - 150 + (150 - sw) / 2, y, sw, sh)
        b.line(right - 150, y + sh + 4, right, y + sh + 4, muted, 0.6)
        b.text(right - 75, y + sh + 16, "Authorized signature", "regular", 8, muted, "c")

    # ---- page numbers
    n = len(b.pages)
    if n > 1:
        for i, ops in enumerate(b.pages, 1):
            ops.append(("text", W / 2, H - 28, f"Page {i} of {n}", "regular", 8, muted, "c"))
    return Document(W, H, b.pages, T)


# ---------------------------------------------------------------- backends
def _rgb_image(img: Image.Image) -> Image.Image:
    return img if img.mode in ("RGB", "RGBA") else img.convert("RGBA")


def render_png(doc: Document, page: int = 0, dpi: float = 200, supersample: int = 1) -> Image.Image:
    fonts = get_fonts()
    s = dpi / 72.0 * supersample
    Wpx, Hpx = int(round(doc.width * s)), int(round(doc.height * s))
    img = Image.new("RGB", (Wpx, Hpx), "white")
    d = ImageDraw.Draw(img)
    for op in doc.pages[page]:
        kind = op[0]
        if kind == "rect":
            _, x, y, w, h, fill, stroke, radius, lw = op
            box = [x * s, y * s, (x + w) * s - 1, (y + h) * s - 1]
            if radius:
                d.rounded_rectangle(box, radius=radius * s, fill=fill, outline=stroke,
                                    width=max(1, round(lw * s)) if stroke else 0)
            else:
                d.rectangle(box, fill=fill, outline=stroke, width=max(1, round(lw * s)) if stroke else 0)
        elif kind == "line":
            _, x1, y1, x2, y2, color, lw = op
            d.line([x1 * s, y1 * s, x2 * s, y2 * s], fill=color, width=max(1, round(lw * s)))
        elif kind == "text":
            _, x, y, txt, style, size, color, align = op
            font = fonts.pil(style, round(size * s))
            d.text((x * s, y * s), txt, font=font, fill=color, anchor={"l": "ls", "r": "rs", "c": "ms"}[align])
        elif kind == "image":
            _, im, x, y, w, h = op
            im = _rgb_image(im).resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
            img.paste(im, (round(x * s), round(y * s)), im if im.mode == "RGBA" else None)
    if supersample > 1:
        img = img.resize((Wpx // supersample, Hpx // supersample), Image.LANCZOS)
    return img


def render_preview(doc: Document, page: int, max_w: int, max_h: int) -> Image.Image:
    dpi = min(max_w / (doc.width / 72.0), max_h / (doc.height / 72.0))
    return render_png(doc, page, dpi=max(20.0, dpi), supersample=1)


def export_png(doc: Document, path: str | Path, dpi: int = 200) -> list[Path]:
    path = Path(path)
    out: list[Path] = []
    for i in range(len(doc.pages)):
        target = path if len(doc.pages) == 1 else path.with_name(f"{path.stem}_page{i + 1}{path.suffix}")
        render_png(doc, i, dpi=dpi, supersample=2).save(target, dpi=(dpi, dpi))
        out.append(target)
    return out


def export_pdf(doc: Document, path: str | Path, title: str = "", author: str = "") -> Path:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    fonts = get_fonts()
    fonts.register_pdf()
    path = Path(path)
    H = doc.height
    c = canvas.Canvas(str(path), pagesize=(doc.width, doc.height))
    c.setTitle(title or "Invoice")
    c.setAuthor(author or "Invoice Studio")
    c.setCreator("Invoice Studio")
    for ops in doc.pages:
        for op in ops:
            kind = op[0]
            if kind == "rect":
                _, x, y, w, h, fill, stroke, radius, lw = op
                c.saveState()
                if fill:
                    c.setFillColor(HexColor(fill))
                if stroke:
                    c.setStrokeColor(HexColor(stroke))
                    c.setLineWidth(lw)
                if radius:
                    c.roundRect(x, H - y - h, w, h, radius, stroke=1 if stroke else 0, fill=1 if fill else 0)
                else:
                    c.rect(x, H - y - h, w, h, stroke=1 if stroke else 0, fill=1 if fill else 0)
                c.restoreState()
            elif kind == "line":
                _, x1, y1, x2, y2, color, lw = op
                c.saveState()
                c.setStrokeColor(HexColor(color))
                c.setLineWidth(lw)
                c.line(x1, H - y1, x2, H - y2)
                c.restoreState()
            elif kind == "text":
                _, x, y, txt, style, size, color, align = op
                c.setFont(f"IS-{style}", size)
                c.setFillColor(HexColor(color))
                {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[align](x, H - y, txt)
            elif kind == "image":
                _, im, x, y, w, h = op
                c.drawImage(ImageReader(_rgb_image(im)), x, H - y - h, w, h, mask="auto")
        c.showPage()
    c.save()
    return path
