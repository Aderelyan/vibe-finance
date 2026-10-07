"""Menulis transaksi dan menghitung saldo. Saldo tidak pernah disimpan.

Dua kelas akun:
- dompet operasional (cash, bank, ewallet): totalnya selalu sama dengan total budget (aturan utama);
- tabungan (savings): di luar aturan utama, tidak pernah menyentuh budget kecuali lewat deposit/withdraw.

Efek tiap jenis transaksi (O = dompet operasional, T = tabungan, B = budget):
  income, debt_in        O +X, B +X        (di tabungan: hanya T, tanpa budget)
  expense, debt_out      O -X, B -X        (expense di tabungan = spend purpose: T -X, tanpa budget)
  adjustment             O ±X, B ±X        (di tabungan: T ±X, tanpa budget)
  transfer               O -X, O +X        (hanya antar dompet operasional, atau antar tabungan)
  deposit                O -X, T +X, B -X  (menabung, budget sumber berkurang)
  withdraw               T -X, O +X, B +X  (menarik tabungan, budget tujuan bertambah)
  savings_loan           T -X              (spend mode debt: pinjam dari tabungan, belum jadi pengeluaran)
  savings_repay          T +X              (pelunasan; pasangannya expense di dompet operasional)
Setiap baris seimbang sendiri, jadi aturan utama tetap benar setelah delete/undo transaksi mana pun.
"""
import json
import uuid

from . import clock
from .output import fmt_ts, rupiah

TYPE_LABEL = {
    "income": "pemasukan", "expense": "pengeluaran", "transfer": "transfer",
    "adjustment": "penyesuaian", "debt_in": "hutang/piutang masuk", "debt_out": "hutang/piutang keluar",
    "deposit": "menabung", "withdraw": "tarik tabungan", "savings_loan": "pinjam dari tabungan",
    "savings_repay": "kembali ke tabungan",
}
ACCOUNT_TYPE_LABEL = {"cash": "tunai", "bank": "bank", "ewallet": "e-wallet", "savings": "tabungan"}
OPERATIONAL_TYPES = ("cash", "bank", "ewallet")

# saldo akun: jenis yang menambah akun utama (account_id); sisanya mengurangi
ACCOUNT_PLUS = ("income", "debt_in", "adjustment", "savings_repay")
# jenis yang juga menambah akun tujuan (to_account_id)
TWO_SIDED = ("transfer", "deposit", "withdraw")
# saldo budget: jenis yang menambah budget; sisanya (jika budget_id terisi) mengurangi
BUDGET_PLUS = ("income", "debt_in", "adjustment", "withdraw")

TX_SELECT = ("SELECT t.*, a.name AS account, a.type AS account_type, b.name AS to_account, c.name AS category, "
             "bu.name AS budget FROM transactions t JOIN accounts a ON a.id = t.account_id "
             "LEFT JOIN accounts b ON b.id = t.to_account_id "
             "LEFT JOIN categories c ON c.id = t.category_id "
             "LEFT JOIN budgets bu ON bu.id = t.budget_id")


def _in(values):
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


def new_group(conn, action, restore=None):
    """Satu pemanggilan perintah = satu group. Urutan op_groups.id dipakai undo.

    restore: [[tabel, id], ...] yang diaktifkan lagi (archived = 0) jika group ini di-undo.
    Di dalam batch, semua perintah memakai group batch; restore-nya digabung.
    """
    if conn.batch_group is not None:
        add_restore(conn, conn.batch_group, restore)
        return conn.batch_group
    group_id = uuid.uuid4().hex[:12]
    conn.execute("INSERT INTO op_groups(group_id, action, restore, created_at) VALUES (?,?,?,?)",
                 (group_id, action, json.dumps(restore) if restore else None, clock.now_ts()))
    return group_id


def add_restore(conn, group_id, restore):
    """Tambahkan entri restore ke group yang sudah ada (mis. id baru diketahui setelah group dibuat)."""
    if not restore:
        return
    row = conn.execute("SELECT restore FROM op_groups WHERE group_id = ?", (group_id,)).fetchone()
    merged = (json.loads(row["restore"]) if row["restore"] else []) + restore
    conn.execute("UPDATE op_groups SET restore = ? WHERE group_id = ?", (json.dumps(merged), group_id))


def is_savings(conn, account_id):
    return conn.execute("SELECT type FROM accounts WHERE id = ?", (account_id,)).fetchone()["type"] == "savings"


def needs_budget(conn, type, account_id, to_account_id=None):
    """Apakah transaksi ini wajib menunjuk ke budget (supaya total dompet = total budget tetap benar)."""
    if type in ("deposit", "withdraw"):
        return True
    if type in ("transfer", "savings_loan", "savings_repay"):
        return False
    return not is_savings(conn, account_id)


