"""fin.sh lewat bash MSYS (Git Bash). Dilewati jika tidak ada bash MSYS.

bash dicari dari env FIN_TEST_BASH, PATH, lalu instalasi git (usr/bin/bash.exe atau sh.exe). Bash WSL tidak dipakai
karena fin.sh ditujukan untuk MSYS.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import DEFAULT_NOW, ROOT

SCRIPT = ROOT / "fin.sh"


def _is_msys(exe):
    try:
        out = subprocess.run([exe, "-c", "uname -s"], capture_output=True, timeout=20).stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return any(tag in out for tag in ("MSYS", "MINGW", "CYGWIN"))


def find_msys_bash():
    candidates = [os.environ.get("FIN_TEST_BASH"), shutil.which("bash"), shutil.which("sh")]
    git = shutil.which("git")
    if git:
        for parent in Path(git).resolve().parents:
            candidates += [str(parent / "usr" / "bin" / "bash.exe"), str(parent / "bin" / "bash.exe"),
                           str(parent / "usr" / "bin" / "sh.exe")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(str(Path(base) / "Git" / "bin" / "bash.exe"))
            candidates.append(str(Path(base) / "Programs" / "Git" / "bin" / "bash.exe"))
    for c in candidates:
        if c and Path(c).is_file() and _is_msys(c):
            return c
    return None


BASH = find_msys_bash() if sys.platform == "win32" else None
pytestmark = pytest.mark.skipif(BASH is None, reason="bash MSYS/Git Bash tidak ditemukan")


def run(*args, home=None, cwd=None, stdin=None, env_extra=None, script=SCRIPT, now=True):
    env = {k: v for k, v in os.environ.items() if k not in ("FINANCE_HOME", "FINANCE_NOW")}
    if home is not None:
        env["FINANCE_HOME"] = str(home)
    env.update(env_extra or {})
    argv = [BASH, script.as_posix(), *(["--now", DEFAULT_NOW] if now else []), *args]
    proc = subprocess.run(argv, capture_output=True, env=env, cwd=str(cwd) if cwd else None,
                          input=stdin.encode("utf-8") if stdin is not None else None, timeout=60)
    out = proc.stdout.decode("utf-8")
    obj = json.loads(out)  # seluruh stdout harus tepat satu objek JSON
    assert out.count("\n") <= 1 and out.strip().startswith("{")
    return proc.returncode, obj


def test_called_from_other_folder_with_tricky_args(tmp_path):
    home = tmp_path / "data"
    elsewhere = tmp_path / "lain"
    elsewhere.mkdir()
    code, obj = run("account", "add", "tunai utama", "--type", "cash", "--opening", "150k", home=home, cwd=elsewhere)
    assert code == 0 and obj["data"]["account"]["name"] == "tunai utama"
    code, obj = run("add", "--type", "expense", "--item", "ayam goreng é|15k|makan", "--item", "kopi|8k",
                    "--raw", "/c/bukan/path a|b; $HOME `x`", home=home, cwd=elsewhere)
    assert code == 0 and obj["data"]["total"] == 23_000 and "é" in obj["message"]
    code, obj = run("list", "--search", "ayam", home=home)
    assert obj["data"]["transactions"][0]["raw_text"] == "/c/bukan/path a|b; $HOME `x`"
    code, obj = run("adjust", "--account", "tunai utama", "--actual=-5k", home=home)
    assert code == 0 and obj["data"]["after"] == -5_000
    assert (home / "finance.db").exists()


def test_error_exit_code(tmp_path):
    code, obj = run("balance", "--account", "bca", home=tmp_path)
    assert code == 1 and obj["error"]["code"] == "UNKNOWN_ACCOUNT"
    code, obj = run("terbang", home=tmp_path)
    assert code == 1 and obj["error"]["code"] == "BAD_ARGS"


def test_stdin_batch_and_relative_file(tmp_path):
    home = tmp_path / "data"
    run("account", "add", "tunai", "--type", "cash", "--opening", "100k", home=home)
    batch = json.dumps([{"cmd": "add", "args": {"type": "expense", "item": "es teh ☕|3k"}},
                        {"cmd": "budget alloc", "args": {"item": "makan|50k"}}], ensure_ascii=False)
    code, obj = run("batch", "--stdin", home=home, stdin=batch)
    assert code == 0 and obj["data"]["count"] == 2 and "☕" in obj["message"]
    # path relatif tetap relatif ke folder pemanggil
    (tmp_path / "b.json").write_text(batch, encoding="utf-8")
    code, obj = run("batch", "--file", "b.json", home=home, cwd=tmp_path)
    assert code == 0 and obj["data"]["source"] == "b.json"


def test_finance_home_default_and_posix_form(tmp_path):
    profile = tmp_path / "profil"
    code, obj = run("init", env_extra={"USERPROFILE": str(profile)})
    expected = profile / "Documents" / "Manager" / "Finance" / "data" / "finance.db"
    assert code == 0 and Path(obj["data"]["path"]) == expected and expected.exists()

    # FINANCE_HOME yang sudah diisi tidak ditimpa, termasuk bentuk /c/... dari MSYS
    drive, rest = str(tmp_path / "posix").split(":", 1)
    posix = "/" + drive.lower() + rest.replace("\\", "/")
    code, obj = run("init", env_extra={"FINANCE_HOME": posix, "USERPROFILE": str(profile)})
    assert Path(obj["data"]["path"]) == tmp_path / "posix" / "finance.db"


def test_default_home_same_as_finance_py(tmp_path):
    """Tanpa FINANCE_HOME, fin.sh dan finance.py langsung membuka database yang sama."""
    profile = tmp_path / "profil"
    code, via_sh = run("init", env_extra={"USERPROFILE": str(profile)})
    env = {k: v for k, v in os.environ.items() if k != "FINANCE_HOME"}
    env["USERPROFILE"] = str(profile)
    proc = subprocess.run([sys.executable, str(ROOT / "finance.py"), "--now", DEFAULT_NOW, "init"],
                          capture_output=True, env=env, cwd=str(tmp_path))
    direct = json.loads(proc.stdout.decode("utf-8"))
    assert Path(via_sh["data"]["path"]) == Path(direct["data"]["path"])
    assert Path(direct["data"]["path"]) == profile / "Documents" / "Manager" / "Finance" / "data" / "finance.db"
    assert direct["data"]["created"] is False  # database yang sudah dibuat lewat fin.sh


def test_finance_home_msys_mount_path(tmp_path):
    """/tmp/... adalah mount MSYS, bukan C:/tmp. Data harus sampai di folder yang sama dengan yang dilihat bash."""
    name = f"fin-sh-test-{os.getpid()}-{tmp_path.name}"
    real = subprocess.run([BASH, "-c", "cd /tmp && pwd -W"], capture_output=True).stdout.decode().strip()
    assert real
    target = Path(real) / name / "data"
    try:
        code, obj = run("init", env_extra={"FINANCE_HOME": f"/tmp/{name}/data"})
        assert code == 0 and Path(obj["data"]["path"]) == target / "finance.db" and (target / "finance.db").exists()
    finally:
        shutil.rmtree(Path(real) / name, ignore_errors=True)


def test_missing_venv_gives_json(tmp_path):
    copy = tmp_path / "tanpa venv"
    copy.mkdir()
    shutil.copy(SCRIPT, copy / "fin.sh")
    code, obj = run("context", home=tmp_path, script=copy / "fin.sh", now=False)
    assert code == 1 and obj["ok"] is False and obj["error"]["code"] == "INTERNAL"
    assert ".venv" in obj["error"]["message"] and "pip install -r requirements.txt" in obj["error"]["hint"]


def test_script_has_lf_line_endings():
    assert b"\r\n" not in SCRIPT.read_bytes()
