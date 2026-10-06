"""Tagihan rutin. Bulan yang sudah dibayar dihitung dari recurring_payments yang transaksinya masih aktif."""
import calendar
from datetime import date

from . import clock


def due_date(day_of_month, year, month):
    """Tanggal jatuh tempo pada bulan itu. Tanggal 29-31 di bulan pendek jadi akhir bulan."""
    return date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))


def paid_months(conn, recurring_id):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT p.month FROM recurring_payments p JOIN transactions t ON t.id = p.tx_id "
        "WHERE p.recurring_id = ? AND t.deleted_at IS NULL ORDER BY p.month", (recurring_id,))]


def recompute_last_paid(conn, recurring_id):
    months = paid_months(conn, recurring_id)
    conn.execute("UPDATE recurring SET last_paid_month = ? WHERE id = ?",
                 (months[-1] if months else None, recurring_id))


def ids_for_transactions(conn, tx_ids):
    if not tx_ids:
        return []
    marks = ",".join("?" * len(tx_ids))
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT recurring_id FROM recurring_payments WHERE tx_id IN ({marks})", list(tx_ids))]


def is_used(conn, recurring_id):
    return conn.execute("SELECT 1 FROM recurring_payments WHERE recurring_id = ? LIMIT 1",
                        (recurring_id,)).fetchone() is not None


def month_status(conn, rec, today=None):
    """Status tagihan untuk bulan berjalan."""
    today = today or clock.today()
    month = today.strftime("%Y-%m")
    due = due_date(rec["day_of_month"], today.year, today.month)
    paid = month in paid_months(conn, rec["id"])
    return {"month": month, "due_date": due.isoformat(), "paid": paid,
            "days_until_due": (due - today).days}
