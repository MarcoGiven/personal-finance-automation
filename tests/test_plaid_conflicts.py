
import json
from types import SimpleNamespace

import pytest

from app import database
from app.plaid_sync import apply_changes


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Create an isolated SQLite database for every test."""
    monkeypatch.setattr(
        database, "DB_PATH", tmp_path / "test_finance.db"
    )
    database.initialize_database()
    return database.get_connection


def make_transaction(
    amount=20.0,
    date="2026-10-13",
    name="Chipotle",
    account_id="account_1",
    transaction_id="txn_1",
):
    return SimpleNamespace(
        account_id=account_id,
        transaction_id=transaction_id,
        date=date,
        amount=amount,
        name=name,
        merchant_name=name,
        pending=False,
        personal_finance_category=None,
    )


def make_account():
    return SimpleNamespace(
        type="credit",
        subtype="credit card",
    )


ACCOUNTS = {"account_1": make_account()}


def seed_transaction(
    get_connection,
    status="pending",
    manual_override=0,
    amount_cents=2000,
    category="Food & Groceries",
    transaction_type="expense",
):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO transactions (
                source, account_id, external_id,
                date, description, amount_cents,
                category, transaction_type, status,
                manual_override
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "plaid", "account_1", "txn_1",
                "2026-10-13", "Chipotle",
                amount_cents, category,
                transaction_type, status, manual_override,
            ),
        )


def get_record(get_connection):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE external_id = 'txn_1'"
        ).fetchone()
        return dict(row) if row else None


def get_conflicts(get_connection):
    with get_connection() as conn:
        return [
            dict(row) for row in conn.execute(
                "SELECT * FROM sync_conflicts"
            ).fetchall()
        ]


def test_unreviewed_transaction_updates(test_db):
    seed_transaction(test_db)

    updated = make_transaction(amount=25.0)

    apply_changes([], [updated], [], ACCOUNTS)

    record = get_record(test_db)

    assert record["amount_cents"] == 2500
    assert record["status"] == "pending"
    assert get_conflicts(test_db) == []


def test_manual_category_is_preserved(test_db):
    seed_transaction(
        test_db,
        manual_override=1,
        category="Entertainment",
    )

    updated = make_transaction(
        name="Chipotle Mexican Grill"
    )

    apply_changes([], [updated], [], ACCOUNTS)

    record = get_record(test_db)

    assert record["category"] == "Entertainment"
    assert record["description"] == "Chipotle"
    assert record["manual_override"] == 1


def test_approved_amount_change_creates_conflict(test_db):
    seed_transaction(
        test_db,
        status="ready",
        manual_override=1,
    )

    updated = make_transaction(amount=25.0)

    apply_changes([], [updated], [], ACCOUNTS)

    record = get_record(test_db)
    conflicts = get_conflicts(test_db)

    assert record["amount_cents"] == 2000
    assert record["status"] == "ready"
    assert len(conflicts) == 1
    assert conflicts[0]["change_type"] == "modified"

    new_data = json.loads(conflicts[0]["new_data"])
    assert new_data["amount_cents"] == 2500


def test_excluded_removal_creates_conflict(test_db):
    seed_transaction(
        test_db,
        status="excluded",
        manual_override=1,
        transaction_type="transfer",
    )

    removed = SimpleNamespace(
        transaction_id="txn_1",
        account_id="account_1",
    )

    apply_changes([], [], [removed], ACCOUNTS)

    assert get_record(test_db)["status"] == "excluded"
    assert len(get_conflicts(test_db)) == 1
    assert get_conflicts(test_db)[0]["change_type"] == "removed"


def test_unreviewed_removal_deletes_transaction(test_db):
    seed_transaction(test_db)

    removed = SimpleNamespace(
        transaction_id="txn_1",
        account_id="account_1",
    )

    apply_changes([], [], [removed], ACCOUNTS)

    assert get_record(test_db) is None
    assert get_conflicts(test_db) == []


def test_repeated_change_does_not_duplicate_conflict(test_db):
    seed_transaction(
        test_db, status="ready", manual_override=1
    )

    updated = make_transaction(amount=25.0)

    apply_changes([], [updated], [], ACCOUNTS)
    apply_changes([], [updated], [], ACCOUNTS)

    assert len(get_conflicts(test_db)) == 1
