"""Ringkasan pemasukan/pengeluaran per kategori untuk satu periode."""
from .output import percent


def summarize(conn, period, kind, account_ids=None, category_ids=None):
    """Hanya type income atau expense yang dihitung. Transfer, hutang, penyesuaian tidak pernah masuk."""
    assert kind in ("income", "expense")
    start, end = period.bounds()
    sql = ("SELECT c.name AS category, SUM(t.amount) AS amount, COUNT(*) AS count "
           "FROM transactions t JOIN categories c ON c.id = t.category_id "
           "WHERE t.deleted_at IS NULL AND t.type = ? AND t.ts BETWEEN ? AND ?")
    params = [kind, start, end]
    if account_ids:
        sql += f" AND t.account_id IN ({','.join('?' * len(account_ids))})"
        params += account_ids
    if category_ids:
        sql += f" AND t.category_id IN ({','.join('?' * len(category_ids))})"
        params += category_ids
    sql += " GROUP BY c.id ORDER BY amount DESC, c.name"
    rows = conn.execute(sql, params).fetchall()
    total = sum(r["amount"] for r in rows)
    count = sum(r["count"] for r in rows)
    return {
        "total": total,
        "count": count,
        "by_category": [{"category": r["category"], "amount": r["amount"], "percent": percent(r["amount"], total),
                         "count": r["count"]} for r in rows],
    }
