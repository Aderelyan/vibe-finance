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
        return obj

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

    def count_tx(self):
        import sqlite3
        conn = sqlite3.connect(self.home / "finance.db")
        try:
            return conn.execute("SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL").fetchone()[0]
        finally:
            conn.close()


@pytest.fixture
def fin(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_HOME", str(tmp_path))
    monkeypatch.delenv("FINANCE_NOW", raising=False)
    f = Fin(tmp_path)
    f.ok("init")
    return f


@pytest.fixture
def wallets(fin):
    """tunai 150k (default), bri 500k, gopay 50k, tabungan 0."""
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "150k", "--default")
    fin.ok("account", "add", "bri", "--type", "bank", "--opening", "500k")
    fin.ok("account", "add", "gopay", "--type", "ewallet", "--opening", "50k")
    fin.ok("account", "add", "tabungan", "--type", "savings", "--target", "2jt")
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
