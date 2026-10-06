"""category add / list / archive / unarchive, dan alias add / list / remove"""
from .. import budgets, resolve
from ..db import UNALLOCATED, write
from ..ledger import new_group
from ..output import FinError, rupiah, success
from ..resolve import KIND_LABEL

KINDS = ["expense", "income"]
SYSTEM_CATEGORIES = {("lainnya", "expense"), ("lainnya", "income"), ("biaya admin", "expense")}


def register(sub):
    p = sub.add_parser("category", help="Kelola kategori.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Tambah kategori.")
    a.add_argument("name")
    a.add_argument("--kind", required=True, choices=KINDS)
    a.set_defaults(func=cmd_category_add)

    a = s.add_parser("list", help="Daftar kategori.")
    a.add_argument("--kind", choices=KINDS)
    a.add_argument("--all", action="store_true", help="Sertakan kategori yang diarsipkan.")
    a.set_defaults(func=cmd_category_list)

    a = s.add_parser("rename", help="Ganti nama kategori.")
    a.add_argument("name")
    a.add_argument("new_name")
    a.add_argument("--kind", choices=KINDS, help="Wajib jika nama ada di pemasukan dan pengeluaran.")
    a.set_defaults(func=cmd_category_rename)

    a = s.add_parser("remove", help="Hapus kategori (budgetnya ikut ditutup).")
    a.add_argument("name")
    a.add_argument("--kind", choices=KINDS, help="Wajib jika nama ada di pemasukan dan pengeluaran.")
    a.set_defaults(func=cmd_category_remove)

    p = sub.add_parser("alias", help="Kelola alias dompet/kategori dan kata kunci tebak kategori.")
    s = p.add_subparsers(dest="action", required=True, metavar="<aksi>")

    a = s.add_parser("add", help="Tambah alias atau kata kunci.")
    a.add_argument("--kind", required=True, choices=["account", "category", "keyword"])
    a.add_argument("--alias", required=True)
    a.add_argument("--target", required=True, help="Nama dompet (kind account) atau kategori.")
    a.add_argument("--target-kind", choices=KINDS, help="Jenis kategori target jika namanya ambigu.")
    a.set_defaults(func=cmd_alias_add)

    a = s.add_parser("list", help="Daftar alias.")
    a.add_argument("--kind", choices=["account", "category", "keyword"])
    a.set_defaults(func=cmd_alias_list)

    a = s.add_parser("remove", help="Hapus alias.")
    a.add_argument("--kind", required=True, choices=["account", "category", "keyword"])
    a.add_argument("--alias", required=True)
    a.set_defaults(func=cmd_alias_remove)


# ---------- category ----------

def _ensure_name_free(conn, name, kind, except_id=None):
    key = resolve.norm(name)
    if key == resolve.norm(UNALLOCATED):
        raise FinError("SYSTEM_PROTECTED", f"Nama '{UNALLOCATED}' dipakai sistem.")
    for row in conn.execute("SELECT * FROM categories WHERE kind = ?", (kind,)):
        if row["id"] != except_id and resolve.norm(row["name"]) == key:
            raise FinError("BAD_ARGS", f"Kategori {KIND_LABEL[kind]} '{row['name']}' sudah ada.")
    for row in conn.execute("SELECT al.alias, c.name, c.id FROM aliases al JOIN categories c ON c.id = al.target_id "
                            "WHERE al.kind = 'category' AND c.kind = ?", (kind,)):
        if row["id"] != except_id and resolve.norm(row["alias"]) == key:
            raise FinError("BAD_ARGS", f"'{name}' sudah dipakai sebagai alias kategori {row['name']}.",
                           hint=f"Hapus dulu aliasnya: alias remove --kind category --alias \"{row['alias']}\"")
    if kind == "expense":
        clash = budgets.name_taken(conn, name)
        if clash and not (clash["kind"] == "category" and clash["category_id"] == except_id):
            raise FinError("BAD_ARGS", f"Nama '{name}' sudah dipakai budget {budgets.KIND_LABEL[clash['kind']]}.",
                           hint="Kategori pengeluaran dan tabungan tidak boleh bernama sama. Pakai nama lain.")


def _protect(cat, action):
    if (cat["name"].lower(), cat["kind"]) in SYSTEM_CATEGORIES:
        raise FinError("SYSTEM_PROTECTED", f"Kategori '{cat['name']}' dipakai sistem dan tidak bisa {action}.")


