"""Parser argumen dan eksekusi perintah. Setiap jalur keluar menghasilkan satu objek JSON."""
import argparse
import sys

from . import clock
from .commands import register_all
from .db import connect
from .output import FinError, dumps, failure, success


class HelpRequested(Exception):
    def __init__(self, text):
        super().__init__(text)
        self.text = text


class JsonArgumentParser(argparse.ArgumentParser):
    """ArgumentParser yang melempar FinError alih-alih mencetak usage dan keluar."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise FinError("BAD_ARGS", f"Argumen tidak sah: {message}",
                       hint=f"Lihat bantuan: python {self.prog} --help")

    def print_help(self, file=None):
        raise HelpRequested(self.format_help())

    def print_usage(self, file=None):
        raise HelpRequested(self.format_usage())

    def exit(self, status=0, message=None):
        raise FinError("BAD_ARGS", message or "Argumen tidak sah.")


def build_parser():
    parser = JsonArgumentParser(prog="finance.py", description="Pencatat keuangan pribadi (output JSON).")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<perintah>")
    register_all(sub)
    return parser


def _extract_now(argv):
    """Ambil opsi tersembunyi --now dari posisi mana pun."""
    rest, now_text, i = [], None, 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--now":
            if i + 1 >= len(argv):
                raise FinError("BAD_ARGS", "--now butuh nilai.", hint='Contoh: --now "2026-10-06 14:30:00"')
            now_text = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--now="):
            now_text = arg[len("--now="):]
        else:
            rest.append(arg)
        i += 1
    return rest, now_text


def execute(argv=None):
    """Jalankan satu perintah. Kembalikan (exit_code, objek_json)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    conn = None
    try:
        argv, now_text = _extract_now(argv)
        clock.set_override(now_text)
        args = build_parser().parse_args(argv)
        conn = connect()
        return 0, args.func(args, conn)
    except HelpRequested as h:
        return 0, success(h.text, {"help": h.text})
    except FinError as e:
        return 1, failure(e)
    except Exception as e:  # noqa: BLE001 - semua error tetap harus berbentuk JSON
        return 1, {"ok": False, "error": {
            "code": "INTERNAL",
            "message": f"Terjadi kesalahan internal: {type(e).__name__}: {e}",
            "hint": "Perubahan dibatalkan. Laporkan pesan ini ke pengembang."}}
    finally:
        if conn is not None:
            conn.close()
        clock.set_override(None)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    code, obj = execute(argv)
    print(dumps(obj))
    return code
