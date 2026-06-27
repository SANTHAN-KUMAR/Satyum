"""Shared test builders — genuine and tampered statements for discrimination tests.

A *genuine* statement reconciles every invariant; a *tampered* one has exactly one edited figure.
These are real structured statements, NOT hand-tuned-until-the-test-passes fixtures.
"""

from __future__ import annotations

import copy
from decimal import Decimal

from forensics.arithmetic import StatementData, Transaction


def genuine_statement() -> StatementData:
    """Opening 10,000; +5,000; -2,000; +1,000 -> closing 14,000. Every invariant reconciles."""
    txns = [
        Transaction(index=0, credit=Decimal("5000"), balance=Decimal("15000"),
                    balance_bbox=(100, 200, 80, 20)),
        Transaction(index=1, debit=Decimal("2000"), balance=Decimal("13000"),
                    balance_bbox=(100, 220, 80, 20)),
        Transaction(index=2, credit=Decimal("1000"), balance=Decimal("14000"),
                    balance_bbox=(100, 240, 80, 20)),
    ]
    return StatementData(
        opening_balance=Decimal("10000"),
        closing_balance=Decimal("14000"),
        transactions=txns,
        stated_total_debits=Decimal("2000"),
        stated_total_credits=Decimal("6000"),
    )


def tampered_balance_statement() -> StatementData:
    """Genuine statement with ONE balance figure inflated (15,000 -> 16,000)."""
    stmt = copy.deepcopy(genuine_statement())
    stmt.transactions[0].balance = Decimal("16000")  # the edit
    return stmt


def tampered_credit_statement() -> StatementData:
    """Genuine statement with ONE credit amount inflated (5,000 -> 8,000), balance left untouched."""
    stmt = copy.deepcopy(genuine_statement())
    stmt.transactions[0].credit = Decimal("8000")  # the edit
    return stmt
