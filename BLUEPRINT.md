# BLUEPRINT: Backend Pencatat Keuangan Pribadi (Python CLI + SQLite)

Dokumen ini adalah perintah kerja untuk Claude Code. Baca seluruhnya sebelum menulis kode. Kerjakan per tahap (bagian 10) dan berhenti di setiap checkpoint supaya pengguna bisa mengetes sendiri di terminal.

---

## 1. Tujuan dan cakupan

Bangun **backend** pencatat keuangan pribadi: satu program CLI bernama `finance.py` dengan database SQLite. Program ini memegang semua data dan semua hitungan.

Nantinya program ini akan dipanggil oleh sebuah bot AI di Telegram, yang menerjemahkan chat bebas menjadi perintah CLI. **Bagian itu bukan pekerjaan sekarang.** Jangan membuat bot Telegram, integrasi AI, pemrosesan bahasa alami, atau penjadwal. Yang penting sekarang: logikanya benar dan bisa dites penuh dari terminal.

Karena pemanggilnya nanti adalah AI yang bisa salah, backend harus:
- menerima perintah yang sederhana dan konsisten,
- memvalidasi semua input dengan ketat,
- selalu membalas dalam JSON yang berisi kalimat siap kirim ke pengguna.

Kebutuhan pengguna yang harus bisa dilayani backend:

| Kebutuhan | Contoh |
|---|---|
| Catat pengeluaran | ayam goreng 15k |
| Catat pemasukan | gajian 600k |
| Beberapa item sekaligus | jajan 10k dan es teh 3k |
| Satu nominal untuk beberapa barang | jajan, parkir, dan makan total 50k |
| Saldo satu dompet | sisa uang di BRI |
| Saldo total | sisa uang seluruhnya |
| Laporan periode | pengeluaran bulan ini, bulan Agustus, 3 bulan terakhir |
| Analisis | data untuk menilai pola pengeluaran |
| Tabungan | posisi tabungan saat ini |
| Hutang piutang | siapa berhutang berapa, cicilan, sisa |

## 2. Prinsip yang tidak boleh dilanggar

1. **Semua hitungan ada di kode.** Saldo, total, persen, selisih, semuanya dihitung `finance.py`.
2. **Script tidak percaya input.** Setiap argumen divalidasi. Input salah ditolak dengan pesan yang menjelaskan cara memperbaikinya, dan data tidak berubah.
3. **Setiap output adalah satu objek JSON** dengan field `message` berbahasa Indonesia yang bisa langsung dibaca orang.
4. **Saldo tidak disimpan, selalu dihitung** dari tabel transaksi.
5. **Tidak ada yang benar-benar dihapus.** Hapus berarti soft delete (`deleted_at`).
6. **Nominal adalah integer rupiah.** Tidak ada float.
7. **Excel hanya hasil ekspor.** Sumber kebenaran adalah SQLite.
8. **Tidak ada input interaktif.** Tidak boleh ada `input()` atau prompt. Semua lewat argumen, supaya bisa dipanggil program lain.

Tulis prinsip ini juga ke `CLAUDE.md` di root project.

## 3. Lingkungan

- OS: Windows. Laptop dengan RAM terbatas, jadi program harus ringan dan cepat dijalankan.
- Python 3.10 ke atas. Pakai pustaka standar (`sqlite3`, `argparse`, `json`, `datetime`, `shutil`). Dependensi luar hanya `openpyxl` (ekspor) dan `pytest` (tes).
- Lokasi data: folder `data\` di dalam project. Bisa diganti lewat environment variable `FINANCE_HOME`.
- Waktu: waktu lokal sistem (WIB), disimpan sebagai teks ISO `YYYY-MM-DD HH:MM:SS`.
- Di awal `main()`, panggil `sys.stdout.reconfigure(encoding="utf-8")` agar output aman di terminal Windows.
- Sediakan opsi global tersembunyi `--now "YYYY-MM-DD HH:MM:SS"` (atau env `FINANCE_NOW`) untuk memalsukan waktu sekarang. Ini dipakai tes dan demo.

## 4. Struktur folder

```
finance\
  finance.py            # entry point CLI
  fin\
    db.py               # koneksi, skema, migrasi
    parse.py            # parse_amount, parse periode, parse tanggal
    resolve.py          # cari dompet/kategori dari nama atau alias
    output.py           # pembungkus JSON, format rupiah
    commands\           # satu file per kelompok perintah
    report.py
    export.py
  tests\
  data\                 # finance.db, backups\, exports\  (tidak masuk git)
  demo.py               # lihat bagian 9
  requirements.txt
  CLAUDE.md
  README.md             # cara pakai singkat, bahasa Indonesia
  COMMANDS.md           # referensi lengkap semua perintah (lihat tahap 4)
