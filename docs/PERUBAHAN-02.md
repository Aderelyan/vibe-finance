# PERUBAHAN 02: Tabungan menjadi akun terpisah di luar budget

Perubahan atas model tabungan dari `PERUBAHAN-01.md` bagian D (tabungan sebagai budget berjenis `savings`). Sudah
dimasukkan ke `BLUEPRINT.md` (skema v4, bagian 6 "Tabungan") dan `COMMANDS.md`.

## A. Permintaan

1. Aturan utama tetap: total dompet operasional (cash/bank/ewallet) = total budget (`belum teralokasi` + kategori).
   Tabungan tidak lagi bagian dari budget dan tidak ikut aturan ini.
2. Tabungan = akun berjenis `savings` (dompet terpisah), saldo dihitung dari transaksi, target opsional, tidak bisa jadi
   dompet default. Konsep budget tabungan dihapus. Migrasi skema yang aman tetap disediakan.
3. Perintah: `savings add/list/set/rename/remove` (aturan hapus seperti dompet: `--move-to` atau `--write-off` jika
   bersaldo), `savings deposit` (dompet −X, tabungan +X, budget −X; ditolak jika budget sumber tidak cukup),
   `savings withdraw` (kebalikannya), `savings spend --mode purpose` (tabungan −X saja, pengeluaran bersumber
   tabungan), `savings spend --mode debt` (tabungan −X, dicatat sebagai hutang ke tabungan; pelunasan lewat
   `debt pay`: dompet −X, tabungan +X, budget kategori −X, pengeluaran tercatat di kategori itu).
4. `balance` memisahkan dompet dan tabungan (per tabungan). `report`/`analyze` memisahkan pengeluaran dari tabungan.
   `undo`, `batch`, `export`, `context` mendukung tabungan.
5. Semua jaminan lama tetap: soft delete, saldo dihitung, satu `group_id` per aksi, error JSON dengan hint.
6. Tes: invarian acak mencakup tabungan; tes khusus deposit, withdraw, spend purpose, spend debt lalu lunas, saldo
   tabungan tidak cukup, undo tiap operasi.

## B. Model pembukuan

Jenis transaksi baru: `deposit`, `withdraw`, `savings_loan`, `savings_repay`. Setiap jenis seimbang sendiri antara
dompet operasional dan budget, sehingga aturan utama tetap benar setelah `delete`/`undo` transaksi mana pun:

| Jenis | Dompet operasional | Tabungan | Budget |
|---|---|---|---|
| `deposit` | −X | +X | −X |
| `withdraw` | +X | −X | +X |
| `expense` di tabungan (spend purpose) | – | −X | – |
| `savings_loan` (spend debt) | – | −X | – |
| pelunasan: `expense` di dompet + `savings_repay` | −X | +X | −X |
| `adjustment` di tabungan | – | ±X | – |

`budget_id` wajib persis pada transaksi yang mengubah total dompet operasional dan kosong pada yang lain; `insert_tx`
memeriksa ini beserta kelas akun asal/tujuan, dan tes memeriksanya langsung dari tabel setelah setiap perintah.

## C. Keputusan yang diambil sendiri (belum ada di permintaan)

1. **Kode error tidak bertambah.** Saldo tabungan atau budget sumber tidak cukup = `BAD_AMOUNT` (dengan
   `error.data.savings_balance` / `budget_balance`); tabungan dipakai di tempat dompet (atau sebaliknya) =
   `UNKNOWN_ACCOUNT`; nama tabungan dipakai sebagai budget = `UNKNOWN_BUDGET` dengan hint ke perintah `savings`.
2. **`--mode` wajib** pada `savings spend` (tidak ada bawaan), karena dampaknya berbeda jauh. `--item` boleh diulang;
   pada mode debt dibuat satu hutang per item supaya kategori tiap barang tercatat saat dilunasi.
3. **Pinjaman dari tabungan bersifat internal**: tidak masuk total hutang ke orang lain dan tidak mengurangi kekayaan
   bersih (saldo tabungan sudah berkurang; kalau dikurangi lagi jadi ganda). Ditampilkan terpisah sebagai
   "pinjaman dari tabungan" (`savings_loans_total`). `debt rename` ditolak untuk pinjaman ini; `savings rename` ikut
   mengganti namanya. Tabungan yang masih punya pinjaman tidak bisa dihapus (`NOT_EMPTY`).
4. **Kekayaan bersih** = dompet + tabungan + piutang − hutang ke orang lain.
5. **Tabungan hanya lewat perintah `savings`** (plus `adjust`, `balance`, `report`/`list --account`): `add`,
   `transfer`, `debt add/pay --account`, dan `recurring` hanya menerima dompet operasional. `transfer` antar tabungan
   hanya dipakai secara internal oleh `savings remove --move-to <tabungan lain>`.
6. **`savings add --opening`** untuk tabungan yang sudah ada isinya (tidak mengubah dompet maupun budget), dan
   **`savings withdraw --amount all`**.
7. **`savings deposit` hanya menolak jika budget sumber kurang**, bukan jika dompet kurang; saldo dompet boleh minus
   dengan peringatan, sama seperti perintah lain.
8. **`savings withdraw --to-budget`** boleh kategori yang belum punya budget (dibuatkan, seperti `budget move --to`).
9. **`savings set-target` diganti `savings set`** tanpa alias (bot belum dibuat, jadi tidak ada pemanggil lama).
10. **`report --account <tabungan>`** melaporkan tabungan itu saja; tanpa `--account`, angka utama = pengeluaran
    dompet dan pengeluaran dari tabungan ada di `data.savings_expense`. `analyze` menambah blok `data.savings`.
    `export` menambah kolom Sumber, baris TOTAL DOMPET/TOTAL TABUNGAN, dan ringkasan "pengeluaran dari tabungan".
11. **Migrasi v4 yang aman**: budget tabungan lama bersaldo dikembalikan ke `belum teralokasi` (pindahan migrasi,
    tidak bisa di-undo), diarsipkan, lalu dibuat akun tabungan kosong bernama dan bertarget sama. Uang tidak
    dipindahkan ke tabungan secara otomatis karena tidak diketahui dari dompet mana; pengguna mengisinya dengan
    `savings deposit`. Transaksi lama yang menunjuk ke budget tabungan lama tetap utuh (riwayat tidak ditulis ulang).
