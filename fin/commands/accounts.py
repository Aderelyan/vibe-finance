"""account add / list / rename / remove / set-default"""
from .. import budgets, clock, resolve
from ..db import UNALLOCATED, write
from ..ledger import ACCOUNT_TYPE_LABEL, balance, balance_sentence, balances, insert_tx, new_group
from ..output import FinError, rupiah, signed_rupiah, success
from ..parse import parse_amount

TYPES = ["cash", "bank", "ewallet"]


def register(sub):
    p = sub.add_parser("account", help="Kelola dompet.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Tambah dompet (atau aktifkan lagi dompet yang pernah dihapus).")
    a.add_argument("name")
    a.add_argument("--type", required=True, choices=TYPES)
    a.add_argument("--opening", help="Saldo awal. Masuk ke budget 'belum teralokasi'.")
    a.add_argument("--default", action="store_true", help="Jadikan dompet default.")
    a.set_defaults(func=cmd_add)

    a = s.add_parser("list", help="Daftar dompet beserta saldo.")
    a.add_argument("--all", action="store_true", help="Sertakan dompet yang sudah dihapus (diarsipkan).")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("rename", help="Ganti nama dompet.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.set_defaults(func=cmd_rename)

    a = s.add_parser("remove", help="Hapus dompet.")
    a.add_argument("name")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--move-to", help="Pindahkan sisa saldo ke dompet ini dulu.")
    g.add_argument("--write-off", action="store_true", help="Nolkan sisa saldo lewat penyesuaian.")
    a.set_defaults(func=cmd_remove)

    a = s.add_parser("set-default", help="Atur dompet default.")
    a.add_argument("name")
    a.set_defaults(func=cmd_set_default)


def _ensure_name_free(conn, name, except_id=None):
    """Nama dompet dan tabungan berbagi satu ruang nama (keduanya tabel accounts)."""
    key = resolve.norm(name)
    for row in conn.execute("SELECT id, name, type FROM accounts"):
        if row["id"] != except_id and resolve.norm(row["name"]) == key:
            what = "Tabungan" if row["type"] == "savings" else "Dompet"
            raise FinError("BAD_ARGS", f"{what} bernama '{row['name']}' sudah ada.",
                           hint="Pakai nama lain, atau lihat daftar dengan: account list --all / savings list --all")
    for row in conn.execute("SELECT al.alias, a.name, a.id FROM aliases al JOIN accounts a ON a.id = al.target_id "
                            "WHERE al.kind = 'account'"):
        if row["id"] != except_id and resolve.norm(row["alias"]) == key:
            raise FinError("BAD_ARGS", f"'{name}' sudah dipakai sebagai alias dompet {row['name']}.",
                           hint=f"Pakai nama lain, atau hapus aliasnya: alias remove --kind account --alias \"{row['alias']}\"")


def _account_dict(row, bal):
    return {"id": row["id"], "name": row["name"], "type": row["type"], "is_default": bool(row["is_default"]),
            "archived": bool(row["archived"]), "balance": bal}


def _has_default(conn):
    return conn.execute("SELECT 1 FROM accounts WHERE is_default = 1 AND archived = 0").fetchone() is not None


def cmd_add(args, conn):
    name = resolve.clean_name(args.name, "nama dompet")
    existing = resolve.find_account(conn, name)  # dompet yang dihapus (diarsipkan) akan diaktifkan kembali
    if existing is not None and existing["type"] == "savings":
        raise FinError("BAD_ARGS", f"Nama '{existing['name']}' sudah dipakai tabungan.",
                       hint="Pakai nama lain untuk dompet ini.")
    if existing is None or not existing["archived"]:
        _ensure_name_free(conn, name)
    opening = None
    if args.opening is not None:
        opening = parse_amount(args.opening, allow_zero=True, allow_negative=True, field="saldo awal")
    make_default = args.default or not _has_default(conn)
    now = clock.now_ts()
    unalloc = budgets.unallocated(conn)

    with write(conn):
        if make_default:
            conn.execute("UPDATE accounts SET is_default = 0")
        if existing is None:
            acc_id = conn.execute("INSERT INTO accounts(name, type, is_default, created_at) VALUES (?,?,?,?)",
                                  (name, args.type, int(make_default), now)).lastrowid
            current = 0
        else:
            acc_id = existing["id"]
            conn.execute("UPDATE accounts SET archived = 0, type = ?, is_default = ? WHERE id = ?",
                         (args.type, int(make_default), acc_id))
            current = balance(conn, acc_id)
        diff = (opening - current) if opening is not None else 0
        if diff:
            insert_tx(conn, ts=now, type="adjustment", amount=diff, account_id=acc_id, budget_id=unalloc["id"],
                      note="saldo awal", group_id=new_group(conn, "opening"))

    bal = balance(conn, acc_id)
    if existing is None:
        msg = f"Dompet {name} ({ACCOUNT_TYPE_LABEL[args.type]}) dibuat dengan saldo awal {rupiah(bal)}."
    else:
        msg = f"Dompet {existing['name']} ({ACCOUNT_TYPE_LABEL[args.type]}) diaktifkan kembali dengan saldo {rupiah(bal)}."
    if diff:
        msg += f" {signed_rupiah(diff)} masuk ke budget {UNALLOCATED}."
    if make_default:
        msg += " Dijadikan dompet default." if args.default else \
            " Dijadikan dompet default karena belum ada dompet default."
    if bal < 0:
        msg += " Peringatan: saldo awal minus."
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (acc_id,)).fetchone()
    return success(msg, {"account": _account_dict(row, bal), "reactivated": existing is not None})


