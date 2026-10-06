"""add / transfer / adjust / edit / delete / undo"""
import json

from .. import budgets, clock, debts, recurring, resolve
from ..db import UNALLOCATED, write
from ..ledger import (TX_SELECT, balance, balance_sentence, get_tx, insert_tx, new_group, tx_dict, tx_line)
from ..output import FinError, fmt_date, fmt_ts, rupiah, signed_rupiah, success
from ..parse import parse_amount, parse_date

ITEM_HINT = 'Format --item "catatan|jumlah" atau "catatan|jumlah|kategori", contoh --item "ayam goreng|15k|makan".'


def register(sub):
    p = sub.add_parser("add", help="Catat satu atau beberapa pemasukan/pengeluaran.")
    p.add_argument("--type", required=True, choices=["income", "expense"])
    p.add_argument("--item", action="append", required=True, help="catatan|jumlah|kategori (kategori opsional)")
    p.add_argument("--account", help="Dompet (bawaan: dompet default).")
    p.add_argument("--budget", help="Khusus pengeluaran: ambil dari budget ini, bukan budget kategorinya.")
    p.add_argument("--date", help="YYYY-MM-DD, today, atau yesterday.")
    p.add_argument("--raw", help="Teks asli dari pengguna.")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("transfer", help="Pindah uang antar dompet (termasuk tarik tunai). Budget tidak berubah.")
    p.add_argument("--from", dest="from_account", required=True)
    p.add_argument("--to", dest="to_account", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--fee", help="Biaya admin, dicatat sebagai pengeluaran 'biaya admin' dari dompet asal.")
    p.add_argument("--date")
    p.add_argument("--note")
    p.add_argument("--raw")
    p.set_defaults(func=cmd_transfer)

    p = sub.add_parser("adjust", help="Samakan saldo dompet dengan kenyataan.")
    p.add_argument("--account", required=True)
    p.add_argument("--actual", required=True, help="Saldo sebenarnya sekarang (boleh 0).")
    p.add_argument("--note")
    p.set_defaults(func=cmd_adjust)

    p = sub.add_parser("edit", help="Ubah transaksi.")
    p.add_argument("id", type=int)
    p.add_argument("--amount")
    p.add_argument("--category")
    p.add_argument("--budget", help="Khusus pengeluaran: pindahkan ke budget ini.")
    p.add_argument("--account")
    p.add_argument("--to", dest="to_account", help="Dompet tujuan (khusus transfer).")
    p.add_argument("--note")
    p.add_argument("--date")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("delete", help="Hapus transaksi (soft delete).")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("undo", help="Batalkan pencatatan terakhir (transaksi atau alokasi budget).")
    p.set_defaults(func=cmd_undo)


def _ts_or_now(date_text):
    return parse_date(date_text) if date_text else clock.now_ts()


def _date_note(ts):
    if ts[:10] != clock.today().isoformat():
        return f" Tanggal: {fmt_date(ts)}."
    return ""


def _with_item_prefix(err, index, total):
    if total > 1:
        err.message = f"Item ke-{index}: {err.message}"
    return err


# ---------- add ----------

def _parse_item(conn, raw, kind, index, total):
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) not in (2, 3):
        raise _with_item_prefix(FinError("BAD_ARGS", f"Item '{raw}' tidak sesuai format.", hint=ITEM_HINT),
                                index, total)
    note, amount_text = parts[0], parts[1]
    cat_text = parts[2] if len(parts) == 3 and parts[2] else None
    try:
        amount = parse_amount(amount_text)
        if cat_text:
            cat, how = resolve.category(conn, cat_text, kind), "given"
            keyword = None
        else:
            cat, keyword = resolve.guess_category(conn, note, kind)
            how = "keyword" if keyword else "fallback"
    except FinError as e:
        raise _with_item_prefix(e, index, total)
    return {"note": note or None, "amount": amount, "category": cat, "how": how, "keyword": keyword}


def _category_text(item):
    name = item["category"]["name"]
    if item["how"] == "keyword":
        return f"{name}, ditebak dari kata '{item['keyword']}'"
    if item["how"] == "fallback":
        return f"{name}, tidak ada kata kunci yang cocok"
    return name


