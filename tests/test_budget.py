UNALLOC = "belum teralokasi"


def budget_bal(fin, name):
    for b in fin.ok("budget", "list")["data"]["budgets"]:
        if b["name"] == name:
            return b["balance"]
    raise AssertionError(f"budget {name} tidak ada")


def test_income_always_goes_to_unallocated(wallets):
    fin = wallets
    start = budget_bal(fin, UNALLOC)
    assert start == 700_000
    fin.ok("budget", "alloc", "--item", "makan|100k")
    for cat in ("gaji", "bonus", "lainnya", "freelance"):
        r = fin.ok("add", "--type", "income", "--item", f"x|10k|{cat}")
        assert r["data"]["items"][0]["budget"] == UNALLOC
    assert budget_bal(fin, UNALLOC) == start - 100_000 + 40_000
    assert budget_bal(fin, "makan") == 100_000
    fin.err("BAD_ARGS", "add", "--type", "income", "--budget", "makan", "--item", "x|1k")


def test_expense_without_budget_uses_unallocated_until_allocated(wallets):
    fin = wallets
    first = fin.ok("add", "--type", "expense", "--item", "nasi|20k|makan")
    assert first["data"]["items"][0]["budget"] == UNALLOC
    assert budget_bal(fin, UNALLOC) == 680_000
    fin.ok("budget", "alloc", "--item", "makan|300k")
    second = fin.ok("add", "--type", "expense", "--item", "nasi|15k|makan")
    assert second["data"]["items"][0]["budget"] == "makan"
    assert second["data"]["items"][0]["budget_balance"] == 285_000
    assert "Sisa budget makan Rp285.000" in second["message"] and "Sisa tunai" in second["message"]
    # transaksi lama tidak ditulis ulang
    old = fin.ok("list", "--search", "nasi")["data"]["transactions"]
    assert {t["id"]: t["budget"] for t in old} == {first["data"]["items"][0]["id"]: UNALLOC,
                                                  second["data"]["items"][0]["id"]: "makan"}
    assert budget_bal(fin, UNALLOC) == 380_000


def test_alloc_many_items_atomic(wallets):
    fin = wallets
    r = fin.ok("budget", "alloc", "--item", "makan|300k", "--item", "transport|100k", "--note", "Oktober")
    assert r["data"]["total"] == 400_000 and r["data"]["unallocated_balance"] == 300_000
    assert [i["budget"] for i in r["data"]["items"]] == ["makan", "transport"]
    groups = {m["group_id"] for m in fin.ok("budget", "history")["data"]["moves"]}
    assert len(groups) == 1
    for bad in (["--item", "jajan|50k", "--item", "makanan enak|10k"], ["--item", "jajan|50k", "--item", "pulsa|x"],
                ["--item", "jajan|50k", "--item", "gaji|10k"], ["--item", "jajan|50k", "--item", f"{UNALLOC}|1k"],
                ["--item", "jajan|50k", "--item", "jajan"]):
        e = fin("budget", "alloc", *bad)
        assert not e["ok"] and "Item ke-2" in e["error"]["message"], e
    assert budget_bal(fin, UNALLOC) == 300_000
    assert all(b["name"] != "jajan" for b in fin.ok("budget", "list")["data"]["budgets"])
    fin.err("UNKNOWN_BUDGET", "budget", "alloc", "--item", "liburan|10k")


