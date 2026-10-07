# BLUEPRINT: Backend Pencatat Keuangan Pribadi (Python CLI + SQLite)

Dokumen ini adalah perintah kerja untuk Claude Code. Baca seluruhnya sebelum menulis kode. Kerjakan per tahap (bagian 10) dan berhenti di setiap checkpoint supaya pengguna bisa mengetes sendiri di terminal.

Perubahan sesudah blueprint awal dicatat di `docs\` (mulai `PERUBAHAN-01.md`) dan sudah dimasukkan ke dokumen ini.

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
| Budget (sistem amplop) | sisa uang makan bulan ini, pindah budget |
| Tabungan | posisi tabungan saat ini |
| Hutang piutang | siapa berhutang berapa, cicilan, sisa |
| Kustomisasi lewat chat | tambah, ganti nama, hapus dompet, kategori, budget, tabungan |

## 2. Prinsip yang tidak boleh dilanggar

1. **Semua hitungan ada di kode.** Saldo, total, persen, selisih, semuanya dihitung `finance.py`.
2. **Script tidak percaya input.** Setiap argumen divalidasi. Input salah ditolak dengan pesan yang menjelaskan cara memperbaikinya, dan data tidak berubah.
3. **Setiap output adalah satu objek JSON** dengan field `message` berbahasa Indonesia yang bisa langsung dibaca orang.
4. **Saldo tidak disimpan, selalu dihitung** dari tabel transaksi.
5. **Transaksi tidak pernah benar-benar dihapus.** Hapus transaksi berarti soft delete (`deleted_at`). Dompet, kategori, budget, dan tabungan yang sudah pernah dipakai diarsipkan, bukan dihapus; hanya yang belum pernah dipakai yang dihapus sungguhan.
6. **Nominal adalah integer rupiah.** Tidak ada float.
7. **Excel hanya hasil ekspor.** Sumber kebenaran adalah SQLite.
8. **Tidak ada input interaktif.** Tidak boleh ada `input()` atau prompt. Semua lewat argumen, supaya bisa dipanggil program lain.

Tulis prinsip ini juga ke `CLAUDE.md` di root project.

## 3. Lingkungan

- OS: Windows. Laptop dengan RAM terbatas, jadi program harus ringan dan cepat dijalankan.
- Python 3.10 ke atas. Pakai pustaka standar (`sqlite3`, `argparse`, `json`, `datetime`, `shutil`). Dependensi luar hanya `openpyxl` (ekspor) dan `pytest` (tes).
- Lokasi data: `<profil pengguna>\Documents\Manager\Finance\data` (profil = `%USERPROFILE%` di Windows, atau `~` di Linux/Mac), sama dengan `fin.sh`. Bisa diganti lewat environment variable `FINANCE_HOME`. Path yang memuat nama pengguna tidak ditulis di repo; selalu dihitung dari `USERPROFILE`/`HOME`.
- Waktu: waktu lokal sistem (WIB), disimpan sebagai teks ISO `YYYY-MM-DD HH:MM:SS`.
- Di awal `main()`, panggil `sys.stdout.reconfigure(encoding="utf-8")` agar output aman di terminal Windows.
- Sediakan opsi global tersembunyi `--now "YYYY-MM-DD HH:MM:SS"` (atau env `FINANCE_NOW`) untuk memalsukan waktu sekarang. Ini dipakai tes dan demo.

## 4. Struktur folder

```
vibe-finance\
  finance.py            # entry point CLI
  fin\
    cli.py              # parser, --now, pembungkus error
    db.py               # koneksi, skema, migrasi, write(), backup
    parse.py            # parse_amount, parse periode, parse tanggal
    resolve.py          # cari dompet/kategori dari nama atau alias
    output.py           # pembungkus JSON, format rupiah, kode error
    ledger.py           # tulis transaksi, saldo dompet, op_groups
    budgets.py          # saldo budget, cari/buat budget, pindahan
    debts.py            # sisa hutang piutang, pilih hutang dari --person/--id
    recurring.py        # jatuh tempo dan bulan terbayar tagihan rutin
    report.py
    analysis.py         # fakta untuk analyze
    export.py
    commands\           # satu file per kelompok perintah
  tests\
  tools\commands_doc.py # menjalankan contoh di COMMANDS.md dan mengisi outputnya
  docs\                 # dokumen perubahan (PERUBAHAN-xx.md)
  fin.sh                # pembungkus bash (MSYS)
  data\                 # lama, tidak dipakai lagi; tetap di .gitignore
# folder data: <profil>\Documents\Manager\Finance\data\  (finance.db, backups\, exports\), di luar repo
  demo.py               # lihat bagian 9
  requirements.txt
  CLAUDE.md
  README.md             # cara pakai singkat, bahasa Indonesia
  COMMANDS.md           # referensi lengkap semua perintah (lihat tahap 4)
```

Repo: `https://github.com/Aderelyan/vibe-finance.git` (publik), branch `main`. `.gitignore` memuat `data/`, `*.db`, `*.xlsx`, `setup_awal.cmd`, `.venv/`. Tidak boleh ada database, backup, ekspor, saldo asli, atau path yang memuat nama pengguna Windows di riwayat git. Push setiap kali satu tahap selesai dan semua tes lolos. Jangan force push.

## 5. Skema database

Versi skema saat ini: **4**. Tabel `accounts`, `transactions`, dan `debts` di bawah sudah dalam bentuk v4 (lihat migrasi v4). Migrasi berurutan berdasarkan `meta.schema_version`. Sebelum migrasi database yang sudah ada, dibuat backup `finance-YYYYMMDD-pre-vN.db`.

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);          -- schema_version, last_backup_date

-- dompet operasional (cash/bank/ewallet) dan tabungan (savings) berbagi satu tabel dan satu ruang nama
CREATE TABLE accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type TEXT NOT NULL CHECK (type IN ('cash','bank','ewallet','savings')),
  is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default = 0 OR type != 'savings'),
  archived INTEGER NOT NULL DEFAULT 0,     -- 1 = sudah dihapus tapi punya riwayat
  target_amount INTEGER,                   -- hanya savings
  target_date TEXT,                        -- hanya savings
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
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','paid')),   -- dihitung ulang dari pembayaran
  created_at TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,     -- v3: 1 = dihapus tapi punya transaksi
  savings_account_id INTEGER REFERENCES accounts(id)   -- v4: terisi = pinjaman dari tabungan ini
);