def cmd_add(args, conn):
    kind = args.type
    if args.budget and kind != "expense":
        raise FinError("BAD_ARGS", "--budget hanya untuk pengeluaran.",
                       hint=f"Pemasukan selalu masuk ke {UNALLOCATED}; bagi lewat budget alloc.")
    acc, used_default = resolve.account_or_default(conn, args.account)
    ts = _ts_or_now(args.date)
    items = [_parse_item(conn, raw, kind, i, len(args.item)) for i, raw in enumerate(args.item, 1)]
    forced = budgets.find(conn, args.budget) if args.budget else None

    with write(conn):
        group = new_group(conn, "add")
        for item in items:
            if kind == "income":
                bud = budgets.unallocated(conn)
            else:
                bud = forced or budgets.for_expense(conn, item["category"]["id"])
            item["budget"] = bud
            item["id"] = insert_tx(conn, ts=ts, type=kind, amount=item["amount"], account_id=acc["id"],
                                   category_id=item["category"]["id"], budget_id=bud["id"], note=item["note"],
                                   raw_text=args.raw, group_id=group)

    word = "pengeluaran" if kind == "expense" else "pemasukan"
    prep = "dari" if kind == "expense" else "ke"
    acc_text = acc["name"] + (" (dompet default)" if used_default else "")
    total = sum(i["amount"] for i in items)
    if len(items) == 1:
        it = items[0]
        msg = (f"Tercatat {word} {it['note'] or '(tanpa catatan)'} {rupiah(it['amount'])} "
               f"(kategori {_category_text(it)}) {prep} {acc_text}.")
    else:
        details = "; ".join(f"{i['note'] or '(tanpa catatan)'} {rupiah(i['amount'])} [{_category_text(i)}]"
                            for i in items)
        msg = f"Tercatat {len(items)} {word} ({rupiah(total)}) {prep} {acc_text}: {details}."
    if forced:
        msg += f" Diambil dari budget {forced['name']}."
    msg += _date_note(ts) + " " + balance_sentence(conn, [acc["id"]])
    msg += " " + budgets.sentence(conn, [i["budget"]["id"] for i in items])

    bals = budgets.balances(conn)
    return success(msg, {
        "group_id": group, "type": kind, "account": acc["name"], "used_default_account": used_default,
        "ts": ts, "total": total, "balance_after": balance(conn, acc["id"]),
        "items": [{"id": i["id"], "note": i["note"], "amount": i["amount"], "category": i["category"]["name"],
                   "category_source": i["how"], "budget": i["budget"]["name"],
                   "budget_balance": bals[i["budget"]["id"]]} for i in items],
    })


# ---------- transfer ----------

def cmd_transfer(args, conn):
    src = resolve.account(conn, args.from_account)
    dst = resolve.account(conn, args.to_account)
    if src["id"] == dst["id"]:
        raise FinError("BAD_ARGS", f"Dompet asal dan tujuan sama ({src['name']}).",
                       hint="Transfer harus ke dompet lain.")
    amount = parse_amount(args.amount)
    fee = parse_amount(args.fee, field="biaya admin") if args.fee else 0
    fee_cat = resolve.category_by_name(conn, "biaya admin", "expense") if fee else None
    ts = _ts_or_now(args.date)

    fee_id = fee_budget = None
    with write(conn):
        group = new_group(conn, "transfer")
        tx_id = insert_tx(conn, ts=ts, type="transfer", amount=amount, account_id=src["id"],
                          to_account_id=dst["id"], note=args.note, raw_text=args.raw, group_id=group)
        if fee:
            fee_budget = budgets.for_expense(conn, fee_cat["id"])
            fee_id = insert_tx(conn, ts=ts, type="expense", amount=fee, account_id=src["id"],
                               category_id=fee_cat["id"], budget_id=fee_budget["id"],
                               note=f"biaya admin transfer {src['name']} ke {dst['name']}",
                               raw_text=args.raw, group_id=group)

    if src["type"] == "bank" and dst["type"] == "cash":
        kind, verb = "cash_withdrawal", f"Tarik tunai {rupiah(amount)} dari {src['name']} ke {dst['name']}."
    else:
        kind, verb = "transfer", f"Transfer {rupiah(amount)} dari {src['name']} ke {dst['name']}."
    msg = verb
    if fee:
        msg += f" Biaya admin {rupiah(fee)} dicatat sebagai pengeluaran dari {src['name']}."
    msg += _date_note(ts) + " " + balance_sentence(conn, [src["id"], dst["id"]])
    if fee:
        msg += " " + budgets.sentence(conn, [fee_budget["id"]])
    return success(msg, {
        "group_id": group, "kind": kind, "transfer_id": tx_id, "fee_id": fee_id, "amount": amount, "fee": fee,
        "from": src["name"], "to": dst["name"], "ts": ts,
        "balance_from": balance(conn, src["id"]), "balance_to": balance(conn, dst["id"]),
    })


