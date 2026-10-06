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


MIGRATIONS = {1: _migrate_v1}
SCHEMA_VERSION = max(MIGRATIONS)


class Connection(sqlite3.Connection):
    """Koneksi dengan penanda apakah database baru saja dibuat."""
    created = False


def home():
    env = os.environ.get("FINANCE_HOME")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "data"


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
    for v in sorted(MIGRATIONS):
        if v > version:
            conn.execute("BEGIN IMMEDIATE")
            try:
                MIGRATIONS[v](conn)
                set_meta(conn, "schema_version", v)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            if v == 1:
                conn.created = True


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
    """Salin database ke data/backups dan simpan BACKUP_KEEP file terakhir."""
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
    """Satu perintah tulis = satu transaksi database. Gagal di tengah = tidak ada yang tersimpan."""
    auto_backup(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
