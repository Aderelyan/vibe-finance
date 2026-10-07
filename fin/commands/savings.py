"""savings add / list / set / rename / remove / deposit / withdraw / spend.

Tabungan adalah akun berjenis savings, terpisah dari dompet operasional dan di luar aturan utama
(total dompet operasional = total budget). Lihat ledger.py untuk efek tiap jenis transaksi.
"""
from .. import budgets, clock, debts, resolve
from ..db import UNALLOCATED, write
from ..ledger import ACCOUNT_DELTA_SQL, add_restore, balance, balance_sentence, balances, insert_tx, new_group
from ..output import FinError, fmt_date, fmt_pct, percent, rupiah, signed_rupiah, success
from ..parse import parse_amount, parse_date, parse_day
from .accounts import _ensure_name_free
from .transactions import _category_text, _parse_item


def register(sub):
    p = sub.add_parser("savings", help="Tabungan: akun terpisah dari dompet operasional dan budget.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Buat tabungan (atau aktifkan lagi yang pernah dihapus).")
    a.add_argument("name")
    a.add_argument("--target")
    a.add_argument("--target-date", help="YYYY-MM-DD")
    a.add_argument("--opening", help="Saldo awal tabungan yang sudah ada. Tidak mengubah dompet atau budget.")
    a.set_defaults(func=cmd_add)

    a = s.add_parser("list", help="Saldo, target, dan perkembangan tiap tabungan.")
    a.add_argument("--all", action="store_true", help="Sertakan tabungan yang sudah dihapus (diarsipkan).")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("set", help="Ubah atau hapus target tabungan.")
    a.add_argument("name")
    a.add_argument("--target")
    a.add_argument("--target-date", help="YYYY-MM-DD")
    a.add_argument("--clear", action="store_true", help="Hapus target nominal dan tanggal.")
    a.set_defaults(func=cmd_set)

    a = s.add_parser("rename", help="Ganti nama tabungan.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.set_defaults(func=cmd_rename)

    a = s.add_parser("remove", help="Hapus tabungan.")
    a.add_argument("name")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--move-to", help="Pindahkan sisa saldo ke dompet (masuk ke 'belum teralokasi') atau tabungan lain.")
    g.add_argument("--write-off", action="store_true", help="Nolkan sisa saldo lewat penyesuaian (budget tidak berubah).")
    a.set_defaults(func=cmd_remove)

    a = s.add_parser("deposit", help="Menabung: dompet dan budget berkurang, tabungan bertambah.")
    a.add_argument("--from", dest="from_account", required=True, help="Dompet asal.")
    a.add_argument("--to", dest="to_savings", required=True, help="Tabungan tujuan.")
    a.add_argument("--amount", required=True)
    a.add_argument("--from-budget", help=f"Budget yang dikurangi (bawaan: '{UNALLOCATED}').")
    a.add_argument("--date")
    a.add_argument("--note")
    a.add_argument("--raw", help="Teks asli dari pengguna.")
    a.set_defaults(func=cmd_deposit)

    a = s.add_parser("withdraw", help="Menarik tabungan: tabungan berkurang, dompet dan budget bertambah.")
    a.add_argument("--from", dest="from_savings", required=True, help="Tabungan asal.")
    a.add_argument("--to", dest="to_account", required=True, help="Dompet tujuan.")
    a.add_argument("--amount", required=True, help="Jumlah, atau 'all' untuk seluruh saldo tabungan.")
    a.add_argument("--to-budget", help=f"Budget yang bertambah (bawaan: '{UNALLOCATED}').")
    a.add_argument("--date")
    a.add_argument("--note")
    a.add_argument("--raw", help="Teks asli dari pengguna.")
    a.set_defaults(func=cmd_withdraw)

    a = s.add_parser("spend", help="Belanja langsung dari tabungan (purpose) atau meminjam dari tabungan (debt).")
    a.add_argument("--from", dest="from_savings", required=True, help="Tabungan.")
    a.add_argument("--item", action="append", required=True, help="catatan|jumlah|kategori (kategori opsional)")
    a.add_argument("--mode", required=True, choices=["purpose", "debt"],
                   help="purpose: pengeluaran sesuai tujuan tabungan. debt: pinjam dari tabungan, dicatat sebagai "
                        "hutang ke tabungan dan baru menjadi pengeluaran saat dikembalikan (debt pay).")
    a.add_argument("--date")
    a.add_argument("--raw", help="Teks asli dari pengguna.")
    a.set_defaults(func=cmd_spend)


# ---------- helper ----------

def _savings(conn, name, include_archived=False):
    return resolve.account(conn, name, include_archived=include_archived, kind="savings")


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


def _month_change(conn, account_id):
    today = clock.today()
    start, end = f"{today.replace(day=1).isoformat()} 00:00:00", f"{today.isoformat()} 23:59:59"
    return conn.execute(f"SELECT COALESCE(SUM({ACCOUNT_DELTA_SQL}), 0) FROM transactions t "
                        "WHERE t.deleted_at IS NULL AND (t.account_id = :acc OR t.to_account_id = :acc) "
                        "AND t.ts BETWEEN :s AND :e", {"acc": account_id, "s": start, "e": end}).fetchone()[0]


def _info(conn, row, bals=None):
    bals = bals if bals is not None else balances(conn)
    bal, target = bals[row["id"]], row["target_amount"]
    return {"id": row["id"], "name": row["name"], "balance": bal, "target_amount": target,
            "target_date": row["target_date"], "archived": bool(row["archived"]),
            "percent": percent(bal, target) if target else None,
            "shortfall": max(target - bal, 0) if target else None,
            "month_change": _month_change(conn, row["id"]),
            "loans_outstanding": debts.savings_loans_total(conn, row["id"])}


def _progress_text(info):
    if not info["target_amount"]:
        return ""
    return f" ({fmt_pct(info['percent'])} dari target {rupiah(info['target_amount'])})"


def _ts(args):
    return parse_date(args.date) if args.date else clock.now_ts()


def _date_note(ts):
    return f" Tanggal: {fmt_date(ts)}." if ts[:10] != clock.today().isoformat() else ""


def _amount_or_all(text, available, what):
    if text.strip().lower() in ("all", "semua"):
        if available <= 0:
            raise FinError("BAD_AMOUNT", f"{what} tidak punya saldo untuk ditarik (saldo {rupiah(available)}).")
        return available
    return parse_amount(text)


def _ensure_enough(sav, available, amount, action):
    if amount > available:
        raise FinError("BAD_AMOUNT", f"Saldo tabungan {sav['name']} tidak cukup untuk {action} {rupiah(amount)}: "
                                     f"sisanya {rupiah(available)}.",
                       hint=f"Kurangi jumlahnya, paling banyak {rupiah(max(available, 0))}, atau isi dulu lewat "
                            f"savings deposit --to \"{sav['name']}\".",
                       data={"savings_balance": available})


# ---------- add / list / set / rename ----------

def cmd_add(args, conn):
    name = resolve.clean_name(args.name, "nama tabungan")
    existing = resolve.find_account(conn, name)
    reactivate = existing is not None and existing["archived"] and existing["type"] == "savings"
    if not reactivate:
        _ensure_name_free(conn, name)
    opening = parse_amount(args.opening, allow_zero=True, field="saldo awal") if args.opening is not None else None
    with write(conn):
        if reactivate:
            sav_id = existing["id"]
            target, target_date = _targets(args, existing["target_amount"], existing["target_date"])
            conn.execute("UPDATE accounts SET archived = 0, target_amount = ?, target_date = ? WHERE id = ?",
                         (target, target_date, sav_id))
        else:
            target, target_date = _targets(args)
            sav_id = conn.execute("INSERT INTO accounts(name, type, target_amount, target_date, created_at) "
                                  "VALUES (?, 'savings', ?, ?, ?)",
                                  (name, target, target_date, clock.now_ts())).lastrowid
        diff = (opening - balance(conn, sav_id)) if opening is not None else 0
        if diff:
            insert_tx(conn, ts=clock.now_ts(), type="adjustment", amount=diff, account_id=sav_id,
                      note="saldo awal tabungan", group_id=new_group(conn, "opening"))
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (sav_id,)).fetchone()
    info = _info(conn, row)
    verb = "diaktifkan kembali" if reactivate else "dibuat"
    msg = f"Tabungan {row['name']} {verb} ({_target_text(info['target_amount'], info['target_date'])}), saldo {rupiah(info['balance'])}."
    if diff:
        msg += " Saldo awal tidak mengubah dompet maupun budget."
    msg += f" Isi dengan: savings deposit --from <dompet> --to \"{row['name']}\" --amount 100k"
    return success(msg, {"savings": info, "reactivated": reactivate})


