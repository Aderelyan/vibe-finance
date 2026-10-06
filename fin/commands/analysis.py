"""analyze / daily-check / export"""
from datetime import timedelta
from pathlib import Path

from .. import analysis, clock, db, debts
from ..output import FinError, fmt_date, fmt_pct, fmt_range, rupiah, signed_rupiah, success
from ..recurring import due_date
from .common import add_period_args, period_from_args
from .recurring import month_label

BILL_DAYS = 3     # daily-check pagi: tagihan dan hutang yang jatuh tempo dalam 3 hari (termasuk yang lewat)


def register(sub):
    p = sub.add_parser("analyze", help="Fakta untuk menilai pola pengeluaran (tanpa nasihat).")
    add_period_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("daily-check", help="Pengingat harian untuk dipanggil penjadwal.")
    p.add_argument("--when", required=True, choices=["pagi", "malam"])
    p.set_defaults(func=cmd_daily_check)

    p = sub.add_parser("export", help="Ekspor ke file Excel (.xlsx).")
    add_period_args(p)
    p.add_argument("--out", help="Path file .xlsx (bawaan: data\\exports\\keuangan-<periode>-<waktu>.xlsx).")
    p.set_defaults(func=cmd_export)


# ---------- analyze ----------

def _change_text(ch):
    if ch["previous"] == 0:
        return "periode sebelumnya belum ada" if ch["current"] else "sama-sama nol"
    word = "naik" if ch["difference"] > 0 else ("turun" if ch["difference"] < 0 else "sama")
    if word == "sama":
        return "sama dengan periode sebelumnya"
    return f"{word} {rupiah(abs(ch['difference']))} ({fmt_pct(abs(ch['percent']))})"


def analyze_message(a):
    p = a["period"]
    lines = [f"Analisis {p['label']} ({p['text']}):"]
    if a["income_total"] == 0 and a["expense_total"] == 0:
        lines.append("Belum ada pemasukan atau pengeluaran di periode ini.")
    else:
        rate = (f", rasio menabung {fmt_pct(a['savings_rate'])}" if a["savings_rate"] is not None
                else ", belum ada pemasukan")
        lines.append(f"Pemasukan {rupiah(a['income_total'])}, pengeluaran {rupiah(a['expense_total'])}, "
                     f"selisih {signed_rupiah(a['net'])}{rate}.")
        prev = a["comparison"]["previous_period"]
        lines.append(f"Pengeluaran dibanding {fmt_range(prev['start'], prev['end'])}: "
                     f"{_change_text(a['comparison']['expense'])}.")
        if a["expense_by_category"]:
            top = ", ".join(f"{c['category']} {rupiah(c['amount'])} ({fmt_pct(c['percent'])})"
                            for c in a["expense_by_category"][:3])
            lines.append(f"Kategori terbesar: {top}.")
        d = a["daily"]
        busiest = (f"; paling boros {fmt_date(d['busiest_day']['date'])} ({rupiah(d['busiest_day']['amount'])})"
                   if d["busiest_day"] else "")
        lines.append(f"Rata-rata {rupiah(d['average_per_day'])} per hari{busiest}; "
                     f"{d['days_without_spending']} dari {d['days']} hari tanpa pengeluaran.")
        if a["projection"]:
            pr = a["projection"]
            lines.append(f"Proyeksi pengeluaran sampai akhir bulan: {rupiah(pr['projected_expense'])} "
                         f"(rata-rata harian x {pr['days_in_month']} hari).")
    extra = []
    if a["frequent_small"]:
        extra.append("Pengeluaran kecil yang sering: " + ", ".join(
            f"{s['note']} {s['count']}x ({rupiah(s['total'])})" for s in a["frequent_small"][:3]) + ".")
    neg = a["budget_status"]["negative"]
    extra.append(f"Budget minus: {', '.join(neg)}." if neg else "Tidak ada budget yang minus.")
    lines.append(" ".join(extra))
    dbt = a["debts"]
    if dbt["debt_total"] or dbt["receivable_total"]:
        due = dbt["due_within_7_days"]
        lines.append(f"Hutang {rupiah(dbt['debt_total'])}, piutang {rupiah(dbt['receivable_total'])}"
                     + (f"; {len(due)} jatuh tempo dalam 7 hari." if due else "."))
    return "\n".join(lines)


def cmd_analyze(args, conn):
    period = period_from_args(conn, args)
    result = analysis.analyze(conn, period)
    return success(analyze_message(result), result)


# ---------- daily-check ----------

