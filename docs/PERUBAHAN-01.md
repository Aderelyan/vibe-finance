# PERUBAHAN 01: Repo GitHub, kustomisasi penuh, dan budget sistem amplop

Dokumen ini untuk Claude Code. Isinya perubahan atas `BLUEPRINT.md` setelah Tahap 1 selesai. Jika ada yang bertentangan, dokumen ini yang berlaku. Kerjakan ini sebagai **Tahap 1.5**, sebelum Tahap 2.

Setelah selesai, perbarui `BLUEPRINT.md` dan `CLAUDE.md` supaya isinya cocok dengan dokumen ini, lalu simpan dokumen ini di folder `docs\`.

---

## A. Repo GitHub

- Remote: `https://github.com/Aderelyan/vibe-finance.git`. Repo ini kosong dan **publik**.
- Tambahkan sebagai `origin`, pakai branch `main`, lalu push commit yang sudah ada. Jangan pakai force push. Jika ternyata remote sudah berisi, berhenti dan tanyakan.
- Karena publik, sebelum push pertama periksa seluruh riwayat git: tidak boleh ada database, file backup, file ekspor, `setup_awal.cmd`, saldo asli, atau path yang memuat nama pengguna Windows. Jika ada, laporkan dulu, jangan langsung push.
- Pastikan `.gitignore` memuat `data/`, `*.db`, `*.xlsx`, `setup_awal.cmd`, `.venv/`.
- Push setiap kali satu tahap selesai dan semua tes lolos.

## B. Kustomisasi penuh lewat perintah

Pengguna nanti mengatur semuanya lewat chat, jadi setiap hal di bawah harus punya perintah CLI: tambah, ganti nama, hapus, dan lihat daftar.

| Hal | Perintah |
|---|---|
| Dompet | `account add / rename / remove / list / set-default` |
| Kategori pengeluaran dan pemasukan | `category add / rename / remove / list` |
| Budget | lihat bagian C |
| Tabungan | lihat bagian D |
| Alias dan kata kunci | `alias add / remove / list` (sudah ada) |
| Tagihan rutin, hutang | Tahap 2, dengan pola yang sama |

**Aturan `remove`** (berlaku untuk dompet, kategori, budget, tabungan):
- Belum pernah dipakai transaksi: dihapus sungguhan.
- Sudah pernah dipakai: diarsipkan, tidak muncul lagi di daftar dan tidak bisa dipilih, tetapi riwayat transaksinya tetap utuh. Dari sisi pengguna, hasilnya sama: "sudah dihapus".
- `message` menyebut mana yang terjadi.
- Menambah nama yang sama dengan yang sudah diarsipkan akan mengaktifkannya kembali.

**Hapus dompet yang masih ada isinya.** Aturan lama (harus saldo 0) diganti. Jika saldo tidak 0, perintah ditolak dengan `hint` yang menawarkan dua pilihan:
- `--move-to <dompet>`: sisa saldo dipindah dulu ke dompet lain (transfer).
- `--write-off`: sisa saldo dinolkan lewat penyesuaian.

Menghapus dompet default ditolak sampai default dipindah, kecuali memang tinggal satu dompet.

**Hapus kategori.** Jika kategori punya budget, budget itu ditutup dulu (bagian C). Kategori sistem tidak bisa dihapus atau diganti nama: `lainnya` (pengeluaran dan pemasukan) dan `biaya admin`.

**Ganti atau reset isi dompet.** Tetap memakai `adjust --account <nama> --actual <jumlah>`. Dua perubahan:
- `--actual 0` harus diterima. Saat ini `parse_amount` menolak nol, jadi buat pengecualian khusus untuk `--actual`.
- Selisihnya masuk ke atau keluar dari budget "belum teralokasi" (bagian C).

`setup_awal.cmd` tidak wajib lagi. Pengguna akan membuat dompetnya sendiri lewat perintah.

## C. Budget sistem amplop

Ini menggantikan rancangan budget lama (batas per bulan per kategori). Tabel `budgets` lama dan perintah `budget set / status` versi lama **tidak dibuat**. Butir "budget sistem amplop" di bagian "Di luar cakupan" pada blueprint dihapus.

### Konsep

Uang yang sama dilihat dari dua sisi:
- **Dompet**: uangnya ada di mana (tunai, bri).
- **Budget**: uangnya untuk apa (makan, transport, belum teralokasi).

**Aturan utama: total semua dompet selalu sama dengan total semua budget.** Ini harus benar setelah perintah apa pun.

### Aturan

