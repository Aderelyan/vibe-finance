"""balance / report / list"""
from .. import budgets, debts, resolve
from ..ledger import ACCOUNT_TYPE_LABEL, TX_SELECT, balances, tx_dict, tx_line
from ..output import FinError, fmt_pct, rupiah, success
from ..report import summarize
from .budget import overview_message
from .common import add_period_args, period_from_args

TX_TYPES = ["income", "expense", "transfer", "adjustment", "debt_in", "debt_out", "deposit", "withdraw",
            "savings_loan", "savings_repay"]
KIND_WORD = {"expense": "Pengeluaran", "income": "Pemasukan"}


def register(sub):
    p = sub.add_parser("balance", help="Saldo satu dompet, atau semua dompet dan budget beserta total.")
    p.add_argument("--account")
    p.set_defaults(func=cmd_balance)

    p = sub.add_parser("report", help="Laporan pemasukan/pengeluaran per kategori.")
    add_period_args(p)
    p.add_argument("--type", default="expense", choices=["expense", "income", "all"])
    p.add_argument("--category")
    p.add_argument("--account")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("list", help="Daftar transaksi beserta ID.")
    add_period_args(p)
    p.add_argument("--search", help="Cari di catatan dan teks asli.")
    p.add_argument("--type", choices=TX_TYPES)
    p.add_argument("--account")
    p.add_argument("--category")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--include-deleted", action="store_true")
    p.set_defaults(func=cmd_list)


# ---------- balance ----------

def cmd_balance(args, conn):
    bals = balances(conn)
    if args.account:
        acc = resolve.account(conn, args.account, include_archived=True, kind=None)
        bal = bals[acc["id"]]
        msg = f"Saldo {acc['name']} ({ACCOUNT_TYPE_LABEL[acc['type']]}): {rupiah(bal)}."
        if bal < 0:
            msg += f" Peringatan: saldo {acc['name']} minus."
        return success(msg, {"account": acc["name"], "type": acc["type"], "balance": bal,
                             "savings": acc["type"] == "savings"})

    rows = [r for r in conn.execute("SELECT * FROM accounts ORDER BY id")
            if not r["archived"] or bals[r["id"]] != 0]
    wallets = [r for r in rows if r["type"] != "savings"]
    savings = [r for r in rows if r["type"] == "savings"]
    if not rows:
        raise FinError("UNKNOWN_ACCOUNT", "Belum ada dompet.",
                       hint="Buat dulu, contoh: account add tunai --type cash --opening 100k")
    total_dompet = sum(bals[r["id"]] for r in conn.execute("SELECT id FROM accounts WHERE type != 'savings'"))
    total_tabungan = sum(bals[r["id"]] for r in conn.execute("SELECT id FROM accounts WHERE type = 'savings'"))
    ov = budgets.overview(conn)
    owe, owed = debts.totals(conn)
    loans = debts.savings_loans_total(conn)
    net_worth = total_dompet + total_tabungan + owed - owe

    def acc_line(r):
        return (f"- {r['name']} ({ACCOUNT_TYPE_LABEL[r['type']]}): {rupiah(bals[r['id']])}"
                + (" [dihapus]" if r["archived"] else "") + (" [minus]" if bals[r["id"]] < 0 else ""))

    lines = ["Dompet (uang untuk dipakai):"] + [acc_line(r) for r in wallets]
    lines.append(f"Total dompet: {rupiah(total_dompet)}")
    lines += ["", "Per budget (uang di dompet untuk apa):"]
    lines += overview_message(conn, ov, total_dompet)
    lines += ["", "Tabungan (terpisah, di luar budget):"]
    lines += [acc_line(r) for r in savings] or ["- belum ada tabungan"]
    lines.append(f"Total tabungan: {rupiah(total_tabungan)}")
    if loans:
        lines.append(f"Pinjaman dari tabungan yang belum dikembalikan: {rupiah(loans)}")
    lines.append("")
    if owe or owed:
        lines.append(f"Hutang saya: {rupiah(owe)} | Piutang: {rupiah(owed)}")
    lines.append(f"Kekayaan bersih (dompet + tabungan + piutang − hutang): {rupiah(net_worth)}")
    negatives = [r["name"] for r in rows if bals[r["id"]] < 0]
    if negatives:
        lines.append(f"Peringatan: saldo {', '.join(negatives)} minus.")
    acc_dict = lambda r: {"name": r["name"], "type": r["type"], "balance": bals[r["id"]],  # noqa: E731
                          "is_default": bool(r["is_default"]), "archived": bool(r["archived"])}
    return success("\n".join(lines), {
        "accounts": [acc_dict(r) for r in wallets],
        "savings": [{**acc_dict(r), "target_amount": r["target_amount"]} for r in savings],
        "total_dompet": total_dompet, "total_tabungan": total_tabungan, **ov,
        "consistent": total_dompet == ov["total_budget"],
        "debt_total": owe, "receivable_total": owed, "savings_loans_total": loans, "net_worth": net_worth,
    })


# ---------- report ----------

def _section_lines(section):
    return [f"- {c['category']}: {rupiah(c['amount'])} ({fmt_pct(c['percent'])}) · {c['count']}x"
            for c in section["by_category"]]


