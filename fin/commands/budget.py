"""budget list / alloc / move / close / history"""
from .. import budgets
from ..db import UNALLOCATED, write
from ..ledger import new_group, operational_total
from ..output import FinError, fmt_ts, rupiah, success
from ..parse import parse_amount
from .common import add_period_args, period_from_args
from .transactions import _with_item_prefix

ALLOC_HINT = ('Format --item "budget|jumlah", contoh --item "makan|300k". Budget adalah kategori pengeluaran; '
              'untuk menabung pakai savings deposit.')


def register(sub):
    p = sub.add_parser("budget", help="Budget sistem amplop.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("list", help="Semua budget dan saldonya.")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("alloc", help=f"Alokasi dari '{UNALLOCATED}' ke satu atau banyak budget.")
    a.add_argument("--item", action="append", required=True, help="budget|jumlah")
    a.add_argument("--note")
    a.set_defaults(func=cmd_alloc)

    a = s.add_parser("move", help="Pindah saldo antar budget.")
    a.add_argument("--from", dest="from_budget", required=True)
    a.add_argument("--to", dest="to_budget", required=True)
    a.add_argument("--amount", required=True, help="Jumlah, atau 'all' untuk seluruh sisa.")
    a.add_argument("--note")
    a.set_defaults(func=cmd_move)

    a = s.add_parser("close", help=f"Tutup budget, sisanya kembali ke '{UNALLOCATED}'.")
    a.add_argument("name")
    a.set_defaults(func=cmd_close)

    a = s.add_parser("history", help="Riwayat alokasi dan pindahan budget.")
    a.add_argument("--budget")
    add_period_args(a)
    a.add_argument("--limit", type=int, default=50)
    a.set_defaults(func=cmd_history)


def overview_message(conn, ov, total_dompet):
    groups = {"unallocated": [], "category": [], "savings": []}
    for item in ov["budgets"]:
        groups[item["kind"]].append(item)
    lines = [budgets.line(i) for i in groups["unallocated"]]
    if groups["category"]:
        lines.append("Budget kategori:")
        lines += ["  " + budgets.line(i) for i in groups["category"]]
    if groups["savings"]:  # sisa budget tabungan lama (sebelum skema v4) yang masih bersaldo
        lines.append("Budget tabungan lama:")
        lines += ["  " + budgets.line(i) for i in groups["savings"]]
    lines.append(f"Total budget: {rupiah(ov['total_budget'])}")
    if ov["total_budget"] != total_dompet:
        lines.append(f"PERINGATAN: total budget tidak sama dengan total dompet ({rupiah(total_dompet)}).")
    for item in ov["budgets"]:
        if item["balance"] < 0:
            lines.append(budgets.warning(budgets.get(conn, item["id"]), item["balance"]))
    return lines


def cmd_list(args, conn):
    ov = budgets.overview(conn)
    total_dompet = operational_total(conn)
    lines = ["Budget:"] + overview_message(conn, ov, total_dompet)
    return success("\n".join(lines), {**ov, "total_dompet": total_dompet,
                                      "consistent": total_dompet == ov["total_budget"]})


def cmd_alloc(args, conn):
    parsed = []
    for i, raw in enumerate(args.item, 1):
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 2 or not parts[0]:
            raise _with_item_prefix(FinError("BAD_ARGS", f"Item '{raw}' tidak sesuai format.", hint=ALLOC_HINT),
                                    i, len(args.item))
        try:
            parsed.append((parts[0], parse_amount(parts[1])))
        except FinError as e:
            raise _with_item_prefix(e, i, len(args.item))
    unalloc = budgets.unallocated(conn)
    done = []
    with write(conn):
        group = new_group(conn, "budget_alloc")
        for i, (name, amount) in enumerate(parsed, 1):
            try:
                bud = budgets.find(conn, name, create=True)
                if bud["kind"] == "unallocated":
                    raise FinError("BAD_ARGS", f"Tidak bisa mengalokasikan ke {UNALLOCATED} sendiri.", hint=ALLOC_HINT)
            except FinError as e:
                raise _with_item_prefix(e, i, len(parsed))
            move_id = budgets.insert_move(conn, from_id=unalloc["id"], to_id=bud["id"], amount=amount,
                                          group_id=group, note=args.note)
            done.append({"id": move_id, "budget": bud["name"], "budget_id": bud["id"], "amount": amount})
    total = sum(d["amount"] for d in done)
    detail = ", ".join(f"{d['budget']} {rupiah(d['amount'])}" for d in done)
    msg = (f"Dialokasikan {rupiah(total)} dari {UNALLOCATED}: {detail}. "
           + budgets.sentence(conn, [d["budget_id"] for d in done] + [unalloc["id"]]))
    bals = budgets.balances(conn)
    for d in done:
        d["balance_after"] = bals[d.pop("budget_id")]
    return success(msg, {"group_id": group, "total": total, "items": done,
                         "unallocated_balance": bals[unalloc["id"]]})


def cmd_move(args, conn):
    src = budgets.find(conn, args.from_budget)
    with write(conn):
        dst = budgets.find(conn, args.to_budget, create=True)
        if src["id"] == dst["id"]:
            raise FinError("BAD_ARGS", f"Budget asal dan tujuan sama ({src['name']}).")
        if args.amount.strip().lower() in ("all", "semua"):
            amount = budgets.balances(conn)[src["id"]]
            if amount <= 0:
                raise FinError("BAD_AMOUNT", f"Budget {src['name']} tidak punya sisa untuk dipindah "
                                             f"(saldo {rupiah(amount)}).")
        else:
            amount = parse_amount(args.amount)
        group = new_group(conn, "budget_move")
        move_id = budgets.insert_move(conn, from_id=src["id"], to_id=dst["id"], amount=amount, group_id=group,
                                      note=args.note)
    msg = f"Dipindah {rupiah(amount)} dari budget {src['name']} ke {dst['name']}. " + \
        budgets.sentence(conn, [src["id"], dst["id"]])
    bals = budgets.balances(conn)
    return success(msg, {"id": move_id, "group_id": group, "from": src["name"], "to": dst["name"],
                         "amount": amount, "from_balance": bals[src["id"]], "to_balance": bals[dst["id"]]})


def close_budget(conn, bud, action, note):
    """Kembalikan sisa ke 'belum teralokasi' lalu tutup. Dipanggil di dalam write(conn)."""
    bal = budgets.balances(conn)[bud["id"]]
    if bal:
        restore = [["budgets", bud["id"]]] if not bud["archived"] else None
        group = new_group(conn, action, restore=restore)
        budgets.sweep_to_unallocated(conn, bud, group, note)
    conn.execute("UPDATE budgets SET archived = 1 WHERE id = ?", (bud["id"],))
    return bal


def returned_text(bal):
    if bal > 0:
        return f"Sisa {rupiah(bal)} dikembalikan ke {UNALLOCATED}."
    if bal < 0:
        return f"Budget ini minus {rupiah(-bal)}, jadi {UNALLOCATED} dikurangi {rupiah(-bal)} untuk menutupnya."
    return "Tidak ada sisa."


def cmd_close(args, conn):
    bud = budgets.find(conn, args.name, include_archived=True)
    if bud["kind"] == "unallocated":
        raise FinError("SYSTEM_PROTECTED", f"Budget {UNALLOCATED} milik sistem dan tidak bisa ditutup.")
    if bud["archived"] and budgets.balances(conn)[bud["id"]] == 0:
        raise FinError("UNKNOWN_BUDGET", f"Budget {bud['name']} sudah ditutup.")
    with write(conn):
        bal = close_budget(conn, bud, "budget_close", f"tutup budget {bud['name']}")
    msg = f"Budget {bud['name']} ditutup. {returned_text(bal)}"
    if bud["kind"] == "category":
        msg += f" Pengeluaran kategori {bud['name']} sekarang memakai {UNALLOCATED} lagi."
    msg += " " + budgets.sentence(conn, [budgets.unallocated(conn)["id"]])
    return success(msg, {"id": bud["id"], "name": bud["name"], "kind": bud["kind"], "returned": bal,
                         "unallocated_balance": budgets.balances(conn)[budgets.unallocated(conn)["id"]]})


def cmd_history(args, conn):
    if args.limit < 1 or args.limit > 1000:
        raise FinError("BAD_ARGS", "--limit harus 1 sampai 1000.")
    period = period_from_args(conn, args)
    start, end = period.bounds()
    sql = ("SELECT m.*, f.name AS from_budget, t.name AS to_budget FROM budget_moves m "
           "JOIN budgets f ON f.id = m.from_budget_id JOIN budgets t ON t.id = m.to_budget_id "
           "WHERE m.deleted_at IS NULL AND m.ts BETWEEN ? AND ?")
    params = [start, end]
    head = f"Riwayat budget {period.describe}"
    if args.budget:
        bud = budgets.find(conn, args.budget, include_archived=True)
        sql += " AND (m.from_budget_id = ? OR m.to_budget_id = ?)"
        params += [bud["id"], bud["id"]]
        head = f"Riwayat budget {bud['name']} {period.describe}"
    rows = conn.execute(sql + " ORDER BY m.ts DESC, m.id DESC LIMIT ?", (*params, args.limit)).fetchall()
    items = [{"id": r["id"], "ts": r["ts"], "from": r["from_budget"], "to": r["to_budget"], "amount": r["amount"],
              "note": r["note"], "group_id": r["group_id"]} for r in rows]
    if not rows:
        return success(f"{head}: tidak ada alokasi atau pindahan.", {"period": period.to_dict(), "moves": []})
    lines = [f"#{r['id']} {fmt_ts(r['ts'])} · {rupiah(r['amount'])} {r['from_budget']} → {r['to_budget']}"
             + (f" ({r['note']})" if r["note"] else "") for r in rows]
    return success(f"{head}, {len(rows)} catatan:\n" + "\n".join(lines),
                   {"period": period.to_dict(), "moves": items})
