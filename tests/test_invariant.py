"""Aturan utama: total semua dompet selalu sama dengan total semua budget, setelah perintah apa pun.

Fin.__call__ sudah memeriksa aturan ini langsung dari tabel setelah setiap perintah. Tes ini
menjalankan ratusan perintah acak (sah maupun tidak) dengan seed tetap.
"""
import random

import pytest

ACCOUNTS = ["tunai", "tunai", "bri", "bri", "gopay", "dana"]
CATEGORIES = ["makan", "jajan", "transport", "belanja", "hiburan", "kesehatan", "kucing", "biaya admin", "lainnya"]
BUDGETS = CATEGORIES + ["belum teralokasi", "tabungan", "laptop", "liburan"]
AMOUNTS = ["5k", "10k", "25rb", "50.000", "100k", "1,5jt"] * 3 + ["0", "abc", "-5k", "all"]


def random_command(rng, max_id):
    acc, acc2 = rng.sample(ACCOUNTS, 2)
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
    ]
    weights = [w for w, _ in choices]
    return rng.choices([c for _, c in choices], weights=weights)[0]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_wallets_equal_budgets_after_random_commands(fin, seed):
    rng = random.Random(seed)
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "200k")
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "1jt")
    fin.ok("savings", "add", "tabungan")
    ok_count = 0
    for step in range(300):
        cmd = random_command(rng, max_id=fin.max_tx_id())
        obj = fin(*cmd)  # memeriksa aturan utama dari tabel
        ok_count += obj["ok"]
        if step % 25 == 0:
            data = fin.ok("balance")["data"] if fin.ok("account", "list")["data"]["accounts"] else None
            if data:
                assert data["consistent"] is True and data["total_dompet"] == data["total_budget"]
    assert ok_count > 120, "terlalu sedikit perintah yang berhasil, tes tidak bermakna"
    budgets = fin.ok("budget", "list")["data"]
    assert budgets["consistent"] is True
