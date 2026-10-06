"""Sumber waktu "sekarang". Bisa dipalsukan lewat --now atau env FINANCE_NOW."""
import os
from datetime import datetime

from .output import FinError

TS_FORMAT = "%Y-%m-%d %H:%M:%S"

_override = None


def _parse(text):
    text = text.strip()
    for fmt in (TS_FORMAT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise FinError("BAD_DATE", f"Nilai --now '{text}' tidak bisa dibaca.",
                   hint='Format: "YYYY-MM-DD HH:MM:SS", contoh "2026-10-06 14:30:00".')


def set_override(text):
    global _override
    _override = _parse(text) if text else None


def now():
    if _override is not None:
        return _override
    env = os.environ.get("FINANCE_NOW")
    if env:
        return _parse(env)
    return datetime.now().replace(microsecond=0)


def now_ts():
    return now().strftime(TS_FORMAT)


def today():
    return now().date()