CREATE TABLE budgets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  kind TEXT NOT NULL CHECK (kind IN ('unallocated','category','savings')),  -- 'savings' hanya sisa lama (diarsipkan)
  category_id INTEGER UNIQUE REFERENCES categories(id),   -- hanya kind category
  target_amount INTEGER,                                  -- tidak dipakai lagi sejak v4
  target_date TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE transactions (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,                 -- waktu kejadian
  type TEXT NOT NULL CHECK (type IN ('income','expense','transfer','adjustment','debt_in','debt_out',
                                     'deposit','withdraw','savings_loan','savings_repay')),
  amount INTEGER NOT NULL,          -- > 0, kecuali adjustment yang boleh negatif
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  to_account_id INTEGER REFERENCES accounts(id),   -- hanya transfer, deposit, withdraw
  category_id INTEGER REFERENCES categories(id),   -- income/expense; savings_loan (kategori barang)
  debt_id INTEGER REFERENCES debts(id),            -- debt_in/debt_out/savings_loan/savings_repay
  budget_id INTEGER REFERENCES budgets(id),        -- lihat aturan budget_id di bagian 6
  note TEXT,
  raw_text TEXT,                    -- teks asli dari pengguna, jika ada
  group_id TEXT NOT NULL,           -- satu pemanggilan = satu group, dipakai untuk undo
  created_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX idx_tx_ts ON transactions(ts);
CREATE INDEX idx_tx_account ON transactions(account_id);
CREATE INDEX idx_tx_group ON transactions(group_id);

CREATE TABLE budget_moves (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  from_budget_id INTEGER NOT NULL REFERENCES budgets(id),
  to_budget_id INTEGER NOT NULL REFERENCES budgets(id),
  amount INTEGER NOT NULL CHECK (amount > 0),
  note TEXT,
  group_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  deleted_at TEXT
);

-- urutan gabungan semua pencatatan uang (transaksi dan pindahan budget), dipakai undo
CREATE TABLE op_groups (
  id INTEGER PRIMARY KEY,
  group_id TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL,             -- add, transfer, adjust, opening, budget_alloc, budget_move, ...
  restore TEXT,                     -- JSON [[tabel, id], ...] diaktifkan lagi jika di-undo;
                                    -- [tabel, id, 1] justru diarsipkan (hutang yang dibuat group itu)
  undoable INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE recurring (            -- v3: dibangun ulang, kolom active diganti archived
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  amount INTEGER NOT NULL CHECK (amount > 0),
  category_id INTEGER REFERENCES categories(id),
  account_id INTEGER REFERENCES accounts(id),       -- NULL = dompet default saat dibayar
  day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
  last_paid_month TEXT,             -- 'YYYY-MM', selalu dihitung ulang dari recurring_payments
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- v3: satu baris per pembayaran tagihan rutin; bulan tagihan bisa berbeda dari tanggal bayar
CREATE TABLE recurring_payments (
  id INTEGER PRIMARY KEY,
  recurring_id INTEGER NOT NULL REFERENCES recurring(id),
  tx_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
  month TEXT NOT NULL               -- 'YYYY-MM'
);
```

Data awal saat database dibuat:
- Kategori pengeluaran: makan, jajan, transport, belanja, tempat tinggal, pulsa & internet, pendidikan, kesehatan, hiburan, tagihan, biaya admin, sedekah, lainnya.
- Kategori pemasukan: gaji, uang saku, freelance, bonus, lainnya.
- Kata kunci tebak kategori (mis. parkir → transport, kopi → jajan), bisa diubah lewat `alias`.
- Budget sistem `belum teralokasi`.
- Dompet dan tabungan: tidak dibuat otomatis. Pengguna membuatnya sendiri lewat perintah.

**Migrasi v1 → v2**: tabel `budgets` lama dibuang dan dibuat ulang, `budget_moves` dan `op_groups` dibuat, `transactions.budget_id` ditambah. Semua transaksi lama selain transfer diarahkan ke `belum teralokasi`. Dompet bertipe `savings` diubah menjadi `bank`, lalu dibuat tabungan bernama dan bertarget sama, dan uang sebesar saldo dompet itu dipindah dari `belum teralokasi` ke tabungan tersebut (pindahan ini tidak bisa di-undo).

**Migrasi v2 → v3**: `debts.archived` ditambah. Tabel `recurring` dibangun ulang (`archived = 1 - active`, `amount > 0`, `created_at`), lalu `recurring_payments` dibuat.

**Migrasi v3 → v4** (tabungan menjadi akun terpisah, `docs\PERUBAHAN-02.md`): tabel `accounts` dibangun ulang (jenis `savings`, `target_amount`, `target_date`, tabungan tidak boleh default), tabel `transactions` dibangun ulang (jenis transaksi baru, indeks `group_id`), `debts.savings_account_id` ditambah. Budget tabungan lama (jika ada) diubah dengan aman: saldonya dikembalikan ke `belum teralokasi` lewat pindahan budget yang tidak bisa di-undo (uangnya memang ada di dompet operasional), budget itu diarsipkan, lalu dibuat akun tabungan kosong bernama dan bertarget sama (jika nama sudah dipakai dompet, diberi akhiran ` (tabungan)`). Tidak ada uang yang dibuat-buat atau hilang; pengguna lalu mengisinya dengan `savings deposit`.

Aktifkan `PRAGMA foreign_keys = ON`. Setiap perintah tulis berjalan dalam satu transaksi database, supaya tidak ada data setengah tersimpan.

## 6. Aturan bisnis

**Saldo akun** (dompet maupun tabungan) = jumlah dari transaksi yang tidak terhapus:
- tambah: `income`, `debt_in`, `adjustment` (bertanda), `savings_repay` di akun itu; `transfer`, `deposit`, `withdraw` yang masuk ke akun itu (`to_account_id`)
- kurang: `expense`, `debt_out`, `savings_loan` di akun itu; `transfer`, `deposit`, `withdraw` yang keluar dari akun itu (`account_id`)

Saldo boleh negatif (tidak ditolak), tetapi `message` harus memberi peringatan.

**Pengeluaran** di laporan = hanya `type = expense`. **Pemasukan** = hanya `type = income`. Transfer, hutang, penyesuaian, alokasi dan pindahan budget, menabung, dan menarik tabungan tidak pernah dihitung sebagai pengeluaran atau pemasukan. Pengeluaran dari tabungan (`expense` di akun tabungan) dilaporkan terpisah dari pengeluaran dompet di `report`, `analyze`, dan `export`.

**Transfer**: satu baris `transfer`, hanya antar dompet operasional (tabungan memakai `savings deposit/withdraw`). Biaya admin dicatat sebagai baris `expense` terpisah berkategori "biaya admin" dengan `group_id` yang sama. Tarik tunai adalah transfer dari bank ke tunai. Transfer ke dompet yang sama ditolak. Transfer tidak mengubah budget apa pun.

**Saldo awal dan koreksi**: `adjustment`. Perintah `adjust` menerima saldo sebenarnya (boleh 0), script menghitung selisihnya sendiri. Untuk dompet, selisihnya masuk ke atau keluar dari `belum teralokasi`; untuk tabungan, budget tidak berubah.

### Budget sistem amplop

Uang yang sama dilihat dari dua sisi: **dompet** (uangnya ada di mana) dan **budget** (uangnya untuk apa).

**Aturan utama: total dompet operasional (cash/bank/ewallet) selalu sama dengan total semua budget**, setelah perintah apa pun. Tabungan tidak ikut. Ini dijaga karena setiap transaksi yang mengubah total dompet operasional menunjuk ke tepat satu budget (`budget_id`), transaksi lain tidak punya budget, dan pindahan budget selalu berpasangan. Aturan `budget_id` (diperiksa di `insert_tx` dan di tes langsung dari tabel):
- wajib: `deposit`, `withdraw`, serta `income`/`expense`/`adjustment`/`debt_in`/`debt_out` di dompet operasional;
- kosong: `transfer`, `savings_loan`, `savings_repay`, serta `expense`/`adjustment` di tabungan.

Saldo budget: `income`, `debt_in`, `adjustment`, `withdraw` menambah; `expense`, `debt_out`, `deposit` mengurangi. Setiap jenis transaksi seimbang sendiri antara dompet operasional dan budget, jadi aturan utama tetap benar setelah `delete` atau `undo` transaksi mana pun.

1. Budget sistem `belum teralokasi` tidak bisa dihapus, ditutup, atau diganti nama.
2. Pemasukan selalu masuk ke `belum teralokasi`. Tidak ada alokasi otomatis. Saldo awal dompet juga masuk ke sini.
3. Alokasi hanya terjadi atas perintah pengguna, lewat `budget alloc` atau `budget move`.
4. Budget pengeluaran menempel pada kategori pengeluaran, satu kategori satu budget, bernama sama dengan kategorinya. Kategori baru punya budget setelah pertama kali diberi alokasi.
5. Pengeluaran mengurangi budget milik kategorinya. Jika kategori itu belum punya budget (atau budgetnya ditutup), pengeluaran mengurangi `belum teralokasi`.
6. Budget boleh minus. `message` wajib memberi peringatan ("Budget makan minus Rp5.000"), begitu juga jika `belum teralokasi` minus (alokasi melebihi uang yang ada).
7. Setiap `add` pengeluaran menampilkan sisa budget yang terpakai di `message`, di samping sisa dompet.
8. Biaya admin tetap pengeluaran kategori `biaya admin`.
9. Hutang piutang: uang masuk menambah `belum teralokasi` (`--budget` ditolak). Uang keluar mengurangi `belum teralokasi`, kecuali diberi `--budget`.
10. Riwayat tidak ditulis ulang. Transaksi lama tetap tercatat pada budget yang berlaku saat dibuat.
11. `edit` yang mengganti kategori memindahkan transaksi itu ke budget kategori barunya (atau `belum teralokasi`).
12. `--budget <nama>` pada `add` dan `edit` pengeluaran memaksa pengeluaran diambil dari budget tertentu. Tabungan bukan budget (`UNKNOWN_BUDGET` dengan hint ke perintah `savings`).
13. Budget yang ditutup tetapi masih punya sisa (karena transaksi lamanya diubah atau dihapus) tetap tampil dengan tanda "(ditutup)", dan bisa ditutup lagi untuk mengembalikan sisanya.

Saldo budget = jumlah bertanda transaksi yang menunjuk ke budget itu, ditambah pindahan masuk, dikurangi pindahan keluar. Yang terhapus tidak dihitung. Saldo budget tidak disimpan.

### Tabungan (sejak skema v4, `docs\PERUBAHAN-02.md`)

**Tabungan** adalah akun berjenis `savings`: dompet terpisah dengan saldo sendiri (dihitung dari transaksi) dan target opsional, di luar aturan utama. Bukan budget, tidak pernah jadi dompet default, dan tidak bisa dipakai `add`, `transfer`, `debt add`, `recurring`. Nama tabungan dan dompet berbagi satu ruang nama. Boleh ada banyak tabungan.

| Perintah | Transaksi | Dompet operasional | Tabungan | Budget |
|---|---|---|---|---|
| `savings add --opening X` | `adjustment` di tabungan | – | +X | – |
| `savings deposit --from D --to T --amount X [--from-budget B]` | `deposit` | D −X | T +X | B −X (bawaan `belum teralokasi`); ditolak `BAD_AMOUNT` jika saldo B kurang dari X |
| `savings withdraw --from T --to D --amount X [--to-budget B]` | `withdraw` | D +X | T −X | B +X (bawaan `belum teralokasi`) |
| `savings spend --mode purpose` | `expense` di tabungan | – | −X | – |
| `savings spend --mode debt` | `savings_loan` + hutang `i_owe` ke tabungan | – | −X | – |
| `debt pay` pinjaman tabungan dari D [`--budget B`] | `expense` di D + `savings_repay` di T | D −X | T +X | B −X (bawaan budget kategori barangnya) |
| `adjust --account T` | `adjustment` di tabungan | – | ±X | – |

- `withdraw` dan `spend` ditolak (`BAD_AMOUNT`, `error.data.savings_balance`) jika saldo tabungan tidak cukup. Saldo tabungan tidak pernah dibuat minus oleh perintah ini (hanya `adjust` dan penghapusan transaksi yang bisa).
- `spend --mode purpose`: pengeluaran dengan sumber tabungan, tidak memotong dompet maupun budget, dilaporkan terpisah dari pengeluaran dompet.
- `spend --mode debt`: satu hutang per item (`direction = i_owe`, `person` = nama tabungan, `savings_account_id` terisi, catatan = catatan item). Belum menjadi pengeluaran. Saat dilunasi lewat `debt pay` (boleh sebagian), dompet dan budget berkurang, tabungan bertambah, dan pengeluaran tercatat di kategori barangnya. Hutang ini internal: tidak masuk total hutang ke orang lain maupun kekayaan bersih; ditampilkan sebagai "pinjaman dari tabungan". `debt rename` ditolak (nama mengikuti tabungan; `savings rename` ikut mengganti nama di pinjamannya).
- `edit`: dompet hanya bisa diganti dengan akun sekelas (dompet dengan dompet, tabungan dengan tabungan); pengeluaran dari tabungan tidak bisa diberi `--budget`; nominal `savings_loan`/`savings_repay` tidak bisa diubah (sama seperti hutang).

### Hapus, ganti nama, aktifkan kembali

Berlaku untuk dompet, kategori, budget, tabungan:
- Belum pernah dipakai: dihapus sungguhan.
- Sudah pernah dipakai: diarsipkan (`archived = 1`), tidak muncul lagi di daftar dan tidak bisa dipilih, riwayat transaksinya tetap utuh. Dari sisi pengguna hasilnya sama: "sudah dihapus". `message` menyebut mana yang terjadi.
- Menambah nama yang sama dengan yang diarsipkan mengaktifkannya kembali.
- Milik sistem (`belum teralokasi`, kategori `lainnya` di kedua jenis, `biaya admin`) tidak bisa dihapus atau diganti nama: `SYSTEM_PROTECTED`.

Hapus dompet yang masih berisi ditolak dengan `NOT_EMPTY` dan `hint` dua pilihan: `--move-to <dompet>` (sisa dipindah lewat transfer) atau `--write-off` (sisa dinolkan lewat penyesuaian, `belum teralokasi` ikut berubah). Menghapus dompet default ditolak sampai default dipindah, kecuali tinggal satu dompet.

Hapus kategori yang punya budget: budget itu ditutup dulu (sisa kembali ke `belum teralokasi`).

Hapus tabungan: ditolak (`NOT_EMPTY`) selama masih ada pinjaman tabungan yang belum dikembalikan. Saldo tidak nol butuh `--move-to <dompet>` (lewat `withdraw`, masuk ke `belum teralokasi`), `--move-to <tabungan lain>` (lewat `transfer` antar tabungan), atau `--write-off` (penyesuaian di tabungan, budget tidak berubah). Lalu mengikuti aturan hapus di atas; undo mengaktifkannya kembali tanpa menjadikannya default.

**Undo**: membatalkan pencatatan uang terakhir, yaitu group terakhir di `op_groups` yang masih punya transaksi atau pindahan budget aktif. Urutannya gabungan antara transaksi dan pindahan budget. Jika group itu juga mengarsipkan sesuatu (hapus dompet dengan `--move-to`/`--write-off`, tutup budget, hapus kategori atau tabungan yang bersaldo), undo mengaktifkannya kembali. Perubahan pengaturan tanpa uang (tambah, ganti nama, hapus yang kosong) tidak di-undo.

**Hutang piutang**:
- `i_owe` (saya berhutang): saat dibuat, uang masuk = `debt_in`. Saat saya membayar = `debt_out`.
- `owed_to_me` (orang berhutang ke saya): saat dibuat, uang keluar = `debt_out`. Saat dia membayar = `debt_in`.
- Sisa = `principal` dikurangi total pembayaran. Pembayaran boleh sebagian; `--amount all` melunasi sisanya. Pembayaran melebihi sisa ditolak (`OVERPAYMENT`). Saat sisa 0, status jadi `paid`. Jika pembayaran dihapus atau di-undo, status dihitung ulang. Nominal transaksi hutang tidak bisa diubah lewat `edit`.
- Nama orang dicocokkan tanpa peka huruf besar kecil; hutang baru untuk orang yang sudah ada memakai ejaan yang sudah tercatat. `--person` memilih hutang yang masih terbuka; jika lebih dari satu, `AMBIGUOUS_DEBT` beserta daftar ID (`data.candidates`). `--direction` mempersempit pilihan.
- Opsi `--paid-for "catatan|kategori"` (khusus `i_owe`, kategori opsional dan ditebak seperti `add`): orang lain membayari sesuatu untuk saya. Dalam satu group dicatat `debt_in` ke `belum teralokasi` dan `expense` sebesar sama dari dompet yang sama ke budget kategorinya. Saldo dompet tidak berubah, pengeluarannya muncul di laporan, budget kategorinya terpotong. `undo` membatalkan keduanya dan menghapus hutangnya.
- Opsi `--no-cash` untuk hutang tanpa aliran uang: tidak ada transaksi pembuka, dompet dan budget tidak berubah. Dipakai untuk hutang lama yang uangnya sudah termasuk di saldo awal. Tidak boleh digabung dengan `--paid-for`, `--account`, `--budget`, atau `--date`.
- `undo` setelah `debt add` (bukan `--no-cash`) membatalkan transaksi pembukanya dan menghapus (mengarsipkan) hutang itu.
- `debt remove`: tanpa transaksi sama sekali = dihapus sungguhan. Sudah lunas = diarsipkan. Masih bersisa = `NOT_EMPTY` dengan pilihan `debt pay --amount all` atau `--write-off` (sisa dianggap selesai, diarsipkan, dompet dan budget tidak berubah). Hutang yang diarsipkan tidak dihitung di total hutang/piutang.
- Budget: lihat aturan budget nomor 9.

**Tagihan rutin**:
- Jatuh tempo tiap bulan pada `day_of_month`; tanggal 29-31 di bulan yang lebih pendek menjadi akhir bulan.
- `recurring add` tanpa `--category`: ditebak dari nama lewat kata kunci, jika tidak cocok memakai `tagihan` (atau `lainnya` jika `tagihan` dihapus). Tanpa `--account`: dompet default saat dibayar.
- `recurring pay` mencatat satu `expense` (kategori dan budget mengikuti aturan pengeluaran biasa, `--budget` boleh), plus satu baris `recurring_payments`. Bulan tagihan = `--month`, atau bulan dari tanggal bayar. Membayar bulan yang sudah dibayar ditolak (`BAD_ARGS`).
- `last_paid_month` = bulan terbesar dari pembayaran yang transaksinya masih aktif, dihitung ulang setelah `pay`, `delete`, dan `undo`.
- Hapus: belum pernah dibayar = dihapus sungguhan; sudah pernah = diarsipkan. `recurring add` dengan nama yang diarsipkan mengaktifkannya kembali dengan nilai baru.
- Dompet atau kategori tagihan yang sudah dihapus menghasilkan `UNKNOWN_ACCOUNT`/`UNKNOWN_CATEGORY` saat `pay`, dengan hint `recurring set`.

**Total**: `balance` tanpa argumen menampilkan dompet dan tabungan sebagai dua angka terpisah. Per dompet: saldo tiap dompet operasional dan total dompet. Per budget: `belum teralokasi`, budget kategori, total budget (= total dompet). Tabungan: saldo tiap tabungan dan total tabungan, plus pinjaman tabungan yang belum dikembalikan. Lalu total hutang, total piutang, dan kekayaan bersih (dompet + tabungan + piutang − hutang ke orang lain). `data` memuat `accounts` (hanya dompet), `savings`, `total_dompet`, `total_tabungan`, `total_budget`, `consistent` (total dompet = total budget), `savings_loans_total`.

**Periode** (dipakai `report`, `list`, `analyze`, `export`, `budget history`):
- `today`, `yesterday`, `this-week` (Senin sampai hari ini), `last-week`, `this-month`, `last-month`, `YYYY-MM`, `last:N`, `all`, atau `--from` dan `--to`.
- `last:N` = bulan berjalan ditambah N−1 bulan kalender sebelumnya.
- Akhir periode tidak melewati hari ini.
- Setiap output wajib menyebut rentang tanggal persisnya di `message` dan di `data`.

**Parsing nominal** (`parse_amount`, dipakai semua perintah): terima `15k`, `15rb`, `15 ribu`, `1,5jt`, `1.5jt`, `2 juta`, `15.000`, `15,000`, `15000`, `Rp15.000`, `rp 15.000`. Tolak nol, negatif, dan teks yang tidak bisa dibaca. Pengecualian: `--actual` pada `adjust` dan `--opening` menerima nol dan negatif (negatif ditulis `--opening=-5k`). Hati-hati dengan titik: `1.5jt` adalah desimal, `15.000` adalah pemisah ribuan.

**Parsing tanggal** (`--date`): terima `YYYY-MM-DD`, `today`, `yesterday`. Tanggal di masa depan ditolak. Jika hanya tanggal yang diberikan, jam diisi jam saat ini.

**Resolusi nama** dompet, kategori, dan budget: cocokkan nama atau alias, tidak peka huruf besar kecil. Kalau tidak ketemu, kembalikan error berisi daftar nama yang sah. Jangan pernah membuat dompet atau kategori baru secara diam-diam. (Budget kategori dibuat saat kategori itu pertama kali diberi alokasi, karena itu memang perintah pengguna.)

**Tebak kategori**: kalau kategori tidak diberikan, cari kata kunci di catatan (tabel `aliases`, kind `keyword`). Kalau tidak ada yang cocok, pakai "lainnya". `message` harus menyebut kategori yang dipakai.

**Dompet default**: dompet pertama otomatis jadi default. Kalau dompet tidak diberikan, pakai dompet default, dan `message` menyebutkannya. Kalau belum ada dompet default, kembalikan error.

**Backup otomatis**: pada operasi tulis pertama setiap hari, salin `finance.db` ke `<folder data>\backups\finance-YYYYMMDD.db`. Simpan 30 file terakhir.

## 7. Spesifikasi CLI

Bentuk umum: `python finance.py <perintah> [opsi]`

Output selalu satu objek JSON di stdout, tidak ada teks lain:

```json
{"ok": true, "message": "Tercatat 2 pengeluaran (Rp13.000) dari tunai. Sisa tunai Rp137.000. Sisa budget jajan Rp37.000.", "data": {}}
{"ok": false, "error": {"code": "UNKNOWN_ACCOUNT", "message": "Dompet 'bca' tidak ada.", "hint": "Pilihan: tunai, bri, gopay"}}
```

- Exit code 0 jika `ok`, 1 jika tidak.
- Format rupiah di `message`: `Rp15.000`. Di `data`, nominal tetap integer.
- Error argumen dari `argparse` juga harus keluar sebagai JSON (override `error()`), bukan teks usage.
- Bungkus `main()` dengan penangkap exception, supaya error tak terduga tetap berbentuk JSON dengan `code: "INTERNAL"`.
- Kode error tetap dan terdokumentasi: `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `UNKNOWN_BUDGET`, `BAD_AMOUNT`, `BAD_DATE`, `BAD_PERIOD`, `NOT_FOUND`, `NO_DEFAULT_ACCOUNT`, `AMBIGUOUS_DEBT`, `OVERPAYMENT`, `NOTHING_TO_UNDO`, `NOT_EMPTY`, `SYSTEM_PROTECTED`, `BAD_ARGS`, `INTERNAL`.

| Perintah | Fungsi |
|---|---|
| `init` | Buat database dan data awal. Aman dijalankan ulang. |
| `account add <nama> --type cash\|bank\|ewallet [--opening] [--default]` | Tambah dompet, atau aktifkan kembali yang pernah dihapus. `--opening` membuat adjustment "saldo awal" ke `belum teralokasi`. |
| `account list [--all]` / `rename <nama> <baru>` / `set-default <nama>` | Kelola dompet. |
| `account remove <nama> [--move-to <dompet> \| --write-off]` | Hapus dompet. Lihat aturan hapus. |
| `category add <nama> --kind` / `category list [--kind] [--all]` / `category rename <nama> <baru> [--kind]` / `category remove <nama> [--kind]` | Kelola kategori. |
| `alias add --kind account\|category\|keyword --alias --target [--target-kind]` / `alias list` / `alias remove` | Alias dan kata kunci. |
| `add --type income\|expense [--account] [--budget] [--date] [--raw "..."] --item "catatan\|jumlah\|kategori" [--item ...]` | Catat satu atau banyak item dalam satu pemanggilan. Bagian kategori pada `--item` opsional. Semua item memakai `group_id` yang sama. Jika satu item tidak sah, tidak ada yang tersimpan. |
| `transfer --from --to --amount [--fee] [--date] [--note]` | Pindah uang antar dompet, termasuk tarik tunai. |
| `adjust --account --actual [--note]` | Samakan saldo dengan kenyataan. `--actual 0` diterima. |
| `balance [--account]` | Saldo satu dompet, atau semua dompet dan budget beserta total. |
| `report --period ... [--type expense\|income\|all] [--category] [--account]` | Total, rincian per kategori dengan persen, jumlah transaksi, dan rentang tanggal. |
| `list --period ... [--search] [--type] [--account] [--category] [--limit] [--include-deleted]` | Daftar transaksi beserta ID. |
| `edit <id> [--amount] [--category] [--budget] [--account] [--to] [--note] [--date]` | Ubah transaksi. `message` menampilkan sebelum dan sesudah. |
| `delete <id>` | Soft delete. |
| `undo` | Batalkan pencatatan uang terakhir (transaksi atau alokasi/pindahan budget). `message` menyebut apa yang dibatalkan. |
| `budget list` | Semua budget dan saldonya, lalu total dan pemeriksaan total dompet = total budget. |
| `budget alloc --item "budget\|jumlah" [--item ...] [--note]` | Alokasi dari `belum teralokasi` ke satu atau banyak budget kategori pengeluaran. Satu `group_id`, semua atau tidak sama sekali. |
| `budget move --from --to --amount\|all [--note]` | Pindah antar budget mana pun. |
| `budget close <nama>` | Sisa (plus atau minus) kembali ke `belum teralokasi`, budget ditutup. Kategorinya tetap ada. |
| `budget history [--budget] [--period] [--limit]` | Riwayat alokasi dan pindahan. |
| `savings add <nama> [--target] [--target-date] [--opening]` | Buat tabungan (akun terpisah), atau aktifkan kembali. |
| `savings list [--all]` | Saldo, target, persen tercapai, kekurangan, perubahan bersih bulan ini, pinjaman belum dikembalikan, lalu total. |
| `savings set <nama> [--target] [--target-date] [--clear]` / `savings rename` / `savings remove [--move-to \| --write-off]` | Kelola tabungan. |
| `savings deposit --from <dompet> --to <tabungan> --amount [--from-budget] [--date] [--note] [--raw]` | Menabung. Lihat bagian 6, Tabungan. |
| `savings withdraw --from <tabungan> --to <dompet> --amount\|all [--to-budget] [--date] [--note] [--raw]` | Menarik tabungan. |
| `savings spend --from <tabungan> --item ... [--item ...] --mode purpose\|debt [--date] [--raw]` | Belanja dari tabungan, atau pinjam dari tabungan. |
| `debt add --direction i_owe\|owed_to_me --person --amount [--account] [--budget] [--due] [--note] [--date] [--no-cash \| --paid-for "catatan\|kategori"] [--raw]` | Catat hutang atau piutang. |
| `debt pay (--person \| --id) [--direction] --amount\|all [--account] [--budget] [--date] [--note] [--raw]` | Catat pembayaran. Jika satu orang punya lebih dari satu hutang terbuka dan `--id` tidak diberikan, kembalikan `AMBIGUOUS_DEBT` beserta daftar ID. |
| `debt list [--status open\|paid\|all] [--person] [--direction] [--all]` | Daftar dengan sisa dan jatuh tempo, total hutang dan piutang, yang jatuh tempo dalam 7 hari. |
| `debt set (--person \| --id) [--direction] [--due \| --clear-due] [--note]` | Ubah jatuh tempo atau catatan. |
| `debt rename <nama> <baru>` | Ganti nama orang di semua catatannya (digabung jika nama baru sudah ada). |
| `debt remove (--person \| --id) [--direction] [--write-off]` | Hapus catatan. Lihat aturan hutang. |
| `recurring add <nama> --amount --day [--category] [--account]` | Tambah tagihan rutin, atau aktifkan kembali. |
| `recurring list [--all]` | Status bulan berjalan tiap tagihan, total per bulan, total yang belum dibayar. |
| `recurring pay <nama> [--amount] [--account] [--budget] [--date] [--month] [--raw]` | Catat pembayaran sebagai pengeluaran dan perbarui `last_paid_month`. |
| `recurring set <nama> [--amount] [--day] [--category] [--account]` / `rename <nama> <baru>` / `remove <nama>` | Kelola tagihan rutin. |
| `analyze --period ...` | Lihat bagian 8. |
| `export --period ... [--out]` | Buat .xlsx di `<folder data>\exports`. Kembalikan path file di `data.path`. |
| `daily-check --when pagi\|malam` | Lihat bagian 8. |
| `context` | Tanggal hari ini, dompet (nama, tipe, saldo, default), kategori, budget, tabungan, alias, kata kunci, hutang terbuka, tagihan rutin. Untuk pemanggil sebelum menyusun perintah. |
| `batch --file <path.json> \| --stdin` | Daftar `{"cmd": ..., "args": {...}}` untuk `add`, `transfer`, `adjust`, `budget alloc`, `budget move`, `debt add`, `debt pay`, `recurring pay`. Setiap entri di-parse oleh parser CLI yang sama; semua dalam satu transaksi database dan satu `group_id` (satu `undo`). Format lengkap di `COMMANDS.md`. |
| `backup` | Backup manual. |

## 8. Analisis, pengecekan harian, ekspor

**`analyze`** hanya menyiapkan fakta, tidak memberi nasihat. Isi `data`:

- total pemasukan, total pengeluaran, selisih, rasio menabung (persen pemasukan yang tersisa)
- pengeluaran per kategori: nominal, persen, jumlah transaksi
- perbandingan dengan periode sebelumnya yang sama panjang: selisih nominal dan persen, total dan per kategori
- rata-rata pengeluaran per hari, hari paling boros, jumlah hari tanpa pengeluaran
- 5 transaksi terbesar
- pengeluaran kecil yang sering (di bawah Rp20.000, catatan yang sama muncul lebih dari 5 kali): jumlah kali dan totalnya
- status budget: saldo tiap budget, total pengeluaran per budget pada periode itu, dan budget yang minus
- khusus bulan berjalan: proyeksi pengeluaran sampai akhir bulan berdasarkan rata-rata harian
- total hutang, piutang, dan yang jatuh tempo dalam 7 hari

`message` berisi ringkasan 5 sampai 8 baris yang bisa dibaca sendiri. Hindari pembagian dengan nol saat periode kosong atau pemasukan nol.

Detail perhitungan (`fin/analysis.py`):
- Periode sebelumnya: jika periode mulai tanggal 1, dibandingkan per bulan kalender dengan jumlah bulan yang sama (1–6 Oktober dengan 1–6 September; September penuh dengan Agustus penuh; `last:3` dengan tiga bulan sebelumnya). Selain itu digeser sejumlah hari periode. Persen perubahan `null` jika periode sebelumnya nol.
- Rasio menabung = selisih / pemasukan, `null` jika pemasukan nol. Rata-rata harian dan proyeksi dibulatkan ke rupiah terdekat dengan aritmetika integer.
- Pengeluaran kecil yang sering: catatan dibandingkan tanpa peka huruf besar kecil dan spasi berlebih.
- Proyeksi hanya untuk `this-month` (periode 1 bulan berjalan sampai hari ini): rata-rata harian × jumlah hari bulan itu.
- Jatuh tempo dalam 7 hari termasuk yang sudah lewat.

**`daily-check`** disiapkan untuk dipanggil penjadwal nanti. Backend hanya menyediakan perintahnya.
- `pagi`: tagihan rutin bulan berjalan yang belum dibayar dan jatuh temponya paling lambat 3 hari lagi (termasuk yang sudah lewat), dan hutang/piutang terbuka yang jatuh tempo paling lambat 3 hari lagi (termasuk yang lewat).
- `malam`: jika hari ini belum ada transaksi, pengingat singkat. Jika ada, total pengeluaran hari ini. Selalu `send: true`.
- Jika tidak ada yang perlu disampaikan: `"data": {"send": false}`. Jika ada: `"send": true`.

**`export`** (`openpyxl`, hanya dimuat saat ekspor): sheet Transaksi (periode itu), Ringkasan per kategori (periode itu), Saldo dompet (saat ini), Budget (saldo saat ini dan pengeluaran periode itu), Hutang piutang (yang tidak dihapus). Header tebal dan dibekukan, kolom nominal berformat angka, lebar kolom disesuaikan. Nama bawaan `<folder data>\exports\keuangan-<periode>-<YYYYMMDD-HHMMSS>.xlsx`; `--out` harus berakhiran `.xlsx`. File yang sedang dibuka Excel menghasilkan `BAD_ARGS` dengan hint.

## 9. Pengujian

**`pytest`** dengan database sementara (`FINANCE_HOME`, `USERPROFILE`, dan `HOME` diarahkan ke folder tmp untuk setiap tes, supaya data asli tidak pernah tersentuh) dan waktu dipalsukan lewat `--now`. Setiap pemanggilan di tes memeriksa aturan utama (total dompet = total budget) langsung dari tabel. Minimal mencakup:

- `parse_amount`: semua format di bagian 6 dan input tidak sah.
- Saldo benar setelah campuran income, expense, transfer dengan fee, adjustment, hutang.
- Transfer, hutang, dan alokasi budget tidak muncul di laporan pengeluaran maupun pemasukan.
- Batas periode: awal dan akhir bulan, pergantian tahun, `last:3` di bulan Januari, `this-week` di hari Senin.
- `add` dengan beberapa `--item`: semua tersimpan, atau tidak sama sekali jika satu item salah.
- `undo` membatalkan seluruh item dari satu pemanggilan, termasuk transfer beserta fee-nya, `budget alloc`, dan urutan campuran transaksi dan pindahan budget.
- `delete` dan `edit` mengubah saldo dengan benar; `edit` ganti kategori memindahkan budget.
- Aturan utama: ratusan perintah acak dengan seed tetap, total dompet = total budget setelah setiap perintah.
- Pemasukan selalu ke `belum teralokasi`; pengeluaran kategori tanpa budget memakai `belum teralokasi`, setelah diberi alokasi memakai budget kategorinya, transaksi lama tidak berubah.
- `budget alloc` banyak item: semua atau tidak sama sekali. Budget minus dan `belum teralokasi` minus: peringatan, bukan error.
- `budget close` mengembalikan sisa dengan benar, termasuk sisa minus. `--budget` pada `add`.
- Tabungan: deposit, withdraw, spend purpose, spend debt lalu lunas (sebagian dan penuh), saldo tabungan atau budget sumber tidak cukup, undo tiap operasi, hapus (`--move-to` dompet/tabungan, `--write-off`, pinjaman belum lunas), laporan memisahkan pengeluaran dari tabungan. Tes invarian acak mencakup operasi tabungan dan memeriksa total tabungan dari tabel.
- Migrasi dari database versi 3 yang berisi budget tabungan bersaldo.
- `account remove`: tanpa transaksi (hapus sungguhan), dengan transaksi (arsip), berisi tanpa opsi (`NOT_EMPTY`), `--move-to`, `--write-off`. `category remove` pada kategori yang punya budget dan pada kategori sistem (`SYSTEM_PROTECTED`). `adjust --actual 0`.
- Migrasi dari database versi 1 yang berisi dompet `savings` dan beberapa transaksi.
- Hutang: bayar sebagian, lunas, bayar berlebih ditolak, dua hutang untuk orang yang sama, `--no-cash`, `--paid-for` (saldo tetap, pengeluaran di laporan, undo sekaligus), undo, hapus.
- Tagihan rutin: bayar, bayar dua kali ditolak, `--month`, undo/hapus pembayaran mengembalikan `last_paid_month`, tanggal 31, dompet/kategori yang dihapus.
- Migrasi dari database versi 2.
- Dompet, kategori, atau budget tidak dikenal menghasilkan error dengan `hint`, tanpa mengubah data.
- `analyze` pada periode kosong tidak error; periode sebelumnya, rata-rata, pengeluaran kecil, budget minus, proyeksi. `daily-check` pagi dan malam. `export` (sheet, header, format angka, `--out`).
- Setiap perintah, termasuk saat argumen salah, mengeluarkan JSON yang sah.

**`demo.py`**: script yang membuat database baru di folder sementara, menjalankan skenario dua bulan (kira-kira 45 transaksi, dua dompet, alokasi budget, satu tabungan yang diisi tiap bulan dan dipakai sekali, satu hutang, satu piutang), lalu mencetak hasil `balance`, `report`, `budget list`, `savings list`, `debt list`, dan `analyze`. Angka akhir di demo harus diperiksa juga oleh sebuah tes.

**Skenario wajib lolos** (masuk ke tes sebagai tes end-to-end lewat subprocess):

| Maksud | Perintah |
|---|---|
| Beli ayam goreng 15k | `add --type expense --item "ayam goreng\|15k\|makan"` |
| Gajian 600k | `add --type income --item "gajian\|600k\|gaji"`, lalu `belum teralokasi` naik 600k |
| Jajan 10k dan es teh 3k | `add --type expense --item "jajan\|10k\|jajan" --item "es teh\|3k\|jajan"` |
| Jajan, parkir, makan total 50k | `add --type expense --item "jajan, parkir, makan\|50k\|makan"` |
| Alokasikan makan 300k, transport 100k | `budget alloc --item "makan\|300k" --item "transport\|100k"` |
| Nabung 100k | `savings deposit --from bri --to tabungan --amount 100k` |
| Pindah 50k dari makan ke jajan | `budget move --from makan --to jajan --amount 50k` |
| Sisa budget saya | `budget list` |
| Tabungan saya saat ini | `savings list` |
| Sisa uang di BRI | `balance --account bri` |
| Sisa uang total | `balance` |
| Pengeluaran bulan ini | `report --period this-month --type expense` |
| Pengeluaran Agustus | `report --period 2026-08 --type expense` |
| Pengeluaran 3 bulan terakhir | `report --period last:3 --type expense` |
| Analisis pengeluaran | `analyze --period this-month` |
| Tarik tunai 200k, admin 2.5k | `transfer --from bri --to tunai --amount 200k --fee 2.5k` |
| Tambah dompet gopay isi 50k | `account add gopay --type ewallet --opening 50k` |
| Hapus dompet gopay, sisanya ke bri | `account remove gopay --move-to bri` |
| Kosongkan dompet tunai | `adjust --account tunai --actual 0` |
| Tambah kategori "kucing" | `category add kucing --kind expense` |
| Hapus kategori hiburan | `category remove hiburan --kind expense` |
| Pinjam 50k dari Budi | `debt add --direction i_owe --person Budi --amount 50k` |
| Andi pinjam 100k | `debt add --direction owed_to_me --person Andi --amount 100k` |
| Bayar hutang Budi 20k | `debt pay --person Budi --amount 20k` |
| Bayar kos bulan ini | `recurring pay kos` |
| Saldo BRI sebenarnya 450k | `adjust --account bri --actual 450k` |
| Batalkan yang terakhir | `undo` |
| Ekspor bulan ini | `export --period this-month` |

## 10. Tahapan kerja

Pengguna membuat dompet, kategori, budget, dan tabungannya sendiri lewat perintah. `setup_awal.cmd` tidak wajib.

**Tahap 1: Inti.** (selesai) Struktur project, `db.py` dan migrasi, `parse_amount`, pembungkus JSON, lalu `init`, `account`, `category`, `alias`, `add`, `transfer`, `adjust`, `balance`, `report`, `list`, `edit`, `delete`, `undo`, backup otomatis, beserta tesnya.

**Tahap 1.5: Repo GitHub, kustomisasi penuh, budget amplop, tabungan.** (selesai) Lihat `docs\PERUBAHAN-01.md`. Model tabungan diganti menjadi akun terpisah setelah Tahap 4: `docs\PERUBAHAN-02.md`.

**Tahap 2: Hutang dan tagihan rutin.** (selesai) `debt` dan `recurring` dengan pola kustomisasi yang sama (tambah, ganti nama, hapus, daftar), beserta tesnya.
Checkpoint: beri pengguna sekitar 10 perintah terminal untuk dicoba sendiri, lengkap dengan hasil yang seharusnya muncul.

**Tahap 3: Analisis dan ekspor.** (selesai) `analyze`, `daily-check`, `export`, `demo.py`.
Checkpoint: pengguna menjalankan `python demo.py` dan membuka file Excel hasil ekspor.

**Tahap 4: Dokumentasi serah terima.** (selesai) Ditambah perintah `context` dan `batch`. Contoh di `COMMANDS.md` dijalankan sungguhan oleh `tools\commands_doc.py` (yang juga mengisi blok output-nya), dan `tests\test_commands_doc.py` memastikan setiap perintah dan opsi CLI terdokumentasi, setiap contoh termasuk contoh batch menghasilkan output yang tertulis, setiap perintah di tabel pemetaan chat valid, dan semua skenario wajib bagian 9 ada di tabel itu. Tulis `COMMANDS.md`: setiap perintah dengan semua opsinya, satu contoh pemanggilan, contoh output sukses, dan error yang mungkin muncul. Dokumen ini akan menjadi dasar integrasi dengan bot AI nanti, jadi harus lengkap dan cocok persis dengan perilaku kode. Buat tes yang memastikan setiap perintah di `COMMANDS.md` memang ada di CLI.

Setiap tahap: semua tes harus lolos, lalu commit git, perbarui `README.md`, lalu push ke GitHub.

## 11. Di luar cakupan

- Bot Telegram, integrasi dengan agen AI, dan pemrosesan chat bebas. Dikerjakan terpisah setelah backend selesai.
- Penjadwal (cron). Backend hanya menyediakan `daily-check` dan `analyze` untuk dipanggil nanti.
- Sinkronisasi otomatis dengan bank atau e-wallet.
- Multi pengguna dan multi mata uang.
- Antarmuka web atau dashboard.
