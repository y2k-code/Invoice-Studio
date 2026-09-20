"""Currencies, money formatting, conversion and exchange rates."""
from __future__ import annotations

import json
import time
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# code -> (name, decimal places, symbol used in documents or None)
# Symbols are limited to ones every font has; everything else prints as "PKR 1,000.00".
CURRENCIES: dict[str, tuple[str, int, str | None]] = {
    "USD": ("US Dollar", 2, "$"),
    "EUR": ("Euro", 2, "€"),
    "GBP": ("British Pound", 2, "£"),
    "PKR": ("Pakistani Rupee", 2, None),
    "INR": ("Indian Rupee", 2, None),
    "AED": ("UAE Dirham", 2, None),
    "SAR": ("Saudi Riyal", 2, None),
    "QAR": ("Qatari Riyal", 2, None),
    "KWD": ("Kuwaiti Dinar", 3, None),
    "BHD": ("Bahraini Dinar", 3, None),
    "OMR": ("Omani Rial", 3, None),
    "CAD": ("Canadian Dollar", 2, "$"),
    "AUD": ("Australian Dollar", 2, "$"),
    "NZD": ("New Zealand Dollar", 2, "$"),
    "SGD": ("Singapore Dollar", 2, "$"),
    "HKD": ("Hong Kong Dollar", 2, "$"),
    "JPY": ("Japanese Yen", 0, "¥"),
    "CNY": ("Chinese Yuan", 2, None),
    "KRW": ("South Korean Won", 0, None),
    "CHF": ("Swiss Franc", 2, None),
    "SEK": ("Swedish Krona", 2, None),
    "NOK": ("Norwegian Krone", 2, None),
    "DKK": ("Danish Krone", 2, None),
    "TRY": ("Turkish Lira", 2, None),
    "ZAR": ("South African Rand", 2, None),
    "EGP": ("Egyptian Pound", 2, None),
    "BRL": ("Brazilian Real", 2, None),
    "MXN": ("Mexican Peso", 2, None),
    "MYR": ("Malaysian Ringgit", 2, None),
    "THB": ("Thai Baht", 2, None),
    "IDR": ("Indonesian Rupiah", 2, None),
    "BDT": ("Bangladeshi Taka", 2, None),
    "LKR": ("Sri Lankan Rupee", 2, None),
}

# Rough built-in fallback rates (units per 1 USD). They exist so the app works
# offline; use "Update live rates" in Settings for current numbers.
DEFAULT_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.78, "PKR": 280.0, "INR": 84.0,
    "AED": 3.6725, "SAR": 3.75, "QAR": 3.64, "KWD": 0.307, "BHD": 0.376,
    "OMR": 0.385, "CAD": 1.36, "AUD": 1.5, "NZD": 1.65, "SGD": 1.34,
    "HKD": 7.8, "JPY": 150.0, "CNY": 7.2, "KRW": 1350.0, "CHF": 0.88,
    "SEK": 10.5, "NOK": 10.7, "DKK": 6.9, "TRY": 33.0, "ZAR": 18.0,
    "EGP": 48.0, "BRL": 5.2, "MXN": 18.0, "MYR": 4.6, "THB": 35.0,
    "IDR": 15800.0, "BDT": 118.0, "LKR": 300.0,
}

# Shown first in currency pickers.
COMMON = ["USD", "EUR", "GBP", "PKR", "INR", "AED", "SAR", "CAD", "AUD"]

RATES_URL = "https://open.er-api.com/v6/latest/USD"  # free, no key, attribution required


def currency_codes() -> list[str]:
    rest = sorted(c for c in CURRENCIES if c not in COMMON)
    return COMMON + rest


def currency_name(code: str) -> str:
    return CURRENCIES.get(code, (code, 2, None))[0]


def D(value, default: str = "0") -> Decimal:
    """Forgiving Decimal parser: '1,250.50', ' 3 ', '', None all work."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else Decimal(default)
    if value is None:
        return Decimal(default)
    s = str(value).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "+", "."):
        return Decimal(default)
    try:
        d = Decimal(s)
    except InvalidOperation:
        return Decimal(default)
    return d if d.is_finite() else Decimal(default)


def decimals(code: str) -> int:
    return CURRENCIES.get(code, ("", 2, None))[1]


def quantize(value, code: str) -> Decimal:
    exp = Decimal(1).scaleb(-decimals(code))
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def plain(value: Decimal) -> str:
    """Decimal -> string without exponent, for storing in fields."""
    return format(value, "f")


def format_number(value, code: str) -> str:
    q = quantize(value, code)
    return f"{q:,.{decimals(code)}f}"


def format_money(value, code: str, symbols: bool = True) -> str:
    q = quantize(value, code)
    body = f"{abs(q):,.{decimals(code)}f}"
    sign = "-" if q < 0 else ""
    sym = CURRENCIES.get(code, ("", 2, None))[2]
    if sym and symbols:
        return f"{sign}{sym}{body}"
    return f"{sign}{code} {body}"


class RateBook:
    """Exchange rates relative to USD, with per-currency manual overrides."""

    def __init__(self, state: dict | None = None):
        self.base: dict[str, float] = dict(DEFAULT_RATES)
        self.manual: dict[str, float] = {}
        self.updated: str = ""
        self.source: str = "built-in"
        if state:
            for k, v in (state.get("base") or {}).items():
                if k in CURRENCIES and float(v) > 0:
                    self.base[k] = float(v)
            for k, v in (state.get("manual") or {}).items():
                if k in CURRENCIES and float(v) > 0:
                    self.manual[k] = float(v)
            self.updated = state.get("updated", "")
            self.source = state.get("source", "built-in")

    def to_state(self) -> dict:
        return {"base": self.base, "manual": self.manual,
                "updated": self.updated, "source": self.source}

    def rate(self, code: str) -> Decimal:
        r = self.manual.get(code) or self.base.get(code) or 1.0
        return Decimal(str(r))

    def origin(self, code: str) -> str:
        if code in self.manual:
            return "manual"
        return "live" if self.source == "live" and code != "USD" else "built-in"

    def convert(self, amount, src: str, dst: str) -> Decimal:
        if src == dst:
            return quantize(amount, dst)
        usd = D(amount) / self.rate(src)
        return quantize(usd * self.rate(dst), dst)

    def apply_live(self, live: dict[str, float]) -> int:
        n = 0
        for k, v in live.items():
            if k in CURRENCIES and v and float(v) > 0:
                self.base[k] = float(v)
                n += 1
        self.base["USD"] = 1.0
        self.updated = time.strftime("%Y-%m-%d %H:%M")
        self.source = "live"
        return n

    def set_manual(self, code: str, rate: float | None) -> None:
        if rate is None or rate <= 0:
            self.manual.pop(code, None)
        else:
            self.manual[code] = float(rate)


def fetch_live_rates(timeout: float = 12.0) -> dict[str, float]:
    """Download current rates (per 1 USD). Raises on any failure."""
    req = urllib.request.Request(RATES_URL, headers={"User-Agent": "InvoiceStudio/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("result") != "success" or "rates" not in payload:
        raise RuntimeError("The rates service returned an unexpected answer.")
    rates = {k: float(v) for k, v in payload["rates"].items() if k in CURRENCIES}
    if not rates:
        raise RuntimeError("No supported currencies in the rates response.")
    return rates
