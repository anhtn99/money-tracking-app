#!/bin/bash
# Runs once at first boot (Amazon Linux 2023's cloud-init). Installs
# Docker + the Compose v2 plugin (AL2023's docker package doesn't bundle
# it) and lays down the two small config files the app needs to run --
# actual deploys (pulling a new image, restarting) happen later via
# infra/scripts/deploy-free-tier.sh over SSM Run Command, not here.
set -euxo pipefail

dnf update -y
dnf install -y docker
systemctl enable --now docker

# Explicit, not assumed -- the standard AL2023 AMI ships this
# pre-installed and running, but the (very similarly named) "minimal"
# variant doesn't, and this instance has no SSH access at all. If the
# AMI selection ever regresses again, this is the one thing standing
# between "still reachable" and "no remote access path whatsoever" --
# install/enable it explicitly rather than trust the AMI to have it.
dnf install -y amazon-ssm-agent
systemctl enable --now amazon-ssm-agent

mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

usermod -aG docker ec2-user

mkdir -p /opt/money-tracking-app
cat > /opt/money-tracking-app/docker-compose.yml <<'COMPOSE_EOF'
${docker_compose_content}
COMPOSE_EOF

cat > /opt/money-tracking-app/Caddyfile <<'CADDY_EOF'
${caddyfile_content}
CADDY_EOF
