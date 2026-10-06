"""category add / list / archive / unarchive, dan alias add / list / remove"""
from .. import resolve
from ..db import write
from ..output import FinError, success
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

    for action, func, text in (("archive", cmd_category_archive, "Arsipkan kategori."),
                               ("unarchive", cmd_category_unarchive, "Aktifkan lagi kategori.")):
        a = s.add_parser(action, help=text)
        a.add_argument("name")
        a.add_argument("--kind", choices=KINDS, help="Wajib jika nama ada di pemasukan dan pengeluaran.")
        a.set_defaults(func=func)

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

def cmd_category_add(args, conn):
    name = resolve.clean_name(args.name, "nama kategori")
    key = resolve.norm(name)
    for row in conn.execute("SELECT * FROM categories WHERE kind = ?", (args.kind,)):
        if resolve.norm(row["name"]) == key:
            hint = (f"Kategori itu diarsipkan; aktifkan dengan: category unarchive \"{row['name']}\" --kind {args.kind}"
                    if row["archived"] else None)
            raise FinError("BAD_ARGS", f"Kategori {KIND_LABEL[args.kind]} '{row['name']}' sudah ada.", hint=hint)
    for row in conn.execute("SELECT al.alias, c.name FROM aliases al JOIN categories c ON c.id = al.target_id "
                            "WHERE al.kind = 'category' AND c.kind = ?", (args.kind,)):
        if resolve.norm(row["alias"]) == key:
            raise FinError("BAD_ARGS", f"'{name}' sudah dipakai sebagai alias kategori {row['name']}.",
                           hint=f"Hapus dulu aliasnya: alias remove --kind category --alias \"{row['alias']}\"")
    with write(conn):
        cat_id = conn.execute("INSERT INTO categories(name, kind) VALUES (?, ?)", (name, args.kind)).lastrowid
    return success(f"Kategori {KIND_LABEL[args.kind]} '{name}' ditambahkan.",
                   {"id": cat_id, "name": name, "kind": args.kind})


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
            data.append({"id": r["id"], "name": r["name"], "kind": kind, "archived": bool(r["archived"]),
                         "keywords": keywords})
            names.append(r["name"] + (" [arsip]" if r["archived"] else ""))
        lines.append(f"Kategori {KIND_LABEL[kind]}: {', '.join(names) or '-'}.")
    return success("\n".join(lines), {"categories": data})


def _set_category_archived(args, conn, archived):
    cat = resolve.category(conn, args.name, args.kind, include_archived=True)
    if archived and (cat["name"].lower(), cat["kind"]) in SYSTEM_CATEGORIES:
        raise FinError("BAD_ARGS", f"Kategori '{cat['name']}' dipakai sistem dan tidak bisa diarsipkan.")
    with write(conn):
        conn.execute("UPDATE categories SET archived = ? WHERE id = ?", (int(archived), cat["id"]))
    state = "diarsipkan" if archived else "aktif lagi"
    return success(f"Kategori {KIND_LABEL[cat['kind']]} '{cat['name']}' {state}.",
                   {"id": cat["id"], "name": cat["name"], "kind": cat["kind"], "archived": archived})


def cmd_category_archive(args, conn):
    return _set_category_archived(args, conn, True)


def cmd_category_unarchive(args, conn):
    return _set_category_archived(args, conn, False)


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
