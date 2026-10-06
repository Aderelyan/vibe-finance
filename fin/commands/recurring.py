"""recurring add / list / pay / set / rename / remove (tagihan rutin)"""
import re

from .. import budgets, clock, resolve
from ..db import write
from ..ledger import balance, balance_sentence, insert_tx, new_group
from ..output import MONTHS, FinError, fmt_date, rupiah, success
from ..parse import parse_amount, parse_date
from ..recurring import is_used, month_status, paid_months, recompute_last_paid


def register(sub):
    p = sub.add_parser("recurring", help="Tagihan rutin bulanan.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Tambah tagihan rutin (atau aktifkan lagi yang pernah dihapus).")
    a.add_argument("name")
    a.add_argument("--amount", required=True)
    a.add_argument("--day", required=True, type=int, help="Tanggal jatuh tempo tiap bulan, 1-31.")
    a.add_argument("--category", help="Kategori pengeluaran (bawaan: ditebak dari nama, atau 'tagihan').")
    a.add_argument("--account", help="Dompet pembayar (bawaan: dompet default saat dibayar).")
    a.set_defaults(func=cmd_add)

    a = s.add_parser("list", help="Daftar tagihan rutin dan status bulan ini.")
    a.add_argument("--all", action="store_true", help="Sertakan yang sudah dihapus (diarsipkan).")
    a.set_defaults(func=cmd_list)

    a = s.add_parser("pay", help="Catat pembayaran tagihan sebagai pengeluaran.")
    a.add_argument("name")
    a.add_argument("--amount", help="Jumlah jika berbeda dari biasanya.")
    a.add_argument("--account")
    a.add_argument("--budget", help="Ambil dari budget ini, bukan budget kategorinya.")
    a.add_argument("--date", help="Tanggal bayar: YYYY-MM-DD, today, atau yesterday.")
    a.add_argument("--month", help="Bulan tagihan yang dibayar, YYYY-MM (bawaan: bulan tanggal bayar).")
    a.add_argument("--raw", help="Teks asli dari pengguna.")
    a.set_defaults(func=cmd_pay)

    a = s.add_parser("set", help="Ubah nominal, tanggal, kategori, atau dompet tagihan.")
    a.add_argument("name")
    a.add_argument("--amount")
    a.add_argument("--day", type=int)
    a.add_argument("--category")
    a.add_argument("--account")
    a.set_defaults(func=cmd_set)

    a = s.add_parser("rename", help="Ganti nama tagihan.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.set_defaults(func=cmd_rename)

    a = s.add_parser("remove", help="Hapus tagihan rutin.")
    a.add_argument("name")
    a.set_defaults(func=cmd_remove)


SELECT = ("SELECT r.*, c.name AS category, c.archived AS category_archived, a.name AS account, "
          "a.archived AS account_archived FROM recurring r LEFT JOIN categories c ON c.id = r.category_id "
          "LEFT JOIN accounts a ON a.id = r.account_id")


def _get(conn, rec_id):
    return conn.execute(SELECT + " WHERE r.id = ?", (rec_id,)).fetchone()


def _find(conn, name, include_archived=False):
    key = resolve.norm(name)
    rows = [r for r in conn.execute(SELECT + " ORDER BY r.archived, r.id") if resolve.norm(r["name"]) == key]
    for r in rows:
        if not r["archived"] or include_archived:
            return r
    if rows:
        raise FinError("NOT_FOUND", f"Tagihan '{rows[0]['name']}' sudah dihapus.",
                       hint=f"Aktifkan lagi dengan: recurring add \"{rows[0]['name']}\" --amount <jumlah> --day <tanggal>")
    names = [r["name"] for r in conn.execute("SELECT name FROM recurring WHERE archived = 0 ORDER BY id")]
    raise FinError("NOT_FOUND", f"Tagihan rutin '{name}' tidak ada.",
                   hint=("Tagihan yang ada: " + ", ".join(names)) if names else
                   "Belum ada tagihan rutin. Tambah dengan: recurring add kos --amount 500k --day 5")


def _check_day(day):
    if day is not None and not 1 <= day <= 31:
        raise FinError("BAD_ARGS", f"Tanggal {day} tidak sah.", hint="--day harus 1 sampai 31. "
                       "Tanggal 29-31 di bulan yang lebih pendek dianggap akhir bulan.")
    return day


def _month(text, ts):
    if not text:
        return ts[:7]
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", text.strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise FinError("BAD_DATE", f"Bulan '{text}' tidak sah.", hint="Pakai format YYYY-MM, contoh 2026-10.")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"


def month_label(month):
    return f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}"


