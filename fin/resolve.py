"""Mencari dompet dan kategori dari nama atau alias. Tidak pernah membuat data baru."""
import re

from .output import FinError

KIND_LABEL = {"expense": "pengeluaran", "income": "pemasukan"}


def norm(text):
    """Bentuk pembanding: huruf kecil, spasi/strip/garis bawah disamakan."""
    return re.sub(r"[\s_\-]+", " ", str(text).strip().lower())


def clean_name(text, what="nama"):
    name = re.sub(r"\s+", " ", str(text or "").strip())
    if not name:
        raise FinError("BAD_ARGS", f"{what.capitalize()} tidak boleh kosong.")
    if len(name) > 40:
        raise FinError("BAD_ARGS", f"{what.capitalize()} terlalu panjang (maksimal 40 huruf).")
    if "|" in name:
        raise FinError("BAD_ARGS", f"{what.capitalize()} tidak boleh mengandung tanda '|'.")
    return name


# ---------- dompet ----------

def account_names(conn, include_archived=False, kind="operational"):
    """Nama akun aktif. kind: 'operational' (dompet), 'savings' (tabungan), atau None (semua)."""
    where = [] if include_archived else ["archived = 0"]
    if kind == "operational":
        where.append("type != 'savings'")
    elif kind == "savings":
        where.append("type = 'savings'")
    sql = "SELECT name FROM accounts" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
    return [r["name"] for r in conn.execute(sql)]


def _account_hint(conn, kind="operational"):
    if kind == "savings":
        names = account_names(conn, kind="savings")
        if not names:
            return "Belum ada tabungan. Buat dulu, contoh: savings add \"dana darurat\" --target 5jt"
        return "Tabungan yang ada: " + ", ".join(names)
    names = account_names(conn, kind=kind)
    if not names:
        return "Belum ada dompet. Buat dulu, contoh: account add tunai --type cash --opening 100k --default"
    return "Pilihan: " + ", ".join(names)


def find_account(conn, name):
    """Cari dompet (termasuk yang diarsipkan) dari nama atau alias. None jika tidak ada."""
    key = norm(name)
    for row in conn.execute("SELECT * FROM accounts"):
        if norm(row["name"]) == key:
            return row
    for row in conn.execute("SELECT a.*, al.alias AS _alias FROM aliases al JOIN accounts a ON a.id = al.target_id "
                            "WHERE al.kind = 'account'"):
        if norm(row["_alias"]) == key:
            return conn.execute("SELECT * FROM accounts WHERE id = ?", (row["id"],)).fetchone()
    return None


def account(conn, name, include_archived=False, kind="operational"):
    """Dompet/tabungan dari nama atau alias.

    kind='operational' (bawaan): hanya dompet cash/bank/ewallet. kind='savings': hanya tabungan. None: keduanya.
    """
    row = find_account(conn, name)
    what = "Tabungan" if kind == "savings" else "Dompet"
    if row is None:
        raise FinError("UNKNOWN_ACCOUNT", f"{what} '{name}' tidak ada.", hint=_account_hint(conn, kind))
    is_sav = row["type"] == "savings"
    if kind == "operational" and is_sav:
        raise FinError("UNKNOWN_ACCOUNT", f"'{row['name']}' adalah tabungan, bukan dompet.",
                       hint="Untuk tabungan pakai perintah savings (deposit, withdraw, spend). "
                            + _account_hint(conn, kind))
    if kind == "savings" and not is_sav:
        raise FinError("UNKNOWN_ACCOUNT", f"'{row['name']}' adalah dompet, bukan tabungan.",
                       hint=_account_hint(conn, kind))
    if row["archived"] and not include_archived:
        again = (f"savings add \"{row['name']}\"" if is_sav else f"account add {row['name']} --type {row['type']}")
        raise FinError("UNKNOWN_ACCOUNT", f"{'Tabungan' if is_sav else 'Dompet'} '{row['name']}' sudah dihapus.",
                       hint=f"Untuk memakainya lagi: {again}. {_account_hint(conn, 'savings' if is_sav else kind)}")
    return row


