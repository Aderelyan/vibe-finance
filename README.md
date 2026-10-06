# Pencatat Keuangan Pribadi (backend)

Program CLI `finance.py` dengan database SQLite. Semua perintah membalas **satu objek JSON**:

```json
{"ok": true, "message": "Tercatat pengeluaran ayam goreng Rp15.000 (kategori makan) dari tunai (dompet default). Sisa tunai Rp135.000.", "data": {...}}
{"ok": false, "error": {"code": "UNKNOWN_ACCOUNT", "message": "Dompet 'bca' tidak ada.", "hint": "Pilihan: tunai, bri"}}
```

Exit code 0 jika berhasil, 1 jika gagal.

## Persiapan (sekali saja)

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
python finance.py init
```

Data disimpan di folder `data\` (`finance.db`, `backups\`). Untuk memakai folder lain, set `FINANCE_HOME`.
Backup otomatis dibuat pada operasi tulis pertama setiap hari, 30 file terakhir disimpan.

## Status

**Tahap 1 (selesai):** `init`, `account`, `category`, `alias`, `add`, `transfer`, `adjust`, `balance`,
`report`, `list`, `edit`, `delete`, `undo`, `backup`.

Belum ada: `debt`, `budget`, `savings`, `recurring` (tahap 2), `analyze`, `daily-check`, `export`, `demo.py` (tahap 3),
`COMMANDS.md` (tahap 4).

## Contoh pemakaian

```bat
python finance.py account add tunai --type cash --opening 150k --default
python finance.py account add bri --type bank --opening 500k
python finance.py account add tabungan --type savings --target 2jt

python finance.py add --type expense --item "ayam goreng|15k|makan"
python finance.py add --type expense --item "jajan|10k" --item "es teh|3k"
python finance.py add --type income --account bri --item "gajian|600k|gaji"
python finance.py transfer --from bri --to tunai --amount 200k --fee 2.5k
python finance.py adjust --account bri --actual 450k

python finance.py balance
python finance.py report --period this-month --type expense
python finance.py list --period this-month
python finance.py undo
```

- `--item` berformat `catatan|jumlah|kategori`; kategori boleh dikosongkan (ditebak dari kata kunci, atau `lainnya`).
- Nominal: `15000`, `15.000`, `15k`, `15rb`, `15 ribu`, `1,5jt`, `2 juta`, `Rp15.000`.
- Periode: `today`, `yesterday`, `this-week`, `last-week`, `this-month`, `last-month`, `2026-08`, `last:3`, `all`,
  atau `--from 2026-08-01 --to 2026-08-31`.
- Tanggal transaksi: `--date 2026-10-05`, `--date yesterday`.
- `python finance.py <perintah> --help` menampilkan semua opsi (juga dalam JSON).

## Tes

```bat
.venv\Scripts\python -m pytest -q
```