# ---------- adjust ----------

def cmd_adjust(args, conn):
    acc = resolve.account(conn, args.account)
    actual = parse_amount(args.actual, allow_zero=True, allow_negative=True, field="saldo sebenarnya")
    current = balance(conn, acc["id"])
    diff = actual - current
    if diff == 0:
        return success(f"Saldo {acc['name']} sudah {rupiah(actual)}, tidak ada perubahan.",
                       {"account": acc["name"], "before": current, "after": actual, "difference": 0, "id": None})
    unalloc = budgets.unallocated(conn)
    with write(conn):
        group = new_group(conn, "adjust")
        tx_id = insert_tx(conn, ts=clock.now_ts(), type="adjustment", amount=diff, account_id=acc["id"],
                          budget_id=unalloc["id"], note=args.note or "penyesuaian saldo", group_id=group)
    msg = (f"Saldo {acc['name']} disesuaikan dari {rupiah(current)} menjadi {rupiah(actual)} "
           f"(selisih {signed_rupiah(diff)}). Selisih ini {'masuk ke' if diff > 0 else 'keluar dari'} "
           f"budget {UNALLOCATED} dan tidak dihitung sebagai pemasukan atau pengeluaran. "
           + budgets.sentence(conn, [unalloc["id"]]))
    if actual < 0:
        msg += f" Peringatan: saldo {acc['name']} minus."
    return success(msg, {"account": acc["name"], "before": current, "after": actual, "difference": diff,
                         "id": tx_id, "group_id": group,
                         "unallocated_balance": budgets.balances(conn)[unalloc["id"]]})


# ---------- edit ----------

def _not_found(tx_id, conn):
    row = get_tx(conn, tx_id, include_deleted=True)
    if row is not None:
        return FinError("NOT_FOUND", f"Transaksi #{tx_id} sudah dihapus.",
                        hint="Lihat transaksi aktif dengan: list --period all")
    return FinError("NOT_FOUND", f"Transaksi #{tx_id} tidak ada.", hint="Cek ID lewat perintah: list --period all")


