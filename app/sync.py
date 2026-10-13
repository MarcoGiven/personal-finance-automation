
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


def read_sheet_rows(service, month):
    """Read the expense table and sync identifiers."""

    result = service.spreadsheets().values().batchGet(
        spreadsheetId=SPREADSHEET_ID,
        ranges=[
            f"'{month}'!C{EXPENSE_START_ROW}:E{EXPENSE_END_ROW}",
            f"'{month}'!{SYNC_COLUMN}{EXPENSE_START_ROW}:"
            f"{SYNC_COLUMN}{EXPENSE_END_ROW}",
        ],
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()

    ranges = result.get("valueRanges", [])

    if len(ranges) != 2:
        raise RuntimeError("Could not read spreadsheet ranges")

    expense_rows = ranges[0].get("values", [])
    key_rows = ranges[1].get("values", [])

    rows = []

    count = EXPENSE_END_ROW - EXPENSE_START_ROW + 1

    for index in range(count):
        expense = (
            expense_rows[index]
            if index < len(expense_rows) else []
        )

        key = (
            key_rows[index][0]
            if index < len(key_rows) and key_rows[index]
            else ""
        )

        rows.append({
            "row": EXPENSE_START_ROW + index,
            "values": expense,
            "key": str(key).strip(),
        })

    return rows


def sync_transaction(service, transaction, write=False):
    """Safely prepare or write one expense."""

    if transaction["transaction_type"] != "expense":
        return "skipped_type"

    if transaction["category"] not in VALID_CATEGORIES:
        return "skipped_category"

    month = get_month(transaction)
    key = transaction_key(transaction)
    rows = read_sheet_rows(service, month)

    # Check whether this transaction already exists.
    existing = next(
        (row for row in rows if row["key"] == key),
        None,
    )

    if existing:
        expected_amount = (
            Decimal(transaction["amount_cents"]) / 100
        )
        values = existing["values"]

        valid = (
            len(values) >= 3
            and str(values[0]) == transaction["description"]
            and Decimal(str(values[1])) == expected_amount
            and str(values[2]) == transaction["category"]
        )

        if not valid:
            raise RuntimeError(
                f"Tracked transaction was modified in {month}, "
                f"row {existing['row']}. Review manually."
            )

        if write:
            mark_synced(transaction["id"])

        print(
            f"Already exists: {transaction['description']} "
            f"({month}, row {existing['row']})"
        )
        return "already_exists"

    # Never overwrite existing user-entered data.
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
        raise RuntimeError(f"No empty expense rows in {month}")

    row_number = empty["row"]
    amount = transaction["amount_cents"] / 100

    print(
        f"{'[WRITE]' if write else '[PREVIEW]'} "
        f"{month} row {row_number}: "
        f"{transaction['description']} "
        f"${amount:.2f} "
        f"({transaction['category']})"
    )

    if not write:
        return "preview"

    # Write the purchase and its tracking ID together.
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {
                    "range": f"'{month}'!C{row_number}:E{row_number}",
                    "values": [[
                        transaction["description"],
                        amount,
                        transaction["category"],
                    ]],
                },
                {
                    "range": (
                        f"'{month}'!{SYNC_COLUMN}{row_number}"
                    ),
                    "values": [[key]],
                },
            ],
        },
    ).execute()

    # Verify that the write is actually present.
    updated_rows = read_sheet_rows(service, month)
    updated = next(
        row for row in updated_rows
        if row["row"] == row_number
    )

    if updated["key"] != key:
        raise RuntimeError(
            "Sync verification failed. Database status unchanged."
        )

    values = updated["values"]
    if not (
        len(values) >= 3
        and str(values[0]) == transaction["description"]
        and Decimal(str(values[1])) == Decimal(amount).quantize(
            Decimal("0.01")
        )
        and str(values[2]) == transaction["category"]
    ):
        raise RuntimeError(
            "Expense verification failed. Database status unchanged."
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
