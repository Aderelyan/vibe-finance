# Pencatat Keuangan Pribadi (backend)

Program CLI `finance.py` dengan database SQLite. Semua perintah membalas **satu objek JSON**:

```json
{"ok": true, "message": "Tercatat pengeluaran ayam goreng Rp15.000 (kategori makan) dari tunai (dompet default). Sisa tunai Rp135.000. Sisa budget makan Rp285.000.", "data": {...}}
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

## Konsep: dompet dan budget (sistem amplop)

Uang yang sama dilihat dari dua sisi:
- **Dompet**: uangnya ada di mana (tunai, bri, gopay).
- **Budget**: uangnya untuk apa (makan, transport, tabungan, `belum teralokasi`).

Total semua dompet selalu sama dengan total semua budget. Pemasukan dan saldo awal masuk ke `belum teralokasi`;
kamu sendiri yang membaginya lewat `budget alloc`. Pengeluaran mengurangi budget kategorinya, atau
`belum teralokasi` jika kategori itu belum punya budget. Tabungan adalah budget, bukan dompet.

## Status

- **Tahap 1 (selesai):** `init`, `account`, `category`, `alias`, `add`, `transfer`, `adjust`, `balance`, `report`, `list`,
  `edit`, `delete`, `undo`, `backup`.
- **Tahap 1.5 (selesai):** budget amplop (`budget list/alloc/move/close/history`), tabungan (`savings`),
  hapus dan ganti nama untuk dompet/kategori/tabungan, repo GitHub.
- **Tahap 2 (selesai):** hutang piutang (`debt add/pay/list/set/rename/remove`) dan tagihan rutin
  (`recurring add/list/pay/set/rename/remove`).
- Belum ada: `analyze`, `daily-check`, `export`, `demo.py` (tahap 3), `COMMANDS.md` (tahap 4).

## Contoh pemakaian

```bat
python finance.py account add tunai --type cash --opening 150k
python finance.py account add bri --type bank --opening 500k
python finance.py add --type income --account bri --item "gajian|600k|gaji"

python finance.py budget alloc --item "makan|300k" --item "transport|100k"
python finance.py savings add "dana darurat" --target 5jt
python finance.py budget alloc --item "dana darurat|100k"
python finance.py budget move --from makan --to jajan --amount 50k

python finance.py add --type expense --item "ayam goreng|15k|makan"
python finance.py add --type expense --item "jajan|10k" --item "es teh|3k"
python finance.py add --type expense --budget "dana darurat" --item "ban bocor|40k|transport"
python finance.py transfer --from bri --to tunai --amount 200k --fee 2.5k
python finance.py adjust --account bri --actual 450k

python finance.py balance
python finance.py budget list
python finance.py savings list
python finance.py report --period this-month --type expense
python finance.py list --period this-month
python finance.py undo

python finance.py account remove gopay --move-to bri
python finance.py category add kucing --kind expense
python finance.py category remove hiburan --kind expense

python finance.py debt add --direction i_owe --person Budi --amount 50k --due 2026-10-20
python finance.py debt add --direction owed_to_me --person Andi --amount 100k
python finance.py debt pay --person Budi --amount 20k
python finance.py debt pay --person Andi --amount all
python finance.py debt list

python finance.py recurring add kos --amount 500k --day 5 --account bri
python finance.py recurring pay kos
python finance.py recurring list
```

- `--item` berformat `catatan|jumlah|kategori`; kategori boleh dikosongkan (ditebak dari kata kunci, atau `lainnya`).
- Nominal: `15000`, `15.000`, `15k`, `15rb`, `15 ribu`, `1,5jt`, `2 juta`, `Rp15.000`.
  Nilai negatif untuk `--opening`/`--actual` ditulis dengan tanda sama dengan: `--opening=-5k`.
- Periode: `today`, `yesterday`, `this-week`, `last-week`, `this-month`, `last-month`, `2026-08`, `last:3`, `all`,
  atau `--from 2026-08-01 --to 2026-08-31`.
- Tanggal transaksi: `--date 2026-10-05`, `--date yesterday`.
- Hapus dompet yang masih berisi butuh `--move-to <dompet>` atau `--write-off`.
- Hutang: `i_owe` = saya pinjam (uang masuk), `owed_to_me` = orang pinjam ke saya (uang keluar). Jika satu orang punya
  beberapa hutang terbuka, sebutkan `--id` (lihat `debt list`). `--no-cash` = tanpa uang masuk/keluar dompet.
- Tagihan rutin: `recurring pay` mencatat pengeluaran untuk bulan berjalan; `--month 2026-09` untuk bulan lain.
- `python finance.py <perintah> --help` menampilkan semua opsi (juga dalam JSON).

## Tes

```bat
.venv\Scripts\python -m pytest -q
```
