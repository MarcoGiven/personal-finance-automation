
import argparse
from app.database import get_connection, initialize_database
from app.categorizer import categorize_transaction


def reclassify(month, write=False):
    initialize_database()

    with get_connection() as conn:
        transactions = conn.execute(
            """
            SELECT * FROM transactions
            WHERE date LIKE ?
              AND status = 'pending'
              AND manual_override = 0
              AND transaction_type = 'expense'
            ORDER BY date, id
            """,
            (f"{month}-%",),
        ).fetchall()

        changes = []

        for transaction in transactions:
            category, inferred_type = categorize_transaction(
                transaction["description"]
            )

            # This task only revises expense categories.
            # Don't change transaction types or classify transfers.
            if inferred_type != "expense":
                continue

            if transaction["category"] != category:
                changes.append((
                    transaction["id"],
                    transaction["description"],
                    transaction["category"],
                    category,
                ))

        for txn_id, description, old, new in changes:
            print(
                f"{txn_id}: {description}: "
                f"{old or 'Uncategorized'} -> "
                f"{new or 'Uncategorized'}"
            )

            if write:
                conn.execute(
                    "UPDATE transactions SET category = ? WHERE id = ?",
                    (new, txn_id),
                )

        if not write:
            conn.rollback()

    print(f"\n{len(changes)} category changes found.")
    print("Changes saved." if write else "Dry run only.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="2026-10")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    reclassify(args.month, args.write)
