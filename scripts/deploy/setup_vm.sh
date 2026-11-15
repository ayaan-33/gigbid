#!/usr/bin/env bash
# One-shot setup for a fresh Ubuntu 22.04/24.04 VM (Oracle Cloud Always Free, ARM or x86).
# Usage on the VM:  bash setup_vm.sh <git-repo-url>
set -euo pipefail
REPO=${1:?usage: setup_vm.sh <git repo url>}
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi
# Oracle images ship iptables rules that block 80/443 even when the security list allows them
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || true
sudo sh -c 'command -v netfilter-persistent >/dev/null && netfilter-persistent save || true'
[ -d gigbid ] || git clone "$REPO" gigbid
cd gigbid
[ -f .env ] || cp .env.example .env
IP=$(curl -s https://api.ipify.org)
echo
echo "Public IP: $IP  ->  suggested DOMAIN=${IP//./-}.sslip.io"
echo "Next: edit gigbid/.env (keys + DOMAIN + APP_ENV=production), then run:"
echo "  sudo docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --env-file .env up -d --build"
