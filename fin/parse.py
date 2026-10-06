"""Parsing nominal, tanggal, dan periode. Semua input dari luar lewat sini."""
import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import clock
from .output import MONTHS, FinError, fmt_range

MAX_AMOUNT = 10**12
AMOUNT_HINT = "Contoh yang sah: 15000, 15.000, 15k, 15rb, 15 ribu, 1,5jt, 2 juta, Rp15.000."

# urutan penting: akhiran yang lebih panjang dicek dulu
_SUFFIXES = [("ribu", 1000), ("juta", 10**6), ("rb", 1000), ("jt", 10**6), ("k", 1000)]


def _bad_amount(raw, field, why=""):
    msg = f"{field.capitalize()} '{raw}' tidak bisa dibaca sebagai rupiah."
    if why:
        msg = f"{field.capitalize()} '{raw}' tidak sah: {why}."
    return FinError("BAD_AMOUNT", msg, hint=AMOUNT_HINT)


def _is_grouped(s):
    """True jika s memakai pemisah ribuan yang rapi, mis. 15.000 atau 1,500,000."""
    seps = set(re.findall(r"[.,]", s))
    if len(seps) != 1:
        return False
    parts = re.split(r"[.,]", s)
    return 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])


def _number(s, suffix, raw, field):
    if s.isdigit():
        return Decimal(s)
    seps = re.findall(r"[.,]", s)
    parts = re.split(r"[.,]", s)
    if any(not p.isdigit() for p in parts):
        raise _bad_amount(raw, field)
    # angka tanpa akhiran: hanya pemisah ribuan, atau ekor ,00 / .00 gaya bank
    if suffix is None:
        if _is_grouped(s):
            return Decimal("".join(parts))
        m = re.fullmatch(r"(.+)([.,])0{1,2}", s)
        if m:
            head, tail_sep = m.group(1), m.group(2)
            if head.isdigit() or (_is_grouped(head) and tail_sep not in head):
                return Decimal(re.sub(r"[.,]", "", head))
        raise _bad_amount(raw, field, "rupiah tidak memakai angka desimal")
    # dengan akhiran juta: satu pemisah selalu desimal (1,250jt = 1.250.000)
    if len(seps) == 1 and suffix in ("jt", "juta"):
        return Decimal(f"{parts[0]}.{parts[1]}")
    if _is_grouped(s):
        return Decimal("".join(parts))
    if len(seps) == 1:
        return Decimal(f"{parts[0]}.{parts[1]}")
    raise _bad_amount(raw, field)


def parse_amount(text, *, allow_zero=False, allow_negative=False, field="jumlah"):
    """Ubah teks nominal menjadi integer rupiah. Lihat AMOUNT_HINT untuk format."""
    if text is None:
        raise FinError("BAD_AMOUNT", f"{field.capitalize()} wajib diisi.", hint=AMOUNT_HINT)
    raw = str(text)
    s = re.sub(r"\s+", "", raw.replace(" ", " ")).lower()
    negative = False
    if s.startswith("-"):
        negative, s = True, s[1:]
    if s.startswith("rp"):
        s = s[2:].lstrip(".")
    if s.startswith("-"):
        negative, s = True, s[1:]
    suffix, mult = None, 1
    for suf, m in _SUFFIXES:
        if s.endswith(suf):
            suffix, mult, s = suf, m, s[: -len(suf)]
            break
    if not s or not re.fullmatch(r"[\d.,]+", s):
        raise _bad_amount(raw, field)
    value = _number(s, suffix, raw, field) * mult
    if value != value.to_integral_value():
        raise _bad_amount(raw, field, "hasilnya bukan rupiah bulat")
    amount = int(value)
    if negative:
        amount = -amount
    if amount == 0 and not allow_zero:
        raise _bad_amount(raw, field, "tidak boleh nol")
    if amount < 0 and not allow_negative:
        raise _bad_amount(raw, field, "tidak boleh negatif")
    if abs(amount) >= MAX_AMOUNT:
        raise _bad_amount(raw, field, "terlalu besar")
    return amount


DATE_HINT = "Pakai YYYY-MM-DD (contoh 2026-10-05), today, atau yesterday."


def parse_day(text, field="tanggal"):
    """Tanggal kalender YYYY-MM-DD tanpa batasan masa depan (untuk target, jatuh tempo)."""
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise FinError("BAD_DATE", f"{field.capitalize()} '{text}' tidak bisa dibaca.",
                       hint="Pakai format YYYY-MM-DD, contoh 2026-12-31.")


