"""debt add / pay / list / set / rename / remove"""
from .. import budgets, clock, debts, resolve
from ..db import UNALLOCATED, write
from ..debts import OPENING_TYPE, PAYMENT_TYPE
from ..ledger import balance, balance_sentence, insert_tx, new_group
from ..output import FinError, fmt_date, rupiah, success
from ..parse import parse_amount, parse_date, parse_day

DIRECTIONS = ["i_owe", "owed_to_me"]
DIRECTION_HELP = "i_owe = saya berhutang ke orang lain; owed_to_me = orang lain berhutang ke saya (piutang)."


def register(sub):
    p = sub.add_parser("debt", help="Hutang dan piutang.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Catat hutang (saya pinjam) atau piutang (orang pinjam ke saya).")
    a.add_argument("--direction", required=True, choices=DIRECTIONS, help=DIRECTION_HELP)
    a.add_argument("--person", required=True)
    a.add_argument("--amount", required=True)
    a.add_argument("--account", help="Dompet tempat uang masuk/keluar (bawaan: dompet default).")
    a.add_argument("--budget", help=f"Khusus piutang (uang keluar): ambil dari budget ini, bukan '{UNALLOCATED}'.")
    a.add_argument("--due", help="Jatuh tempo, YYYY-MM-DD.")
    a.add_argument("--note")
    a.add_argument("--date", help="Tanggal pinjam: YYYY-MM-DD, today, atau yesterday.")
    a.add_argument("--no-cash", action="store_true", help="Tanpa aliran uang: dompet dan budget tidak berubah.")
    a.add_argument("--paid-for", help="Khusus i_owe: orang itu membayari sesuatu untukmu, \"catatan|kategori\" "
                                      "(kategori opsional). Hutang dan pengeluarannya dicatat sekaligus; "
                                      "saldo dompet tidak berubah.")
    a.add_argument("--raw", help="Teks asli dari pengguna.")
    a.set_defaults(func=cmd_add)

    a = s.add_parser("pay", help="Catat pembayaran hutang atau piutang (boleh sebagian).")
    _target_args(a)
    a.add_argument("--amount", required=True, help="Jumlah, atau 'all' untuk melunasi sisanya.")
    a.add_argument("--account", help="Dompet (bawaan: dompet default).")
    a.add_argument("--budget", help=f"Khusus bayar hutang (uang keluar): ambil dari budget ini, bukan '{UNALLOCATED}'.")
    a.add_argument("--date")
    a.add_argument("--note")
    a.add_argument("--raw")
    a.set_defaults(func=cmd_pay)

    a = s.add_parser("list", help="Daftar hutang piutang beserta sisa dan jatuh tempo.")
    a.add_argument("--status", choices=["open", "paid", "all"], default="open")
    a.add_argument("--person")
    a.add_argument("--direction", choices=DIRECTIONS)
    a.add_argument("--all", action="store_true", help="Sertakan yang sudah dihapus (diarsipkan).")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("set", help="Ubah jatuh tempo atau catatan.")
    _target_args(a)
    a.add_argument("--due", help="YYYY-MM-DD")
    a.add_argument("--clear-due", action="store_true", help="Hapus jatuh tempo.")
    a.add_argument("--note", help="Catatan baru (kosongkan dengan --note \"\").")
    a.set_defaults(func=cmd_set)

    a = s.add_parser("rename", help="Ganti nama orang di semua catatan hutang piutangnya.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.set_defaults(func=cmd_rename)

    a = s.add_parser("remove", help="Hapus catatan hutang piutang.")
    _target_args(a)
    a.add_argument("--write-off", action="store_true",
                   help="Sisa yang belum dibayar dianggap selesai (tanpa uang, dompet dan budget tidak berubah).")
    a.set_defaults(func=cmd_remove)


def _target_args(parser):
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--person")
    g.add_argument("--id", type=int)
    parser.add_argument("--direction", choices=DIRECTIONS, help="Persempit pencarian --person.")


def _find(conn, args, require_open):
    person = resolve.clean_name(args.person, "nama orang") if args.person is not None else None
    return debts.find(conn, debt_id=args.id, person=person, direction=args.direction, require_open=require_open)


def _money_budget(conn, name, money_out, hint_cmd):
    """Budget untuk transaksi hutang: uang masuk selalu ke 'belum teralokasi'; uang keluar boleh --budget."""
    if name and not money_out:
        raise FinError("BAD_ARGS", "--budget hanya untuk uang yang keluar.",
                       hint=f"Uang yang masuk ({hint_cmd}) selalu masuk ke {UNALLOCATED}; bagi lewat budget alloc.")
    return budgets.find(conn, name) if name else budgets.unallocated(conn)


def _person_total_text(conn, debt):
    rows = [d for d in debts.person_matches(conn, debt["person"])
            if d["direction"] == debt["direction"] and d["status"] == "open"]
    total = sum(debts.remaining(conn, d) for d in rows)
    text = f"Total {debts.title(debt)} sekarang {rupiah(total)}"
    if len(rows) > 1:
        text += f" dari {len(rows)} catatan"
    return text + "."


# ---------- add ----------

PAID_FOR_HINT = 'Format --paid-for "catatan|kategori" atau "catatan", contoh --paid-for "makan siang|makan".'


def _parse_paid_for(conn, raw):
    """(catatan, kategori pengeluaran, cara kategori ditentukan) dari --paid-for."""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) > 2 or not parts[0]:
        raise FinError("BAD_ARGS", f"--paid-for '{raw}' tidak sesuai format.", hint=PAID_FOR_HINT)
    if len(parts) == 2 and parts[1]:
        return parts[0], resolve.category(conn, parts[1], "expense"), None
    cat, keyword = resolve.guess_category(conn, parts[0], "expense")
    return parts[0], cat, (f"ditebak dari kata '{keyword}'" if keyword else "tidak ada kata kunci yang cocok")


