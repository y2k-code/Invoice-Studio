"""Invoice Studio - launch with:  python main.py"""
import os
import sys


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main() -> None:
    _enable_dpi_awareness()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("Tkinter is missing. Re-install Python from python.org and keep 'tcl/tk and IDLE' ticked.")
    from invoice_studio.ui.app import InvoiceStudio
    InvoiceStudio().mainloop()


if __name__ == "__main__":
    main()
