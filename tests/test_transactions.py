import sqlite3


def test_add_single_and_guess(wallets):
    fin = wallets
    r = fin.ok("add", "--type", "expense", "--item", "ayam goreng|15k|makan")
    assert r["data"]["items"][0]["category_source"] == "given"
    assert "makan" in r["message"] and "tunai" in r["message"] and "dompet default" in r["message"]
    assert "Rp135.000" in r["message"]
    r = fin.ok("add", "--type", "expense", "--item", "bensin motor|20rb")
    assert r["data"]["items"][0]["category"] == "transport"
    assert "bensin" in r["message"]
    r = fin.ok("add", "--type", "expense", "--item", "sesuatu|5k")
    assert r["data"]["items"][0]["category"] == "lainnya"
    assert "lainnya" in r["message"]
    r = fin.ok("add", "--type", "income", "--account", "bri", "--item", "gajian bulan ini|600k")
    assert r["data"]["items"][0]["category"] == "gaji"
    assert fin.balance("bri") == 1_100_000


def test_add_multi_atomic(wallets):
    fin = wallets
    before = fin.count_tx()
    r = fin.ok("add", "--type", "expense", "--item", "jajan|10k|jajan", "--item", "es teh|3k|jajan",
               "--raw", "jajan 10k dan es teh 3k")
    assert r["data"]["total"] == 13_000
    ids = [i["id"] for i in r["data"]["items"]]
    assert len(ids) == 2
    assert fin.count_tx() == before + 2
    assert fin.balance("tunai") == 137_000
    assert "Rp137.000" in r["message"]
    # satu item salah -> tidak ada yang tersimpan
    for bad in (["--item", "a|5k", "--item", "b|xx"], ["--item", "a|5k", "--item", "b|5k|kategori-aneh"],
                ["--item", "a|5k", "--item", "tanpa jumlah"], ["--item", "a|5k", "--item", "b|0"]):
        e = fin("add", "--type", "expense", *bad)
        assert not e["ok"] and "Item ke-2" in e["error"]["message"]
    assert fin.count_tx() == before + 2
    assert fin.balance("tunai") == 137_000


def test_add_one_amount_many_things(wallets):
    r = wallets.ok("add", "--type", "expense", "--item", "jajan, parkir, dan makan|50k|makan")
    assert r["data"]["items"][0]["amount"] == 50_000
    assert wallets.balance("tunai") == 100_000


def test_add_date_and_negative_warning(wallets):
    fin = wallets
    r = fin.ok("add", "--type", "expense", "--date", "yesterday", "--item", "nasi|10k")
    assert r["data"]["ts"] == "2026-10-05 12:00:00"
    assert "5 Oktober 2026" in r["message"]
    fin.err("BAD_DATE", "add", "--type", "expense", "--date", "2026-10-07", "--item", "nasi|10k")
    r = fin.ok("add", "--type", "expense", "--item", "hp baru|1jt")
    assert "minus" in r["message"]
    assert fin.balance("tunai") == 140_000 - 1_000_000


def test_unknown_account_does_not_change_data(wallets):
    fin = wallets
    before = fin.count_tx()
    e = fin.err("UNKNOWN_ACCOUNT", "add", "--type", "expense", "--account", "bca", "--item", "x|1k")
    assert e["error"]["hint"] == "Pilihan: tunai, bri, gopay"
    fin.err("UNKNOWN_ACCOUNT", "transfer", "--from", "bca", "--to", "tunai", "--amount", "1k")
    fin.err("UNKNOWN_ACCOUNT", "adjust", "--account", "bca", "--actual", "1k")
    assert fin.count_tx() == before


def test_no_default_account(fin):
    fin.ok("account", "add", "tunai", "--type", "cash")
    fin.ok("account", "remove", "tunai")  # dompet terakhir boleh dihapus walau default
    e = fin.err("NO_DEFAULT_ACCOUNT", "add", "--type", "expense", "--item", "x|1k")
    assert "set-default" in e["error"]["hint"]


