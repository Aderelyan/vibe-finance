"""Setiap modul punya register(sub) yang menambahkan subparser beserta handler-nya."""
from . import accounts, budget, categories, debt, queries, recurring, savings, setup, transactions

MODULES = [setup, accounts, categories, transactions, queries, budget, savings, debt, recurring]


def register_all(sub):
    for module in MODULES:
        module.register(sub)
