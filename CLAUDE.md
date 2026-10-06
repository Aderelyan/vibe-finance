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
- `fin/db.py`: skema, migrasi via `meta.schema_version` (sekarang v2), `write(conn)` = satu transaksi DB + backup harian.
- `fin/parse.py`: `parse_amount`, `parse_date`, `parse_period`. Semua input nominal/tanggal/periode lewat sini.
- `fin/resolve.py`: cari dompet/kategori dari nama atau alias; tebak kategori dari kata kunci.
- `fin/ledger.py`: tulis transaksi, saldo dompet, `new_group()` (mencatat ke `op_groups` untuk urutan undo).
- `fin/budgets.py`: saldo budget, `find()` (budget dari nama budget/kategori), pindahan, tutup budget.
- `fin/report.py`: ringkasan per kategori. `fin/debts.py`: sisa hutang.
- `fin/commands/*.py`: satu modul per kelompok perintah, masing-masing punya `register(sub)`.

## Aturan kerja

- Error yang diketahui: lempar `FinError(code, message, hint)`. Kode error tetap (lihat `fin/output.py`); jangan menambah kode baru tanpa memperbarui BLUEPRINT dan dokumentasi.
- Validasi dulu, baru tulis di dalam `with write(conn):`. Error di dalam blok itu membatalkan semuanya.
- Setiap pencatatan uang (transaksi atau pindahan budget) memakai `group_id` dari `new_group(conn, action, restore)` supaya bisa di-undo.
- Tes: `.venv\Scripts\python -m pytest -q`. Tes memakai `FINANCE_HOME` sementara dan `--now`, dan setiap pemanggilan di tes memeriksa total dompet = total budget.
- Repo publik `origin` (github.com/Aderelyan/vibe-finance), branch `main`. Jangan commit database, backup, ekspor, `setup_awal.cmd`, atau data pribadi. Push setelah tahap selesai dan tes lolos; jangan force push.
