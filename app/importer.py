
import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.database import (
    initialize_database,
    insert_transaction,
    get_transactions,
)
from app.categorizer import categorize_transaction


VALID_TYPES = {"expense", "income", "transfer"}


def process_transaction(raw):
    """Normalize one imported financial transaction."""

    required = [
        "source",
        "account_id",
        "external_id",
        "date",
        "description",
        "amount",
        "type",
    ]

    for field in required:
        if not str(raw.get(field, "")).strip():
            raise ValueError(f"Missing required field: {field}")

    transaction_date = date.fromisoformat(raw["date"])
    amount = Decimal(str(raw["amount"]))

    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be positive and finite")

    amount_cents = int(
        (amount * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )

    description = raw["description"].strip()
    transaction_type = raw["type"].strip().lower()

    if transaction_type not in VALID_TYPES:
        raise ValueError(f"Unknown transaction type: {transaction_type}")

    category = None

    if transaction_type == "expense":
        category, inferred_type = categorize_transaction(
            description
        )

        if inferred_type == "transfer":
            transaction_type = "transfer"
            category = None

    # Only recognizable expenses are automatically ready.
    # Income and transfers require review during this milestone.
    status = (
        "ready"
        if transaction_type == "expense" and category
        else "pending"
    )

    return {
        "source": raw["source"].strip(),
        "account_id": raw["account_id"].strip(),
        "external_id": raw["external_id"].strip(),
        "date": transaction_date.isoformat(),
        "description": description,
        "amount_cents": amount_cents,
        "category": category,
        "transaction_type": transaction_type,
        "status": status,
    }


def import_csv(file_path, commit=False):
    initialize_database()

    with open(file_path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        if not set([
            "source", "account_id", "external_id",
            "date", "description", "amount", "type"
        ]).issubset(reader.fieldnames or []):
            raise ValueError("CSV is missing required columns")

        transactions = [
            process_transaction(row) for row in reader
        ]

    print(f"Read {len(transactions)} transactions.")

    if not commit:
        for transaction in transactions:
            print(
                transaction["date"],
                transaction["description"],
                f'${transaction["amount_cents"] / 100:.2f}',
                transaction["category"] or "REVIEW",
                transaction["transaction_type"],
            )

        print("\nDry run. Use --commit to save to SQLite.")
        return

    imported = 0

    for transaction in transactions:
        if insert_transaction(transaction):
            imported += 1

    print(f"New transactions: {imported}")
    print(f"Duplicates skipped: {len(transactions) - imported}")

    pending = get_transactions(status="pending")
    print(f"Transactions awaiting review: {len(pending)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Standardized CSV file")
    parser.add_argument("--commit", action="store_true")

    args = parser.parse_args()
    import_csv(args.file, commit=args.commit)
