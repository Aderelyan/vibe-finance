"""Hutang piutang: arah uang, budget, bayar sebagian/lunas/berlebih, ambigu, --no-cash, undo, hapus."""

UNALLOC = "belum teralokasi"


def bud(fin, name):
    return next(b["balance"] for b in fin.ok("budget", "list")["data"]["budgets"] if b["name"] == name)


def debt(fin, debt_id):
    items = fin.ok("debt", "list", "--status", "all", "--all")["data"]["debts"]
    return next((d for d in items if d["id"] == debt_id), None)


def test_i_owe_adds_money_to_wallet_and_unallocated(wallets):
    fin = wallets
    before = bud(fin, UNALLOC)
    r = fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    assert r["data"]["account"] == "tunai" and r["data"]["used_default_account"] is True
    assert "dompet default" in r["message"] and "Budi" in r["message"]
    assert fin.balance("tunai") == 200_000
    assert bud(fin, UNALLOC) == before + 50_000
    assert r["data"]["debt"]["remaining"] == 50_000 and r["data"]["debt"]["status"] == "open"


def test_owed_to_me_takes_money_from_wallet(wallets):
    fin = wallets
    before = bud(fin, UNALLOC)
    r = fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "100k", "--account", "bri")
    assert fin.balance("bri") == 400_000
    assert bud(fin, UNALLOC) == before - 100_000
    bal = fin.ok("balance")["data"]
    assert bal["receivable_total"] == 100_000 and bal["debt_total"] == 0
    assert bal["net_worth"] == bal["total_dompet"] + 100_000
    assert r["data"]["debt"]["direction"] == "owed_to_me"


def test_budget_option_only_for_money_out(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|100k")
    fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "30k", "--budget", "makan")
    assert bud(fin, "makan") == 70_000
    n = fin.count_tx()
    fin.err("BAD_ARGS", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
            "--budget", "makan")
    fin.err("UNKNOWN_BUDGET", "debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "30k",
            "--budget", "liburan")
    assert fin.count_tx() == n

    # bayar hutang (uang keluar) boleh dari budget tertentu
    fin.ok("budget", "alloc", "--item", "jajan|100k")
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "40k")
    fin.ok("debt", "pay", "--person", "Budi", "--amount", "40k", "--budget", "jajan")
    assert bud(fin, "jajan") == 60_000
    # hutang biasa tidak lewat tabungan
    fin.err("UNKNOWN_ACCOUNT", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "1k",
            "--account", "tabungan")
    # terima pembayaran piutang (uang masuk) tidak boleh --budget
    fin.err("BAD_ARGS", "debt", "pay", "--person", "Andi", "--amount", "10k", "--budget", "makan")


