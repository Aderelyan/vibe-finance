"""Tagihan rutin: tambah, daftar, bayar, undo/hapus pembayaran, ubah, ganti nama, hapus."""


def rec(fin, name, all_=False):
    args = ["recurring", "list"] + (["--all"] if all_ else [])
    return next((r for r in fin.ok(*args)["data"]["recurring"] if r["name"] == name), None)


def test_add_guesses_category_and_lists_status(wallets):
    fin = wallets
    r = fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5", "--account", "bri")
    assert r["data"]["recurring"]["category"] == "tempat tinggal" and "ditebak" in r["message"]
    r = fin.ok("recurring", "add", "iuran RT", "--amount", "20k", "--day", "10")
    assert r["data"]["recurring"]["category"] == "tagihan"  # tidak ada kata kunci: bawaan tagihan
    r = fin.ok("recurring", "add", "spotify", "--amount", "55k", "--day", "20", "--category", "hiburan")
    assert r["data"]["recurring"]["category"] == "hiburan"

    data = fin.ok("recurring", "list")["data"]
    assert data["monthly_total"] == 575_000 and data["unpaid_count"] == 3
    kos = rec(fin, "kos")
    assert kos["this_month"] == {"month": "2026-10", "due_date": "2026-10-05", "paid": False, "days_until_due": -1}
    assert "lewat 1 hari" in fin.ok("recurring", "list")["message"]


def test_bad_input(wallets):
    fin = wallets
    fin.err("BAD_ARGS", "recurring", "add", "kos", "--amount", "500k", "--day", "32")
    fin.err("BAD_ARGS", "recurring", "add", "kos", "--amount", "500k", "--day", "lima")
    fin.err("BAD_AMOUNT", "recurring", "add", "kos", "--amount", "0", "--day", "5")
    fin.err("UNKNOWN_CATEGORY", "recurring", "add", "kos", "--amount", "500k", "--day", "5", "--category", "gaji")
    fin.err("UNKNOWN_ACCOUNT", "recurring", "add", "kos", "--amount", "500k", "--day", "5", "--account", "bca")
    fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5")
    r = fin.err("BAD_ARGS", "recurring", "add", "Kos", "--amount", "600k", "--day", "5")
    assert "recurring set" in r["error"]["hint"]
    r = fin.err("NOT_FOUND", "recurring", "pay", "wifi")
    assert "kos" in r["error"]["hint"]


def test_pay_records_expense_and_marks_month(wallets):
    fin = wallets
    fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5", "--account", "bri")
    fin.ok("budget", "alloc", "--item", "tempat tinggal|500k")
    r = fin.ok("recurring", "pay", "kos")
    assert r["data"]["month"] == "2026-10" and r["data"]["amount"] == 500_000
    assert r["data"]["account"] == "bri" and r["data"]["budget"] == "tempat tinggal"
    assert r["data"]["budget_balance"] == 0 and fin.balance("bri") == 0
    assert rec(fin, "kos")["this_month"]["paid"] is True
    assert rec(fin, "kos")["last_paid_month"] == "2026-10"
    rep = fin.ok("report", "--period", "this-month", "--type", "expense")["data"]
    assert rep["total"] == 500_000

    n = fin.count_tx()
    r = fin.err("BAD_ARGS", "recurring", "pay", "kos")
    assert "sudah dibayar" in r["error"]["message"]
    assert fin.count_tx() == n

    # bayar bulan depan di muka, nominal berbeda, dari dompet lain
    r = fin.ok("recurring", "pay", "kos", "--month", "2026-11", "--amount", "450k", "--account", "tunai")
    assert r["data"]["month"] == "2026-11" and "Biasanya Rp500.000" in r["message"]
    assert rec(fin, "kos")["last_paid_month"] == "2026-11"
    fin.err("BAD_DATE", "recurring", "pay", "kos", "--month", "2026-13")


def test_pay_late_for_previous_month(wallets):
    fin = wallets
    fin.ok("recurring", "add", "listrik", "--amount", "100k", "--day", "28")
    r = fin.ok("recurring", "pay", "listrik", "--month", "2026-09")
    assert r["data"]["month"] == "2026-09"
    assert rec(fin, "listrik")["this_month"]["paid"] is False
    # tanpa --month, bulan tagihan = bulan tanggal bayar (September, sudah dibayar)
    fin.err("BAD_ARGS", "recurring", "pay", "listrik", "--date", "2026-09-30")
    r = fin.ok("recurring", "pay", "listrik", "--date", "2026-10-01")
    assert r["data"]["month"] == "2026-10" and "Tanggal: 1 Oktober 2026" in r["message"]