def _default_category(conn, name):
    """Tebak dari nama tagihan; jika tidak ada kata kunci yang cocok pakai 'tagihan' (atau 'lainnya')."""
    cat, keyword = resolve.guess_category(conn, name, "expense")
    if keyword:
        return cat, f"ditebak dari kata '{keyword}'"
    row = conn.execute("SELECT * FROM categories WHERE name = 'tagihan' AND kind = 'expense' AND archived = 0").fetchone()
    return (row, "bawaan") if row else (cat, "bawaan")


def _info(conn, row):
    st = month_status(conn, row)
    return {"id": row["id"], "name": row["name"], "amount": row["amount"], "day": row["day_of_month"],
            "category": row["category"], "account": row["account"], "last_paid_month": row["last_paid_month"],
            "archived": bool(row["archived"]), "this_month": st}


def _status_text(st):
    if st["paid"]:
        return f"{month_label(st['month'])} sudah dibayar"
    days = st["days_until_due"]
    when = f"lewat {-days} hari" if days < 0 else ("hari ini" if days == 0 else f"{days} hari lagi")
    return f"belum dibayar, jatuh tempo {fmt_date(st['due_date'])} ({when})"


def _line(info):
    where = info["category"] or "tanpa kategori"
    where += f", dari {info['account']}" if info["account"] else ", dari dompet default"
    text = f"- {info['name']} {rupiah(info['amount'])} tiap tgl {info['day']} [{where}]: "
    if info["archived"]:
        return text + "[dihapus]"
    return text + _status_text(info["this_month"])


# ---------- add ----------

def cmd_add(args, conn):
    name = resolve.clean_name(args.name, "nama tagihan")
    amount = parse_amount(args.amount)
    day = _check_day(args.day)
    if args.category:
        cat, how = resolve.category(conn, args.category, "expense"), None
    else:
        cat, how = _default_category(conn, name)
    acc = resolve.account(conn, args.account) if args.account else None
    existing = [r for r in conn.execute("SELECT * FROM recurring") if resolve.norm(r["name"]) == resolve.norm(name)]
    if existing and not existing[0]["archived"]:
        raise FinError("BAD_ARGS", f"Tagihan '{existing[0]['name']}' sudah ada.",
                       hint=f"Untuk mengubahnya pakai: recurring set \"{existing[0]['name']}\" --amount ... --day ...")
    with write(conn):
        if existing:
            rec_id = existing[0]["id"]
            conn.execute("UPDATE recurring SET amount = ?, day_of_month = ?, category_id = ?, account_id = ?, "
                         "archived = 0 WHERE id = ?", (amount, day, cat["id"], acc["id"] if acc else None, rec_id))
        else:
            rec_id = conn.execute("INSERT INTO recurring(name, amount, category_id, account_id, day_of_month, "
                                  "created_at) VALUES (?,?,?,?,?,?)",
                                  (name, amount, cat["id"], acc["id"] if acc else None, day,
                                   clock.now_ts())).lastrowid
    info = _info(conn, _get(conn, rec_id))
    verb = "diaktifkan kembali" if existing else "ditambahkan"
    cat_text = cat["name"] + (f", {how}" if how else "")
    msg = (f"Tagihan rutin {info['name']} {verb}: {rupiah(amount)} tiap tanggal {day} "
           f"(kategori {cat_text}), dibayar dari {acc['name'] if acc else 'dompet default'}. "
           f"Bulan ini: {_status_text(info['this_month'])}.")
    if day > 28:
        msg += f" Di bulan yang tidak punya tanggal {day}, jatuh temponya akhir bulan."
    return success(msg, {"recurring": info, "reactivated": bool(existing)})


