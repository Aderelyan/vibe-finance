# COMMANDS: referensi lengkap `finance.py`

Dokumen ini adalah kontrak antara backend dan pemanggilnya (misalnya bot AI). Isinya setiap perintah beserta semua
opsinya, satu atau lebih contoh pemanggilan, contoh output, dan error yang mungkin muncul.

Semua contoh di dokumen ini **dijalankan sungguhan** secara berurutan, pada database baru dengan waktu tetap
`2026-10-06 12:00:00` (Selasa). Blok output JSON dihasilkan oleh `tools\commands_doc.py`, dan
`tests\test_commands_doc.py` memastikan output itu masih sama persis dengan perilaku kode. Jadi contoh-contoh di sini
saling bersambung: saldo di satu contoh adalah akibat dari contoh-contoh sebelumnya.

Di contoh output:
- `<FINANCE_HOME>` adalah folder data (bawaan `<profil pengguna>\Documents\Manager\Finance\data`).
- `"<acak>"` adalah nilai acak (`group_id`), berbeda di setiap pemanggilan.
- Daftar yang panjang dipotong menjadi 3 elemen pertama. Output asli berisi semuanya.

## Cara memanggil

Dari terminal Windows di folder project:

```
.venv\Scripts\python finance.py <perintah> [opsi]
```

Dari bash (MSYS / Git Bash), misalnya oleh bot, pakai pembungkus `fin.sh` di root project. Contoh di dokumen ini
diawali `python finance.py`; lewat bash ganti awalan itu dengan `bash <path>/fin.sh`, sisanya sama persis.

```bash
bash C:/path/ke/vibe-finance/fin.sh context
bash C:/path/ke/vibe-finance/fin.sh add --type expense --item "ayam goreng|15k|makan"
bash C:/path/ke/vibe-finance/fin.sh adjust --account tunai --actual=-5k

bash C:/path/ke/vibe-finance/fin.sh batch --stdin <<'EOF'
[
  {"cmd": "add", "args": {"type": "expense", "item": ["nasi padang|20k|makan", "es teh|3k"]}},
  {"cmd": "budget alloc", "args": {"item": "makan|100k"}}
]
EOF
```

Yang dilakukan `fin.sh`:
- Mencari foldernya sendiri, jadi bisa dipanggil dari folder mana pun lewat path apa pun. Folder kerja pemanggil
  tidak diubah, jadi path relatif (`batch --file x.json`, `export --out x.xlsx`) tetap relatif ke folder pemanggil.
- Jika `FINANCE_HOME` belum diisi, memakai `<profil pengguna Windows>/Documents/Manager/Finance/data`
  (dari `USERPROFILE`). Jika sudah diisi, tidak ditimpa; path MSYS diubah ke bentuk Windows yang sama
  (`/c/data` → `C:/data`, `/tmp/x` → folder Windows yang dipakai MSYS untuk `/tmp`).
- Mengisi `PYTHONIOENCODING=utf-8` dan `PYTHONUTF8=1`.
- Menjalankan `.venv/Scripts/python.exe finance.py "$@"`: semua argumen diteruskan apa adanya, termasuk spasi, `|`,
  `--actual=-5k`, dan teks yang diawali `/` (konversi path otomatis MSYS dimatikan). Stdin tetap tersambung
  (`batch --stdin` dengan heredoc), exit code diteruskan.
- Stdout hanya berisi output `finance.py`. Jika `.venv` tidak ada, stdout berisi JSON
  `{"ok": false, "error": {"code": "INTERNAL", ...}}` dengan petunjuk membuat `.venv`, dan exit code 1.

Dengan heredoc, pakai `<<'EOF'` (bertanda kutip) supaya `$` dan `` ` `` di dalam JSON tidak diproses bash.

## Daftar isi

1. [Aturan umum](#aturan-umum): bentuk output, exit code, kode error
2. [Menulis nilai](#menulis-nilai): nominal, nilai negatif, tanggal, periode, item dengan tanda `|`
3. [Perintah](#perintah): persiapan, dompet, kategori, alias, transaksi, laporan, budget, tabungan, hutang, tagihan
   rutin, analisis, `context`, `batch`
4. [Cara memetakan chat ke perintah](#cara-memetakan-chat-ke-perintah)

---

## Aturan umum

Bentuk umum: `python finance.py <perintah> [aksi] [opsi]`. Tidak pernah ada pertanyaan interaktif; semua lewat argumen.

**Output selalu tepat satu objek JSON** di stdout, tanpa teks lain, dalam UTF-8.

Berhasil:

```
{"ok": true, "message": "<kalimat bahasa Indonesia, siap dikirim ke pengguna>", "data": {...}}
```

Gagal:

```
{"ok": false, "error": {"code": "<KODE>", "message": "<penjelasan>", "hint": "<cara memperbaiki atau null>", "data": {...}}}
```

- `error.data` hanya ada pada sebagian error (misalnya daftar kandidat pada `AMBIGUOUS_DEBT`).
- Exit code `0` jika `ok` true, `1` jika false.
- Jika gagal, **tidak ada data yang berubah**.
- `message` boleh berisi beberapa baris (`\n`).
- Nominal di `data` selalu integer rupiah. Di `message` ditulis `Rp15.000`.
- Waktu di `data` berbentuk `YYYY-MM-DD HH:MM:SS` (waktu lokal), tanggal `YYYY-MM-DD`.
- `python finance.py <perintah> --help` juga membalas JSON: `{"ok": true, "message": "<teks bantuan>", "data": {"help": "..."}}`.

Lingkungan:

| Nama | Arti |
|---|---|
| `FINANCE_HOME` | Folder data (`finance.db`, `backups\`, `exports\`). Bawaan: `%USERPROFILE%\Documents\Manager\Finance\data` di Windows, `~/Documents/Manager/Finance/data` di Linux/Mac. `finance.py` dan `fin.sh` memakai bawaan yang sama. |
| `--now "YYYY-MM-DD HH:MM:SS"` | Opsi global tersembunyi, boleh di posisi mana pun: memalsukan waktu sekarang. Untuk tes dan demo. |
| `FINANCE_NOW` | Sama dengan `--now`, lewat environment variable. |

### Kode error

| Kode | Arti | Yang sebaiknya dilakukan pemanggil |
|---|---|---|
| `BAD_ARGS` | Argumen tidak sah: opsi salah atau kurang, kombinasi opsi yang tidak boleh, format `--item` salah, nama sudah dipakai, sesuatu yang dilarang aturan (misalnya membayar tagihan dua kali di bulan yang sama). | Baca `message` dan `hint`, perbaiki perintahnya. |
| `BAD_AMOUNT` | Nominal tidak bisa dibaca, nol, negatif (jika tidak boleh), atau terlalu besar; atau saldo tabungan / budget sumber tidak cukup untuk `savings` (`error.data` berisi saldonya). | Tanyakan ulang nominalnya ke pengguna. |
| `BAD_DATE` | Tanggal tidak bisa dibaca, atau tanggal transaksi di masa depan. | Pakai `YYYY-MM-DD`, `today`, atau `yesterday`. |
| `BAD_PERIOD` | Periode tidak dikenal, terbalik, atau di masa depan. | Pakai salah satu bentuk periode di bawah. |
| `UNKNOWN_ACCOUNT` | Dompet atau tabungan tidak ada atau sudah dihapus, atau jenisnya salah (tabungan dipakai di tempat dompet, atau sebaliknya). `hint` berisi daftar yang sah. | Pilih dari `hint`, atau tanyakan ke pengguna. Jangan membuat dompet baru diam-diam. |
| `UNKNOWN_CATEGORY` | Kategori tidak ada atau sudah dihapus. `hint` berisi daftar kategori. | Pilih dari `hint`, atau kosongkan kategori supaya ditebak. |
| `UNKNOWN_BUDGET` | Budget tidak ada, sudah ditutup, atau kategori itu belum punya budget. Nama tabungan dipakai sebagai budget juga menghasilkan ini (tabungan bukan budget). | Lihat `hint`; kategori tanpa budget bisa diberi alokasi dulu; untuk tabungan pakai perintah `savings`. |
| `NOT_FOUND` | Transaksi, alias, hutang, atau tagihan rutin yang dimaksud tidak ada. | Cek ID atau nama lewat perintah `list`. |
| `NO_DEFAULT_ACCOUNT` | Dompet tidak disebut dan belum ada dompet default. | Sebutkan `--account`, atau atur `account set-default`. |
| `AMBIGUOUS_DEBT` | Satu orang punya lebih dari satu hutang/piutang yang cocok. `error.data.candidates` berisi daftar ID beserta sisanya. | Tanyakan yang mana, lalu ulangi dengan `--id`. |
| `OVERPAYMENT` | Pembayaran melebihi sisa hutang, atau hutangnya sudah lunas. `error.data.remaining` berisi sisa. | Tawarkan membayar sebesar sisa (`--amount all`). |
| `NOTHING_TO_UNDO` | Tidak ada pencatatan uang yang bisa dibatalkan. | Sampaikan ke pengguna. |
| `NOT_EMPTY` | Menghapus dompet, tabungan, atau hutang yang masih bersisa tanpa opsi penyelesaian, atau tabungan yang masih punya pinjaman. `hint` berisi pilihannya. | Tanyakan pilihan ke pengguna. |
| `SYSTEM_PROTECTED` | Mencoba menghapus, menutup, atau mengganti nama milik sistem (`belum teralokasi`, kategori `lainnya`, `biaya admin`). | Sampaikan bahwa itu tidak bisa diubah. |
| `INTERNAL` | Kesalahan tak terduga di program. Perubahan dibatalkan. | Laporkan ke pengembang. |

`BAD_ARGS` dan `INTERNAL` bisa muncul di perintah mana pun dan tidak diulang di daftar error tiap perintah.

---

## Menulis nilai

### Nominal

Diterima: `15000`, `15.000`, `15,000`, `15k`, `15rb`, `15 ribu`, `1,5jt`, `1.5jt`, `2 juta`, `Rp15.000`, `rp 15.000`.

- Titik dan koma sebelum `jt`/`juta` adalah desimal (`1.5jt` = 1.500.000). Tanpa akhiran, keduanya pemisah ribuan
  (`15.000` = 15.000). `,00` di belakang ala bank diterima (`15.000,00`).
- Hasilnya harus rupiah bulat. Nol dan negatif ditolak (`BAD_AMOUNT`), kecuali pada `--opening` (`account add`) dan
  `--actual` (`adjust`) yang menerima nol dan negatif.
- Beberapa opsi menerima `all` sebagai nominal: `budget move --amount all` (seluruh sisa budget) dan
  `debt pay --amount all` (seluruh sisa hutang).

### Nilai negatif

Nilai yang diawali `-` harus ditulis menempel dengan tanda sama dengan, supaya tidak dibaca sebagai opsi:

```
python finance.py adjust --account tunai --actual=-5k
python finance.py account add kartu --type bank --opening=-250k
```

`--actual -5k` (dengan spasi) ditolak sebagai `BAD_ARGS`.

### Tanggal

- `--date` (waktu transaksi): `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, `today`, `yesterday`. Tidak boleh di masa depan. Jika
  hanya tanggal, jam diisi jam sekarang. Tanpa `--date` = sekarang.
- `--due`, `--target-date`: `YYYY-MM-DD`, boleh di masa depan.
- `--month` (tagihan rutin): `YYYY-MM`.

### Periode

Dipakai `report`, `list`, `budget history`, `analyze`, `export`. Bawaan: `this-month`.

| Nilai | Arti |
|---|---|
| `today`, `yesterday` | Hari ini, kemarin |
| `this-week`, `last-week` | Senin sampai hari ini; Senin sampai Minggu minggu lalu |
| `this-month`, `last-month` | Tanggal 1 sampai hari ini; bulan lalu penuh |
| `YYYY-MM` | Satu bulan kalender, contoh `2026-08` |
| `last:N` | Bulan berjalan ditambah N−1 bulan sebelumnya, contoh `last:3` |
| `all` | Sejak transaksi pertama |
| `--from YYYY-MM-DD [--to YYYY-MM-DD]` | Rentang bebas (tidak boleh digabung dengan `--period`) |

Akhir periode tidak pernah melewati hari ini. Rentang tanggal persisnya selalu ada di `message` dan `data.period`.

### Item dengan tanda `|`

`add --item` dan `budget alloc --item` memakai `|` untuk memisahkan bagian:

| Opsi | Format | Contoh |
|---|---|---|
| `add --item` | `catatan\|jumlah` atau `catatan\|jumlah\|kategori` | `"ayam goreng\|15k\|makan"`, `"es teh\|3k"` |
| `budget alloc --item` | `budget\|jumlah` | `"makan\|300k"`, `"transport\|100k"` |
| `savings spend --item` | sama dengan `add --item` | `"kacamata\|40k\|kesehatan"` |
| `debt add --paid-for` | `catatan` atau `catatan\|kategori` | `"makan siang\|makan"`, `"bakso"` |

- `--item` boleh diulang; semua item satu pemanggilan disimpan bersama atau tidak sama sekali.
- **Selalu beri tanda kutip** di sekitar nilai yang berisi `|`, karena `|` adalah pipa di shell: `--item "kopi|8k"`.
  Jika memanggil lewat program dengan daftar argumen (misalnya `subprocess.run([...])`), tanda kutip tidak perlu.
- Catatan dan nama tidak boleh berisi `|`.
- Kategori yang dikosongkan ditebak dari kata kunci di catatan (lihat `alias`), dan jika tidak ada yang cocok
  dipakai `lainnya`. `message` selalu menyebut kategori yang dipakai.
- Nama yang berisi spasi ditulis dengan tanda kutip: `--account "bri utama"`, `savings add "dana darurat"`.

---

## Perintah

### Persiapan

### `init`

Membuat database dan data awal (kategori bawaan, kata kunci tebak kategori, budget `belum teralokasi`). Aman
dijalankan ulang. Database juga dibuat otomatis oleh perintah lain jika belum ada.

Tanpa opsi.

```bat
python finance.py init
```
```json
{
  "ok": true,
  "message": "Database baru dibuat di <FINANCE_HOME>\\finance.db dengan 18 kategori bawaan. Belum ada dompet. Tambahkan dengan: account add <nama> --type cash|bank|ewallet --opening <saldo>.",
  "data": {
    "path": "<FINANCE_HOME>\\finance.db",
    "created": true,
    "schema_version": 4,
    "accounts": 0,
    "categories": 18
  }
}
```

Error: tidak ada yang khusus.

### `backup`

Menyalin database ke `backups\finance-YYYYMMDD-HHMMSS.db`. Selain itu ada backup otomatis pada operasi tulis
pertama setiap hari; 30 file terakhir disimpan.

Tanpa opsi.

```bat
python finance.py backup
```
```json
{
  "ok": true,
  "message": "Backup tersimpan di <FINANCE_HOME>\\backups\\finance-20261006-120000.db.",
  "data": {
    "path": "<FINANCE_HOME>\\backups\\finance-20261006-120000.db"
  }
}
```

Error: tidak ada yang khusus.

---

### Dompet

### `account add`

Menambah dompet, atau mengaktifkan kembali dompet yang pernah dihapus (nama sama). Dompet pertama otomatis menjadi
default.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama dompet. |
| `--type cash\|bank\|ewallet` | ya | Jenis dompet. |
| `--opening <nominal>` | | Saldo awal, masuk ke budget `belum teralokasi`. Boleh 0 dan negatif (`--opening=-50k`). |
| `--default` | | Jadikan dompet default. |

```bat
python finance.py account add tunai --type cash --opening 150k --default
```
```json
{
  "ok": true,
  "message": "Dompet tunai (tunai) dibuat dengan saldo awal Rp150.000. +Rp150.000 masuk ke budget belum teralokasi. Dijadikan dompet default.",
  "data": {
    "account": {
      "id": 1,
      "name": "tunai",
      "type": "cash",
      "is_default": true,
      "archived": false,
      "balance": 150000
    },
    "reactivated": false
  }
}
```

```bat
python finance.py account add bri --type bank --opening 500k
```
```json
{
  "ok": true,
  "message": "Dompet bri (bank) dibuat dengan saldo awal Rp500.000. +Rp500.000 masuk ke budget belum teralokasi.",
  "data": {
    "account": {
      "id": 2,
      "name": "bri",
      "type": "bank",
      "is_default": false,
      "archived": false,
      "balance": 500000
    },
    "reactivated": false
  }
}
```