def cmd_edit(args, conn):
    row = get_tx(conn, args.id)
    if row is None:
        raise _not_found(args.id, conn)
    if not any(v is not None for v in (args.amount, args.category, args.budget, args.account, args.to_account,
                                       args.note, args.date)):
        raise FinError("BAD_ARGS", "Tidak ada yang diubah.",
                       hint="Isi minimal satu: --amount, --category, --budget, --account, --to, --note, --date.")
    t = row["type"]
    updates, changes = {}, []

    if args.amount is not None:
        if t in ("debt_in", "debt_out"):
            raise FinError("BAD_ARGS", "Nominal transaksi hutang tidak bisa diubah lewat edit.",
                           hint=f"Hapus transaksinya (delete {row['id']}) lalu catat ulang lewat perintah debt.")
        amount = parse_amount(args.amount, allow_negative=(t == "adjustment"))
        if amount != row["amount"]:
            updates["amount"] = amount
            changes.append(("jumlah", rupiah(row["amount"]), rupiah(amount)))
    new_budget = None
    if args.category is not None:
        if t not in ("income", "expense"):
            raise FinError("BAD_ARGS", f"Transaksi #{row['id']} bertipe {t} tidak punya kategori.")
        cat = resolve.category(conn, args.category, t)
        if cat["id"] != row["category_id"]:
            updates["category_id"] = cat["id"]
            changes.append(("kategori", row["category"], cat["name"]))
            if t == "expense":
                new_budget = budgets.for_expense(conn, cat["id"])
    if args.budget is not None:
        if t != "expense":
            raise FinError("BAD_ARGS", "--budget hanya untuk pengeluaran.")
        new_budget = budgets.find(conn, args.budget)
    if new_budget is not None and new_budget["id"] != row["budget_id"]:
        updates["budget_id"] = new_budget["id"]
        changes.append(("budget", row["budget"], new_budget["name"]))
    new_from, new_to = row["account_id"], row["to_account_id"]
    if args.account is not None:
        acc = resolve.account(conn, args.account)
        if acc["id"] != row["account_id"]:
            new_from = updates["account_id"] = acc["id"]
            changes.append(("dompet" if t != "transfer" else "dompet asal", row["account"], acc["name"]))
    if args.to_account is not None:
        if t != "transfer":
            raise FinError("BAD_ARGS", "--to hanya untuk transaksi transfer.", hint="Untuk ganti dompet pakai --account.")
        acc = resolve.account(conn, args.to_account)
        if acc["id"] != row["to_account_id"]:
            new_to = updates["to_account_id"] = acc["id"]
            changes.append(("dompet tujuan", row["to_account"], acc["name"]))
    if t == "transfer" and new_from == new_to:
        raise FinError("BAD_ARGS", "Dompet asal dan tujuan transfer tidak boleh sama.")
    if args.note is not None:
        note = args.note.strip() or None
        if note != row["note"]:
            updates["note"] = note
            changes.append(("catatan", row["note"] or "(kosong)", note or "(kosong)"))
    if args.date is not None:
        ts = parse_date(args.date)
        if ts != row["ts"]:
            updates["ts"] = ts
            changes.append(("waktu", fmt_ts(row["ts"]), fmt_ts(ts)))

    if not updates:
        return success(f"Transaksi #{row['id']} tidak berubah karena nilainya sama.",
                       {"id": row["id"], "before": tx_dict(row), "after": tx_dict(row), "changes": []})

    with write(conn):
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE transactions SET {sets} WHERE id = ?", (*updates.values(), row["id"]))
        if row["debt_id"]:
            debts.recompute_status(conn, row["debt_id"])
    after = get_tx(conn, row["id"])
    affected = [row["account_id"], after["account_id"]]
    if t == "transfer":
        affected += [row["to_account_id"], after["to_account_id"]]
    msg = (f"Transaksi #{row['id']} diubah: " + "; ".join(f"{k} {a} → {b}" for k, a, b in changes) + ". "
           + balance_sentence(conn, affected))
    if row["budget_id"]:
        msg += " " + budgets.sentence(conn, [row["budget_id"], after["budget_id"]])
    return success(msg, {"id": row["id"], "before": tx_dict(row), "after": tx_dict(after),
                         "changes": [{"field": k, "before": a, "after": b} for k, a, b in changes]})


# ---------- delete / undo ----------

def _accounts_of(rows):
    ids = []
    for r in rows:
        ids.append(r["account_id"])
        if r["to_account_id"]:
            ids.append(r["to_account_id"])
    return ids


def _soft_delete(conn, rows, moves=()):
    now = clock.now_ts()
    for r in rows:
        conn.execute("UPDATE transactions SET deleted_at = ? WHERE id = ?", (now, r["id"]))
    for m in moves:
        conn.execute("UPDATE budget_moves SET deleted_at = ? WHERE id = ?", (now, m["id"]))
    for debt_id in {r["debt_id"] for r in rows if r["debt_id"]}:
        debts.recompute_status(conn, debt_id)
    for rec_id in recurring.ids_for_transactions(conn, [r["id"] for r in rows]):
        recurring.recompute_last_paid(conn, rec_id)


def cmd_delete(args, conn):
    row = get_tx(conn, args.id)
    if row is None:
        raise _not_found(args.id, conn)
    with write(conn):
        _soft_delete(conn, [row])
    msg = f"Transaksi dihapus: {tx_line(row)}. " + balance_sentence(conn, _accounts_of([row]))
    if row["budget_id"]:
        msg += " " + budgets.sentence(conn, [row["budget_id"]])
    siblings = conn.execute(TX_SELECT + " WHERE t.group_id = ? AND t.deleted_at IS NULL ORDER BY t.id",
                            (row["group_id"],)).fetchall()
    if siblings:
        ids = ", ".join(f"#{s['id']}" for s in siblings)
        msg += f" Catatan: transaksi lain dari pencatatan yang sama masih ada ({ids})."
    return success(msg, {"id": row["id"], "deleted": tx_dict(get_tx(conn, row["id"], include_deleted=True)),
                         "remaining_in_group": [s["id"] for s in siblings]})