def test_transfer_fee_and_mixed_balance(wallets):
    fin = wallets
    fin.ok("add", "--type", "income", "--account", "bri", "--item", "gajian|600k|gaji")
    fin.ok("add", "--type", "expense", "--item", "ayam goreng|15k|makan")
    r = fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "200k", "--fee", "2.5k")
    assert r["data"]["kind"] == "cash_withdrawal"
    assert "Tarik tunai" in r["message"] and "Rp2.500" in r["message"]
    fin.ok("budget", "alloc", "--item", "tabungan|100k")
    fin.ok("transfer", "--from", "gopay", "--to", "tunai", "--amount", "20k")
    fin.err("BAD_ARGS", "transfer", "--from", "bri", "--to", "BRI", "--amount", "1k")
    fin.err("BAD_AMOUNT", "transfer", "--from", "bri", "--to", "tunai", "--amount", "0")
    r = fin.ok("adjust", "--account", "gopay", "--actual", "25k")
    assert r["data"]["difference"] == -5_000

    assert fin.balance("bri") == 500_000 + 600_000 - 200_000 - 2_500
    assert fin.balance("tunai") == 150_000 - 15_000 + 200_000 + 20_000
    assert fin.balance("gopay") == 25_000
    total = fin.ok("balance")["data"]
    assert total["total_dompet"] == 897_500 + 355_000 + 25_000
    assert total["total_budget"] == total["total_dompet"] and total["consistent"] is True
    assert total["savings_total"] == 100_000
    assert total["non_savings_total"] == total["total_dompet"] - 100_000
    assert total["net_worth"] == total["total_dompet"]

    # transfer, adjustment, dan saldo awal tidak masuk laporan
    rep = fin.ok("report", "--period", "this-month", "--type", "all")["data"]
    assert rep["income"]["total"] == 600_000
    assert rep["expense"]["total"] == 15_000 + 2_500
    assert {c["category"] for c in rep["expense"]["by_category"]} == {"makan", "biaya admin"}


def test_adjust_same_balance_no_tx(wallets):
    before = wallets.count_tx()
    r = wallets.ok("adjust", "--account", "tunai", "--actual", "150.000")
    assert r["data"]["difference"] == 0
    assert wallets.count_tx() == before
    r = wallets.ok("adjust", "--account", "bri", "--actual", "450k")
    assert r["data"]["difference"] == -50_000 and wallets.balance("bri") == 450_000


def test_edit_changes_balance(wallets):
    fin = wallets
    tx = fin.ok("add", "--type", "expense", "--item", "nasi|10k|makan")["data"]["items"][0]["id"]
    r = fin.ok("edit", tx, "--amount", "12k", "--category", "jajan", "--note", "nasi kucing")
    assert r["data"]["before"]["amount"] == 10_000 and r["data"]["after"]["amount"] == 12_000
    assert "Rp10.000 → Rp12.000" in r["message"] and "makan → jajan" in r["message"]
    assert fin.balance("tunai") == 138_000
    fin.ok("edit", tx, "--account", "gopay")
    assert fin.balance("tunai") == 150_000 and fin.balance("gopay") == 38_000
    fin.err("BAD_ARGS", "edit", tx)
    fin.err("UNKNOWN_CATEGORY", "edit", tx, "--category", "gaji")
    fin.err("NOT_FOUND", "edit", 999, "--amount", "1k")
    fin.err("BAD_DATE", "edit", tx, "--date", "2027-01-01")
    fin.ok("edit", tx, "--date", "2026-09-30")
    assert fin.ok("report", "--period", "2026-09")["data"]["total"] == 12_000

    t = fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "50k")["data"]["transfer_id"]
    fin.err("BAD_ARGS", "edit", t, "--category", "makan")
    fin.err("BAD_ARGS", "edit", t, "--to", "bri")
    fin.ok("edit", t, "--to", "gopay", "--amount", "60k")
    assert fin.balance("tunai") == 150_000 and fin.balance("gopay") == 98_000
    assert fin.balance("bri") == 440_000


