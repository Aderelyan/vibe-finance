"""init dan backup."""
from .. import clock, db
from ..output import success


def register(sub):
    p = sub.add_parser("init", help="Buat database dan data awal. Aman dijalankan ulang.")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("backup", help="Backup manual database.")
    p.set_defaults(func=cmd_backup)


def cmd_init(args, conn):
    path = str(db.db_path())
    n_acc = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    n_cat = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if conn.created:
        msg = f"Database baru dibuat di {path} dengan {n_cat} kategori bawaan."
    else:
        msg = f"Database sudah ada di {path}. Tidak ada yang diubah."
    if n_acc == 0:
        msg += " Belum ada dompet. Tambahkan dengan: account add <nama> --type cash|bank|ewallet --opening <saldo>."
    return success(msg, {"path": path, "created": conn.created, "schema_version": db.schema_version(conn),
                         "accounts": n_acc, "categories": n_cat})


def cmd_backup(args, conn):
    dest = db.make_backup(conn, name=f"finance-{clock.now().strftime('%Y%m%d-%H%M%S')}.db")
    return success(f"Backup tersimpan di {dest}.", {"path": str(dest)})
