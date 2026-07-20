"""
Plaid API client setup -- same environment-variable pattern as the
existing plaid-sheets-sync Lambda project (PLAID_CLIENT_ID, PLAID_SECRET,
PLAID_ENV).
"""
import os
import plaid
from plaid.api import plaid_api

HOST_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def get_plaid_client() -> plaid_api.PlaidApi:
    configuration = plaid.Configuration(
        host=HOST_MAP[os.environ["PLAID_ENV"]],
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))
