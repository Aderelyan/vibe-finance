"""Folder data bawaan finance.py = <profil pengguna>/Documents/Manager/Finance/data, sama dengan fin.sh.

conftest._never_touch_real_data sudah mengarahkan USERPROFILE/HOME ke folder sementara, jadi tes ini tidak pernah
menyentuh data asli walau FINANCE_HOME dihapus.
"""
import json
import re
import subprocess
import sys

from conftest import DEFAULT_NOW, ROOT
from fin import db
from fin.cli import execute

PARTS = ("Documents", "Manager", "Finance", "data")


def test_default_uses_userprofile(tmp_path, monkeypatch):
    monkeypatch.delenv("FINANCE_HOME")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    expected = tmp_path.joinpath("profil", *PARTS)
    assert db.home() == expected
    code, obj = execute(["--now", DEFAULT_NOW, "init"])
    assert code == 0 and obj["data"]["path"] == str(expected / "finance.db")
    assert (expected / "finance.db").exists()
    assert not (ROOT / "data" / "finance.db").exists()  # bukan lagi folder data\ di dalam project


def test_default_without_userprofile_uses_home(tmp_path, monkeypatch):
    """Linux/Mac: tidak ada USERPROFILE, jadi ~/Documents/Manager/Finance/data."""
    monkeypatch.delenv("FINANCE_HOME")
    monkeypatch.delenv("USERPROFILE")
    monkeypatch.setenv("HOME", str(tmp_path / "rumah"))
    assert db.home() == tmp_path.joinpath("rumah", *PARTS)


def test_finance_home_wins_and_empty_means_default(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("FINANCE_HOME", str(tmp_path / "lain"))
    assert db.home() == tmp_path / "lain"
    monkeypatch.setenv("FINANCE_HOME", "")
    assert db.home() == tmp_path.joinpath("profil", *PARTS)


def test_subprocess_default(tmp_path, monkeypatch):
    """Lewat proses baru (seperti dipanggil program lain), tetap memakai profil pengguna."""
    monkeypatch.delenv("FINANCE_HOME")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    proc = subprocess.run([sys.executable, str(ROOT / "finance.py"), "--now", DEFAULT_NOW, "init"],
                          capture_output=True, cwd=str(tmp_path))
    obj = json.loads(proc.stdout.decode("utf-8"))
    assert obj["data"]["path"] == str(tmp_path.joinpath("profil", *PARTS, "finance.db"))


def test_fin_sh_uses_same_rule():
    """Pemeriksaan statis yang tetap jalan tanpa bash: urutan profil dan sub-folder fin.sh sama dengan db.py."""
    script = (ROOT / "fin.sh").read_text(encoding="utf-8")
    assert 'profile="${USERPROFILE:-$HOME}"' in script
    assert re.search(r'FINANCE_HOME="\$\(to_windows_path "\$profile"\)/' + "/".join(PARTS) + '"', script)
    for text in (script, (ROOT / "fin" / "db.py").read_text(encoding="utf-8")):
        assert not re.search(r"[A-Za-z]:[\\/]+Users[\\/]", text), "jangan tulis path profil pengguna di repo"
