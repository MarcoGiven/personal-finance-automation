
import argparse
import hashlib
import os
from datetime import date
from decimal import Decimal
from calendar import month_name

from dotenv import load_dotenv

from app.database import get_connection, get_transactions
from app.sheets import (
    get_sheets_service,
    EXPENSE_START_ROW,
    EXPENSE_END_ROW,
    VALID_CATEGORIES,
)

load_dotenv()

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")

# Column AA stores our sync identifier.
SYNC_COLUMN = "AA"

# Income uses A:B; expenses continue to use C:E.
INCOME_START_ROW = 17
INCOME_END_ROW = 100

# Separate tracking column so income and expenses
# can occupy the same spreadsheet row.
INCOME_SYNC_COLUMN = "AB"


def transaction_key(transaction):
    """Create a stable identifier for a bank transaction."""
    identity = "|".join([
        transaction["source"],
        transaction["account_id"],
        transaction["external_id"],
    ])

    return hashlib.sha256(identity.encode()).hexdigest()


def mark_synced(transaction_id):
    """Update the transaction's SQLite status."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET status = 'synced' "
            "WHERE id = ?",
            (transaction_id,),
        )


def get_month(transaction):
    """Return the destination month, only for 2026."""
    transaction_date = date.fromisoformat(transaction["date"])

    if transaction_date.year != 2026:
        raise ValueError(
            f"Unsupported budget year: {transaction_date.year}"
        )

    return month_name[transaction_date.month]



def read_sheet_rows(service, month, transaction_type="expense"):
    """Read a budget input table and its sync identifiers."""

    if transaction_type == "income":
        start_row = INCOME_START_ROW
        end_row = INCOME_END_ROW
        input_columns = "A:B"
        sync_column = INCOME_SYNC_COLUMN

    elif transaction_type == "expense":
        start_row = EXPENSE_START_ROW
        end_row = EXPENSE_END_ROW
        input_columns = "C:E"
        sync_column = SYNC_COLUMN

    else:
        raise ValueError("Unsupported transaction type")

    start_col, end_col = input_columns.split(":")

    result = service.spreadsheets().values().batchGet(
        spreadsheetId=SPREADSHEET_ID,
        ranges=[
            f"'{month}'!{start_col}{start_row}:"
            f"{end_col}{end_row}",
            f"'{month}'!{sync_column}{start_row}:"
            f"{sync_column}{end_row}",
        ],
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()

    ranges = result["valueRanges"]

    input_rows = ranges[0].get("values", [])
    key_rows = ranges[1].get("values", [])

    rows = []

    for index in range(end_row - start_row + 1):
        values = (
            input_rows[index]
            if index < len(input_rows)
            else []
        )

        key = (
            key_rows[index][0]
            if index < len(key_rows) and key_rows[index]
            else ""
        )

        rows.append({
            "row": start_row + index,
            "values": values,
            "key": str(key).strip(),
        })

    return rows





def sync_transaction(service, transaction, write=False):
    """Synchronize one approved transaction to Google Sheets."""
    with get_connection() as conn:
        conflict = conn.execute(
            """
            SELECT id
            FROM sync_conflicts
            WHERE transaction_id = ?
            AND resolved = 0
            LIMIT 1
            """,
            (transaction["id"],),
        ).fetchone()

    if conflict:
        raise RuntimeError(
            f"Transaction {transaction['id']} has an "
            "unresolved Plaid conflict."
        )

    transaction_type = transaction["transaction_type"]

    if transaction_type not in ("expense", "income"):
        return "skipped_type"

    if transaction_type == "expense":
        if transaction["category"] not in VALID_CATEGORIES:
            return "skipped_category"

    if transaction["amount_cents"] == 0:
        raise ValueError("Cannot sync a zero-value transaction")

    month = get_month(transaction)
    key = transaction_key(transaction)

    rows = read_sheet_rows(service, month, transaction_type)

    # Plaid outflows are positive, inflows negative.
    # Google Sheets stores income as a positive amount.
    if transaction_type == "income":
        if transaction["amount_cents"] >= 0:
            raise ValueError(
                "Income must have a negative Plaid amount"
            )

        amount_cents = -transaction["amount_cents"]
        start_col, end_col = "A", "B"
        sync_column = INCOME_SYNC_COLUMN

        values_to_write = [
            transaction["description"],
            amount_cents / 100,
        ]

    else:
        amount_cents = transaction["amount_cents"]
        start_col, end_col = "C", "E"
        sync_column = SYNC_COLUMN

        values_to_write = [
            transaction["description"],
            amount_cents / 100,
            transaction["category"],
        ]

    expected_amount = Decimal(amount_cents) / 100

    # Check the tracking column first.
    existing = next(
        (row for row in rows if row["key"] == key),
        None,
    )

    if existing:
        values = existing["values"]

        valid = (
            len(values) == len(values_to_write)
            and str(values[0]) == transaction["description"]
            and Decimal(str(values[1])) == expected_amount
        )

        if transaction_type == "expense":
            valid = (
                valid
                and str(values[2]) == transaction["category"]
            )

        if not valid:
            raise RuntimeError(
                f"Tracked transaction changed in "
                f"{month}, row {existing['row']}"
            )

        if write:
            mark_synced(transaction["id"])

        print(
            f"Already exists: {transaction['description']} "
            f"({month}, row {existing['row']})"
        )
        return "already_exists"

    # Find a completely unused row.
    empty = next(
        (
            row for row in rows
            if not row["key"]
            and not any(
                str(value).strip()
                for value in row["values"]
            )
        ),
        None,
    )

    if empty is None:
        raise RuntimeError(
            f"No available {transaction_type} rows in {month}"
        )

    row_number = empty["row"]

    print(
        f"{'[WRITE]' if write else '[PREVIEW]'} "
        f"{month}, row {row_number}: "
        f"{transaction['description']} "
        f"${expected_amount:.2f} "
        f"({transaction_type})"
    )

    if not write:
        return "preview"

    input_range = (
        f"'{month}'!{start_col}{row_number}:"
        f"{end_col}{row_number}"
    )

    key_range = f"'{month}'!{sync_column}{row_number}"

    # Re-read the target row immediately before writing.
    fresh_rows = read_sheet_rows(
        service, month, transaction_type
    )
    target = next(
        row for row in fresh_rows
        if row["row"] == row_number
    )

    if target["key"] or any(
        str(v).strip() for v in target["values"]
    ):
        raise RuntimeError(
            "Destination was changed before writing"
        )

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {
                    "range": input_range,
                    "values": [values_to_write],
                },
                {
                    "range": key_range,
                    "values": [[key]],
                },
            ],
        },
    ).execute()

    # Verify the transaction before updating SQLite.
    updated_rows = read_sheet_rows(
        service, month, transaction_type
    )

    updated = next(
        row for row in updated_rows
        if row["row"] == row_number
    )

    actual = updated["values"]

    valid = (
        updated["key"] == key
        and len(actual) == len(values_to_write)
        and str(actual[0]) == transaction["description"]
        and Decimal(str(actual[1])) == expected_amount
    )

    if transaction_type == "expense":
        valid = (
            valid
            and str(actual[2]) == transaction["category"]
        )

    if not valid:
        raise RuntimeError(
            "Spreadsheet verification failed. "
            "Database status unchanged."
        )

    mark_synced(transaction["id"])
    return "synced"



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--month",
        required=True,
        choices=list(month_name)[1:],
        help="Budget month to synchronize",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write to Google Sheets (default: preview)",
    )

    args = parser.parse_args()

    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SPREADSHEET_ID is missing")

    service = get_sheets_service()
    transactions = get_transactions(status="ready")

    selected = [
        transaction for transaction in transactions
        if get_month(transaction) == args.month
    ]

    print(f"Spreadsheet: {SPREADSHEET_ID}")
    print(f"Month: {args.month}")
    print(f"Ready transactions: {len(selected)}")

    if not args.write:
        print("DRY RUN — no spreadsheet changes")

    for transaction in selected:
        sync_transaction(
            service,
            transaction,
            write=args.write,
        )

    print("Sync finished.")


if __name__ == "__main__":
    main()
