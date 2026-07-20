"""
Stores/retrieves Plaid access tokens in AWS Secrets Manager, rather than
directly in the database (see the design note in app/models/account.py).
The database only ever stores the secret's name/ARN (Account.plaid_access_token_ref).

Requires AWS credentials to be available (locally: `aws configure`/SSO,
same as your other AWS projects; in ECS: the task's IAM role).
"""
import json
import boto3


def store_plaid_access_token(item_id: str, access_token: str) -> str:
    """Creates a new secret, returns its name (what we store in our DB)."""
    client = boto3.client("secretsmanager")
    secret_name = f"copilot-clone/plaid-access-token/{item_id}"
    client.create_secret(
        Name=secret_name,
        SecretString=json.dumps({"access_token": access_token}),
    )
    return secret_name


def get_plaid_access_token(secret_ref: str) -> str:
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_ref)
    return json.loads(response["SecretString"])["access_token"]
