"""SQLite storage: settings, clients, items, invoices, backups."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    company TEXT DEFAULT '', email TEXT DEFAULT '', phone TEXT DEFAULT '',
    address TEXT DEFAULT '', tax_id TEXT DEFAULT '', currency TEXT DEFAULT '',
    notes TEXT DEFAULT '', use_count INTEGER DEFAULT 0, last_used TEXT DEFAULT '',
    created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    unit TEXT DEFAULT '', price TEXT DEFAULT '0', currency TEXT DEFAULT 'USD',
    notes TEXT DEFAULT '', use_count INTEGER DEFAULT 0, last_used TEXT DEFAULT '',
    created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_type TEXT NOT NULL, status TEXT NOT NULL,
    number TEXT NOT NULL, client_name TEXT DEFAULT '', currency TEXT NOT NULL,
    issue_date TEXT DEFAULT '', due_date TEXT DEFAULT '', total TEXT DEFAULT '0',
    paid TEXT DEFAULT '0', data TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(doc_type, number);
"""

REQUIRED_TABLES = {"settings", "clients", "items", "invoices"}
BACKUP_PREFIX = "InvoiceStudio_"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.dirty = False  # unsaved-to-backup changes
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:
            pass

    def _touch(self) -> None:
        self.conn.commit()
        self.dirty = True

    # ------------------------------------------------------------ settings
    def get_json(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set_json(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)))
        self._touch()

    # ------------------------------------------------------------ images (stored inside the db so backups are complete)
    def set_image(self, name: str, png_bytes: bytes | None) -> None:
        if png_bytes is None:
            self.conn.execute("DELETE FROM settings WHERE key=?", (f"img:{name}",))
            self._touch()
        else:
            self.set_json(f"img:{name}", base64.b64encode(png_bytes).decode("ascii"))

    def get_image(self, name: str):
        data = self.get_json(f"img:{name}")
        if not data:
            return None
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(base64.b64decode(data)))
            img.load()
            return img.convert("RGBA")
        except Exception:
            return None

    # ------------------------------------------------------------ clients
    def all_clients(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM clients ORDER BY name COLLATE NOCASE")]

    def get_client(self, cid: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def save_client(self, c: dict) -> int:
        cols = ("name", "company", "email", "phone", "address", "tax_id", "currency", "notes")
        vals = [str(c.get(k, "") or "").strip() if k != "address" else str(c.get(k, "") or "").strip() for k in cols]
        if c.get("id"):
            self.conn.execute(f"UPDATE clients SET {', '.join(k + '=?' for k in cols)} WHERE id=?", (*vals, c["id"]))
            cid = int(c["id"])
        else:
            cur = self.conn.execute(
                f"INSERT INTO clients({', '.join(cols)}, created) VALUES({', '.join('?' * len(cols))}, ?)",
                (*vals, _now()))
            cid = int(cur.lastrowid)
        self._touch()
        return cid

    def delete_client(self, cid: int) -> None:
        self.conn.execute("DELETE FROM clients WHERE id=?", (cid,))
        self._touch()

    def bump_client(self, cid: int) -> None:
        self.conn.execute("UPDATE clients SET use_count=use_count+1, last_used=? WHERE id=?", (_now(), cid))
        self._touch()

    # ------------------------------------------------------------ items
    def all_items(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM items ORDER BY name COLLATE NOCASE")]

    def get_item(self, iid: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        return dict(r) if r else None

    def find_item_by_name(self, name: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM items WHERE lower(name)=lower(?)", (name.strip(),)).fetchone()
        return dict(r) if r else None

    def save_item(self, it: dict) -> int:
        cols = ("name", "unit", "price", "currency", "notes")
        vals = [str(it.get(k, "") or "").strip() for k in cols]
        if not vals[2]:
            vals[2] = "0"
        if it.get("id"):
            self.conn.execute(f"UPDATE items SET {', '.join(k + '=?' for k in cols)} WHERE id=?", (*vals, it["id"]))
            iid = int(it["id"])
        else:
            cur = self.conn.execute(
                f"INSERT INTO items({', '.join(cols)}, created) VALUES({', '.join('?' * len(cols))}, ?)",
                (*vals, _now()))
            iid = int(cur.lastrowid)
        self._touch()
        return iid

    def delete_item(self, iid: int) -> None:
        self.conn.execute("DELETE FROM items WHERE id=?", (iid,))
        self._touch()

    def bump_item(self, iid: int) -> None:
        self.conn.execute("UPDATE items SET use_count=use_count+1, last_used=? WHERE id=?", (_now(), iid))
        self._touch()

    # ------------------------------------------------------------ invoices
    def save_invoice(self, inv: dict, total, paid) -> int:
        client = inv.get("client", {})
        client_name = (client.get("company") or client.get("name") or "").strip()
        payload = {k: v for k, v in inv.items() if k != "id"}
        blob = json.dumps(payload)
        row = (inv.get("doc_type", "invoice"), inv.get("status", "draft"), inv.get("number", ""),
               client_name, inv.get("currency", "USD"), inv.get("issue_date", ""), inv.get("due_date", ""),
               str(total), str(paid), blob, _now())
        if inv.get("id"):
            self.conn.execute(
                "UPDATE invoices SET doc_type=?, status=?, number=?, client_name=?, currency=?, issue_date=?, "
                "due_date=?, total=?, paid=?, data=?, updated=? WHERE id=?", (*row, inv["id"]))
            iid = int(inv["id"])
        else:
            cur = self.conn.execute(
                "INSERT INTO invoices(doc_type, status, number, client_name, currency, issue_date, due_date, "
                "total, paid, data, updated, created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*row, _now()))
            iid = int(cur.lastrowid)
        self._touch()
        return iid

    def get_invoice(self, iid: int) -> dict | None:
        r = self.conn.execute("SELECT id, data FROM invoices WHERE id=?", (iid,)).fetchone()
        if not r:
            return None
        inv = json.loads(r["data"])
        inv["id"] = int(r["id"])
        return inv

    def list_invoices(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, doc_type, status, number, client_name, currency, issue_date, due_date, total, paid, updated "
            "FROM invoices ORDER BY updated DESC, id DESC")
        return [dict(r) for r in rows]

    def delete_invoice(self, iid: int) -> None:
        self.conn.execute("DELETE FROM invoices WHERE id=?", (iid,))
        self._touch()

    def numbers(self, doc_type: str) -> list[str]:
        return [r["number"] for r in self.conn.execute("SELECT number FROM invoices WHERE doc_type=?", (doc_type,))]

    def number_taken(self, doc_type: str, number: str, exclude_id: int | None = None) -> bool:
        r = self.conn.execute(
            "SELECT id FROM invoices WHERE doc_type=? AND number=? AND id<>?",
            (doc_type, number, exclude_id or -1)).fetchone()
        return r is not None

    # ------------------------------------------------------------ backups
    def backup_to(self, folder: Path, keep: int = 30, tag: str = "") -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.conn.commit()
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = folder / f"{BACKUP_PREFIX}{stamp}{tag}.db"
        n = 1
        while dest.exists():  # two backups within one second
            dest = folder / f"{BACKUP_PREFIX}{stamp}{tag}_{n}.db"
            n += 1
        out = sqlite3.connect(str(dest))
        try:
            self.conn.backup(out)
        finally:
            out.close()
        self.dirty = False
        self.prune_backups(folder, keep)
        return dest

    @staticmethod
    def list_backups(folder: Path) -> list[Path]:
        folder = Path(folder)
        if not folder.exists():
            return []
        return sorted(folder.glob(f"{BACKUP_PREFIX}*.db"), reverse=True)

    def prune_backups(self, folder: Path, keep: int) -> None:
        files = self.list_backups(folder)
        for old in files[max(1, keep):]:
            try:
                old.unlink()
            except OSError:
                pass

    @staticmethod
    def is_valid_backup(path: Path) -> bool:
        try:
            con = sqlite3.connect(str(path))
            try:
                names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
            return REQUIRED_TABLES <= names
        except sqlite3.Error:
            return False

    def restore_from(self, path: Path, safety_folder: Path) -> None:
        """Replace the live data with a backup (a safety copy of the current data is made first)."""
        if not self.is_valid_backup(path):
            raise ValueError("That file is not an Invoice Studio backup.")
        self.backup_to(safety_folder, keep=10_000, tag="_before-restore")
        src = sqlite3.connect(str(path))
        try:
            src.backup(self.conn)
        finally:
            src.close()
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.dirty = True
