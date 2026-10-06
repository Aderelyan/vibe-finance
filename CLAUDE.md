# CLAUDE.md

Backend pencatat keuangan pribadi: CLI `finance.py` + SQLite. Spesifikasi lengkap ada di `BLUEPRINT.md`.

## Prinsip yang tidak boleh dilanggar

1. **Semua hitungan ada di kode.** Saldo, total, persen, selisih, semuanya dihitung `finance.py`.
2. **Script tidak percaya input.** Setiap argumen divalidasi. Input salah ditolak dengan pesan yang menjelaskan cara memperbaikinya, dan data tidak berubah.
3. **Setiap output adalah satu objek JSON** dengan field `message` berbahasa Indonesia yang bisa langsung dibaca orang.
4. **Saldo tidak disimpan, selalu dihitung** dari tabel transaksi.
5. **Tidak ada yang benar-benar dihapus.** Hapus berarti soft delete (`deleted_at`).
6. **Nominal adalah integer rupiah.** Tidak ada float.
7. **Excel hanya hasil ekspor.** Sumber kebenaran adalah SQLite.
8. **Tidak ada input interaktif.** Tidak boleh ada `input()` atau prompt. Semua lewat argumen, supaya bisa dipanggil program lain.

## Peta kode

- `fin/cli.py`: parser (error argparse → JSON `BAD_ARGS`), opsi tersembunyi `--now`, penangkap `INTERNAL`.
- `fin/db.py`: skema, migrasi via `meta.schema_version`, `write(conn)` = satu transaksi DB + backup harian.
- `fin/parse.py`: `parse_amount`, `parse_date`, `parse_period`. Semua input nominal/tanggal/periode lewat sini.
- `fin/resolve.py`: cari dompet/kategori dari nama atau alias; tebak kategori dari kata kunci.
- `fin/ledger.py`: tulis transaksi, hitung saldo. `fin/report.py`: ringkasan per kategori.
- `fin/commands/*.py`: satu modul per kelompok perintah, masing-masing punya `register(sub)`.

## Aturan kerja

- Error yang diketahui: lempar `FinError(code, message, hint)`. Kode error tetap (lihat `fin/output.py`); jangan menambah kode baru tanpa memperbarui dokumentasi.
- Validasi dulu, baru tulis di dalam `with write(conn):`.
- Tes: `.venv\Scripts\python -m pytest -q`. Tes memakai `FINANCE_HOME` sementara dan `--now`.
