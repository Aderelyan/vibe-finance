"""batch: validasi sama dengan CLI, semua atau tidak sama sekali, satu group, satu undo. Juga context."""
import io
import json
import os
import subprocess
import sys

from conftest import DEFAULT_NOW, ROOT


def write_batch(tmp_path, entries, name="b.json"):
    path = tmp_path / name
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return str(path)


def bud(fin, name):
    return next(b["balance"] for b in fin.ok("budget", "list")["data"]["budgets"] if b["name"] == name)


def test_batch_runs_all_in_one_group(wallets, tmp_path):
    fin = wallets
    fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5")
    path = write_batch(tmp_path, [
        {"cmd": "add", "args": {"type": "income", "account": "bri", "item": ["gajian|1jt|gaji"]}},
        {"cmd": "budget alloc", "args": {"item": ["makan|300k", "tabungan|100k"]}},
        {"cmd": "add", "args": {"type": "expense", "item": "ayam goreng|15k|makan", "raw": "ayam goreng 15k"}},
        {"cmd": "transfer", "args": {"from": "bri", "to": "tunai", "amount": 200000, "fee": "2.5k"}},
        {"cmd": "debt add", "args": {"direction": "i_owe", "person": "Budi", "amount": "30k",
                                     "paid_for": "bakso|makan"}},
        {"cmd": "debt pay", "args": {"person": "Budi", "amount": "10k"}},
        {"cmd": "budget move", "args": {"from": "makan", "to": "jajan", "amount": "50k"}},
        {"cmd": "recurring pay", "args": {"name": "kos", "account": "bri"}},
        {"cmd": "adjust", "args": {"account": "gopay", "actual": "0"}},
    ])
    before = fin.ok("balance")["data"]
    n = fin.count_tx()
    r = fin.ok("batch", "--file", path)
    d = r["data"]
    assert d["count"] == 9 and d["group_id"]
    assert {res["data"]["group_id"] for res in d["results"] if "group_id" in res["data"]} == {d["group_id"]}
    assert r["message"].startswith("9 perintah dari batch tercatat sekaligus")
    assert bud(fin, "makan") == 300_000 - 15_000 - 30_000 - 50_000
    assert bud(fin, "jajan") == 50_000
    assert fin.balance("bri") == 500_000 + 1_000_000 - 200_000 - 2_500 - 500_000
    assert fin.balance("gopay") == 0
    assert fin.ok("debt", "list")["data"]["debts"][0]["remaining"] == 20_000
    assert fin.ok("recurring", "list")["data"]["recurring"][0]["this_month"]["paid"] is True
    assert d["results"][2]["data"]["items"][0]["note"] == "ayam goreng"

    r = fin.ok("undo")
    assert r["data"]["action"] == "batch" and r["data"]["removed"][0]["table"] == "debts"
    assert fin.count_tx() == n
    after = fin.ok("balance")["data"]
    saldo = lambda data: {b["name"]: b["balance"] for b in data["budgets"] if b["balance"]}  # noqa: E731
    assert after["total_dompet"] == before["total_dompet"] and saldo(after) == saldo(before)
    assert [a["balance"] for a in after["accounts"]] == [a["balance"] for a in before["accounts"]]
    assert after["debt_total"] == 0
    assert fin.ok("recurring", "list")["data"]["recurring"][0]["this_month"]["paid"] is False
    assert fin.ok("debt", "list")["data"]["count"] == 0
    # undo berikutnya membatalkan pencatatan sebelum batch, bukan sisa batch
    assert fin.ok("undo")["data"]["action"] != "batch"