def _pagi(conn):
    today = clock.today()
    limit = today + timedelta(days=BILL_DAYS)
    month = today.strftime("%Y-%m")
    bills = []
    for r in conn.execute("SELECT * FROM recurring WHERE archived = 0 ORDER BY day_of_month, id"):
        paid = conn.execute("SELECT 1 FROM recurring_payments p JOIN transactions t ON t.id = p.tx_id "
                            "WHERE p.recurring_id = ? AND p.month = ? AND t.deleted_at IS NULL",
                            (r["id"], month)).fetchone()
        due = due_date(r["day_of_month"], today.year, today.month)
        if not paid and due <= limit:
            bills.append({"id": r["id"], "name": r["name"], "amount": r["amount"], "due_date": due.isoformat(),
                          "days_until_due": (due - today).days, "month": month})
    due_debts = []
    for d in conn.execute("SELECT * FROM debts WHERE status = 'open' AND archived = 0 AND due_date IS NOT NULL "
                          "ORDER BY due_date, id").fetchall():
        if debts.days_until(d["due_date"]) <= BILL_DAYS:
            due_debts.append(debts.info(conn, d))
    lines = []
    if bills:
        lines.append(f"Tagihan {month_label(month)} yang belum dibayar:")
        for b in bills:
            days = b["days_until_due"]
            when = f"lewat {-days} hari" if days < 0 else ("hari ini" if days == 0 else f"{days} hari lagi")
            lines.append(f"- {b['name']} {rupiah(b['amount'])}, jatuh tempo {fmt_date(b['due_date'])} ({when})")
    if due_debts:
        lines.append("Hutang piutang yang jatuh tempo:")
        lines += [f"- {debts.line(i)}" for i in due_debts]
    send = bool(lines)
    msg = "Selamat pagi. " + "\n".join(lines) if send else "Tidak ada tagihan atau hutang yang jatuh tempo."
    return success(msg, {"send": send, "when": "pagi", "bills": bills, "debts": due_debts})


def _malam(conn):
    today = clock.today().isoformat()
    bounds = (f"{today} 00:00:00", f"{today} 23:59:59")
    count = conn.execute("SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL AND ts BETWEEN ? AND ?",
                         bounds).fetchone()[0]
    spent, n_exp = conn.execute("SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM transactions WHERE deleted_at IS NULL "
                                "AND type = 'expense' AND ts BETWEEN ? AND ?", bounds).fetchone()
    if count == 0:
        msg = "Hari ini belum ada transaksi yang dicatat. Ada pengeluaran yang belum dicatat?"
    elif n_exp == 0:
        msg = f"Hari ini ada {count} transaksi tercatat, tanpa pengeluaran."
    else:
        msg = f"Pengeluaran hari ini {rupiah(spent)} dari {n_exp} transaksi."
    return success(msg, {"send": True, "when": "malam", "date": today, "transactions": count,
                         "expense_total": spent, "expense_count": n_exp})


def cmd_daily_check(args, conn):
    return _pagi(conn) if args.when == "pagi" else _malam(conn)


# ---------- export ----------

def _out_path(args, period):
    if args.out:
        path = Path(args.out).expanduser()
        if path.suffix.lower() != ".xlsx":
            raise FinError("BAD_ARGS", f"File ekspor harus berakhiran .xlsx: {args.out}",
                           hint="Contoh: --out laporan-oktober.xlsx")
        if path.is_dir():
            raise FinError("BAD_ARGS", f"'{args.out}' adalah folder, bukan file.")
        return path.resolve()
    stamp = clock.now().strftime("%Y%m%d-%H%M%S")
    return db.home() / "exports" / f"keuangan-{period.key.replace(':', '')}-{stamp}.xlsx"


def cmd_export(args, conn):
    from .. import export  # openpyxl berat, hanya dimuat saat ekspor
    period = period_from_args(conn, args)
    path = _out_path(args, period)
    try:
        counts = export.build(conn, period, path)
    except PermissionError:
        raise FinError("BAD_ARGS", f"File {path} tidak bisa ditulis.",
                       hint="Tutup file itu jika sedang dibuka di Excel, atau pakai --out dengan nama lain.")
    msg = (f"Ekspor {period.describe} tersimpan di {path}. Isi: {counts['transactions']} transaksi, "
           f"ringkasan per kategori, saldo {counts['accounts']} dompet, {counts['budgets']} budget, "
           f"{counts['debts']} hutang piutang.")
    return success(msg, {"path": str(path), "period": period.to_dict(), "counts": counts})
