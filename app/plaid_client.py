
import os

import plaid
from dotenv import load_dotenv
from plaid.api import plaid_api

load_dotenv()


def get_plaid_client():
    environment = os.getenv("PLAID_ENV", "sandbox")

    hosts = {
        "sandbox": plaid.Environment.Sandbox,
        "production": plaid.Environment.Production,
    }

    if environment not in hosts:
        raise ValueError("Invalid PLAID_ENV")

    configuration = plaid.Configuration(
        host=hosts[environment],
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
            "plaidVersion": "2020-09-14",
        },
    )

    return plaid_api.PlaidApi(plaid.ApiClient(configuration))