def cmd_list(args, conn):
    bals = balances(conn)
    sql = "SELECT * FROM accounts WHERE type != 'savings'" + ("" if args.all else " AND archived = 0") + " ORDER BY id"
    rows = conn.execute(sql).fetchall()
    if not rows:
        return success("Belum ada dompet. Tambahkan dengan: account add <nama> --type cash|bank|ewallet "
                       "--opening <saldo>.", {"accounts": []})
    lines = []
    for r in rows:
        line = f"- {r['name']} ({ACCOUNT_TYPE_LABEL[r['type']]}): {rupiah(bals[r['id']])}"
        if r["is_default"]:
            line += " [default]"
        if r["archived"]:
            line += " [dihapus]"
        lines.append(line)
    return success("Daftar dompet:\n" + "\n".join(lines),
                   {"accounts": [_account_dict(r, bals[r["id"]]) for r in rows]})


def cmd_rename(args, conn):
    acc = resolve.account(conn, args.name)
    new = resolve.clean_name(args.new_name, "nama dompet")
    _ensure_name_free(conn, new, except_id=acc["id"])
    with write(conn):
        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (new, acc["id"]))
    return success(f"Dompet {acc['name']} diganti nama menjadi {new}.",
                   {"id": acc["id"], "old_name": acc["name"], "name": new})


def _is_used(conn, acc_id):
    return bool(conn.execute("SELECT 1 FROM transactions WHERE account_id = ? OR to_account_id = ? LIMIT 1",
                             (acc_id, acc_id)).fetchone()
                or conn.execute("SELECT 1 FROM recurring WHERE account_id = ? LIMIT 1", (acc_id,)).fetchone())