def insert_tx(conn, *, ts, type, amount, account_id, group_id, budget_id=None, to_account_id=None,
              category_id=None, debt_id=None, note=None, raw_text=None):
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise TypeError("amount harus integer")
    if type == "adjustment":
        assert amount != 0
    else:
        assert amount > 0
    src_savings = is_savings(conn, account_id)
    if type in TWO_SIDED:
        dst_savings = is_savings(conn, to_account_id)
        expected = {"transfer": (src_savings, src_savings), "deposit": (False, True), "withdraw": (True, False)}
        assert (src_savings, dst_savings) == expected[type], f"{type}: kelas akun asal/tujuan salah"
    else:
        assert to_account_id is None
        if type in ("savings_loan", "savings_repay"):
            assert src_savings, f"{type} hanya untuk akun tabungan"
        elif type in ("debt_in", "debt_out"):
            assert not src_savings, "hutang piutang biasa hanya lewat dompet operasional"
    # aturan utama: hanya transaksi yang mengubah total dompet operasional yang menunjuk ke budget
    if needs_budget(conn, type, account_id, to_account_id):
        assert budget_id is not None, f"transaksi {type} wajib punya budget"
    else:
        assert budget_id is None, f"transaksi {type} di akun ini tidak boleh punya budget"
    cur = conn.execute(
        "INSERT INTO transactions(ts, type, amount, account_id, to_account_id, category_id, debt_id, budget_id, "
        "note, raw_text, group_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, type, amount, account_id, to_account_id, category_id, debt_id, budget_id, note or None,
         raw_text or None, group_id, clock.now_ts()))
    return cur.lastrowid


_BALANCE_SQL = f"""
SELECT acc, SUM(delta) AS bal FROM (
  SELECT account_id AS acc,
         CASE WHEN type IN {_in(ACCOUNT_PLUS)} THEN amount ELSE -amount END AS delta
    FROM transactions WHERE deleted_at IS NULL
  UNION ALL
  SELECT to_account_id AS acc, amount AS delta
    FROM transactions WHERE deleted_at IS NULL AND type IN {_in(TWO_SIDED)}
) GROUP BY acc
"""

# delta saldo akun untuk satu baris transaksi t, dari sisi akun :acc (dipakai perubahan bulanan tabungan)
ACCOUNT_DELTA_SQL = (f"CASE WHEN t.to_account_id = :acc AND t.type IN {_in(TWO_SIDED)} THEN t.amount "
                     f"WHEN t.type IN {_in(ACCOUNT_PLUS)} THEN t.amount ELSE -t.amount END")
BUDGET_SIGN_SQL = f"CASE WHEN type IN {_in(BUDGET_PLUS)} THEN amount ELSE -amount END"


def balances(conn):
    """{account_id: saldo} untuk semua akun, dompet maupun tabungan (yang tanpa transaksi bernilai 0)."""
    result = {r["id"]: 0 for r in conn.execute("SELECT id FROM accounts")}
    for r in conn.execute(_BALANCE_SQL):
        result[r["acc"]] = r["bal"]
    return result


def balance(conn, account_id):
    return balances(conn).get(account_id, 0)


def operational_total(conn, bals=None):
    bals = bals if bals is not None else balances(conn)
    return sum(bals[r["id"]] for r in conn.execute("SELECT id FROM accounts WHERE type != 'savings'"))


def balance_sentence(conn, account_ids):
    """'Sisa tunai Rp137.000.' plus peringatan bila ada yang minus."""
    bals = balances(conn)
    parts, negatives = [], []
    for acc_id in dict.fromkeys(account_ids):
        row = conn.execute("SELECT name, type FROM accounts WHERE id = ?", (acc_id,)).fetchone()
        label = ("tabungan " if row["type"] == "savings" else "") + row["name"]
        parts.append(f"{label} {rupiah(bals[acc_id])}")
        if bals[acc_id] < 0:
            negatives.append(row["name"])
    text = "Sisa " + ", ".join(parts) + "."
    if negatives:
        text += f" Peringatan: saldo {', '.join(negatives)} minus. Cek lagi apakah ada transaksi yang terlewat."
    return text


def get_tx(conn, tx_id, include_deleted=False):
    sql = TX_SELECT + " WHERE t.id = ?" + ("" if include_deleted else " AND t.deleted_at IS NULL")
    return conn.execute(sql, (tx_id,)).fetchone()


def source_of(row):
    """'tabungan' jika transaksi ini terjadi di akun tabungan, selain itu 'dompet'."""
    return "tabungan" if row["account_type"] == "savings" else "dompet"


def tx_dict(row):
    d = {k: row[k] for k in ("id", "ts", "type", "amount", "account", "to_account", "category", "budget",
                             "debt_id", "note", "raw_text", "group_id", "deleted_at")}
    d["source"] = "savings" if row["account_type"] == "savings" else "wallet"
    return d


def tx_line(row):
    """'#12 06/10/2026 14:30 · pengeluaran Rp15.000 · ayam goreng [makan] · tunai'"""
    if row["type"] in TWO_SIDED:
        where = f"{row['account']} → {row['to_account']}"
    else:
        where = row["account"] + (" (tabungan)" if row["account_type"] == "savings" else "")
    amount = rupiah(row["amount"]) if row["type"] != "adjustment" else (
        ("+" if row["amount"] > 0 else "") + rupiah(row["amount"]))
    desc = row["note"] or "(tanpa catatan)"
    if row["category"]:
        desc += f" [{row['category']}]"
    if row["budget"] and row["type"] == "expense" and row["budget"] != row["category"]:
        desc += f" (budget {row['budget']})"
    if row["budget"] and row["type"] in ("deposit", "withdraw"):
        desc += f" (budget {row['budget']})"
    label = TYPE_LABEL[row["type"]]
    if row["type"] == "expense" and row["account_type"] == "savings":
        label = "pengeluaran dari tabungan"
    line = f"#{row['id']} {fmt_ts(row['ts'])} · {label} {amount} · {desc} · {where}"
    if row["deleted_at"]:
        line += " (dihapus)"
    return line
