def _seed(fin):
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "1jt", now="2026-07-01 08:00:00")
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "2jt", now="2026-07-01 08:00:00")
    fin.ok("savings", "add", "tabungan", now="2026-07-01 08:00:00")
    fin.ok("add", "--type", "expense", "--item", "nasi|20k|makan", now="2026-07-31 23:59:59")
    fin.ok("add", "--type", "expense", "--item", "nasi|30k|makan", now="2026-08-01 00:00:00")
    fin.ok("add", "--type", "expense", "--item", "bensin|10k|transport", now="2026-08-31 23:59:59")
    fin.ok("add", "--type", "income", "--account", "bri", "--item", "gajian|600k|gaji", now="2026-08-25 09:00:00")
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "100k", now="2026-08-26 09:00:00")
    fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "50k", "--fee", "2.5k",
           now="2026-09-01 00:00:00")
    fin.ok("add", "--type", "expense", "--item", "kopi|15k|jajan", "--item", "nasi|25k|makan",
           now="2026-10-02 12:00:00")
    fin.ok("adjust", "--account", "tunai", "--actual", "800k", now="2026-10-03 12:00:00")


def test_report_month_and_boundaries(fin):
    _seed(fin)
    aug = fin.ok("report", "--period", "2026-08", "--type", "expense")
    assert aug["data"]["total"] == 40_000 and aug["data"]["count"] == 2
    assert aug["data"]["period"]["start"] == "2026-08-01" and aug["data"]["period"]["end"] == "2026-08-31"
    assert "1–31 Agustus 2026" in aug["message"]
    cats = {c["category"]: c for c in aug["data"]["by_category"]}
    assert cats["makan"]["percent"] == 75.0 and cats["transport"]["percent"] == 25.0
    assert fin.ok("report", "--period", "2026-07")["data"]["total"] == 20_000
    sep = fin.ok("report", "--period", "2026-09")["data"]
    assert sep["total"] == 2_500 and sep["by_category"][0]["category"] == "biaya admin"
    assert fin.ok("report", "--period", "2026-08", "--type", "income")["data"]["total"] == 600_000


def test_report_relative_periods(fin):
    _seed(fin)
    this = fin.ok("report", "--period", "this-month")
    assert this["data"]["total"] == 40_000
    assert "bulan ini (1–6 Oktober 2026)" in this["message"]
    assert fin.ok("report", "--period", "last-month")["data"]["total"] == 2_500
    last3 = fin.ok("report", "--period", "last:3", "--type", "expense")["data"]
    assert last3["period"]["start"] == "2026-08-01" and last3["total"] == 40_000 + 2_500 + 40_000
    allp = fin.ok("report", "--period", "all", "--type", "all")["data"]
    assert allp["period"]["start"] == "2026-07-01"
    assert allp["expense"]["total"] == 102_500 and allp["income"]["total"] == 600_000
    assert allp["net"] == 600_000 - 102_500


def test_report_filters_and_empty(fin):
    _seed(fin)
    r = fin.ok("report", "--period", "all", "--category", "makan")["data"]
    assert r["total"] == 75_000 and r["by_category"][0]["percent"] == 100.0
    assert fin.ok("report", "--period", "all", "--account", "bri")["data"]["total"] == 2_500
    fin.err("UNKNOWN_CATEGORY", "report", "--category", "gajii")
    fin.err("UNKNOWN_ACCOUNT", "report", "--account", "bca")
    empty = fin.ok("report", "--period", "today")
    assert empty["data"]["total"] == 0 and empty["data"]["by_category"] == []
    assert "belum ada transaksi" in empty["message"]
    fin.err("BAD_PERIOD", "report", "--period", "agustus")
    custom = fin.ok("report", "--from", "2026-08-01", "--to", "2026-08-01")["data"]
    assert custom["total"] == 30_000


def test_report_january_last3(fin):
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "1jt", now="2026-10-01 08:00:00")
    fin.ok("add", "--type", "expense", "--item", "a|10k", now="2026-10-31 20:00:00")
    fin.ok("add", "--type", "expense", "--item", "b|20k", now="2026-11-01 08:00:00")
    fin.ok("add", "--type", "expense", "--item", "c|30k", now="2026-12-31 23:00:00")
    fin.ok("add", "--type", "expense", "--item", "d|40k", now="2027-01-01 00:30:00")
    r = fin.ok("report", "--period", "last:3", now="2027-01-15 08:00:00")
    assert r["data"]["total"] == 90_000
    assert "1 November 2026 – 15 Januari 2027" in r["message"]
    r = fin.ok("report", "--period", "last-month", now="2027-01-15 08:00:00")
    assert r["data"]["total"] == 30_000


def test_report_this_week_monday(fin):
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "1jt", now="2026-10-01 08:00:00")
    fin.ok("add", "--type", "expense", "--item", "minggu|10k", now="2026-10-04 23:59:00")
    fin.ok("add", "--type", "expense", "--item", "senin|20k", now="2026-10-05 07:00:00")
    r = fin.ok("report", "--period", "this-week", now="2026-10-05 09:00:00")
    assert r["data"]["total"] == 20_000
    assert r["data"]["period"]["start"] == r["data"]["period"]["end"] == "2026-10-05"
    r = fin.ok("report", "--period", "last-week", now="2026-10-05 09:00:00")
    assert r["data"]["total"] == 10_000
