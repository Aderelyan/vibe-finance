"""Opsi dan helper yang dipakai beberapa perintah."""
from datetime import date

from ..parse import parse_period


def add_period_args(parser):
    parser.add_argument("--period", help="today, yesterday, this-week, last-week, this-month, last-month, "
                                         "YYYY-MM, last:N, all (bawaan: this-month)")
    parser.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="YYYY-MM-DD")


def period_from_args(conn, args):
    row = conn.execute("SELECT MIN(ts) FROM transactions WHERE deleted_at IS NULL").fetchone()
    earliest = date.fromisoformat(row[0][:10]) if row[0] else None
    return parse_period(args.period, args.date_from, args.date_to, earliest=earliest)
