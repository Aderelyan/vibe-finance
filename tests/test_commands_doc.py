"""COMMANDS.md harus cocok persis dengan CLI: setiap perintah dan opsi terdokumentasi, setiap perintah di dokumen
ada, dan setiap contoh (termasuk contoh batch) menghasilkan output yang tertulis."""
import json
import re
import shlex
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))

import commands_doc  # noqa: E402
from fin.cli import build_parser  # noqa: E402
from fin.output import ERROR_CODES  # noqa: E402

TEXT = commands_doc.DOC.read_text(encoding="utf-8")


def leaf_commands(parser=None, path=()):
    """{'account add': subparser, 'add': subparser, ...}"""
    parser = parser or build_parser()
    subs = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    if not subs:
        return {" ".join(path): parser}
    result = {}
    for name, child in subs[0].choices.items():
        result.update(leaf_commands(child, path + (name,)))
    return result


def sections():
    """{'account add': teks bagian} dari heading ### `...`"""
    parts = re.split(r"^### `([^`]+)`[ \t]*$", TEXT, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def test_every_cli_command_and_option_is_documented():
    docs = sections()
    leaves = leaf_commands()
    assert set(docs) == set(leaves), (set(leaves) - set(docs), set(docs) - set(leaves))
    for name, parser in leaves.items():
        body = docs[name]
        for action in parser._actions:
            if action.dest == "help":
                continue
            if action.option_strings:
                for opt in action.option_strings:
                    assert re.search(re.escape(opt) + r"(?![\w-])", body), f"{name}: opsi {opt} tidak didokumentasikan"
                if action.choices:
                    for choice in action.choices:
                        assert choice in body, f"{name}: pilihan {choice} untuk {action.option_strings[0]} tidak ada"
            else:
                assert f"<{action.dest}>" in body, f"{name}: argumen <{action.dest}> tidak didokumentasikan"
        examples = [commands_doc.example_argv(i, b) for i, b, _s, _e in commands_doc.blocks(body)]
        assert any(e for e in examples), f"{name}: tidak ada contoh pemanggilan"
        assert re.search(r"^Error: ", body, flags=re.M), f"{name}: tidak ada daftar error"


def test_error_codes_documented():
    table = TEXT.split("### Kode error", 1)[1].split("\n\n", 2)[1]
    documented = set(re.findall(r"^\| `([A-Z_]+)` \|", table, flags=re.M))
    assert documented == ERROR_CODES
    for line in re.findall(r"^Error: .*(?:\n(?!\n).*)*", TEXT, flags=re.M):
        for code in re.findall(r"`([A-Z][A-Z_]+)`", line):
            assert code in ERROR_CODES, f"kode error tidak dikenal di dokumen: {code}"


def test_examples_match_doc(tmp_path):
    results = commands_doc.run(TEXT, tmp_path / "data")
    assert len(results) >= len(leaf_commands())
    for argv, actual, out_block, _ex in results:
        label = "python finance.py " + " ".join(argv)
        assert out_block is not None, f"{label}: tidak ada blok output, jalankan tools\\commands_doc.py"
        documented = json.loads(out_block[1])
        assert commands_doc.matches(documented, actual), (
            f"{label}: output di COMMANDS.md tidak cocok lagi dengan kode. Jalankan tools\\commands_doc.py "
            f"lalu periksa perubahannya.\nDokumen: {json.dumps(documented, ensure_ascii=False)[:500]}\n"
            f"Asli: {json.dumps(actual, ensure_ascii=False)[:500]}")
    batch_runs = [(a, o) for a, o, _n, _e in results if a[0] == "batch"]
    assert batch_runs and any(o["ok"] for _a, o in batch_runs), "contoh batch harus ada dan ada yang berhasil"
    for argv, obj in batch_runs:
        if obj["ok"]:
            assert obj["data"]["group_id"] and obj["data"]["count"] >= 2


def _mapping_rows():
    part = TEXT.split("## Cara memetakan chat ke perintah", 1)[1]
    rows = []
    for line in part.splitlines():
        cells = re.split(r"(?<!\\)\|", line.strip())[1:-1]
        if len(cells) == 2 and cells[0].strip() not in ("Chat", "---"):
            rows.append((cells[0].strip(), cells[1].strip().replace("\\|", "|")))
    return rows


def _command_of(cell):
    m = re.fullmatch(r"`([^`]+)`", cell)
    return shlex.split(m.group(1)) if m else None


@pytest.mark.parametrize("chat, cell", _mapping_rows())
def test_chat_mapping_commands_exist(chat, cell):
    argv = _command_of(cell)
    assert argv, f"'{chat}': kolom perintah harus satu perintah dalam backtick"
    args = build_parser().parse_args(argv)  # melempar FinError BAD_ARGS jika perintah/opsi tidak ada
    assert callable(args.func)


def test_mapping_covers_required_scenarios():
    """Semua skenario wajib di BLUEPRINT bagian 9 ada di tabel pemetaan chat."""
    blueprint = (ROOT / "BLUEPRINT.md").read_text(encoding="utf-8")
    table = blueprint.split("**Skenario wajib lolos**", 1)[1].split("\n## ", 1)[0]
    mapped = {" ".join(_command_of(cell) or []) for _chat, cell in _mapping_rows()}
    required = []
    for line in table.splitlines():
        cells = re.split(r"(?<!\\)\|", line.strip())[1:-1]
        if len(cells) == 2 and cells[1].strip().startswith("`"):
            cmd = re.match(r"`([^`]+)`", cells[1].strip().replace("\\|", "|")).group(1)
            required.append(" ".join(shlex.split(cmd)))
    assert len(required) >= 25
    missing = [r for r in required if not any(m == r or m.startswith(r + " ") for m in mapped)]
    assert not missing, f"skenario wajib belum ada di tabel pemetaan: {missing}"


def test_every_documented_command_line_parses():
    """Setiap `python finance.py ...` di dokumen (termasuk di teks) memakai perintah dan opsi yang ada."""
    lines = re.findall(r"python finance\.py ([^\n`]+)", TEXT)
    assert len(lines) > 60
    for line in lines:
        argv = shlex.split(line.replace("<perintah>", "init").replace(" --help", ""))
        if not argv or argv[0].startswith("<") or "--help" in line or "[" in line:
            continue
        build_parser().parse_args(argv)
