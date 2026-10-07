"""Tabungan sebagai akun terpisah di luar aturan utama (total dompet operasional = total budget).

Fixture `wallets`: tunai 150k (default), bri 500k, gopay 50k, tabungan kosong 'tabungan' target 2jt. Semua 700k di
'belum teralokasi'. Fin.__call__ memeriksa aturan utama dari tabel setelah setiap perintah.
"""
UNALLOC = "belum teralokasi"


def bud(fin, name):
    return next((b["balance"] for b in fin.ok("budget", "list")["data"]["budgets"] if b["name"] == name), None)


def totals(fin):
    d = fin.ok("balance")["data"]
    return d["total_dompet"], d["total_budget"], d["total_tabungan"]


def test_add_list_set_rename(wallets):
    fin = wallets
    r = fin.ok("savings", "add", "dana darurat", "--target", "5jt", "--target-date", "2027-06-30",
               "--opening", "1jt")
    assert r["data"]["savings"]["balance"] == 1_000_000 and "tidak mengubah dompet maupun budget" in r["message"]
    assert totals(fin) == (700_000, 700_000, 1_000_000)  # saldo awal tabungan di luar invarian
    lst = fin.ok("savings", "list")["data"]
    dd = next(s for s in lst["savings"] if s["name"] == "dana darurat")
    assert dd["percent"] == 20.0 and dd["shortfall"] == 4_000_000 and dd["month_change"] == 1_000_000
    assert lst["total"] == 1_000_000

    fin.err("BAD_ARGS", "savings", "add", "Tabungan")  # sudah ada
    fin.err("BAD_ARGS", "savings", "add", "bri")  # nama dompet
    r = fin.ok("savings", "set", "dana darurat", "--target", "3jt")
    assert r["data"]["target_amount"] == 3_000_000 and r["data"]["target_date"] == "2027-06-30"
    assert fin.ok("savings", "set", "dana darurat", "--clear")["data"]["target_amount"] is None
    fin.err("BAD_ARGS", "savings", "set-target", "dana darurat", "--clear")  # nama lama, diganti savings set
    fin.err("BAD_ARGS", "savings", "set", "dana darurat")
    fin.ok("savings", "rename", "dana darurat", "darurat")
    fin.err("UNKNOWN_ACCOUNT", "savings", "set", "dana darurat", "--target", "1jt")
    r = fin.err("UNKNOWN_ACCOUNT", "savings", "set", "bri", "--target", "1jt")
    assert "dompet, bukan tabungan" in r["error"]["message"]
    # tabungan tidak ikut daftar dompet dan tidak bisa jadi default
    assert all(a["name"] not in ("tabungan", "darurat") for a in fin.ok("account", "list")["data"]["accounts"])
    fin.err("UNKNOWN_ACCOUNT", "account", "set-default", "darurat")


def test_deposit(wallets):
    fin = wallets
    r = fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "100k")
    d = r["data"]
    assert d["savings"]["balance"] == 100_000 and d["balance_from"] == 400_000 and d["budget"] == UNALLOC
    assert d["budget_balance"] == 600_000 and "5,0% dari target" in r["message"]
    assert totals(fin) == (600_000, 600_000, 100_000)
    # dari budget kategori
    fin.ok("budget", "alloc", "--item", "makan|200k")
    fin.ok("savings", "deposit", "--from", "tunai", "--to", "tabungan", "--amount", "50k", "--from-budget", "makan")
    assert bud(fin, "makan") == 150_000 and fin.balance("tabungan") == 150_000
    # menabung bukan pengeluaran
    assert fin.ok("report", "--period", "this-month")["data"]["total"] == 0


def test_deposit_rejected_when_budget_short(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|30k")
    n = fin.count_tx()
    r = fin.err("BAD_AMOUNT", "savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "50k",
                "--from-budget", "makan")
    assert "Budget makan tidak cukup" in r["error"]["message"] and r["error"]["data"]["budget_balance"] == 30_000
    assert "--from-budget" in r["error"]["hint"]
    fin.err("BAD_AMOUNT", "savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "1jt")  # > 670k
    fin.err("UNKNOWN_BUDGET", "savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "1k",
            "--from-budget", "liburan")
    fin.err("UNKNOWN_ACCOUNT", "savings", "deposit", "--from", "tabungan", "--to", "tabungan", "--amount", "1k")
    fin.err("UNKNOWN_ACCOUNT", "savings", "deposit", "--from", "bri", "--to", "tunai", "--amount", "1k")
    assert fin.count_tx() == n


def test_withdraw(wallets):
    fin = wallets
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "300k")
    r = fin.ok("savings", "withdraw", "--from", "tabungan", "--to", "tunai", "--amount", "100k")
    assert r["data"]["balance_to"] == 250_000 and r["data"]["savings"]["balance"] == 200_000
    assert r["data"]["budget"] == UNALLOC and bud(fin, UNALLOC) == 500_000
    # ke budget kategori (dibuatkan jika belum ada)
    fin.ok("savings", "withdraw", "--from", "tabungan", "--to", "bri", "--amount", "50k", "--to-budget", "kesehatan")
    assert bud(fin, "kesehatan") == 50_000
    r = fin.ok("savings", "withdraw", "--from", "tabungan", "--to", "bri", "--amount", "all")
    assert r["data"]["amount"] == 150_000 and fin.balance("tabungan") == 0
    assert totals(fin) == (700_000, 700_000, 0)


def test_withdraw_and_spend_rejected_when_savings_short(wallets):
    fin = wallets
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "40k")
    n = fin.count_tx()
    r = fin.err("BAD_AMOUNT", "savings", "withdraw", "--from", "tabungan", "--to", "bri", "--amount", "50k")
    assert "sisanya Rp40.000" in r["error"]["message"] and r["error"]["data"]["savings_balance"] == 40_000
    r = fin.err("BAD_AMOUNT", "savings", "spend", "--from", "tabungan", "--item", "a|30k", "--item", "b|20k",
                "--mode", "purpose")
    assert "Rp50.000" in r["error"]["message"]
    fin.err("BAD_AMOUNT", "savings", "spend", "--from", "tabungan", "--item", "a|41k", "--mode", "debt")
    fin.ok("savings", "withdraw", "--from", "tabungan", "--to", "bri", "--amount", "all")
    fin.err("BAD_AMOUNT", "savings", "withdraw", "--from", "tabungan", "--to", "bri", "--amount", "all")
    fin.err("BAD_ARGS", "savings", "spend", "--from", "tabungan", "--item", "a|1k")  # --mode wajib
    assert fin.count_tx() == n + 1