def test_batch_all_or_nothing(wallets, tmp_path):
    fin = wallets
    n, before = fin.count_tx(), fin.ok("balance")["data"]
    path = write_batch(tmp_path, [
        {"cmd": "add", "args": {"type": "expense", "item": "kopi|8k"}},
        {"cmd": "budget alloc", "args": {"item": "makan|50k"}},
        {"cmd": "add", "args": {"type": "expense", "account": "bca", "item": "nasi|15k"}},
    ])
    r = fin.err("UNKNOWN_ACCOUNT", "batch", "--file", path)
    assert r["error"]["message"].startswith("Perintah ke-3 (add): Dompet 'bca' tidak ada.")
    assert r["error"]["data"] == {"index": 3, "cmd": "add"} and "tunai" in r["error"]["hint"]
    assert fin.count_tx() == n and fin.ok("balance")["data"] == before

    # error yang muncul di dalam blok tulis (budget tidak dikenal, bayar berlebih) juga membatalkan semuanya
    path = write_batch(tmp_path, [
        {"cmd": "debt add", "args": {"direction": "i_owe", "person": "Budi", "amount": "30k"}},
        {"cmd": "debt pay", "args": {"person": "Budi", "amount": "40k"}},
    ])
    r = fin.err("OVERPAYMENT", "batch", "--file", path)
    assert r["error"]["data"]["remaining"] == 30_000 and r["error"]["data"]["index"] == 2
    assert fin.ok("debt", "list", "--status", "all", "--all")["data"]["count"] == 0
    assert fin.count_tx() == n


def test_batch_validation_same_as_cli(wallets, tmp_path):
    fin = wallets
    cases = [
        ([{"cmd": "account add", "args": {"name": "x", "type": "cash"}}], "BAD_ARGS", "tidak bisa dipakai di batch"),
        ([{"cmd": "undo"}], "BAD_ARGS", "tidak bisa dipakai di batch"),
        ([{"cmd": "add", "args": {"type": "boros", "item": "x|1k"}}], "BAD_ARGS", "Argumen tidak sah"),
        ([{"cmd": "add", "args": {"type": "expense", "itm": "x|1k"}}], "BAD_ARGS", "Argumen tidak sah"),
        ([{"cmd": "add", "args": {"type": "expense", "item": "x|nol"}}], "BAD_AMOUNT", "tidak bisa dibaca"),
        ([{"cmd": "add", "args": {"type": "expense", "item": "x|1k", "date": "2030-01-01"}}], "BAD_DATE", "masa depan"),
        ([{"cmd": "add", "args": {"type": "expense", "item": {"a": 1}}}], "BAD_ARGS", "harus teks"),
        ([{"cmd": "add", "args": {"type": "expense", "item": "x|1k", "help": True}}], "BAD_ARGS", "--help"),
        ([{"cmd": "recurring pay", "args": {}}], "BAD_ARGS", "wajib berisi: name"),
        ([{"command": "add"}], "BAD_ARGS", "\"cmd\""),
        ([{"cmd": "add", "args": ["--type", "expense"]}], "BAD_ARGS", "harus objek"),
        ([], "BAD_ARGS", "minimal satu"),
        ({"cmd": "add"}, "BAD_ARGS", "daftar"),
    ]
    n = fin.count_tx()
    for entries, code, text in cases:
        r = fin.err(code, "batch", "--file", write_batch(tmp_path, entries))
        assert text in r["error"]["message"], (entries, r)
    (tmp_path / "rusak.json").write_text('[{"cmd": "add",]', encoding="utf-8")
    r = fin.err("BAD_ARGS", "batch", "--file", str(tmp_path / "rusak.json"))
    assert "JSON tidak sah di baris 1" in r["error"]["message"]
    fin.err("BAD_ARGS", "batch", "--file", str(tmp_path / "tidak-ada.json"))
    fin.err("BAD_ARGS", "batch")
    fin.err("BAD_ARGS", "batch", "--file", "x.json", "--stdin")
    assert fin.count_tx() == n


