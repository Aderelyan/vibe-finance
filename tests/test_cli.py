"""Tes lewat subprocess: stdout harus satu objek JSON, exit code sesuai."""
import pytest

from conftest import run_subprocess


@pytest.mark.parametrize("args, code", [
    ([], "BAD_ARGS"),
    (["terbang"], "BAD_ARGS"),
    (["add"], "BAD_ARGS"),
    (["add", "--type", "expense"], "BAD_ARGS"),
    (["add", "--type", "boros", "--item", "x|1k"], "BAD_ARGS"),
    (["add", "--tipe", "expense"], "BAD_ARGS"),
    (["edit", "abc"], "BAD_ARGS"),
    (["account"], "BAD_ARGS"),
    (["report", "--period", "kapan-kapan"], "BAD_PERIOD"),
    (["--now", "kemarin sore", "balance"], "BAD_DATE"),
    (["balance", "--account", "bca"], "UNKNOWN_ACCOUNT"),
])
def test_bad_input_is_json(tmp_path, args, code):
    obj = run_subprocess(tmp_path, *args)
    assert obj["ok"] is False
    assert obj["error"]["code"] == code
    assert obj["error"]["message"]


def test_help_is_json(tmp_path):
    obj = run_subprocess(tmp_path, "add", "--help")
    assert obj["ok"] is True and "--item" in obj["data"]["help"]


def test_utf8_output(tmp_path):
    run_subprocess(tmp_path, "account", "add", "tunai", "--type", "cash", "--opening", "100k")
    obj = run_subprocess(tmp_path, "add", "--type", "expense", "--item", "kopi ☕ é|5k")
    assert "☕" in obj["message"]


def test_required_scenarios(tmp_path):
    """Skenario wajib (BLUEPRINT bagian 9 dan PERUBAHAN-01 bagian F) yang sudah tersedia."""
    run = lambda *a: run_subprocess(tmp_path, *a)  # noqa: E731
    bud = lambda name: next(b["balance"] for b in run("budget", "list")["data"]["budgets"]  # noqa: E731
                            if b["name"] == name)
    assert run("init")["ok"]
    assert run("account", "add", "tunai", "--type", "cash", "--opening", "150k", "--default")["ok"]
    assert run("account", "add", "bri", "--type", "bank", "--opening", "500k")["ok"]
    assert run("savings", "add", "tabungan", "--target", "2jt")["ok"]

    r = run("add", "--type", "expense", "--item", "ayam goreng|15k|makan")
    assert r["data"]["total"] == 15_000
    before = bud("belum teralokasi")
    r = run("add", "--type", "income", "--item", "gajian|600k|gaji")
    assert r["data"]["balance_after"] == 135_000 + 600_000
    assert bud("belum teralokasi") == before + 600_000
    r = run("budget", "alloc", "--item", "makan|300k", "--item", "transport|100k")
    assert r["data"]["total"] == 400_000
    r = run("budget", "alloc", "--item", "tabungan|100k")
    assert bud("tabungan") == 100_000
    r = run("add", "--type", "expense", "--item", "jajan|10k|jajan", "--item", "es teh|3k|jajan")
    assert r["data"]["total"] == 13_000 and len(r["data"]["items"]) == 2
    r = run("add", "--type", "expense", "--item", "jajan, parkir, makan|50k|makan")
    assert r["data"]["items"][0]["budget_balance"] == 250_000
    r = run("budget", "move", "--from", "makan", "--to", "jajan", "--amount", "50k")
    assert r["data"]["to_balance"] == 50_000
    assert run("budget", "list")["data"]["consistent"] is True
    assert run("savings", "list")["data"]["total"] == 100_000
    assert run("balance", "--account", "bri")["data"]["balance"] == 500_000
    r = run("transfer", "--from", "bri", "--to", "tunai", "--amount", "200k", "--fee", "2.5k")
    assert r["data"]["balance_from"] == 297_500
    r = run("adjust", "--account", "bri", "--actual", "450k")
    assert r["data"]["difference"] == 152_500
    assert run("account", "add", "gopay", "--type", "ewallet", "--opening", "50k")["ok"]
    r = run("account", "remove", "gopay", "--move-to", "bri")
    assert r["data"]["moved_to"] == "bri" and run("balance", "--account", "bri")["data"]["balance"] == 500_000
    r = run("adjust", "--account", "tunai", "--actual", "0")
    assert run("balance", "--account", "tunai")["data"]["balance"] == 0
    assert run("category", "add", "kucing", "--kind", "expense")["ok"]
    assert run("category", "remove", "hiburan", "--kind", "expense")["ok"]
    total = run("balance")["data"]
    assert total["total_dompet"] == 500_000 and total["consistent"] is True
    rep = run("report", "--period", "this-month", "--type", "expense")["data"]
    assert rep["total"] == 15_000 + 13_000 + 50_000 + 2_500
    assert run("report", "--period", "2026-08", "--type", "expense")["data"]["total"] == 0
    assert run("report", "--period", "last:3", "--type", "expense")["data"]["period"]["start"] == "2026-08-01"
    r = run("undo")
    assert r["data"]["undone"] and run("balance", "--account", "tunai")["data"]["balance"] > 0


def test_required_debt_scenarios(tmp_path):
    """Skenario wajib Tahap 2: pinjam dari Budi, Andi pinjam, bayar hutang Budi."""
    run = lambda *a: run_subprocess(tmp_path, *a)  # noqa: E731
    assert run("account", "add", "tunai", "--type", "cash", "--opening", "150k")["ok"]
    r = run("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "50k")
    assert r["data"]["balance_after"] == 200_000
    r = run("debt", "add", "--direction", "owed_to_me", "--person", "Andi", "--amount", "100k")
    assert r["data"]["balance_after"] == 100_000
    r = run("debt", "pay", "--person", "Budi", "--amount", "20k")
    assert r["data"]["remaining"] == 30_000 and r["data"]["balance_after"] == 80_000
    bal = run("balance")["data"]
    assert bal["debt_total"] == 30_000 and bal["receivable_total"] == 100_000
    assert bal["net_worth"] == 80_000 + 100_000 - 30_000 and bal["consistent"] is True
    r = run("recurring", "add", "kos", "--amount", "500k", "--day", "5")
    assert r["ok"]
    assert run("recurring", "pay", "kos", "--amount", "50k")["data"]["month"] == "2026-10"


@pytest.mark.parametrize("args, code", [
    (["debt", "add", "--direction", "pinjam", "--person", "Budi", "--amount", "5k"], "BAD_ARGS"),
    (["debt", "pay", "--amount", "5k"], "BAD_ARGS"),
    (["debt", "pay", "--id", "satu", "--amount", "5k"], "BAD_ARGS"),
    (["recurring", "add", "kos", "--amount", "5k"], "BAD_ARGS"),
    (["recurring", "pay"], "BAD_ARGS"),
])
def test_bad_debt_and_recurring_input_is_json(tmp_path, args, code):
    obj = run_subprocess(tmp_path, *args)
    assert obj["ok"] is False and obj["error"]["code"] == code
