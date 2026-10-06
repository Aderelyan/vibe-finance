"""context: semua nama yang sah dan saldo saat ini, untuk pemanggil (mis. bot) sebelum menyusun perintah."""
from .. import budgets, clock, debts
from ..ledger import ACCOUNT_TYPE_LABEL, balances
from ..output import fmt_date, rupiah, success
from ..recurring import month_status

DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def register(sub):
    p = sub.add_parser("context", help="Dompet, kategori, budget, tabungan, alias, dan tanggal hari ini.")
    p.set_defaults(func=cmd_context)


def cmd_context(args, conn):
    today = clock.today()
    bals = balances(conn)
    accounts = [{"name": r["name"], "type": r["type"], "balance": bals[r["id"]], "is_default": bool(r["is_default"])}
                for r in conn.execute("SELECT * FROM accounts WHERE archived = 0 ORDER BY id")]
    categories = {kind: [r["name"] for r in conn.execute(
        "SELECT name FROM categories WHERE kind = ? AND archived = 0 ORDER BY id", (kind,))]
        for kind in ("expense", "income")}
    bud_bals = budgets.balances(conn)
    rows = conn.execute("SELECT * FROM budgets WHERE archived = 0 ORDER BY CASE kind WHEN 'unallocated' THEN 0 "
                        "WHEN 'category' THEN 1 ELSE 2 END, id").fetchall()
    budget_items = [{"name": r["name"], "kind": r["kind"], "balance": bud_bals[r["id"]]}
                    for r in rows if r["kind"] != "savings"]
    savings = [{"name": r["name"], "balance": bud_bals[r["id"]], "target_amount": r["target_amount"],
                "target_date": r["target_date"]} for r in rows if r["kind"] == "savings"]
    aliases, keywords = [], {"expense": {}, "income": {}}
    for r in conn.execute("SELECT * FROM aliases ORDER BY kind, alias"):
        table = "accounts" if r["kind"] == "account" else "categories"
        target = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (r["target_id"],)).fetchone()
        if target is None or target["archived"]:
            continue
        if r["kind"] == "keyword":
            keywords[target["kind"]].setdefault(target["name"], []).append(r["alias"])
            continue
        item = {"kind": r["kind"], "alias": r["alias"], "target": target["name"]}
        if table == "categories":
            item["target_kind"] = target["kind"]
        aliases.append(item)
    open_debts = [{"id": d["id"], "direction": d["direction"], "person": d["person"],
                   "remaining": debts.remaining(conn, d), "due_date": d["due_date"]}
                  for d in conn.execute("SELECT * FROM debts WHERE status = 'open' AND archived = 0 ORDER BY id")]
    recurring = []
    for r in conn.execute("SELECT * FROM recurring WHERE archived = 0 ORDER BY day_of_month, id"):
        st = month_status(conn, r)
        recurring.append({"name": r["name"], "amount": r["amount"], "day": r["day_of_month"],
                          "paid_this_month": st["paid"]})
    default = next((a["name"] for a in accounts if a["is_default"]), None)

    data = {"today": today.isoformat(), "weekday": DAYS[today.weekday()], "now": clock.now_ts(),
            "accounts": accounts, "default_account": default, "categories": categories,
            "budgets": budget_items, "savings": savings, "aliases": aliases, "keywords": keywords,
            "open_debts": open_debts, "recurring": recurring}

    lines = [f"Hari ini {DAYS[today.weekday()]}, {fmt_date(today)}."]
    if accounts:
        lines.append("Dompet: " + ", ".join(
            f"{a['name']} ({ACCOUNT_TYPE_LABEL[a['type']]}{', default' if a['is_default'] else ''}) "
            f"{rupiah(a['balance'])}" for a in accounts) + ".")
    else:
        lines.append("Belum ada dompet.")
    lines.append("Kategori pengeluaran: " + ", ".join(categories["expense"]) + ".")
    lines.append("Kategori pemasukan: " + ", ".join(categories["income"]) + ".")
    lines.append("Budget: " + ", ".join(f"{b['name']} {rupiah(b['balance'])}" for b in budget_items) + ".")
    if savings:
        lines.append("Tabungan: " + ", ".join(f"{s['name']} {rupiah(s['balance'])}" for s in savings) + ".")
    if aliases:
        lines.append("Alias: " + ", ".join(f"{a['alias']} = {a['target']}" for a in aliases) + ".")
    n_kw = sum(len(words) for kind in keywords.values() for words in kind.values())
    lines.append(f"Kata kunci tebak kategori: {n_kw} (lihat data.keywords).")
    if open_debts:
        lines.append("Hutang/piutang terbuka: " + "; ".join(
            f"#{d['id']} {'hutang ke' if d['direction'] == 'i_owe' else 'piutang dari'} {d['person']} "
            f"{rupiah(d['remaining'])}" for d in open_debts) + ".")
    if recurring:
        lines.append("Tagihan rutin: " + ", ".join(
            f"{r['name']} {rupiah(r['amount'])} tgl {r['day']}{' (lunas bulan ini)' if r['paid_this_month'] else ''}"
            for r in recurring) + ".")
    return success("\n".join(lines), data)
