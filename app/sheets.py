
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

# Configuration
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

# Existing spreadsheet structure
EXPENSE_START_ROW = 17
EXPENSE_END_ROW = 45

VALID_CATEGORIES = {
    "Food & Groceries",
    "Utilities",
    "Subscriptions",
    "Entertainment",
    "Shopping",
    "Savings",
}


def get_sheets_service():
    """Authenticate and return the Google Sheets service."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)

    return build("sheets", "v4", credentials=creds)


def get_next_expense_row(service, month):
    """Find the first completely empty expense row."""

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{month}'!C{EXPENSE_START_ROW}:E{EXPENSE_END_ROW}",
    ).execute()

    rows = result.get("values", [])

    for index in range(EXPENSE_END_ROW - EXPENSE_START_ROW + 1):
        row = rows[index] if index < len(rows) else []

        if not any(str(value).strip() for value in row):
            return EXPENSE_START_ROW + index

    raise ValueError(f"No empty expense rows in {month}.")


def add_expense(service, month, description, amount, category):
    """Write a transaction to the existing expense table."""

    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {category}")

    if amount <= 0:
        raise ValueError("Expense amount must be positive.")

    row = get_next_expense_row(service, month)
    cell_range = f"'{month}'!C{row}:E{row}"

    # Recheck the destination immediately before writing.
    existing = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=cell_range,
    ).execute().get("values", [])

    if existing and any(str(v).strip() for v in existing[0]):
        raise RuntimeError("Destination is no longer empty.")

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=cell_range,
        valueInputOption="USER_ENTERED",
        body={
            "values": [[description, amount, category]]
        },
    ).execute()

    print(f"Added {description} (${amount:.2f}) to {month}, row {row}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SPREADSHEET_ID is missing from .env")

    service = get_sheets_service()

    month = "October"
    description = "TEST TRANSACTION"
    amount = 1.00
    category = "Entertainment"

    row = get_next_expense_row(service, month)

    print(f"Connected to spreadsheet: {SPREADSHEET_ID}")
    print(f"Next empty expense row: {row}")
    print(f"Test: {description} / ${amount:.2f} / {category}")

    if args.write:
        add_expense(service, month, description, amount, category)
    else:
        print("Dry run only. Use --write to insert the test.")


if __name__ == "__main__":
    main()