def parse_date(text):
    """Nilai --date menjadi timestamp ISO. Tanggal saja diberi jam saat ini."""
    now = clock.now()
    s = str(text).strip().lower()
    if s in ("today", "hari-ini", "hari ini"):
        d, t = now.date(), now.time()
    elif s in ("yesterday", "kemarin"):
        d, t = now.date() - timedelta(days=1), now.time()
    else:
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
        if dt is not None:
            d, t = dt.date(), dt.time()
        else:
            try:
                d = date.fromisoformat(s)
            except ValueError:
                raise FinError("BAD_DATE", f"Tanggal '{text}' tidak bisa dibaca.", hint=DATE_HINT)
            t = now.time()
    result = datetime.combine(d, t)
    if result > now:
        raise FinError("BAD_DATE", f"Tanggal '{text}' ada di masa depan.",
                       hint=f"Hari ini {now.date().isoformat()}. Transaksi tidak boleh bertanggal setelah sekarang.")
    return result.strftime(clock.TS_FORMAT)


PERIOD_HINT = ("Pilihan: today, yesterday, this-week, last-week, this-month, last-month, "
               "YYYY-MM (contoh 2026-08), last:N (contoh last:3), all, atau --from YYYY-MM-DD --to YYYY-MM-DD.")


@dataclass
class Period:
    key: str
    label: str
    start: date
    end: date

    @property
    def text(self):
        return fmt_range(self.start, self.end)

    @property
    def describe(self):
        """'bulan ini (1–6 Oktober 2026)'"""
        return f"{self.label} ({self.text})"

    def bounds(self):
        return f"{self.start.isoformat()} 00:00:00", f"{self.end.isoformat()} 23:59:59"

    def days(self):
        return (self.end - self.start).days + 1

    def to_dict(self):
        return {"key": self.key, "label": self.label, "start": self.start.isoformat(),
                "end": self.end.isoformat(), "text": self.text}


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _period_day(text, field):
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise FinError("BAD_PERIOD", f"Tanggal {field} '{text}' tidak bisa dibaca.",
                       hint="Pakai format YYYY-MM-DD, contoh --from 2026-08-01 --to 2026-08-31.")


def parse_period(period=None, date_from=None, date_to=None, earliest=None):
    """Ubah --period / --from / --to menjadi Period. Akhir periode tidak melewati hari ini.

    earliest: tanggal transaksi paling awal (untuk 'all'), boleh None.
    """
    today = clock.today()
    if date_from or date_to:
        if period:
            raise FinError("BAD_ARGS", "Pakai --period atau --from/--to, jangan keduanya.", hint=PERIOD_HINT)
        if not date_from:
            raise FinError("BAD_PERIOD", "--to harus disertai --from.", hint=PERIOD_HINT)
        start = _period_day(date_from, "--from")
        end = _period_day(date_to, "--to") if date_to else today
        if start > end:
            raise FinError("BAD_PERIOD", "Tanggal --from lebih besar dari --to.", hint=PERIOD_HINT)
        if start > today:
            raise FinError("BAD_PERIOD", "Periode ada di masa depan.", hint=PERIOD_HINT)
        return Period("custom", "periode", start, min(end, today))

    p = (period or "this-month").strip().lower()
    if p == "today":
        return Period(p, "hari ini", today, today)
    if p == "yesterday":
        d = today - timedelta(days=1)
        return Period(p, "kemarin", d, d)
    if p == "this-week":
        return Period(p, "minggu ini", today - timedelta(days=today.weekday()), today)
    if p == "last-week":
        start = today - timedelta(days=today.weekday() + 7)
        return Period(p, "minggu lalu", start, start + timedelta(days=6))
    if p == "this-month":
        return Period(p, "bulan ini", today.replace(day=1), today)
    if p == "last-month":
        end = today.replace(day=1) - timedelta(days=1)
        return Period(p, "bulan lalu", end.replace(day=1), end)
    if p == "all":
        start = min(earliest, today) if earliest else today
        return Period(p, "semua waktu", start, today)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", p)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            raise FinError("BAD_PERIOD", f"Bulan '{period}' tidak sah.", hint=PERIOD_HINT)
        start = date(y, mo, 1)
        if start > today:
            raise FinError("BAD_PERIOD", f"Bulan {MONTHS[mo - 1]} {y} belum terjadi.", hint=PERIOD_HINT)
        end = date(y, mo, calendar.monthrange(y, mo)[1])
        return Period(f"{y:04d}-{mo:02d}", f"{MONTHS[mo - 1]} {y}", start, min(end, today))
    m = re.fullmatch(r"last:(\d+)", p)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= 120:
            raise FinError("BAD_PERIOD", "Nilai N pada last:N harus 1 sampai 120.", hint=PERIOD_HINT)
        start = add_months(today.replace(day=1), -(n - 1))
        return Period(p, f"{n} bulan terakhir", start, today)
    raise FinError("BAD_PERIOD", f"Periode '{period}' tidak dikenal.", hint=PERIOD_HINT)
