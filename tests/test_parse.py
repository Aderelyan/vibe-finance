from datetime import date

import pytest

from fin import clock
from fin.output import FinError, fmt_range, rupiah
from fin.parse import parse_amount, parse_date, parse_period


@pytest.mark.parametrize("text, expected", [
    ("15k", 15_000), ("15K", 15_000), ("15rb", 15_000), ("15 ribu", 15_000), ("15ribu", 15_000),
    ("1,5jt", 1_500_000), ("1.5jt", 1_500_000), ("2 juta", 2_000_000), ("2jt", 2_000_000),
    ("1,25jt", 1_250_000), ("1,250jt", 1_250_000), ("2.5k", 2_500), ("2,5k", 2_500), ("1.500rb", 1_500_000),
    ("15.000", 15_000), ("15,000", 15_000), ("15000", 15_000), ("1.500.000", 1_500_000),
    ("Rp15.000", 15_000), ("rp 15.000", 15_000), ("Rp. 15.000", 15_000), ("RP15000", 15_000),
    ("Rp15.000,00", 15_000), ("  20k  ", 20_000), ("500", 500), ("1.000.000,00", 1_000_000),
])
def test_parse_amount_valid(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", [
    "0", "0k", "-5k", "-15000", "abc", "", "   ", "15.5", "15,50", "1.2345k", "k", "rp", "15kk",
    "15.00.0", "1.5.000", "15 000x", "10^3", "1e5", "15.000,50", None, "12,3456",
])
def test_parse_amount_invalid(text):
    with pytest.raises(FinError) as e:
        parse_amount(text)
    assert e.value.code == "BAD_AMOUNT"
    assert e.value.hint


def test_parse_amount_signed_and_zero():
    assert parse_amount("0", allow_zero=True) == 0
    assert parse_amount("-50k", allow_negative=True) == -50_000
    assert parse_amount("Rp-50.000", allow_negative=True) == -50_000


def test_rupiah_format():
    assert rupiah(15000) == "Rp15.000"
    assert rupiah(0) == "Rp0"
    assert rupiah(-2500) == "-Rp2.500"
    assert rupiah(1234567) == "Rp1.234.567"


@pytest.fixture
def now():
    def set_now(text):
        clock.set_override(text)
    yield set_now
    clock.set_override(None)


def test_parse_date(now):
    now("2026-10-06 14:30:00")
    assert parse_date("today") == "2026-10-06 14:30:00"
    assert parse_date("yesterday") == "2026-10-05 14:30:00"
    assert parse_date("2026-09-01") == "2026-09-01 14:30:00"
    assert parse_date("2026-09-01 08:15") == "2026-09-01 08:15:00"
    for bad in ("2026-10-07", "2026-10-06 15:00", "besok", "06/10/2026", "2026-02-30"):
        with pytest.raises(FinError) as e:
            parse_date(bad)
        assert e.value.code == "BAD_DATE"


def _p(*args, **kw):
    p = parse_period(*args, **kw)
    return p.start, p.end


def test_period_month_boundaries(now):
    now("2026-10-31 23:00:00")
    assert _p("this-month") == (date(2026, 10, 1), date(2026, 10, 31))
    assert _p("last-month") == (date(2026, 9, 1), date(2026, 9, 30))
    assert _p("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert _p("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    now("2026-10-01 00:05:00")
    assert _p("this-month") == (date(2026, 10, 1), date(2026, 10, 1))
    assert _p("yesterday") == (date(2026, 9, 30), date(2026, 9, 30))
    # bulan berjalan dipotong sampai hari ini
    assert _p("2026-10") == (date(2026, 10, 1), date(2026, 10, 1))


def test_period_year_change(now):
    now("2027-01-01 09:00:00")
    assert _p("last-month") == (date(2026, 12, 1), date(2026, 12, 31))
    assert _p("yesterday") == (date(2026, 12, 31), date(2026, 12, 31))
    assert _p("last:3") == (date(2026, 11, 1), date(2027, 1, 1))
    now("2027-01-20 09:00:00")
    assert _p("last:3") == (date(2026, 11, 1), date(2027, 1, 20))
    assert _p("last:1") == (date(2027, 1, 1), date(2027, 1, 20))
    assert _p("last:13") == (date(2026, 1, 1), date(2027, 1, 20))


def test_period_weeks(now):
    now("2026-10-05 08:00:00")  # Senin
    assert _p("this-week") == (date(2026, 10, 5), date(2026, 10, 5))
    assert _p("last-week") == (date(2026, 9, 28), date(2026, 10, 4))
    now("2026-10-11 08:00:00")  # Minggu
    assert _p("this-week") == (date(2026, 10, 5), date(2026, 10, 11))


def test_period_custom_and_all(now):
    now("2026-10-06 08:00:00")
    assert _p(None, "2026-08-15", "2026-09-02") == (date(2026, 8, 15), date(2026, 9, 2))
    assert _p(None, "2026-10-01", "2026-12-31") == (date(2026, 10, 1), date(2026, 10, 6))
    assert _p("all", earliest=date(2026, 3, 4)) == (date(2026, 3, 4), date(2026, 10, 6))
    assert _p("all") == (date(2026, 10, 6), date(2026, 10, 6))
    assert _p(None) == (date(2026, 10, 1), date(2026, 10, 6))  # bawaan this-month


@pytest.mark.parametrize("args, code", [
    (("bulan-ini",), "BAD_PERIOD"), (("2026-13",), "BAD_PERIOD"), (("2026-11",), "BAD_PERIOD"),
    (("last:0",), "BAD_PERIOD"), (("last:abc",), "BAD_PERIOD"), ((None, "2026-09-10", "2026-09-01"), "BAD_PERIOD"),
    ((None, None, "2026-09-01"), "BAD_PERIOD"), ((None, "kemarin"), "BAD_PERIOD"),
    (("this-month", "2026-09-01"), "BAD_ARGS"),
])
def test_period_invalid(now, args, code):
    now("2026-10-06 08:00:00")
    with pytest.raises(FinError) as e:
        parse_period(*args)
    assert e.value.code == code


def test_fmt_range():
    assert fmt_range(date(2026, 10, 1), date(2026, 10, 6)) == "1–6 Oktober 2026"
    assert fmt_range(date(2026, 8, 1), date(2026, 10, 6)) == "1 Agustus – 6 Oktober 2026"
    assert fmt_range(date(2026, 11, 1), date(2027, 1, 5)) == "1 November 2026 – 5 Januari 2027"
    assert fmt_range(date(2026, 10, 6), date(2026, 10, 6)) == "6 Oktober 2026"