1. Ada satu budget sistem bernama **`belum teralokasi`**. Tidak bisa dihapus atau diganti nama.
2. **Pemasukan selalu masuk ke `belum teralokasi`.** Tidak ada alokasi otomatis. Saldo awal dompet juga masuk ke sini.
3. **Alokasi hanya terjadi atas perintah pengguna**, lewat `budget alloc` atau `budget move`.
4. Budget pengeluaran menempel pada kategori pengeluaran, satu kategori satu budget. Kategori baru punya budget setelah pertama kali diberi alokasi.
5. **Pengeluaran** mengurangi budget milik kategorinya. Jika kategori itu belum punya budget, pengeluaran mengurangi `belum teralokasi`.
6. Budget boleh minus, tidak ditolak. `message` wajib memberi peringatan, misalnya "Budget makan minus Rp5.000". Begitu juga jika `belum teralokasi` minus, yang artinya alokasi melebihi uang yang ada.
7. Setiap `add` pengeluaran menampilkan sisa budget yang terpakai di `message`, di samping sisa dompet.
8. Transfer antar dompet tidak mengubah budget apa pun. Biaya admin tetap pengeluaran kategori `biaya admin`.
9. `adjust`: selisihnya masuk ke atau keluar dari `belum teralokasi`.
10. Hutang piutang (Tahap 2): uang masuk menambah `belum teralokasi`. Uang keluar mengurangi `belum teralokasi`, kecuali diberi `--budget`.
11. Riwayat tidak ditulis ulang. Transaksi lama tetap tercatat pada budget yang berlaku saat transaksi itu dibuat.
12. `edit` yang mengganti kategori memindahkan transaksi itu ke budget kategori barunya.
13. Opsi `--budget <nama>` pada `add` pengeluaran: memaksa pengeluaran diambil dari budget tertentu, termasuk dari tabungan.

### Penyimpanan

Saldo budget tidak disimpan, selalu dihitung, sama seperti saldo dompet.

```sql
CREATE TABLE budgets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  kind TEXT NOT NULL CHECK (kind IN ('unallocated','category','savings')),
  category_id INTEGER UNIQUE REFERENCES categories(id),   -- hanya kind category
  target_amount INTEGER,                                  -- hanya kind savings
  target_date TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

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

ALTER TABLE transactions ADD COLUMN budget_id INTEGER REFERENCES budgets(id);
```

- `transactions.budget_id` wajib terisi untuk `income`, `expense`, `adjustment`, `debt_in`, `debt_out`, dan kosong untuk `transfer`. Pastikan lewat kode dan tes.
- Saldo budget = jumlah bertanda transaksi yang menunjuk ke budget itu, ditambah pindahan masuk, dikurangi pindahan keluar. Yang terhapus tidak dihitung.
- Migrasi ke `schema_version` 2: buat budget `belum teralokasi`, lalu isi `budget_id` semua transaksi lama dengan budget itu.

### Perintah

| Perintah | Fungsi |
|---|---|
| `budget list` | Semua budget dan saldonya: `belum teralokasi`, budget kategori, tabungan, lalu total. |
| `budget alloc --item "makan\|300k" [--item ...] [--note]` | Alokasi dari `belum teralokasi` ke satu atau banyak budget dalam satu pemanggilan. Satu `group_id`. Jika satu item tidak sah, tidak ada yang tersimpan. Nama boleh kategori pengeluaran atau tabungan. |
| `budget move --from --to --amount [--note]` | Pindah antar budget mana pun. `--amount all` memindahkan seluruh sisa. |
| `budget close <nama>` | Sisa saldo (plus atau minus) dikembalikan ke `belum teralokasi`, lalu budget ditutup. Kategorinya tetap ada dan kembali memakai `belum teralokasi`. |
| `budget history [--budget] [--period]` | Riwayat alokasi dan pindahan. |

Perubahan pada perintah lama:
- `balance` tanpa argumen menampilkan dua bagian: per dompet dan per budget. `data` memuat `total_dompet`, `total_budget`, dan `consistent` (true jika sama).
- `undo` juga membatalkan `budget alloc` dan `budget move` terakhir. Pembatalan mengikuti urutan waktu gabungan antara transaksi dan pindahan budget.
- `report` tidak berubah. Alokasi dan pindahan budget bukan pengeluaran.
- `analyze` (Tahap 3): bagian "status budget" diisi saldo tiap budget, total pengeluaran per budget pada periode itu, dan budget yang minus.
- Peringatan budget 80% dan 100% dari blueprint lama dihapus, diganti aturan 6 dan 7 di atas.

Kode error baru: `UNKNOWN_BUDGET`, `SYSTEM_PROTECTED` (mencoba menghapus atau mengganti nama milik sistem), `NOT_EMPTY` (hapus dompet yang masih berisi tanpa opsi).

## D. Tabungan

Tabungan sekarang adalah **budget berjenis `savings`**, bukan dompet. Uangnya tetap berada di dompet mana pun. Yang dicatat adalah tujuannya.

- Tipe dompet `savings` beserta kolom `target_amount` dan `target_date` di tabel `accounts` dihapus. Tipe dompet tinggal `cash`, `bank`, `ewallet`.
- Migrasi: dompet bertipe `savings` diubah menjadi `bank`. Lalu buat tabungan dengan nama dan target yang sama, dan pindahkan uang sebesar saldo dompet itu dari `belum teralokasi` ke tabungan tersebut. Jika nama dompet dan nama tabungan jadi sama, itu tidak masalah karena tabelnya berbeda.
- Boleh ada banyak tabungan, misalnya "dana darurat" dan "tabungan laptop".
- Menabung = `budget alloc` atau `budget move` ke tabungan. Menarik tabungan = `budget move` dari tabungan ke budget lain.
- Menabung bukan pengeluaran dan tidak mengurangi total uang.
- Membelanjakan tabungan langsung: `add --type expense --budget "tabungan laptop" --item "laptop|5jt|belanja"`.

