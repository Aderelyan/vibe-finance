"""Menulis transaksi dan menghitung saldo. Saldo tidak pernah disimpan."""
import json
import uuid

from . import clock
from .output import fmt_ts, rupiah

TYPE_LABEL = {
    "income": "pemasukan", "expense": "pengeluaran", "transfer": "transfer",
    "adjustment": "penyesuaian", "debt_in": "hutang/piutang masuk", "debt_out": "hutang/piutang keluar",
}
ACCOUNT_TYPE_LABEL = {"cash": "tunai", "bank": "bank", "ewallet": "e-wallet"}

TX_SELECT = ("SELECT t.*, a.name AS account, b.name AS to_account, c.name AS category, bu.name AS budget "
             "FROM transactions t JOIN accounts a ON a.id = t.account_id "
             "LEFT JOIN accounts b ON b.id = t.to_account_id "
             "LEFT JOIN categories c ON c.id = t.category_id "
             "LEFT JOIN budgets bu ON bu.id = t.budget_id")


def new_group(conn, action, restore=None):
    """Satu pemanggilan perintah = satu group. Urutan op_groups.id dipakai undo.

    restore: [[tabel, id], ...] yang diaktifkan lagi (archived = 0) jika group ini di-undo.
    """
    group_id = uuid.uuid4().hex[:12]
    conn.execute("INSERT INTO op_groups(group_id, action, restore, created_at) VALUES (?,?,?,?)",
                 (group_id, action, json.dumps(restore) if restore else None, clock.now_ts()))
    return group_id


def insert_tx(conn, *, ts, type, amount, account_id, group_id, budget_id=None, to_account_id=None,
              category_id=None, debt_id=None, note=None, raw_text=None):
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise TypeError("amount harus integer")
    if type == "adjustment":
        assert amount != 0
    else:
        assert amount > 0
    # aturan utama total dompet = total budget: semua selain transfer wajib punya budget
    if type == "transfer":
        assert budget_id is None, "transfer tidak boleh punya budget"
    else:
        assert budget_id is not None, f"transaksi {type} wajib punya budget"
    cur = conn.execute(
        "INSERT INTO transactions(ts, type, amount, account_id, to_account_id, category_id, debt_id, budget_id, "
        "note, raw_text, group_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, type, amount, account_id, to_account_id, category_id, debt_id, budget_id, note or None,
         raw_text or None, group_id, clock.now_ts()))
    return cur.lastrowid


_BALANCE_SQL = """
SELECT acc, SUM(delta) AS bal FROM (
  SELECT account_id AS acc,
         CASE WHEN type IN ('income','debt_in','adjustment') THEN amount ELSE -amount END AS delta
    FROM transactions WHERE deleted_at IS NULL
  UNION ALL
  SELECT to_account_id AS acc, amount AS delta
    FROM transactions WHERE deleted_at IS NULL AND type = 'transfer'
) GROUP BY acc
"""


def balances(conn):
    """{account_id: saldo} untuk semua dompet (yang tanpa transaksi bernilai 0)."""
    result = {r["id"]: 0 for r in conn.execute("SELECT id FROM accounts")}
    for r in conn.execute(_BALANCE_SQL):
        result[r["acc"]] = r["bal"]
    return result


def balance(conn, account_id):
    return balances(conn).get(account_id, 0)


def balance_sentence(conn, account_ids):
    """'Sisa tunai Rp137.000.' plus peringatan bila ada yang minus."""
    bals = balances(conn)
    parts, negatives = [], []
    for acc_id in dict.fromkeys(account_ids):
        name = conn.execute("SELECT name FROM accounts WHERE id = ?", (acc_id,)).fetchone()["name"]
        parts.append(f"{name} {rupiah(bals[acc_id])}")
        if bals[acc_id] < 0:
            negatives.append(name)
    text = "Sisa " + ", ".join(parts) + "."
    if negatives:
        text += f" Peringatan: saldo {', '.join(negatives)} minus. Cek lagi apakah ada transaksi yang terlewat."
    return text


def get_tx(conn, tx_id, include_deleted=False):
    sql = TX_SELECT + " WHERE t.id = ?" + ("" if include_deleted else " AND t.deleted_at IS NULL")
    return conn.execute(sql, (tx_id,)).fetchone()


def tx_dict(row):
    return {k: row[k] for k in ("id", "ts", "type", "amount", "account", "to_account", "category", "budget",
                                "debt_id", "note", "raw_text", "group_id", "deleted_at")}


def tx_line(row):
    """'#12 06/10/2026 14:30 · pengeluaran Rp15.000 · ayam goreng [makan] · tunai'"""
    if row["type"] == "transfer":
        where = f"{row['account']} → {row['to_account']}"
    else:
        where = row["account"]
    amount = rupiah(row["amount"]) if row["type"] != "adjustment" else (
        ("+" if row["amount"] > 0 else "") + rupiah(row["amount"]))
    desc = row["note"] or "(tanpa catatan)"
    if row["category"]:
        desc += f" [{row['category']}]"
    if row["budget"] and row["type"] == "expense" and row["budget"] != row["category"]:
        desc += f" (budget {row['budget']})"
    line = f"#{row['id']} {fmt_ts(row['ts'])} · {TYPE_LABEL[row['type']]} {amount} · {desc} · {where}"
    if row["deleted_at"]:
        line += " (dihapus)"
    return line
