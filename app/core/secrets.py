"""
Stores/retrieves Plaid access tokens in AWS SSM Parameter Store, rather
than directly in the database (see the design note in app/models/account.py).
The database only ever stores the parameter's name (Account.plaid_access_token_ref).

Parameter Store over Secrets Manager: a standard SecureString parameter
is free (no per-secret monthly charge like Secrets Manager), and matches
the convention already used by the sibling plaid-sheets-sync Lambda
project (/plaid-sheets-sync/store) -- see infra/ARCHITECTURE.md for the
full cost/tradeoff writeup. The one capability given up is Secrets
Manager's automatic rotation, which this app doesn't use anyway (Plaid
access tokens aren't rotated on a schedule).

Requires AWS credentials to be available (locally: `aws configure`/SSO,
same as your other AWS projects; in ECS/EC2: the task/instance IAM role).
"""
import json
import boto3


def store_plaid_access_token(item_id: str, access_token: str) -> str:
    """Creates a new parameter, returns its name (what we store in our DB).
    Deliberately omits Overwrite=True -- fails loudly (ParameterAlreadyExists)
    on a duplicate item_id rather than silently clobbering an existing token,
    same behavior as Secrets Manager's create_secret had."""
    client = boto3.client("ssm")
    parameter_name = f"/money-tracking-app/plaid-access-token/{item_id}"
    client.put_parameter(
        Name=parameter_name,
        Value=json.dumps({"access_token": access_token}),
        Type="SecureString",
    )
    return parameter_name


def get_plaid_access_token(secret_ref: str) -> str:
    client = boto3.client("ssm")
    response = client.get_parameter(Name=secret_ref, WithDecryption=True)
    return json.loads(response["Parameter"]["Value"])["access_token"]
