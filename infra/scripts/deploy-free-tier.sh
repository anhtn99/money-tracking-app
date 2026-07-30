#!/usr/bin/env bash
# Deploy for the free-tier environment -- run by hand from your own
# machine, or by .github/workflows/deploy-free-tier.yml in CI. Requires
# AWS credentials (local profile, or the CI role assumed via OIDC) with
# permission to push to ECR and call ssm:SendCommand/GetCommandInvocation
# on the free-tier instance.
set -euo pipefail

AWS_REGION="us-east-2"
AWS_ACCOUNT_ID="884135111378"
ECR_REPO="money-tracking-app"
ECR_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest"

cd "$(git rev-parse --show-toplevel)"

echo "==> Building and pushing image to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
# --platform linux/amd64 -- the EC2 instance is x86_64 (t3.micro), but a
# build machine with Apple Silicon defaults to arm64 -- without this the
# pushed image would fail to run on the instance at all ("exec format
# error"). Harmless/no-op on an x86_64 build machine (including GitHub's
# own ubuntu-latest runners, which are already x86_64).
docker build --platform linux/amd64 -t "$ECR_IMAGE" .
docker push "$ECR_IMAGE"

# CI sets INSTANCE_ID directly (a GitHub Actions repo Variable) so the
# deploy role never needs Terraform state read access just to look this
# up. Local runs have no INSTANCE_ID set, so this falls back to asking
# Terraform, same as before.
INSTANCE_ID="${INSTANCE_ID:-$(terraform -chdir=infra/terraform/environments/free-tier output -raw instance_id)}"

echo "==> Fetching app config from SSM and deploying on $INSTANCE_ID"
# Everything after `echo "Deploying..."` runs ON the instance via SSM Run
# Command -- no SSH involved anywhere in this script. get-parameters-by-path
# pulls all three config parameters in one call, decrypted, and writes
# them into a .env file docker compose reads automatically.
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters commands="[
    \"cd /opt/money-tracking-app\",
    \"echo Deploying $ECR_IMAGE...\",
    \"aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com\",
    \"aws ssm get-parameter --name /money-tracking-app/free-tier/database-url --with-decryption --query Parameter.Value --output text > /tmp/database_url\",
    \"aws ssm get-parameter --name /money-tracking-app/free-tier/plaid-client-id --with-decryption --query Parameter.Value --output text > /tmp/plaid_client_id\",
    \"aws ssm get-parameter --name /money-tracking-app/free-tier/plaid-secret --with-decryption --query Parameter.Value --output text > /tmp/plaid_secret\",
    \"echo ECR_IMAGE=$ECR_IMAGE > .env\",
    \"echo DATABASE_URL=\$(cat /tmp/database_url) >> .env\",
    \"echo PLAID_CLIENT_ID=\$(cat /tmp/plaid_client_id) >> .env\",
    \"echo PLAID_SECRET=\$(cat /tmp/plaid_secret) >> .env\",
    \"echo PLAID_ENV=production >> .env\",
    \"echo APP_DOMAIN=app.anhnguyen-expenses.com >> .env\",
    \"rm -f /tmp/database_url /tmp/plaid_client_id /tmp/plaid_secret\",
    \"docker compose pull\",
    \"docker compose up -d\",
    \"sleep 5\",
    \"docker compose exec -T app alembic upgrade head\",
    \"rm -f .env\"
  ]" \
  --query "Command.CommandId" --output text)

echo "==> Waiting for deploy command to finish (command: $COMMAND_ID)"
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" || true

STATUS=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query "Status" --output text)
echo "==> Deploy command status: $STATUS"
if [ "$STATUS" != "Success" ]; then
  echo "==> Deploy failed -- full output:"
  aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
  exit 1
fi

echo "==> Deployed. Checking /health..."
curl -sf "https://app.anhnguyen-expenses.com/health" && echo "==> OK"
