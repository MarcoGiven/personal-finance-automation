
from datetime import date

from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

from app.plaid_client import get_plaid_client
from app.token_store import load_connections
from app.plaid_sync import get_item_accounts


START_DATE = date(2026, 10, 8)
END_DATE = date(2026, 10, 14)


def main():
    client = get_plaid_client()
    connections = load_connections()

    if not connections:
        print("No saved Plaid connections.")
        return

    # Identify the bank without printing access tokens or Item IDs.
    available = []

    for connection in connections.values():
        accounts = get_item_accounts(
            client,
            connection["access_token"],
        )

        names = [
            account.name or "Unnamed account"
            for account in accounts.values()
        ]

        available.append((connection, accounts, names))

    print("\nConnected accounts:")
    for index, (_, _, names) in enumerate(available, 1):
        print(f"{index}. {', '.join(names)}")

    choice = int(input("\nSelect Bank of America number: "))
    if not 1 <= choice <= len(available):
        raise ValueError("Invalid selection")

    connection, accounts, _ = available[choice - 1]
    access_token = connection["access_token"]

    transactions = []
    offset = 0

    while True:
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=START_DATE,
            end_date=END_DATE,
            options=TransactionsGetRequestOptions(
                count=100,
                offset=offset,
            ),
        )

        response = client.transactions_get(request)

        transactions.extend(response.transactions)
        offset += len(response.transactions)

        if offset >= response.total_transactions:
            break

        if not response.transactions:
            raise RuntimeError("Pagination returned no transactions")

    transactions.sort(
        key=lambda transaction: str(transaction.date),
        reverse=True,
    )

    print(f"\nPlaid transactions from {START_DATE} to {END_DATE}:")
    print(f"Total: {len(transactions)}\n")

    for transaction in transactions:
        account = accounts.get(transaction.account_id)
        account_name = account.name if account else "Unknown"

        status = "PENDING" if transaction.pending else "POSTED"
        name = transaction.merchant_name or transaction.name

        print(
            f"{transaction.date} | "
            f"{status:7} | "
            f"${transaction.amount:8.2f} | "
            f"{name} | {account_name}"
        )


if __name__ == "__main__":
    main()
