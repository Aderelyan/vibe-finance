"""balance / report / list"""
from .. import budgets, debts, resolve
from ..ledger import ACCOUNT_TYPE_LABEL, TX_SELECT, balances, tx_dict, tx_line
from ..output import FinError, fmt_pct, rupiah, success
from ..report import summarize
from .budget import overview_message
from .common import add_period_args, period_from_args

TX_TYPES = ["income", "expense", "transfer", "adjustment", "debt_in", "debt_out"]
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
        acc = resolve.account(conn, args.account, include_archived=True)
        bal = bals[acc["id"]]
        msg = f"Saldo {acc['name']} ({ACCOUNT_TYPE_LABEL[acc['type']]}): {rupiah(bal)}."
        if bal < 0:
            msg += f" Peringatan: saldo {acc['name']} minus."
        return success(msg, {"account": acc["name"], "type": acc["type"], "balance": bal})

    rows = [r for r in conn.execute("SELECT * FROM accounts ORDER BY id")
            if not r["archived"] or bals[r["id"]] != 0]
    if not rows:
        raise FinError("UNKNOWN_ACCOUNT", "Belum ada dompet.",
                       hint="Buat dulu, contoh: account add tunai --type cash --opening 100k")
    total_dompet = sum(bals.values())
    ov = budgets.overview(conn)
    owe, owed = debts.totals(conn)
    net_worth = total_dompet + owed - owe

    lines = ["Per dompet (uangnya di mana):"]
    for r in rows:
        lines.append(f"- {r['name']} ({ACCOUNT_TYPE_LABEL[r['type']]}): {rupiah(bals[r['id']])}"
                     + (" [dihapus]" if r["archived"] else "") + (" [minus]" if bals[r["id"]] < 0 else ""))
    lines.append(f"Total dompet: {rupiah(total_dompet)}")
    lines.append("")
    lines.append("Per budget (uangnya untuk apa):")
    lines += overview_message(conn, ov, total_dompet)
    if owe or owed:
        lines += ["", f"Hutang saya: {rupiah(owe)} | Piutang: {rupiah(owed)}",
                  f"Kekayaan bersih: {rupiah(net_worth)}"]
    negatives = [r["name"] for r in rows if bals[r["id"]] < 0]
    if negatives:
        lines.append(f"Peringatan: saldo dompet {', '.join(negatives)} minus.")
    return success("\n".join(lines), {
        "accounts": [{"name": r["name"], "type": r["type"], "balance": bals[r["id"]],
                      "is_default": bool(r["is_default"]), "archived": bool(r["archived"])} for r in rows],
        "total_dompet": total_dompet, **ov, "consistent": total_dompet == ov["total_budget"],
        "debt_total": owe, "receivable_total": owed, "net_worth": net_worth,
    })


# ---------- report ----------

def _section_lines(section):
    return [f"- {c['category']}: {rupiah(c['amount'])} ({fmt_pct(c['percent'])}) · {c['count']}x"
            for c in section["by_category"]]


def cmd_report(args, conn):
    period = period_from_args(conn, args)
    account_ids = [resolve.account(conn, args.account, include_archived=True)["id"]] if args.account else None
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
    if account_ids:
        scope += f" dari dompet {resolve.account(conn, args.account, include_archived=True)['name']}"

    data = {"period": period.to_dict(), "type": args.type, "filters": filters}
    if args.type in ("expense", "income"):
        sec = summarize(conn, period, args.type, account_ids, category_ids)
        data.update(sec)
        head = f"{KIND_WORD[args.type]}{scope} {period.describe}"
        if sec["count"] == 0:
            msg = f"{head}: belum ada transaksi."
        else:
            msg = f"{head}: {rupiah(sec['total'])} dari {sec['count']} transaksi.\n" + "\n".join(_section_lines(sec))
        return success(msg, data)

    inc = summarize(conn, period, "income", account_ids, category_ids)
    exp = summarize(conn, period, "expense", account_ids, category_ids)
    net = inc["total"] - exp["total"]
    data.update({"income": inc, "expense": exp, "net": net})
    lines = [f"Laporan{scope} {period.describe}:",
             f"Pemasukan: {rupiah(inc['total'])} ({inc['count']} transaksi)"]
    lines += _section_lines(inc)
    lines.append(f"Pengeluaran: {rupiah(exp['total'])} ({exp['count']} transaksi)")
    lines += _section_lines(exp)
    lines.append(f"Selisih: {('+' if net > 0 else '')}{rupiah(net)}")
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
        acc = resolve.account(conn, args.account, include_archived=True)
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
