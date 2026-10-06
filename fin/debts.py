"""Hitungan hutang piutang. Sisa selalu dihitung dari transaksi pembayaran."""
from datetime import date

from . import clock, resolve
from .output import FinError, fmt_date, rupiah

# jenis transaksi yang dihitung sebagai pembayaran untuk tiap arah
PAYMENT_TYPE = {"i_owe": "debt_out", "owed_to_me": "debt_in"}
OPENING_TYPE = {"i_owe": "debt_in", "owed_to_me": "debt_out"}
DIRECTION_LABEL = {"i_owe": "hutang", "owed_to_me": "piutang"}


def paid(conn, debt):
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions "
                       "WHERE debt_id = ? AND type = ? AND deleted_at IS NULL",
                       (debt["id"], PAYMENT_TYPE[debt["direction"]])).fetchone()
    return row[0]


def remaining(conn, debt):
    return debt["principal"] - paid(conn, debt)


def recompute_status(conn, debt_id):
    debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    if debt is None:
        return
    status = "paid" if remaining(conn, debt) <= 0 else "open"
    conn.execute("UPDATE debts SET status = ? WHERE id = ?", (status, debt_id))


def totals(conn):
    """(total hutang saya, total piutang) dari hutang yang masih terbuka dan tidak dihapus."""
    owe = owed = 0
    for debt in conn.execute("SELECT * FROM debts WHERE status = 'open' AND archived = 0").fetchall():
        rest = max(remaining(conn, debt), 0)
        if debt["direction"] == "i_owe":
            owe += rest
        else:
            owed += rest
    return owe, owed


def title(debt, cap=False):
    """'hutang ke Budi' / 'piutang dari Andi'. cap=True: huruf pertama kalimat saja yang dibesarkan."""
    text = ("hutang ke " if debt["direction"] == "i_owe" else "piutang dari ") + debt["person"]
    return text[0].upper() + text[1:] if cap else text


def due_text(due_date):
    """'jatuh tempo 10 Oktober 2026 (4 hari lagi)' atau None."""
    if not due_date:
        return None
    days = days_until(due_date)
    if days < 0:
        when = f"lewat {-days} hari"
    elif days == 0:
        when = "hari ini"
    else:
        when = f"{days} hari lagi"
    return f"jatuh tempo {fmt_date(due_date)} ({when})"


def days_until(due_date):
    return (date.fromisoformat(due_date[:10]) - clock.today()).days


def info(conn, debt):
    """Ringkasan satu hutang sebagai dict untuk data JSON."""
    p = paid(conn, debt)
    has_tx = conn.execute("SELECT 1 FROM transactions WHERE debt_id = ? AND type = ? AND deleted_at IS NULL",
                          (debt["id"], OPENING_TYPE[debt["direction"]])).fetchone() is not None
    days_left = days_until(debt["due_date"]) if debt["due_date"] else None
    return {"id": debt["id"], "direction": debt["direction"], "person": debt["person"],
            "principal": debt["principal"], "paid": p, "remaining": debt["principal"] - p,
            "status": debt["status"], "due_date": debt["due_date"], "days_until_due": days_left,
            "note": debt["note"], "cash": has_tx, "archived": bool(debt["archived"]),
            "created_at": debt["created_at"]}


def line(item):
    """'#3 hutang ke Budi: sisa Rp30.000 dari Rp50.000, jatuh tempo ...'"""
    who = f"hutang ke {item['person']}" if item["direction"] == "i_owe" else f"piutang dari {item['person']}"
    text = f"#{item['id']} {who}: "
    if item["status"] == "paid":
        text += f"lunas ({rupiah(item['principal'])})"
    else:
        text += f"sisa {rupiah(item['remaining'])} dari {rupiah(item['principal'])}"
        due = due_text(item["due_date"])
        if due:
            text += f", {due}"
    if item["note"]:
        text += f" · {item['note']}"
    if item["archived"]:
        text += " [dihapus]"
    return text


def person_matches(conn, person, *, include_archived=False):
    key = resolve.norm(person)
    sql = "SELECT * FROM debts" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY id"
    return [d for d in conn.execute(sql).fetchall() if resolve.norm(d["person"]) == key]


def known_person(conn, person):
    """Ejaan nama yang sudah dipakai di catatan hutang (supaya 'budi' dan 'Budi' jadi satu), atau None."""
    rows = person_matches(conn, person, include_archived=True)
    return rows[-1]["person"] if rows else None


def _people_hint(conn):
    rows = conn.execute("SELECT * FROM debts WHERE archived = 0 AND status = 'open' ORDER BY id").fetchall()
    if not rows:
        return "Belum ada hutang atau piutang yang terbuka. Lihat semua dengan: debt list --status all"
    return "Yang terbuka: " + "; ".join(f"#{d['id']} {title(d)} sisa {rupiah(remaining(conn, d))}" for d in rows)


def find(conn, *, debt_id=None, person=None, direction=None, require_open=True):
    """Pilih tepat satu hutang dari --id atau --person (opsional --direction).

    Dengan --person, yang masih terbuka diutamakan. require_open=True: jika semuanya lunas, OVERPAYMENT.
    Lebih dari satu kandidat: AMBIGUOUS_DEBT beserta daftar ID.
    """
    if debt_id is not None:
        row = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
        if row is None or row["archived"]:
            what = "sudah dihapus" if row is not None else "tidak ada"
            raise FinError("NOT_FOUND", f"Hutang/piutang #{debt_id} {what}.", hint=_people_hint(conn))
        if direction and row["direction"] != direction:
            raise FinError("BAD_ARGS", f"#{debt_id} adalah {title(row)}, bukan {DIRECTION_LABEL[direction]}.")
        return row
    rows = person_matches(conn, person)
    if direction:
        rows = [d for d in rows if d["direction"] == direction]
    if not rows:
        raise FinError("NOT_FOUND", f"Tidak ada hutang/piutang atas nama '{person}'.", hint=_people_hint(conn))
    open_rows = [d for d in rows if d["status"] == "open"]
    if open_rows:
        rows = open_rows
    elif require_open:
        raise FinError("OVERPAYMENT", f"Hutang/piutang atas nama {rows[0]['person']} sudah lunas semua.",
                       hint=f"Lihat riwayatnya: debt list --status all --person \"{rows[0]['person']}\"")
    if len(rows) > 1:
        options = [{"id": d["id"], "direction": d["direction"], "remaining": remaining(conn, d),
                    "principal": d["principal"], "created_at": d["created_at"], "note": d["note"]} for d in rows]
        listing = "; ".join(f"#{o['id']} {title(d)} sisa {rupiah(o['remaining'])}"
                            + (f" ({o['note']})" if o["note"] else "") for o, d in zip(options, rows))
        raise FinError("AMBIGUOUS_DEBT", f"{rows[0]['person']} punya {len(rows)} catatan hutang/piutang: {listing}.",
                       hint="Sebutkan yang dimaksud dengan --id, contoh --id " + str(rows[0]["id"]) + ".",
                       data={"candidates": options})
    return rows[0]
