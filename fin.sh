#!/usr/bin/env bash
# Pembungkus finance.py untuk bash (MSYS / Git Bash di Windows).
#
#   bash /path/ke/vibe-finance/fin.sh <perintah> [opsi]
#
# - Bisa dipanggil dari folder mana pun; folder kerja pemanggil tidak diubah
#   (path relatif seperti `batch --file x.json` tetap relatif ke folder pemanggil).
# - FINANCE_HOME bawaan: <profil pengguna Windows>/Documents/Manager/Finance/data, hanya jika belum diisi.
# - Argumen diteruskan apa adanya (konversi path otomatis MSYS dimatikan), stdin tetap tersambung,
#   exit code diteruskan. Stdout hanya berisi output finance.py (satu objek JSON).

# Path ke bentuk yang dimengerti Python Windows (C:/x). Backslash -> slash; /c/x -> C:/x; path MSYS lain
# (/tmp/x, /home/x) lewat cygpath, atau jika tidak ada lewat `pwd -W` dari folder induk terdekat yang sudah ada.
to_windows_path() {
    local p="${1//\\//}" head tail="" win
    if [[ $p =~ ^/([a-zA-Z])(/.*)?$ ]]; then
        p="${BASH_REMATCH[1]^^}:${BASH_REMATCH[2]:-/}"
    elif [[ $p == /* ]]; then
        if command -v cygpath >/dev/null 2>&1; then
            p="$(cygpath -m -- "$p")"
        else
            head="${p%/}"
            while [[ -n $head && ! -d $head ]]; do
                tail="/${head##*/}$tail"
                head="${head%/*}"
            done
            win="$(CDPATH='' cd -- "${head:-/}" >/dev/null 2>&1 && pwd -W 2>/dev/null)"
            [[ -n $win ]] && p="${win%/}$tail"
        fi
    fi
    printf '%s' "$p"
}

json_escape() {
    local s="${1//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

fail_json() {
    printf '{"ok": false, "error": {"code": "INTERNAL", "message": "%s", "hint": "%s"}}\n' \
        "$(json_escape "$1")" "$(json_escape "$2")"
    exit 1
}

# folder skrip ini, lewat path apa pun yang dipakai untuk memanggilnya
source_path="${BASH_SOURCE[0]}"
while [[ -L $source_path ]]; do
    link="$(readlink "$source_path")"
    [[ $link == /* ]] || link="$(dirname "$source_path")/$link"
    source_path="$link"
done
root="$(CDPATH='' cd -- "$(dirname -- "$source_path")" >/dev/null 2>&1 && { pwd -W 2>/dev/null || pwd; })"
[[ -n $root ]] || fail_json "Folder fin.sh tidak bisa ditentukan dari '$source_path'." \
    "Panggil dengan path lengkap, contoh: bash C:/path/ke/vibe-finance/fin.sh context"
root="$(to_windows_path "$root")"

python="$root/.venv/Scripts/python.exe"
if [[ ! -f $python ]]; then
    fail_json "Python virtual environment tidak ditemukan di $root/.venv." \
        "Buat dulu dari folder $root: python -m venv .venv, lalu .venv/Scripts/python -m pip install -r requirements.txt"
fi

if [[ -z ${FINANCE_HOME:-} ]]; then
    profile="${USERPROFILE:-$HOME}"
    [[ -n $profile ]] || fail_json "FINANCE_HOME belum diisi dan folder profil pengguna tidak diketahui." \
        "Isi FINANCE_HOME dengan folder data, contoh: FINANCE_HOME=C:/data/finance bash fin.sh context"
    FINANCE_HOME="$(to_windows_path "$profile")/Documents/Manager/Finance/data"
else
    FINANCE_HOME="$(to_windows_path "$FINANCE_HOME")"
fi
export FINANCE_HOME
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' exec "$python" "$root/finance.py" "$@"