def cmd_list(args, conn):
    sql = "SELECT * FROM accounts WHERE type = 'savings'" + ("" if args.all else " AND archived = 0") + " ORDER BY id"
    rows = conn.execute(sql).fetchall()
    if not rows:
        return success("Belum ada tabungan. Buat dengan: savings add \"dana darurat\" --target 5jt",
                       {"savings": [], "total": 0, "month_change_total": 0, "loans_outstanding_total": 0})
    bals = balances(conn)
    items, lines = [], []
    for r in rows:
        item = _info(conn, r, bals)
        items.append(item)
        line = f"- {r['name']}{' (dihapus)' if r['archived'] else ''}: {rupiah(item['balance'])}"
        if item["target_amount"]:
            line += (f" dari target {rupiah(item['target_amount'])} ({fmt_pct(item['percent'])}), "
                     f"kurang {rupiah(item['shortfall'])}")
        if r["target_date"]:
            line += f", tenggat {fmt_date(r['target_date'])}"
        line += f". Bulan ini {signed_rupiah(item['month_change'])}."
        if item["loans_outstanding"]:
            line += f" Pinjaman belum dikembalikan {rupiah(item['loans_outstanding'])}."
        if item["balance"] < 0:
            line += " [minus]"
        lines.append(line)
    total = sum(i["balance"] for i in items)
    change = sum(i["month_change"] for i in items)
    loans = sum(i["loans_outstanding"] for i in items)
    msg = ("Tabungan (terpisah dari dompet dan budget):\n" + "\n".join(lines)
           + f"\nTotal tabungan: {rupiah(total)} (bulan ini {signed_rupiah(change)}).")
    return success(msg, {"savings": items, "total": total, "month_change_total": change,
                         "loans_outstanding_total": loans})