def test_negative_budgets_warn_not_error(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|10k")
    r = fin.ok("add", "--type", "expense", "--item", "nasi padang|15k|makan")
    assert "budget makan minus Rp5.000" in r["message"]
    r = fin.ok("budget", "alloc", "--item", "transport|800k")
    assert "belum teralokasi minus" in r["message"]
    assert budget_bal(fin, UNALLOC) == -110_000
    assert "minus" in fin.ok("budget", "list")["message"]
    assert "minus" in fin.ok("balance")["message"]


def test_move_and_move_all(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|300k")
    r = fin.ok("budget", "move", "--from", "makan", "--to", "jajan", "--amount", "50k")
    assert r["data"]["from_balance"] == 250_000 and r["data"]["to_balance"] == 50_000
    r = fin.ok("budget", "move", "--from", "jajan", "--to", "transport", "--amount", "all")
    assert r["data"]["amount"] == 50_000 and budget_bal(fin, "jajan") == 0
    # tabungan bukan budget: hint mengarahkan ke savings deposit
    r = fin.err("UNKNOWN_BUDGET", "budget", "move", "--from", "makan", "--to", "tabungan", "--amount", "1k")
    assert "savings deposit" in r["error"]["hint"]
    fin.err("BAD_AMOUNT", "budget", "move", "--from", "jajan", "--to", "makan", "--amount", "all")
    fin.err("BAD_ARGS", "budget", "move", "--from", "makan", "--to", "Makan", "--amount", "1k")
    fin.err("UNKNOWN_BUDGET", "budget", "move", "--from", "kesehatan", "--to", "makan", "--amount", "1k")
    fin.err("UNKNOWN_BUDGET", "budget", "move", "--from", "makan", "--to", "liburan", "--amount", "1k")
    r = fin.ok("budget", "move", "--from", "makan", "--to", UNALLOC, "--amount", "100k")
    assert budget_bal(fin, UNALLOC) == 700_000 - 300_000 + 100_000
    assert len(fin.ok("budget", "history", "--budget", "jajan")["data"]["moves"]) == 2


def test_transfer_does_not_touch_budgets(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|100k")
    before = fin.ok("budget", "list")["data"]["budgets"]
    fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "200k")
    assert fin.ok("budget", "list")["data"]["budgets"] == before
    r = fin.ok("transfer", "--from", "bri", "--to", "tunai", "--amount", "100k", "--fee", "2.5k")
    assert budget_bal(fin, UNALLOC) == 600_000 - 2_500  # biaya admin belum punya budget
    assert "belum teralokasi" in r["message"]


def test_adjust_zero_and_unallocated(wallets):
    fin = wallets
    r = fin.ok("adjust", "--account", "tunai", "--actual", "0")
    assert r["data"]["difference"] == -150_000 and fin.balance("tunai") == 0
    assert r["data"]["unallocated_balance"] == 550_000
    r = fin.ok("adjust", "--account", "tunai", "--actual", "Rp0")
    assert r["data"]["difference"] == 0
    fin.ok("adjust", "--account", "tunai", "--actual", "25k")
    assert budget_bal(fin, UNALLOC) == 575_000


def test_close_budget_positive_and_negative(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|100k", "--item", "jajan|20k")
    fin.ok("add", "--type", "expense", "--item", "nasi|30k|makan", "--item", "kopi|25k|jajan")
    r = fin.ok("budget", "close", "makan")
    assert r["data"]["returned"] == 70_000 and "Sisa Rp70.000 dikembalikan" in r["message"]
    r = fin.ok("budget", "close", "jajan")
    assert r["data"]["returned"] == -5_000 and "minus" in r["message"]
    assert budget_bal(fin, UNALLOC) == 700_000 - 120_000 + 70_000 - 5_000
    names = [b["name"] for b in fin.ok("budget", "list")["data"]["budgets"]]
    assert "makan" not in names and "jajan" not in names
    # kategori tetap ada dan kembali memakai belum teralokasi
    r = fin.ok("add", "--type", "expense", "--item", "nasi|10k|makan")
    assert r["data"]["items"][0]["budget"] == UNALLOC
    fin.err("UNKNOWN_BUDGET", "budget", "close", "makan")
    fin.err("SYSTEM_PROTECTED", "budget", "close", UNALLOC)
    # alokasi lagi mengaktifkan budget yang sama
    fin.ok("budget", "alloc", "--item", "makan|50k")
    assert budget_bal(fin, "makan") == 50_000


def test_closed_budget_with_leftover_is_visible_and_reclosable(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|100k")
    tx = fin.ok("add", "--type", "expense", "--item", "nasi|30k|makan")["data"]["items"][0]["id"]
    fin.ok("budget", "close", "makan")
    fin.ok("delete", tx)  # budget lama mendapat 30k lagi
    data = fin.ok("budget", "list")["data"]
    closed = [b for b in data["budgets"] if b["name"] == "makan"][0]
    assert closed["archived"] is True and closed["balance"] == 30_000
    assert data["consistent"] is True
    r = fin.ok("budget", "close", "makan")
    assert r["data"]["returned"] == 30_000
    assert budget_bal(fin, UNALLOC) == 700_000


def test_undo_alloc_and_mixed_order(wallets):
    fin = wallets
    fin.ok("add", "--type", "expense", "--item", "nasi|10k|makan")           # 1
    fin.ok("budget", "alloc", "--item", "makan|100k", "--item", "jajan|50k")  # 2
    fin.ok("add", "--type", "expense", "--item", "nasi|20k|makan")           # 3
    fin.ok("budget", "move", "--from", "makan", "--to", "jajan", "--amount", "30k")  # 4

    r = fin.ok("undo")
    assert r["data"]["action"] == "budget_move" and len(r["data"]["undone_moves"]) == 1
    assert budget_bal(fin, "makan") == 80_000
    r = fin.ok("undo")
    assert r["data"]["action"] == "add" and budget_bal(fin, "makan") == 100_000
    r = fin.ok("undo")
    assert r["data"]["action"] == "budget_alloc" and len(r["data"]["undone_moves"]) == 2
    assert budget_bal(fin, UNALLOC) == 690_000
    r = fin.ok("undo")
    assert r["data"]["action"] == "add" and budget_bal(fin, UNALLOC) == 700_000
    r = fin.ok("undo")  # saldo awal savings? tidak: ini saldo awal gopay
    assert r["data"]["action"] == "opening"
    assert "pindah budget" not in fin.ok("budget", "history")["message"]


def test_edit_category_moves_budget(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|100k", "--item", "jajan|100k")
    tx = fin.ok("add", "--type", "expense", "--item", "roti|20k|makan")["data"]["items"][0]["id"]
    assert budget_bal(fin, "makan") == 80_000
    r = fin.ok("edit", tx, "--category", "jajan")
    assert r["data"]["after"]["budget"] == "jajan" and "budget makan → jajan" in r["message"]
    assert budget_bal(fin, "makan") == 100_000 and budget_bal(fin, "jajan") == 80_000
    fin.ok("edit", tx, "--category", "kesehatan")  # tanpa budget -> belum teralokasi
    assert budget_bal(fin, "jajan") == 100_000 and budget_bal(fin, UNALLOC) == 480_000
    fin.ok("edit", tx, "--budget", "jajan")
    assert budget_bal(fin, "jajan") == 80_000
    fin.err("UNKNOWN_BUDGET", "edit", tx, "--budget", "tabungan")
    fin.err("UNKNOWN_BUDGET", "edit", tx, "--budget", "")


def test_add_with_budget(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "jajan|500k")
    r = fin.ok("add", "--type", "expense", "--account", "bri", "--budget", "jajan",
               "--item", "laptop bekas|300k|belanja")
    assert r["data"]["items"][0]["budget"] == "jajan" and "Diambil dari budget jajan" in r["message"]
    assert budget_bal(fin, "jajan") == 200_000
    assert fin.ok("report", "--category", "belanja")["data"]["total"] == 300_000
    # tabungan bukan budget: belanja dari tabungan lewat savings spend
    r = fin.err("UNKNOWN_BUDGET", "add", "--type", "expense", "--budget", "tabungan", "--item", "x|1k")
    assert "savings spend" in r["error"]["hint"]
    fin.err("UNKNOWN_BUDGET", "add", "--type", "expense", "--budget", "liburan", "--item", "x|1k")
    fin.err("UNKNOWN_BUDGET", "add", "--type", "expense", "--budget", "pendidikan", "--item", "x|1k")
    fin.err("UNKNOWN_BUDGET", "budget", "alloc", "--item", "makan|1k", "--item", "tabungan|1k")
    assert "makan" not in [b["name"] for b in fin.ok("budget", "list")["data"]["budgets"]]  # semua atau tidak


def test_balance_two_sides(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "makan|200k")
    fin.ok("savings", "deposit", "--from", "bri", "--to", "tabungan", "--amount", "100k")
    data = fin.ok("balance")["data"]
    assert data["total_dompet"] == 600_000 and data["total_budget"] == 600_000 and data["consistent"] is True
    assert data["total_tabungan"] == 100_000 and data["net_worth"] == 700_000
    assert all(b["kind"] != "savings" for b in data["budgets"])
    msg = fin.ok("balance")["message"]
    assert "Dompet" in msg and "Per budget" in msg and "Tabungan" in msg