```bat
python finance.py account add gopay --type ewallet --opening 50k
```
```json
{
  "ok": true,
  "message": "Dompet gopay (e-wallet) dibuat dengan saldo awal Rp50.000. +Rp50.000 masuk ke budget belum teralokasi.",
  "data": {
    "account": {
      "id": 3,
      "name": "gopay",
      "type": "ewallet",
      "is_default": false,
      "archived": false,
      "balance": 50000
    },
    "reactivated": false
  }
}
```

Error: `BAD_AMOUNT` (saldo awal), `BAD_ARGS` (nama sudah dipakai dompet atau alias lain, kosong, lebih dari 40
huruf).

### `account list`

Daftar dompet beserta saldo.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--all` | | Sertakan dompet yang sudah dihapus (diarsipkan). |

```bat
python finance.py account list
```
```json
{
  "ok": true,
  "message": "Daftar dompet:\n- tunai (tunai): Rp150.000 [default]\n- bri (bank): Rp500.000\n- gopay (e-wallet): Rp50.000",
  "data": {
    "accounts": [
      {
        "id": 1,
        "name": "tunai",
        "type": "cash",
        "is_default": true,
        "archived": false,
        "balance": 150000
      },
      {
        "id": 2,
        "name": "bri",
        "type": "bank",
        "is_default": false,
        "archived": false,
        "balance": 500000
      },
      {
        "id": 3,
        "name": "gopay",
        "type": "ewallet",
        "is_default": false,
        "archived": false,
        "balance": 50000
      }
    ]
  }
}
```

Error: tidak ada yang khusus.

### `account rename`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama atau alias dompet sekarang. |
| `<new_name>` | ya | Nama baru. |

```bat
python finance.py account rename gopay "gopay lama"
```
```json
{
  "ok": true,
  "message": "Dompet gopay diganti nama menjadi gopay lama.",
  "data": {
    "id": 3,
    "old_name": "gopay",
    "name": "gopay lama"
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `BAD_ARGS` (nama baru sudah dipakai).

### `account remove`

Belum pernah dipakai: dihapus sungguhan. Sudah pernah dipakai: diarsipkan (riwayat tetap ada). Dompet yang masih
berisi ditolak dengan `NOT_EMPTY` kecuali diberi salah satu opsi. Dompet default ditolak selama masih ada dompet lain.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama atau alias dompet. |
| `--move-to <dompet>` | | Sisa saldo dipindah ke dompet ini lewat transfer. |
| `--write-off` | | Sisa saldo dinolkan lewat penyesuaian; `belum teralokasi` ikut berubah. |

Tanpa opsi, dompet yang masih berisi:

```bat
python finance.py account remove "gopay lama"
```
```json
{
  "ok": false,
  "error": {
    "code": "NOT_EMPTY",
    "message": "Dompet gopay lama masih berisi Rp50.000.",
    "hint": "Pilih salah satu: account remove gopay lama --move-to tunai (sisa dipindah ke dompet lain), atau account remove gopay lama --write-off (sisa dinolkan, budget belum teralokasi ikut berkurang).",
    "data": {
      "balance": 50000
    }
  }
}
```

Dengan `--move-to`:

```bat
python finance.py account remove "gopay lama" --move-to bri
```
```json
{
  "ok": true,
  "message": "Dompet gopay lama dihapus. Riwayat transaksinya tetap disimpan (diarsipkan). Sisa Rp50.000 dipindah ke bri. Sisa bri Rp550.000.",
  "data": {
    "id": 3,
    "name": "gopay lama",
    "mode": "archived",
    "balance_before": 50000,
    "moved_to": "bri",
    "written_off": false
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `NOT_EMPTY`, `BAD_ARGS` (dompet default, tujuan sama dengan asal).

### `account set-default`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Dompet yang dipakai jika `--account` tidak disebut. |

```bat
python finance.py account set-default tunai
```
```json
{
  "ok": true,
  "message": "Dompet default sekarang tunai.",
  "data": {
    "id": 1,
    "name": "tunai"
  }
}
```

Error: `UNKNOWN_ACCOUNT`.

---

### Kategori

Kategori bawaan. Pengeluaran: makan, jajan, transport, belanja, tempat tinggal, pulsa & internet, pendidikan,
kesehatan, hiburan, tagihan, biaya admin, sedekah, lainnya. Pemasukan: gaji, uang saku, freelance, bonus, lainnya.

### `category add`

Menambah kategori, atau mengaktifkan kembali yang pernah dihapus. Kategori pengeluaran baru belum punya budget;
pengeluarannya memakai `belum teralokasi` sampai diberi alokasi.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama kategori. |
| `--kind expense\|income` | ya | Jenis kategori. |

```bat
python finance.py category add kucing --kind expense
```
```json
{
  "ok": true,
  "message": "Kategori pengeluaran 'kucing' ditambahkan. Belum punya budget; pengeluarannya memakai belum teralokasi sampai diberi alokasi.",
  "data": {
    "id": 19,
    "name": "kucing",
    "kind": "expense",
    "reactivated": false
  }
}
```

Error: `BAD_ARGS` (sudah ada, bentrok dengan alias atau nama budget lain), `SYSTEM_PROTECTED` (nama `belum teralokasi`).

### `category list`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--kind expense\|income` | | Hanya satu jenis. |
| `--all` | | Sertakan kategori yang sudah dihapus. |

```bat
python finance.py category list --kind income
```
```json
{
  "ok": true,
  "message": "Kategori pemasukan: gaji, uang saku, freelance, bonus, lainnya.",
  "data": {
    "categories": [
      {
        "id": 14,
        "name": "gaji",
        "kind": "income",
        "archived": false,
        "has_budget": false,
        "keywords": [
          "gaji",
          "gajian"
        ]
      },
      {
        "id": 15,
        "name": "uang saku",
        "kind": "income",
        "archived": false,
        "has_budget": false,
        "keywords": [
          "kiriman",
          "uang saku"
        ]
      },
      {
        "id": 16,
        "name": "freelance",
        "kind": "income",
        "archived": false,
        "has_budget": false,
        "keywords": [
          "freelance",
          "project",
          "proyek"
        ]
      }
    ]
  }
}
```

Error: tidak ada yang khusus.

### `category rename`

Budget milik kategori itu ikut berganti nama.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama atau alias kategori. |
| `<new_name>` | ya | Nama baru. |
| `--kind expense\|income` | | Wajib jika nama ada di pemasukan dan pengeluaran (misalnya `lainnya`). |

```bat
python finance.py category rename kucing "kucing oren" --kind expense
```
```json
{
  "ok": true,
  "message": "Kategori pengeluaran 'kucing' diganti nama menjadi 'kucing oren'.",
  "data": {
    "id": 19,
    "old_name": "kucing",
    "name": "kucing oren",
    "kind": "expense"
  }
}
```

Error: `UNKNOWN_CATEGORY`, `SYSTEM_PROTECTED`, `BAD_ARGS` (nama ambigu tanpa `--kind`, nama baru sudah dipakai).

### `category remove`

Jika kategori punya budget, budget itu ditutup dulu dan sisanya kembali ke `belum teralokasi`. Belum pernah dipakai:
dihapus sungguhan; sudah dipakai: diarsipkan.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama atau alias kategori. |
| `--kind expense\|income` | | Wajib jika nama ada di kedua jenis. |

```bat
python finance.py category remove hiburan --kind expense
```
```json
{
  "ok": true,
  "message": "Kategori pengeluaran 'hiburan' dihapus permanen karena belum pernah dipakai.",
  "data": {
    "id": 9,
    "name": "hiburan",
    "kind": "expense",
    "mode": "deleted",
    "budget_closed": false,
    "returned_to_unallocated": 0
  }
}
```

Kategori sistem:

```bat
python finance.py category remove "biaya admin"
```
```json
{
  "ok": false,
  "error": {
    "code": "SYSTEM_PROTECTED",
    "message": "Kategori 'biaya admin' dipakai sistem dan tidak bisa dihapus.",
    "hint": null
  }
}
```

Error: `UNKNOWN_CATEGORY`, `SYSTEM_PROTECTED`, `BAD_ARGS` (nama ambigu).

---

### Alias dan kata kunci

Alias `account`/`category` adalah nama lain yang diterima di mana pun nama dompet/kategori diminta. Alias `keyword`
adalah kata kunci untuk menebak kategori dari catatan (`add` tanpa kategori).

### `alias add`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--kind account\|category\|keyword` | ya | Jenis alias. |
| `--alias <teks>` | ya | Nama lain atau kata kunci. |
| `--target <nama>` | ya | Dompet (kind `account`) atau kategori tujuan. |
| `--target-kind expense\|income` | | Jenis kategori tujuan jika namanya ada di keduanya. |

```bat
python finance.py alias add --kind account --alias cash --target tunai
```
```json
{
  "ok": true,
  "message": "'cash' sekarang dikenali sebagai dompet tunai.",
  "data": {
    "id": 84,
    "kind": "account",
    "alias": "cash",
    "target": "tunai",
    "target_id": 1
  }
}
```

```bat
python finance.py alias add --kind keyword --alias mixue --target jajan
```
```json
{
  "ok": true,
  "message": "'mixue' sekarang dikenali sebagai kategori pengeluaran jajan (kata kunci tebakan).",
  "data": {
    "id": 85,
    "kind": "keyword",
    "alias": "mixue",
    "target": "jajan",
    "target_id": 2
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `BAD_ARGS` (alias sudah ada, bentrok dengan nama, kategori ambigu).

### `alias list`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--kind account\|category\|keyword` | | Hanya satu jenis. |

```bat
python finance.py alias list --kind account
```
```json
{
  "ok": true,
  "message": "1 alias:\n- [account] cash → tunai",
  "data": {
    "aliases": [
      {
        "id": 84,
        "kind": "account",
        "alias": "cash",
        "target": "tunai"
      }
    ]
  }
}
```

Error: tidak ada yang khusus.

### `alias remove`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--kind account\|category\|keyword` | ya | Jenis alias. |
| `--alias <teks>` | ya | Alias yang dihapus. |

```bat
python finance.py alias remove --kind keyword --alias mixue
```
```json
{
  "ok": true,
  "message": "Alias 'mixue' dihapus.",
  "data": {
    "id": 85,
    "kind": "keyword",
    "alias": "mixue"
  }
}
```

Error: `NOT_FOUND`.

---

### Transaksi

### `add`

Mencatat satu atau banyak pemasukan/pengeluaran dalam satu pemanggilan (satu `group_id`, satu `undo`). Pemasukan
selalu masuk ke `belum teralokasi`. Pengeluaran mengurangi budget kategorinya, atau `belum teralokasi` jika
kategori itu belum punya budget. `message` menyebut sisa dompet dan sisa budget yang terpakai, plus peringatan
jika ada yang minus.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--type income\|expense` | ya | Jenis. |
| `--item "catatan\|jumlah\|kategori"` | ya, boleh diulang | Kategori opsional (ditebak). |
| `--account <dompet>` | | Bawaan: dompet default (disebut di `message`). |
| `--budget <budget>` | | Khusus pengeluaran: ambil dari budget ini, bukan budget kategorinya. (Belanja dari tabungan: `savings spend`.) |
| `--date <tanggal>` | | Waktu transaksi. |
| `--raw <teks>` | | Teks asli dari pengguna, disimpan untuk pencarian. |

```bat
python finance.py add --type expense --item "ayam goreng|15k|makan" --raw "beli ayam goreng 15k"
```
```json
{
  "ok": true,
  "message": "Tercatat pengeluaran ayam goreng Rp15.000 (kategori makan) dari tunai (dompet default). Sisa tunai Rp135.000. Sisa budget belum teralokasi Rp685.000.",
  "data": {
    "group_id": "<acak>",
    "type": "expense",
    "account": "tunai",
    "used_default_account": true,
    "ts": "2026-10-06 12:00:00",
    "total": 15000,
    "balance_after": 135000,
    "items": [
      {
        "id": 5,
        "note": "ayam goreng",
        "amount": 15000,
        "category": "makan",
        "category_source": "given",
        "budget": "belum teralokasi",
        "budget_balance": 685000
      }
    ]
  }
}
```

```bat
python finance.py add --type income --account bri --item "gajian|600k|gaji"
```
```json
{
  "ok": true,
  "message": "Tercatat pemasukan gajian Rp600.000 (kategori gaji) ke bri. Sisa bri Rp1.150.000. Sisa budget belum teralokasi Rp1.285.000.",
  "data": {
    "group_id": "<acak>",
    "type": "income",
    "account": "bri",
    "used_default_account": false,
    "ts": "2026-10-06 12:00:00",
    "total": 600000,
    "balance_after": 1150000,
    "items": [
      {
        "id": 6,
        "note": "gajian",
        "amount": 600000,
        "category": "gaji",
        "category_source": "given",
        "budget": "belum teralokasi",
        "budget_balance": 1285000
      }
    ]
  }
}
```

Beberapa item sekaligus, kategori ditebak:

```bat
python finance.py add --type expense --item "jajan|10k" --item "es teh|3k"
```
```json
{
  "ok": true,
  "message": "Tercatat 2 pengeluaran (Rp13.000) dari tunai (dompet default): jajan Rp10.000 [jajan, ditebak dari kata 'jajan']; es teh Rp3.000 [jajan, ditebak dari kata 'es teh']. Sisa tunai Rp122.000. Sisa budget belum teralokasi Rp1.272.000.",
  "data": {
    "group_id": "<acak>",
    "type": "expense",
    "account": "tunai",
    "used_default_account": true,
    "ts": "2026-10-06 12:00:00",
    "total": 13000,
    "balance_after": 122000,
    "items": [
      {
        "id": 7,
        "note": "jajan",
        "amount": 10000,
        "category": "jajan",
        "category_source": "keyword",
        "budget": "belum teralokasi",
        "budget_balance": 1272000
      },
      {
        "id": 8,
        "note": "es teh",
        "amount": 3000,
        "category": "jajan",
        "category_source": "keyword",
        "budget": "belum teralokasi",
        "budget_balance": 1272000
      }
    ]
  }
}
```

Satu nominal untuk beberapa barang: tulis sebagai satu item.

```bat
python finance.py add --type expense --date yesterday --item "jajan, parkir, makan|50k|makan"
```
```json
{
  "ok": true,
  "message": "Tercatat pengeluaran jajan, parkir, makan Rp50.000 (kategori makan) dari tunai (dompet default). Tanggal: 5 Oktober 2026. Sisa tunai Rp72.000. Sisa budget belum teralokasi Rp1.222.000.",
  "data": {
    "group_id": "<acak>",
    "type": "expense",
    "account": "tunai",
    "used_default_account": true,
    "ts": "2026-10-05 12:00:00",
    "total": 50000,
    "balance_after": 72000,
    "items": [
      {
        "id": 9,
        "note": "jajan, parkir, makan",
        "amount": 50000,
        "category": "makan",
        "category_source": "given",
        "budget": "belum teralokasi",
        "budget_balance": 1222000
      }
    ]
  }
}
```

Error: `BAD_AMOUNT`, `BAD_DATE`, `UNKNOWN_ACCOUNT`, `NO_DEFAULT_ACCOUNT`, `UNKNOWN_CATEGORY`, `UNKNOWN_BUDGET`,
`BAD_ARGS` (format item, `--budget` pada pemasukan). Jika satu item salah, `message` menyebut item ke berapa dan
tidak ada yang tersimpan.

### `transfer`

Memindah uang antar dompet, termasuk tarik tunai. Tidak mengubah budget. Biaya admin dicatat sebagai pengeluaran
kategori `biaya admin` dari dompet asal, dalam group yang sama. Tabungan tidak bisa dipakai di sini (`UNKNOWN_ACCOUNT`);
pakai `savings deposit` atau `savings withdraw`.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--from <dompet>` | ya | Dompet asal. |
| `--to <dompet>` | ya | Dompet tujuan, harus berbeda. |
| `--amount <nominal>` | ya | Jumlah yang dipindah. |
| `--fee <nominal>` | | Biaya admin. |
| `--date <tanggal>` | | Waktu transfer. |
| `--note <teks>` | | Catatan. |
| `--raw <teks>` | | Teks asli. |

```bat
python finance.py transfer --from bri --to tunai --amount 200k --fee 2.5k
```
```json
{
  "ok": true,
  "message": "Tarik tunai Rp200.000 dari bri ke tunai. Biaya admin Rp2.500 dicatat sebagai pengeluaran dari bri. Sisa bri Rp947.500, tunai Rp272.000. Sisa budget belum teralokasi Rp1.219.500.",
  "data": {
    "group_id": "<acak>",
    "kind": "cash_withdrawal",
    "transfer_id": 10,
    "fee_id": 11,
    "amount": 200000,
    "fee": 2500,
    "from": "bri",
    "to": "tunai",
    "ts": "2026-10-06 12:00:00",
    "balance_from": 947500,
    "balance_to": 272000
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `BAD_AMOUNT`, `BAD_DATE`, `BAD_ARGS` (dompet asal = tujuan).

### `adjust`

Menyamakan saldo dompet atau tabungan dengan kenyataan. Script menghitung selisihnya sendiri dan mencatatnya sebagai
penyesuaian (bukan pemasukan/pengeluaran). Untuk dompet, selisih itu masuk ke atau keluar dari `belum teralokasi`;
untuk tabungan, budget tidak berubah.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--account <dompet>` | ya | Dompet. |
| `--actual <nominal>` | ya | Saldo sebenarnya sekarang. Boleh 0 dan negatif (`--actual=-5k`). |
| `--note <teks>` | | Catatan (bawaan: "penyesuaian saldo"). |

```bat
python finance.py adjust --account bri --actual 450k
```
```json
{
  "ok": true,
  "message": "Saldo bri disesuaikan dari Rp947.500 menjadi Rp450.000 (selisih -Rp497.500). Selisih ini keluar dari budget belum teralokasi dan tidak dihitung sebagai pemasukan atau pengeluaran. Sisa budget belum teralokasi Rp722.000.",
  "data": {
    "account": "bri",
    "before": 947500,
    "after": 450000,
    "difference": -497500,
    "id": 12,
    "group_id": "<acak>",
    "savings": false,
    "unallocated_balance": 722000
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `BAD_AMOUNT`.

### `edit`

Mengubah transaksi. `message` menampilkan nilai sebelum dan sesudah. Mengganti kategori pengeluaran memindahkan
transaksi ke budget kategori barunya. Nominal transaksi hutang tidak bisa diubah (hapus lalu catat ulang).

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<id>` | ya | ID transaksi (lihat `list`). |
| `--amount <nominal>` | | Nominal baru. |
| `--category <kategori>` | | Khusus pemasukan/pengeluaran. |
| `--budget <budget>` | | Khusus pengeluaran. |
| `--account <dompet>` | | Dompet (untuk transfer: dompet asal). |
| `--to <dompet>` | | Khusus transfer: dompet tujuan. |
| `--note <teks>` | | Catatan baru (`--note ""` mengosongkan). |
| `--date <tanggal>` | | Waktu baru. |

```bat
python finance.py edit 5 --amount 18k --note "ayam geprek"
```
```json
{
  "ok": true,
  "message": "Transaksi #5 diubah: jumlah Rp15.000 → Rp18.000; catatan ayam goreng → ayam geprek. Sisa tunai Rp269.000. Sisa budget belum teralokasi Rp719.000.",
  "data": {
    "id": 5,
    "before": {
      "id": 5,
      "ts": "2026-10-06 12:00:00",
      "type": "expense",
      "amount": 15000,
      "account": "tunai",
      "to_account": null,
      "category": "makan",
      "budget": "belum teralokasi",
      "debt_id": null,
      "note": "ayam goreng",
      "raw_text": "beli ayam goreng 15k",
      "group_id": "<acak>",
      "deleted_at": null,
      "source": "wallet"
    },
    "after": {
      "id": 5,
      "ts": "2026-10-06 12:00:00",
      "type": "expense",
      "amount": 18000,
      "account": "tunai",
      "to_account": null,
      "category": "makan",
      "budget": "belum teralokasi",
      "debt_id": null,
      "note": "ayam geprek",
      "raw_text": "beli ayam goreng 15k",
      "group_id": "<acak>",
      "deleted_at": null,
      "source": "wallet"
    },
    "changes": [
      {
        "field": "jumlah",
        "before": "Rp15.000",
        "after": "Rp18.000"
      },
      {
        "field": "catatan",
        "before": "ayam goreng",
        "after": "ayam geprek"
      }
    ]
  }
}
```

Error: `NOT_FOUND`, `BAD_AMOUNT`, `BAD_DATE`, `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `UNKNOWN_BUDGET`, `BAD_ARGS`
(tidak ada yang diubah, opsi tidak cocok dengan jenis transaksi).

### `delete`

Menghapus transaksi (soft delete; tetap terlihat dengan `list --include-deleted`). Status hutang dan tagihan rutin
yang terkait dihitung ulang.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<id>` | ya | ID transaksi. |

```bat
python finance.py delete 8
```
```json
{
  "ok": true,
  "message": "Transaksi dihapus: #8 06/10/2026 12:00 · pengeluaran Rp3.000 · es teh [jajan] (budget belum teralokasi) · tunai. Sisa tunai Rp272.000. Sisa budget belum teralokasi Rp722.000. Catatan: transaksi lain dari pencatatan yang sama masih ada (#7).",
  "data": {
    "id": 8,
    "deleted": {
      "id": 8,
      "ts": "2026-10-06 12:00:00",
      "type": "expense",
      "amount": 3000,
      "account": "tunai",
      "to_account": null,
      "category": "jajan",
      "budget": "belum teralokasi",
      "debt_id": null,
      "note": "es teh",
      "raw_text": null,
      "group_id": "<acak>",
      "deleted_at": "2026-10-06 12:00:00",
      "source": "wallet"
    },
    "remaining_in_group": [
      7
    ]
  }
}
```

Error: `NOT_FOUND`.

### `undo`

Membatalkan pencatatan uang terakhir: semua transaksi dan pindahan budget dari satu pemanggilan (termasuk satu
`batch` utuh). Jika pencatatan itu juga menghapus sesuatu (dompet, budget, kategori), yang dihapus diaktifkan lagi;
jika ia membuat hutang, hutangnya ikut dihapus. Perubahan pengaturan tanpa uang (tambah, ganti nama) tidak di-undo.

Tanpa opsi.

```bat
python finance.py undo
```
```json
{
  "ok": true,
  "message": "Dibatalkan: #12 06/10/2026 12:00 · penyesuaian -Rp497.500 · penyesuaian saldo · bri. Sisa bri Rp947.500. Sisa budget belum teralokasi Rp1.219.500.",
  "data": {
    "group_id": "<acak>",
    "action": "adjust",
    "undone": [
      12
    ],
    "undone_moves": [],
    "restored": [],
    "removed": [],
    "transactions": [
      {
        "id": 12,
        "ts": "2026-10-06 12:00:00",
        "type": "adjustment",
        "amount": -497500,
        "account": "bri",
        "to_account": null,
        "category": null,
        "budget": "belum teralokasi",
        "debt_id": null,
        "note": "penyesuaian saldo",
        "raw_text": null,
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      }
    ]
  }
}
```

Error: `NOTHING_TO_UNDO`.

---

### Saldo, laporan, daftar

### `balance`

Tanpa `--account`: saldo per dompet dan total dompet, per budget (`belum teralokasi`, budget kategori) dan total
budget, lalu per tabungan dan total tabungan (terpisah), pinjaman tabungan yang belum dikembalikan,
hutang, piutang, dan kekayaan bersih (dompet + tabungan + piutang − hutang). `data.consistent` true jika total
dompet = total budget (tabungan tidak ikut). `data.accounts` hanya dompet; tabungan ada di `data.savings` dan
`data.total_tabungan`.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--account <dompet>` | | Hanya satu dompet atau tabungan (yang dihapus juga bisa dilihat). |

```bat
python finance.py balance --account bri
```
```json
{
  "ok": true,
  "message": "Saldo bri (bank): Rp947.500.",
  "data": {
    "account": "bri",
    "type": "bank",
    "balance": 947500,
    "savings": false
  }
}
```

```bat
python finance.py balance
```
```json
{
  "ok": true,
  "message": "Dompet (uang untuk dipakai):\n- tunai (tunai): Rp272.000\n- bri (bank): Rp947.500\nTotal dompet: Rp1.219.500\n\nPer budget (uang di dompet untuk apa):\n- belum teralokasi: Rp1.219.500\nTotal budget: Rp1.219.500\n\nTabungan (terpisah, di luar budget):\n- belum ada tabungan\nTotal tabungan: Rp0\n\nKekayaan bersih (dompet + tabungan + piutang − hutang): Rp1.219.500",
  "data": {
    "accounts": [
      {
        "name": "tunai",
        "type": "cash",
        "balance": 272000,
        "is_default": true,
        "archived": false
      },
      {
        "name": "bri",
        "type": "bank",
        "balance": 947500,
        "is_default": false,
        "archived": false
      }
    ],
    "savings": [],
    "total_dompet": 1219500,
    "total_tabungan": 0,
    "budgets": [
      {
        "id": 1,
        "name": "belum teralokasi",
        "kind": "unallocated",
        "balance": 1219500,
        "archived": false
      }
    ],
    "total_budget": 1219500,
    "consistent": true,
    "debt_total": 0,
    "receivable_total": 0,
    "savings_loans_total": 0,
    "net_worth": 1219500
  }
}
```

Error: `UNKNOWN_ACCOUNT` (dompet tidak ada, atau belum ada dompet sama sekali).

### `report`

Total dan rincian per kategori (nominal, persen, jumlah transaksi). Hanya `income` dan `expense` yang dihitung;
transfer, hutang, penyesuaian, alokasi budget, menabung, dan menarik tabungan tidak pernah masuk. Angka utama adalah
pengeluaran dari dompet; pengeluaran dari tabungan (`savings spend --mode purpose`) dilaporkan terpisah di
`data.savings_expense` dan di baris tersendiri pada `message`. Dengan `--account <tabungan>`, laporannya tentang
tabungan itu saja.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--period <periode>` | | Bawaan `this-month`. |
| `--from <YYYY-MM-DD>` | | Awal rentang bebas. |
| `--to <YYYY-MM-DD>` | | Akhir rentang bebas (bawaan: hari ini). |
| `--type expense\|income\|all` | | Bawaan `expense`. `all` = pemasukan, pengeluaran, dan selisih. |
| `--category <kategori>` | | Hanya satu kategori. |
| `--account <dompet>` | | Hanya satu dompet. |

```bat
python finance.py report --period this-month --type expense
```
```json
{
  "ok": true,
  "message": "Pengeluaran bulan ini (1–6 Oktober 2026): Rp80.500 dari 4 transaksi.\n- makan: Rp68.000 (84,5%) · 2x\n- jajan: Rp10.000 (12,4%) · 1x\n- biaya admin: Rp2.500 (3,1%) · 1x",
  "data": {
    "period": {
      "key": "this-month",
      "label": "bulan ini",
      "start": "2026-10-01",
      "end": "2026-10-06",
      "text": "1–6 Oktober 2026"
    },
    "type": "expense",
    "filters": {
      "account": null,
      "category": null
    },
    "total": 80500,
    "count": 4,
    "by_category": [
      {
        "category": "makan",
        "amount": 68000,
        "percent": 84.5,
        "count": 2
      },
      {
        "category": "jajan",
        "amount": 10000,
        "percent": 12.4,
        "count": 1
      },
      {
        "category": "biaya admin",
        "amount": 2500,
        "percent": 3.1,
        "count": 1
      }
    ],
    "savings_expense": {
      "total": 0,
      "count": 0,
      "by_category": []
    }
  }
}
```

Error: `BAD_PERIOD`, `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `BAD_ARGS` (`--period` bersama `--from`).

### `list`

Daftar transaksi terbaru dulu, beserta ID.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--period <periode>` | | Bawaan `this-month`. |
| `--from <YYYY-MM-DD>` | | Awal rentang bebas. |
| `--to <YYYY-MM-DD>` | | Akhir rentang bebas. |
| `--search <teks>` | | Cari di catatan dan teks asli. |
| `--type <jenis>` | | `income`, `expense`, `transfer`, `adjustment`, `debt_in`, `debt_out`, `deposit` (menabung), `withdraw` (tarik tabungan), `savings_loan` (pinjam dari tabungan), `savings_repay` (kembali ke tabungan). |
| `--account <dompet>` | | Transaksi yang menyentuh dompet ini. |
| `--category <kategori>` | | Hanya kategori ini. |
| `--limit <n>` | | 1 sampai 1000, bawaan 50. |
| `--include-deleted` | | Sertakan transaksi yang dihapus. |

```bat
python finance.py list --period this-month --limit 3
```
```json
{
  "ok": true,
  "message": "Transaksi bulan ini (1–6 Oktober 2026), 3 dari 10 transaksi:\n#11 06/10/2026 12:00 · pengeluaran Rp2.500 · biaya admin transfer bri ke tunai [biaya admin] (budget belum teralokasi) · bri\n#10 06/10/2026 12:00 · transfer Rp200.000 · (tanpa catatan) · bri → tunai\n#7 06/10/2026 12:00 · pengeluaran Rp10.000 · jajan [jajan] (budget belum teralokasi) · tunai",
  "data": {
    "period": {
      "key": "this-month",
      "label": "bulan ini",
      "start": "2026-10-01",
      "end": "2026-10-06",
      "text": "1–6 Oktober 2026"
    },
    "count": 3,
    "total_matching": 10,
    "transactions": [
      {
        "id": 11,
        "ts": "2026-10-06 12:00:00",
        "type": "expense",
        "amount": 2500,
        "account": "bri",
        "to_account": null,
        "category": "biaya admin",
        "budget": "belum teralokasi",
        "debt_id": null,
        "note": "biaya admin transfer bri ke tunai",
        "raw_text": null,
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      },
      {
        "id": 10,
        "ts": "2026-10-06 12:00:00",
        "type": "transfer",
        "amount": 200000,
        "account": "bri",
        "to_account": "tunai",
        "category": null,
        "budget": null,
        "debt_id": null,
        "note": null,
        "raw_text": null,
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      },
      {
        "id": 7,
        "ts": "2026-10-06 12:00:00",
        "type": "expense",
        "amount": 10000,
        "account": "tunai",
        "to_account": null,
        "category": "jajan",
        "budget": "belum teralokasi",
        "debt_id": null,
        "note": "jajan",
        "raw_text": null,
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      }
    ]
  }
}
```

Error: `BAD_PERIOD`, `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `BAD_ARGS` (`--limit` di luar batas).

---

### Budget (sistem amplop)

Total semua dompet selalu sama dengan total semua budget. Pemasukan masuk ke `belum teralokasi`; pengguna sendiri
yang membaginya. Budget kategori dibuat saat kategori itu pertama kali diberi alokasi. Budget boleh minus (ada
peringatan di `message`).

### `budget list`

Tanpa opsi.

```bat
python finance.py budget list
```
```json
{
  "ok": true,
  "message": "Budget:\n- belum teralokasi: Rp1.219.500\nTotal budget: Rp1.219.500",
  "data": {
    "budgets": [
      {
        "id": 1,
        "name": "belum teralokasi",
        "kind": "unallocated",
        "balance": 1219500,
        "archived": false
      }
    ],
    "total_budget": 1219500,
    "total_dompet": 1219500,
    "consistent": true
  }
}
```

Error: tidak ada yang khusus.

### `budget alloc`

Alokasi dari `belum teralokasi` ke satu atau banyak budget kategori pengeluaran. Satu group; jika
satu item salah, tidak ada yang tersimpan.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--item "budget\|jumlah"` | ya, boleh diulang | Nama budget atau kategori pengeluaran. (Menabung: `savings deposit`.) |
| `--note <teks>` | | Catatan. |

```bat
python finance.py budget alloc --item "makan|300k" --item "transport|100k"
```
```json
{
  "ok": true,
  "message": "Dialokasikan Rp400.000 dari belum teralokasi: makan Rp300.000, transport Rp100.000. Sisa budget makan Rp300.000, transport Rp100.000, belum teralokasi Rp819.500.",
  "data": {
    "group_id": "<acak>",
    "total": 400000,
    "items": [
      {
        "id": 1,
        "budget": "makan",
        "amount": 300000,
        "balance_after": 300000
      },
      {
        "id": 2,
        "budget": "transport",
        "amount": 100000,
        "balance_after": 100000
      }
    ],
    "unallocated_balance": 819500
  }
}
```

Error: `BAD_AMOUNT`, `UNKNOWN_BUDGET`, `BAD_ARGS` (format item, alokasi ke `belum teralokasi`).

### `budget move`

Memindah saldo antar budget mana pun, termasuk ke/dari `belum teralokasi`. Tabungan bukan budget.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--from <budget>` | ya | Budget asal (harus sudah ada). |
| `--to <budget>` | ya | Budget tujuan (kategori tanpa budget akan dibuatkan). |
| `--amount <nominal>\|all` | ya | `all` = seluruh sisa budget asal. |
| `--note <teks>` | | Catatan. |

```bat
python finance.py budget move --from makan --to jajan --amount 50k
```
```json
{
  "ok": true,
  "message": "Dipindah Rp50.000 dari budget makan ke jajan. Sisa budget makan Rp250.000, jajan Rp50.000.",
  "data": {
    "id": 3,
    "group_id": "<acak>",
    "from": "makan",
    "to": "jajan",
    "amount": 50000,
    "from_balance": 250000,
    "to_balance": 50000
  }
}
```

Error: `UNKNOWN_BUDGET`, `BAD_AMOUNT` (termasuk `all` saat sisa 0 atau minus), `BAD_ARGS` (asal = tujuan).

### `budget close`

Sisa (plus atau minus) kembali ke `belum teralokasi`, lalu budget ditutup. Kategorinya tetap ada dan kembali
memakai `belum teralokasi`.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama budget. |

```bat
python finance.py budget close transport
```
```json
{
  "ok": true,
  "message": "Budget transport ditutup. Sisa Rp100.000 dikembalikan ke belum teralokasi. Pengeluaran kategori transport sekarang memakai belum teralokasi lagi. Sisa budget belum teralokasi Rp919.500.",
  "data": {
    "id": 3,
    "name": "transport",
    "kind": "category",
    "returned": 100000,
    "unallocated_balance": 919500
  }
}
```

Error: `UNKNOWN_BUDGET`, `SYSTEM_PROTECTED` (`belum teralokasi`).

### `budget history`

Riwayat alokasi dan pindahan budget.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--budget <budget>` | | Hanya yang menyentuh budget ini. |
| `--period <periode>` | | Bawaan `this-month`. |
| `--from <YYYY-MM-DD>` | | Awal rentang bebas. |
| `--to <YYYY-MM-DD>` | | Akhir rentang bebas. |
| `--limit <n>` | | 1 sampai 1000, bawaan 50. |

```bat
python finance.py budget history --budget makan
```
```json
{
  "ok": true,
  "message": "Riwayat budget makan bulan ini (1–6 Oktober 2026), 2 catatan:\n#3 06/10/2026 12:00 · Rp50.000 makan → jajan\n#1 06/10/2026 12:00 · Rp300.000 belum teralokasi → makan",
  "data": {
    "period": {
      "key": "this-month",
      "label": "bulan ini",
      "start": "2026-10-01",
      "end": "2026-10-06",
      "text": "1–6 Oktober 2026"
    },
    "moves": [
      {
        "id": 3,
        "ts": "2026-10-06 12:00:00",
        "from": "makan",
        "to": "jajan",
        "amount": 50000,
        "note": null,
        "group_id": "<acak>"
      },
      {
        "id": 1,
        "ts": "2026-10-06 12:00:00",
        "from": "belum teralokasi",
        "to": "makan",
        "amount": 300000,
        "note": null,
        "group_id": "<acak>"
      }
    ]
  }
}
```

Error: `BAD_PERIOD`, `UNKNOWN_BUDGET`, `BAD_ARGS` (`--limit`).

---

### Tabungan

Tabungan adalah **akun terpisah** (jenis `savings`), bukan dompet operasional dan bukan budget. Saldonya dihitung
dari transaksinya sendiri dan **tidak ikut aturan utama**: total dompet operasional (cash/bank/ewallet) selalu sama
dengan total budget, sedangkan tabungan berdiri sendiri. Tabungan tidak bisa jadi dompet default dan tidak bisa
dipakai di `add`, `transfer`, `debt add`, atau `recurring`; untuk uang masuk/keluar tabungan pakai perintah di bawah.

| Aksi | Dompet operasional | Tabungan | Budget | Masuk laporan pengeluaran |
|---|---|---|---|---|
| `savings deposit` (menabung) | berkurang | bertambah | budget sumber berkurang | tidak |
| `savings withdraw` (menarik) | bertambah | berkurang | budget tujuan bertambah | tidak |
| `savings spend --mode purpose` | tetap | berkurang | tetap | terpisah, sebagai "pengeluaran dari tabungan" |
| `savings spend --mode debt` | tetap | berkurang | tetap | belum (dicatat sebagai hutang ke tabungan) |
| `debt pay` pinjaman tabungan | berkurang | bertambah | budget kategori berkurang | ya, di kategori barangnya |
| `adjust --account <tabungan>` | tetap | disesuaikan | tetap | tidak |

`balance` menampilkan total dompet dan total tabungan secara terpisah; kekayaan bersih = dompet + tabungan +
piutang − hutang (pinjaman dari tabungan sendiri tidak dihitung sebagai hutang).

### `savings add`

Membuat tabungan, atau mengaktifkan kembali tabungan yang pernah dihapus (nama sama). Nama tabungan dan dompet
berbagi satu daftar nama.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tabungan. |
| `--target <nominal>` | | Target nominal. |
| `--target-date <YYYY-MM-DD>` | | Tenggat. |
| `--opening <nominal>` | | Saldo awal tabungan yang sudah ada (boleh 0). Tidak mengubah dompet maupun budget. |

```bat
python finance.py savings add "dana darurat" --target 5jt --target-date 2027-06-30
```
```json
{
  "ok": true,
  "message": "Tabungan dana darurat dibuat (target Rp5.000.000 pada 30 Juni 2027), saldo Rp0. Isi dengan: savings deposit --from <dompet> --to \"dana darurat\" --amount 100k",
  "data": {
    "savings": {
      "id": 4,
      "name": "dana darurat",
      "balance": 0,
      "target_amount": 5000000,
      "target_date": "2027-06-30",
      "archived": false,
      "percent": 0.0,
      "shortfall": 5000000,
      "month_change": 0,
      "loans_outstanding": 0
    },
    "reactivated": false
  }
}
```

Error: `BAD_ARGS` (nama sudah dipakai dompet atau tabungan lain), `BAD_AMOUNT`, `BAD_DATE`.

### `savings deposit`

Menabung dari dompet operasional. Dompet dan budget sumber berkurang, tabungan bertambah. Ditolak jika sisa budget
sumber tidak cukup.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--from <dompet>` | ya | Dompet asal (bukan tabungan). |
| `--to <tabungan>` | ya | Tabungan tujuan. |
| `--amount <nominal>` | ya | Jumlah. |
| `--from-budget <budget>` | | Budget yang dikurangi (bawaan `belum teralokasi`). |
| `--date <tanggal>` | | Waktu menabung. |
| `--note <teks>` | | Catatan. |
| `--raw <teks>` | | Teks asli. |

```bat
python finance.py savings deposit --from bri --to "dana darurat" --amount 100k
```
```json
{
  "ok": true,
  "message": "Menabung Rp100.000 dari bri ke tabungan dana darurat (2,0% dari target Rp5.000.000); budget belum teralokasi berkurang Rp100.000. Sisa bri Rp847.500, tabungan dana darurat Rp100.000. Sisa budget belum teralokasi Rp819.500.",
  "data": {
    "id": 13,
    "group_id": "<acak>",
    "from": "bri",
    "to": "dana darurat",
    "amount": 100000,
    "budget": "belum teralokasi",
    "balance_from": 847500,
    "savings": {
      "id": 4,
      "name": "dana darurat",
      "balance": 100000,
      "target_amount": 5000000,
      "target_date": "2027-06-30",
      "archived": false,
      "percent": 2.0,
      "shortfall": 4900000,
      "month_change": 100000,
      "loans_outstanding": 0
    },
    "budget_balance": 819500
  }
}
```

Budget sumber tidak cukup:

```bat
python finance.py savings deposit --from tunai --to "dana darurat" --amount 60k --from-budget jajan
```
```json
{
  "ok": false,
  "error": {
    "code": "BAD_AMOUNT",
    "message": "Budget jajan tidak cukup untuk menabung Rp60.000: sisanya Rp50.000.",
    "hint": "Kurangi jumlahnya, pakai --from-budget dengan budget lain, atau pindahkan dulu dengan budget move --to \"jajan\". Budget yang ada: belum teralokasi, makan, jajan.",
    "data": {
      "budget_balance": 50000
    }
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `UNKNOWN_BUDGET`, `BAD_AMOUNT` (termasuk budget sumber tidak cukup), `BAD_DATE`.

### `savings withdraw`

Menarik tabungan ke dompet operasional. Tabungan berkurang, dompet dan budget tujuan bertambah. Ditolak jika saldo
tabungan tidak cukup.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--from <tabungan>` | ya | Tabungan asal. |
| `--to <dompet>` | ya | Dompet tujuan. |
| `--amount <nominal>\|all` | ya | `all` = seluruh saldo tabungan. |
| `--to-budget <budget>` | | Budget yang bertambah (bawaan `belum teralokasi`; kategori tanpa budget dibuatkan). |
| `--date <tanggal>` | | Waktu menarik. |
| `--note <teks>` | | Catatan. |
| `--raw <teks>` | | Teks asli. |

```bat
python finance.py savings withdraw --from "dana darurat" --to tunai --amount 30k --to-budget makan
```
```json
{
  "ok": true,
  "message": "Menarik Rp30.000 dari tabungan dana darurat ke tunai; budget makan bertambah Rp30.000. Sisa tabungan dana darurat Rp70.000, tunai Rp302.000. Sisa budget makan Rp280.000.",
  "data": {
    "id": 14,
    "group_id": "<acak>",
    "from": "dana darurat",
    "to": "tunai",
    "amount": 30000,
    "budget": "makan",
    "balance_to": 302000,
    "savings": {
      "id": 4,
      "name": "dana darurat",
      "balance": 70000,
      "target_amount": 5000000,
      "target_date": "2027-06-30",
      "archived": false,
      "percent": 1.4,
      "shortfall": 4930000,
      "month_change": 70000,
      "loans_outstanding": 0
    },
    "budget_balance": 280000
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `UNKNOWN_BUDGET`, `BAD_AMOUNT` (termasuk saldo tabungan tidak cukup), `BAD_DATE`.

### `savings spend`

Belanja dengan uang tabungan. Satu pemanggilan boleh berisi beberapa item; semuanya tersimpan bersama atau tidak
sama sekali, dan ditolak jika total melebihi saldo tabungan.

- `--mode purpose`: pengeluaran sesuai tujuan tabungan. Saldo tabungan turun; dompet dan budget tidak berubah.
  Tercatat sebagai pengeluaran dengan sumber tabungan, dilaporkan terpisah dari pengeluaran dompet.
- `--mode debt`: meminjam dari tabungan. Saldo tabungan turun; dompet dan budget belum berubah. Tercatat sebagai
  hutang ke tabungan (satu hutang per item, `person` = nama tabungan). Saat dikembalikan dengan `debt pay`, dompet dan
  budget kategori barangnya berkurang, tabungan bertambah lagi, dan pengeluarannya baru tercatat di kategori itu.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--from <tabungan>` | ya | Tabungan. |
| `--item "catatan\|jumlah\|kategori"` | ya, boleh diulang | Kategori opsional (ditebak). |
| `--mode purpose\|debt` | ya | Lihat di atas. |
| `--date <tanggal>` | | Waktu belanja. |
| `--raw <teks>` | | Teks asli. |

```bat
python finance.py savings spend --from "dana darurat" --item "kacamata|40k|kesehatan" --mode purpose
```
```json
{
  "ok": true,
  "message": "Belanja dari tabungan dana darurat Rp40.000: kacamata Rp40.000 [kesehatan]. Dicatat sebagai pengeluaran dari tabungan; dompet dan budget tidak berubah. Sisa tabungan dana darurat Rp30.000.",
  "data": {
    "group_id": "<acak>",
    "mode": "purpose",
    "savings": {
      "id": 4,
      "name": "dana darurat",
      "balance": 30000,
      "target_amount": 5000000,
      "target_date": "2027-06-30",
      "archived": false,
      "percent": 0.6,
      "shortfall": 4970000,
      "month_change": 30000,
      "loans_outstanding": 0
    },
    "total": 40000,
    "items": [
      {
        "id": 15,
        "note": "kacamata",
        "amount": 40000,
        "category": "kesehatan",
        "category_source": "given",
        "debt_id": null
      }
    ]
  }
}
```

```bat
python finance.py savings spend --from "dana darurat" --item "servis motor|20k|transport" --mode debt
```
```json
{
  "ok": true,
  "message": "Pinjam Rp20.000 dari tabungan dana darurat untuk: servis motor Rp20.000 [transport]. Dicatat sebagai hutang ke tabungan (#1); dompet dan budget belum berubah. Kembalikan dengan: debt pay --person \"dana darurat\" --amount <jumlah> (pengeluarannya tercatat saat dikembalikan). Sisa tabungan dana darurat Rp10.000.",
  "data": {
    "group_id": "<acak>",
    "mode": "debt",
    "savings": {
      "id": 4,
      "name": "dana darurat",
      "balance": 10000,
      "target_amount": 5000000,
      "target_date": "2027-06-30",
      "archived": false,
      "percent": 0.2,
      "shortfall": 4990000,
      "month_change": 10000,
      "loans_outstanding": 20000
    },
    "total": 20000,
    "items": [
      {
        "id": 16,
        "note": "servis motor",
        "amount": 20000,
        "category": "transport",
        "category_source": "given",
        "debt_id": 1
      }
    ]
  }
}
```

Saldo tabungan tidak cukup:

```bat
python finance.py savings spend --from "dana darurat" --item "hp baru|1jt" --mode purpose
```
```json
{
  "ok": false,
  "error": {
    "code": "BAD_AMOUNT",
    "message": "Saldo tabungan dana darurat tidak cukup untuk membayar Rp1.000.000: sisanya Rp10.000.",
    "hint": "Kurangi jumlahnya, paling banyak Rp10.000, atau isi dulu lewat savings deposit --to \"dana darurat\".",
    "data": {
      "savings_balance": 10000
    }
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `UNKNOWN_CATEGORY`, `BAD_AMOUNT` (termasuk saldo tabungan tidak cukup), `BAD_DATE`,
`BAD_ARGS` (format item).

### `savings list`

Saldo, target, persen tercapai, kekurangan, perubahan bersih bulan ini, dan pinjaman yang belum dikembalikan untuk
tiap tabungan, lalu total.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--all` | | Sertakan tabungan yang sudah dihapus. |

```bat
python finance.py savings list
```
```json
{
  "ok": true,
  "message": "Tabungan (terpisah dari dompet dan budget):\n- dana darurat: Rp10.000 dari target Rp5.000.000 (0,2%), kurang Rp4.990.000, tenggat 30 Juni 2027. Bulan ini +Rp10.000. Pinjaman belum dikembalikan Rp20.000.\nTotal tabungan: Rp10.000 (bulan ini +Rp10.000).",
  "data": {
    "savings": [
      {
        "id": 4,
        "name": "dana darurat",
        "balance": 10000,
        "target_amount": 5000000,
        "target_date": "2027-06-30",
        "archived": false,
        "percent": 0.2,
        "shortfall": 4990000,
        "month_change": 10000,
        "loans_outstanding": 20000
      }
    ],
    "total": 10000,
    "month_change_total": 10000,
    "loans_outstanding_total": 20000
  }
}
```

Error: tidak ada yang khusus.

### `savings set`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tabungan. |
| `--target <nominal>` | | Target baru. |
| `--target-date <YYYY-MM-DD>` | | Tenggat baru. |
| `--clear` | | Hapus target dan tenggat (tidak boleh digabung dengan dua opsi di atas). |

```bat
python finance.py savings set "dana darurat" --target 3jt
```
```json
{
  "ok": true,
  "message": "Tabungan dana darurat sekarang target Rp3.000.000 pada 30 Juni 2027.",
  "data": {
    "id": 4,
    "name": "dana darurat",
    "target_amount": 3000000,
    "target_date": "2027-06-30"
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `BAD_AMOUNT`, `BAD_DATE`, `BAD_ARGS` (tidak ada yang diubah).

### `savings rename`

Nama di pinjaman tabungannya ikut berganti.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama sekarang. |
| `<new_name>` | ya | Nama baru. |

```bat
python finance.py savings rename "dana darurat" darurat
```
```json
{
  "ok": true,
  "message": "Tabungan dana darurat diganti nama menjadi darurat.",
  "data": {
    "id": 4,
    "old_name": "dana darurat",
    "name": "darurat"
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `BAD_ARGS` (nama sudah dipakai).

### `savings remove`

Belum pernah dipakai: dihapus sungguhan; sudah: diarsipkan. Ditolak (`NOT_EMPTY`) jika masih ada pinjaman yang belum
dikembalikan, atau jika saldo tidak nol tanpa salah satu opsi.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tabungan. |
| `--move-to <dompet\|tabungan>` | | Sisa dipindah ke dompet (masuk ke `belum teralokasi`) atau ke tabungan lain. |
| `--write-off` | | Sisa dinolkan lewat penyesuaian (dompet dan budget tidak berubah). |

```bat
python finance.py savings add liburan
```
```json
{
  "ok": true,
  "message": "Tabungan liburan dibuat (tanpa target), saldo Rp0. Isi dengan: savings deposit --from <dompet> --to \"liburan\" --amount 100k",
  "data": {
    "savings": {
      "id": 5,
      "name": "liburan",
      "balance": 0,
      "target_amount": null,
      "target_date": null,
      "archived": false,
      "percent": null,
      "shortfall": null,
      "month_change": 0,
      "loans_outstanding": 0
    },
    "reactivated": false
  }
}
```

```bat
python finance.py savings remove liburan
```
```json
{
  "ok": true,
  "message": "Tabungan liburan dihapus permanen karena belum pernah dipakai.",
  "data": {
    "id": 5,
    "name": "liburan",
    "mode": "deleted",
    "balance_before": 0,
    "moved_to": null,
    "written_off": false
  }
}
```

Masih ada pinjaman:

```bat
python finance.py savings remove darurat --write-off
```
```json
{
  "ok": false,
  "error": {
    "code": "NOT_EMPTY",
    "message": "Masih ada pinjaman dari tabungan darurat sebesar Rp20.000 yang belum dikembalikan.",
    "hint": "Kembalikan dulu: debt pay --person \"darurat\" --amount all, atau hapus pinjamannya: debt remove --person \"darurat\" --write-off",
    "data": {
      "loans_outstanding": 20000
    }
  }
}
```

Error: `UNKNOWN_ACCOUNT`, `NOT_EMPTY`, `BAD_ARGS` (tujuan sama dengan asal).

---

### Hutang piutang

- `i_owe`: saya berhutang. Saat dicatat uang masuk ke dompet (dan ke `belum teralokasi`); saat saya membayar, uang
  keluar.
- `owed_to_me`: orang lain berhutang ke saya (piutang). Saat dicatat uang keluar; saat dia membayar, uang masuk.
- Hutang piutang tidak pernah masuk laporan pemasukan/pengeluaran. Uang keluar mengurangi `belum teralokasi`
  kecuali diberi `--budget`; uang masuk selalu ke `belum teralokasi`.
- Nama orang tidak peka huruf besar kecil.

### `debt add`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--direction i_owe\|owed_to_me` | ya | Arah. |
| `--person <nama>` | ya | Nama orang. |
| `--amount <nominal>` | ya | Pokok hutang. |
| `--account <dompet>` | | Dompet tempat uang masuk/keluar (bawaan: default). |
| `--budget <budget>` | | Khusus `owed_to_me`: uang yang dipinjamkan diambil dari budget ini. |
| `--due <YYYY-MM-DD>` | | Jatuh tempo. |
| `--note <teks>` | | Catatan. |
| `--date <tanggal>` | | Tanggal pinjam. |
| `--no-cash` | | Tanpa aliran uang (hutang lama yang sudah termasuk di saldo awal). Tidak boleh bersama `--account`, `--budget`, `--date`, `--paid-for`. |
| `--paid-for "catatan\|kategori"` | | Khusus `i_owe`: orang itu membayari sesuatu untukmu. Hutang dan pengeluarannya dicatat sekaligus; saldo dompet tidak berubah, pengeluaran muncul di laporan dan memotong budget kategorinya. Kategori opsional (ditebak). |
| `--raw <teks>` | | Teks asli. |

Pinjam uang:

```bat
python finance.py debt add --direction i_owe --person Budi --amount 50k --due 2026-10-20
```
```json
{
  "ok": true,
  "message": "Tercatat hutang ke Budi Rp50.000 (#2), jatuh tempo 20 Oktober 2026 (14 hari lagi). Uangnya masuk ke tunai (dompet default) dan ke budget belum teralokasi. Sisa tunai Rp352.000. Sisa budget belum teralokasi Rp869.500. Total hutang ke Budi sekarang Rp50.000.",
  "data": {
    "debt": {
      "id": 2,
      "direction": "i_owe",
      "person": "Budi",
      "principal": 50000,
      "paid": 0,
      "remaining": 50000,
      "status": "open",
      "due_date": "2026-10-20",
      "days_until_due": 14,
      "note": null,
      "cash": true,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": 17,
    "group_id": "<acak>",
    "expense_id": null,
    "expense_category": null,
    "expense_budget": null,
    "account": "tunai",
    "used_default_account": true,
    "budget": "belum teralokasi",
    "balance_after": 352000
  }
}
```

Meminjamkan uang:

```bat
python finance.py debt add --direction owed_to_me --person Andi --amount 100k --account bri
```
```json
{
  "ok": true,
  "message": "Tercatat piutang: Andi pinjam Rp100.000 ke kamu (#3). Uangnya keluar dari bri, diambil dari budget belum teralokasi. Sisa bri Rp747.500. Sisa budget belum teralokasi Rp769.500. Total piutang dari Andi sekarang Rp100.000.",
  "data": {
    "debt": {
      "id": 3,
      "direction": "owed_to_me",
      "person": "Andi",
      "principal": 100000,
      "paid": 0,
      "remaining": 100000,
      "status": "open",
      "due_date": null,
      "days_until_due": null,
      "note": null,
      "cash": true,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": 18,
    "group_id": "<acak>",
    "expense_id": null,
    "expense_category": null,
    "expense_budget": null,
    "account": "bri",
    "used_default_account": false,
    "budget": "belum teralokasi",
    "balance_after": 747500
  }
}
```

Dibayari teman:

```bat
python finance.py debt add --direction i_owe --person Citra --amount 25k --paid-for "makan siang|makan"
```
```json
{
  "ok": true,
  "message": "Tercatat hutang ke Citra Rp25.000 (#4). Citra membayari makan siang, dicatat sebagai pengeluaran Rp25.000 (kategori makan). Saldo tunai tidak berubah; budget belum teralokasi bertambah Rp25.000 dari hutang, budget makan berkurang Rp25.000. Sisa tunai Rp352.000. Sisa budget belum teralokasi Rp794.500, makan Rp255.000. Total hutang ke Citra sekarang Rp25.000.",
  "data": {
    "debt": {
      "id": 4,
      "direction": "i_owe",
      "person": "Citra",
      "principal": 25000,
      "paid": 0,
      "remaining": 25000,
      "status": "open",
      "due_date": null,
      "days_until_due": null,
      "note": "makan siang",
      "cash": true,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": 19,
    "group_id": "<acak>",
    "expense_id": 20,
    "expense_category": "makan",
    "expense_budget": "makan",
    "account": "tunai",
    "used_default_account": true,
    "budget": "belum teralokasi",
    "balance_after": 352000
  }
}
```

Hutang lama tanpa aliran uang:

```bat
python finance.py debt add --direction i_owe --person Budi --amount 30k --no-cash --note "utang bulan lalu"
```
```json
{
  "ok": true,
  "message": "Tercatat hutang ke Budi Rp30.000 (#5). Tanpa aliran uang: dompet dan budget tidak berubah. Total hutang ke Budi sekarang Rp80.000 dari 2 catatan.",
  "data": {
    "debt": {
      "id": 5,
      "direction": "i_owe",
      "person": "Budi",
      "principal": 30000,
      "paid": 0,
      "remaining": 30000,
      "status": "open",
      "due_date": null,
      "days_until_due": null,
      "note": "utang bulan lalu",
      "cash": false,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": null,
    "group_id": null,
    "expense_id": null,
    "expense_category": null,
    "expense_budget": null,
    "account": null,
    "used_default_account": false,
    "budget": null,
    "balance_after": null
  }
}
```

Error: `BAD_AMOUNT`, `BAD_DATE`, `UNKNOWN_ACCOUNT`, `NO_DEFAULT_ACCOUNT`, `UNKNOWN_BUDGET`, `UNKNOWN_CATEGORY`
(`--paid-for`), `BAD_ARGS` (kombinasi opsi yang tidak boleh, format `--paid-for`).

### `debt pay`

Pembayaran boleh sebagian. Dengan `--person`, hanya hutang yang masih terbuka yang dipilih; jika ada lebih dari satu,
hasilnya `AMBIGUOUS_DEBT` beserta daftar ID.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--person <nama>` | salah satu | Nama orang. |
| `--id <id>` | salah satu | ID hutang (lihat `debt list`). |
| `--direction i_owe\|owed_to_me` | | Persempit pencarian `--person`. |
| `--amount <nominal>\|all` | ya | `all` = lunasi sisanya. |
| `--account <dompet>` | | Bawaan: default. |
| `--budget <budget>` | | Khusus membayar hutang saya (uang keluar). |
| `--date <tanggal>` | | Tanggal bayar. |
| `--note <teks>` | | Catatan. |
| `--raw <teks>` | | Teks asli. |

Budi punya dua hutang terbuka:

```bat
python finance.py debt pay --person Budi --amount 20k
```
```json
{
  "ok": false,
  "error": {
    "code": "AMBIGUOUS_DEBT",
    "message": "Budi punya 2 catatan hutang/piutang: #2 hutang ke Budi sisa Rp50.000; #5 hutang ke Budi sisa Rp30.000 (utang bulan lalu).",
    "hint": "Sebutkan yang dimaksud dengan --id, contoh --id 2.",
    "data": {
      "candidates": [
        {
          "id": 2,
          "direction": "i_owe",
          "remaining": 50000,
          "principal": 50000,
          "created_at": "2026-10-06 12:00:00",
          "note": null
        },
        {
          "id": 5,
          "direction": "i_owe",
          "remaining": 30000,
          "principal": 30000,
          "created_at": "2026-10-06 12:00:00",
          "note": "utang bulan lalu"
        }
      ]
    }
  }
}
```

```bat
python finance.py debt pay --id 2 --amount 20k
```
```json
{
  "ok": true,
  "message": "Bayar hutang ke Budi Rp20.000 dari tunai (dompet default). Sisa hutang ke Budi (#2) Rp30.000. Sisa tunai Rp332.000. Sisa budget belum teralokasi Rp774.500.",
  "data": {
    "debt": {
      "id": 2,
      "direction": "i_owe",
      "person": "Budi",
      "principal": 50000,
      "paid": 20000,
      "remaining": 30000,
      "status": "open",
      "due_date": "2026-10-20",
      "days_until_due": 14,
      "note": null,
      "cash": true,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": 21,
    "group_id": "<acak>",
    "amount": 20000,
    "remaining": 30000,
    "paid_off": false,
    "account": "tunai",
    "used_default_account": true,
    "budget": "belum teralokasi",
    "balance_after": 332000
  }
}
```

Bayar melebihi sisa:

```bat
python finance.py debt pay --id 2 --amount 50k
```
```json
{
  "ok": false,
  "error": {
    "code": "OVERPAYMENT",
    "message": "Pembayaran Rp50.000 melebihi sisa hutang ke Budi (#2) yaitu Rp30.000.",
    "hint": "Bayar paling banyak Rp30.000, atau pakai --amount all untuk melunasi.",
    "data": {
      "remaining": 30000
    }
  }
}
```

Andi membayar sebagian:

```bat
python finance.py debt pay --person Andi --amount 40k --account bri
```
```json
{
  "ok": true,
  "message": "Andi membayar piutang Rp40.000, masuk ke bri. Sisa piutang dari Andi (#3) Rp60.000. Sisa bri Rp787.500. Sisa budget belum teralokasi Rp814.500.",
  "data": {
    "debt": {
      "id": 3,
      "direction": "owed_to_me",
      "person": "Andi",
      "principal": 100000,
      "paid": 40000,
      "remaining": 60000,
      "status": "open",
      "due_date": null,
      "days_until_due": null,
      "note": null,
      "cash": true,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": 22,
    "group_id": "<acak>",
    "amount": 40000,
    "remaining": 60000,
    "paid_off": false,
    "account": "bri",
    "used_default_account": false,
    "budget": "belum teralokasi",
    "balance_after": 787500
  }
}
```

Mengembalikan pinjaman dari tabungan (dari `savings spend --mode debt`). `--person` adalah nama tabungannya. Dompet
dan budget berkurang, tabungan bertambah, dan pengeluarannya tercatat di kategori barang yang dulu dibeli; budget
bawaannya budget kategori itu, bisa diganti dengan `--budget`:

```bat
python finance.py debt pay --person darurat --amount all
```
```json
{
  "ok": true,
  "message": "Kembalikan Rp20.000 ke tabungan darurat dari tunai (dompet default), dicatat sebagai pengeluaran servis motor (kategori transport, budget belum teralokasi). Pinjaman dari tabungan darurat (#1) LUNAS. Sisa tunai Rp312.000, tabungan darurat Rp30.000. Sisa budget belum teralokasi Rp794.500.",
  "data": {
    "debt": {
      "id": 1,
      "direction": "i_owe",
      "person": "darurat",
      "principal": 20000,
      "paid": 20000,
      "remaining": 0,
      "status": "paid",
      "due_date": null,
      "days_until_due": null,
      "note": "servis motor",
      "cash": true,
      "archived": false,
      "savings": "darurat",
      "created_at": "2026-10-06 12:00:00"
    },
    "transaction_id": 24,
    "expense_id": 23,
    "group_id": "<acak>",
    "amount": 20000,
    "remaining": 0,
    "paid_off": true,
    "account": "tunai",
    "used_default_account": true,
    "budget": "belum teralokasi",
    "category": "transport",
    "savings": "darurat",
    "balance_after": 312000,
    "savings_balance_after": 30000
  }
}
```

Error: `NOT_FOUND`, `AMBIGUOUS_DEBT`, `OVERPAYMENT`, `BAD_AMOUNT`, `BAD_DATE`, `UNKNOWN_ACCOUNT`,
`NO_DEFAULT_ACCOUNT`, `UNKNOWN_BUDGET`, `BAD_ARGS` (`--budget` pada uang masuk, `--direction` tidak cocok).

### `debt list`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--status open\|paid\|all` | | Bawaan `open`. |
| `--person <nama>` | | Hanya orang ini. |
| `--direction i_owe\|owed_to_me` | | Hanya satu arah. |
| `--all` | | Sertakan yang sudah dihapus. |

```bat
python finance.py debt list
```
```json
{
  "ok": true,
  "message": "Hutang saya:\n- #2 hutang ke Budi: sisa Rp30.000 dari Rp50.000, jatuh tempo 20 Oktober 2026 (14 hari lagi)\n- #4 hutang ke Citra: sisa Rp25.000 dari Rp25.000 · makan siang\n- #5 hutang ke Budi: sisa Rp30.000 dari Rp30.000 · utang bulan lalu\nPiutang (orang berhutang ke saya):\n- #3 piutang dari Andi: sisa Rp60.000 dari Rp100.000\nTotal hutang saya: Rp85.000 | Total piutang: Rp60.000.",
  "data": {
    "debts": [
      {
        "id": 2,
        "direction": "i_owe",
        "person": "Budi",
        "principal": 50000,
        "paid": 20000,
        "remaining": 30000,
        "status": "open",
        "due_date": "2026-10-20",
        "days_until_due": 14,
        "note": null,
        "cash": true,
        "archived": false,
        "savings": null,
        "created_at": "2026-10-06 12:00:00"
      },
      {
        "id": 3,
        "direction": "owed_to_me",
        "person": "Andi",
        "principal": 100000,
        "paid": 40000,
        "remaining": 60000,
        "status": "open",
        "due_date": null,
        "days_until_due": null,
        "note": null,
        "cash": true,
        "archived": false,
        "savings": null,
        "created_at": "2026-10-06 12:00:00"
      },
      {
        "id": 4,
        "direction": "i_owe",
        "person": "Citra",
        "principal": 25000,
        "paid": 0,
        "remaining": 25000,
        "status": "open",
        "due_date": null,
        "days_until_due": null,
        "note": "makan siang",
        "cash": true,
        "archived": false,
        "savings": null,
        "created_at": "2026-10-06 12:00:00"
      }
    ],
    "count": 4,
    "debt_total": 85000,
    "receivable_total": 60000,
    "savings_loans_total": 0,
    "due_within_7_days": []
  }
}
```

Error: tidak ada yang khusus.

### `debt set`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--person <nama>` | salah satu | Nama orang. |
| `--id <id>` | salah satu | ID hutang. |
| `--direction i_owe\|owed_to_me` | | Persempit `--person`. |
| `--due <YYYY-MM-DD>` | | Jatuh tempo baru. |
| `--clear-due` | | Hapus jatuh tempo. |
| `--note <teks>` | | Catatan baru (`--note ""` mengosongkan). |

```bat
python finance.py debt set --person Andi --due 2026-10-31
```
```json
{
  "ok": true,
  "message": "Piutang dari Andi (#3) diubah: jatuh tempo 31 Oktober 2026 (25 hari lagi).",
  "data": {
    "debt": {
      "id": 3,
      "direction": "owed_to_me",
      "person": "Andi",
      "principal": 100000,
      "paid": 40000,
      "remaining": 60000,
      "status": "open",
      "due_date": "2026-10-31",
      "days_until_due": 25,
      "note": null,
      "cash": true,
      "archived": false,
      "savings": null,
      "created_at": "2026-10-06 12:00:00"
    }
  }
}
```

Error: `NOT_FOUND`, `AMBIGUOUS_DEBT`, `BAD_DATE`, `BAD_ARGS` (tidak ada yang diubah).

### `debt rename`

Mengganti nama orang di semua catatannya. Jika nama baru sudah dipakai, catatannya digabung.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama sekarang. |
| `<new_name>` | ya | Nama baru. |

```bat
python finance.py debt rename Andi "Andi Saputra"
```
```json
{
  "ok": true,
  "message": "Nama Andi diganti menjadi Andi Saputra di 1 catatan hutang/piutang.",
  "data": {
    "old_name": "Andi",
    "name": "Andi Saputra",
    "ids": [
      3
    ],
    "merged_ids": []
  }
}
```

Error: `NOT_FOUND`.

### `debt remove`

Tanpa transaksi sama sekali: dihapus sungguhan. Lunas: diarsipkan. Masih bersisa: `NOT_EMPTY`, kecuali
`--write-off` (sisa dianggap selesai tanpa uang; dompet dan budget tidak berubah).

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--person <nama>` | salah satu | Nama orang. |
| `--id <id>` | salah satu | ID hutang. |
| `--direction i_owe\|owed_to_me` | | Persempit `--person`. |
| `--write-off` | | Hapus walau masih bersisa. |

```bat
python finance.py debt remove --person Citra
```
```json
{
  "ok": false,
  "error": {
    "code": "NOT_EMPTY",
    "message": "Hutang ke Citra (#4) masih bersisa Rp25.000.",
    "hint": "Pilih salah satu: debt pay --id 4 --amount all (lunasi), atau debt remove --id 4 --write-off (sisa dianggap selesai tanpa uang). Jika salah catat, hapus transaksinya dulu: delete <id> (ID: 19).",
    "data": {
      "remaining": 25000,
      "transaction_ids": [
        19
      ]
    }
  }
}
```

```bat
python finance.py debt remove --person Citra --write-off
```
```json
{
  "ok": true,
  "message": "Hutang ke Citra (#4) dihapus. Riwayat transaksinya tetap disimpan (diarsipkan). Sisa Rp25.000 dianggap selesai; dompet dan budget tidak berubah. Total hutang saya: Rp60.000 | Total piutang: Rp60.000.",
  "data": {
    "id": 4,
    "mode": "archived",
    "written_off": 25000,
    "debt_total": 60000,
    "receivable_total": 60000
  }
}
```

Error: `NOT_FOUND`, `AMBIGUOUS_DEBT`, `NOT_EMPTY`.

---

### Tagihan rutin

Tagihan bulanan dengan tanggal jatuh tempo. Tanggal 29–31 di bulan yang lebih pendek menjadi akhir bulan.

### `recurring add`

Menambah tagihan, atau mengaktifkan kembali yang pernah dihapus (dengan nilai baru).

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tagihan. |
| `--amount <nominal>` | ya | Nominal biasanya. |
| `--day <1-31>` | ya | Tanggal jatuh tempo. |
| `--category <kategori>` | | Kategori pengeluaran (bawaan: ditebak dari nama, atau `tagihan`). |
| `--account <dompet>` | | Dompet pembayar (bawaan: dompet default saat dibayar). |

```bat
python finance.py recurring add kos --amount 500k --day 5 --account bri
```
```json
{
  "ok": true,
  "message": "Tagihan rutin kos ditambahkan: Rp500.000 tiap tanggal 5 (kategori tempat tinggal, ditebak dari kata 'kos'), dibayar dari bri. Bulan ini: belum dibayar, jatuh tempo 5 Oktober 2026 (lewat 1 hari).",
  "data": {
    "recurring": {
      "id": 1,
      "name": "kos",
      "amount": 500000,
      "day": 5,
      "category": "tempat tinggal",
      "account": "bri",
      "last_paid_month": null,
      "archived": false,
      "this_month": {
        "month": "2026-10",
        "due_date": "2026-10-05",
        "paid": false,
        "days_until_due": -1
      }
    },
    "reactivated": false
  }
}
```

```bat
python finance.py recurring add wifi --amount 150k --day 20
```
```json
{
  "ok": true,
  "message": "Tagihan rutin wifi ditambahkan: Rp150.000 tiap tanggal 20 (kategori pulsa & internet, ditebak dari kata 'wifi'), dibayar dari dompet default. Bulan ini: belum dibayar, jatuh tempo 20 Oktober 2026 (14 hari lagi).",
  "data": {
    "recurring": {
      "id": 2,
      "name": "wifi",
      "amount": 150000,
      "day": 20,
      "category": "pulsa & internet",
      "account": null,
      "last_paid_month": null,
      "archived": false,
      "this_month": {
        "month": "2026-10",
        "due_date": "2026-10-20",
        "paid": false,
        "days_until_due": 14
      }
    },
    "reactivated": false
  }
}
```

Error: `BAD_AMOUNT`, `UNKNOWN_CATEGORY`, `UNKNOWN_ACCOUNT`, `BAD_ARGS` (tanggal di luar 1–31, nama sudah ada).

### `recurring list`

Status bulan berjalan tiap tagihan, total per bulan, dan total yang belum dibayar.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--all` | | Sertakan yang sudah dihapus. |

```bat
python finance.py recurring list
```
```json
{
  "ok": true,
  "message": "Tagihan rutin:\n- kos Rp500.000 tiap tgl 5 [tempat tinggal, dari bri]: belum dibayar, jatuh tempo 5 Oktober 2026 (lewat 1 hari)\n- wifi Rp150.000 tiap tgl 20 [pulsa & internet, dari dompet default]: belum dibayar, jatuh tempo 20 Oktober 2026 (14 hari lagi)\nTotal per bulan: Rp650.000. Belum dibayar Oktober 2026: 2 tagihan, Rp650.000.",
  "data": {
    "recurring": [
      {
        "id": 1,
        "name": "kos",
        "amount": 500000,
        "day": 5,
        "category": "tempat tinggal",
        "account": "bri",
        "last_paid_month": null,
        "archived": false,
        "this_month": {
          "month": "2026-10",
          "due_date": "2026-10-05",
          "paid": false,
          "days_until_due": -1
        }
      },
      {
        "id": 2,
        "name": "wifi",
        "amount": 150000,
        "day": 20,
        "category": "pulsa & internet",
        "account": null,
        "last_paid_month": null,
        "archived": false,
        "this_month": {
          "month": "2026-10",
          "due_date": "2026-10-20",
          "paid": false,
          "days_until_due": 14
        }
      }
    ],
    "monthly_total": 650000,
    "unpaid_count": 2,
    "unpaid_total": 650000,
    "month": "2026-10"
  }
}
```

Error: tidak ada yang khusus.

### `recurring pay`

Mencatat pembayaran sebagai pengeluaran (kategori dan budget mengikuti aturan pengeluaran biasa).

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tagihan. |
| `--amount <nominal>` | | Jika berbeda dari biasanya. |
| `--account <dompet>` | | Bawaan: dompet tagihan, atau default. |
| `--budget <budget>` | | Ambil dari budget ini. |
| `--date <tanggal>` | | Tanggal bayar. |
| `--month <YYYY-MM>` | | Bulan tagihan yang dibayar (bawaan: bulan tanggal bayar). |
| `--raw <teks>` | | Teks asli. |

```bat
python finance.py recurring pay kos
```
```json
{
  "ok": true,
  "message": "Tagihan kos Oktober 2026 dibayar Rp500.000 dari bri, kategori tempat tinggal. Sisa bri Rp287.500. Sisa budget belum teralokasi Rp294.500.",
  "data": {
    "recurring": {
      "id": 1,
      "name": "kos",
      "amount": 500000,
      "day": 5,
      "category": "tempat tinggal",
      "account": "bri",
      "last_paid_month": "2026-10",
      "archived": false,
      "this_month": {
        "month": "2026-10",
        "due_date": "2026-10-05",
        "paid": true,
        "days_until_due": -1
      }
    },
    "transaction_id": 25,
    "group_id": "<acak>",
    "month": "2026-10",
    "amount": 500000,
    "account": "bri",
    "used_default_account": false,
    "category": "tempat tinggal",
    "budget": "belum teralokasi",
    "balance_after": 287500,
    "budget_balance": 294500
  }
}
```

Dibayar dua kali untuk bulan yang sama:

```bat
python finance.py recurring pay kos
```
```json
{
  "ok": false,
  "error": {
    "code": "BAD_ARGS",
    "message": "Tagihan kos untuk Oktober 2026 sudah dibayar.",
    "hint": "Untuk bulan lain pakai --month YYYY-MM. Jika memang bayar dua kali, catat lewat add."
  }
}
```

Error: `NOT_FOUND`, `BAD_AMOUNT`, `BAD_DATE` (`--date`, `--month`), `UNKNOWN_ACCOUNT`, `NO_DEFAULT_ACCOUNT`,
`UNKNOWN_CATEGORY`, `UNKNOWN_BUDGET`, `BAD_ARGS` (bulan itu sudah dibayar).

### `recurring set`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tagihan. |
| `--amount <nominal>` | | Nominal baru. |
| `--day <1-31>` | | Tanggal baru. |
| `--category <kategori>` | | Kategori baru. |
| `--account <dompet>` | | Dompet baru. |

```bat
python finance.py recurring set wifi --amount 160k
```
```json
{
  "ok": true,
  "message": "Tagihan wifi diubah: nominal Rp150.000 → Rp160.000.",
  "data": {
    "recurring": {
      "id": 2,
      "name": "wifi",
      "amount": 160000,
      "day": 20,
      "category": "pulsa & internet",
      "account": null,
      "last_paid_month": null,
      "archived": false,
      "this_month": {
        "month": "2026-10",
        "due_date": "2026-10-20",
        "paid": false,
        "days_until_due": 14
      }
    }
  }
}
```

Error: `NOT_FOUND`, `BAD_AMOUNT`, `UNKNOWN_CATEGORY`, `UNKNOWN_ACCOUNT`, `BAD_ARGS` (tidak ada yang diubah).

### `recurring rename`

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama sekarang. |
| `<new_name>` | ya | Nama baru. |

```bat
python finance.py recurring rename wifi internet
```
```json
{
  "ok": true,
  "message": "Tagihan wifi diganti nama menjadi internet.",
  "data": {
    "id": 2,
    "old_name": "wifi",
    "name": "internet"
  }
}
```

Error: `NOT_FOUND`, `BAD_ARGS` (nama sudah dipakai).

### `recurring remove`

Belum pernah dibayar: dihapus sungguhan; sudah: diarsipkan.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `<name>` | ya | Nama tagihan. |

```bat
python finance.py recurring remove internet
```
```json
{
  "ok": true,
  "message": "Tagihan rutin internet dihapus permanen karena belum pernah dibayar.",
  "data": {
    "id": 2,
    "name": "internet",
    "mode": "deleted"
  }
}
```

Error: `NOT_FOUND`.

---

### Analisis, pengingat, ekspor

### `analyze`

Fakta untuk menilai pola pengeluaran, tanpa nasihat: total, rasio menabung, per kategori, perbandingan dengan periode
sebelumnya yang sama panjang, rata-rata harian, hari paling boros, hari tanpa pengeluaran, 5 transaksi terbesar,
pengeluaran kecil (< Rp20.000) yang muncul lebih dari 5 kali, status budget, proyeksi akhir bulan (khusus bulan
berjalan), dan hutang yang jatuh tempo dalam 7 hari. Periode kosong tidak error.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--period <periode>` | | Bawaan `this-month`. |
| `--from <YYYY-MM-DD>` | | Awal rentang bebas. |
| `--to <YYYY-MM-DD>` | | Akhir rentang bebas. |

```bat
python finance.py analyze --period this-month
```
```json
{
  "ok": true,
  "message": "Analisis bulan ini (1–6 Oktober 2026):\nPemasukan Rp600.000, pengeluaran Rp625.500, selisih -Rp25.500, rasio menabung -4,2%.\nPengeluaran dibanding 1–6 September 2026: periode sebelumnya belum ada.\nKategori terbesar: tempat tinggal Rp500.000 (79,9%), makan Rp93.000 (14,9%), transport Rp20.000 (3,2%).\nRata-rata Rp104.250 per hari; paling boros 6 Oktober 2026 (Rp575.500); 4 dari 6 hari tanpa pengeluaran.\nProyeksi pengeluaran sampai akhir bulan: Rp3.231.750 (rata-rata harian x 31 hari).\nTidak ada budget yang minus.\nTabungan Rp30.000; pengeluaran dari tabungan (di luar angka di atas) Rp40.000.\nHutang Rp60.000, piutang Rp60.000.",
  "data": {
    "period": {
      "key": "this-month",
      "label": "bulan ini",
      "start": "2026-10-01",
      "end": "2026-10-06",
      "text": "1–6 Oktober 2026"
    },
    "income_total": 600000,
    "expense_total": 625500,
    "net": -25500,
    "savings_rate": -4.2,
    "expense_count": 7,
    "expense_by_category": [
      {
        "category": "tempat tinggal",
        "amount": 500000,
        "percent": 79.9,
        "count": 1
      },
      {
        "category": "makan",
        "amount": 93000,
        "percent": 14.9,
        "count": 3
      },
      {
        "category": "transport",
        "amount": 20000,
        "percent": 3.2,
        "count": 1
      }
    ],
    "comparison": {
      "previous_period": {
        "key": "previous",
        "label": "periode sebelumnya",
        "start": "2026-09-01",
        "end": "2026-09-06",
        "text": "1–6 September 2026"
      },
      "expense": {
        "current": 625500,
        "previous": 0,
        "difference": 625500,
        "percent": null
      },
      "income": {
        "current": 600000,
        "previous": 0,
        "difference": 600000,
        "percent": null
      },
      "by_category": [
        {
          "category": "tempat tinggal",
          "current": 500000,
          "previous": 0,
          "difference": 500000,
          "percent": null
        },
        {
          "category": "makan",
          "current": 93000,
          "previous": 0,
          "difference": 93000,
          "percent": null
        },
        {
          "category": "transport",
          "current": 20000,
          "previous": 0,
          "difference": 20000,
          "percent": null
        }
      ]
    },
    "daily": {
      "days": 6,
      "average_per_day": 104250,
      "busiest_day": {
        "date": "2026-10-06",
        "amount": 575500,
        "count": 6
      },
      "days_with_spending": 2,
      "days_without_spending": 4
    },
    "top_expenses": [
      {
        "id": 25,
        "ts": "2026-10-06 12:00:00",
        "amount": 500000,
        "note": "kos Oktober 2026",
        "category": "tempat tinggal",
        "account": "bri"
      },
      {
        "id": 9,
        "ts": "2026-10-05 12:00:00",
        "amount": 50000,
        "note": "jajan, parkir, makan",
        "category": "makan",
        "account": "tunai"
      },
      {
        "id": 20,
        "ts": "2026-10-06 12:00:00",
        "amount": 25000,
        "note": "makan siang (dibayari Citra)",
        "category": "makan",
        "account": "tunai"
      }
    ],
    "frequent_small": [],
    "budget_status": {
      "budgets": [
        {
          "name": "belum teralokasi",
          "kind": "unallocated",
          "balance": 294500,
          "archived": false,
          "spent_in_period": 600500
        },
        {
          "name": "jajan",
          "kind": "category",
          "balance": 50000,
          "archived": false,
          "spent_in_period": 0
        },
        {
          "name": "makan",
          "kind": "category",
          "balance": 255000,
          "archived": false,
          "spent_in_period": 25000
        }
      ],
      "negative": []
    },
    "projection": {
      "days_elapsed": 6,
      "days_in_month": 31,
      "average_per_day": 104250,
      "projected_expense": 3231750
    },
    "savings": {
      "accounts": [
        {
          "name": "darurat",
          "balance": 30000,
          "target_amount": 3000000
        }
      ],
      "total": 30000,
      "expense": {
        "total": 40000,
        "count": 1,
        "by_category": [
          {
            "category": "kesehatan",
            "amount": 40000,
            "percent": 100.0,
            "count": 1
          }
        ]
      },
      "loans_outstanding": 0
    },
    "debts": {
      "debt_total": 60000,
      "receivable_total": 60000,
      "due_within_7_days": []
    }
  }
}
```

Error: `BAD_PERIOD`.

### `daily-check`

Untuk dipanggil penjadwal. `data.send` false berarti tidak ada yang perlu dikirim.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--when pagi\|malam` | ya | `pagi`: tagihan rutin belum dibayar dan hutang/piutang yang jatuh tempo paling lambat 3 hari lagi (termasuk yang lewat). `malam`: total pengeluaran hari ini, atau pengingat jika belum ada transaksi (selalu `send: true`). |

```bat
python finance.py daily-check --when pagi
```
```json
{
  "ok": true,
  "message": "Tidak ada tagihan atau hutang yang jatuh tempo.",
  "data": {
    "send": false,
    "when": "pagi",
    "bills": [],
    "debts": []
  }
}
```

```bat
python finance.py daily-check --when malam
```
```json
{
  "ok": true,
  "message": "Pengeluaran hari ini Rp615.500 dari 7 transaksi.",
  "data": {
    "send": true,
    "when": "malam",
    "date": "2026-10-06",
    "transactions": 22,
    "expense_total": 615500,
    "expense_count": 7
  }
}
```

Error: tidak ada yang khusus.

### `export`

Membuat file Excel: sheet Transaksi, Ringkasan per kategori, Saldo dompet, Budget, Hutang piutang. Path file ada di
`data.path`.

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--period <periode>` | | Bawaan `this-month`. |
| `--from <YYYY-MM-DD>` | | Awal rentang bebas. |
| `--to <YYYY-MM-DD>` | | Akhir rentang bebas. |
| `--out <path.xlsx>` | | Bawaan `<FINANCE_HOME>\exports\keuangan-<periode>-<waktu>.xlsx`. |

```bat
python finance.py export --period this-month
```
```json
{
  "ok": true,
  "message": "Ekspor bulan ini (1–6 Oktober 2026) tersimpan di <FINANCE_HOME>\\exports\\keuangan-this-month-20261006-120000.xlsx. Isi: 23 transaksi, ringkasan per kategori, saldo 3 dompet, 3 budget, 4 hutang piutang.",
  "data": {
    "path": "<FINANCE_HOME>\\exports\\keuangan-this-month-20261006-120000.xlsx",
    "period": {
      "key": "this-month",
      "label": "bulan ini",
      "start": "2026-10-01",
      "end": "2026-10-06",
      "text": "1–6 Oktober 2026"
    },
    "counts": {
      "transactions": 23,
      "categories": 10,
      "accounts": 3,
      "budgets": 3,
      "debts": 4
    }
  }
}
```

Error: `BAD_PERIOD`, `BAD_ARGS` (`--out` bukan `.xlsx`, file sedang dibuka di Excel).

---

### `context`

Semua nama yang sah dan saldo saat ini, dalam satu panggilan: tanggal dan hari, dompet (nama, tipe, saldo, default),
kategori pengeluaran dan pemasukan, budget (nama, jenis, saldo), tabungan (`data.savings`: saldo, target, pinjaman
yang belum dikembalikan; terpisah dari `data.accounts`), alias dompet/kategori, kata kunci tebak kategori
(`data.keywords`), hutang/piutang terbuka (termasuk pinjaman dari tabungan, `savings_loan: true`), dan tagihan rutin.
Dipakai pemanggil sebelum menyusun perintah, supaya memakai nama yang benar.

Tanpa opsi.

```bat
python finance.py context
```
```json
{
  "ok": true,
  "message": "Hari ini Selasa, 6 Oktober 2026.\nDompet: tunai (tunai, default) Rp312.000, bri (bank) Rp287.500.\nKategori pengeluaran: makan, jajan, transport, belanja, tempat tinggal, pulsa & internet, pendidikan, kesehatan, tagihan, biaya admin, sedekah, lainnya, kucing oren.\nKategori pemasukan: gaji, uang saku, freelance, bonus, lainnya.\nBudget: belum teralokasi Rp294.500, makan Rp255.000, jajan Rp50.000.\nTabungan (terpisah dari dompet dan budget): darurat Rp30.000.\nAlias: cash = tunai.\nKata kunci tebak kategori: 78 (lihat data.keywords).\nHutang/piutang terbuka: #2 hutang ke Budi Rp30.000; #3 piutang dari Andi Saputra Rp60.000; #5 hutang ke Budi Rp30.000.\nTagihan rutin: kos Rp500.000 tgl 5 (lunas bulan ini).",
  "data": {
    "today": "2026-10-06",
    "weekday": "Selasa",
    "now": "2026-10-06 12:00:00",
    "accounts": [
      {
        "name": "tunai",
        "type": "cash",
        "balance": 312000,
        "is_default": true
      },
      {
        "name": "bri",
        "type": "bank",
        "balance": 287500,
        "is_default": false
      }
    ],
    "default_account": "tunai",
    "categories": {
      "expense": [
        "makan",
        "jajan",
        "transport"
      ],
      "income": [
        "gaji",
        "uang saku",
        "freelance"
      ]
    },
    "budgets": [
      {
        "name": "belum teralokasi",
        "kind": "unallocated",
        "balance": 294500
      },
      {
        "name": "makan",
        "kind": "category",
        "balance": 255000
      },
      {
        "name": "jajan",
        "kind": "category",
        "balance": 50000
      }
    ],
    "savings": [
      {
        "name": "darurat",
        "balance": 30000,
        "target_amount": 3000000,
        "target_date": "2027-06-30",
        "loans_outstanding": 0
      }
    ],
    "aliases": [
      {
        "kind": "account",
        "alias": "cash",
        "target": "tunai"
      }
    ],
    "keywords": {
      "expense": {
        "belanja": [
          "alfamart",
          "belanja",
          "indomaret"
        ],
        "transport": [
          "angkot",
          "bensin",
          "bus"
        ],
        "kesehatan": [
          "apotek",
          "dokter",
          "obat"
        ],
        "makan": [
          "ayam",
          "bakso",
          "geprek"
        ],
        "jajan": [
          "boba",
          "cilok",
          "es teh"
        ],
        "pendidikan": [
          "buku",
          "fotokopi",
          "kuliah"
        ],
        "sedekah": [
          "donasi",
          "infak",
          "infaq"
        ],
        "pulsa & internet": [
          "internet",
          "kuota",
          "paket data"
        ],
        "tempat tinggal": [
          "kontrakan",
          "kos",
          "kost"
        ],
        "tagihan": [
          "listrik",
          "pdam",
          "pln"
        ]
      },
      "income": {
        "bonus": [
          "bonus",
          "thr"
        ],
        "freelance": [
          "freelance",
          "project",
          "proyek"
        ],
        "gaji": [
          "gaji",
          "gajian"
        ],
        "uang saku": [
          "kiriman",
          "uang saku"
        ]
      }
    },
    "open_debts": [
      {
        "id": 2,
        "direction": "i_owe",
        "person": "Budi",
        "remaining": 30000,
        "due_date": "2026-10-20",
        "savings_loan": false
      },
      {
        "id": 3,
        "direction": "owed_to_me",
        "person": "Andi Saputra",
        "remaining": 60000,
        "due_date": "2026-10-31",
        "savings_loan": false
      },
      {
        "id": 5,
        "direction": "i_owe",
        "person": "Budi",
        "remaining": 30000,
        "due_date": null,
        "savings_loan": false
      }
    ],
    "recurring": [
      {
        "name": "kos",
        "amount": 500000,
        "day": 5,
        "paid_this_month": true
      }
    ]
  }
}
```

Error: tidak ada yang khusus.

---

### `batch`

Menjalankan beberapa perintah pencatatan uang sekaligus: **semua atau tidak sama sekali**, dalam satu transaksi
database dan satu `group_id`, sehingga satu `undo` membatalkan seluruh batch. Setiap entri diubah menjadi argumen
CLI dan diproses oleh parser dan kode yang sama dengan pemanggilan biasa, jadi validasi, pesan, dan aturannya
identik. Perintah dijalankan berurutan; perintah berikutnya melihat hasil perintah sebelumnya (misalnya alokasi lalu
pengeluaran dari budget itu).

| Opsi | Wajib | Keterangan |
|---|---|---|
| `--file <path.json>` | salah satu | File JSON (UTF-8, BOM boleh). |
| `--stdin` | salah satu | Baca JSON dari stdin (UTF-8). |

**Format JSON**: daftar (array) berisi 1 sampai 200 objek `{"cmd": "<perintah>", "args": {<opsi>: <nilai>}}`.

- `cmd`: salah satu dari `add`, `transfer`, `adjust`, `budget alloc`, `budget move`, `debt add`, `debt pay`,
  `recurring pay`, `savings deposit`, `savings withdraw`, `savings spend`. Perintah lain (pengaturan, `edit`,
  `delete`, `undo`, laporan) ditolak karena tidak bisa di-undo bersama.
- `args`: nama opsi **tanpa** `--`; tanda `_` boleh dipakai untuk `-` (`paid_for` = `--paid-for`). Argumen
  positional memakai namanya di tabel opsi (`recurring pay` → `"name"`).
- Nilai: teks, angka bulat (`15000`), `true` untuk opsi tanpa nilai (`"no_cash": true`), `false`/`null` = opsi tidak
  dipakai, daftar teks untuk opsi yang boleh diulang (`"item": ["kopi|8k", "roti|10k"]`; satu teks juga boleh).
  Nilai negatif ditulis biasa (`"actual": "-5k"`).
- Hasil: `data.results` berisi `message` dan `data` tiap perintah, berurutan; `data.group_id` dipakai bersama.
  Jika tidak ada uang yang berubah sama sekali (misalnya semua `adjust` tanpa selisih), `group_id` null.
- Gagal: kode error sama dengan perintah yang gagal, `message` diawali `Perintah ke-N (<cmd>):`, dan
  `error.data.index`/`error.data.cmd` menunjuk perintah itu. Tidak ada yang disimpan.

```json file=contoh-batch.json
[
  {"cmd": "add", "args": {"type": "income", "account": "bri", "item": "kiriman ortu|300k|uang saku"}},
  {"cmd": "budget alloc", "args": {"item": ["makan|100k", "jajan|50k"]}},
  {"cmd": "savings deposit", "args": {"from": "bri", "to": "darurat", "amount": "50k"}},
  {"cmd": "add", "args": {"type": "expense", "item": ["nasi padang|20k|makan", "kopi|8k"], "raw": "nasi padang 20rb sama kopi 8rb"}},
  {"cmd": "transfer", "args": {"from": "bri", "to": "tunai", "amount": "100k"}},
  {"cmd": "debt pay", "args": {"person": "Andi Saputra", "amount": "all"}}
]
```

```bat
python finance.py batch --file contoh-batch.json
```
```json
{
  "ok": true,
  "message": "6 perintah dari batch tercatat sekaligus (satu undo membatalkan semuanya):\n1. Tercatat pemasukan kiriman ortu Rp300.000 (kategori uang saku) ke bri. Sisa bri Rp587.500. Sisa budget belum teralokasi Rp594.500.\n2. Dialokasikan Rp150.000 dari belum teralokasi: makan Rp100.000, jajan Rp50.000. Sisa budget makan Rp355.000, jajan Rp100.000, belum teralokasi Rp444.500.\n3. Menabung Rp50.000 dari bri ke tabungan darurat (2,7% dari target Rp3.000.000); budget belum teralokasi berkurang Rp50.000. Sisa bri Rp537.500, tabungan darurat Rp80.000. Sisa budget belum teralokasi Rp394.500.\n4. Tercatat 2 pengeluaran (Rp28.000) dari tunai (dompet default): nasi padang Rp20.000 [makan]; kopi Rp8.000 [jajan, ditebak dari kata 'kopi']. Sisa tunai Rp284.000. Sisa budget makan Rp335.000, jajan Rp92.000.\n5. Tarik tunai Rp100.000 dari bri ke tunai. Sisa bri Rp437.500, tunai Rp384.000.\n6. Andi Saputra membayar piutang Rp60.000, masuk ke tunai (dompet default). Piutang dari Andi Saputra (#3) LUNAS. Sisa tunai Rp444.000. Sisa budget belum teralokasi Rp454.500.",
  "data": {
    "group_id": "<acak>",
    "count": 6,
    "source": "contoh-batch.json",
    "results": [
      {
        "index": 1,
        "cmd": "add",
        "message": "Tercatat pemasukan kiriman ortu Rp300.000 (kategori uang saku) ke bri. Sisa bri Rp587.500. Sisa budget belum teralokasi Rp594.500.",
        "data": {
          "group_id": "<acak>",
          "type": "income",
          "account": "bri",
          "used_default_account": false,
          "ts": "2026-10-06 12:00:00",
          "total": 300000,
          "balance_after": 587500,
          "items": [
            {
              "id": 26,
              "note": "kiriman ortu",
              "amount": 300000,
              "category": "uang saku",
              "category_source": "given",
              "budget": "belum teralokasi",
              "budget_balance": 594500
            }
          ]
        }
      },
      {
        "index": 2,
        "cmd": "budget alloc",
        "message": "Dialokasikan Rp150.000 dari belum teralokasi: makan Rp100.000, jajan Rp50.000. Sisa budget makan Rp355.000, jajan Rp100.000, belum teralokasi Rp444.500.",
        "data": {
          "group_id": "<acak>",
          "total": 150000,
          "items": [
            {
              "id": 5,
              "budget": "makan",
              "amount": 100000,
              "balance_after": 355000
            },
            {
              "id": 6,
              "budget": "jajan",
              "amount": 50000,
              "balance_after": 100000
            }
          ],
          "unallocated_balance": 444500
        }
      },
      {
        "index": 3,
        "cmd": "savings deposit",
        "message": "Menabung Rp50.000 dari bri ke tabungan darurat (2,7% dari target Rp3.000.000); budget belum teralokasi berkurang Rp50.000. Sisa bri Rp537.500, tabungan darurat Rp80.000. Sisa budget belum teralokasi Rp394.500.",
        "data": {
          "id": 27,
          "group_id": "<acak>",
          "from": "bri",
          "to": "darurat",
          "amount": 50000,
          "budget": "belum teralokasi",
          "balance_from": 537500,
          "savings": {
            "id": 4,
            "name": "darurat",
            "balance": 80000,
            "target_amount": 3000000,
            "target_date": "2027-06-30",
            "archived": false,
            "percent": 2.7,
            "shortfall": 2920000,
            "month_change": 80000,
            "loans_outstanding": 0
          },
          "budget_balance": 394500
        }
      }
    ]
  }
}
```

Satu `undo` membatalkan keenam perintah di atas:

```bat
python finance.py undo
```
```json
{
  "ok": true,
  "message": "Dibatalkan 8 catatan dari pencatatan terakhir:\n- #26 06/10/2026 12:00 · pemasukan Rp300.000 · kiriman ortu [uang saku] · bri\n- #27 06/10/2026 12:00 · menabung Rp50.000 · menabung ke darurat (budget belum teralokasi) · bri → darurat\n- #28 06/10/2026 12:00 · pengeluaran Rp20.000 · nasi padang [makan] · tunai\n- #29 06/10/2026 12:00 · pengeluaran Rp8.000 · kopi [jajan] · tunai\n- #30 06/10/2026 12:00 · transfer Rp100.000 · (tanpa catatan) · bri → tunai\n- #31 06/10/2026 12:00 · hutang/piutang masuk Rp60.000 · Andi Saputra bayar piutang · tunai\n- pindah budget Rp100.000 belum teralokasi → makan\n- pindah budget Rp50.000 belum teralokasi → jajan\nSisa bri Rp287.500, tabungan darurat Rp30.000, tunai Rp312.000. Sisa budget belum teralokasi Rp294.500, makan Rp255.000, jajan Rp50.000.",
  "data": {
    "group_id": "<acak>",
    "action": "batch",
    "undone": [
      26,
      27,
      28
    ],
    "undone_moves": [
      5,
      6
    ],
    "restored": [],
    "removed": [],
    "transactions": [
      {
        "id": 26,
        "ts": "2026-10-06 12:00:00",
        "type": "income",
        "amount": 300000,
        "account": "bri",
        "to_account": null,
        "category": "uang saku",
        "budget": "belum teralokasi",
        "debt_id": null,
        "note": "kiriman ortu",
        "raw_text": null,
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      },
      {
        "id": 27,
        "ts": "2026-10-06 12:00:00",
        "type": "deposit",
        "amount": 50000,
        "account": "bri",
        "to_account": "darurat",
        "category": null,
        "budget": "belum teralokasi",
        "debt_id": null,
        "note": "menabung ke darurat",
        "raw_text": null,
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      },
      {
        "id": 28,
        "ts": "2026-10-06 12:00:00",
        "type": "expense",
        "amount": 20000,
        "account": "tunai",
        "to_account": null,
        "category": "makan",
        "budget": "makan",
        "debt_id": null,
        "note": "nasi padang",
        "raw_text": "nasi padang 20rb sama kopi 8rb",
        "group_id": "<acak>",
        "deleted_at": null,
        "source": "wallet"
      }
    ]
  }
}
```

Jika satu perintah salah, tidak ada yang tersimpan:

```json file=contoh-batch-salah.json
[
  {"cmd": "add", "args": {"type": "expense", "item": "bakso|15k"}},
  {"cmd": "add", "args": {"type": "expense", "account": "bca", "item": "parkir|2k"}}
]
```

```bat
python finance.py batch --file contoh-batch-salah.json
```
```json
{
  "ok": false,
  "error": {
    "code": "UNKNOWN_ACCOUNT",
    "message": "Perintah ke-2 (add): Dompet 'bca' tidak ada. Tidak ada yang disimpan.",
    "hint": "Pilihan: tunai, bri",
    "data": {
      "index": 2,
      "cmd": "add"
    }
  }
}
```

Lewat stdin (misalnya dari program lain). Di PowerShell 5.1, atur dulu `$OutputEncoding` ke UTF-8 supaya huruf
non-ASCII tidak rusak:

```
$OutputEncoding = [Text.UTF8Encoding]::new($false)
Get-Content contoh-batch.json -Raw | python finance.py batch --stdin
```

Error: `BAD_ARGS` (file tidak ada, JSON tidak sah, format salah, perintah tidak boleh), ditambah semua error perintah
di dalamnya.

---

## Cara memetakan chat ke perintah

Pedoman untuk pemanggil yang menerjemahkan chat bebas:

1. Panggil `context` dulu untuk mengetahui nama dompet, kategori, budget, tabungan, dan hutang yang sah. Jangan
   mengarang nama; jika tidak ada yang cocok, tanyakan ke pengguna. Backend tidak pernah membuat dompet atau
   kategori diam-diam.
2. Nominal salin apa adanya (`15k`, `1,5jt`, `20rb`); backend yang menghitung. Jangan menghitung total sendiri.
3. Dompet tidak disebut: jangan isi `--account` (dompet default dipakai dan disebut di `message`).
4. Kategori tidak jelas: kosongkan bagian kategori di `--item` (ditebak dari kata kunci, atau `lainnya`).
5. Simpan kalimat asli pengguna di `--raw`.
6. Beberapa hal dalam satu chat yang berbeda jenis (pemasukan dan pengeluaran, alokasi lalu belanja): pakai `batch`
   supaya tersimpan bersama dan bisa di-undo sekaligus.
7. Kirim `message` ke pengguna apa adanya. Jika `ok` false, sampaikan `error.message` dan gunakan `error.hint` untuk
   bertanya atau memperbaiki perintah.
8. `AMBIGUOUS_DEBT`: tanyakan yang mana dari `error.data.candidates`, lalu ulangi dengan `--id`.
9. Tabungan bukan budget dan bukan dompet biasa. "Nabung" = `savings deposit`; "ambil dari tabungan" =
   `savings withdraw`; "beli X pakai tabungan" = `savings spend --mode purpose` jika memang tujuan tabungannya,
   atau `--mode debt` jika pengguna berniat mengembalikannya (lalu `debt pay --person "<tabungan>"` saat dikembalikan).
   Jika tidak jelas, tanyakan: "pakai tabungan untuk tujuannya, atau pinjam dulu dan nanti diganti?"

| Chat | Perintah |
|---|---|
| beli ayam goreng 15k | `add --type expense --item "ayam goreng\|15k\|makan" --raw "beli ayam goreng 15k"` |
| gajian 600k | `add --type income --item "gajian\|600k\|gaji"` |
| gajian 2jt masuk BRI | `add --type income --account bri --item "gajian\|2jt\|gaji"` |
| jajan 10k dan es teh 3k | `add --type expense --item "jajan\|10k\|jajan" --item "es teh\|3k\|jajan"` |
| jajan, parkir, dan makan total 50k | `add --type expense --item "jajan, parkir, makan\|50k\|makan"` |
| kemarin beli bensin 30rb pakai gopay | `add --type expense --account gopay --date yesterday --item "bensin\|30rb\|transport"` |
| tanggal 3 kemarin beli buku 85k | `add --type expense --date 2026-10-03 --item "buku\|85k\|pendidikan"` |
| alokasikan makan 300k, transport 100k | `budget alloc --item "makan\|300k" --item "transport\|100k"` |
| bagi gaji: makan 500k, jajan 200k | `budget alloc --item "makan\|500k" --item "jajan\|200k"` |
| pindah 50k dari makan ke jajan | `budget move --from makan --to jajan --amount 50k` |
| balikin semua sisa transport ke belum teralokasi | `budget move --from transport --to "belum teralokasi" --amount all` |
| budget transport udah ga dipakai | `budget close transport` |
| sisa budget saya | `budget list` |
| bikin tabungan laptop target 8 juta sebelum Juni | `savings add "tabungan laptop" --target 8jt --target-date 2027-06-01` |
| aku udah punya tabungan darurat 2 juta di rekening lain | `savings add "dana darurat" --opening 2jt` |
| nabung 100k | `savings deposit --from bri --to tabungan --amount 100k` |
| nabung 300k ke dana darurat dari BRI | `savings deposit --from bri --to "dana darurat" --amount 300k` |
| sisihkan 50k dari budget jajan buat tabungan laptop | `savings deposit --from tunai --to "tabungan laptop" --amount 50k --from-budget jajan` |
| ambil 200k dari dana darurat buat makan | `savings withdraw --from "dana darurat" --to tunai --amount 200k --to-budget makan` |
| tarik semua tabungan liburan ke BRI | `savings withdraw --from liburan --to bri --amount all` |
| beli laptop 5jt pakai tabungan laptop | `savings spend --from "tabungan laptop" --item "laptop\|5jt\|belanja" --mode purpose` |
| pinjam dulu dana darurat 200k buat servis motor, nanti aku ganti | `savings spend --from "dana darurat" --item "servis motor\|200k\|transport" --mode debt` |
| ganti 100k ke dana darurat yang kemarin kupakai servis | `debt pay --person "dana darurat" --amount 100k` |
| saldo tabungan laptop sebenarnya 1,2 juta | `adjust --account "tabungan laptop" --actual 1,2jt` |
| tabungan saya saat ini | `savings list` |
| target dana darurat naikin jadi 10 juta | `savings set "dana darurat" --target 10jt` |
| sisa uang di BRI | `balance --account bri` |
| sisa uang total (dompet dan tabungan, terpisah) | `balance` |
| berapa yang kupakai dari tabungan bulan ini (lihat `data.savings_expense`) | `report --period this-month --type expense` |
| pengeluaran bulan ini | `report --period this-month --type expense` |
| pengeluaran bulan Agustus | `report --period 2026-08 --type expense` |
| pengeluaran 3 bulan terakhir | `report --period last:3 --type expense` |
| pemasukan dan pengeluaran minggu ini | `report --period this-week --type all` |
| habis berapa buat makan bulan ini | `report --period this-month --type expense --category makan` |
| transaksi kopi bulan ini apa aja | `list --period this-month --search kopi` |
| analisis pengeluaran | `analyze --period this-month` |
| tarik tunai 200k di ATM BRI, admin 2.5k | `transfer --from bri --to tunai --amount 200k --fee 2.5k` |
| top up gopay 50k dari BRI | `transfer --from bri --to gopay --amount 50k` |
| tambah dompet gopay isi 50k | `account add gopay --type ewallet --opening 50k` |
| hapus dompet gopay, sisanya ke BRI | `account remove gopay --move-to bri` |
| kosongkan dompet tunai | `adjust --account tunai --actual 0` |
| saldo BRI sebenarnya 450k | `adjust --account bri --actual 450k` |
| tunai ternyata minus 5 ribu | `adjust --account tunai --actual=-5k` |
| tambah kategori "kucing" | `category add kucing --kind expense` |
| hapus kategori hiburan | `category remove hiburan --kind expense` |
| kalau aku bilang "cash" maksudnya tunai | `alias add --kind account --alias cash --target tunai` |
| pinjam 50k dari Budi | `debt add --direction i_owe --person Budi --amount 50k` |
| pinjam 300k dari Budi, janji balikin tanggal 20 | `debt add --direction i_owe --person Budi --amount 300k --due 2026-10-20` |
| Andi pinjam 100k | `debt add --direction owed_to_me --person Andi --amount 100k` |
| Andi pinjam 100k dari BRI, potong dari budget jajan | `debt add --direction owed_to_me --person Andi --amount 100k --account bri --budget jajan` |
| makan siang 25k dibayarin Citra | `debt add --direction i_owe --person Citra --amount 25k --paid-for "makan siang\|makan"` |
| Rina traktir kopi 18k, nanti aku ganti | `debt add --direction i_owe --person Rina --amount 18k --paid-for "kopi"` |
| aku masih utang 200k ke Dodi dari bulan lalu | `debt add --direction i_owe --person Dodi --amount 200k --no-cash --note "utang bulan lalu"` |
| bayar hutang Budi 20k | `debt pay --person Budi --amount 20k` |
| lunasin hutang ke Budi | `debt pay --person Budi --amount all` |
| Andi bayar 50k | `debt pay --person Andi --amount 50k` |
| siapa aja yang masih utang | `debt list --direction owed_to_me` |
| hutang piutang saya | `debt list` |
| hutang Andi diikhlaskan saja | `debt remove --person Andi --write-off` |
| tagihan kos 500k tiap tanggal 5 dari BRI | `recurring add kos --amount 500k --day 5 --account bri` |
| udah bayar kos | `recurring pay kos` |
| bayar listrik bulan ini 87rb | `recurring pay listrik --amount 87rb` |
| bayar kos bulan November duluan | `recurring pay kos --month 2026-11` |
| tagihan apa aja yang belum dibayar | `recurring list` |
| batalkan yang terakhir | `undo` |
| yang tadi salah, harusnya 18k (ID dari `list` atau dari `data` hasil pencatatan, misalnya 12) | `edit 12 --amount 18k` |
| hapus transaksi nomor 12 | `delete 12` |
| ekspor bulan ini | `export --period this-month` |
| gajian 2jt, langsung alokasi makan 800k dan nabung 300k (isi file di bawah) | `batch --file gajian.json` |

Isi `gajian.json` untuk chat terakhir:

```json file=gajian.json
[
  {"cmd": "add", "args": {"type": "income", "item": "gajian|2jt|gaji", "raw": "gajian 2jt, langsung alokasi makan 800k dan nabung 300k"}},
  {"cmd": "budget alloc", "args": {"item": "makan|800k"}},
  {"cmd": "savings deposit", "args": {"from": "tunai", "to": "darurat", "amount": "300k"}}
]
```

```bat
python finance.py batch --file gajian.json
```
```json
{
  "ok": true,
  "message": "3 perintah dari batch tercatat sekaligus (satu undo membatalkan semuanya):\n1. Tercatat pemasukan gajian Rp2.000.000 (kategori gaji) ke tunai (dompet default). Sisa tunai Rp2.312.000. Sisa budget belum teralokasi Rp2.294.500.\n2. Dialokasikan Rp800.000 dari belum teralokasi: makan Rp800.000. Sisa budget makan Rp1.055.000, belum teralokasi Rp1.494.500.\n3. Menabung Rp300.000 dari tunai ke tabungan darurat (11,0% dari target Rp3.000.000); budget belum teralokasi berkurang Rp300.000. Sisa tunai Rp2.012.000, tabungan darurat Rp330.000. Sisa budget belum teralokasi Rp1.194.500.",
  "data": {
    "group_id": "<acak>",
    "count": 3,
    "source": "gajian.json",
    "results": [
      {
        "index": 1,
        "cmd": "add",
        "message": "Tercatat pemasukan gajian Rp2.000.000 (kategori gaji) ke tunai (dompet default). Sisa tunai Rp2.312.000. Sisa budget belum teralokasi Rp2.294.500.",
        "data": {
          "group_id": "<acak>",
          "type": "income",
          "account": "tunai",
          "used_default_account": true,
          "ts": "2026-10-06 12:00:00",
          "total": 2000000,
          "balance_after": 2312000,
          "items": [
            {
              "id": 32,
              "note": "gajian",
              "amount": 2000000,
              "category": "gaji",
              "category_source": "given",
              "budget": "belum teralokasi",
              "budget_balance": 2294500
            }
          ]
        }
      },
      {
        "index": 2,
        "cmd": "budget alloc",
        "message": "Dialokasikan Rp800.000 dari belum teralokasi: makan Rp800.000. Sisa budget makan Rp1.055.000, belum teralokasi Rp1.494.500.",
        "data": {
          "group_id": "<acak>",
          "total": 800000,
          "items": [
            {
              "id": 7,
              "budget": "makan",
              "amount": 800000,
              "balance_after": 1055000
            }
          ],
          "unallocated_balance": 1494500
        }
      },
      {
        "index": 3,
        "cmd": "savings deposit",
        "message": "Menabung Rp300.000 dari tunai ke tabungan darurat (11,0% dari target Rp3.000.000); budget belum teralokasi berkurang Rp300.000. Sisa tunai Rp2.012.000, tabungan darurat Rp330.000. Sisa budget belum teralokasi Rp1.194.500.",
        "data": {
          "id": 33,
          "group_id": "<acak>",
          "from": "tunai",
          "to": "darurat",
          "amount": 300000,
          "budget": "belum teralokasi",
          "balance_from": 2012000,
          "savings": {
            "id": 4,
            "name": "darurat",
            "balance": 330000,
            "target_amount": 3000000,
            "target_date": "2027-06-30",
            "archived": false,
            "percent": 11.0,
            "shortfall": 2670000,
            "month_change": 330000,
            "loans_outstanding": 0
          },
          "budget_balance": 1194500
        }
      }
    ]
  }
}
```