def cmd_add(args, conn):
    person = resolve.clean_name(args.person, "nama orang")
    person = debts.known_person(conn, person) or person
    amount = parse_amount(args.amount)
    due = parse_day(args.due, "jatuh tempo").isoformat() if args.due else None
    money_out = args.direction == "owed_to_me"
    paid_for = None
    if args.paid_for is not None:
        if args.no_cash:
            raise FinError("BAD_ARGS", "--paid-for tidak bisa dipakai bersama --no-cash.",
                           hint="--paid-for sudah mencatat hutang dan pengeluarannya sekaligus tanpa mengubah saldo.")
        if money_out:
            raise FinError("BAD_ARGS", "--paid-for hanya untuk --direction i_owe (orang lain membayari kamu).",
                           hint="Untuk piutang tanpa uang keluar sekarang, pakai --no-cash.")
        paid_for = _parse_paid_for(conn, args.paid_for)
    if args.no_cash:
        for opt, val in (("--account", args.account), ("--budget", args.budget), ("--date", args.date)):
            if val:
                raise FinError("BAD_ARGS", f"{opt} tidak bisa dipakai bersama --no-cash.",
                               hint="--no-cash berarti tidak ada uang yang masuk atau keluar dompet.")
        acc = bud = None
        used_default = False
        ts = None
    else:
        acc, used_default = resolve.account_or_default(conn, args.account)
        bud = _money_budget(conn, args.budget, money_out, "uang pinjaman yang kamu terima")
        ts = parse_date(args.date) if args.date else clock.now_ts()

    tx_id = group = expense_id = expense_budget = None
    with write(conn):
        debt_note = args.note or (paid_for[0] if paid_for else None)
        debt_id = conn.execute("INSERT INTO debts(direction, person, principal, due_date, note, created_at) "
                               "VALUES (?,?,?,?,?,?)", (args.direction, person, amount, due, debt_note,
                                                        clock.now_ts())).lastrowid
        if acc is not None:
            group = new_group(conn, "debt_add", restore=[["debts", debt_id, 1]])
            if paid_for:
                note = f"{person} membayari {paid_for[0]}"
            else:
                note = f"pinjam dari {person}" if args.direction == "i_owe" else f"dipinjam {person}"
            if args.note:
                note += f" ({args.note})"
            tx_id = insert_tx(conn, ts=ts, type=OPENING_TYPE[args.direction], amount=amount, account_id=acc["id"],
                              debt_id=debt_id, budget_id=bud["id"], note=note, raw_text=args.raw, group_id=group)
            if paid_for:
                # uang pinjaman langsung terpakai: saldo dompet tetap, budget kategorinya terpotong
                expense_budget = budgets.for_expense(conn, paid_for[1]["id"])
                expense_id = insert_tx(conn, ts=ts, type="expense", amount=amount, account_id=acc["id"],
                                       category_id=paid_for[1]["id"], budget_id=expense_budget["id"],
                                       note=f"{paid_for[0]} (dibayari {person})", raw_text=args.raw, group_id=group)
    debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()

    if args.direction == "i_owe":
        msg = f"Tercatat hutang ke {person} {rupiah(amount)} (#{debt_id})"
    else:
        msg = f"Tercatat piutang: {person} pinjam {rupiah(amount)} ke kamu (#{debt_id})"
    due_txt = debts.due_text(due)
    msg += f", {due_txt}." if due_txt else "."
    if acc is None:
        msg += " Tanpa aliran uang: dompet dan budget tidak berubah."
    elif paid_for:
        cat = paid_for[1]["name"] + (f", {paid_for[2]}" if paid_for[2] else "")
        msg += (f" {person} membayari {paid_for[0]}, dicatat sebagai pengeluaran {rupiah(amount)} "
                f"(kategori {cat}). Saldo {acc['name']} tidak berubah; budget {UNALLOCATED} bertambah "
                f"{rupiah(amount)} dari hutang, budget {expense_budget['name']} berkurang {rupiah(amount)}.")
        if ts[:10] != clock.today().isoformat():
            msg += f" Tanggal: {fmt_date(ts)}."
        msg += " " + balance_sentence(conn, [acc["id"]]) + " " + budgets.sentence(conn, [bud["id"], expense_budget["id"]])
    else:
        acc_text = acc["name"] + (" (dompet default)" if used_default else "")
        msg += (f" Uangnya masuk ke {acc_text} dan ke budget {bud['name']}." if not money_out else
                f" Uangnya keluar dari {acc_text}, diambil dari budget {bud['name']}.")
        if ts[:10] != clock.today().isoformat():
            msg += f" Tanggal: {fmt_date(ts)}."
        msg += " " + balance_sentence(conn, [acc["id"]]) + " " + budgets.sentence(conn, [bud["id"]])
    msg += " " + _person_total_text(conn, debt)
    return success(msg, {"debt": debts.info(conn, debt), "transaction_id": tx_id, "group_id": group,
                         "expense_id": expense_id,
                         "expense_category": paid_for[1]["name"] if paid_for else None,
                         "expense_budget": expense_budget["name"] if expense_budget else None,
                         "account": acc["name"] if acc else None, "used_default_account": used_default,
                         "budget": bud["name"] if bud else None,
                         "balance_after": balance(conn, acc["id"]) if acc else None})