def test_spend_purpose(wallets):
    fin = wallets
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "500k")
    before = totals(fin)
    r = fin.ok("savings", "spend", "--from", "tabungan", "--item", "laptop bekas|300k|belanja",
               "--item", "tas laptop|50k", "--mode", "purpose")
    assert r["data"]["total"] == 350_000 and r["data"]["savings"]["balance"] == 150_000
    assert r["data"]["items"][1]["category"] == "lainnya"
    assert totals(fin) == (before[0], before[1], 150_000)  # dompet dan budget tidak berubah
    # laporan memisahkan pengeluaran dari tabungan
    rep = fin.ok("report", "--period", "this-month", "--type", "expense")
    assert rep["data"]["total"] == 0 and rep["data"]["savings_expense"]["total"] == 350_000
    assert "Pengeluaran dari tabungan" in rep["message"]
    rep = fin.ok("report", "--account", "tabungan")["data"]
    assert rep["total"] == 350_000
    a = fin.ok("analyze")["data"]
    assert a["expense_total"] == 0 and a["savings"]["expense"]["total"] == 350_000
    tx = fin.ok("list", "--search", "laptop bekas")["data"]["transactions"][0]
    assert tx["source"] == "savings" and tx["budget"] is None
    # edit: kategori boleh, budget tidak, dompet hanya ke tabungan lain
    fin.ok("edit", tx["id"], "--category", "pendidikan")
    fin.err("BAD_ARGS", "edit", tx["id"], "--budget", "makan")
    fin.err("UNKNOWN_ACCOUNT", "edit", tx["id"], "--account", "bri")


def test_spend_debt_then_repay(wallets):
    fin = wallets
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "500k")
    fin.ok("budget", "alloc", "--item", "transport|100k")
    before = totals(fin)
    r = fin.ok("savings", "spend", "--from", "tabungan", "--item", "servis motor|200k|transport", "--mode", "debt")
    debt_id = r["data"]["items"][0]["debt_id"]
    assert r["data"]["savings"]["balance"] == 300_000 and r["data"]["savings"]["loans_outstanding"] == 200_000
    assert totals(fin) == (before[0], before[1], 300_000)  # dompet dan budget belum berubah
    assert fin.ok("report")["data"]["total"] == 0  # belum jadi pengeluaran
    lst = fin.ok("debt", "list")["data"]
    assert lst["debt_total"] == 0 and lst["savings_loans_total"] == 200_000  # bukan hutang ke orang lain
    assert lst["debts"][0]["savings"] == "tabungan" and "Pinjaman dari tabungan" in fin.ok("debt", "list")["message"]
    assert fin.ok("balance")["data"]["net_worth"] == 700_000 - 200_000

    # lunasi sebagian dari tunai, budget bawaan = budget kategori barangnya (transport)
    r = fin.ok("debt", "pay", "--person", "tabungan", "--amount", "50k")
    assert r["data"]["category"] == "transport" and r["data"]["budget"] == "transport"
    assert r["data"]["remaining"] == 150_000 and r["data"]["savings_balance_after"] == 350_000
    assert bud(fin, "transport") == 50_000 and fin.balance("tunai") == 100_000
    rep = fin.ok("report")["data"]
    assert rep["total"] == 50_000 and rep["by_category"][0]["category"] == "transport"
    fin.err("OVERPAYMENT", "debt", "pay", "--id", debt_id, "--amount", "151k")
    # sisanya dari bri dengan budget lain
    r = fin.ok("debt", "pay", "--id", debt_id, "--amount", "all", "--account", "bri", "--budget", UNALLOC)
    assert r["data"]["paid_off"] is True and fin.balance("tabungan") == 500_000
    assert fin.ok("debt", "list")["data"]["savings_loans_total"] == 0
    assert fin.ok("report")["data"]["total"] == 200_000
    # rename tabungan ikut mengganti nama di pinjamannya; debt rename ditolak
    fin.err("BAD_ARGS", "debt", "rename", "tabungan", "celengan")
    fin.ok("savings", "rename", "tabungan", "celengan")
    assert fin.ok("debt", "list", "--status", "all")["data"]["debts"][0]["person"] == "celengan"


