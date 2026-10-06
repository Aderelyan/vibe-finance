"""Fakta untuk analisis pengeluaran. Tidak memberi nasihat, hanya angka yang sudah dihitung."""
import calendar
from datetime import timedelta

from . import budgets, clock, debts
from .output import percent
from .parse import Period, add_months
from .report import summarize

SMALL_LIMIT = 20_000      # pengeluaran kecil: di bawah Rp20.000
SMALL_MIN_COUNT = 6       # "lebih dari 5 kali"
TOP_N = 5
DUE_SOON_DAYS = 7


def _month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def previous_period(period):
    """Periode sebelumnya yang sama panjang.

    Periode yang mulai tanggal 1 dibandingkan per bulan kalender (1-6 Oktober dengan 1-6 September,
    September penuh dengan Agustus penuh). Periode lain digeser sejumlah harinya.
    """
    s, e = period.start, period.end
    if s.day == 1:
        months = (e.year - s.year) * 12 + e.month - s.month + 1
        ps = add_months(s, -months)
        pe = _month_end(add_months(e.replace(day=1), -months)) if e == _month_end(e) else add_months(e, -months)
    else:
        days = period.days()
        ps, pe = s - timedelta(days=days), e - timedelta(days=days)
    return Period("previous", "periode sebelumnya", ps, pe)


def _change(current, previous):
    return {"current": current, "previous": previous, "difference": current - previous,
            "percent": percent(current - previous, previous) if previous else None}


def _div(total, n):
    """Pembagian bulat ke rupiah terdekat, tanpa float."""
    return (total + n // 2) // n if n else 0


def _expense_rows(conn, period, columns):
    start, end = period.bounds()
    return conn.execute(f"SELECT {columns} FROM transactions t LEFT JOIN categories c ON c.id = t.category_id "
                        "LEFT JOIN accounts a ON a.id = t.account_id "
                        "WHERE t.deleted_at IS NULL AND t.type = 'expense' AND t.ts BETWEEN ? AND ?",
                        (start, end)).fetchall()


def daily_stats(conn, period):
    rows = conn.execute("SELECT substr(ts, 1, 10) AS day, SUM(amount) AS amount, COUNT(*) AS count "
                        "FROM transactions WHERE deleted_at IS NULL AND type = 'expense' AND ts BETWEEN ? AND ? "
                        "GROUP BY day ORDER BY amount DESC, day", period.bounds()).fetchall()
    total = sum(r["amount"] for r in rows)
    days = period.days()
    busiest = {"date": rows[0]["day"], "amount": rows[0]["amount"], "count": rows[0]["count"]} if rows else None
    return {"days": days, "average_per_day": _div(total, days), "busiest_day": busiest,
            "days_with_spending": len(rows), "days_without_spending": days - len(rows)}


def top_transactions(conn, period, n=TOP_N):
    rows = _expense_rows(conn, period, "t.id, t.ts, t.amount, t.note, c.name AS category, a.name AS account")
    rows = sorted(rows, key=lambda r: (-r["amount"], r["ts"], r["id"]))[:n]
    return [{"id": r["id"], "ts": r["ts"], "amount": r["amount"], "note": r["note"], "category": r["category"],
             "account": r["account"]} for r in rows]


def frequent_small(conn, period):
    """Catatan yang sama (tidak peka huruf besar kecil) di bawah Rp20.000 yang muncul lebih dari 5 kali."""
    groups = {}
    for r in _expense_rows(conn, period, "t.amount, t.note, c.name AS category"):
        if r["amount"] >= SMALL_LIMIT or not r["note"]:
            continue
        key = " ".join(r["note"].lower().split())
        g = groups.setdefault(key, {"note": key, "count": 0, "total": 0, "category": r["category"]})
        g["count"] += 1
        g["total"] += r["amount"]
    items = [g for g in groups.values() if g["count"] >= SMALL_MIN_COUNT]
    return sorted(items, key=lambda g: (-g["total"], g["note"]))


def budget_status(conn, period):
    spent = {r["budget_id"]: r["amount"] for r in conn.execute(
        "SELECT budget_id, SUM(amount) AS amount FROM transactions WHERE deleted_at IS NULL AND type = 'expense' "
        "AND ts BETWEEN ? AND ? GROUP BY budget_id", period.bounds())}
    ov = budgets.overview(conn)
    shown = {b["id"] for b in ov["budgets"]}
    items = [{"name": b["name"], "kind": b["kind"], "balance": b["balance"], "archived": b["archived"],
              "spent_in_period": spent.get(b["id"], 0)} for b in ov["budgets"]]
    bals = budgets.balances(conn)
    for bud_id, amount in spent.items():  # budget ditutup tanpa sisa tapi ada pengeluaran di periode ini
        if bud_id not in shown:
            row = budgets.get(conn, bud_id)
            items.append({"name": row["name"], "kind": row["kind"], "balance": bals[bud_id], "archived": True,
                          "spent_in_period": amount})
    return {"budgets": items, "negative": [i["name"] for i in items if i["balance"] < 0]}


def projection(conn, period, expense_total):
    """Proyeksi pengeluaran sampai akhir bulan, hanya untuk periode bulan berjalan."""
    today = clock.today()
    if period.start != today.replace(day=1) or period.end != today:
        return None
    elapsed = period.days()
    month_days = calendar.monthrange(today.year, today.month)[1]
    return {"days_elapsed": elapsed, "days_in_month": month_days,
            "average_per_day": _div(expense_total, elapsed),
            "projected_expense": _div(expense_total * month_days, elapsed)}


def debt_status(conn):
    owe, owed = debts.totals(conn)
    due = []
    for d in conn.execute("SELECT * FROM debts WHERE status = 'open' AND archived = 0 AND due_date IS NOT NULL "
                          "ORDER BY due_date, id").fetchall():
        days = debts.days_until(d["due_date"])
        if days <= DUE_SOON_DAYS:
            due.append({"id": d["id"], "direction": d["direction"], "person": d["person"],
                        "remaining": debts.remaining(conn, d), "due_date": d["due_date"], "days_until_due": days})
    return {"debt_total": owe, "receivable_total": owed, "due_within_7_days": due}


def analyze(conn, period):
    exp = summarize(conn, period, "expense")
    inc = summarize(conn, period, "income")
    net = inc["total"] - exp["total"]
    prev = previous_period(period)
    prev_exp = summarize(conn, prev, "expense")
    prev_inc = summarize(conn, prev, "income")

    cur_by = {c["category"]: c["amount"] for c in exp["by_category"]}
    prev_by = {c["category"]: c["amount"] for c in prev_exp["by_category"]}
    names = sorted(set(cur_by) | set(prev_by), key=lambda n: (-cur_by.get(n, 0), -prev_by.get(n, 0), n))
    return {
        "period": period.to_dict(),
        "income_total": inc["total"],
        "expense_total": exp["total"],
        "net": net,
        "savings_rate": percent(net, inc["total"]) if inc["total"] > 0 else None,
        "expense_count": exp["count"],
        "expense_by_category": exp["by_category"],
        "comparison": {
            "previous_period": prev.to_dict(),
            "expense": _change(exp["total"], prev_exp["total"]),
            "income": _change(inc["total"], prev_inc["total"]),
            "by_category": [{"category": n, **_change(cur_by.get(n, 0), prev_by.get(n, 0))} for n in names],
        },
        "daily": daily_stats(conn, period),
        "top_expenses": top_transactions(conn, period),
        "frequent_small": frequent_small(conn, period),
        "budget_status": budget_status(conn, period),
        "projection": projection(conn, period, exp["total"]),
        "debts": debt_status(conn),
    }