```

Jalankan `git init` dan buat `.gitignore` untuk `data\`.

## 5. Skema database

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);          -- schema_version, last_backup_date

CREATE TABLE accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type TEXT NOT NULL CHECK (type IN ('cash','bank','ewallet','savings')),
  is_default INTEGER NOT NULL DEFAULT 0,
  target_amount INTEGER,            -- hanya untuk type savings, boleh NULL
  target_date TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL COLLATE NOCASE,
  kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE (name, kind)
);

-- nama lain untuk dompet/kategori, dan kata kunci untuk tebak kategori dari catatan
CREATE TABLE aliases (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('account','category','keyword')),
  alias TEXT NOT NULL COLLATE NOCASE,
  target_id INTEGER NOT NULL,
  UNIQUE (kind, alias)
);

CREATE TABLE debts (
  id INTEGER PRIMARY KEY,
  direction TEXT NOT NULL CHECK (direction IN ('i_owe','owed_to_me')),
  person TEXT NOT NULL COLLATE NOCASE,
  principal INTEGER NOT NULL CHECK (principal > 0),
  due_date TEXT,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','paid')),
  created_at TEXT NOT NULL
);

CREATE TABLE transactions (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,                 -- waktu kejadian
  type TEXT NOT NULL CHECK (type IN ('income','expense','transfer','adjustment','debt_in','debt_out')),
  amount INTEGER NOT NULL,          -- > 0, kecuali adjustment yang boleh negatif
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  to_account_id INTEGER REFERENCES accounts(id),   -- hanya transfer
  category_id INTEGER REFERENCES categories(id),   -- hanya income/expense
  debt_id INTEGER REFERENCES debts(id),            -- hanya debt_in/debt_out
  note TEXT,
  raw_text TEXT,                    -- teks asli dari pengguna, jika ada
  group_id TEXT NOT NULL,           -- satu pemanggilan = satu group, dipakai untuk undo
  created_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX idx_tx_ts ON transactions(ts);
CREATE INDEX idx_tx_account ON transactions(account_id);

CREATE TABLE budgets (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  month TEXT,                       -- 'YYYY-MM', atau NULL = berlaku tiap bulan
  amount INTEGER NOT NULL CHECK (amount > 0),
  UNIQUE (category_id, month)
);

CREATE TABLE recurring (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  amount INTEGER NOT NULL,
  category_id INTEGER REFERENCES categories(id),
  account_id INTEGER REFERENCES accounts(id),
  day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
  last_paid_month TEXT,             -- 'YYYY-MM'
  active INTEGER NOT NULL DEFAULT 1
);
```

Data awal saat `init`:
- Kategori pengeluaran: makan, jajan, transport, belanja, tempat tinggal, pulsa & internet, pendidikan, kesehatan, hiburan, tagihan, biaya admin, sedekah, lainnya.
- Kategori pemasukan: gaji, uang saku, freelance, bonus, lainnya.
- Dompet: tidak dibuat otomatis. Lihat pertanyaan di bagian 10.

Sediakan migrasi sederhana berdasarkan `schema_version`. Aktifkan `PRAGMA foreign_keys = ON`. Setiap perintah tulis berjalan dalam satu transaksi database, supaya tidak ada data setengah tersimpan.

## 6. Aturan bisnis

**Saldo dompet** = jumlah dari transaksi yang tidak terhapus:
- tambah: `income`, `debt_in`, `adjustment` (bertanda), `transfer` yang masuk ke dompet itu
- kurang: `expense`, `debt_out`, `transfer` yang keluar dari dompet itu

