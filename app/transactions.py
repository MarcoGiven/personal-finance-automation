
from plaid.model.transactions_sync_request import (
    TransactionsSyncRequest,
)

from app.plaid_client import get_plaid_client


def fetch_transactions(access_token):
    client = get_plaid_client()

    transactions = []
    cursor = ""

    while True:
        request = TransactionsSyncRequest(
            access_token=access_token,
            cursor=cursor,
        )

        response = client.transactions_sync(request)

        transactions.extend(response.added)
        cursor = response.next_cursor

        if not response.has_more:
            break

    return [
        {
            "id": transaction.transaction_id,
            "date": str(transaction.date),
            "name": transaction.name,
            "amount": transaction.amount,
            "account_id": transaction.account_id,
            "pending": transaction.pending,
        }
        for transaction in transactions
    ]