def cmd_category_add(args, conn):
    name = resolve.clean_name(args.name, "nama kategori")
    archived = [r for r in conn.execute("SELECT * FROM categories WHERE kind = ? AND archived = 1", (args.kind,))
                if resolve.norm(r["name"]) == resolve.norm(name)]
    if archived:
        cat = archived[0]
        with write(conn):
            conn.execute("UPDATE categories SET archived = 0 WHERE id = ?", (cat["id"],))
        return success(f"Kategori {KIND_LABEL[args.kind]} '{cat['name']}' diaktifkan kembali.",
                       {"id": cat["id"], "name": cat["name"], "kind": args.kind, "reactivated": True})
    _ensure_name_free(conn, name, args.kind)
    with write(conn):
        cat_id = conn.execute("INSERT INTO categories(name, kind) VALUES (?, ?)", (name, args.kind)).lastrowid
    msg = f"Kategori {KIND_LABEL[args.kind]} '{name}' ditambahkan."
    if args.kind == "expense":
        msg += f" Belum punya budget; pengeluarannya memakai {UNALLOCATED} sampai diberi alokasi."
    return success(msg, {"id": cat_id, "name": name, "kind": args.kind, "reactivated": False})


def cmd_category_list(args, conn):
    kinds = [args.kind] if args.kind else KINDS
    data, lines = [], []
    for kind in kinds:
        sql = "SELECT * FROM categories WHERE kind = ?" + ("" if args.all else " AND archived = 0") + " ORDER BY id"
        rows = conn.execute(sql, (kind,)).fetchall()
        names = []
        for r in rows:
            keywords = [k["alias"] for k in conn.execute(
                "SELECT alias FROM aliases WHERE kind = 'keyword' AND target_id = ? ORDER BY alias", (r["id"],))]
            bud = budgets.for_category(conn, r["id"]) if kind == "expense" else None
            data.append({"id": r["id"], "name": r["name"], "kind": kind, "archived": bool(r["archived"]),
                         "has_budget": bud is not None, "keywords": keywords})
            names.append(r["name"] + (" [dihapus]" if r["archived"] else ""))
        lines.append(f"Kategori {KIND_LABEL[kind]}: {', '.join(names) or '-'}.")
    return success("\n".join(lines), {"categories": data})


def cmd_category_rename(args, conn):
    cat = resolve.category(conn, args.name, args.kind)
    _protect(cat, "diganti nama")
    new = resolve.clean_name(args.new_name, "nama kategori")
    _ensure_name_free(conn, new, cat["kind"], except_id=cat["id"])
    with write(conn):
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new, cat["id"]))
        conn.execute("UPDATE budgets SET name = ? WHERE kind = 'category' AND category_id = ?", (new, cat["id"]))
    return success(f"Kategori {KIND_LABEL[cat['kind']]} '{cat['name']}' diganti nama menjadi '{new}'.",
                   {"id": cat["id"], "old_name": cat["name"], "name": new, "kind": cat["kind"]})


def cmd_category_remove(args, conn):
    cat = resolve.category(conn, args.name, args.kind)
    _protect(cat, "dihapus")
    bud = conn.execute("SELECT * FROM budgets WHERE kind = 'category' AND category_id = ?", (cat["id"],)).fetchone()
    swept = 0
    with write(conn):
        if bud is not None:
            swept = budgets.balances(conn)[bud["id"]]
            if swept:
                restore = [["categories", cat["id"]]] + ([["budgets", bud["id"]]] if not bud["archived"] else [])
                group = new_group(conn, "category_remove", restore=restore)
                budgets.sweep_to_unallocated(conn, bud, group, f"hapus kategori {cat['name']}")
            conn.execute("UPDATE budgets SET archived = 1 WHERE id = ?", (bud["id"],))
        used = bud is not None or conn.execute(
            "SELECT 1 FROM transactions WHERE category_id = ? UNION ALL "
            "SELECT 1 FROM recurring WHERE category_id = ? LIMIT 1", (cat["id"], cat["id"])).fetchone()
        if used:
            mode = "archived"
            conn.execute("UPDATE categories SET archived = 1 WHERE id = ?", (cat["id"],))
        else:
            mode = "deleted"
            conn.execute("DELETE FROM aliases WHERE kind IN ('category','keyword') AND target_id = ?", (cat["id"],))
            conn.execute("DELETE FROM categories WHERE id = ?", (cat["id"],))
    label = f"Kategori {KIND_LABEL[cat['kind']]} '{cat['name']}'"
    if mode == "deleted":
        msg = f"{label} dihapus permanen karena belum pernah dipakai."
    else:
        msg = f"{label} dihapus. Riwayat transaksinya tetap disimpan (diarsipkan)."
    if bud is not None and not bud["archived"]:
        msg += f" Budget {cat['name']} ditutup"
        msg += f", sisa {rupiah(swept)} dikembalikan ke {UNALLOCATED}." if swept else "."
        msg += " " + budgets.sentence(conn, [budgets.unallocated(conn)["id"]])
    return success(msg, {"id": cat["id"], "name": cat["name"], "kind": cat["kind"], "mode": mode,
                         "budget_closed": bud is not None and not bud["archived"], "returned_to_unallocated": swept})


