# CLAUDE.md

Backend pencatat keuangan pribadi: CLI `finance.py` + SQLite. Spesifikasi lengkap ada di `BLUEPRINT.md`;
riwayat perubahan spesifikasi ada di `docs\`.

## Prinsip yang tidak boleh dilanggar

1. **Semua hitungan ada di kode.** Saldo, total, persen, selisih, semuanya dihitung `finance.py`.
2. **Script tidak percaya input.** Setiap argumen divalidasi. Input salah ditolak dengan pesan yang menjelaskan cara memperbaikinya, dan data tidak berubah.
3. **Setiap output adalah satu objek JSON** dengan field `message` berbahasa Indonesia yang bisa langsung dibaca orang.
4. **Saldo tidak disimpan, selalu dihitung** dari tabel transaksi (dompet) dan transaksi + pindahan budget (budget).
5. **Transaksi tidak pernah benar-benar dihapus.** Hapus transaksi = soft delete (`deleted_at`). Dompet, kategori, budget, tabungan yang sudah pernah dipakai diarsipkan; yang belum pernah dipakai boleh dihapus sungguhan.
6. **Nominal adalah integer rupiah.** Tidak ada float.
7. **Excel hanya hasil ekspor.** Sumber kebenaran adalah SQLite.
8. **Tidak ada input interaktif.** Tidak boleh ada `input()` atau prompt. Semua lewat argumen, supaya bisa dipanggil program lain.
9. **Total semua dompet selalu sama dengan total semua budget.** Setiap transaksi selain `transfer` wajib punya `budget_id`; transfer wajib tidak punya. Pindahan budget selalu berpasangan.

## Peta kode

- `fin/cli.py`: parser (error argparse → JSON `BAD_ARGS`), opsi tersembunyi `--now`, penangkap `INTERNAL`.
- `fin/db.py`: skema, migrasi via `meta.schema_version` (sekarang v3), `write(conn)` = satu transaksi DB + backup harian.
  Folder data: `FINANCE_HOME`, atau `default_home()` = `<USERPROFILE atau HOME>/Documents/Manager/Finance/data`
  (aturan yang sama dengan `fin.sh`; jangan tulis username di repo). Itu folder data ASLI pengguna.
- `fin/parse.py`: `parse_amount`, `parse_date`, `parse_period`. Semua input nominal/tanggal/periode lewat sini.
- `fin/resolve.py`: cari dompet/kategori dari nama atau alias; tebak kategori dari kata kunci.
- `fin/ledger.py`: tulis transaksi, saldo dompet, `new_group()` (mencatat ke `op_groups` untuk urutan undo).
- `fin/budgets.py`: saldo budget, `find()` (budget dari nama budget/kategori), pindahan, tutup budget.
- `fin/report.py`: ringkasan per kategori. `fin/debts.py`: sisa dan status hutang, `find()` dari `--person`/`--id`.
- `fin/analysis.py`: fakta `analyze` (periode sebelumnya, harian, proyeksi). `fin/export.py`: workbook .xlsx;
  `openpyxl` hanya diimpor di dalam `cmd_export` supaya perintah lain tetap ringan.
- `fin/commands/batch.py`: entri JSON → argv → parser yang sama. Di dalam `db.batch()`, `write()` tidak membuka
  transaksi sendiri dan `new_group()` mengembalikan group batch (restore digabung). `fin/commands/context.py`.
- `COMMANDS.md` adalah kontrak untuk bot. Contohnya dijalankan sungguhan: setelah mengubah perilaku, pesan, atau
  opsi, jalankan `.venv\Scripts\python tools\commands_doc.py`, periksa diff COMMANDS.md, lalu tes.
  `tests/test_commands_doc.py` gagal jika ada perintah/opsi yang belum didokumentasikan atau output yang berubah.
- `fin.sh`: pembungkus bash MSYS (dipakai bot). Bawaan `FINANCE_HOME` dihitung dari `USERPROFILE`, jangan
  menulis path berisi nama pengguna. Konversi path MSYS dimatikan supaya argumen sampai apa adanya; folder kerja
  pemanggil tidak diubah. Harus LF (`.gitattributes`). `tests/test_fin_sh.py` mencari bash MSYS (bukan WSL) dan
  dilewati jika tidak ada.
- `demo.py`: skenario dua bulan sebagai data (nominal integer); `tests/test_demo.py` memeriksa angkanya dari data itu.
- `fin/recurring.py`: jatuh tempo tagihan rutin, `recompute_last_paid()` dari `recurring_payments`.
- `delete`/`undo` lewat `_soft_delete` di `commands/transactions.py`: menghitung ulang status hutang dan `last_paid_month`.
  `op_groups.restore` berisi `[tabel, id]` (aktifkan lagi saat undo) atau `[tabel, id, 1]` (arsipkan saat undo).
- `fin/commands/*.py`: satu modul per kelompok perintah, masing-masing punya `register(sub)`.

## Aturan kerja

- Error yang diketahui: lempar `FinError(code, message, hint)`. Kode error tetap (lihat `fin/output.py`); jangan menambah kode baru tanpa memperbarui BLUEPRINT dan dokumentasi.
- Validasi dulu, baru tulis di dalam `with write(conn):`. Error di dalam blok itu membatalkan semuanya.
- Setiap pencatatan uang (transaksi atau pindahan budget) memakai `group_id` dari `new_group(conn, action, restore)` supaya bisa di-undo.
- Tes: `.venv\Scripts\python -m pytest -q`. Tes memakai `FINANCE_HOME` sementara dan `--now`, dan setiap pemanggilan di tes memeriksa total dompet = total budget.
  Fixture autouse `_never_touch_real_data` di `tests/conftest.py` mengarahkan `FINANCE_HOME`, `USERPROFILE`, dan
  `HOME` ke folder sementara; jangan dihapus. Saat mencoba perintah manual, selalu set `FINANCE_HOME` ke folder
  sementara supaya data asli tidak tersentuh.
- Repo publik `origin` (github.com/Aderelyan/vibe-finance), branch `main`. Jangan commit database, backup, ekspor, `setup_awal.cmd`, atau data pribadi. Push setelah tahap selesai dan tes lolos; jangan force push.