def cmd_set(args, conn):
    sav = _savings(conn, args.name)
    if args.clear:
        if args.target or args.target_date:
            raise FinError("BAD_ARGS", "--clear tidak bisa digabung dengan --target atau --target-date.")
        target, target_date = None, None
    else:
        if not args.target and not args.target_date:
            raise FinError("BAD_ARGS", "Isi --target dan/atau --target-date, atau --clear untuk menghapus target.")
        target, target_date = _targets(args, sav["target_amount"], sav["target_date"])
    with write(conn):
        conn.execute("UPDATE accounts SET target_amount = ?, target_date = ? WHERE id = ?",
                     (target, target_date, sav["id"]))
    msg = f"Target tabungan {sav['name']} dihapus." if target is None and target_date is None else \
        f"Tabungan {sav['name']} sekarang {_target_text(target, target_date)}."
    return success(msg, {"id": sav["id"], "name": sav["name"], "target_amount": target, "target_date": target_date})


def cmd_rename(args, conn):
    sav = _savings(conn, args.name)
    new = resolve.clean_name(args.new_name, "nama tabungan")
    _ensure_name_free(conn, new, except_id=sav["id"])
    with write(conn):
        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (new, sav["id"]))
        conn.execute("UPDATE debts SET person = ? WHERE savings_account_id = ?", (new, sav["id"]))
    return success(f"Tabungan {sav['name']} diganti nama menjadi {new}.",
                   {"id": sav["id"], "old_name": sav["name"], "name": new})


# ---------- remove ----------