# ---------- pay ----------

def cmd_pay(args, conn):
    debt = _find(conn, args, require_open=True)
    rest = debts.remaining(conn, debt)
    if rest <= 0:
        raise FinError("OVERPAYMENT", f"{debts.title(debt, cap=True)} (#{debt['id']}) sudah lunas.",
                       hint="Lihat daftar: debt list --status all")
    if args.amount.strip().lower() in ("all", "semua", "lunas"):
        amount = rest
    else:
        amount = parse_amount(args.amount)
    if amount > rest:
        raise FinError("OVERPAYMENT", f"Pembayaran {rupiah(amount)} melebihi sisa {debts.title(debt)} "
                                      f"(#{debt['id']}) yaitu {rupiah(rest)}.",
                       hint=f"Bayar paling banyak {rupiah(rest)}, atau pakai --amount all untuk melunasi.",
                       data={"remaining": rest})
    money_out = debt["direction"] == "i_owe"
    acc, used_default = resolve.account_or_default(conn, args.account)
    bud = _money_budget(conn, args.budget, money_out, "pembayaran piutang yang kamu terima")
    ts = parse_date(args.date) if args.date else clock.now_ts()

    with write(conn):
        group = new_group(conn, "debt_pay")
        note = f"bayar hutang ke {debt['person']}" if money_out else f"{debt['person']} bayar piutang"
        if args.note:
            note += f" ({args.note})"
        tx_id = insert_tx(conn, ts=ts, type=PAYMENT_TYPE[debt["direction"]], amount=amount, account_id=acc["id"],
                          debt_id=debt["id"], budget_id=bud["id"], note=note, raw_text=args.raw, group_id=group)
        debts.recompute_status(conn, debt["id"])
    debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt["id"],)).fetchone()
    left = debts.remaining(conn, debt)

    acc_text = acc["name"] + (" (dompet default)" if used_default else "")
    if money_out:
        msg = f"Bayar hutang ke {debt['person']} {rupiah(amount)} dari {acc_text}."
    else:
        msg = f"{debt['person']} membayar piutang {rupiah(amount)}, masuk ke {acc_text}."
    if left == 0:
        msg += f" {debts.title(debt, cap=True)} (#{debt['id']}) LUNAS."
    else:
        msg += f" Sisa {debts.title(debt)} (#{debt['id']}) {rupiah(left)}."
    if ts[:10] != clock.today().isoformat():
        msg += f" Tanggal: {fmt_date(ts)}."
    msg += " " + balance_sentence(conn, [acc["id"]]) + " " + budgets.sentence(conn, [bud["id"]])
    return success(msg, {"debt": debts.info(conn, debt), "transaction_id": tx_id, "group_id": group,
                         "amount": amount, "remaining": left, "paid_off": left == 0, "account": acc["name"],
                         "used_default_account": used_default, "budget": bud["name"],
                         "balance_after": balance(conn, acc["id"])})


