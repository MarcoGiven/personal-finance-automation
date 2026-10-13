
from fastapi import FastAPI, HTTPException
from plaid.model.country_code import CountryCode
from plaid.model.institutions_get_request import InstitutionsGetRequest
from plaid.model.products import Products
from plaid.exceptions import ApiException

from app.plaid_client import get_plaid_client
from app.sandbox import create_sandbox_account
from app.transactions import fetch_transactions

app = FastAPI(title="Personal Finance Automation")


@app.get("/")
def home():
    return {"message": "Personal Finance API is running"}


@app.get("/test-plaid")
def test_plaid():
    client = get_plaid_client()

    request = InstitutionsGetRequest(
        count=5,
        offset=0,
        country_codes=[CountryCode("US")],
        options={
            "products": [Products("transactions")]
        },
    )

    try:
        response = client.institutions_get(request)

        return {
            "status": "connected",
            "institutions": [
                institution.name
                for institution in response.institutions
            ],
        }
    except ApiException:
        raise HTTPException(
            status_code=502,
            detail="Plaid request failed. Check Sandbox credentials and logs.",
        )

@app.post("/sandbox/test-transactions")
def test_sandbox_transactions():
    access_token = create_sandbox_account()
    transactions = fetch_transactions(access_token)

    return {
        "status": "success",
        "transaction_count": len(transactions),
        "transactions": transactions[:20],
    }