def cmd_remove(args, conn):
    sav = resolve.find_account(conn, args.name)
    if sav is None or sav["type"] != "savings" or sav["archived"]:
        _savings(conn, args.name)  # melempar UNKNOWN_ACCOUNT dengan hint
    loans = debts.savings_loans_total(conn, sav["id"])
    if loans:
        raise FinError("NOT_EMPTY", f"Masih ada pinjaman dari tabungan {sav['name']} sebesar {rupiah(loans)} "
                                    f"yang belum dikembalikan.",
                       hint=f"Kembalikan dulu: debt pay --person \"{sav['name']}\" --amount all, "
                            f"atau hapus pinjamannya: debt remove --person \"{sav['name']}\" --write-off",
                       data={"loans_outstanding": loans})
    bal = balance(conn, sav["id"])
    if bal != 0 and not (args.move_to or args.write_off):
        raise FinError("NOT_EMPTY", f"Tabungan {sav['name']} masih berisi {rupiah(bal)}.",
                       hint=f"Pilih salah satu: savings remove \"{sav['name']}\" --move-to <dompet atau tabungan lain> "
                            f"(sisa dipindah; ke dompet berarti masuk ke {UNALLOCATED}), atau "
                            f"savings remove \"{sav['name']}\" --write-off (sisa dinolkan, budget tidak berubah).",
                       data={"balance": bal})
    dst = None
    if args.move_to and bal != 0:
        dst = resolve.account(conn, args.move_to, kind=None)
        if dst["id"] == sav["id"]:
            raise FinError("BAD_ARGS", "Tujuan tidak boleh tabungan yang sama.")
    ts = clock.now_ts()
    note = f"hapus tabungan {sav['name']}"
    with write(conn):
        if bal != 0:
            group = new_group(conn, "savings_remove", restore=[["accounts", sav["id"]]])
            if dst is None:
                insert_tx(conn, ts=ts, type="adjustment", amount=-bal, account_id=sav["id"], note=note, group_id=group)
            elif dst["type"] == "savings":
                src_id, dst_id = (sav["id"], dst["id"]) if bal > 0 else (dst["id"], sav["id"])
                insert_tx(conn, ts=ts, type="transfer", amount=abs(bal), account_id=src_id, to_account_id=dst_id,
                          note=note, group_id=group)
            else:
                unalloc = budgets.unallocated(conn)["id"]
                if bal > 0:
                    insert_tx(conn, ts=ts, type="withdraw", amount=bal, account_id=sav["id"], to_account_id=dst["id"],
                              budget_id=unalloc, note=note, group_id=group)
                else:
                    insert_tx(conn, ts=ts, type="deposit", amount=-bal, account_id=dst["id"], to_account_id=sav["id"],
                              budget_id=unalloc, note=note, group_id=group)
        used = conn.execute("SELECT 1 FROM transactions WHERE account_id = :a OR to_account_id = :a LIMIT 1",
                            {"a": sav["id"]}).fetchone() or conn.execute(
            "SELECT 1 FROM debts WHERE savings_account_id = ? LIMIT 1", (sav["id"],)).fetchone()
        if used:
            mode = "archived"
            conn.execute("UPDATE accounts SET archived = 1 WHERE id = ?", (sav["id"],))
        else:
            mode = "deleted"
            conn.execute("DELETE FROM aliases WHERE kind = 'account' AND target_id = ?", (sav["id"],))
            conn.execute("DELETE FROM accounts WHERE id = ?", (sav["id"],))

    if mode == "deleted":
        msg = f"Tabungan {sav['name']} dihapus permanen karena belum pernah dipakai."
    else:
        msg = f"Tabungan {sav['name']} dihapus. Riwayatnya tetap disimpan (diarsipkan)."
    if bal and dst is not None:
        msg += f" Sisa {rupiah(bal)} dipindah ke {dst['name']}. " + balance_sentence(conn, [dst["id"]])
        if dst["type"] != "savings":
            msg += " " + budgets.sentence(conn, [budgets.unallocated(conn)["id"]])
    elif bal:
        msg += f" Sisa {rupiah(bal)} dinolkan lewat penyesuaian; dompet dan budget tidak berubah."
    return success(msg, {"id": sav["id"], "name": sav["name"], "mode": mode, "balance_before": bal,
                         "moved_to": dst["name"] if dst is not None else None,
                         "written_off": bool(bal and dst is None)})


# ---------- deposit / withdraw ----------

def cmd_deposit(args, conn):
    src = resolve.account(conn, args.from_account)
    sav = _savings(conn, args.to_savings)
    amount = parse_amount(args.amount)
    bud = budgets.find(conn, args.from_budget) if args.from_budget else budgets.unallocated(conn)
    available = budgets.balances(conn)[bud["id"]]
    if amount > available:
        raise FinError("BAD_AMOUNT", f"Budget {bud['name']} tidak cukup untuk menabung {rupiah(amount)}: "
                                     f"sisanya {rupiah(available)}.",
                       hint=f"Kurangi jumlahnya, pakai --from-budget dengan budget lain, atau pindahkan dulu "
                            f"dengan budget move --to \"{bud['name']}\". Budget yang ada: "
                            + ", ".join(budgets.active_names(conn)) + ".",
                       data={"budget_balance": available})
    ts = _ts(args)
    with write(conn):
        group = new_group(conn, "savings_deposit")
        tx_id = insert_tx(conn, ts=ts, type="deposit", amount=amount, account_id=src["id"], to_account_id=sav["id"],
                          budget_id=bud["id"], note=args.note or f"menabung ke {sav['name']}", raw_text=args.raw,
                          group_id=group)
    info = _info(conn, sav)
    msg = (f"Menabung {rupiah(amount)} dari {src['name']} ke tabungan {sav['name']}{_progress_text(info)}; "
           f"budget {bud['name']} berkurang {rupiah(amount)}.{_date_note(ts)} "
           + balance_sentence(conn, [src["id"], sav["id"]]) + " " + budgets.sentence(conn, [bud["id"]]))
    return success(msg, {"id": tx_id, "group_id": group, "from": src["name"], "to": sav["name"], "amount": amount,
                         "budget": bud["name"], "balance_from": balance(conn, src["id"]),
                         "savings": info, "budget_balance": budgets.balances(conn)[bud["id"]]})