MOVE_SELECT = ("SELECT m.*, f.name AS from_budget, t.name AS to_budget FROM budget_moves m "
               "JOIN budgets f ON f.id = m.from_budget_id JOIN budgets t ON t.id = m.to_budget_id")


def move_line(m):
    line = f"pindah budget {rupiah(m['amount'])} {m['from_budget']} → {m['to_budget']}"
    if m["note"]:
        line += f" ({m['note']})"
    return line


def cmd_undo(args, conn):
    group = conn.execute(
        "SELECT * FROM op_groups g WHERE g.undoable = 1 AND ("
        " EXISTS (SELECT 1 FROM transactions t WHERE t.group_id = g.group_id AND t.deleted_at IS NULL) OR"
        " EXISTS (SELECT 1 FROM budget_moves m WHERE m.group_id = g.group_id AND m.deleted_at IS NULL))"
        " ORDER BY g.id DESC LIMIT 1").fetchone()
    if group is None:
        raise FinError("NOTHING_TO_UNDO", "Tidak ada transaksi atau alokasi budget yang bisa dibatalkan.")
    gid = group["group_id"]
    rows = conn.execute(TX_SELECT + " WHERE t.group_id = ? AND t.deleted_at IS NULL ORDER BY t.id",
                        (gid,)).fetchall()
    moves = conn.execute(MOVE_SELECT + " WHERE m.group_id = ? AND m.deleted_at IS NULL ORDER BY m.id",
                         (gid,)).fetchall()
    restore = json.loads(group["restore"]) if group["restore"] else []
    restored, removed = [], []
    with write(conn):
        _soft_delete(conn, rows, moves)
        for entry in restore:
            # [tabel, id] = aktifkan lagi; [tabel, id, 1] = arsipkan (mis. hutang yang dibuat oleh group ini)
            table, ref_id, archived = (entry + [0])[:3]
            assert table in ("accounts", "budgets", "categories", "debts")
            conn.execute(f"UPDATE {table} SET archived = ? WHERE id = ?", (archived, ref_id))
            ref = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (ref_id,)).fetchone()
            name = debts.title(ref) if table == "debts" else ref["name"]
            (removed if archived else restored).append({"table": table, "id": ref_id, "name": name})
            if table == "accounts" and not conn.execute(
                    "SELECT 1 FROM accounts WHERE is_default = 1 AND archived = 0").fetchone():
                conn.execute("UPDATE accounts SET is_default = 1 WHERE id = ?", (ref_id,))

    lines = [tx_line(r) for r in rows] + [move_line(m) for m in moves]
    if len(lines) == 1:
        msg = f"Dibatalkan: {lines[0]}."
    else:
        msg = f"Dibatalkan {len(lines)} catatan dari pencatatan terakhir:\n" + "\n".join(f"- {x}" for x in lines) + "\n"
    label = {"accounts": "dompet ", "budgets": "budget ", "categories": "kategori ", "debts": ""}
    if restored:
        msg = msg.rstrip("\n") + " Diaktifkan kembali: " + \
            ", ".join(f"{label[r['table']]}{r['name']}" for r in restored) + "."
    if removed:
        msg = msg.rstrip("\n") + " Ikut dihapus: " + \
            ", ".join(f"{label[r['table']]}{r['name']} (#{r['id']})" for r in removed) + "."
    tail = []
    if rows:
        tail.append(balance_sentence(conn, _accounts_of(rows)))
    bud_ids = [r["budget_id"] for r in rows if r["budget_id"]]
    bud_ids += [x for m in moves for x in (m["from_budget_id"], m["to_budget_id"])]
    if bud_ids:
        tail.append(budgets.sentence(conn, bud_ids))
    msg = msg.rstrip("\n") + " " + " ".join(tail)
    return success(msg, {"group_id": gid, "action": group["action"], "undone": [r["id"] for r in rows],
                         "undone_moves": [m["id"] for m in moves], "restored": restored, "removed": removed,
                         "transactions": [tx_dict(r) for r in rows]})
