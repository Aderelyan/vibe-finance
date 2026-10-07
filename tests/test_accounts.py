def test_init_is_idempotent(fin):
    again = fin.ok("init")
    assert again["data"]["created"] is False
    assert again["data"]["categories"] == 18
    assert again["data"]["schema_version"] == 4
    cats = fin.ok("category", "list")["data"]["categories"]
    names = {(c["name"], c["kind"]) for c in cats}
    assert ("biaya admin", "expense") in names and ("gaji", "income") in names
    assert len(cats) == 18


def test_account_add_with_opening_and_default(fin):
    r = fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "150k")
    assert r["data"]["account"]["is_default"] is True  # dompet pertama jadi default
    assert "default" in r["message"] and "belum teralokasi" in r["message"]
    r = fin.ok("account", "add", "bri", "--type", "bank", "--opening", "Rp500.000")
    assert r["data"]["account"]["is_default"] is False
    assert fin.balance("tunai") == 150_000
    assert fin.balance("BRI") == 500_000
    listed = fin.ok("account", "list")["data"]["accounts"]
    assert [a["name"] for a in listed] == ["tunai", "bri"]
    # saldo awal adalah penyesuaian (masuk belum teralokasi), bukan pemasukan
    assert fin.ok("report", "--type", "income")["data"]["total"] == 0
    assert fin.ok("budget", "list")["data"]["budgets"][0] == {
        "id": 1, "name": "belum teralokasi", "kind": "unallocated", "balance": 650_000, "archived": False}


def test_account_validation(wallets):
    fin = wallets
    fin.err("BAD_ARGS", "account add", "x")  # perintah tidak dikenal
    fin.err("BAD_ARGS", "account", "add", "TUNAI", "--type", "cash")
    fin.err("BAD_ARGS", "account", "add", "dana", "--type", "crypto")
    fin.err("BAD_ARGS", "account", "add", "celengan", "--type", "savings")  # tabungan lewat savings add
    fin.err("BAD_ARGS", "account", "add", "tabungan", "--type", "bank")  # nama sudah dipakai tabungan
    r = fin.err("UNKNOWN_ACCOUNT", "account", "set-default", "tabungan")
    assert "tabungan, bukan dompet" in r["error"]["message"]
    fin.err("UNKNOWN_ACCOUNT", "account", "rename", "tabungan", "celengan")
    fin.err("UNKNOWN_ACCOUNT", "account", "remove", "tabungan")
    fin.err("BAD_AMOUNT", "account", "add", "dana", "--type", "ewallet", "--opening", "banyak")
    fin.err("BAD_ARGS", "account", "archive", "gopay")  # diganti account remove
    assert len(fin.ok("account", "list")["data"]["accounts"]) == 3


def test_rename_and_default(wallets):
    fin = wallets
    fin.ok("account", "rename", "gopay", "GoPay")
    assert fin.balance("gopay") == 50_000
    fin.err("BAD_ARGS", "account", "rename", "gopay", "bri")
    fin.ok("account", "set-default", "bri")
    r = fin.ok("add", "--type", "expense", "--item", "nasi|10k")
    assert r["data"]["account"] == "bri" and r["data"]["used_default_account"] is True


def test_remove_unused_account_is_deleted(fin):
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "10k")
    fin.ok("account", "add", "dana", "--type", "ewallet")
    fin.ok("alias", "add", "--kind", "account", "--alias", "dn", "--target", "dana")
    r = fin.ok("account", "remove", "dana")
    assert r["data"]["mode"] == "deleted" and "permanen" in r["message"]
    assert fin.ok("account", "list", "--all")["data"]["accounts"][-1]["name"] == "tunai"
    assert fin.ok("alias", "list", "--kind", "account")["data"]["aliases"] == []
    fin.ok("account", "add", "dana", "--type", "ewallet")  # nama boleh dipakai lagi


def test_remove_used_account_is_archived(wallets):
    fin = wallets
    fin.ok("adjust", "--account", "gopay", "--actual", "0")
    r = fin.ok("account", "remove", "gopay")
    assert r["data"]["mode"] == "archived" and "Riwayat" in r["message"]
    assert [a["name"] for a in fin.ok("account", "list")["data"]["accounts"]] == ["tunai", "bri"]
    e = fin.err("UNKNOWN_ACCOUNT", "add", "--type", "expense", "--account", "gopay", "--item", "x|1k")
    assert "sudah dihapus" in e["error"]["message"] and "account add gopay" in e["error"]["hint"]
    assert len(fin.ok("list", "--account", "gopay")["data"]["transactions"]) == 2  # riwayat utuh
    fin.err("UNKNOWN_ACCOUNT", "account", "remove", "gopay")
    # menambah nama yang sama mengaktifkannya kembali
    r = fin.ok("account", "add", "gopay", "--type", "ewallet", "--opening", "30k")
    assert r["data"]["reactivated"] is True and r["data"]["account"]["balance"] == 30_000
    assert "diaktifkan kembali" in r["message"]


