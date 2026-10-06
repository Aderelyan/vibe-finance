"""Setiap modul punya register(sub) yang menambahkan subparser beserta handler-nya."""
from . import (accounts, analysis, batch, budget, categories, context, debt, queries, recurring, savings, setup,
               transactions)

MODULES = [setup, accounts, categories, transactions, queries, budget, savings, debt, recurring, analysis,
           context, batch]


def register_all(sub):
    for module in MODULES:
        module.register(sub)