Saldo boleh negatif (tidak ditolak), tetapi `message` harus memberi peringatan.

**Pengeluaran** di laporan = hanya `type = expense`. **Pemasukan** = hanya `type = income`. Transfer, hutang, dan penyesuaian tidak pernah dihitung sebagai pengeluaran atau pemasukan.

**Transfer**: satu baris `transfer`. Biaya admin dicatat sebagai baris `expense` terpisah berkategori "biaya admin" dengan `group_id` yang sama. Tarik tunai adalah transfer dari bank ke tunai. Transfer ke dompet yang sama ditolak.

**Tabungan**: dompet bertipe `savings`. Menabung = transfer ke dompet itu. Jadi tabungan tidak mengurangi total harta dan tidak muncul sebagai pengeluaran.

**Saldo awal dan koreksi**: `adjustment`. Perintah `adjust` menerima saldo sebenarnya, script menghitung selisihnya sendiri.

**Hutang piutang**:
- `i_owe` (saya berhutang): saat dibuat, uang masuk = `debt_in`. Saat saya membayar = `debt_out`.
- `owed_to_me` (orang berhutang ke saya): saat dibuat, uang keluar = `debt_out`. Saat dia membayar = `debt_in`.
- Sisa = `principal` dikurangi total pembayaran. Pembayaran boleh sebagian. Pembayaran melebihi sisa ditolak. Saat sisa 0, status jadi `paid`. Jika pembayaran dihapus, status dihitung ulang.
- Opsi `--no-cash` untuk hutang tanpa aliran uang (contoh: teman membayari makan). Hutang dicatat tanpa transaksi pembuka, dan pengeluarannya dicatat terpisah lewat `add`.

**Total**: `balance` tanpa argumen menampilkan saldo tiap dompet, subtotal uang pakai (cash, bank, ewallet), subtotal tabungan, total keseluruhan, lalu total hutang, total piutang, dan kekayaan bersih (total + piutang − hutang).

**Periode** (dipakai `report`, `list`, `analyze`, `export`):
- `today`, `yesterday`, `this-week` (Senin sampai hari ini), `last-week`, `this-month`, `last-month`, `YYYY-MM`, `last:N`, `all`, atau `--from` dan `--to`.
- `last:N` = bulan berjalan ditambah N−1 bulan kalender sebelumnya.
- Setiap output wajib menyebut rentang tanggal persisnya di `message` dan di `data`.

**Parsing nominal** (`parse_amount`, dipakai semua perintah): terima `15k`, `15rb`, `15 ribu`, `1,5jt`, `1.5jt`, `2 juta`, `15.000`, `15,000`, `15000`, `Rp15.000`, `rp 15.000`. Tolak nol, negatif, dan teks yang tidak bisa dibaca. Hati-hati dengan titik: `1.5jt` adalah desimal, `15.000` adalah pemisah ribuan.

**Parsing tanggal** (`--date`): terima `YYYY-MM-DD`, `today`, `yesterday`. Tanggal di masa depan ditolak. Jika hanya tanggal yang diberikan, jam diisi jam saat ini.

**Resolusi nama** dompet dan kategori: cocokkan nama atau alias, tidak peka huruf besar kecil. Kalau tidak ketemu, kembalikan error berisi daftar nama yang sah. Jangan pernah membuat dompet atau kategori baru secara diam-diam.

**Tebak kategori**: kalau kategori tidak diberikan, cari kata kunci di catatan (tabel `aliases`, kind `keyword`). Kalau tidak ada yang cocok, pakai "lainnya". `message` harus menyebut kategori yang dipakai.

**Dompet default**: kalau dompet tidak diberikan, pakai dompet `is_default`, dan `message` menyebutkannya. Kalau belum ada dompet default, kembalikan error.

**Budget**: setelah `add` pengeluaran, jika kategori itu punya budget dan pemakaian bulan itu melewati 80% atau 100%, tambahkan peringatan singkat di `message`.

**Backup otomatis**: pada operasi tulis pertama setiap hari, salin `finance.db` ke `data\backups\finance-YYYYMMDD.db`. Simpan 30 file terakhir.

