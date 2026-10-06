def test_init_is_idempotent(fin):
    again = fin.ok("init")
    assert again["data"]["created"] is False
    assert again["data"]["categories"] == 18
    cats = fin.ok("category", "list")["data"]["categories"]
    names = {(c["name"], c["kind"]) for c in cats}
    assert ("biaya admin", "expense") in names and ("gaji", "income") in names
    assert len(cats) == 18


def test_account_add_with_opening_and_default(fin):
    r = fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "150k")
    assert r["data"]["account"]["is_default"] is True  # dompet non-tabungan pertama jadi default
    assert "default" in r["message"]
    r = fin.ok("account", "add", "bri", "--type", "bank", "--opening", "Rp500.000")
    assert r["data"]["account"]["is_default"] is False
    assert fin.balance("tunai") == 150_000
    assert fin.balance("BRI") == 500_000
    listed = fin.ok("account", "list")["data"]["accounts"]
    assert [a["name"] for a in listed] == ["tunai", "bri"]
    # saldo awal adalah penyesuaian, bukan pemasukan
    assert fin.ok("report", "--type", "income")["data"]["total"] == 0


def test_account_validation(wallets):
    fin = wallets
    fin.err("BAD_ARGS", "account add", "x")  # perintah tidak dikenal
    fin.err("BAD_ARGS", "account", "add", "TUNAI", "--type", "cash")
    fin.err("BAD_ARGS", "account", "add", "dana", "--type", "crypto")
    fin.err("BAD_ARGS", "account", "add", "dana", "--type", "ewallet", "--target", "1jt")
    fin.err("BAD_ARGS", "account", "add", "celengan", "--type", "savings", "--default")
    fin.err("BAD_AMOUNT", "account", "add", "dana", "--type", "ewallet", "--opening", "banyak")
    fin.err("BAD_DATE", "account", "add", "celengan", "--type", "savings", "--target-date", "31-12-2026")
    assert len(fin.ok("account", "list")["data"]["accounts"]) == 4


def test_rename_archive_default(wallets):
    fin = wallets
    fin.ok("account", "rename", "gopay", "GoPay")
    assert fin.balance("gopay") == 50_000
    fin.err("BAD_ARGS", "account", "rename", "gopay", "bri")
    # tidak bisa arsip jika saldo bukan 0
    e = fin.err("BAD_ARGS", "account", "archive", "gopay")
    assert "transfer" in e["error"]["hint"]
    fin.ok("adjust", "--account", "gopay", "--actual", "0")
    fin.ok("account", "archive", "gopay")
    e = fin.err("UNKNOWN_ACCOUNT", "add", "--type", "expense", "--account", "gopay", "--item", "x|1k")
    assert "unarchive" in e["error"]["hint"]
    fin.ok("account", "unarchive", "gopay")
    # archive dompet default menghapus status default
    fin.ok("adjust", "--account", "tunai", "--actual", "0")
    r = fin.ok("account", "archive", "tunai")
    assert r["data"]["was_default"] is True
    fin.err("NO_DEFAULT_ACCOUNT", "add", "--type", "expense", "--item", "nasi|10k")
    fin.err("BAD_ARGS", "account", "set-default", "tabungan")
    fin.ok("account", "set-default", "bri")
    r = fin.ok("add", "--type", "expense", "--item", "nasi|10k")
    assert r["data"]["account"] == "bri" and r["data"]["used_default_account"] is True


def test_set_target(wallets):
    fin = wallets
    r = fin.ok("account", "set-target", "tabungan", "--amount", "5jt", "--date", "2027-06-30")
    assert r["data"] == {"id": 4, "target_amount": 5_000_000, "target_date": "2027-06-30"}
    fin.err("BAD_ARGS", "account", "set-target", "bri", "--amount", "1jt")
    fin.err("BAD_ARGS", "account", "set-target", "tabungan")
    r = fin.ok("account", "set-target", "tabungan", "--clear")
    assert r["data"]["target_amount"] is None


def test_aliases(wallets):
    fin = wallets
    fin.ok("alias", "add", "--kind", "account", "--alias", "cash", "--target", "tunai")
    assert fin.balance("CASH") == 150_000
    fin.err("BAD_ARGS", "alias", "add", "--kind", "account", "--alias", "bri", "--target", "tunai")
    fin.err("UNKNOWN_ACCOUNT", "alias", "add", "--kind", "account", "--alias", "x", "--target", "bca")
    fin.ok("alias", "add", "--kind", "category", "--alias", "food", "--target", "makan")
    r = fin.ok("add", "--type", "expense", "--item", "nasi uduk|12k|food")
    assert r["data"]["items"][0]["category"] == "makan"
    # 'lainnya' ada di dua jenis, jadi perlu --target-kind
    fin.err("BAD_ARGS", "alias", "add", "--kind", "keyword", "--alias", "random", "--target", "lainnya")
    fin.ok("alias", "add", "--kind", "keyword", "--alias", "seblak", "--target", "jajan")
    r = fin.ok("add", "--type", "expense", "--item", "seblak level 3|15k")
    assert r["data"]["items"][0]["category"] == "jajan"
    assert "seblak" in r["message"]
    fin.ok("alias", "remove", "--kind", "keyword", "--alias", "SEBLAK")
    fin.err("NOT_FOUND", "alias", "remove", "--kind", "keyword", "--alias", "seblak")
    r = fin.ok("add", "--type", "expense", "--item", "seblak|15k")
    assert r["data"]["items"][0]["category"] == "lainnya"
    assert any(a["alias"] == "cash" for a in fin.ok("alias", "list")["data"]["aliases"])


def test_categories(wallets):
    fin = wallets
    fin.ok("category", "add", "kopi", "--kind", "expense")
    fin.err("BAD_ARGS", "category", "add", "Makan", "--kind", "expense")
    fin.ok("category", "add", "makan", "--kind", "income")  # nama sama, jenis beda boleh
    fin.err("BAD_ARGS", "category", "archive", "lainnya", "--kind", "expense")
    fin.err("BAD_ARGS", "category", "archive", "makan")  # ambigu
    fin.ok("category", "archive", "kopi")
    fin.err("UNKNOWN_CATEGORY", "add", "--type", "expense", "--item", "x|1k|kopi")
    fin.ok("category", "unarchive", "kopi")
    fin.ok("add", "--type", "expense", "--item", "x|1k|kopi")
    e = fin.err("UNKNOWN_CATEGORY", "add", "--type", "expense", "--item", "x|1k|gaji")
    assert "makan" in e["error"]["hint"]
