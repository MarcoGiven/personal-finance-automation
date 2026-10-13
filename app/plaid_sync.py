
import argparse
import json
from decimal import Decimal, ROUND_HALF_UP

from plaid.exceptions import ApiException
from plaid.model.transactions_sync_request import (
    TransactionsSyncRequest,
)

from app.plaid_client import get_plaid_client
from app.token_store import load_connections, save_cursor
from app.database import initialize_database, get_connection
from app.categorizer import categorize_transaction
from plaid.model.accounts_get_request import AccountsGetRequest
from app.classifier import classify_transaction


def to_cents(amount):
    return int(
        (Decimal(str(amount)) * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def get_item_accounts(client, access_token):
    """Get the accounts belonging to a Plaid connection."""

    request = AccountsGetRequest(
        access_token=access_token
    )

    response = client.accounts_get(request)

    return {
        account.account_id: account
        for account in response.accounts
    }



def normalize_transaction(transaction, accounts):
    """Convert and classify a Plaid transaction."""

    account = accounts.get(transaction.account_id)

    if account is None:
        raise ValueError(
            f"Unknown account: {transaction.account_id}"
        )

    description = (
        transaction.merchant_name
        or transaction.name
        or "Unknown transaction"
    )

    transaction_type, category, signed_amount = (
        classify_transaction(transaction, account)
    )

    return {
        "source": "plaid",
        "account_id": transaction.account_id,
        "external_id": transaction.transaction_id,
        "date": str(transaction.date),
        "description": description,
        "amount_cents": to_cents(signed_amount),
        "category": category,
        "transaction_type": transaction_type,
        "status": "pending",
    }


def collect_changes(client, access_token, starting_cursor):
    """Retrieve all pages of transaction updates."""

    for attempt in range(3):
        cursor = starting_cursor
        added = []
        modified = []
        removed = []

        try:
            while True:
                request = TransactionsSyncRequest(
                    access_token=access_token,
                    cursor=cursor,
                    count=500,
                )

                response = client.transactions_sync(request)

                added.extend(response.added)
                modified.extend(response.modified)
                removed.extend(response.removed)

                cursor = response.next_cursor

                if not response.has_more:
                    return added, modified, removed, cursor

        except ApiException as error:
            try:
                code = json.loads(error.body).get("error_code")
            except (ValueError, TypeError):
                code = None

            if (
                code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
                and attempt < 2
            ):
                print("Pagination changed. Restarting sync...")
                continue

            raise


def apply_changes(added, modified, removed, accounts):
    """Update SQLite using Plaid's transaction changes."""

    with get_connection() as conn:
        for transaction in added + modified:

            # Wait for pending transactions to post.
            if transaction.pending:
                continue

            normalized = normalize_transaction(transaction, accounts)

            existing = conn.execute(
                """
                SELECT id, status
                FROM transactions
                WHERE source = 'plaid'
                  AND account_id = ?
                  AND external_id = ?
                """,
                (
                    normalized["account_id"],
                    normalized["external_id"],
                ),
            ).fetchone()

            if existing:
                if existing["status"] == "synced":
                    raise RuntimeError(
                        "A transaction already exported to Sheets "
                        "has changed. Manual reconciliation required."
                    )

                conn.execute(
                    """
                    UPDATE transactions
                    SET date = ?,
                        description = ?,
                        amount_cents = ?,
                        category = ?,
                        transaction_type = ?,
                        status = 'pending'
                    WHERE id = ?
                    """,
                    (
                        normalized["date"],
                        normalized["description"],
                        normalized["amount_cents"],
                        normalized["category"],
                        normalized["transaction_type"],
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO transactions (
                        source, account_id, external_id,
                        date, description, amount_cents,
                        category, transaction_type, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized["source"],
                        normalized["account_id"],
                        normalized["external_id"],
                        normalized["date"],
                        normalized["description"],
                        normalized["amount_cents"],
                        normalized["category"],
                        normalized["transaction_type"],
                        normalized["status"],
                    ),
                )

        for removal in removed:
            existing = conn.execute(
                """
                SELECT id, status
                FROM transactions
                WHERE source = 'plaid'
                  AND external_id = ?
                """,
                (removal.transaction_id,),
            ).fetchone()

            if not existing:
                continue

            if existing["status"] == "synced":
                raise RuntimeError(
                    "Previously exported transaction was removed. "
                    "Manual reconciliation required."
                )

            conn.execute(
                "DELETE FROM transactions WHERE id = ?",
                (existing["id"],),
            )


def sync_item(client, item_id, connection, write=False):
    """Fetch and optionally import updates for one Plaid Item."""

    starting_cursor = connection.get("cursor", "")

    accounts = get_item_accounts(
        client,
        connection["access_token"]
    )

    added, modified, removed, new_cursor = collect_changes(
        client,
        connection["access_token"],
        starting_cursor,
    )

    print(f"\nConnection: {item_id}")
    print(f"Added: {len(added)}")
    print(f"Modified: {len(modified)}")
    print(f"Removed: {len(removed)}")

    if not write:
        print("Preview only — SQLite unchanged.")
        return

    # Save transactions before advancing the cursor.
    apply_changes(added, modified, removed, accounts)
    save_cursor(item_id, new_cursor)

    print("Transactions imported and cursor saved.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Import transaction changes into SQLite",
    )
    args = parser.parse_args()

    initialize_database()

    connections = load_connections()

    if not connections:
        print("No saved Plaid connections.")
        return

    client = get_plaid_client()

    print(f"Saved connections: {len(connections)}")

    for item_id, connection in connections.items():
        sync_item(
            client,
            item_id,
            connection,
            write=args.write,
        )


if __name__ == "__main__":
    main()
