
import os

import plaid
from dotenv import load_dotenv
from plaid.api import plaid_api

load_dotenv()


def get_plaid_client():
    if os.getenv("PLAID_ENV", "sandbox") != "sandbox":
        raise ValueError("Only Sandbox is supported for now.")

    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
        },
    )

    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)
