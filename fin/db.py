"""Koneksi SQLite, skema, migrasi, transaksi tulis, dan backup otomatis."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import clock

BACKUP_KEEP = 30

EXPENSE_CATEGORIES = ["makan", "jajan", "transport", "belanja", "tempat tinggal", "pulsa & internet",
                      "pendidikan", "kesehatan", "hiburan", "tagihan", "biaya admin", "sedekah", "lainnya"]
INCOME_CATEGORIES = ["gaji", "uang saku", "freelance", "bonus", "lainnya"]

# kata kunci awal untuk menebak kategori dari catatan; bisa diubah lewat perintah alias
DEFAULT_KEYWORDS = {
    ("expense", "makan"): ["makan", "nasi", "ayam", "warteg", "padang", "bakso", "mie", "soto", "sate",
                           "geprek", "sarapan", "makan siang", "makan malam"],
    ("expense", "jajan"): ["jajan", "kopi", "es teh", "snack", "gorengan", "boba", "cilok", "roti"],
    ("expense", "transport"): ["parkir", "bensin", "ojek", "ojol", "gojek", "grab", "angkot", "krl",
                               "tol", "bus", "kereta", "busway"],
    ("expense", "belanja"): ["belanja", "sabun", "sampo", "indomaret", "alfamart", "shopee", "tokopedia"],
    ("expense", "tempat tinggal"): ["kos", "kost", "kontrakan", "sewa"],
    ("expense", "pulsa & internet"): ["pulsa", "kuota", "wifi", "internet", "paket data"],
    ("expense", "pendidikan"): ["buku", "fotokopi", "print", "ukt", "spp", "kuliah"],
    ("expense", "kesehatan"): ["obat", "dokter", "apotek", "vitamin"],
    ("expense", "hiburan"): ["nonton", "bioskop", "netflix", "spotify", "game"],
    ("expense", "tagihan"): ["listrik", "pln", "pdam", "tagihan", "token"],
    ("expense", "sedekah"): ["sedekah", "infaq", "infak", "zakat", "donasi"],
    ("income", "gaji"): ["gaji", "gajian"],
    ("income", "uang saku"): ["uang saku", "kiriman"],
    ("income", "freelance"): ["freelance", "proyek", "project"],
    ("income", "bonus"): ["bonus", "thr"],
}

SCHEMA_V1 = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type TEXT NOT NULL CHECK (type IN ('cash','bank','ewallet','savings')),
  is_default INTEGER NOT NULL DEFAULT 0,
  target_amount INTEGER,
  target_date TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL COLLATE NOCASE,
  kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE (name, kind)
);

CREATE TABLE aliases (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('account','category','keyword')),
  alias TEXT NOT NULL COLLATE NOCASE,
  target_id INTEGER NOT NULL,
  UNIQUE (kind, alias)
);

CREATE TABLE debts (
  id INTEGER PRIMARY KEY,
  direction TEXT NOT NULL CHECK (direction IN ('i_owe','owed_to_me')),
  person TEXT NOT NULL COLLATE NOCASE,
  principal INTEGER NOT NULL CHECK (principal > 0),
  due_date TEXT,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','paid')),
  created_at TEXT NOT NULL
);

CREATE TABLE transactions (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('income','expense','transfer','adjustment','debt_in','debt_out')),
  amount INTEGER NOT NULL,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  to_account_id INTEGER REFERENCES accounts(id),
  category_id INTEGER REFERENCES categories(id),
  debt_id INTEGER REFERENCES debts(id),
  note TEXT,
  raw_text TEXT,
  group_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX idx_tx_ts ON transactions(ts);
CREATE INDEX idx_tx_account ON transactions(account_id);

CREATE TABLE budgets (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  month TEXT,
  amount INTEGER NOT NULL CHECK (amount > 0),
  UNIQUE (category_id, month)
);

CREATE TABLE recurring (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  amount INTEGER NOT NULL,
  category_id INTEGER REFERENCES categories(id),
  account_id INTEGER REFERENCES accounts(id),
  day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
  last_paid_month TEXT,
  active INTEGER NOT NULL DEFAULT 1
);
"""


def _migrate_v1(conn):
    # executescript() akan meng-commit sendiri, jadi pernyataan dijalankan satu per satu
    for stmt in SCHEMA_V1.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    for name in EXPENSE_CATEGORIES:
        conn.execute("INSERT INTO categories(name, kind) VALUES (?, 'expense')", (name,))
    for name in INCOME_CATEGORIES:
        conn.execute("INSERT INTO categories(name, kind) VALUES (?, 'income')", (name,))
    for (kind, cat), words in DEFAULT_KEYWORDS.items():
        cat_id = conn.execute("SELECT id FROM categories WHERE name = ? AND kind = ?", (cat, kind)).fetchone()[0]
        for w in words:
            conn.execute("INSERT INTO aliases(kind, alias, target_id) VALUES ('keyword', ?, ?)", (w, cat_id))


