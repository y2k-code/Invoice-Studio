"""Where things live on disk."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Folder that contains the bundled resources (fonts/...)."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Per-user folder for the database and default backups."""
    override = os.environ.get("INVOICE_STUDIO_HOME")
    if override:
        p = Path(override)
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA") or Path.home()) / "InvoiceStudio"
    else:
        p = Path.home() / ".invoice_studio"
    p.mkdir(parents=True, exist_ok=True)
    return p
