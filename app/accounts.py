from app.plaid_client import get_plaid_client
from app.token_store import load_connections
from app.plaid_sync import get_item_accounts


def get_account_names():
    client = get_plaid_client()
    connections = load_connections()

    account_names = {}

    for connection in connections.values():
        accounts = get_item_accounts(
            client,
            connection["access_token"],
        )

        for account_id, account in accounts.items():
            account_names[account_id] = (
                account.official_name
                or account.name
                or "Unknown Account"
            )

    return account_names