# ---------- list ----------

def cmd_list(args, conn):
    rows = conn.execute(SELECT + ("" if args.all else " WHERE r.archived = 0") + " ORDER BY r.day_of_month, r.id")
    items = [_info(conn, r) for r in rows]
    active = [i for i in items if not i["archived"]]
    unpaid = [i for i in active if not i["this_month"]["paid"]]
    data = {"recurring": items, "monthly_total": sum(i["amount"] for i in active),
            "unpaid_count": len(unpaid), "unpaid_total": sum(i["amount"] for i in unpaid),
            "month": clock.today().strftime("%Y-%m")}
    if not items:
        return success("Belum ada tagihan rutin. Tambah dengan: recurring add kos --amount 500k --day 5", data)
    msg = "Tagihan rutin:\n" + "\n".join(_line(i) for i in items)
    msg += f"\nTotal per bulan: {rupiah(data['monthly_total'])}."
    month = month_label(data["month"])
    if unpaid:
        msg += f" Belum dibayar {month}: {len(unpaid)} tagihan, {rupiah(data['unpaid_total'])}."
    elif active:
        msg += f" Semua tagihan {month} sudah dibayar."
    return success(msg, data)


# ---------- pay ----------

def _pay_account(conn, rec, account_arg):
    if account_arg:
        return resolve.account(conn, account_arg), False
    if rec["account_id"] is None:
        return resolve.default_account(conn), True
    if rec["account_archived"]:
        raise FinError("UNKNOWN_ACCOUNT", f"Dompet {rec['account']} untuk tagihan {rec['name']} sudah dihapus.",
                       hint=f"Sebutkan dompet dengan --account, atau ubah: recurring set \"{rec['name']}\" --account <dompet>")
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (rec["account_id"],)).fetchone(), False


def _pay_category(conn, rec):
    if rec["category_id"] is None:
        return _default_category(conn, rec["name"])[0]
    if rec["category_archived"]:
        raise FinError("UNKNOWN_CATEGORY", f"Kategori {rec['category']} untuk tagihan {rec['name']} sudah dihapus.",
                       hint=f"Ubah dulu: recurring set \"{rec['name']}\" --category <kategori>")
    return conn.execute("SELECT * FROM categories WHERE id = ?", (rec["category_id"],)).fetchone()


def cmd_pay(args, conn):
    rec = _find(conn, args.name)
    amount = parse_amount(args.amount) if args.amount else rec["amount"]
    acc, used_default = _pay_account(conn, rec, args.account)
    cat = _pay_category(conn, rec)
    ts = parse_date(args.date) if args.date else clock.now_ts()
    month = _month(args.month, ts)
    if month in paid_months(conn, rec["id"]):
        raise FinError("BAD_ARGS", f"Tagihan {rec['name']} untuk {month_label(month)} sudah dibayar.",
                       hint="Untuk bulan lain pakai --month YYYY-MM. Jika memang bayar dua kali, catat lewat add.")
    forced = budgets.find(conn, args.budget) if args.budget else None

    with write(conn):
        bud = forced or budgets.for_expense(conn, cat["id"])
        group = new_group(conn, "recurring_pay")
        tx_id = insert_tx(conn, ts=ts, type="expense", amount=amount, account_id=acc["id"], category_id=cat["id"],
                          budget_id=bud["id"], note=f"{rec['name']} {month_label(month)}", raw_text=args.raw,
                          group_id=group)
        conn.execute("INSERT INTO recurring_payments(recurring_id, tx_id, month) VALUES (?,?,?)",
                     (rec["id"], tx_id, month))
        recompute_last_paid(conn, rec["id"])

    acc_text = acc["name"] + (" (dompet default)" if used_default else "")
    msg = f"Tagihan {rec['name']} {month_label(month)} dibayar {rupiah(amount)} dari {acc_text}, kategori {cat['name']}."
    if amount != rec["amount"]:
        msg += f" Biasanya {rupiah(rec['amount'])}."
    if forced:
        msg += f" Diambil dari budget {forced['name']}."
    if ts[:10] != clock.today().isoformat():
        msg += f" Tanggal: {fmt_date(ts)}."
    msg += " " + balance_sentence(conn, [acc["id"]]) + " " + budgets.sentence(conn, [bud["id"]])
    return success(msg, {"recurring": _info(conn, _get(conn, rec["id"])), "transaction_id": tx_id,
                         "group_id": group, "month": month, "amount": amount, "account": acc["name"],
                         "used_default_account": used_default, "category": cat["name"], "budget": bud["name"],
                         "balance_after": balance(conn, acc["id"]),
                         "budget_balance": budgets.balances(conn)[bud["id"]]})