def test_undo_and_delete_reset_last_paid(wallets):
    fin = wallets
    fin.ok("recurring", "add", "wifi", "--amount", "300k", "--day", "15")
    fin.ok("recurring", "pay", "wifi", "--month", "2026-09")
    fin.ok("recurring", "pay", "wifi")
    assert rec(fin, "wifi")["last_paid_month"] == "2026-10"
    r = fin.ok("undo")
    assert r["data"]["action"] == "recurring_pay"
    assert rec(fin, "wifi")["last_paid_month"] == "2026-09"
    assert rec(fin, "wifi")["this_month"]["paid"] is False
    tx = fin.ok("list", "--period", "this-month", "--search", "wifi")["data"]["transactions"][0]
    fin.ok("delete", str(tx["id"]))
    assert rec(fin, "wifi")["last_paid_month"] is None
    fin.ok("recurring", "pay", "wifi")  # boleh dibayar lagi
    assert rec(fin, "wifi")["last_paid_month"] == "2026-10"


def test_day_31_in_short_month(wallets):
    fin = wallets
    fin.ok("recurring", "add", "listrik", "--amount", "100k", "--day", "31")
    item = fin.ok("recurring", "list", now="2027-02-10 09:00:00")["data"]["recurring"][0]
    assert item["this_month"]["due_date"] == "2027-02-28"


def test_set_rename(wallets):
    fin = wallets
    fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5")
    r = fin.ok("recurring", "set", "kos", "--amount", "550k", "--day", "1", "--account", "bri")
    assert r["data"]["recurring"]["amount"] == 550_000 and r["data"]["recurring"]["day"] == 1
    assert r["data"]["recurring"]["account"] == "bri"
    fin.err("BAD_ARGS", "recurring", "set", "kos")
    fin.ok("recurring", "add", "wifi", "--amount", "300k", "--day", "15")
    fin.err("BAD_ARGS", "recurring", "rename", "kos", "WIFI")
    r = fin.ok("recurring", "rename", "kos", "kontrakan")
    assert rec(fin, "kontrakan")["amount"] == 550_000 and rec(fin, "kos") is None


def test_archived_account_or_category(wallets):
    fin = wallets
    fin.ok("category", "add", "kucing", "--kind", "expense")
    fin.ok("recurring", "add", "pasir kucing", "--amount", "50k", "--day", "1", "--category", "kucing",
           "--account", "gopay")
    fin.ok("account", "remove", "gopay", "--move-to", "bri")
    r = fin.err("UNKNOWN_ACCOUNT", "recurring", "pay", "pasir kucing")
    assert "recurring set" in r["error"]["hint"]
    fin.ok("recurring", "set", "pasir kucing", "--account", "tunai")
    r = fin.ok("category", "remove", "kucing", "--kind", "expense")
    assert r["data"]["mode"] == "archived"  # dipakai tagihan rutin
    fin.err("UNKNOWN_CATEGORY", "recurring", "pay", "pasir kucing")
    fin.ok("recurring", "set", "pasir kucing", "--category", "belanja")
    assert fin.ok("recurring", "pay", "pasir kucing")["data"]["category"] == "belanja"


def test_remove_and_reactivate(wallets):
    fin = wallets
    fin.ok("recurring", "add", "netflix", "--amount", "50k", "--day", "3")
    r = fin.ok("recurring", "remove", "netflix")
    assert r["data"]["mode"] == "deleted"
    assert rec(fin, "netflix", all_=True) is None

    fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5")
    fin.ok("recurring", "pay", "kos")
    r = fin.ok("recurring", "remove", "kos")
    assert r["data"]["mode"] == "archived"
    assert rec(fin, "kos") is None and rec(fin, "kos", all_=True)["archived"] is True
    r = fin.err("NOT_FOUND", "recurring", "pay", "kos")
    assert "recurring add" in r["error"]["hint"]
    # transaksinya tetap ada
    assert fin.ok("report", "--period", "this-month")["data"]["total"] == 500_000

    r = fin.ok("recurring", "add", "kos", "--amount", "600k", "--day", "7")
    assert r["data"]["reactivated"] is True
    item = rec(fin, "kos")
    assert item["amount"] == 600_000 and item["this_month"]["paid"] is True