UNALLOCATED = "belum teralokasi"

SCHEMA_V2 = """
DROP TABLE budgets;

CREATE TABLE budgets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  kind TEXT NOT NULL CHECK (kind IN ('unallocated','category','savings')),
  category_id INTEGER UNIQUE REFERENCES categories(id),
  target_amount INTEGER,
  target_date TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE budget_moves (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  from_budget_id INTEGER NOT NULL REFERENCES budgets(id),
  to_budget_id INTEGER NOT NULL REFERENCES budgets(id),
  amount INTEGER NOT NULL CHECK (amount > 0),
  note TEXT,
  group_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX idx_moves_ts ON budget_moves(ts);

CREATE TABLE op_groups (
  id INTEGER PRIMARY KEY,
  group_id TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL,
  restore TEXT,
  undoable INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

ALTER TABLE transactions ADD COLUMN budget_id INTEGER REFERENCES budgets(id);

CREATE TABLE accounts_v2 (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type TEXT NOT NULL CHECK (type IN ('cash','bank','ewallet')),
  is_default INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""


def _migrate_v2(conn):
    """Budget amplop: tabel budgets baru, budget_moves, op_groups, transactions.budget_id.
    Dompet bertipe savings menjadi bank, dan saldonya dialokasikan ke tabungan bernama sama."""
    now = clock.now_ts()
    savings = conn.execute("SELECT * FROM accounts WHERE type = 'savings' ORDER BY id").fetchall()
    for stmt in SCHEMA_V2.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.execute("INSERT INTO accounts_v2(id, name, type, is_default, archived, created_at) "
                 "SELECT id, name, CASE type WHEN 'savings' THEN 'bank' ELSE type END, is_default, archived, "
                 "created_at FROM accounts")
    conn.execute("DROP TABLE accounts")
    conn.execute("ALTER TABLE accounts_v2 RENAME TO accounts")

    unalloc = conn.execute("INSERT INTO budgets(name, kind, created_at) VALUES (?, 'unallocated', ?)",
                           (UNALLOCATED, now)).lastrowid
    conn.execute("UPDATE transactions SET budget_id = ? WHERE type != 'transfer'", (unalloc,))
    conn.execute("INSERT INTO op_groups(group_id, action, created_at) "
                 "SELECT group_id, 'legacy', MIN(created_at) FROM transactions GROUP BY group_id ORDER BY MIN(id)")

    for acc in savings:
        name = acc["name"]
        if conn.execute("SELECT 1 FROM budgets WHERE name = ?", (name,)).fetchone():
            name = f"{name} (tabungan)"
        bud = conn.execute("INSERT INTO budgets(name, kind, target_amount, target_date, archived, created_at) "
                           "VALUES (?, 'savings', ?, ?, ?, ?)",
                           (name, acc["target_amount"], acc["target_date"], acc["archived"], now)).lastrowid
        bal = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN account_id = :a AND type IN ('income','debt_in','adjustment') THEN amount "
            "WHEN account_id = :a THEN -amount WHEN to_account_id = :a THEN amount ELSE 0 END), 0) "
            "FROM transactions WHERE deleted_at IS NULL AND (account_id = :a OR to_account_id = :a)",
            {"a": acc["id"]}).fetchone()[0]
        if bal:
            group = f"migrasi-v2-{acc['id']}"
            conn.execute("INSERT INTO op_groups(group_id, action, undoable, created_at) "
                         "VALUES (?, 'migration', 0, ?)", (group, now))
            src, dst = (unalloc, bud) if bal > 0 else (bud, unalloc)
            conn.execute("INSERT INTO budget_moves(ts, from_budget_id, to_budget_id, amount, note, group_id, "
                         "created_at) VALUES (?,?,?,?,?,?,?)",
                         (now, src, dst, abs(bal), f"migrasi dompet tabungan {acc['name']}", group, now))
    if not conn.execute("SELECT 1 FROM accounts WHERE is_default = 1 AND archived = 0").fetchone():
        conn.execute("UPDATE accounts SET is_default = 1 WHERE id = "
                     "(SELECT MIN(id) FROM accounts WHERE archived = 0)")


SCHEMA_V3 = """
ALTER TABLE debts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;