def cmd_withdraw(args, conn):
    sav = _savings(conn, args.from_savings)
    dst = resolve.account(conn, args.to_account)
    available = balance(conn, sav["id"])
    amount = _amount_or_all(args.amount, available, f"Tabungan {sav['name']}")
    _ensure_enough(sav, available, amount, "menarik")
    ts = _ts(args)
    with write(conn):
        bud = budgets.find(conn, args.to_budget, create=True) if args.to_budget else budgets.unallocated(conn)
        group = new_group(conn, "savings_withdraw")
        tx_id = insert_tx(conn, ts=ts, type="withdraw", amount=amount, account_id=sav["id"], to_account_id=dst["id"],
                          budget_id=bud["id"], note=args.note or f"tarik dari tabungan {sav['name']}",
                          raw_text=args.raw, group_id=group)
    info = _info(conn, sav)
    msg = (f"Menarik {rupiah(amount)} dari tabungan {sav['name']} ke {dst['name']}; budget {bud['name']} bertambah "
           f"{rupiah(amount)}.{_date_note(ts)} " + balance_sentence(conn, [sav["id"], dst["id"]]) + " "
           + budgets.sentence(conn, [bud["id"]]))
    return success(msg, {"id": tx_id, "group_id": group, "from": sav["name"], "to": dst["name"], "amount": amount,
                         "budget": bud["name"], "balance_to": balance(conn, dst["id"]),
                         "savings": info, "budget_balance": budgets.balances(conn)[bud["id"]]})


# ---------- spend ----------

def cmd_spend(args, conn):
    sav = _savings(conn, args.from_savings)
    items = [_parse_item(conn, raw, "expense", i, len(args.item)) for i, raw in enumerate(args.item, 1)]
    total = sum(i["amount"] for i in items)
    available = balance(conn, sav["id"])
    _ensure_enough(sav, available, total, "membayar")
    ts = _ts(args)
    debt_ids = []
    with write(conn):
        group = new_group(conn, f"savings_spend_{args.mode}")
        for item in items:
            if args.mode == "purpose":
                item["id"] = insert_tx(conn, ts=ts, type="expense", amount=item["amount"], account_id=sav["id"],
                                       category_id=item["category"]["id"], note=item["note"], raw_text=args.raw,
                                       group_id=group)
                continue
            debt_id = conn.execute(
                "INSERT INTO debts(direction, person, principal, note, savings_account_id, created_at) "
                "VALUES ('i_owe', ?, ?, ?, ?, ?)",
                (sav["name"], item["amount"], item["note"], sav["id"], clock.now_ts())).lastrowid
            add_restore(conn, group, [["debts", debt_id, 1]])  # undo ikut menghapus hutangnya
            debt_ids.append(debt_id)
            item["debt_id"] = debt_id
            item["id"] = insert_tx(conn, ts=ts, type="savings_loan", amount=item["amount"], account_id=sav["id"],
                                   category_id=item["category"]["id"], debt_id=debt_id, note=item["note"],
                                   raw_text=args.raw, group_id=group)

    details = "; ".join(f"{i['note'] or '(tanpa catatan)'} {rupiah(i['amount'])} [{_category_text(i)}]" for i in items)
    if args.mode == "purpose":
        msg = (f"Belanja dari tabungan {sav['name']} {rupiah(total)}: {details}. Dicatat sebagai pengeluaran dari "
               f"tabungan; dompet dan budget tidak berubah.")
    else:
        ids = ", ".join(f"#{d}" for d in debt_ids)
        msg = (f"Pinjam {rupiah(total)} dari tabungan {sav['name']} untuk: {details}. Dicatat sebagai hutang ke "
               f"tabungan ({ids}); dompet dan budget belum berubah. Kembalikan dengan: debt pay --person "
               f"\"{sav['name']}\" --amount <jumlah> (pengeluarannya tercatat saat dikembalikan).")
    msg += _date_note(ts) + " " + balance_sentence(conn, [sav["id"]])
    return success(msg, {"group_id": group, "mode": args.mode, "savings": _info(conn, sav), "total": total,
                         "items": [{"id": i["id"], "note": i["note"], "amount": i["amount"],
                                    "category": i["category"]["name"], "category_source": i["how"],
                                    "debt_id": i.get("debt_id")} for i in items]})
