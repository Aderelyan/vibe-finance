"""Pembungkus JSON, format rupiah, dan format tanggal untuk pesan."""
import json
from datetime import date, datetime

MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember"]

ERROR_CODES = {
    "UNKNOWN_ACCOUNT", "UNKNOWN_CATEGORY", "BAD_AMOUNT", "BAD_DATE", "BAD_PERIOD",
    "NOT_FOUND", "NO_DEFAULT_ACCOUNT", "AMBIGUOUS_DEBT", "OVERPAYMENT",
    "NOTHING_TO_UNDO", "BAD_ARGS", "INTERNAL",
}


class FinError(Exception):
    """Kesalahan yang sudah diketahui. Selalu berakhir sebagai JSON ok=false."""

    def __init__(self, code, message, hint=None, data=None):
        assert code in ERROR_CODES, code
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.data = data


def success(message, data=None):
    return {"ok": True, "message": message, "data": data if data is not None else {}}


def failure(err):
    body = {"code": err.code, "message": err.message, "hint": err.hint}
    if err.data is not None:
        body["data"] = err.data
    return {"ok": False, "error": body}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def rupiah(n):
    sign = "-" if n < 0 else ""
    return f"{sign}Rp{abs(n):,}".replace(",", ".")


def signed_rupiah(n):
    return ("+" if n > 0 else "") + rupiah(n)


def percent(part, whole):
    """Persen dengan satu desimal. Aman untuk whole = 0."""
    if not whole:
        return 0.0
    return round(part * 100 / whole, 1)


def fmt_pct(p):
    return f"{p:.1f}".replace(".", ",") + "%"


def _as_date(d):
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    return d


def fmt_date(d):
    d = _as_date(d)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_range(start, end):
    s, e = _as_date(start), _as_date(end)
    if s == e:
        return fmt_date(s)
    if (s.year, s.month) == (e.year, e.month):
        return f"{s.day}–{e.day} {MONTHS[s.month - 1]} {s.year}"
    if s.year == e.year:
        return f"{s.day} {MONTHS[s.month - 1]} – {e.day} {MONTHS[e.month - 1]} {s.year}"
    return f"{fmt_date(s)} – {fmt_date(e)}"


def fmt_ts(ts):
    """'2026-10-06 14:30:00' -> '06/10/2026 14:30'"""
    return f"{ts[8:10]}/{ts[5:7]}/{ts[0:4]} {ts[11:16]}"
