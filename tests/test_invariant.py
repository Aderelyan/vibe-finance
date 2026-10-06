"""Aturan utama: total semua dompet selalu sama dengan total semua budget, setelah perintah apa pun.

Fin.__call__ sudah memeriksa aturan ini langsung dari tabel setelah setiap perintah. Tes ini
menjalankan ratusan perintah acak (sah maupun tidak) dengan seed tetap.
"""
import json
import random

import pytest

ACCOUNTS = ["tunai", "tunai", "bri", "bri", "gopay", "dana"]
CATEGORIES = ["makan", "jajan", "transport", "belanja", "hiburan", "kesehatan", "kucing", "biaya admin", "lainnya"]
BUDGETS = CATEGORIES + ["belum teralokasi", "tabungan", "laptop", "liburan"]
AMOUNTS = ["5k", "10k", "25rb", "50.000", "100k", "1,5jt"] * 3 + ["0", "abc", "-5k", "all"]
PEOPLE = ["Budi", "budi", "Andi", "Citra"]
BILLS = ["kos", "wifi", "listrik"]


def random_batch(rng, path):
    """File batch berisi 1-4 perintah acak (kadang ada yang salah, sehingga seluruh batch batal)."""
    entries = []
    for _ in range(rng.randint(1, 4)):
        acc, acc2 = rng.sample(["tunai", "bri"], 2)
        amt = rng.choice(AMOUNTS[:-1])
        entries.append(rng.choice([
            {"cmd": "add", "args": {"type": "expense", "account": acc, "item": [f"x|{amt}|{rng.choice(CATEGORIES)}"]}},
            {"cmd": "add", "args": {"type": "income", "account": acc, "item": f"gaji|{amt}|gaji"}},
            {"cmd": "budget alloc", "args": {"item": f"{rng.choice(BUDGETS)}|{amt}"}},
            {"cmd": "budget move", "args": {"from": rng.choice(BUDGETS), "to": rng.choice(BUDGETS), "amount": amt}},
            {"cmd": "transfer", "args": {"from": acc, "to": acc2, "amount": amt, "fee": "1k"}},
            {"cmd": "adjust", "args": {"account": acc, "actual": rng.choice(["0", "50k", "-5k"])}},
            {"cmd": "debt add", "args": {"direction": "i_owe", "person": rng.choice(PEOPLE), "amount": amt,
                                         "paid_for": "traktiran|makan"}},
            {"cmd": "debt pay", "args": {"person": rng.choice(PEOPLE), "amount": "all", "account": acc}},
        ]))
    path.write_text(json.dumps(entries), encoding="utf-8")