CREATE TABLE recurring_v3 (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  amount INTEGER NOT NULL CHECK (amount > 0),
  category_id INTEGER REFERENCES categories(id),
  account_id INTEGER REFERENCES accounts(id),
  day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
  last_paid_month TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
)
"""

SCHEMA_V3_PAYMENTS = """
CREATE TABLE recurring_payments (
  id INTEGER PRIMARY KEY,
  recurring_id INTEGER NOT NULL REFERENCES recurring(id),
  tx_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
  month TEXT NOT NULL                -- 'YYYY-MM', bulan tagihan yang dibayar
);
CREATE INDEX idx_recpay_recurring ON recurring_payments(recurring_id)
"""


def _migrate_v3(conn):
    """Hutang bisa diarsipkan; tagihan rutin memakai kolom archived dan tabel recurring_payments
    (pembayaran per bulan, supaya last_paid_month bisa dihitung ulang setelah undo/delete)."""
    for stmt in SCHEMA_V3.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.execute("INSERT INTO recurring_v3(id, name, amount, category_id, account_id, day_of_month, "
                 "last_paid_month, archived, created_at) SELECT id, name, amount, category_id, account_id, "
                 "day_of_month, last_paid_month, 1 - active, ? FROM recurring", (clock.now_ts(),))
    conn.execute("DROP TABLE recurring")
    conn.execute("ALTER TABLE recurring_v3 RENAME TO recurring")
    for stmt in SCHEMA_V3_PAYMENTS.split(";"):
        if stmt.strip():
            conn.execute(stmt)


SCHEMA_V4 = """
CREATE TABLE accounts_v4 (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type TEXT NOT NULL CHECK (type IN ('cash','bank','ewallet','savings')),
  is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default = 0 OR type != 'savings'),
  archived INTEGER NOT NULL DEFAULT 0,
  target_amount INTEGER,
  target_date TEXT,
  created_at TEXT NOT NULL
);
INSERT INTO accounts_v4(id, name, type, is_default, archived, created_at)
  SELECT id, name, type, is_default, archived, created_at FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_v4 RENAME TO accounts;

CREATE TABLE transactions_v4 (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('income','expense','transfer','adjustment','debt_in','debt_out',
                                     'deposit','withdraw','savings_loan','savings_repay')),
  amount INTEGER NOT NULL,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  to_account_id INTEGER REFERENCES accounts(id),
  category_id INTEGER REFERENCES categories(id),
  debt_id INTEGER REFERENCES debts(id),
  budget_id INTEGER REFERENCES budgets(id),
  note TEXT,
  raw_text TEXT,
  group_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  deleted_at TEXT
);
INSERT INTO transactions_v4(id, ts, type, amount, account_id, to_account_id, category_id, debt_id, budget_id, note,
                            raw_text, group_id, created_at, deleted_at)
  SELECT id, ts, type, amount, account_id, to_account_id, category_id, debt_id, budget_id, note,
         raw_text, group_id, created_at, deleted_at FROM transactions;
DROP TABLE transactions;
ALTER TABLE transactions_v4 RENAME TO transactions;
CREATE INDEX idx_tx_ts ON transactions(ts);
CREATE INDEX idx_tx_account ON transactions(account_id);
CREATE INDEX idx_tx_group ON transactions(group_id);

