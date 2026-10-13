
from types import SimpleNamespace

from app.classifier import classify_transaction


def fake_transaction(name, amount, primary="", detailed=""):
    return SimpleNamespace(
        name=name,
        merchant_name=name,
        amount=amount,
        personal_finance_category=SimpleNamespace(
            primary=primary,
            detailed=detailed,
        ),
    )


def fake_account(account_type, subtype):
    return SimpleNamespace(
        type=account_type,
        subtype=subtype,
    )


def test_credit_card_purchase():
    txn = fake_transaction("Steam Purchase", 25.00)
    account = fake_account("credit", "credit card")

    result = classify_transaction(txn, account)

    assert result == ("expense", "Entertainment", 25.00)


def test_credit_card_payment():
    txn = fake_transaction(
        "AUTOPAY PAYMENT",
        -200.00,
        detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT",
    )
    account = fake_account("credit", "credit card")

    assert classify_transaction(txn, account) == (
        "transfer", None, -200.00
    )


def test_savings_deposit():
    txn = fake_transaction("ACH TRANSFER", -500.00)
    account = fake_account("depository", "savings")

    assert classify_transaction(txn, account) == (
        "transfer", None, -500.00
    )


def test_savings_interest():
    txn = fake_transaction(
        "INTEREST PAYMENT",
        -3.42,
        detailed="INCOME_INTEREST_EARNED",
    )
    account = fake_account("depository", "savings")

    assert classify_transaction(txn, account) == (
        "income", None, -3.42
    )


def test_credit_card_refund():
    txn = fake_transaction("STORE REFUND", -20.00)
    account = fake_account("credit", "credit card")

    assert classify_transaction(txn, account) == (
        "expense", None, -20.00
    )


def test_checking_paycheck():
    txn = fake_transaction(
        "PAYROLL DIRECT DEPOSIT",
        -1200.00,
        primary="INCOME",
    )
    account = fake_account("depository", "checking")

    assert classify_transaction(txn, account) == (
        "income", None, -1200.00
    )