def test_undo_each_operation(wallets):
    fin = wallets
    start = totals(fin)
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "300k")
    assert fin.ok("undo")["data"]["action"] == "savings_deposit" and totals(fin) == start
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "300k")
    after_deposit = totals(fin)

    fin.ok("savings", "withdraw", "--from", "tabungan", "--to", "tunai", "--amount", "100k")
    assert fin.ok("undo")["data"]["action"] == "savings_withdraw" and totals(fin) == after_deposit
    fin.ok("savings", "spend", "--from", "tabungan", "--item", "buku|50k", "--mode", "purpose")
    assert fin.ok("undo")["data"]["action"] == "savings_spend_purpose" and totals(fin) == after_deposit

    fin.ok("savings", "spend", "--from", "tabungan", "--item", "helm|80k|belanja", "--mode", "debt")
    fin.ok("debt", "pay", "--person", "tabungan", "--amount", "30k")
    r = fin.ok("undo")
    assert r["data"]["action"] == "debt_pay" and len(r["data"]["undone"]) == 2  # pengeluaran + kembali ke tabungan
    assert fin.ok("debt", "list")["data"]["debts"][0]["remaining"] == 80_000
    r = fin.ok("undo")
    assert r["data"]["action"] == "savings_spend_debt" and r["data"]["removed"][0]["table"] == "debts"
    assert totals(fin) == after_deposit and fin.ok("debt", "list")["data"]["count"] == 0

    fin.ok("adjust", "--account", "tabungan", "--actual", "250k")
    assert totals(fin) == (after_deposit[0], after_deposit[1], 250_000)
    assert fin.ok("undo")["data"]["action"] == "adjust" and totals(fin) == after_deposit


def test_delete_single_transaction_keeps_invariant(wallets):
    fin = wallets
    r = fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "100k")
    fin.ok("edit", r["data"]["id"], "--amount", "120k")
    assert fin.balance("tabungan") == 120_000 and fin.balance("bri") == 380_000
    fin.err("UNKNOWN_ACCOUNT", "edit", r["data"]["id"], "--to", "bri")  # tujuan deposit harus tabungan
    fin.ok("delete", r["data"]["id"])
    assert totals(fin) == (700_000, 700_000, 0)


def test_remove_rules(wallets):
    fin = wallets
    # belum pernah dipakai: hapus sungguhan
    fin.ok("savings", "add", "liburan")
    assert fin.ok("savings", "remove", "liburan")["data"]["mode"] == "deleted"
    fin.err("UNKNOWN_ACCOUNT", "savings", "remove", "liburan")

    # bersaldo tanpa opsi: NOT_EMPTY
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "100k")
    r = fin.err("NOT_EMPTY", "savings", "remove", "tabungan")
    assert "--move-to" in r["error"]["hint"] and "--write-off" in r["error"]["hint"]
    # masih ada pinjaman: ditolak
    fin.ok("savings", "spend", "--from", "tabungan", "--item", "x|10k", "--mode", "debt")
    r = fin.err("NOT_EMPTY", "savings", "remove", "tabungan", "--write-off")
    assert "debt pay" in r["error"]["hint"]
    fin.ok("debt", "pay", "--person", "tabungan", "--amount", "all")

    # --move-to dompet: masuk ke belum teralokasi, diarsipkan; undo mengaktifkannya lagi
    unalloc = bud(fin, UNALLOC)
    r = fin.ok("savings", "remove", "tabungan", "--move-to", "bri")
    assert r["data"]["mode"] == "archived" and r["data"]["moved_to"] == "bri"
    assert bud(fin, UNALLOC) == unalloc + 100_000 and totals(fin)[2] == 0
    assert fin.ok("savings", "list")["data"]["savings"] == []
    r = fin.ok("undo")
    assert r["data"]["restored"][0]["name"] == "tabungan" and fin.balance("tabungan") == 100_000
    assert fin.ok("account", "list")["data"]["accounts"][0]["is_default"] is True  # default tetap tunai

    # --move-to tabungan lain dan --write-off
    fin.ok("savings", "add", "darurat")
    fin.ok("savings", "remove", "tabungan", "--move-to", "darurat")
    assert fin.balance("darurat") == 100_000
    before = totals(fin)
    r = fin.ok("savings", "remove", "darurat", "--write-off")
    assert r["data"]["written_off"] is True and totals(fin) == (before[0], before[1], 0)

    # nama yang diarsipkan bisa diaktifkan lagi
    r = fin.ok("savings", "add", "tabungan", "--target", "1jt")
    assert r["data"]["reactivated"] is True and r["data"]["savings"]["target_amount"] == 1_000_000
