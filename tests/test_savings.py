def test_savings_lifecycle(fin):
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "1jt")
    r = fin.ok("savings", "add", "dana darurat", "--target", "5jt", "--target-date", "2027-06-30")
    assert r["data"]["target_amount"] == 5_000_000
    fin.ok("savings", "add", "laptop", "--target", "8jt")
    fin.err("BAD_ARGS", "savings", "add", "Laptop")
    fin.err("BAD_ARGS", "savings", "add", "makan")  # bentrok dengan kategori pengeluaran
    fin.err("SYSTEM_PROTECTED", "savings", "add", "belum teralokasi")
    fin.err("BAD_DATE", "savings", "add", "liburan", "--target-date", "30-06-2027")

    fin.ok("budget", "alloc", "--item", "dana darurat|500k", "--item", "laptop|200k")
    fin.ok("budget", "move", "--from", "laptop", "--to", "dana darurat", "--amount", "50k")
    data = fin.ok("savings", "list")["data"]
    dd = data["savings"][0]
    assert dd["balance"] == 550_000 and dd["percent"] == 11.0 and dd["shortfall"] == 4_450_000
    assert dd["month_change"] == 550_000 and data["savings"][1]["month_change"] == 150_000
    assert data["total"] == 700_000
    # menabung tidak mengurangi total uang dan bukan pengeluaran
    bal = fin.ok("balance")["data"]
    assert bal["total_dompet"] == 1_000_000 and bal["savings_total"] == 700_000
    assert bal["non_savings_total"] == 300_000
    assert fin.ok("report", "--type", "all")["data"]["expense"]["total"] == 0

    r = fin.ok("savings", "set-target", "laptop", "--target", "6jt")
    assert r["data"]["target_amount"] == 6_000_000
    assert fin.ok("savings", "set-target", "laptop", "--clear")["data"]["target_amount"] is None
    fin.err("BAD_ARGS", "savings", "set-target", "laptop")
    fin.ok("savings", "rename", "laptop", "laptop baru")
    fin.err("UNKNOWN_BUDGET", "savings", "rename", "laptop", "x")


def test_savings_remove_returns_leftover(fin):
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "1jt")
    fin.ok("savings", "add", "kosong")
    r = fin.ok("savings", "remove", "kosong")
    assert r["data"]["mode"] == "deleted"

    fin.ok("savings", "add", "laptop")
    fin.ok("budget", "alloc", "--item", "laptop|300k")
    r = fin.ok("savings", "remove", "laptop")
    assert r["data"]["returned"] == 300_000 and r["data"]["mode"] == "archived"
    unalloc = fin.ok("budget", "list")["data"]["budgets"][0]["balance"]
    assert unalloc == 1_000_000
    fin.err("UNKNOWN_BUDGET", "savings", "remove", "laptop")
    fin.err("UNKNOWN_BUDGET", "budget", "alloc", "--item", "laptop|10k")

    # sisa minus: belanja langsung dari tabungan melebihi isinya
    fin.ok("savings", "add", "liburan")
    fin.ok("budget", "alloc", "--item", "liburan|100k")
    fin.ok("add", "--type", "expense", "--budget", "liburan", "--item", "tiket|150k|transport")
    r = fin.ok("savings", "remove", "liburan")
    assert r["data"]["returned"] == -50_000 and "minus" in r["message"]
    assert fin.ok("budget", "list")["data"]["budgets"][0]["balance"] == 1_000_000 - 150_000

    # undo mengaktifkan kembali tabungan beserta isinya
    r = fin.ok("undo")
    assert r["data"]["restored"][0]["name"] == "liburan"
    assert fin.ok("savings", "list")["data"]["savings"][0]["balance"] == -50_000

    # tambah lagi dengan nama yang sama: aktif kembali
    r = fin.ok("savings", "add", "laptop", "--target", "9jt")
    assert r["data"]["reactivated"] is True and r["data"]["balance"] == 0