def test_partial_full_and_overpayment(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    r = fin.ok("debt", "pay", "--person", "budi", "--amount", "20k")
    assert r["data"]["remaining"] == 30_000 and r["data"]["paid_off"] is False
    assert fin.balance("tunai") == 180_000

    n = fin.count_tx()
    r = fin.err("OVERPAYMENT", "debt", "pay", "--person", "Budi", "--amount", "31k")
    assert r["error"]["data"]["remaining"] == 30_000 and "Rp30.000" in r["error"]["message"]
    assert fin.count_tx() == n and fin.balance("tunai") == 180_000

    r = fin.ok("debt", "pay", "--person", "Budi", "--amount", "all")
    assert r["data"]["amount"] == 30_000 and r["data"]["paid_off"] is True and "LUNAS" in r["message"]
    assert debt(fin, 1)["status"] == "paid"
    fin.err("OVERPAYMENT", "debt", "pay", "--person", "Budi", "--amount", "1k")
    fin.err("OVERPAYMENT", "debt", "pay", "--id", "1", "--amount", "1k")
    assert fin.ok("debt", "list")["data"]["count"] == 0
    assert fin.ok("debt", "list", "--status", "paid")["data"]["count"] == 1


def test_owed_to_me_payment_comes_in(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "100k")
    before = bud(fin, UNALLOC)
    r = fin.ok("debt", "pay", "--person", "Andi", "--amount", "60k", "--account", "bri")
    assert fin.balance("bri") == 560_000 and bud(fin, UNALLOC) == before + 60_000
    assert r["data"]["remaining"] == 40_000
    assert "Andi membayar" in r["message"]


def test_two_debts_same_person_is_ambiguous(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k", "--note", "makan")
    r = fin.ok("debt", "add", "--direction", "i_owe", "--person", "budi", "--amount", "20k")
    assert r["data"]["debt"]["person"] == "Budi"  # ejaan disamakan dengan yang sudah ada
    assert "Rp70.000 dari 2 catatan" in r["message"]
    n = fin.count_tx()
    r = fin.err("AMBIGUOUS_DEBT", "debt", "pay", "--person", "Budi", "--amount", "10k")
    assert {c["id"] for c in r["error"]["data"]["candidates"]} == {1, 2}
    assert "#1" in r["error"]["message"] and "#2" in r["error"]["message"] and "--id" in r["error"]["hint"]
    assert fin.count_tx() == n
    r = fin.ok("debt", "pay", "--id", "2", "--amount", "20k")
    assert r["data"]["paid_off"] is True
    # setelah #2 lunas, hanya #1 yang terbuka: --person tidak ambigu lagi
    r = fin.ok("debt", "pay", "--person", "Budi", "--amount", "10k")
    assert r["data"]["debt"]["id"] == 1 and r["data"]["remaining"] == 40_000


def test_direction_narrows_person(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "Budi", "--amount", "30k")
    fin.err("AMBIGUOUS_DEBT", "debt", "pay", "--person", "Budi", "--amount", "10k")
    r = fin.ok("debt", "pay", "--person", "Budi", "--direction", "owed_to_me", "--amount", "10k")
    assert r["data"]["debt"]["id"] == 2
    fin.err("BAD_ARGS", "debt", "pay", "--id", "1", "--direction", "owed_to_me", "--amount", "1k")


def test_unknown_person_and_id(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    r = fin.err("NOT_FOUND", "debt", "pay", "--person", "Citra", "--amount", "10k")
    assert "Budi" in r["error"]["hint"]
    fin.err("NOT_FOUND", "debt", "pay", "--id", "99", "--amount", "10k")
    fin.err("BAD_ARGS", "debt", "pay", "--amount", "10k")  # --person atau --id wajib
    fin.err("BAD_ARGS", "debt", "pay", "--person", "Budi", "--id", "1", "--amount", "10k")


def test_no_cash(wallets):
    fin = wallets
    n, before = fin.count_tx(), fin.balance("tunai")
    r = fin.ok("debt", "add", "--direction", "i_owe", "--person", "Citra", "--amount", "30k", "--no-cash")
    assert r["data"]["transaction_id"] is None and r["data"]["debt"]["cash"] is False
    assert fin.count_tx() == n and fin.balance("tunai") == before
    assert fin.ok("balance")["data"]["debt_total"] == 30_000
    fin.err("BAD_ARGS", "debt", "add", "--direction", "i_owe", "--person", "Citra", "--amount", "30k",
            "--no-cash", "--account", "bri")
    # dibayar seperti biasa, uang keluar dari dompet
    fin.ok("debt", "pay", "--person", "Citra", "--amount", "30k")
    assert fin.balance("tunai") == before - 30_000
    assert fin.ok("balance")["data"]["debt_total"] == 0


def test_paid_for_records_debt_and_expense(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|100k")
    unalloc, n = bud(fin, UNALLOC), fin.count_tx()
    r = fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
               "--paid-for", "makan siang|makan")
    d = r["data"]
    assert d["expense_category"] == "makan" and d["expense_budget"] == "makan" and d["expense_id"]
    assert "tidak berubah" in r["message"]
    assert fin.count_tx() == n + 2
    assert fin.balance("tunai") == 150_000  # saldo dompet tetap
    assert bud(fin, UNALLOC) == unalloc + 30_000 and bud(fin, "makan") == 70_000
    rep = fin.ok("report", "--period", "this-month", "--type", "expense")["data"]
    assert rep["total"] == 30_000 and rep["by_category"][0]["category"] == "makan"
    assert fin.ok("balance")["data"]["debt_total"] == 30_000
    assert d["debt"]["note"] == "makan siang"

    # dibayar nanti: uang keluar sekali saja
    fin.ok("debt", "pay", "--person", "Budi", "--amount", "all")
    assert fin.balance("tunai") == 120_000


def test_paid_for_guess_category_and_undo(wallets):
    fin = wallets
    unalloc = bud(fin, UNALLOC)
    r = fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "12k",
               "--paid-for", "kopi susu", "--account", "bri")
    assert r["data"]["expense_category"] == "jajan" and "ditebak" in r["message"]
    # kategori tanpa budget: pengeluaran memakai belum teralokasi, jadi belum teralokasi netto tetap
    assert bud(fin, UNALLOC) == unalloc and fin.balance("bri") == 500_000
    r = fin.ok("undo")
    assert len(r["data"]["undone"]) == 2 and r["data"]["removed"][0]["id"] == 1
    assert fin.ok("report", "--period", "this-month")["data"]["total"] == 0
    assert fin.ok("balance")["data"]["debt_total"] == 0


def test_paid_for_rejections(wallets):
    fin = wallets
    n = fin.count_tx()
    fin.err("BAD_ARGS", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
            "--paid-for", "makan|makan", "--no-cash")
    fin.err("BAD_ARGS", "debt", "add", "--direction", "owed_to_me", "--person", "Budi", "--amount", "30k",
            "--paid-for", "makan|makan")
    fin.err("BAD_ARGS", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
            "--paid-for", "|makan")
    fin.err("BAD_ARGS", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
            "--paid-for", "a|b|c")
    fin.err("UNKNOWN_CATEGORY", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
            "--paid-for", "makan|gaji")
    fin.err("BAD_ARGS", "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "30k",
            "--paid-for", "makan|makan", "--budget", "makan")
    assert fin.count_tx() == n
    assert fin.ok("debt", "list", "--status", "all", "--all")["data"]["count"] == 0


def test_debts_not_in_reports(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "100k")
    fin.ok("debt", "pay", "--person", "Budi", "--amount", "20k")
    fin.ok("debt", "pay", "--person", "Andi", "--amount", "40k")
    rep = fin.ok("report", "--period", "this-month", "--type", "all")["data"]
    assert rep["income"]["total"] == 0 and rep["expense"]["total"] == 0


def test_delete_payment_reopens(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    r = fin.ok("debt", "pay", "--person", "Budi", "--amount", "all")
    assert debt(fin, 1)["status"] == "paid"
    fin.ok("delete", str(r["data"]["transaction_id"]))
    d = debt(fin, 1)
    assert d["status"] == "open" and d["remaining"] == 50_000
    fin.err("BAD_ARGS", "edit", str(r["data"]["transaction_id"] - 1), "--amount", "10k")  # nominal hutang tidak bisa diedit


def test_undo_payment_and_add(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    fin.ok("debt", "pay", "--person", "Budi", "--amount", "all")
    r = fin.ok("undo")
    assert r["data"]["action"] == "debt_pay"
    assert debt(fin, 1)["status"] == "open" and fin.balance("tunai") == 200_000
    r = fin.ok("undo")
    assert r["data"]["action"] == "debt_add" and r["data"]["removed"][0]["id"] == 1
    assert "Ikut dihapus" in r["message"]
    assert fin.balance("tunai") == 150_000
    assert fin.ok("debt", "list")["data"]["count"] == 0
    assert fin.ok("balance")["data"]["debt_total"] == 0
    assert debt(fin, 1)["archived"] is True


def test_set_due_and_note(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k", "--due", "2026-10-03")
    item = fin.ok("debt", "list")["data"]["debts"][0]
    assert item["days_until_due"] == -3
    assert "lewat 3 hari" in fin.ok("debt", "list")["message"]
    r = fin.ok("debt", "set", "--person", "Budi", "--due", "2026-10-20", "--note", "buat kos")
    assert r["data"]["debt"]["due_date"] == "2026-10-20" and r["data"]["debt"]["note"] == "buat kos"
    r = fin.ok("debt", "set", "--id", "1", "--clear-due")
    assert r["data"]["debt"]["due_date"] is None
    fin.err("BAD_ARGS", "debt", "set", "--id", "1")
    fin.err("BAD_DATE", "debt", "set", "--id", "1", "--due", "besok")


def test_rename_person(wallets):
    fin = wallets
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "budi", "--amount", "10k")
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi S", "--amount", "5k")
    r = fin.ok("debt", "rename", "budi", "Budi Santoso")
    assert r["data"]["ids"] == [1, 2]
    names = {d["person"] for d in fin.ok("debt", "list")["data"]["debts"]}
    assert names == {"Budi Santoso", "Budi S"}
    r = fin.ok("debt", "rename", "Budi S", "budi santoso")
    assert r["data"]["merged_ids"] == [1, 2]
    assert {d["person"] for d in fin.ok("debt", "list")["data"]["debts"]} == {"budi santoso"}
    fin.err("NOT_FOUND", "debt", "rename", "Citra", "Cici")


def test_remove_rules(wallets):
    fin = wallets
    # tanpa transaksi: hapus sungguhan
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Citra", "--amount", "30k", "--no-cash")
    r = fin.ok("debt", "remove", "--person", "Citra")
    assert r["data"]["mode"] == "deleted" and debt(fin, 1) is None

    # masih bersisa: NOT_EMPTY dengan dua pilihan
    fin.ok("debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "100k")
    n, before = fin.count_tx(), fin.balance("tunai")
    r = fin.err("NOT_EMPTY", "debt", "remove", "--person", "Andi")
    assert r["error"]["message"].startswith("Piutang dari Andi (#")  # nama orang tidak ikut dikecilkan
    assert "--write-off" in r["error"]["hint"] and "debt pay" in r["error"]["hint"]
    assert r["error"]["data"]["remaining"] == 100_000
    assert fin.count_tx() == n

    # --write-off: diarsipkan, uang tidak berubah, tidak dihitung lagi
    r = fin.ok("debt", "remove", "--person", "Andi", "--write-off")
    assert r["data"]["mode"] == "archived" and r["data"]["written_off"] == 100_000
    assert fin.balance("tunai") == before and fin.count_tx() == n
    assert fin.ok("balance")["data"]["receivable_total"] == 0
    assert fin.ok("debt", "list", "--status", "all")["data"]["count"] == 0
    assert fin.ok("debt", "list", "--status", "all", "--all")["data"]["count"] == 1
    fin.err("NOT_FOUND", "debt", "remove", "--id", str(r["data"]["id"]))

    # lunas: diarsipkan tanpa opsi
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    fin.ok("debt", "pay", "--person", "Budi", "--amount", "all")
    r = fin.ok("debt", "remove", "--person", "Budi")
    assert r["data"]["mode"] == "archived" and r["data"]["written_off"] == 0