ALTER TABLE debts ADD COLUMN savings_account_id INTEGER REFERENCES accounts(id)
"""


def _migrate_v4(conn):
    """Tabungan menjadi akun (dompet) berjenis savings di luar invarian, bukan lagi budget.

    Tabel accounts dan transactions dibangun ulang (jenis akun 'savings', target, jenis transaksi baru),
    debts.savings_account_id ditambah. Budget tabungan lama (jika ada) diubah dengan aman: sisa saldonya
    dikembalikan ke 'belum teralokasi' (uangnya memang ada di dompet operasional), budget itu diarsipkan, lalu
    dibuat akun tabungan kosong bernama sama dengan target yang sama. Tidak ada uang yang dibuat-buat.
    """
    now = clock.now_ts()
    for stmt in SCHEMA_V4.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    unalloc = conn.execute("SELECT id FROM budgets WHERE kind = 'unallocated'").fetchone()[0]
    for bud in conn.execute("SELECT * FROM budgets WHERE kind = 'savings' ORDER BY id").fetchall():
        bal = conn.execute(
            "SELECT COALESCE((SELECT SUM(CASE WHEN type IN ('income','debt_in','adjustment') THEN amount "
            "ELSE -amount END) FROM transactions WHERE deleted_at IS NULL AND budget_id = :b), 0) + "
            "COALESCE((SELECT SUM(amount) FROM budget_moves WHERE deleted_at IS NULL AND to_budget_id = :b), 0) - "
            "COALESCE((SELECT SUM(amount) FROM budget_moves WHERE deleted_at IS NULL AND from_budget_id = :b), 0)",
            {"b": bud["id"]}).fetchone()[0]
        if bal:
            group = f"migrasi-v4-{bud['id']}"
            conn.execute("INSERT INTO op_groups(group_id, action, undoable, created_at) VALUES (?, 'migration', 0, ?)",
                         (group, now))
            src, dst = (bud["id"], unalloc) if bal > 0 else (unalloc, bud["id"])
            conn.execute("INSERT INTO budget_moves(ts, from_budget_id, to_budget_id, amount, note, group_id, "
                         "created_at) VALUES (?,?,?,?,?,?,?)",
                         (now, src, dst, abs(bal), f"migrasi tabungan {bud['name']} menjadi akun", group, now))
        conn.execute("UPDATE budgets SET archived = 1 WHERE id = ?", (bud["id"],))
        if bud["archived"]:
            continue
        name = bud["name"]
        taken = {r[0].lower() for r in conn.execute("SELECT name FROM accounts")}
        if name.lower() in taken:
            name = f"{name} (tabungan)"
            n = 2
            while name.lower() in taken:
                name, n = f"{bud['name']} (tabungan {n})", n + 1
        conn.execute("INSERT INTO accounts(name, type, target_amount, target_date, created_at) "
                     "VALUES (?, 'savings', ?, ?, ?)", (name, bud["target_amount"], bud["target_date"], now))


MIGRATIONS = {1: _migrate_v1, 2: _migrate_v2, 3: _migrate_v3, 4: _migrate_v4}
SCHEMA_VERSION = max(MIGRATIONS)


class Connection(sqlite3.Connection):
    """Koneksi dengan penanda apakah database baru saja dibuat, dan status batch.

    batch_group: group_id bersama selama perintah batch berjalan (lihat batch()).
    """
    created = False
    batch_group = None


def default_home():
    """<profil pengguna>/Documents/Manager/Finance/data. Profil = USERPROFILE (Windows), atau HOME.

    Aturan yang sama dipakai fin.sh, jadi keduanya selalu membuka database yang sama.
    """
    profile = os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
    return Path(profile) / "Documents" / "Manager" / "Finance" / "data"


def home():
    """Folder data: FINANCE_HOME jika diisi, selain itu default_home()."""
    env = os.environ.get("FINANCE_HOME")
    return Path(env) if env else default_home()


def db_path():
    return home() / "finance.db"


def backup_dir():
    return home() / "backups"


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def schema_version(conn):
    has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if not has_meta:
        return 0
    return int(get_meta(conn, "schema_version") or 0)


def migrate(conn):
    version = schema_version(conn)
    pending = [v for v in sorted(MIGRATIONS) if v > version]
    if not pending:
        return
    if version >= 1:
        make_backup(conn, name=f"finance-{clock.now().strftime('%Y%m%d')}-pre-v{pending[-1]}.db")
    # tabel dibangun ulang saat migrasi, jadi foreign key dimatikan lalu diperiksa manual
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for v in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                MIGRATIONS[v](conn)
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"Migrasi v{v} merusak foreign key: {[tuple(r) for r in broken[:5]]}")
                set_meta(conn, "schema_version", v)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            if v == 1:
                conn.created = True
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def connect():
    """Buka database (membuat dan memigrasi jika perlu)."""
    home().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(), isolation_level=None, factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def make_backup(conn, name=None):
    """Salin database ke <folder data>/backups dan simpan BACKUP_KEEP file terakhir."""
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (name or f"finance-{clock.now().strftime('%Y%m%d')}.db")
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    files = sorted(folder.glob("finance-*.db"), key=lambda p: p.name)
    for old in files[:-BACKUP_KEEP]:
        old.unlink()
    return dest


def auto_backup(conn):
    """Backup sekali sehari, sebelum operasi tulis pertama hari itu."""
    today = clock.today().isoformat()
    if get_meta(conn, "last_backup_date") == today:
        return None
    dest = make_backup(conn)
    set_meta(conn, "last_backup_date", today)
    return dest


@contextmanager
def write(conn):
    """Satu perintah tulis = satu transaksi database. Gagal di tengah = tidak ada yang tersimpan.

    Di dalam batch(), transaksi luar yang menentukan commit atau rollback.
    """
    if conn.batch_group is not None:
        yield conn
        return
    auto_backup(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


@contextmanager
def batch(conn):
    """Beberapa perintah tulis dalam satu transaksi database dan satu group_id (yang di-yield)."""
    from .ledger import new_group
    auto_backup(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.batch_group = new_group(conn, "batch")
        yield conn.batch_group
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.batch_group = None
