"""account add / list / rename / archive / unarchive / set-default / set-target"""
from .. import clock, resolve
from ..db import write
from ..ledger import ACCOUNT_TYPE_LABEL, balances, insert_tx, new_group
from ..output import FinError, fmt_date, rupiah, success
from ..parse import parse_amount, parse_day

TYPES = ["cash", "bank", "ewallet", "savings"]


def register(sub):
    p = sub.add_parser("account", help="Kelola dompet.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Tambah dompet.")
    a.add_argument("name")
    a.add_argument("--type", required=True, choices=TYPES)
    a.add_argument("--opening", help="Saldo awal (dicatat sebagai penyesuaian 'saldo awal').")
    a.add_argument("--default", action="store_true", help="Jadikan dompet default.")
    a.add_argument("--target", help="Target tabungan (hanya type savings).")
    a.add_argument("--target-date", help="Tanggal target YYYY-MM-DD (hanya type savings).")
    a.set_defaults(func=cmd_add)

    a = s.add_parser("list", help="Daftar dompet beserta saldo.")
    a.add_argument("--all", action="store_true", help="Sertakan dompet yang diarsipkan.")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("rename", help="Ganti nama dompet.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.set_defaults(func=cmd_rename)

    a = s.add_parser("archive", help="Arsipkan dompet (saldo harus 0).")
    a.add_argument("name")
    a.set_defaults(func=cmd_archive)

    a = s.add_parser("unarchive", help="Aktifkan lagi dompet yang diarsipkan.")
    a.add_argument("name")
    a.set_defaults(func=cmd_unarchive)

    a = s.add_parser("set-default", help="Atur dompet default.")
    a.add_argument("name")
    a.set_defaults(func=cmd_set_default)

    a = s.add_parser("set-target", help="Atur target dompet tabungan.")
    a.add_argument("name")
    a.add_argument("--amount")
    a.add_argument("--date", help="YYYY-MM-DD")
    a.add_argument("--clear", action="store_true", help="Hapus target.")
    a.set_defaults(func=cmd_set_target)


def _ensure_name_free(conn, name, except_id=None):
    key = resolve.norm(name)
    for row in conn.execute("SELECT id, name FROM accounts"):
        if row["id"] != except_id and resolve.norm(row["name"]) == key:
            raise FinError("BAD_ARGS", f"Dompet bernama '{row['name']}' sudah ada.",
                           hint="Pakai nama lain, atau lihat daftar dengan: account list --all")
    for row in conn.execute("SELECT al.alias, a.name, a.id FROM aliases al JOIN accounts a ON a.id = al.target_id "
                            "WHERE al.kind = 'account'"):
        if row["id"] != except_id and resolve.norm(row["alias"]) == key:
            raise FinError("BAD_ARGS", f"'{name}' sudah dipakai sebagai alias dompet {row['name']}.",
                           hint=f"Pakai nama lain, atau hapus aliasnya: alias remove --kind account --alias \"{row['alias']}\"")


def _account_dict(row, bal):
    return {"id": row["id"], "name": row["name"], "type": row["type"], "is_default": bool(row["is_default"]),
            "archived": bool(row["archived"]), "balance": bal, "target_amount": row["target_amount"],
            "target_date": row["target_date"]}


def cmd_add(args, conn):
    name = resolve.clean_name(args.name, "nama dompet")
    _ensure_name_free(conn, name)
    if args.type != "savings" and (args.target or args.target_date):
        raise FinError("BAD_ARGS", "--target dan --target-date hanya untuk dompet bertipe savings.")
    if args.type == "savings" and args.default:
        raise FinError("BAD_ARGS", "Dompet tabungan tidak bisa dijadikan default.",
                       hint="Pilih dompet bertipe cash, bank, atau ewallet sebagai default.")
    opening = 0
    if args.opening is not None:
        opening = parse_amount(args.opening, allow_zero=True, allow_negative=True, field="saldo awal")
    target = parse_amount(args.target, field="target") if args.target else None
    target_date = parse_day(args.target_date, "tanggal target").isoformat() if args.target_date else None

    has_default = conn.execute("SELECT 1 FROM accounts WHERE is_default = 1 AND archived = 0").fetchone()
    make_default = args.default or (not has_default and args.type != "savings")
    now = clock.now_ts()
    with write(conn):
        if make_default:
            conn.execute("UPDATE accounts SET is_default = 0")
        acc_id = conn.execute(
            "INSERT INTO accounts(name, type, is_default, target_amount, target_date, created_at) "
            "VALUES (?,?,?,?,?,?)", (name, args.type, int(make_default), target, target_date, now)).lastrowid
        if opening:
            insert_tx(conn, ts=now, type="adjustment", amount=opening, account_id=acc_id,
                      note="saldo awal", group_id=new_group())

    msg = f"Dompet {name} ({ACCOUNT_TYPE_LABEL[args.type]}) dibuat dengan saldo awal {rupiah(opening)}."
    if make_default:
        msg += " Dijadikan dompet default." if args.default else \
            " Dijadikan dompet default karena belum ada dompet default."
    if target:
        msg += f" Target {rupiah(target)}" + (f" pada {fmt_date(target_date)}." if target_date else ".")
    if opening < 0:
        msg += " Peringatan: saldo awal minus."
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (acc_id,)).fetchone()
    return success(msg, {"account": _account_dict(row, opening)})


