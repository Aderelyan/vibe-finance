"""savings add / list / set-target / rename / remove. Tabungan = budget berjenis savings."""
from .. import budgets, clock, resolve
from ..db import UNALLOCATED, write
from ..output import FinError, fmt_date, fmt_pct, percent, rupiah, success
from ..parse import parse_amount, parse_day
from .budget import close_budget, returned_text


def register(sub):
    p = sub.add_parser("savings", help="Tabungan (budget berjenis tabungan).")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Buat tabungan (atau aktifkan lagi yang pernah dihapus).")
    a.add_argument("name")
    a.add_argument("--target")
    a.add_argument("--target-date", help="YYYY-MM-DD")
    a.set_defaults(func=cmd_add)

    a = s.add_parser("list", help="Saldo, target, dan perkembangan tiap tabungan.")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("set-target", help="Ubah atau hapus target tabungan.")
    a.add_argument("name")
    a.add_argument("--target")
    a.add_argument("--target-date", help="YYYY-MM-DD")
    a.add_argument("--clear", action="store_true", help="Hapus target nominal dan tanggal.")
    a.set_defaults(func=cmd_set_target)

    a = s.add_parser("rename", help="Ganti nama tabungan.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.set_defaults(func=cmd_rename)

    a = s.add_parser("remove", help=f"Hapus tabungan, sisanya kembali ke '{UNALLOCATED}'.")
    a.add_argument("name")
    a.set_defaults(func=cmd_remove)


def _find(conn, name, include_archived=False):
    key = resolve.norm(name)
    rows = [r for r in conn.execute("SELECT * FROM budgets WHERE kind = 'savings' ORDER BY archived, id")
            if resolve.norm(r["name"]) == key]
    for r in rows:
        if not r["archived"] or include_archived:
            return r
    names = [r["name"] for r in conn.execute("SELECT name FROM budgets WHERE kind = 'savings' AND archived = 0")]
    if rows:
        raise FinError("UNKNOWN_BUDGET", f"Tabungan '{rows[0]['name']}' sudah dihapus.",
                       hint=f"Buat lagi dengan: savings add \"{rows[0]['name']}\"")
    raise FinError("UNKNOWN_BUDGET", f"Tabungan '{name}' tidak ada.",
                   hint=("Tabungan yang ada: " + ", ".join(names)) if names else
                   "Belum ada tabungan. Buat dengan: savings add \"dana darurat\" --target 5jt")


def _ensure_name_free(conn, name, except_id=None):
    if resolve.norm(name) == resolve.norm(UNALLOCATED):
        raise FinError("SYSTEM_PROTECTED", f"Nama '{UNALLOCATED}' dipakai sistem.")
    clash = budgets.name_taken(conn, name, except_budget_id=except_id)
    if clash:
        raise FinError("BAD_ARGS", f"Nama '{clash['name']}' sudah dipakai budget {budgets.KIND_LABEL[clash['kind']]}.",
                       hint="Pakai nama lain.")
    for cat in resolve.find_categories(conn, name, "expense"):
        raise FinError("BAD_ARGS", f"Nama '{cat['name']}' sudah dipakai kategori pengeluaran.",
                       hint="Tabungan dan kategori pengeluaran tidak boleh bernama sama. Pakai nama lain.")


def _targets(args, current_amount=None, current_date=None):
    target = parse_amount(args.target, field="target") if args.target else current_amount
    target_date = parse_day(args.target_date, "tanggal target").isoformat() if args.target_date else current_date
    return target, target_date


def _target_text(target, target_date):
    if not target and not target_date:
        return "tanpa target"
    text = f"target {rupiah(target)}" if target else "target"
    if target_date:
        text += f" pada {fmt_date(target_date)}"
    return text


def cmd_add(args, conn):
    name = resolve.clean_name(args.name, "nama tabungan")
    archived = [r for r in conn.execute("SELECT * FROM budgets WHERE kind = 'savings' AND archived = 1")
                if resolve.norm(r["name"]) == resolve.norm(name)]
    if archived:
        old = archived[0]
        target, target_date = _targets(args, old["target_amount"], old["target_date"])
        with write(conn):
            conn.execute("UPDATE budgets SET archived = 0, target_amount = ?, target_date = ? WHERE id = ?",
                         (target, target_date, old["id"]))
        bal = budgets.balances(conn)[old["id"]]
        return success(f"Tabungan {old['name']} diaktifkan kembali ({_target_text(target, target_date)}), "
                       f"saldo {rupiah(bal)}.",
                       {"id": old["id"], "name": old["name"], "target_amount": target, "target_date": target_date,
                        "balance": bal, "reactivated": True})
    _ensure_name_free(conn, name)
    target, target_date = _targets(args)
    with write(conn):
        bud_id = conn.execute("INSERT INTO budgets(name, kind, target_amount, target_date, created_at) "
                              "VALUES (?, 'savings', ?, ?, ?)", (name, target, target_date, clock.now_ts())).lastrowid
    return success(f"Tabungan {name} dibuat ({_target_text(target, target_date)}). "
                   f"Isi dengan: budget alloc --item \"{name}|100k\"",
                   {"id": bud_id, "name": name, "target_amount": target, "target_date": target_date,
                    "balance": 0, "reactivated": False})


def _month_change(conn, budget_id):
    today = clock.today()
    start, end = f"{today.replace(day=1).isoformat()} 00:00:00", f"{today.isoformat()} 23:59:59"
    moves = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN to_budget_id = :b THEN amount ELSE -amount END), 0) FROM budget_moves "
        "WHERE deleted_at IS NULL AND (to_budget_id = :b OR from_budget_id = :b) AND ts BETWEEN :s AND :e",
        {"b": budget_id, "s": start, "e": end}).fetchone()[0]
    txs = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN type IN ('income','debt_in','adjustment') THEN amount ELSE -amount END), 0) "
        "FROM transactions WHERE deleted_at IS NULL AND budget_id = ? AND ts BETWEEN ? AND ?",
        (budget_id, start, end)).fetchone()[0]
    return moves + txs


