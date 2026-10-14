
import argparse
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from plaid.exceptions import ApiException
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.transactions_sync_request import (
    TransactionsSyncRequest,
)

from app.plaid_client import get_plaid_client
from app.token_store import load_connections, save_cursor
from app.database import initialize_database, get_connection
from app.categorizer import categorize_transaction
from plaid.model.accounts_get_request import AccountsGetRequest
from app.classifier import classify_transaction
from app.database import get_connection
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



def fetch_processing_snapshot(client, access_token):
    """Read all still-pending authorizations from Plaid over the last 90 days.

    Separate from the saved /transactions/sync cursor: previously skipped
    pending records can be recovered without rewinding that cursor.
    """
    end = date.today()
    start = end - timedelta(days=90)
    pending = []
    offset = 0
    while True:
        response = client.transactions_get(TransactionsGetRequest(
            access_token=access_token,
            start_date=start,
            end_date=end,
            options=TransactionsGetRequestOptions(count=100, offset=offset),
        ))
        pending.extend(t for t in response.transactions if t.pending)
        count = len(response.transactions)
        offset += count
        if offset >= response.total_transactions:
            break
        if not count:
            raise RuntimeError("Plaid transaction pagination stopped early")
    return pending


def save_processing_snapshot(accounts, pending, posted):
    """Atomically replace pending records for one Item's accounts."""
    # A pending authorization may be replaced by a posted transaction with
    # a DIFFERENT ID. Never show both when Plaid provides the link.
    superseded_ids = {
        t.pending_transaction_id
        for t in posted
        if not t.pending and getattr(t, "pending_transaction_id", None)
    }
    account_ids = tuple(accounts.keys())
    with get_connection() as conn:
        for account_id in account_ids:
            conn.execute(
                "DELETE FROM processing_transactions WHERE account_id = ?",
                (account_id,),
            )
        for transaction in pending:
            if transaction.account_id not in accounts:
                continue
            if transaction.transaction_id in superseded_ids:
                continue
            normalized = normalize_transaction(transaction, accounts)
            # No processing entry for a transaction already stored as posted.
            present = conn.execute(
                """SELECT 1 FROM transactions
                   WHERE source = 'plaid' AND account_id = ? AND external_id = ?""",
                (transaction.account_id, transaction.transaction_id),
            ).fetchone()
            if present:
                continue
            conn.execute(
                """INSERT INTO processing_transactions
                   (account_id, external_id, date, description,
                    amount_cents, transaction_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (normalized["account_id"], normalized["external_id"],
                 normalized["date"], normalized["description"],
                 normalized["amount_cents"], normalized["transaction_type"]),
            )
    return len(pending)


def apply_changes(added, modified, removed, accounts):
    """Apply Plaid changes without overwriting reviewed transactions."""

    def record_conflict(conn, existing, change_type, new_data):
        """Record unresolved bank changes for later review."""

        new_json = json.dumps(new_data, sort_keys=True)

        duplicate = conn.execute(
            """
            SELECT id
            FROM sync_conflicts
            WHERE account_id = ?
              AND external_id = ?
              AND change_type = ?
              AND new_data = ?
              AND resolved = 0
            LIMIT 1
            """,
            (
                existing["account_id"],
                existing["external_id"],
                change_type,
                new_json,
            ),
        ).fetchone()

        if duplicate:
            return

        conn.execute(
            """
            INSERT INTO sync_conflicts (
                transaction_id,
                account_id,
                external_id,
                change_type,
                old_data,
                new_data
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                existing["id"],
                existing["account_id"],
                existing["external_id"],
                change_type,
                json.dumps(dict(existing), sort_keys=True),
                new_json,
            ),
        )

        print(
            f"REVIEW REQUIRED: {change_type} — "
            f"{existing['description']}"
        )

    with get_connection() as conn:
        for transaction in added + modified:

            # Don't import temporary pending authorizations.
            if transaction.pending:
                continue

            normalized = normalize_transaction(
                transaction, accounts
            )

            existing = conn.execute(
                """
                SELECT *
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

            if existing is None:
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
                        "pending",
                    ),
                )
                continue

            amount_changed = (
                existing["amount_cents"]
                != normalized["amount_cents"]
            )
            date_changed = (
                existing["date"] != normalized["date"]
            )

            protected = (
                existing["manual_override"] == 1
                or existing["status"] in (
                    "ready", "synced", "excluded"
                )
            )

            if protected:
                if amount_changed or date_changed:
                    record_conflict(
                        conn,
                        existing,
                        "modified",
                        normalized,
                    )

                # Preserve manual categories, transaction
                # types, descriptions, and statuses.
                continue

            # Unreviewed transactions may be updated.
            conn.execute(
                """
                UPDATE transactions
                SET date = ?,
                    description = ?,
                    amount_cents = ?,
                    category = ?,
                    transaction_type = ?
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

        for removal in removed:
            account_id = getattr(removal, "account_id", None)

            if not account_id:
                raise RuntimeError(
                    "Removed transaction has no account ID."
                )

            existing = conn.execute(
                """
                SELECT *
                FROM transactions
                WHERE source = 'plaid'
                  AND account_id = ?
                  AND external_id = ?
                """,
                (account_id, removal.transaction_id),
            ).fetchone()

            if existing is None:
                continue

            protected = (
                existing["manual_override"] == 1
                or existing["status"] in (
                    "ready", "synced", "excluded"
                )
            )

            if protected:
                record_conflict(
                    conn,
                    existing,
                    "removed",
                    {"transaction_id": removal.transaction_id},
                )
                continue

            # Only delete transactions never manually reviewed.
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

    print("\nProcessing Plaid connection")
    print(f"Added: {len(added)}")
    print(f"Modified: {len(modified)}")
    print(f"Removed: {len(removed)}")

    if not write:
        print("Preview only — SQLite unchanged.")
        return

    # Fetch staging data independently of the incremental cursor.
    # If Plaid fails, leave the cursor and processing snapshot untouched.
    processing = fetch_processing_snapshot(client, connection["access_token"])

    # Commit posted changes before advancing the cursor.
    apply_changes(added, modified, removed, accounts)
    count = save_processing_snapshot(accounts, processing, added + modified)
    save_cursor(item_id, new_cursor)

    print(f"Processing transactions observed: {count}")
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