## 7. Spesifikasi CLI

Bentuk umum: `python finance.py <perintah> [opsi]`

Output selalu satu objek JSON di stdout, tidak ada teks lain:

```json
{"ok": true, "message": "Tercatat 2 pengeluaran (Rp13.000) dari tunai. Sisa tunai Rp137.000.", "data": {}}
{"ok": false, "error": {"code": "UNKNOWN_ACCOUNT", "message": "Dompet 'bca' tidak ada.", "hint": "Pilihan: tunai, bri, gopay"}}
```

- Exit code 0 jika `ok`, 1 jika tidak.
- Format rupiah di `message`: `Rp15.000`. Di `data`, nominal tetap integer.
- Error argumen dari `argparse` juga harus keluar sebagai JSON (override `error()`), bukan teks usage.
- Bungkus `main()` dengan penangkap exception, supaya error tak terduga tetap berbentuk JSON dengan `code: "INTERNAL"`.
- Kode error dibuat tetap dan terdokumentasi: `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `BAD_AMOUNT`, `BAD_DATE`, `BAD_PERIOD`, `NOT_FOUND`, `NO_DEFAULT_ACCOUNT`, `AMBIGUOUS_DEBT`, `OVERPAYMENT`, `NOTHING_TO_UNDO`, `BAD_ARGS`, `INTERNAL`.

| Perintah | Fungsi |
|---|---|
| `init` | Buat database dan data awal. Aman dijalankan ulang. |
| `account add <nama> --type [--opening] [--default] [--target] [--target-date]` | Tambah dompet. `--opening` membuat adjustment "saldo awal". |
| `account list / rename / archive / set-default / set-target` | Kelola dompet. |
| `category add <nama> --kind` / `category list` / `category archive` | Kelola kategori. |
| `alias add --kind account\|category\|keyword --alias --target` / `alias list` / `alias remove` | Alias dan kata kunci. |
| `add --type income\|expense [--account] [--date] [--raw "..."] --item "catatan\|jumlah\|kategori" [--item ...]` | Catat satu atau banyak item dalam satu pemanggilan. Bagian kategori pada `--item` opsional. Semua item memakai `group_id` yang sama. Jika satu item tidak sah, tidak ada yang tersimpan. |
| `transfer --from --to --amount [--fee] [--date] [--note]` | Pindah uang antar dompet, termasuk menabung dan tarik tunai. |
| `adjust --account --actual [--note]` | Samakan saldo dengan kenyataan. |
| `balance [--account]` | Saldo satu dompet, atau semua beserta total. |
| `report --period ... [--type expense\|income\|all] [--category] [--account]` | Total, rincian per kategori dengan persen, jumlah transaksi, dan rentang tanggal. |
| `list --period ... [--search] [--type] [--limit] [--include-deleted]` | Daftar transaksi beserta ID. |
| `edit <id> [--amount] [--category] [--account] [--note] [--date]` | Ubah transaksi. `message` menampilkan sebelum dan sesudah. |
| `delete <id>` | Soft delete. |
| `undo` | Soft delete semua transaksi pada group terakhir yang belum terhapus. `message` menyebut apa yang dibatalkan. |
| `debt add --direction --person --amount [--account] [--due] [--note] [--no-cash]` | Catat hutang atau piutang. |
| `debt pay (--person \| --id) --amount [--account] [--date]` | Catat pembayaran. Jika satu orang punya lebih dari satu hutang terbuka dan `--id` tidak diberikan, kembalikan `AMBIGUOUS_DEBT` beserta daftar ID. |
| `debt list [--status] [--person]` | Daftar dengan sisa dan jatuh tempo. |
| `budget set --category --amount [--month]` / `budget remove` / `budget status [--month]` | Atur dan cek budget. Status menampilkan terpakai, sisa, persen. |
| `savings` | Saldo tiap dompet tabungan, target, persen tercapai, dan setoran bersih bulan ini. |
| `recurring add <nama> --amount --day [--category] [--account]` / `list` / `pay <nama>` / `remove` | Tagihan rutin. `pay` mencatat pengeluarannya dan mengisi `last_paid_month`. |
| `analyze --period ...` | Lihat bagian 8. |
| `export --period ... [--out]` | Buat .xlsx di `data\exports`. Kembalikan path file di `data.path`. |
| `daily-check --when pagi\|malam` | Lihat bagian 8. |
| `backup` | Backup manual. |

## 8. Analisis, pengecekan harian, ekspor

**`analyze`** hanya menyiapkan fakta, tidak memberi nasihat. Isi `data`:

- total pemasukan, total pengeluaran, selisih, rasio menabung (persen pemasukan yang tersisa)
- pengeluaran per kategori: nominal, persen, jumlah transaksi
- perbandingan dengan periode sebelumnya yang sama panjang: selisih nominal dan persen, total dan per kategori
- rata-rata pengeluaran per hari, hari paling boros, jumlah hari tanpa pengeluaran
- 5 transaksi terbesar
- pengeluaran kecil yang sering (di bawah Rp20.000, catatan yang sama muncul lebih dari 5 kali): jumlah kali dan totalnya
- status budget
- khusus bulan berjalan: proyeksi pengeluaran sampai akhir bulan berdasarkan rata-rata harian
- total hutang, piutang, dan yang jatuh tempo dalam 7 hari

`message` berisi ringkasan 5 sampai 8 baris yang bisa dibaca sendiri. Hindari pembagian dengan nol saat periode kosong atau pemasukan nol.

**`daily-check`** disiapkan untuk dipanggil penjadwal nanti. Backend hanya menyediakan perintahnya.
- `pagi`: tagihan rutin yang belum dibayar dan hutang yang jatuh tempo dalam 3 hari.
- `malam`: jika hari ini belum ada transaksi, pengingat singkat. Jika ada, total pengeluaran hari ini.
- Jika tidak ada yang perlu disampaikan: `"data": {"send": false}`. Jika ada: `"send": true`.

**`export`** (`openpyxl`): sheet Transaksi, Ringkasan per kategori, Saldo dompet, Hutang piutang. Header tebal dan dibekukan, kolom nominal berformat angka, lebar kolom disesuaikan.

## 9. Pengujian

**`pytest`** dengan database sementara (`FINANCE_HOME` diarahkan ke folder tmp) dan waktu dipalsukan lewat `--now`. Minimal mencakup:

- `parse_amount`: semua format di bagian 6 dan input tidak sah.
- Saldo benar setelah campuran income, expense, transfer dengan fee, adjustment, hutang.
- Transfer dan hutang tidak muncul di laporan pengeluaran maupun pemasukan.
- Batas periode: awal dan akhir bulan, pergantian tahun, `last:3` di bulan Januari, `this-week` di hari Senin.
- `add` dengan beberapa `--item`: semua tersimpan, atau tidak sama sekali jika satu item salah.
- `undo` membatalkan seluruh item dari satu pemanggilan, termasuk transfer beserta fee-nya.
- `delete` dan `edit` mengubah saldo dengan benar.
- Hutang: bayar sebagian, lunas, bayar berlebih ditolak, dua hutang untuk orang yang sama, `--no-cash`.
- Dompet atau kategori tidak dikenal menghasilkan error dengan `hint`, tanpa mengubah data.
- Budget: peringatan 80% dan 100%.
- `analyze` pada periode kosong tidak error.
- Setiap perintah, termasuk saat argumen salah, mengeluarkan JSON yang sah.

**`demo.py`**: script yang membuat database baru di folder sementara, menjalankan skenario dua bulan (kira-kira 40 transaksi, dua dompet, satu tabungan, satu hutang, satu piutang, satu budget), lalu mencetak hasil `balance`, `report`, `savings`, `debt list`, dan `analyze`. Tujuannya agar pengguna bisa melihat semua fitur bekerja dengan satu perintah. Angka akhir di demo harus diperiksa juga oleh sebuah tes.

**Skenario wajib lolos** (masuk ke tes sebagai tes end-to-end lewat subprocess):

| Maksud | Perintah |
|---|---|
| Beli ayam goreng 15k | `add --type expense --item "ayam goreng\|15k\|makan"` |
| Gajian 600k | `add --type income --item "gajian\|600k\|gaji"` |
| Jajan 10k dan es teh 3k | `add --type expense --item "jajan\|10k\|jajan" --item "es teh\|3k\|jajan"` |
| Jajan, parkir, makan total 50k | `add --type expense --item "jajan, parkir, makan\|50k\|makan"` |
| Sisa uang di BRI | `balance --account bri` |
| Sisa uang total | `balance` |
| Pengeluaran bulan ini | `report --period this-month --type expense` |
| Pengeluaran Agustus | `report --period 2026-08 --type expense` |
| Pengeluaran 3 bulan terakhir | `report --period last:3 --type expense` |
| Analisis pengeluaran | `analyze --period this-month` |
| Tabungan saat ini | `savings` |
| Nabung 100k dari BRI | `transfer --from bri --to tabungan --amount 100k` |
| Tarik tunai 200k, admin 2.5k | `transfer --from bri --to tunai --amount 200k --fee 2.5k` |
| Pinjam 50k dari Budi | `debt add --direction i_owe --person Budi --amount 50k` |
| Andi pinjam 100k | `debt add --direction owed_to_me --person Andi --amount 100k` |
| Bayar hutang Budi 20k | `debt pay --person Budi --amount 20k` |
| Saldo BRI sebenarnya 450k | `adjust --account bri --actual 450k` |
| Budget makan 600k sebulan | `budget set --category makan --amount 600k` |
| Batalkan yang terakhir | `undo` |
| Ekspor bulan ini | `export --period this-month` |

## 10. Tahapan kerja

**Sebelum mulai, tanyakan ke pengguna:**
1. Daftar dompet (contoh: tunai, bri, e-wallet apa saja) dan saldo masing-masing saat ini.
2. Dompet mana yang jadi default.
3. Apakah ingin dompet tabungan, dan apakah ada targetnya.
4. Kategori bawaan di bagian 5 sudah cocok atau perlu diubah.

Jawaban ini dipakai untuk membuat script `setup_awal.cmd` berisi perintah `account add` milik pengguna. Jangan tulis data pribadi ini ke dalam kode.

**Tahap 1: Inti.** Struktur project, `db.py` dan migrasi, `parse_amount`, pembungkus JSON, lalu `init`, `account`, `category`, `alias`, `add`, `transfer`, `adjust`, `balance`, `report`, `list`, `edit`, `delete`, `undo`, backup otomatis, beserta tesnya.
Checkpoint: beri pengguna sekitar 10 perintah terminal untuk dicoba sendiri, lengkap dengan hasil yang seharusnya muncul.

**Tahap 2: Hutang, budget, tabungan, tagihan.** `debt`, `budget`, `savings`, `recurring`, beserta tesnya.
Checkpoint seperti tahap 1.

**Tahap 3: Analisis dan ekspor.** `analyze`, `daily-check`, `export`, `demo.py`.
Checkpoint: pengguna menjalankan `python demo.py` dan membuka file Excel hasil ekspor.

**Tahap 4: Dokumentasi serah terima.** Tulis `COMMANDS.md`: setiap perintah dengan semua opsinya, satu contoh pemanggilan, contoh output sukses, dan error yang mungkin muncul. Dokumen ini akan menjadi dasar integrasi dengan bot AI nanti, jadi harus lengkap dan cocok persis dengan perilaku kode. Buat tes yang memastikan setiap perintah di `COMMANDS.md` memang ada di CLI.

Setiap tahap: semua tes harus lolos, lalu commit git, lalu perbarui `README.md`.

## 11. Di luar cakupan

- Bot Telegram, integrasi dengan agen AI, dan pemrosesan chat bebas. Dikerjakan terpisah setelah backend selesai.
- Penjadwal (cron). Backend hanya menyediakan `daily-check` dan `analyze` untuk dipanggil nanti.
- Sinkronisasi otomatis dengan bank atau e-wallet.
- Multi pengguna dan multi mata uang.
- Antarmuka web atau dashboard.
- Budget sistem amplop (total dompet harus sama dengan total budget). Skema saat ini tidak menghalangi untuk ditambah nanti.
