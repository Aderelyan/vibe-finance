"""Setiap modul punya register(sub) yang menambahkan subparser beserta handler-nya."""
from . import accounts, categories, queries, setup, transactions

MODULES = [setup, accounts, categories, transactions, queries]


def register_all(sub):
    for module in MODULES:
        module.register(sub)
