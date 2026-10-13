
from plaid.model.sandbox_public_token_create_request import (
    SandboxPublicTokenCreateRequest,
)
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.products import Products

from app.plaid_client import get_plaid_client


def create_sandbox_account():
    client = get_plaid_client()

    # Create a simulated account with Transactions enabled.
    request = SandboxPublicTokenCreateRequest(
        institution_id="ins_109508",
        initial_products=[Products("transactions")],
    )

    response = client.sandbox_public_token_create(request)

    # Exchange the temporary public token for an access token.
    exchange_request = ItemPublicTokenExchangeRequest(
        public_token=response.public_token
    )

    exchange_response = client.item_public_token_exchange(
        exchange_request
    )

    return exchange_response.access_token
