"""Hitungan hutang piutang. Sisa selalu dihitung dari transaksi pembayaran."""

# jenis transaksi yang dihitung sebagai pembayaran untuk tiap arah
PAYMENT_TYPE = {"i_owe": "debt_out", "owed_to_me": "debt_in"}
OPENING_TYPE = {"i_owe": "debt_in", "owed_to_me": "debt_out"}


def paid(conn, debt):
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions "
                       "WHERE debt_id = ? AND type = ? AND deleted_at IS NULL",
                       (debt["id"], PAYMENT_TYPE[debt["direction"]])).fetchone()
    return row[0]


def remaining(conn, debt):
    return debt["principal"] - paid(conn, debt)


def recompute_status(conn, debt_id):
    debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    if debt is None:
        return
    status = "paid" if remaining(conn, debt) <= 0 else "open"
    conn.execute("UPDATE debts SET status = ? WHERE id = ?", (status, debt_id))


def totals(conn):
    """(total hutang saya, total piutang) dari hutang yang masih terbuka."""
    owe = owed = 0
    for debt in conn.execute("SELECT * FROM debts WHERE status = 'open'").fetchall():
        rest = max(remaining(conn, debt), 0)
        if debt["direction"] == "i_owe":
            owe += rest
        else:
            owed += rest
    return owe, owed
