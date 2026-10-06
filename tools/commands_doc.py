"""Contoh di COMMANDS.md dijalankan sungguhan, supaya dokumen selalu cocok dengan perilaku kode.

Aturan blok di COMMANDS.md:
- Blok ```bat berisi tepat satu baris `python finance.py ...` adalah contoh yang dijalankan.
- Blok ```json tepat setelahnya adalah output contoh itu (diisi oleh skrip ini).
- Blok ```json file=NAMA ditulis ke file NAMA di folder kerja sebelum contoh berikutnya dijalankan.
Semua contoh dijalankan berurutan pada database baru dengan waktu tetap NOW.

Perbarui output di dokumen:  .venv\\Scripts\\python tools\\commands_doc.py
Tes (tests/test_commands_doc.py) menjalankan ulang semua contoh dan membandingkannya dengan dokumen.
"""
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fin.cli import execute  # noqa: E402

DOC = ROOT / "COMMANDS.md"
NOW = "2026-10-06 12:00:00"
HOME_MARK = "<FINANCE_HOME>"
RANDOM_MARK = "<acak>"
RANDOM_KEYS = {"group_id"}
MAX_LIST = 3

FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.S | re.M)


def blocks(text):
    """[(info, body, start, end)] untuk setiap blok kode, berurutan."""
    return [(m.group(1).strip(), m.group(2), m.start(), m.end()) for m in FENCE.finditer(text)]


def example_argv(info, body):
    """argv (tanpa 'python finance.py') jika blok ini contoh yang dijalankan, selain itu None."""
    if info != "bat":
        return None
    lines = [ln for ln in body.strip().splitlines() if ln.strip()]
    if len(lines) != 1 or not lines[0].startswith("python finance.py"):
        return None
    return shlex.split(lines[0])[2:]


def normalize(obj, home, trim):
    """Ganti path folder data dan nilai acak dengan penanda; potong daftar panjang jika trim."""
    if isinstance(obj, dict):
        return {k: (RANDOM_MARK if k in RANDOM_KEYS and v is not None else normalize(v, home, trim))
                for k, v in obj.items()}
    if isinstance(obj, list):
        items = obj[:MAX_LIST] if trim else obj
        return [normalize(v, home, trim) for v in items]
    if isinstance(obj, str):
        return obj.replace(str(home), HOME_MARK)
    return obj


def run(text, home):
    """Jalankan semua contoh di folder home. Kembalikan [(argv, output_ternormalisasi_tanpa_potong, blok_output)].

    blok_output = (info, body, start, end) dari blok json setelah contoh, atau None jika belum ada.
    """
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    old_env, old_cwd = os.environ.get("FINANCE_HOME"), os.getcwd()
    os.environ["FINANCE_HOME"] = str(home)
    os.environ.pop("FINANCE_NOW", None)
    os.chdir(home)
    results = []
    try:
        bl = blocks(text)
        for i, (info, body, _s, _e) in enumerate(bl):
            m = re.fullmatch(r"json\s+file=(\S+)", info)
            if m:
                (home / m.group(1)).write_text(body, encoding="utf-8")
                continue
            argv = example_argv(info, body)
            if argv is None:
                continue
            _code, obj = execute(["--now", NOW, *argv])
            nxt = bl[i + 1] if i + 1 < len(bl) and bl[i + 1][0] == "json" else None
            results.append((argv, normalize(obj, home, trim=False), nxt, bl[i]))
    finally:
        os.chdir(old_cwd)
        if old_env is None:
            os.environ.pop("FINANCE_HOME", None)
        else:
            os.environ["FINANCE_HOME"] = old_env
    return results


def render(obj):
    return json.dumps(_trim(obj), ensure_ascii=False, indent=2)


def _trim(obj):
    if isinstance(obj, dict):
        return {k: _trim(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_trim(v) for v in obj[:MAX_LIST]]
    return obj


def matches(doc, actual):
    """True jika output di dokumen cocok dengan output asli. Daftar di dokumen boleh dipotong (awalan)."""
    if doc == RANDOM_MARK:
        return actual is not None
    if isinstance(doc, dict):
        return isinstance(actual, dict) and doc.keys() == actual.keys() and all(
            matches(v, actual[k]) for k, v in doc.items())
    if isinstance(doc, list):
        return (isinstance(actual, list) and len(doc) <= len(actual)
                and (len(doc) == len(actual) or len(doc) == MAX_LIST)
                and all(matches(d, a) for d, a in zip(doc, actual)))
    return doc == actual


def update(path=DOC):
    text = path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="commands-doc-") as tmp:
        results = run(text, Path(tmp) / "data")
    out, pos = [], 0
    for _argv, obj, nxt, ex in results:
        rendered = "```json\n" + render(obj) + "\n```"
        if nxt is None:
            out.append(text[pos:ex[3]] + "\n" + rendered)
            pos = ex[3]
        else:
            out.append(text[pos:nxt[2]] + rendered)
            pos = nxt[3]
    out.append(text[pos:])
    path.write_text("".join(out), encoding="utf-8", newline="\n")
    failed = [" ".join(a) for a, o, _n, _e in results if not o["ok"]]
    print(f"{len(results)} contoh dijalankan, {len(failed)} berakhir error (periksa apakah memang disengaja):")
    for f in failed:
        print("  -", f)


if __name__ == "__main__":
    update()
