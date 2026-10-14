
from fastapi import APIRouter
from pydantic import BaseModel

from plaid.model.link_token_create_request import (
    LinkTokenCreateRequest,
)
from plaid.model.link_token_create_request_user import (
    LinkTokenCreateRequestUser,
)
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.country_code import CountryCode
from plaid.model.products import Products

from app.plaid_client import get_plaid_client
from app.token_store import save_connection, list_connection_ids

router = APIRouter(prefix="/plaid", tags=["Plaid"])


class TokenExchangeRequest(BaseModel):
    public_token: str


@router.post("/link-token")
def create_link_token():
    client = get_plaid_client()

    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        client_name="Personal Finance Automation",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(
            client_user_id="personal-finance-local-user"
        ),
    )

    response = client.link_token_create(request)

    return {"link_token": response.link_token}


@router.post("/exchange")
def exchange_public_token(body: TokenExchangeRequest):
    client = get_plaid_client()

    request = ItemPublicTokenExchangeRequest(
        public_token=body.public_token
    )

    response = client.item_public_token_exchange(request)

    # Store the token before reporting success.
    save_connection(
        item_id=response.item_id,
        access_token=response.access_token,
    )

    # Never return the access token to the browser.
    return {
        "status": "connected",
        "item_id": response.item_id,
    }


@router.get("/connections")
def get_connections():
    return {"count": len(list_connection_ids())}