# ---------- list ----------

def cmd_list(args, conn):
    sql = "SELECT * FROM debts" + ("" if args.all else " WHERE archived = 0") + " ORDER BY id"
    rows = conn.execute(sql).fetchall()
    if args.status != "all":
        rows = [d for d in rows if d["status"] == args.status]
    if args.direction:
        rows = [d for d in rows if d["direction"] == args.direction]
    if args.person:
        key = resolve.norm(args.person)
        rows = [d for d in rows if resolve.norm(d["person"]) == key]
    items = [debts.info(conn, d) for d in rows]
    owe, owed = debts.totals(conn)
    soon = [i for i in items if i["status"] == "open" and not i["archived"]
            and i["days_until_due"] is not None and i["days_until_due"] <= 7]
    data = {"debts": items, "count": len(items), "debt_total": owe, "receivable_total": owed,
            "due_within_7_days": [i["id"] for i in soon]}

    status_word = {"open": "yang belum lunas", "paid": "yang sudah lunas", "all": ""}[args.status]
    scope = f" atas nama {args.person}" if args.person else ""
    if not items:
        msg = f"Tidak ada hutang/piutang {status_word}{scope}.".replace("  ", " ")
    else:
        lines = []
        for direction, head in (("i_owe", "Hutang saya"), ("owed_to_me", "Piutang (orang berhutang ke saya)")):
            group = [i for i in items if i["direction"] == direction]
            if group:
                lines.append(f"{head}:")
                lines += [f"- {debts.line(i)}" for i in group]
        msg = "\n".join(lines)
    msg += f"\nTotal hutang saya: {rupiah(owe)} | Total piutang: {rupiah(owed)}."
    overdue = [i for i in soon if i["days_until_due"] < 0]
    if overdue:
        msg += f" Ada {len(overdue)} yang sudah lewat jatuh tempo."
    elif soon:
        msg += f" Ada {len(soon)} yang jatuh tempo dalam 7 hari."
    return success(msg, data)


# ---------- set / rename / remove ----------