def test_batch_values(wallets, tmp_path):
    fin = wallets
    path = write_batch(tmp_path, [
        {"cmd": "adjust", "args": {"account": "tunai", "actual": "-5k", "note": "koreksi"}},
        {"cmd": "debt add", "args": {"direction": "i_owe", "person": "Citra", "amount": 20000, "no_cash": True,
                                     "account": None, "date": False}},
        {"cmd": "add", "args": {"type": "expense", "item": ["a|1k", "b|2k"], "budget": "tabungan"}},
    ])
    r = fin.ok("batch", "--file", path)
    assert fin.balance("tunai") == -5_000 - 3_000
    assert r["data"]["results"][1]["data"]["debt"]["cash"] is False
    assert r["data"]["results"][2]["data"]["items"][0]["budget"] == "tabungan"


def test_batch_without_changes_has_no_group(wallets, tmp_path):
    fin = wallets
    path = write_batch(tmp_path, [{"cmd": "adjust", "args": {"account": "tunai", "actual": "150k"}}])
    r = fin.ok("batch", "--file", path)
    assert r["data"]["group_id"] is None and "tidak ada perubahan uang" in r["message"]
    assert fin.ok("undo")["data"]["action"] == "opening"  # saldo awal gopay dari fixture


def test_batch_stdin(wallets, monkeypatch):
    fin = wallets
    entries = [{"cmd": "add", "args": {"type": "expense", "item": "es teh ☕|3k"}}]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entries, ensure_ascii=False)))
    r = fin.ok("batch", "--stdin")
    assert r["data"]["source"] == "stdin" and "☕" in r["message"]


def test_batch_stdin_subprocess_utf8_bom(fin, tmp_path):
    fin.ok("account", "add", "tunai", "--type", "cash", "--opening", "100k")
    payload = "﻿" + json.dumps([{"cmd": "add", "args": {"type": "expense", "item": "kopi é|5k"}}],
                                    ensure_ascii=False)
    env = dict(os.environ, FINANCE_HOME=str(tmp_path), PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "finance.py"), "--now", DEFAULT_NOW, "batch", "--stdin"],
                          input=payload.encode("utf-8"), capture_output=True, env=env, cwd=str(ROOT))
    obj = json.loads(proc.stdout.decode("utf-8"))
    assert obj["ok"] and "kopi é" in obj["message"] and proc.returncode == 0


def test_context(wallets):
    fin = wallets
    fin.ok("alias", "add", "--kind", "account", "--alias", "cash", "--target", "tunai")
    fin.ok("budget", "alloc", "--item", "makan|100k", "--item", "tabungan|50k")
    fin.ok("debt", "add", "--direction", "i_owe", "--person", "Budi", "--amount", "20k")
    fin.ok("recurring", "add", "kos", "--amount", "500k", "--day", "5")
    fin.ok("category", "remove", "hiburan", "--kind", "expense")
    r = fin.ok("context")
    d = r["data"]
    assert d["today"] == "2026-10-06" and d["weekday"] == "Selasa" and d["now"] == DEFAULT_NOW
    assert d["accounts"][0] == {"name": "tunai", "type": "cash", "balance": 170_000, "is_default": True}
    assert d["default_account"] == "tunai"
    assert "hiburan" not in d["categories"]["expense"] and "gaji" in d["categories"]["income"]
    assert {"name": "makan", "kind": "category", "balance": 100_000} in d["budgets"]
    assert d["savings"] == [{"name": "tabungan", "balance": 50_000, "target_amount": 2_000_000, "target_date": None}]
    assert d["aliases"] == [{"kind": "account", "alias": "cash", "target": "tunai"}]
    assert "kopi" in d["keywords"]["expense"]["jajan"] and "hiburan" not in d["keywords"]["expense"]
    assert d["open_debts"][0]["person"] == "Budi" and d["recurring"][0]["name"] == "kos"
    assert "Hari ini Selasa, 6 Oktober 2026." in r["message"] and "cash = tunai" in r["message"]


def test_context_empty(fin):
    d = fin.ok("context")["data"]
    assert d["accounts"] == [] and d["default_account"] is None
    assert d["budgets"] == [{"name": "belum teralokasi", "kind": "unallocated", "balance": 0}]
