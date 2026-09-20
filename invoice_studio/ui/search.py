"""Tiny ranked search used for the 'suggested' dropdowns and list filters."""
from __future__ import annotations

import difflib
import re
from typing import Callable, Iterable, Sequence

_WORD = re.compile(r"[\w']+", re.UNICODE)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


def _token_score(token: str, text: str, words: list[str]) -> float:
    if text.startswith(token):
        return 10.0
    if any(w.startswith(token) for w in words):
        return 7.0
    if token in text:
        return 4.0
    if len(token) >= 3 and _subsequence(token, text.replace(" ", "")):
        return 1.5
    if len(token) >= 4:
        for w in words:
            if abs(len(w) - len(token)) <= 2 and difflib.SequenceMatcher(None, token, w).ratio() >= 0.8:
                return 2.0
    return 0.0


def score(query: str, fields: Sequence[str]) -> float:
    """0 means no match. Every query word must match at least one field."""
    tokens = _words(query)
    if not tokens:
        return 1.0
    prepared = [(f.lower(), _words(f)) for f in fields if f]
    if not prepared:
        return 0.0
    total = 0.0
    for tok in tokens:
        best = 0.0
        for i, (text, words) in enumerate(prepared):
            s = _token_score(tok, text, words)
            if s and i == 0:
                s += 1.0  # first field (usually the name) counts a bit more
            best = max(best, s)
        if best == 0.0:
            return 0.0
        total += best
    return total


def rank(query: str, rows: Iterable[dict], keys: Sequence[str], limit: int | None = 8,
         boost: Callable[[dict], float] | None = None) -> list[dict]:
    """Return matching rows, best first. Empty query returns the most-used rows."""
    scored = []
    for idx, row in enumerate(rows):
        s = score(query, [str(row.get(k, "") or "") for k in keys])
        if s <= 0:
            continue
        b = boost(row) if boost else 0.0
        scored.append((s + b, -idx, row))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    out = [r for _, _, r in scored]
    return out if limit is None else out[:limit]


def usage_boost(row: dict) -> float:
    """Frequently used records float up; capped so relevance still wins."""
    try:
        uses = int(row.get("use_count") or 0)
    except (TypeError, ValueError):
        uses = 0
    return min(uses, 20) * 0.15
