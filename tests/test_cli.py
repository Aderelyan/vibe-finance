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


def test_required_scenarios_stage1(tmp_path):
    """Skenario wajib (bagian 9) yang sudah tersedia di tahap 1."""
    run = lambda *a: run_subprocess(tmp_path, *a)  # noqa: E731
    assert run("init")["ok"]
    assert run("account", "add", "tunai", "--type", "cash", "--opening", "150k", "--default")["ok"]
    assert run("account", "add", "bri", "--type", "bank", "--opening", "500k")["ok"]
    assert run("account", "add", "tabungan", "--type", "savings")["ok"]

    r = run("add", "--type", "expense", "--item", "ayam goreng|15k|makan")
    assert r["data"]["total"] == 15_000
    r = run("add", "--type", "income", "--item", "gajian|600k|gaji")
    assert r["data"]["balance_after"] == 135_000 + 600_000
    r = run("add", "--type", "expense", "--item", "jajan|10k|jajan", "--item", "es teh|3k|jajan")
    assert r["data"]["total"] == 13_000 and len(r["data"]["items"]) == 2
    r = run("add", "--type", "expense", "--item", "jajan, parkir, makan|50k|makan")
    assert r["data"]["total"] == 50_000
    assert run("balance", "--account", "bri")["data"]["balance"] == 500_000
    r = run("transfer", "--from", "bri", "--to", "tabungan", "--amount", "100k")
    assert r["data"]["balance_to"] == 100_000
    r = run("transfer", "--from", "bri", "--to", "tunai", "--amount", "200k", "--fee", "2.5k")
    assert r["data"]["balance_from"] == 197_500
    r = run("adjust", "--account", "bri", "--actual", "450k")
    assert r["data"]["difference"] == 252_500
    tunai = 150_000 - 15_000 + 600_000 - 13_000 - 50_000 + 200_000
    total = run("balance")["data"]
    assert total["total"] == tunai + 450_000 + 100_000
    rep = run("report", "--period", "this-month", "--type", "expense")["data"]
    assert rep["total"] == 15_000 + 13_000 + 50_000 + 2_500
    assert run("report", "--period", "2026-08", "--type", "expense")["data"]["total"] == 0
    assert run("report", "--period", "last:3", "--type", "expense")["data"]["period"]["start"] == "2026-08-01"
    r = run("undo")
    assert r["data"]["undone"] and run("balance", "--account", "bri")["data"]["balance"] == 197_500