def default_account(conn):
    row = conn.execute("SELECT * FROM accounts WHERE is_default = 1 AND archived = 0 AND type != 'savings'").fetchone()
    if row is None:
        raise FinError("NO_DEFAULT_ACCOUNT", "Dompet tidak disebut dan belum ada dompet default.",
                       hint="Sebutkan dompet dengan --account, atau atur default: account set-default <nama>. "
                            + _account_hint(conn))
    return row


def account_or_default(conn, name):
    """(row, pakai_default)"""
    if name:
        return account(conn, name), False
    return default_account(conn), True


# ---------- kategori ----------

def category_names(conn, kind):
    return [r["name"] for r in conn.execute(
        "SELECT name FROM categories WHERE kind = ? AND archived = 0 ORDER BY id", (kind,))]


def _category_hint(conn, kind):
    kinds = [kind] if kind else ["expense", "income"]
    return " ".join(f"Kategori {KIND_LABEL[k]}: {', '.join(category_names(conn, k))}." for k in kinds)


def find_categories(conn, name, kind=None):
    """Semua kategori (termasuk arsip) yang cocok dengan nama atau alias, opsional dibatasi kind."""
    key = norm(name)
    found = {}
    for row in conn.execute("SELECT * FROM categories"):
        if norm(row["name"]) == key:
            found[row["id"]] = row
    if not found:
        for row in conn.execute("SELECT c.*, al.alias AS _alias FROM aliases al "
                                "JOIN categories c ON c.id = al.target_id WHERE al.kind = 'category'"):
            if norm(row["_alias"]) == key:
                found[row["id"]] = conn.execute("SELECT * FROM categories WHERE id = ?", (row["id"],)).fetchone()
    rows = list(found.values())
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return rows


def category(conn, name, kind=None, include_archived=False):
    rows = find_categories(conn, name, kind)
    if not rows:
        what = f"Kategori {KIND_LABEL[kind]}" if kind else "Kategori"
        raise FinError("UNKNOWN_CATEGORY", f"{what} '{name}' tidak ada.", hint=_category_hint(conn, kind))
    if len(rows) > 1:
        raise FinError("BAD_ARGS", f"Kategori '{name}' ada di pemasukan dan pengeluaran.",
                       hint="Tambahkan --kind expense atau --kind income.")
    row = rows[0]
    if row["archived"] and not include_archived:
        raise FinError("UNKNOWN_CATEGORY", f"Kategori '{row['name']}' sudah dihapus.",
                       hint=f"Untuk memakainya lagi: category add \"{row['name']}\" --kind {row['kind']}. "
                            + _category_hint(conn, kind))
    return row


def category_by_name(conn, name, kind):
    """Kategori sistem (lainnya, biaya admin). Arsip tetap boleh dipakai."""
    row = conn.execute("SELECT * FROM categories WHERE name = ? AND kind = ?", (name, kind)).fetchone()
    if row is None:
        raise FinError("UNKNOWN_CATEGORY", f"Kategori sistem '{name}' hilang dari database.",
                       hint=f"Buat lagi dengan: category add \"{name}\" --kind {kind}")
    return row


def guess_category(conn, note, kind):
    """Tebak kategori dari kata kunci di catatan. Kembalikan (row, kata_kunci_atau_None)."""
    text = " " + norm(note or "") + " "
    best = None
    for row in conn.execute("SELECT al.alias, c.* FROM aliases al JOIN categories c ON c.id = al.target_id "
                            "WHERE al.kind = 'keyword' AND c.kind = ? AND c.archived = 0", (kind,)):
        word = norm(row["alias"])
        m = re.search(r"(?<![0-9a-z])" + re.escape(word) + r"(?![0-9a-z])", text)
        if m and (best is None or len(word) > len(best[0]) or (len(word) == len(best[0]) and m.start() < best[1])):
            best = (word, m.start(), row)
    if best:
        cat = conn.execute("SELECT * FROM categories WHERE id = ?", (best[2]["id"],)).fetchone()
        return cat, best[0]
    return category_by_name(conn, "lainnya", kind), None