def random_command(rng, max_id, batch_file="batch.json"):
    acc, acc2 = rng.sample(ACCOUNTS, 2)
    person = rng.choice(PEOPLE)
    cat, bud, bud2 = rng.choice(CATEGORIES), rng.choice(BUDGETS), rng.choice(BUDGETS)
    amt = rng.choice(AMOUNTS)
    tx = str(rng.randint(max(1, max_id - 15), max_id + 1))
    choices = [
        (8, ["add", "--type", "expense", "--account", acc, "--item", f"beli|{amt}|{cat}"]),
        (3, ["add", "--type", "expense", "--item", f"a|{amt}|{cat}", "--item", f"b|{rng.choice(AMOUNTS)}"]),
        (2, ["add", "--type", "expense", "--budget", bud, "--item", f"x|{amt}|{cat}"]),
        (5, ["add", "--type", "income", "--account", acc, "--item", f"gaji|{amt}|gaji"]),
        (4, ["transfer", "--from", acc, "--to", acc2, "--amount", amt]
         + (["--fee", "2.5k"] if rng.random() < 0.3 else [])),
        (3, ["adjust", "--account", acc, "--actual", rng.choice(["0", "100k", "1jt", "37.500"])]),
        (5, ["budget", "alloc", "--item", f"{bud}|{amt}"] + (["--item", f"{bud2}|10k"] if rng.random() < 0.4 else [])),
        (4, ["budget", "move", "--from", bud, "--to", bud2, "--amount", amt]),
        (1, ["budget", "close", bud]),
        (4, ["edit", tx, "--amount", amt]),
        (2, ["edit", tx, "--category", cat]),
        (1, ["edit", tx, "--account", acc]),
        (1, ["edit", tx, "--budget", bud]),
        (3, ["delete", tx]),
        (3, ["undo"]),
        (2, ["account", "add", acc, "--type", rng.choice(["cash", "bank", "ewallet"]),
             "--opening", rng.choice(["0", "20k", "75k"])]),
        (2, ["account", "remove", acc] + rng.choice([[], ["--write-off"], ["--move-to", acc2]])),
        (1, ["account", "set-default", acc]),
        (1, ["category", "add", cat, "--kind", "expense"]),
        (1, ["category", "remove", cat, "--kind", "expense"]),
        (1, ["savings", "add", rng.choice(["tabungan", "laptop", "liburan"]), "--target", "1jt"]),
        (1, ["savings", "remove", rng.choice(["tabungan", "laptop", "liburan"])]),
        (3, ["debt", "add", "--direction", "i_owe", "--person", person, "--amount", amt, "--account", acc]
         + rng.choice([[], [], ["--no-cash"], ["--paid-for", f"ditraktir|{cat}"], ["--paid-for", "kopi"],
                       ["--budget", bud]])),  # --budget di sini sengaja salah
        (2, ["debt", "add", "--direction", "owed_to_me", "--person", person, "--amount", amt, "--account", acc]
         + rng.choice([[], ["--budget", bud], ["--no-cash"], ["--paid-for", "x"]])),
        (3, ["debt", "pay", "--person", person, "--amount", rng.choice(AMOUNTS + ["all"]), "--account", acc]
         + rng.choice([[], [], ["--budget", bud], ["--direction", "i_owe"]])),
        (1, ["debt", "remove", "--person", person] + rng.choice([[], ["--write-off"]])),
        (2, ["recurring", "add", rng.choice(BILLS), "--amount", amt, "--day", str(rng.randint(1, 31)),
             "--account", rng.choice(["tunai", "bri"])]),
        (2, ["recurring", "pay", rng.choice(BILLS), "--month", rng.choice(["2026-08", "2026-09", "2026-10"])]
         + rng.choice([[], ["--budget", bud], ["--account", acc]])),
        (1, ["recurring", "remove", rng.choice(BILLS)]),
        (3, ["batch", "--file", batch_file]),
    ]
    weights = [w for w, _ in choices]
    return rng.choices([c for _, c in choices], weights=weights)[0]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_wallets_equal_budgets_after_random_commands(fin, seed):
    rng = random.Random(seed)
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "200k")
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "1jt")
    fin.ok("savings", "add", "tabungan")
    ok_count, ok_by_command = 0, {}
    for step in range(300):
        batch_file = fin.home / "batch.json"
        random_batch(rng, batch_file)
        cmd = random_command(rng, max_id=fin.max_tx_id(), batch_file=str(batch_file))
        obj = fin(*cmd)  # memeriksa aturan utama dari tabel
        ok_count += obj["ok"]
        ok_by_command[cmd[0]] = ok_by_command.get(cmd[0], 0) + obj["ok"]
        assert obj["ok"] or obj["error"]["code"] != "INTERNAL", (cmd, obj)
        if step % 25 == 0:
            data = fin.ok("balance")["data"] if fin.ok("account", "list")["data"]["accounts"] else None
            if data:
                assert data["consistent"] is True and data["total_dompet"] == data["total_budget"]
            check_debts_and_bills(fin)
    assert ok_count > 100,"terlalu sedikit perintah yang berhasil, tes tidak bermakna"
    budgets = fin.ok("budget", "list")["data"]
    assert budgets["consistent"] is True
    check_debts_and_bills(fin)
    # perintah tiap kelompok harus ada yang berhasil, supaya tes ini benar-benar menguji kelompok itu
    for group in ("debt", "recurring", "batch"):
        assert ok_by_command.get(group, 0) >= 2, ok_by_command


def check_debts_and_bills(fin):
    """Status hutang dan last_paid_month selalu cocok dengan transaksi aktif."""
    import sqlite3
    conn = sqlite3.connect(fin.home / "finance.db")
    try:
        for debt_id, direction, principal, status in conn.execute(
                "SELECT id, direction, principal, status FROM debts"):
            pay_type = "debt_out" if direction == "i_owe" else "debt_in"
            paid = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE debt_id = ? AND type = ? "
                                "AND deleted_at IS NULL", (debt_id, pay_type)).fetchone()[0]
            assert 0 <= paid <= principal
            assert status == ("paid" if paid == principal else "open")
        for rec_id, last in conn.execute("SELECT id, last_paid_month FROM recurring"):
            expected = conn.execute("SELECT MAX(p.month) FROM recurring_payments p JOIN transactions t "
                                    "ON t.id = p.tx_id WHERE p.recurring_id = ? AND t.deleted_at IS NULL",
                                    (rec_id,)).fetchone()[0]
            assert last == expected
    finally:
        conn.close()
