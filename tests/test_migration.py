"""Migrasi database versi 1 (dompet savings) ke versi 2 (budget amplop)."""
import sqlite3

from fin import db

T = "2026-09-01 10:00:00"


def make_v1(path):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")
    db.MIGRATIONS[1](conn)
    db.set_meta(conn, "schema_version", 1)
    acc = "INSERT INTO accounts(id, name, type, is_default, target_amount, target_date, archived, created_at) " \
          "VALUES (?,?,?,?,?,?,?,?)"
    conn.execute(acc, (1, "tunai", "cash", 1, None, None, 0, T))
    conn.execute(acc, (2, "bri", "bank", 0, None, None, 0, T))
    conn.execute(acc, (3, "tabungan", "savings", 0, 2_000_000, "2027-01-01", 0, T))
    conn.execute(acc, (4, "celengan", "savings", 0, None, None, 0, T))
    makan = conn.execute("SELECT id FROM categories WHERE name='makan' AND kind='expense'").fetchone()[0]
    gaji = conn.execute("SELECT id FROM categories WHERE name='gaji' AND kind='income'").fetchone()[0]
    tx = "INSERT INTO transactions(ts, type, amount, account_id, to_account_id, category_id, note, group_id, " \
         "created_at, deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    conn.execute(tx, (T, "adjustment", 100_000, 1, None, None, "saldo awal", "g1", T, None))
    conn.execute(tx, (T, "adjustment", 500_000, 2, None, None, "saldo awal", "g2", T, None))
    conn.execute(tx, (T, "income", 600_000, 2, None, gaji, "gajian", "g3", T, None))
    conn.execute(tx, (T, "expense", 20_000, 1, None, makan, "nasi", "g4", T, None))
    conn.execute(tx, (T, "transfer", 150_000, 2, 3, None, None, "g5", T, None))
    conn.execute(tx, (T, "transfer", 30_000, 2, 3, None, None, "g6", T, T))  # terhapus
    conn.execute(tx, (T, "transfer", 10_000, 4, 1, None, None, "g7", T, None))  # celengan jadi minus
    conn.execute("COMMIT")
    conn.close()