| Perintah | Fungsi |
|---|---|
| `savings add <nama> [--target] [--target-date]` | Buat tabungan. |
| `savings list` | Saldo, target, persen tercapai, kekurangan, dan setoran bersih bulan ini untuk tiap tabungan, lalu total. Menggantikan perintah `savings` lama. |
| `savings set-target <nama> [--target] [--target-date]` | Ubah atau hapus target. |
| `savings rename / remove` | `remove` mengembalikan sisa ke `belum teralokasi`, lalu mengikuti aturan hapus di bagian B. |

`balance` menampilkan subtotal tabungan dan subtotal uang di luar tabungan, dihitung dari sisi budget.

## E. Keputusan Tahap 1 yang sudah kamu ambil

Disetujui: dompet default otomatis, kata kunci bawaan, `unarchive`, periode berhenti di hari ini, database dibuat otomatis, dan nominal transaksi hutang tidak bisa diedit.

Diubah: aturan arsip dompet (lihat bagian B). Dompet default otomatis sekarang cukup "dompet pertama", karena tipe `savings` sudah tidak ada.

## F. Pengujian

Tambahkan ke `pytest`:

- **Aturan utama**: tes yang menjalankan ratusan perintah acak (add, transfer, adjust, alloc, move, edit, delete, undo, hapus dompet, tutup budget, hapus kategori) dengan seed tetap, dan setelah setiap perintah memeriksa total dompet sama dengan total budget.
- Pemasukan selalu menambah `belum teralokasi`, apa pun kategorinya.
- Pengeluaran di kategori tanpa budget mengurangi `belum teralokasi`. Setelah kategori itu diberi alokasi, pengeluaran berikutnya mengurangi budget kategorinya, dan transaksi lama tidak berubah.
- `budget alloc` banyak item: semua tersimpan atau tidak sama sekali.
- Budget minus dan `belum teralokasi` minus menghasilkan peringatan, bukan error.
- `budget close` dan `savings remove` mengembalikan sisa dengan benar, termasuk saat sisanya minus.
- `account remove`: tanpa transaksi (hapus sungguhan), dengan transaksi (arsip), berisi saldo tanpa opsi (`NOT_EMPTY`), `--move-to`, `--write-off`.
- `category remove` pada kategori yang punya budget, dan pada kategori sistem (`SYSTEM_PROTECTED`).
- `adjust --actual 0`.
- `undo` setelah `budget alloc`, dan urutan undo campuran antara transaksi dan pindahan budget.
- `edit` ganti kategori memindahkan budget.
- `--budget` pada `add`, termasuk dari tabungan.
- Migrasi dari database versi 1 yang berisi dompet `savings` dan beberapa transaksi.

Skenario wajib lolos yang berubah atau baru:

| Maksud | Perintah |
|---|---|
| Gajian 600k | `add --type income --item "gajian\|600k\|gaji"`, lalu `belum teralokasi` naik 600k |
| Alokasikan makan 300k, transport 100k | `budget alloc --item "makan\|300k" --item "transport\|100k"` |
| Nabung 100k | `budget alloc --item "tabungan\|100k"` |
| Pindah 50k dari makan ke jajan | `budget move --from makan --to jajan --amount 50k` |
| Sisa budget saya | `budget list` |
| Tabungan saya saat ini | `savings list` |
| Tambah dompet gopay isi 50k | `account add gopay --type ewallet --opening 50k` |
| Hapus dompet gopay, sisanya ke bri | `account remove gopay --move-to bri` |
| Kosongkan dompet tunai | `adjust --account tunai --actual 0` |
| Tambah kategori "kucing" | `category add kucing --kind expense` |
| Hapus kategori hiburan | `category remove hiburan --kind expense` |

Skenario lama "Budget makan 600k sebulan" (`budget set`) dan "Nabung 100k dari BRI" (transfer ke dompet tabungan) dihapus.

## G. Urutan kerja Tahap 1.5

1. Bagian A: sambungkan dan push ke GitHub.
2. Migrasi skema ke versi 2 beserta tes migrasinya.
3. Budget (bagian C), lalu tabungan (bagian D).
4. Aturan hapus dan ganti nama (bagian B).
5. Tes di bagian F, perbarui `README.md`, `BLUEPRINT.md`, `CLAUDE.md`.
6. Checkpoint: beri pengguna sekitar 12 perintah untuk dicoba sendiri beserta hasil yang seharusnya muncul. Urutannya: buat dompet, gajian, lihat `balance`, alokasi, belanja, pindah budget, nabung, hapus dompet, lalu `balance` lagi.

Tahap 2 setelah ini tinggal hutang piutang dan tagihan rutin.