def test_delete_changes_balance(wallets):
    fin = wallets
    tx = fin.ok("add", "--type", "expense", "--item", "nasi|10k|makan")["data"]["items"][0]["id"]
    assert fin.balance("tunai") == 140_000
    fin.ok("delete", tx)
    assert fin.balance("tunai") == 150_000
    e = fin.err("NOT_FOUND", "delete", tx)
    assert "sudah dihapus" in e["error"]["message"]
    listed = fin.ok("list", "--include-deleted")["data"]["transactions"]
    assert any(t["id"] == tx and t["deleted_at"] for t in listed)
    assert all(t["id"] != tx for t in fin.ok("list")["data"]["transactions"])
    # hapus transfer, biaya admin dari pencatatan yang sama disebut di message
    r = fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "100k", "--fee", "2.5k")
    d = fin.ok("delete", r["data"]["transfer_id"])
    assert d["data"]["remaining_in_group"] == [r["data"]["fee_id"]]
    assert fin.balance("bri") == 497_500


def test_undo_whole_group(wallets):
    fin = wallets
    fin.ok("add", "--type", "expense", "--item", "nasi|10k")
    fin.ok("add", "--type", "expense", "--item", "jajan|10k", "--item", "es teh|3k")
    r = fin.ok("undo")
    assert len(r["data"]["undone"]) == 2 and "es teh" in r["message"]
    assert fin.balance("tunai") == 140_000
    fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "200k", "--fee", "2.5k")
    r = fin.ok("undo")
    assert len(r["data"]["undone"]) == 2
    assert fin.balance("bri") == 500_000 and fin.balance("tunai") == 140_000
    fin.ok("undo")  # nasi
    assert fin.balance("tunai") == 150_000


def test_nothing_to_undo(fin):
    fin.err("NOTHING_TO_UNDO", "undo")


def test_list_search_and_filters(wallets):
    fin = wallets
    fin.ok("add", "--type", "expense", "--item", "Kopi susu|18k", "--raw", "beli kopi susu 18k")
    fin.ok("add", "--type", "expense", "--item", "nasi 100%|10k")
    fin.ok("add", "--type", "income", "--account", "bri", "--item", "gaji|600k")
    r = fin.ok("list", "--search", "kopi")
    assert [t["note"] for t in r["data"]["transactions"]] == ["Kopi susu"]
    assert len(fin.ok("list", "--search", "%")["data"]["transactions"]) == 1
    assert len(fin.ok("list", "--type", "income")["data"]["transactions"]) == 1
    assert len(fin.ok("list", "--account", "bri")["data"]["transactions"]) == 2  # saldo awal + gaji
    assert len(fin.ok("list", "--category", "jajan")["data"]["transactions"]) == 1
    r = fin.ok("list", "--limit", "2")
    assert r["data"]["count"] == 2 and r["data"]["total_matching"] == 6
    fin.err("BAD_ARGS", "list", "--limit", "0")
    assert "tidak ada" in fin.ok("list", "--period", "2026-01")["message"]


def test_write_is_atomic_on_failure(wallets, monkeypatch):
    """Error di tengah penulisan membatalkan semua baris dari perintah itu."""
    from fin import ledger
    fin = wallets
    before = fin.count_tx()
    real = ledger.insert_tx
    calls = {"n": 0}

    def flaky(conn, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk penuh")
        return real(conn, **kw)

    monkeypatch.setattr("fin.commands.transactions.insert_tx", flaky)
    e = fin.err("INTERNAL", "add", "--type", "expense", "--item", "a|1k", "--item", "b|2k")
    assert "disk penuh" in e["error"]["message"]
    assert fin.count_tx() == before


def test_backup_daily_and_pruned(fin):
    backups = fin.home / "backups"
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "10k")
    assert [p.name for p in backups.iterdir()] == ["finance-20261006.db"]
    fin.ok("add", "--type", "expense", "--item", "x|1k")
    assert len(list(backups.iterdir())) == 1
    for day in range(1, 36):
        fin.ok("add", "--type", "expense", "--item", "x|1k", now=f"2026-11-{day:02d} 10:00:00"
               if day <= 30 else f"2026-12-{day - 30:02d} 10:00:00")
    files = sorted(p.name for p in backups.iterdir())
    assert len(files) == 30
    assert files[-1] == "finance-20261205.db"
    # backup berisi data sebelum perubahan hari itu
    conn = sqlite3.connect(backups / "finance-20261205.db")
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    assert n == fin.count_tx() - 1
    r = fin.ok("backup")
    assert r["data"]["path"].endswith(".db")