# ---------- set / rename / remove ----------

def cmd_set(args, conn):
    rec = _find(conn, args.name)
    if all(v is None for v in (args.amount, args.day, args.category, args.account)):
        raise FinError("BAD_ARGS", "Tidak ada yang diubah.", hint="Isi minimal satu: --amount, --day, --category, --account.")
    updates, changes = {}, []
    if args.amount is not None:
        updates["amount"] = parse_amount(args.amount)
        changes.append(f"nominal {rupiah(rec['amount'])} → {rupiah(updates['amount'])}")
    if args.day is not None:
        updates["day_of_month"] = _check_day(args.day)
        changes.append(f"tanggal {rec['day_of_month']} → {args.day}")
    if args.category is not None:
        cat = resolve.category(conn, args.category, "expense")
        updates["category_id"] = cat["id"]
        changes.append(f"kategori {rec['category'] or '-'} → {cat['name']}")
    if args.account is not None:
        acc = resolve.account(conn, args.account)
        updates["account_id"] = acc["id"]
        changes.append(f"dompet {rec['account'] or 'default'} → {acc['name']}")
    with write(conn):
        conn.execute(f"UPDATE recurring SET {', '.join(f'{k} = ?' for k in updates)} WHERE id = ?",
                     (*updates.values(), rec["id"]))
    info = _info(conn, _get(conn, rec["id"]))
    return success(f"Tagihan {rec['name']} diubah: {'; '.join(changes)}.", {"recurring": info})


def cmd_rename(args, conn):
    rec = _find(conn, args.name)
    new = resolve.clean_name(args.new_name, "nama tagihan")
    for r in conn.execute("SELECT * FROM recurring WHERE id != ?", (rec["id"],)):
        if resolve.norm(r["name"]) == resolve.norm(new):
            raise FinError("BAD_ARGS", f"Tagihan bernama '{r['name']}' sudah ada"
                                       + (" (sudah dihapus)." if r["archived"] else "."),
                           hint="Pakai nama lain.")
    with write(conn):
        conn.execute("UPDATE recurring SET name = ? WHERE id = ?", (new, rec["id"]))
    return success(f"Tagihan {rec['name']} diganti nama menjadi {new}.",
                   {"id": rec["id"], "old_name": rec["name"], "name": new})


def cmd_remove(args, conn):
    rec = _find(conn, args.name)
    with write(conn):
        if is_used(conn, rec["id"]):
            mode = "archived"
            conn.execute("UPDATE recurring SET archived = 1 WHERE id = ?", (rec["id"],))
        else:
            mode = "deleted"
            conn.execute("DELETE FROM recurring WHERE id = ?", (rec["id"],))
    if mode == "deleted":
        msg = f"Tagihan rutin {rec['name']} dihapus permanen karena belum pernah dibayar."
    else:
        msg = f"Tagihan rutin {rec['name']} dihapus. Riwayat pembayarannya tetap disimpan (diarsipkan)."
    return success(msg, {"id": rec["id"], "name": rec["name"], "mode": mode})
