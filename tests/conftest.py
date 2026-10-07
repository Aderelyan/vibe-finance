import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fin.cli import execute  # noqa: E402

DEFAULT_NOW = "2026-10-06 12:00:00"  # Selasa


class Fin:
    """Menjalankan perintah CLI di dalam proses dengan database sementara."""

    def __init__(self, home):
        self.home = home
        self.now = DEFAULT_NOW

    def __call__(self, *args, now=None):
        code, obj = execute(["--now", now or self.now, *[str(a) for a in args]])
        json.dumps(obj)  # harus bisa diserialisasi
        assert (code == 0) == obj["ok"], obj
        self.check_invariant()
        return obj

    def totals(self):
        """(total dompet operasional, total budget) dihitung langsung dari tabel, terpisah dari kode aplikasi.

        Tabungan (accounts.type = 'savings') tidak masuk total dompet. Ikut diperiksa: aturan budget_id per jenis
        transaksi, kelas akun pada transfer/deposit/withdraw, dan tabungan tidak pernah jadi dompet default.
        """
        import sqlite3
        conn = sqlite3.connect(self.home / "finance.db")
        try:
            op = "(SELECT id FROM accounts WHERE type != 'savings')"
            out_side = "CASE WHEN type IN ('income','debt_in','adjustment','savings_repay') THEN amount ELSE -amount END"
            wallets = conn.execute(f"SELECT COALESCE(SUM({out_side}), 0) FROM transactions "
                                   f"WHERE deleted_at IS NULL AND account_id IN {op}").fetchone()[0]
            wallets += conn.execute(f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE deleted_at IS NULL "
                                    f"AND type IN ('transfer','deposit','withdraw') AND to_account_id IN {op}"
                                    ).fetchone()[0]
            bsign = "CASE WHEN type IN ('income','debt_in','adjustment','withdraw') THEN amount ELSE -amount END"
            budget_tx = conn.execute(f"SELECT COALESCE(SUM({bsign}), 0) FROM transactions "
                                     "WHERE deleted_at IS NULL AND budget_id IS NOT NULL").fetchone()[0]
            # budget_id wajib persis untuk transaksi yang mengubah total dompet operasional
            wrong = conn.execute(
                f"SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
                f"LEFT JOIN accounts b ON b.id = t.to_account_id WHERE (t.budget_id IS NOT NULL) != ("
                f"t.type IN ('deposit','withdraw') OR (t.type IN ('income','expense','adjustment','debt_in','debt_out') "
                f"AND a.type != 'savings'))").fetchone()[0]
            assert wrong == 0, "budget_id tidak sesuai aturan jenis transaksi/kelas akun"
            mixed = conn.execute(
                "SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
                "JOIN accounts b ON b.id = t.to_account_id WHERE "
                "(t.type = 'transfer' AND (a.type = 'savings') != (b.type = 'savings')) OR "
                "(t.type = 'deposit' AND NOT (a.type != 'savings' AND b.type = 'savings')) OR "
                "(t.type = 'withdraw' AND NOT (a.type = 'savings' AND b.type != 'savings'))").fetchone()[0]
            assert mixed == 0, "kelas akun asal/tujuan salah"
            assert conn.execute("SELECT COUNT(*) FROM accounts WHERE type = 'savings' AND is_default = 1"
                                ).fetchone()[0] == 0
            return wallets, budget_tx  # pindahan budget selalu berjumlah nol
        finally:
            conn.close()

    def check_invariant(self):
        if (self.home / "finance.db").exists():
            wallets, budgets = self.totals()
            assert wallets == budgets, f"total dompet {wallets} != total budget {budgets}"

    def ok(self, *args, now=None):
        obj = self(*args, now=now)
        assert obj["ok"], obj
        assert isinstance(obj["message"], str) and obj["message"]
        return obj

    def err(self, code, *args, now=None):
        obj = self(*args, now=now)
        assert not obj["ok"], obj
        assert obj["error"]["code"] == code, obj
        return obj

    def balance(self, account):
        return self.ok("balance", "--account", account)["data"]["balance"]

    def max_tx_id(self):
        import sqlite3
        conn = sqlite3.connect(self.home / "finance.db")
        try:
            return conn.execute("SELECT COALESCE(MAX(id), 0) FROM transactions").fetchone()[0]
        finally:
            conn.close()

    def count_tx(self):
        import sqlite3
        conn = sqlite3.connect(self.home / "finance.db")
        try:
            return conn.execute("SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL").fetchone()[0]
        finally:
            conn.close()


@pytest.fixture(autouse=True)
def _never_touch_real_data(tmp_path, monkeypatch):
    """Pengaman: tanpa FINANCE_HOME, finance.py memakai folder data asli di profil pengguna.

    Setiap tes mendapat FINANCE_HOME sementara, dan profil pengguna (USERPROFILE/HOME) juga diarahkan ke folder
    sementara, supaya tes yang menghapus FINANCE_HOME pun tidak pernah menyentuh data asli.
    """
    profile = tmp_path / "_profil"
    monkeypatch.setenv("FINANCE_HOME", str(tmp_path / "_data"))
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.delenv("FINANCE_NOW", raising=False)


@pytest.fixture
def fin(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_HOME", str(tmp_path))
    monkeypatch.delenv("FINANCE_NOW", raising=False)
    f = Fin(tmp_path)
    f.ok("init")
    return f


@pytest.fixture
def fin_home(tmp_path, monkeypatch):
    """Folder data kosong tanpa init, untuk menyiapkan database sendiri (mis. tes migrasi)."""
    monkeypatch.setenv("FINANCE_HOME", str(tmp_path))
    monkeypatch.delenv("FINANCE_NOW", raising=False)
    return tmp_path, Fin(tmp_path)


@pytest.fixture
def wallets(fin):
    """Dompet tunai 150k (default), bri 500k, gopay 50k, dan tabungan kosong bernama 'tabungan' (target 2jt)."""
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "150k", "--default")
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "500k")
    fin.ok("account", "add", "gopay", "--type", "ewallet", "--opening", "50k")
    fin.ok("savings", "add", "tabungan", "--target", "2jt")
    return fin


def run_subprocess(home, *args, now=DEFAULT_NOW):
    env = dict(os.environ, FINANCE_HOME=str(home), PYTHONIOENCODING="utf-8")
    env.pop("FINANCE_NOW", None)
    proc = subprocess.run([sys.executable, str(ROOT / "finance.py"), "--now", now, *args],
                          capture_output=True, env=env, cwd=str(ROOT))
    out = proc.stdout.decode("utf-8")
    obj = json.loads(out)  # seluruh stdout harus satu objek JSON
    assert proc.returncode == (0 if obj["ok"] else 1)
    return obj