def cmd_list(args, conn):
    bals = balances(conn)
    sql = "SELECT * FROM accounts" + ("" if args.all else " WHERE archived = 0") + " ORDER BY id"
    rows = conn.execute(sql).fetchall()
    if not rows:
        return success("Belum ada dompet. Tambahkan dengan: account add <nama> --type cash|bank|ewallet|savings "
                       "--opening <saldo>.", {"accounts": []})
    lines = []
    for r in rows:
        line = f"- {r['name']} ({ACCOUNT_TYPE_LABEL[r['type']]}): {rupiah(bals[r['id']])}"
        if r["is_default"]:
            line += " [default]"
        if r["archived"]:
            line += " [arsip]"
        lines.append(line)
    return success("Daftar dompet:\n" + "\n".join(lines),
                   {"accounts": [_account_dict(r, bals[r["id"]]) for r in rows]})


def cmd_rename(args, conn):
    acc = resolve.account(conn, args.name, include_archived=True)
    new = resolve.clean_name(args.new_name, "nama dompet")
    _ensure_name_free(conn, new, except_id=acc["id"])
    with write(conn):
        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (new, acc["id"]))
    return success(f"Dompet {acc['name']} diganti nama menjadi {new}.",
                   {"id": acc["id"], "old_name": acc["name"], "name": new})


def cmd_archive(args, conn):
    acc = resolve.account(conn, args.name, include_archived=True)
    if acc["archived"]:
        return success(f"Dompet {acc['name']} memang sudah diarsipkan.", {"id": acc["id"], "archived": True})
    bal = balances(conn)[acc["id"]]
    if bal != 0:
        raise FinError("BAD_ARGS", f"Dompet {acc['name']} masih bersaldo {rupiah(bal)}, tidak bisa diarsipkan.",
                       hint=f"Pindahkan dulu saldonya (transfer --from {acc['name']} --to <dompet> --amount {bal}) "
                            f"atau samakan dengan kenyataan (adjust --account {acc['name']} --actual 0).")
    with write(conn):
        conn.execute("UPDATE accounts SET archived = 1, is_default = 0 WHERE id = ?", (acc["id"],))
    msg = f"Dompet {acc['name']} diarsipkan."
    if acc["is_default"]:
        msg += " Dompet ini tadinya default; atur default baru dengan: account set-default <nama>."
    return success(msg, {"id": acc["id"], "archived": True, "was_default": bool(acc["is_default"])})


def cmd_unarchive(args, conn):
    acc = resolve.account(conn, args.name, include_archived=True)
    with write(conn):
        conn.execute("UPDATE accounts SET archived = 0 WHERE id = ?", (acc["id"],))
    return success(f"Dompet {acc['name']} aktif lagi.", {"id": acc["id"], "archived": False})


def cmd_set_default(args, conn):
    acc = resolve.account(conn, args.name)
    if acc["type"] == "savings":
        raise FinError("BAD_ARGS", "Dompet tabungan tidak bisa dijadikan default.",
                       hint="Pilih dompet bertipe cash, bank, atau ewallet.")
    with write(conn):
        conn.execute("UPDATE accounts SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (acc["id"],))
    return success(f"Dompet default sekarang {acc['name']}.", {"id": acc["id"], "name": acc["name"]})


def cmd_set_target(args, conn):
    acc = resolve.account(conn, args.name)
    if acc["type"] != "savings":
        raise FinError("BAD_ARGS", f"Dompet {acc['name']} bukan dompet tabungan.",
                       hint="Target hanya untuk dompet bertipe savings.")
    if args.clear:
        if args.amount or args.date:
            raise FinError("BAD_ARGS", "--clear tidak bisa digabung dengan --amount atau --date.")
        target, target_date = None, None
    else:
        if not args.amount and not args.date:
            raise FinError("BAD_ARGS", "Isi --amount dan/atau --date, atau --clear untuk menghapus target.")
        target = parse_amount(args.amount, field="target") if args.amount else acc["target_amount"]
        target_date = parse_day(args.date, "tanggal target").isoformat() if args.date else acc["target_date"]
    with write(conn):
        conn.execute("UPDATE accounts SET target_amount = ?, target_date = ? WHERE id = ?",
                     (target, target_date, acc["id"]))
    if target is None and target_date is None:
        msg = f"Target tabungan {acc['name']} dihapus."
    else:
        msg = f"Target tabungan {acc['name']}: {rupiah(target) if target else '(tanpa nominal)'}"
        msg += f" pada {fmt_date(target_date)}." if target_date else "."
    return success(msg, {"id": acc["id"], "target_amount": target, "target_date": target_date})
