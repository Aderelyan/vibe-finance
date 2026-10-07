"""Demo: database baru di folder sementara, skenario dua bulan (Agustus-September 2026), lalu cetak hasilnya.

Termasuk tabungan terpisah: menabung tiap bulan dan satu belanja langsung dari tabungan.

Jalankan: python demo.py
Angka akhirnya diperiksa oleh tests/test_demo.py.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fin.cli import execute  # noqa: E402

END = "2026-09-30 21:00:00"   # "sekarang" di akhir demo

OPENING = {"tunai": 200_000, "bri": 1_500_000}
SALARY = 2_000_000            # gajian tanggal 1 tiap bulan, ke bri
ALLOC = [("makan", 900_000), ("jajan", 200_000), ("transport", 300_000), ("tempat tinggal", 600_000),
         ("pulsa & internet", 150_000)]
SAVINGS = "dana darurat"        # tabungan: akun terpisah dari dompet dan budget
DEPOSIT = 300_000               # menabung tanggal 1 tiap bulan dari bri (budget 'belum teralokasi' berkurang)
SAVINGS_SPEND = ("2026-09-22", "servis motor", 250_000, "transport")   # belanja langsung dari tabungan
BILLS = [("kos", 600_000, 5), ("wifi", 150_000, 10)]   # dibayar dari bri tanggal jatuh temponya
WITHDRAW = (500_000, 2_500)  # tarik tunai dari bri tanggal 3 tiap bulan, beserta biaya admin

# (tanggal, catatan, nominal, kategori); semua dari tunai
EXPENSES = [
    ("2026-08-02", "nasi padang", 25_000, "makan"),
    ("2026-08-04", "bensin", 30_000, "transport"),
    ("2026-08-06", "ayam geprek", 18_000, "makan"),
    ("2026-08-07", "es teh", 5_000, "jajan"),
    ("2026-08-09", "sabun dan sampo", 42_000, "belanja"),
    ("2026-08-11", "bakso", 20_000, "makan"),
    ("2026-08-13", "parkir", 2_000, "transport"),
    ("2026-08-16", "nonton bioskop", 50_000, "hiburan"),
    ("2026-08-18", "warteg", 15_000, "makan"),
    ("2026-08-22", "ojol ke kampus", 24_000, "transport"),
    ("2026-08-25", "obat flu", 35_000, "kesehatan"),
    ("2026-08-28", "makan malam", 45_000, "makan"),
    ("2026-09-02", "kopi", 8_000, "jajan"),
    ("2026-09-03", "nasi padang", 27_000, "makan"),
    ("2026-09-04", "kopi", 8_000, "jajan"),
    ("2026-09-06", "bensin", 30_000, "transport"),
    ("2026-09-08", "kopi", 8_000, "jajan"),
    ("2026-09-09", "soto", 20_000, "makan"),
    ("2026-09-11", "kopi", 8_000, "jajan"),
    ("2026-09-12", "fotokopi", 6_000, "pendidikan"),
    ("2026-09-15", "kopi", 8_000, "jajan"),
    ("2026-09-17", "sate", 35_000, "makan"),
    ("2026-09-19", "kopi", 8_000, "jajan"),
    ("2026-09-21", "buku", 85_000, "pendidikan"),
    ("2026-09-24", "ojol", 22_000, "transport"),
    ("2026-09-27", "sedekah jumat", 20_000, "sedekah"),
    ("2026-09-29", "mie ayam", 15_000, "makan"),
]
DEBT_BUDI = ("2026-08-12", 300_000, "2026-10-05")     # pinjam dari Budi ke bri, jatuh tempo
PAY_BUDI = ("2026-08-20", 100_000)                    # bayar dari bri
DEBT_ANDI = ("2026-08-15", 150_000, "2026-10-03")     # Andi pinjam dari tunai
PAY_ANDI = ("2026-09-14", 50_000)                     # Andi bayar ke tunai
PAID_FOR = ("2026-09-20", 35_000, "makan siang", "makan")   # Citra membayari makan siang
MOVE = ("2026-09-25", "jajan", "makan", 50_000)


def _ts(day, hour="12:00:00"):
    return f"{day} {hour}"


class Runner:
    def __init__(self):
        self.log = []

    def __call__(self, now, *args):
        code, obj = execute(["--now", now, *[str(a) for a in args]])
        if not obj["ok"]:
            raise RuntimeError(f"Demo gagal pada {' '.join(map(str, args))}: {obj['error']}")
        self.log.append((args, obj))
        return obj


def run_demo(home):
    """Jalankan skenario di folder home. Kembalikan hasil perintah ringkasan (dict nama -> objek JSON)."""
    old = os.environ.get("FINANCE_HOME")
    os.environ["FINANCE_HOME"] = str(home)
    try:
        return _scenario(Runner())
    finally:
        if old is None:
            os.environ.pop("FINANCE_HOME", None)
        else:
            os.environ["FINANCE_HOME"] = old


def _scenario(run):
    start = _ts("2026-08-01", "07:00:00")
    run(start, "init")
    run(start, "account", "add", "tunai", "--type", "cash", "--opening", OPENING["tunai"], "--default")
    run(start, "account", "add", "bri", "--type", "bank", "--opening", OPENING["bri"])
    run(start, "savings", "add", SAVINGS, "--target", "3jt", "--target-date", "2027-06-30")
    for name, amount, day in BILLS:
        run(start, "recurring", "add", name, "--amount", amount, "--day", day, "--account", "bri")

    for month in ("2026-08", "2026-09"):
        now = _ts(f"{month}-01", "08:00:00")
        run(now, "add", "--type", "income", "--account", "bri", "--item", f"gajian|{SALARY}|gaji")
        run(now, "budget", "alloc", *[x for name, amt in ALLOC for x in ("--item", f"{name}|{amt}")])
        run(now, "savings", "deposit", "--from", "bri", "--to", SAVINGS, "--amount", DEPOSIT)
        run(_ts(f"{month}-03"), "transfer", "--from", "bri", "--to", "tunai", "--amount", WITHDRAW[0],
            "--fee", WITHDRAW[1])
        for name, _amount, day in BILLS:
            run(_ts(f"{month}-{day:02d}", "09:00:00"), "recurring", "pay", name)

    for day, note, amount, cat in EXPENSES:
        run(_ts(day, "19:00:00"), "add", "--type", "expense", "--item", f"{note}|{amount}|{cat}")

    run(_ts(DEBT_BUDI[0]), "debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", DEBT_BUDI[1],
        "--account", "bri", "--due", DEBT_BUDI[2], "--note", "uang buku")
    run(_ts(PAY_BUDI[0]), "debt", "pay", "--person", "Budi", "--amount", PAY_BUDI[1], "--account", "bri")
    run(_ts(DEBT_ANDI[0]), "debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount",
        DEBT_ANDI[1], "--due", DEBT_ANDI[2])
    run(_ts(PAY_ANDI[0]), "debt", "pay", "--person", "Andi", "--amount", PAY_ANDI[1])
    run(_ts(PAID_FOR[0]), "debt", "add", "--direction", "i_owe", "--person", "Citra", "--amount", PAID_FOR[1],
        "--paid-for", f"{PAID_FOR[2]}|{PAID_FOR[3]}")
    run(_ts(MOVE[0]), "budget", "move", "--from", MOVE[1], "--to", MOVE[2], "--amount", MOVE[3])
    day, note, amount, cat = SAVINGS_SPEND
    run(_ts(day), "savings", "spend", "--from", SAVINGS, "--item", f"{note}|{amount}|{cat}", "--mode", "purpose")

    results = {}
    for key, args in [("balance", ["balance"]),
                      ("report", ["report", "--period", "last:2", "--type", "all"]),
                      ("budget", ["budget", "list"]),
                      ("savings", ["savings", "list"]),
                      ("debts", ["debt", "list"]),
                      ("recurring", ["recurring", "list"]),
                      ("analyze", ["analyze", "--period", "this-month"]),
                      ("export", ["export", "--period", "last:2"])]:
        results[key] = run(END, *args)
    return results


TITLES = [("balance", "SALDO"), ("report", "LAPORAN AGUSTUS-SEPTEMBER"), ("budget", "BUDGET"),
          ("savings", "TABUNGAN"), ("debts", "HUTANG PIUTANG"), ("recurring", "TAGIHAN RUTIN"),
          ("analyze", "ANALISIS SEPTEMBER"), ("export", "EKSPOR EXCEL")]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    home = Path(tempfile.mkdtemp(prefix="vibe-finance-demo-"))
    results = run_demo(home)
    print(f"Demo memakai database sementara di {home}")
    print(f"Skenario: 1 Agustus - 30 September 2026, waktu akhir {END}.\n")
    for key, title in TITLES:
        print(f"===== {title} =====")
        print(results[key]["message"])
        print()
    print(f"Buka file Excel ini: {results['export']['data']['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
