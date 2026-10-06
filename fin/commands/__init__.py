"""Setiap modul punya register(sub) yang menambahkan subparser beserta handler-nya."""
from . import accounts, budget, categories, queries, savings, setup, transactions

MODULES = [setup, accounts, categories, transactions, queries, budget, savings]


def register_all(sub):
    for module in MODULES:
        module.register(sub)