def cmd_set(args, conn):
    debt = _find(conn, args, require_open=False)
    if args.due is None and not args.clear_due and args.note is None:
        raise FinError("BAD_ARGS", "Tidak ada yang diubah.", hint="Isi --due, --clear-due, atau --note.")
    if args.due and args.clear_due:
        raise FinError("BAD_ARGS", "--due tidak bisa digabung dengan --clear-due.")
    due = debt["due_date"]
    if args.due:
        due = parse_day(args.due, "jatuh tempo").isoformat()
    elif args.clear_due:
        due = None
    note = debt["note"] if args.note is None else (args.note.strip() or None)
    with write(conn):
        conn.execute("UPDATE debts SET due_date = ?, note = ? WHERE id = ?", (due, note, debt["id"]))
    debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt["id"],)).fetchone()
    changes = []
    if args.due or args.clear_due:
        changes.append(debts.due_text(due) or "tanpa jatuh tempo")
    if args.note is not None:
        changes.append(f"catatan: {note}" if note else "catatan dihapus")
    msg = f"{debts.title(debt, cap=True)} (#{debt['id']}) diubah: {'; '.join(changes)}."
    return success(msg, {"debt": debts.info(conn, debt)})


def cmd_rename(args, conn):
    old = resolve.clean_name(args.name, "nama orang")
    rows = debts.person_matches(conn, old, include_archived=True)
    if not rows:
        raise FinError("NOT_FOUND", f"Tidak ada hutang/piutang atas nama '{old}'.",
                       hint="Lihat daftar: debt list --status all")
    new = resolve.clean_name(args.new_name, "nama orang")
    others = [d for d in debts.person_matches(conn, new, include_archived=True) if d["id"] not in {r["id"] for r in rows}]
    with write(conn):
        for d in rows:
            conn.execute("UPDATE debts SET person = ? WHERE id = ?", (new, d["id"]))
        for d in others:  # samakan ejaan supaya jadi satu orang
            conn.execute("UPDATE debts SET person = ? WHERE id = ?", (new, d["id"]))
    msg = f"Nama {rows[0]['person']} diganti menjadi {new} di {len(rows)} catatan hutang/piutang."
    if others:
        msg += f" Digabung dengan {len(others)} catatan yang sudah atas nama {new}."
    return success(msg, {"old_name": rows[0]["person"], "name": new, "ids": [d["id"] for d in rows],
                         "merged_ids": [d["id"] for d in others]})


def cmd_remove(args, conn):
    debt = _find(conn, args, require_open=False)
    rest = debts.remaining(conn, debt)
    tx_ids = [r[0] for r in conn.execute("SELECT id FROM transactions WHERE debt_id = ? ORDER BY id", (debt["id"],))]
    active = [r[0] for r in conn.execute(
        "SELECT id FROM transactions WHERE debt_id = ? AND deleted_at IS NULL ORDER BY id", (debt["id"],))]
    label = f"{debts.title(debt, cap=True)} (#{debt['id']})"
    if tx_ids and rest > 0 and not args.write_off:
        ids = ", ".join(str(i) for i in active)
        target = f"--id {debt['id']}"
        raise FinError("NOT_EMPTY", f"{label} masih bersisa {rupiah(rest)}.",
                       hint=f"Pilih salah satu: debt pay {target} --amount all (lunasi), atau debt remove {target} "
                            f"--write-off (sisa dianggap selesai tanpa uang)."
                            + (f" Jika salah catat, hapus transaksinya dulu: delete <id> (ID: {ids})." if ids else ""),
                       data={"remaining": rest, "transaction_ids": active})
    with write(conn):
        if not tx_ids:
            mode = "deleted"
            conn.execute("DELETE FROM debts WHERE id = ?", (debt["id"],))
        else:
            mode = "archived"
            conn.execute("UPDATE debts SET archived = 1 WHERE id = ?", (debt["id"],))
    if mode == "deleted":
        msg = f"{label} dihapus permanen karena tidak punya transaksi."
    else:
        msg = f"{label} dihapus. Riwayat transaksinya tetap disimpan (diarsipkan)."
        if rest > 0:
            msg += f" Sisa {rupiah(rest)} dianggap selesai; dompet dan budget tidak berubah."
    owe, owed = debts.totals(conn)
    msg += f" Total hutang saya: {rupiah(owe)} | Total piutang: {rupiah(owed)}."
    return success(msg, {"id": debt["id"], "mode": mode, "written_off": rest if (mode == "archived" and rest > 0) else 0,
                         "debt_total": owe, "receivable_total": owed})
