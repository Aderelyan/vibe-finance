"""batch: beberapa perintah pencatatan uang dalam satu transaksi database dan satu group_id.

Format (lihat COMMANDS.md): daftar objek {"cmd": "<perintah>", "args": {<opsi>: <nilai>}}.
Setiap objek diubah menjadi argumen CLI lalu di-parse oleh parser yang sama, jadi validasinya identik.
"""
import json
import sys
from pathlib import Path

from ..db import batch
from ..output import FinError, success

ALLOWED = ["add", "transfer", "adjust", "budget alloc", "budget move", "debt add", "debt pay", "recurring pay",
           "savings deposit", "savings withdraw", "savings spend"]
MAX_COMMANDS = 200
FORMAT_HINT = ('Isi harus daftar JSON, contoh: [{"cmd": "add", "args": {"type": "expense", '
               '"item": ["kopi|8k|jajan"]}}]. Lihat bagian batch di COMMANDS.md.')


def register(sub):
    p = sub.add_parser("batch", help="Jalankan beberapa perintah pencatatan uang sekaligus (semua atau tidak sama "
                                     "sekali, satu undo).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", help="Path file JSON.")
    g.add_argument("--stdin", action="store_true", help="Baca JSON dari stdin (UTF-8).")
    p.set_defaults(func=cmd_batch)


def _read(args):
    if args.stdin:
        stream = sys.stdin
        raw = stream.buffer.read().decode("utf-8-sig") if hasattr(stream, "buffer") else stream.read()
        source = "stdin"
    else:
        path = Path(args.file)
        if not path.is_file():
            raise FinError("BAD_ARGS", f"File batch '{args.file}' tidak ada.", hint=FORMAT_HINT)
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise FinError("BAD_ARGS", f"File batch '{args.file}' bukan teks UTF-8.", hint=FORMAT_HINT)
        source = str(path)
    try:
        return json.loads(raw), source
    except json.JSONDecodeError as e:
        raise FinError("BAD_ARGS", f"JSON tidak sah di baris {e.lineno} kolom {e.colno}: {e.msg}.", hint=FORMAT_HINT)


def _subparser(parser, words):
    for action in parser._actions:  # noqa: SLF001 - argparse tidak menyediakan API publik untuk ini
        if action.__class__.__name__ == "_SubParsersAction":
            child = action.choices.get(words[0])
            if child is None:
                return None
            return child if len(words) == 1 else _subparser(child, words[1:])
    return None


def _value(key, value):
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    raise FinError("BAD_ARGS", f"Nilai '{key}' harus teks, angka bulat, true/false, atau daftar teks.")


def to_argv(parser, entry):
    """{"cmd": "debt pay", "args": {"person": "Budi", "amount": "20k"}} -> ['debt', 'pay', '--person=Budi', ...]"""
    if not isinstance(entry, dict) or set(entry) - {"cmd", "args"} or "cmd" not in entry:
        raise FinError("BAD_ARGS", "Setiap perintah harus objek dengan kunci \"cmd\" dan \"args\".", hint=FORMAT_HINT)
    cmd = entry["cmd"]
    if not isinstance(cmd, str) or " ".join(cmd.split()) not in ALLOWED:
        raise FinError("BAD_ARGS", f"Perintah '{cmd}' tidak bisa dipakai di batch.",
                       hint="Yang boleh: " + ", ".join(ALLOWED) + ".")
    words = cmd.split()
    args = entry.get("args", {})
    if not isinstance(args, dict):
        raise FinError("BAD_ARGS", "\"args\" harus objek, contoh {\"type\": \"expense\"}.", hint=FORMAT_HINT)
    sub = _subparser(parser, words)
    positionals = [a.dest for a in sub._actions if not a.option_strings]  # noqa: SLF001
    argv, pos = list(words), {}
    for key, value in args.items():
        if not isinstance(key, str) or not key or key.startswith("-"):
            raise FinError("BAD_ARGS", f"Nama opsi '{key}' tidak sah; tulis tanpa '--', contoh \"account\".")
        if key in positionals:
            pos[key] = _value(key, value)
            continue
        opt = "--" + key.replace("_", "-")
        if value is None or value is False:
            continue
        if value is True:
            argv.append(opt)
        elif isinstance(value, list):
            argv += [f"{opt}={_value(key, v)}" for v in value]
        else:
            argv.append(f"{opt}={_value(key, value)}")
    missing = [p for p in positionals if p not in pos]
    if missing:
        raise FinError("BAD_ARGS", f"\"args\" untuk {cmd} wajib berisi: {', '.join(missing)}.")
    # positional ditaruh setelah '--' supaya nilai seperti '-5k' tidak dibaca sebagai opsi
    return argv + (["--"] + [pos[p] for p in positionals] if positionals else [])


def cmd_batch(args, conn):
    from ..cli import HelpRequested, build_parser
    entries, source = _read(args)
    if not isinstance(entries, list) or not entries:
        raise FinError("BAD_ARGS", "Isi batch harus daftar berisi minimal satu perintah.", hint=FORMAT_HINT)
    if len(entries) > MAX_COMMANDS:
        raise FinError("BAD_ARGS", f"Batch paling banyak {MAX_COMMANDS} perintah, ini {len(entries)}.")
    parser = build_parser()

    results = []
    with batch(conn) as group:
        for i, entry in enumerate(entries, 1):
            label = entry.get("cmd") if isinstance(entry, dict) else None
            try:
                argv = to_argv(parser, entry)
                try:
                    parsed = parser.parse_args(argv)
                except HelpRequested:
                    raise FinError("BAD_ARGS", "Bantuan (--help) tidak bisa dipakai di batch.")
                out = parsed.func(parsed, conn)
            except FinError as e:
                e.message = f"Perintah ke-{i} ({label or '?'}): {e.message} Tidak ada yang disimpan."
                e.data = {**(e.data or {}), "index": i, "cmd": label}
                raise
            results.append({"index": i, "cmd": " ".join(label.split()), "message": out["message"],
                            "data": out["data"]})
        used = conn.execute("SELECT EXISTS (SELECT 1 FROM transactions WHERE group_id = :g) OR "
                            "EXISTS (SELECT 1 FROM budget_moves WHERE group_id = :g)", {"g": group}).fetchone()[0]
        if not used:  # mis. semua adjust ternyata tanpa selisih
            conn.execute("DELETE FROM op_groups WHERE group_id = ?", (group,))
            group = None

    lines = [f"{r['index']}. {r['message']}" for r in results]
    head = f"{len(results)} perintah dari batch tercatat sekaligus"
    head += " (satu undo membatalkan semuanya):" if group else " (tidak ada perubahan uang):"
    return success(head + "\n" + "\n".join(lines),
                   {"group_id": group, "count": len(results), "source": source, "results": results})
