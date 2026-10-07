"""Budget sistem amplop. Saldo budget tidak disimpan, selalu dihitung.

Aturan utama: total dompet operasional = total semua budget. Ini dijaga karena setiap transaksi yang mengubah
total dompet operasional menunjuk ke tepat satu budget (lihat ledger.py), dan pindahan budget selalu berpasangan.
Tabungan bukan budget (sejak skema v4); budget berjenis 'savings' hanya sisa lama yang sudah diarsipkan.
"""
from . import clock, resolve
from .db import UNALLOCATED
from .ledger import BUDGET_SIGN_SQL
from .output import FinError, rupiah

KIND_LABEL = {"unallocated": "sistem", "category": "kategori", "savings": "tabungan lama"}

_BALANCE_SQL = f"""
SELECT bud, SUM(delta) AS bal FROM (
  SELECT budget_id AS bud, {BUDGET_SIGN_SQL} AS delta
    FROM transactions WHERE deleted_at IS NULL AND budget_id IS NOT NULL
  UNION ALL
  SELECT to_budget_id AS bud, amount AS delta FROM budget_moves WHERE deleted_at IS NULL
  UNION ALL
  SELECT from_budget_id AS bud, -amount AS delta FROM budget_moves WHERE deleted_at IS NULL
) GROUP BY bud
"""


def balances(conn):
    """{budget_id: saldo} untuk semua budget, termasuk yang ditutup."""
    result = {r["id"]: 0 for r in conn.execute("SELECT id FROM budgets")}
    for r in conn.execute(_BALANCE_SQL):
        result[r["bud"]] = r["bal"]
    return result


def unallocated(conn):
    return conn.execute("SELECT * FROM budgets WHERE kind = 'unallocated'").fetchone()


def get(conn, budget_id):
    return conn.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone()


def for_category(conn, category_id):
    """Budget aktif milik kategori, atau None."""
    return conn.execute("SELECT * FROM budgets WHERE kind = 'category' AND category_id = ? AND archived = 0",
                        (category_id,)).fetchone()


def for_expense(conn, category_id):
    """Budget yang dipakai pengeluaran berkategori ini: budget kategorinya, atau 'belum teralokasi'."""
    return for_category(conn, category_id) or unallocated(conn)


def active_names(conn):
    return [r["name"] for r in conn.execute(
        "SELECT name FROM budgets WHERE archived = 0 ORDER BY CASE kind WHEN 'unallocated' THEN 0 "
        "WHEN 'category' THEN 1 ELSE 2 END, id")]


def _hint(conn):
    return ("Budget yang ada: " + ", ".join(active_names(conn))
            + ". Kategori pengeluaran tanpa budget juga bisa diberi alokasi, contoh: budget alloc --item \"makan|300k\".")


def _savings_named(conn, name):
    key = resolve.norm(name)
    for r in conn.execute("SELECT * FROM accounts WHERE type = 'savings' AND archived = 0"):
        if resolve.norm(r["name"]) == key:
            return r
    return None


def name_taken(conn, name, except_budget_id=None):
    """Budget (aktif maupun ditutup) yang memakai nama ini, atau None."""
    key = resolve.norm(name)
    for row in conn.execute("SELECT * FROM budgets"):
        if row["id"] != except_budget_id and resolve.norm(row["name"]) == key:
            return row
    return None


def find(conn, name, *, create=False, include_archived=False):
    """Cari budget dari nama budget, nama/alias kategori pengeluaran, atau 'belum teralokasi'.

    create=True: kategori pengeluaran yang belum punya budget (atau budgetnya ditutup) diberi budget,
    jadi hanya boleh dipanggil di dalam write(conn).
    """
    key = resolve.norm(name)
    matched = [r for r in conn.execute("SELECT * FROM budgets") if resolve.norm(r["name"]) == key]
    for row in matched:
        if not row["archived"] or include_archived:
            return row
    cats = [c for c in resolve.find_categories(conn, name, "expense") if not c["archived"]]
    if cats:
        cat = cats[0]
        existing = conn.execute("SELECT * FROM budgets WHERE kind = 'category' AND category_id = ?",
                                (cat["id"],)).fetchone()
        if existing and (not existing["archived"] or include_archived):
            return existing
        if not create:
            raise FinError("UNKNOWN_BUDGET", f"Kategori {cat['name']} belum punya budget.",
                           hint=f"Beri alokasi dulu, contoh: budget alloc --item \"{cat['name']}|100k\". "
                                f"Selama belum punya budget, pengeluaran {cat['name']} memakai {UNALLOCATED}.")
        return ensure_category_budget(conn, cat)
    sav = _savings_named(conn, name)
    if sav is not None:
        raise FinError("UNKNOWN_BUDGET", f"'{sav['name']}' adalah tabungan, bukan budget.",
                       hint=f"Menabung: savings deposit --from <dompet> --to \"{sav['name']}\" --amount <jumlah>. "
                            f"Belanja dari tabungan: savings spend --from \"{sav['name']}\" --item ... --mode purpose. "
                            + _hint(conn))
    raise FinError("UNKNOWN_BUDGET", f"Budget '{name}' tidak ada.", hint=_hint(conn))