def cmd_remove(args, conn):
    acc = resolve.find_account(conn, args.name)
    if acc is None or acc["type"] == "savings":
        resolve.account(conn, args.name)  # melempar UNKNOWN_ACCOUNT dengan hint (tabungan: pakai savings remove)
    bal = balance(conn, acc["id"])
    if acc["archived"] and bal == 0:
        raise FinError("UNKNOWN_ACCOUNT", f"Dompet '{acc['name']}' sudah dihapus.",
                       hint=resolve._account_hint(conn))
    others = [r["name"] for r in conn.execute("SELECT name FROM accounts WHERE archived = 0 AND type != 'savings' "
                                              "AND id != ? ORDER BY id", (acc["id"],))]
    if acc["is_default"] and others:
        raise FinError("BAD_ARGS", f"Dompet {acc['name']} adalah dompet default.",
                       hint=f"Pindahkan default dulu, contoh: account set-default {others[0]}")
    if bal != 0 and not (args.move_to or args.write_off):
        target = others[0] if others else "<dompet lain>"
        raise FinError("NOT_EMPTY", f"Dompet {acc['name']} masih berisi {rupiah(bal)}.",
                       hint=f"Pilih salah satu: account remove {acc['name']} --move-to {target} "
                            f"(sisa dipindah ke dompet lain), atau account remove {acc['name']} --write-off "
                            f"(sisa dinolkan, budget {UNALLOCATED} ikut berkurang).",
                       data={"balance": bal})
    dst = None
    if args.move_to and bal != 0:
        dst = resolve.account(conn, args.move_to)
        if dst["id"] == acc["id"]:
            raise FinError("BAD_ARGS", "Dompet tujuan tidak boleh dompet yang sama.")

    now = clock.now_ts()
    with write(conn):
        moved_ids = [acc["id"]]
        if bal != 0:
            group = new_group(conn, "account_remove", restore=[["accounts", acc["id"]]])
            if dst is not None:
                src_id, dst_id = (acc["id"], dst["id"]) if bal > 0 else (dst["id"], acc["id"])
                insert_tx(conn, ts=now, type="transfer", amount=abs(bal), account_id=src_id, to_account_id=dst_id,
                          note=f"hapus dompet {acc['name']}", group_id=group)
                moved_ids.append(dst["id"])
            else:
                insert_tx(conn, ts=now, type="adjustment", amount=-bal, account_id=acc["id"],
                          budget_id=budgets.unallocated(conn)["id"], note=f"hapus dompet {acc['name']}",
                          group_id=group)
        if _is_used(conn, acc["id"]):
            mode = "archived"
            conn.execute("UPDATE accounts SET archived = 1, is_default = 0 WHERE id = ?", (acc["id"],))
        else:
            mode = "deleted"
            conn.execute("DELETE FROM aliases WHERE kind = 'account' AND target_id = ?", (acc["id"],))
            conn.execute("DELETE FROM accounts WHERE id = ?", (acc["id"],))

    if mode == "deleted":
        msg = f"Dompet {acc['name']} dihapus permanen karena belum pernah dipakai transaksi."
    else:
        msg = f"Dompet {acc['name']} dihapus. Riwayat transaksinya tetap disimpan (diarsipkan)."
    if bal != 0 and dst is not None:
        msg += f" Sisa {rupiah(bal)} dipindah ke {dst['name']}. " + balance_sentence(conn, [dst["id"]])
    elif bal != 0:
        unalloc = budgets.unallocated(conn)
        msg += (f" Sisa {rupiah(bal)} dinolkan lewat penyesuaian; budget {UNALLOCATED} ikut berubah "
                f"{signed_rupiah(-bal)}. " + budgets.sentence(conn, [unalloc["id"]]))
    if acc["is_default"]:
        msg += " Sekarang tidak ada dompet default; tambahkan dompet baru dengan account add."
    return success(msg, {"id": acc["id"], "name": acc["name"], "mode": mode, "balance_before": bal,
                         "moved_to": dst["name"] if dst is not None else None,
                         "written_off": bool(bal and dst is None)})


def cmd_set_default(args, conn):
    acc = resolve.account(conn, args.name)
    with write(conn):
        conn.execute("UPDATE accounts SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (acc["id"],))
    return success(f"Dompet default sekarang {acc['name']}.", {"id": acc["id"], "name": acc["name"]})