def _savings_lines(sec):
    if not sec["count"]:
        return []
    return ([f"Pengeluaran dari tabungan (terpisah, tidak memotong dompet dan budget): {rupiah(sec['total'])} "
             f"({sec['count']} transaksi)"] + _section_lines(sec))


def cmd_report(args, conn):
    period = period_from_args(conn, args)
    acc = resolve.account(conn, args.account, include_archived=True, kind=None) if args.account else None
    account_ids = [acc["id"]] if acc else None
    category_ids = None
    filters = {"account": args.account, "category": None}
    if args.category:
        kind = None if args.type == "all" else args.type
        cats = resolve.find_categories(conn, args.category, kind)
        if not cats:
            resolve.category(conn, args.category, kind)  # melempar UNKNOWN_CATEGORY dengan hint
        category_ids = [c["id"] for c in cats]
        filters["category"] = cats[0]["name"]
    scope = ""
    if filters["category"]:
        scope += f" kategori {filters['category']}"
    if acc:
        scope += f" dari {'tabungan' if acc['type'] == 'savings' else 'dompet'} {acc['name']}"
    # angka utama: pengeluaran dompet; pengeluaran dari tabungan dilaporkan terpisah
    main_source = "savings" if acc and acc["type"] == "savings" else "wallet"
    # dengan --account, laporan hanya tentang akun itu: tidak ada bagian tabungan tambahan
    savings_sec = (summarize(conn, period, "expense", None, category_ids, source="savings") if not acc
                   else {"total": 0, "count": 0, "by_category": []})

    data = {"period": period.to_dict(), "type": args.type, "filters": filters}
    if args.type in ("expense", "income"):
        sec = summarize(conn, period, args.type, account_ids, category_ids, source=main_source)
        data.update(sec)
        head = f"{KIND_WORD[args.type]}{scope} {period.describe}"
        if sec["count"] == 0:
            lines = [f"{head}: belum ada transaksi."]
        else:
            lines = [f"{head}: {rupiah(sec['total'])} dari {sec['count']} transaksi."] + _section_lines(sec)
        if args.type == "expense":
            data["savings_expense"] = savings_sec
            lines += _savings_lines(savings_sec)
        return success("\n".join(lines), data)

    inc = summarize(conn, period, "income", account_ids, category_ids, source=main_source)
    exp = summarize(conn, period, "expense", account_ids, category_ids, source=main_source)
    net = inc["total"] - exp["total"]
    data.update({"income": inc, "expense": exp, "net": net, "savings_expense": savings_sec})
    lines = [f"Laporan{scope} {period.describe}:",
             f"Pemasukan: {rupiah(inc['total'])} ({inc['count']} transaksi)"]
    lines += _section_lines(inc)
    lines.append(f"Pengeluaran: {rupiah(exp['total'])} ({exp['count']} transaksi)")
    lines += _section_lines(exp)
    lines.append(f"Selisih: {('+' if net > 0 else '')}{rupiah(net)}")
    lines += _savings_lines(savings_sec)
    return success("\n".join(lines), data)


# ---------- list ----------

def cmd_list(args, conn):
    if args.limit < 1 or args.limit > 1000:
        raise FinError("BAD_ARGS", "--limit harus 1 sampai 1000.")
    period = period_from_args(conn, args)
    start, end = period.bounds()
    where = ["t.ts BETWEEN ? AND ?"]
    params = [start, end]
    if not args.include_deleted:
        where.append("t.deleted_at IS NULL")
    if args.type:
        where.append("t.type = ?")
        params.append(args.type)
    if args.account:
        acc = resolve.account(conn, args.account, include_archived=True, kind=None)
        where.append("(t.account_id = ? OR t.to_account_id = ?)")
        params += [acc["id"], acc["id"]]
    if args.category:
        cats = resolve.find_categories(conn, args.category)
        if not cats:
            resolve.category(conn, args.category)
        where.append(f"t.category_id IN ({','.join('?' * len(cats))})")
        params += [c["id"] for c in cats]
    if args.search:
        term = "%" + args.search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(t.note LIKE ? ESCAPE '\\' OR t.raw_text LIKE ? ESCAPE '\\')")
        params += [term, term]
    cond = " WHERE " + " AND ".join(where)
    total = conn.execute("SELECT COUNT(*) FROM transactions t" + cond, params).fetchone()[0]
    rows = conn.execute(TX_SELECT + cond + " ORDER BY t.ts DESC, t.id DESC LIMIT ?",
                        (*params, args.limit)).fetchall()
    head = f"Transaksi {period.describe}"
    if args.search:
        head += f" yang mengandung '{args.search}'"
    if not rows:
        msg = f"{head}: tidak ada."
    else:
        shown = f"{len(rows)} dari {total}" if total > len(rows) else str(total)
        msg = f"{head}, {shown} transaksi:\n" + "\n".join(tx_line(r) for r in rows)
    return success(msg, {"period": period.to_dict(), "count": len(rows), "total_matching": total,
                         "transactions": [tx_dict(r) for r in rows]})
