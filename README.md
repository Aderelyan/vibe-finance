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

Data disimpan di `%USERPROFILE%\Documents\Manager\Finance\data` (`finance.db`, `backups\`, `exports\`); di
Linux/Mac `~/Documents/Manager/Finance/data`. `finance.py` dan `fin.sh` memakai folder yang sama. Untuk memakai
folder lain, set `FINANCE_HOME`.
Backup otomatis dibuat pada operasi tulis pertama setiap hari, 30 file terakhir disimpan.

## Konsep: dompet, budget (sistem amplop), dan tabungan

Uang di dompet dilihat dari dua sisi:
- **Dompet**: uangnya ada di mana (tunai, bri, gopay).
- **Budget**: uangnya untuk apa (makan, transport, `belum teralokasi`).

Total dompet selalu sama dengan total budget. Pemasukan dan saldo awal masuk ke `belum teralokasi`;
kamu sendiri yang membaginya lewat `budget alloc`. Pengeluaran mengurangi budget kategorinya, atau
`belum teralokasi` jika kategori itu belum punya budget.

**Tabungan** adalah akun terpisah, di luar dompet dan budget, dengan saldo dan target sendiri. Menabung
(`savings deposit`) memindahkan uang dari dompet ke tabungan dan mengurangi budget sumbernya; menarik
(`savings withdraw`) kebalikannya. Belanja dari tabungan (`savings spend --mode purpose`) tidak mengurangi dompet
maupun budget dan dilaporkan terpisah. Meminjam dari tabungan (`--mode debt`) dicatat sebagai hutang ke tabungan, dan
baru menjadi pengeluaran saat dikembalikan dengan `debt pay`. `balance` menampilkan total dompet dan total tabungan
sebagai dua angka terpisah.

## Status

- **Tahap 1 (selesai):** `init`, `account`, `category`, `alias`, `add`, `transfer`, `adjust`, `balance`, `report`, `list`,
  `edit`, `delete`, `undo`, `backup`.
- **Tahap 1.5 (selesai):** budget amplop (`budget list/alloc/move/close/history`), tabungan (`savings`),
  hapus dan ganti nama untuk dompet/kategori/tabungan, repo GitHub.
- **Tahap 2 (selesai):** hutang piutang (`debt add/pay/list/set/rename/remove`) dan tagihan rutin
  (`recurring add/list/pay/set/rename/remove`).
- **Tahap 3 (selesai):** `analyze`, `daily-check`, `export` (.xlsx), `demo.py`.
- **Tahap 4 (selesai):** `context`, `batch`, dan [`COMMANDS.md`](COMMANDS.md): referensi lengkap setiap perintah,
  opsi, contoh output asli, kode error, dan cara memetakan chat ke perintah.
- **Perubahan 02 (selesai):** tabungan menjadi akun terpisah di luar budget (`savings deposit/withdraw/spend`),
  skema v4. Lihat [`docs/PERUBAHAN-02.md`](docs/PERUBAHAN-02.md).

## Demo

```bat
python demo.py
```

Membuat database baru di folder sementara, menjalankan skenario Agustus-September 2026 (dua dompet, gaji, alokasi
budget, tabungan, tagihan rutin, hutang, piutang, sekitar 45 transaksi), lalu mencetak saldo, laporan, budget,
tabungan, hutang, tagihan, analisis, dan path file Excel hasil ekspor. Data aslimu di `Documents\Manager\Finance\data` tidak disentuh.

## Contoh pemakaian

```bat
python finance.py account add tunai --type cash --opening 150k
python finance.py account add bri --type bank --opening 500k
python finance.py add --type income --account bri --item "gajian|600k|gaji"

python finance.py budget alloc --item "makan|300k" --item "transport|100k"
python finance.py budget move --from makan --to jajan --amount 50k

python finance.py savings add "dana darurat" --target 5jt
python finance.py savings deposit --from bri --to "dana darurat" --amount 100k
python finance.py savings withdraw --from "dana darurat" --to tunai --amount 30k --to-budget makan
python finance.py savings spend --from "dana darurat" --item "ban bocor|40k|transport" --mode purpose
python finance.py savings spend --from "dana darurat" --item "servis motor|200k|transport" --mode debt
python finance.py debt pay --person "dana darurat" --amount 100k

python finance.py add --type expense --item "ayam goreng|15k|makan"
python finance.py add --type expense --item "jajan|10k" --item "es teh|3k"
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

python finance.py analyze --period this-month
python finance.py daily-check --when pagi
python finance.py export --period this-month

python finance.py context
python finance.py batch --file catatan.json
```

Referensi lengkap semua perintah ada di [COMMANDS.md](COMMANDS.md).

## Dari bash (MSYS / Git Bash)

`fin.sh` membungkus `finance.py` supaya bisa dipanggil dari bash, dari folder mana pun:

```bash
bash C:/path/ke/vibe-finance/fin.sh context
bash C:/path/ke/vibe-finance/fin.sh add --type expense --item "ayam goreng|15k|makan"
bash C:/path/ke/vibe-finance/fin.sh batch --stdin <<'EOF'
[{"cmd": "add", "args": {"type": "expense", "item": "kopi|8k"}}]
EOF
```

Tanpa `FINANCE_HOME`, datanya ada di `<profil pengguna>/Documents/Manager/Finance/data`. Argumen, stdin, dan exit
code diteruskan apa adanya; stdout hanya berisi JSON. Rinciannya di bagian awal COMMANDS.md.

- `--item` berformat `catatan|jumlah|kategori`; kategori boleh dikosongkan (ditebak dari kata kunci, atau `lainnya`).
- Nominal: `15000`, `15.000`, `15k`, `15rb`, `15 ribu`, `1,5jt`, `2 juta`, `Rp15.000`.
  Nilai negatif untuk `--opening`/`--actual` ditulis dengan tanda sama dengan: `--opening=-5k`.
- Periode: `today`, `yesterday`, `this-week`, `last-week`, `this-month`, `last-month`, `2026-08`, `last:3`, `all`,
  atau `--from 2026-08-01 --to 2026-08-31`.
- Tanggal transaksi: `--date 2026-10-05`, `--date yesterday`.
- Hapus dompet yang masih berisi butuh `--move-to <dompet>` atau `--write-off`.
- Hutang: `i_owe` = saya pinjam (uang masuk), `owed_to_me` = orang pinjam ke saya (uang keluar). Jika satu orang punya
  beberapa hutang terbuka, sebutkan `--id` (lihat `debt list`). `--paid-for "makan siang|makan"` = orang itu
  membayari sesuatu untukmu (hutang + pengeluaran sekaligus, saldo dompet tetap). `--no-cash` = tanpa uang
  masuk/keluar dompet, untuk hutang lama yang sudah termasuk di saldo awal.
- Tagihan rutin: `recurring pay` mencatat pengeluaran untuk bulan berjalan; `--month 2026-09` untuk bulan lain.
- `python finance.py <perintah> --help` menampilkan semua opsi (juga dalam JSON).

## Tes

```bat
.venv\Scripts\python -m pytest -q
```

Setelah mengubah perilaku atau pesan, perbarui contoh output di COMMANDS.md:

```bat
.venv\Scripts\python tools\commands_doc.py
```