def test_remove_account_with_balance(wallets):
    fin = wallets
    before = fin.count_tx()
    e = fin.err("NOT_EMPTY", "account", "remove", "gopay")
    assert "--move-to" in e["error"]["hint"] and "--write-off" in e["error"]["hint"]
    assert e["error"]["data"]["balance"] == 50_000 and fin.count_tx() == before
    fin.err("BAD_ARGS", "account", "remove", "gopay", "--move-to", "bri", "--write-off")
    fin.err("BAD_ARGS", "account", "remove", "gopay", "--move-to", "gopay")
    fin.err("UNKNOWN_ACCOUNT", "account", "remove", "gopay", "--move-to", "bca")

    r = fin.ok("account", "remove", "gopay", "--move-to", "bri")
    assert r["data"]["moved_to"] == "bri" and r["data"]["mode"] == "archived"
    assert fin.balance("bri") == 550_000
    assert fin.ok("balance")["data"]["total_dompet"] == 700_000  # total uang tidak berubah
    assert fin.ok("report", "--type", "all")["data"]["expense"]["total"] == 0

    fin.ok("account", "add", "ovo", "--type", "ewallet", "--opening", "20k")
    unalloc_before = fin.ok("budget", "list")["data"]["budgets"][0]["balance"]
    r = fin.ok("account", "remove", "ovo", "--write-off")
    assert r["data"]["written_off"] is True
    assert fin.ok("budget", "list")["data"]["budgets"][0]["balance"] == unalloc_before - 20_000
    assert fin.ok("balance")["data"]["total_dompet"] == 700_000

    # saldo minus dipindah juga
    fin.ok("account", "add", "dana", "--type", "ewallet", "--opening=-5k")
    fin.ok("account", "remove", "dana", "--move-to", "tunai")
    assert fin.balance("tunai") == 145_000


def test_remove_default_account(wallets):
    fin = wallets
    fin.ok("adjust", "--account", "tunai", "--actual", "0")
    e = fin.err("BAD_ARGS", "account", "remove", "tunai")
    assert "set-default" in e["error"]["hint"]
    fin.ok("account", "set-default", "bri")
    fin.ok("account", "remove", "tunai")


def test_undo_account_remove_restores_it(wallets):
    fin = wallets
    fin.ok("account", "remove", "gopay", "--move-to", "bri")
    r = fin.ok("undo")
    assert r["data"]["restored"] == [{"table": "accounts", "id": 3, "name": "gopay"}]
    assert fin.balance("gopay") == 50_000 and fin.balance("bri") == 500_000
    fin.ok("add", "--type", "expense", "--account", "gopay", "--item", "x|1k")


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


def test_categories_add_rename_remove(wallets):
    fin = wallets
    r = fin.ok("category", "add", "kucing", "--kind", "expense")
    assert "belum teralokasi" in r["message"]
    fin.err("BAD_ARGS", "category", "add", "Makan", "--kind", "expense")
    fin.ok("category", "add", "makan", "--kind", "income")  # nama sama, jenis beda boleh
    fin.ok("category", "add", "tabungan", "--kind", "expense")  # tabungan bukan budget lagi, jadi tidak bentrok
    fin.err("SYSTEM_PROTECTED", "category", "add", "belum teralokasi", "--kind", "expense")

    r = fin.ok("category", "remove", "kucing", "--kind", "expense")
    assert r["data"]["mode"] == "deleted"
    fin.err("UNKNOWN_CATEGORY", "add", "--type", "expense", "--item", "x|1k|kucing")
    r = fin.ok("category", "remove", "hiburan")
    assert r["data"]["mode"] == "deleted"
    assert all(c["name"] != "hiburan" for c in fin.ok("category", "list")["data"]["categories"])
    # kata kunci milik kategori yang dihapus permanen ikut hilang
    assert fin.ok("add", "--type", "expense", "--item", "nonton|50k")["data"]["items"][0]["category"] == "lainnya"

    fin.ok("add", "--type", "expense", "--item", "obat|20k|kesehatan")
    r = fin.ok("category", "remove", "kesehatan")
    assert r["data"]["mode"] == "archived"
    e = fin.err("UNKNOWN_CATEGORY", "add", "--type", "expense", "--item", "x|1k|kesehatan")
    assert "category add" in e["error"]["hint"]
    assert fin.ok("report", "--category", "kesehatan")["data"]["total"] == 20_000  # riwayat utuh
    r = fin.ok("category", "add", "Kesehatan", "--kind", "expense")
    assert r["data"]["reactivated"] is True

    r = fin.ok("category", "rename", "jajan", "camilan")
    fin.ok("add", "--type", "expense", "--item", "keripik|5k|camilan")
    fin.err("BAD_ARGS", "category", "rename", "camilan", "makan", "--kind", "expense")
    fin.err("BAD_ARGS", "category", "remove", "makan")  # ambigu: ada di dua jenis


def test_system_categories_protected(wallets):
    fin = wallets
    for args in (["remove", "lainnya", "--kind", "expense"], ["remove", "lainnya", "--kind", "income"],
                 ["remove", "biaya admin"], ["rename", "biaya admin", "admin"],
                 ["rename", "lainnya", "lain", "--kind", "income"]):
        fin.err("SYSTEM_PROTECTED", "category", *args)


def test_category_remove_closes_budget(wallets):
    fin = wallets
    fin.ok("budget", "alloc", "--item", "hiburan|100k")
    fin.ok("add", "--type", "expense", "--item", "nonton|30k|hiburan")
    unalloc = fin.ok("budget", "list")["data"]["budgets"][0]["balance"]
    r = fin.ok("category", "remove", "hiburan")
    assert r["data"]["mode"] == "archived" and r["data"]["returned_to_unallocated"] == 70_000
    assert "Budget hiburan ditutup" in r["message"]
    data = fin.ok("budget", "list")["data"]
    assert data["budgets"][0]["balance"] == unalloc + 70_000
    assert all(b["name"] != "hiburan" for b in data["budgets"])
    # undo mengembalikan kategori dan budgetnya
    r = fin.ok("undo")
    assert {x["table"] for x in r["data"]["restored"]} == {"categories", "budgets"}
    assert fin.ok("add", "--type", "expense", "--item", "x|10k|hiburan")["data"]["items"][0]["budget"] == "hiburan"