# ---------- alias ----------

def _alias_target_name(conn, kind, target_id):
    table = "accounts" if kind == "account" else "categories"
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (target_id,)).fetchone()
    return row


def cmd_alias_add(args, conn):
    alias = resolve.clean_name(args.alias, "alias")
    key = resolve.norm(alias)
    if args.kind == "account":
        target = resolve.account(conn, args.target)
        if resolve.find_account(conn, alias) is not None:
            raise FinError("BAD_ARGS", f"'{alias}' sudah dipakai sebagai nama atau alias dompet.")
        label = f"dompet {target['name']}"
    else:
        target = resolve.category(conn, args.target, args.target_kind)
        if args.kind == "category":
            if resolve.find_categories(conn, alias, target["kind"]):
                raise FinError("BAD_ARGS", f"'{alias}' sudah dipakai sebagai nama atau alias kategori.")
            label = f"kategori {KIND_LABEL[target['kind']]} {target['name']}"
        else:
            label = f"kategori {KIND_LABEL[target['kind']]} {target['name']} (kata kunci tebakan)"
    for row in conn.execute("SELECT * FROM aliases WHERE kind = ?", (args.kind,)):
        if resolve.norm(row["alias"]) == key:
            current = _alias_target_name(conn, args.kind, row["target_id"])
            raise FinError("BAD_ARGS", f"Alias '{row['alias']}' sudah ada untuk {current['name']}.",
                           hint=f"Hapus dulu: alias remove --kind {args.kind} --alias \"{row['alias']}\"")
    with write(conn):
        alias_id = conn.execute("INSERT INTO aliases(kind, alias, target_id) VALUES (?,?,?)",
                                (args.kind, alias, target["id"])).lastrowid
    return success(f"'{alias}' sekarang dikenali sebagai {label}.",
                   {"id": alias_id, "kind": args.kind, "alias": alias, "target": target["name"],
                    "target_id": target["id"]})


def cmd_alias_list(args, conn):
    sql = "SELECT * FROM aliases" + (" WHERE kind = ?" if args.kind else "") + " ORDER BY kind, alias"
    rows = conn.execute(sql, (args.kind,) if args.kind else ()).fetchall()
    data, lines = [], []
    for r in rows:
        target = _alias_target_name(conn, r["kind"], r["target_id"])
        item = {"id": r["id"], "kind": r["kind"], "alias": r["alias"], "target": target["name"] if target else None}
        if r["kind"] != "account" and target:
            item["target_kind"] = target["kind"]
        data.append(item)
        lines.append(f"- [{r['kind']}] {r['alias']} → {item['target']}")
    if not rows:
        return success("Belum ada alias.", {"aliases": []})
    return success(f"{len(rows)} alias:\n" + "\n".join(lines), {"aliases": data})


def cmd_alias_remove(args, conn):
    key = resolve.norm(args.alias)
    for row in conn.execute("SELECT * FROM aliases WHERE kind = ?", (args.kind,)).fetchall():
        if resolve.norm(row["alias"]) == key:
            with write(conn):
                conn.execute("DELETE FROM aliases WHERE id = ?", (row["id"],))
            return success(f"Alias '{row['alias']}' dihapus.", {"id": row["id"], "kind": args.kind,
                                                                 "alias": row["alias"]})
    raise FinError("NOT_FOUND", f"Alias {args.kind} '{args.alias}' tidak ada.",
                   hint=f"Lihat daftar: alias list --kind {args.kind}")