def test_migrate_v1_to_latest(fin_home):
    """v1 (dompet savings) -> v2 (budget tabungan) -> v4 (tabungan jadi akun terpisah).

    Uang di dompet lama tidak berubah. Budget tabungan hasil v2 dikembalikan ke 'belum teralokasi' dan dibuat akun
    tabungan kosong dengan target yang sama (nama dompet lama sudah terpakai, jadi diberi akhiran).
    """
    home, fin = fin_home
    make_v1(home / "finance.db")
    r = fin.ok("init")
    assert r["data"]["schema_version"] == db.SCHEMA_VERSION and r["data"]["created"] is False
    assert any(p.name.endswith(f"pre-v{db.SCHEMA_VERSION}.db") for p in (home / "backups").iterdir())

    accounts = {a["name"]: a for a in fin.ok("account", "list")["data"]["accounts"]}
    assert accounts["tabungan"]["type"] == "bank" and accounts["celengan"]["type"] == "bank"
    assert accounts["tabungan"]["balance"] == 150_000
    assert accounts["celengan"]["balance"] == -10_000
    assert accounts["tunai"]["is_default"] is True

    savings = {s["name"]: s for s in fin.ok("savings", "list")["data"]["savings"]}
    assert set(savings) == {"tabungan (tabungan)", "celengan (tabungan)"}
    assert savings["tabungan (tabungan)"]["balance"] == 0
    assert savings["tabungan (tabungan)"]["target_amount"] == 2_000_000
    assert savings["tabungan (tabungan)"]["target_date"] == "2027-01-01"

    bal = fin.ok("balance")["data"]
    assert bal["total_dompet"] == 100_000 + 500_000 + 600_000 - 20_000 and bal["total_tabungan"] == 0
    assert bal["consistent"] is True
    unalloc = bal["budgets"][0]
    assert unalloc["name"] == "belum teralokasi" and unalloc["balance"] == bal["total_dompet"]
    assert all(b["kind"] != "savings" for b in bal["budgets"])

    # semua transaksi lama (selain transfer) menunjuk ke belum teralokasi
    txs = fin.ok("list", "--period", "all", "--include-deleted")["data"]["transactions"]
    assert all((t["budget"] is None) == (t["type"] == "transfer") for t in txs)
    assert {t["budget"] for t in txs if t["type"] != "transfer"} == {"belum teralokasi"}

    # undo tidak membatalkan pindahan hasil migrasi; yang dibatalkan transaksi terakhir (g7)
    r = fin.ok("undo")
    assert r["data"]["undone"] and r["data"]["transactions"][0]["note"] is None
    assert r["data"]["transactions"][0]["type"] == "transfer"
    assert fin.ok("balance")["data"]["consistent"] is True

    # foreign key tetap utuh
    conn = sqlite3.connect(home / "finance.db")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_migrate_v2_to_v3(fin_home):
    """Tagihan rutin lama (kolom active) dan hutang lama ikut terbawa."""
    home, fin = fin_home
    conn = sqlite3.connect(home / "finance.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")
    db.MIGRATIONS[1](conn)
    db.MIGRATIONS[2](conn)
    db.set_meta(conn, "schema_version", 2)
    conn.execute("INSERT INTO accounts(id, name, type, is_default, created_at) VALUES (1, 'tunai', 'cash', 1, ?)", (T,))
    conn.execute("INSERT INTO recurring(name, amount, day_of_month, active) VALUES ('kos', 500000, 5, 1)")
    conn.execute("INSERT INTO recurring(name, amount, day_of_month, active) VALUES ('gym', 100000, 1, 0)")
    conn.execute("INSERT INTO debts(direction, person, principal, created_at) VALUES ('i_owe', 'Budi', 50000, ?)", (T,))
    conn.execute("COMMIT")
    conn.close()

    assert fin.ok("init")["data"]["schema_version"] == db.SCHEMA_VERSION
    assert any(p.name.endswith(f"pre-v{db.SCHEMA_VERSION}.db") for p in (home / "backups").iterdir())
    items = {r["name"]: r for r in fin.ok("recurring", "list", "--all")["data"]["recurring"]}
    assert items["kos"]["archived"] is False and items["gym"]["archived"] is True
    assert fin.ok("debt", "list")["data"]["debts"][0]["person"] == "Budi"
    fin.ok("recurring", "pay", "kos")
    conn = sqlite3.connect(home / "finance.db")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_migrate_v3_to_v4_savings_budget(fin_home):
    """Budget tabungan bersaldo (model lama) menjadi akun tabungan; saldonya kembali ke 'belum teralokasi'."""
    home, fin = fin_home
    conn = sqlite3.connect(home / "finance.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")
    for v in (1, 2, 3):
        db.MIGRATIONS[v](conn)
    db.set_meta(conn, "schema_version", 3)
    conn.execute("INSERT INTO accounts(id, name, type, is_default, created_at) VALUES (1, 'bri', 'bank', 1, ?)", (T,))
    unalloc = conn.execute("SELECT id FROM budgets WHERE kind = 'unallocated'").fetchone()[0]
    sav = conn.execute("INSERT INTO budgets(name, kind, target_amount, created_at) VALUES ('laptop', 'savings', "
                       "8000000, ?)", (T,)).lastrowid
    makan = conn.execute("SELECT id FROM categories WHERE name = 'makan' AND kind = 'expense'").fetchone()[0]
    tx = "INSERT INTO transactions(ts, type, amount, account_id, category_id, budget_id, note, group_id, created_at) " \
         "VALUES (?,?,?,?,?,?,?,?,?)"
    conn.execute(tx, (T, "adjustment", 1_000_000, 1, None, unalloc, "saldo awal", "g1", T))
    conn.execute("INSERT INTO budget_moves(ts, from_budget_id, to_budget_id, amount, group_id, created_at) "
                 "VALUES (?,?,?,?,?,?)", (T, unalloc, sav, 300_000, "g2", T))
    conn.execute(tx, (T, "expense", 50_000, 1, makan, sav, "makan dari tabungan", "g3", T))
    for g in ("g1", "g2", "g3"):
        conn.execute("INSERT INTO op_groups(group_id, action, created_at) VALUES (?, 'legacy', ?)", (g, T))
    conn.execute("COMMIT")
    conn.close()

    assert fin.ok("init")["data"]["schema_version"] == 4
    bal = fin.ok("balance")["data"]
    assert bal["total_dompet"] == 950_000 and bal["consistent"] is True
    assert bal["budgets"] == [{"id": unalloc, "name": "belum teralokasi", "kind": "unallocated", "balance": 950_000,
                               "archived": False}]
    sv = fin.ok("savings", "list")["data"]["savings"]
    assert sv[0]["name"] == "laptop" and sv[0]["balance"] == 0 and sv[0]["target_amount"] == 8_000_000
    # pindahan migrasi tidak bisa di-undo; undo membatalkan pengeluaran lama
    assert fin.ok("undo")["data"]["action"] == "legacy"
    # skema baru menerima tabungan sebagai akun
    fin.ok("savings", "deposit", "--from", "bri", "--to", "laptop", "--amount", "100k")
    assert fin.ok("savings", "list")["data"]["total"] == 100_000
    conn = sqlite3.connect(home / "finance.db")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