def cmd_list(args, conn):
    bals = budgets.balances(conn)
    rows = [r for r in conn.execute("SELECT * FROM budgets WHERE kind = 'savings' ORDER BY id")
            if not r["archived"] or bals[r["id"]] != 0]
    if not rows:
        return success("Belum ada tabungan. Buat dengan: savings add \"dana darurat\" --target 5jt",
                       {"savings": [], "total": 0, "month_change_total": 0})
    items, lines = [], []
    for r in rows:
        bal = bals[r["id"]]
        target = r["target_amount"]
        item = {"id": r["id"], "name": r["name"], "balance": bal, "target_amount": target,
                "target_date": r["target_date"], "archived": bool(r["archived"]),
                "percent": percent(bal, target) if target else None,
                "shortfall": max(target - bal, 0) if target else None,
                "month_change": _month_change(conn, r["id"])}
        items.append(item)
        line = f"- {r['name']}{' (dihapus)' if r['archived'] else ''}: {rupiah(bal)}"
        if target:
            line += f" dari target {rupiah(target)} ({fmt_pct(item['percent'])}), kurang {rupiah(item['shortfall'])}"
        if r["target_date"]:
            line += f", tenggat {fmt_date(r['target_date'])}"
        sign = "+" if item["month_change"] > 0 else ""
        line += f". Bulan ini {sign}{rupiah(item['month_change'])}."
        if bal < 0:
            line += " [minus]"
        lines.append(line)
    total = sum(i["balance"] for i in items)
    change = sum(i["month_change"] for i in items)
    msg = "Tabungan:\n" + "\n".join(lines) + f"\nTotal tabungan: {rupiah(total)} (bulan ini {'+' if change > 0 else ''}{rupiah(change)})."
    return success(msg, {"savings": items, "total": total, "month_change_total": change})


def cmd_set_target(args, conn):
    bud = _find(conn, args.name)
    if args.clear:
        if args.target or args.target_date:
            raise FinError("BAD_ARGS", "--clear tidak bisa digabung dengan --target atau --target-date.")
        target, target_date = None, None
    else:
        if not args.target and not args.target_date:
            raise FinError("BAD_ARGS", "Isi --target dan/atau --target-date, atau --clear untuk menghapus target.")
        target, target_date = _targets(args, bud["target_amount"], bud["target_date"])
    with write(conn):
        conn.execute("UPDATE budgets SET target_amount = ?, target_date = ? WHERE id = ?",
                     (target, target_date, bud["id"]))
    msg = f"Target tabungan {bud['name']} dihapus." if target is None and target_date is None else \
        f"Tabungan {bud['name']} sekarang {_target_text(target, target_date)}."
    return success(msg, {"id": bud["id"], "name": bud["name"], "target_amount": target, "target_date": target_date})


def cmd_rename(args, conn):
    bud = _find(conn, args.name)
    new = resolve.clean_name(args.new_name, "nama tabungan")
    _ensure_name_free(conn, new, except_id=bud["id"])
    with write(conn):
        conn.execute("UPDATE budgets SET name = ? WHERE id = ?", (new, bud["id"]))
    return success(f"Tabungan {bud['name']} diganti nama menjadi {new}.",
                   {"id": bud["id"], "old_name": bud["name"], "name": new})


def cmd_remove(args, conn):
    bud = _find(conn, args.name, include_archived=True)
    if bud["archived"] and budgets.balances(conn)[bud["id"]] == 0:
        raise FinError("UNKNOWN_BUDGET", f"Tabungan '{bud['name']}' sudah dihapus.")
    with write(conn):
        bal = close_budget(conn, bud, "savings_remove", f"hapus tabungan {bud['name']}")
        if budgets.is_used(conn, bud["id"]):
            mode = "archived"
        else:
            mode = "deleted"
            conn.execute("DELETE FROM budgets WHERE id = ?", (bud["id"],))
    if mode == "deleted":
        msg = f"Tabungan {bud['name']} dihapus permanen karena belum pernah diisi."
    else:
        msg = f"Tabungan {bud['name']} dihapus. {returned_text(bal)} Riwayatnya tetap disimpan (diarsipkan)."
    msg += " " + budgets.sentence(conn, [budgets.unallocated(conn)["id"]])
    return success(msg, {"id": bud["id"], "name": bud["name"], "mode": mode, "returned": bal})