def ensure_category_budget(conn, cat):
    """Buat atau aktifkan kembali budget milik kategori pengeluaran."""
    existing = conn.execute("SELECT * FROM budgets WHERE kind = 'category' AND category_id = ?",
                            (cat["id"],)).fetchone()
    if existing:
        if existing["archived"]:
            conn.execute("UPDATE budgets SET archived = 0, name = ? WHERE id = ?", (cat["name"], existing["id"]))
        return get(conn, existing["id"])
    clash = name_taken(conn, cat["name"])
    if clash:
        raise FinError("BAD_ARGS", f"Nama '{cat['name']}' sudah dipakai budget {KIND_LABEL[clash['kind']]} lain.",
                       hint="Ganti nama salah satunya dulu (category rename atau savings rename).")
    new_id = conn.execute("INSERT INTO budgets(name, kind, category_id, created_at) VALUES (?, 'category', ?, ?)",
                          (cat["name"], cat["id"], clock.now_ts())).lastrowid
    return get(conn, new_id)


def insert_move(conn, *, from_id, to_id, amount, group_id, note=None, ts=None):
    assert isinstance(amount, int) and amount > 0 and from_id != to_id
    now = clock.now_ts()
    return conn.execute("INSERT INTO budget_moves(ts, from_budget_id, to_budget_id, amount, note, group_id, "
                        "created_at) VALUES (?,?,?,?,?,?,?)",
                        (ts or now, from_id, to_id, amount, note or None, group_id, now)).lastrowid


def sweep_to_unallocated(conn, budget, group_id, note):
    """Kembalikan sisa (plus atau minus) budget ke 'belum teralokasi'. Kembalikan sisa yang dipindah."""
    bal = balances(conn)[budget["id"]]
    unalloc = unallocated(conn)
    if bal > 0:
        insert_move(conn, from_id=budget["id"], to_id=unalloc["id"], amount=bal, group_id=group_id, note=note)
    elif bal < 0:
        insert_move(conn, from_id=unalloc["id"], to_id=budget["id"], amount=-bal, group_id=group_id, note=note)
    return bal


def is_used(conn, budget_id):
    return bool(conn.execute("SELECT 1 FROM transactions WHERE budget_id = ? LIMIT 1", (budget_id,)).fetchone()
                or conn.execute("SELECT 1 FROM budget_moves WHERE from_budget_id = ? OR to_budget_id = ? LIMIT 1",
                                (budget_id, budget_id)).fetchone())


def sentence(conn, budget_ids):
    """'Sisa budget makan Rp250.000.' plus peringatan untuk budget yang minus."""
    bals = balances(conn)
    parts, warnings = [], []
    for bid in dict.fromkeys(budget_ids):
        row = get(conn, bid)
        bal = bals[bid]
        label = row["name"] + (" (ditutup)" if row["archived"] else "")
        parts.append(f"{label} {rupiah(bal)}")
        if bal < 0:
            warnings.append(warning(row, bal))
    text = "Sisa budget " + ", ".join(parts) + "."
    if warnings:
        text += " " + " ".join(warnings)
    return text


def warning(row, bal):
    if row["kind"] == "unallocated":
        return (f"Peringatan: {UNALLOCATED} minus {rupiah(-bal)}, artinya alokasi melebihi uang yang ada. "
                f"Kurangi alokasi lewat budget move ke {UNALLOCATED}.")
    return f"Peringatan: budget {row['name']} minus {rupiah(-bal)}."


def overview(conn):
    """Semua budget aktif (plus yang ditutup tapi masih bersaldo) beserta total."""
    bals = balances(conn)
    rows = conn.execute("SELECT * FROM budgets ORDER BY CASE kind WHEN 'unallocated' THEN 0 "
                        "WHEN 'category' THEN 1 ELSE 2 END, name").fetchall()
    rows = [r for r in rows if not r["archived"] or bals[r["id"]] != 0]
    items = [{"id": r["id"], "name": r["name"], "kind": r["kind"], "balance": bals[r["id"]],
              "archived": bool(r["archived"])} for r in rows]
    return {"budgets": items, "total_budget": sum(bals.values())}


def line(item):
    tag = " (ditutup)" if item["archived"] else ""
    minus = " [minus]" if item["balance"] < 0 else ""
    return f"- {item['name']}{tag}: {rupiah(item['balance'])}{minus}"
