#!/usr/bin/env bash
# Run the live GigBid demo from this Mac and give it a free public HTTPS URL (Cloudflare quick
# tunnel; no account, no card). The whole stack runs in ONE container (infra/hf/Dockerfile).
#   ./scripts/deploy/live_local.sh          start (or restart) and print the public URL
#   ./scripts/deploy/live_local.sh stop     stop the container and the tunnel
# Keep the Mac on and awake; the URL changes whenever the tunnel is restarted.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p .cache/deploy
stop_tunnel() { [ -f .cache/deploy/tunnel.pid ] && kill "$(cat .cache/deploy/tunnel.pid)" 2>/dev/null || true; }
if [ "${1:-}" = "stop" ]; then
  docker rm -f gigbid-live >/dev/null 2>&1 || true
  stop_tunnel
  pkill -f "caffeinate -dims" 2>/dev/null || true
  echo "stopped"; exit 0
fi
docker info >/dev/null 2>&1 || { orb start >/dev/null 2>&1 || open -a OrbStack; sleep 10; }
command -v cloudflared >/dev/null || brew install cloudflared

# Only the keys the app needs go into the container (read from .env; nothing is printed).
uv run python - <<'PY'
from dotenv import dotenv_values
from scripts.deploy.hf_space import SECRETS
e = dotenv_values(".env")
open(".cache/deploy/live.env", "w").write("".join(f"{k}={e[k]}\n" for k in SECRETS if e.get(k)))
PY
chmod 600 .cache/deploy/live.env

# 1) public tunnel first, so the app knows its own URL (retried: Cloudflare's API can time out)
URL=""
for attempt in 1 2; do
  stop_tunnel
  nohup cloudflared tunnel --no-autoupdate --url http://localhost:7860 > .cache/deploy/tunnel.log 2>&1 &
  echo $! > .cache/deploy/tunnel.pid
  for _ in $(seq 1 30); do
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" .cache/deploy/tunnel.log | grep -v "^https://api\." | head -1 || true)
    [ -n "$URL" ] && break
    grep -q "failed to request quick Tunnel" .cache/deploy/tunnel.log && break
    sleep 2
  done
  [ -n "$URL" ] && break
  echo "tunnel attempt $attempt failed, retrying..."; sleep 5
done
if [ -z "$URL" ]; then
  # Fallback: localhost.run (free, no account; plain SSH reverse tunnel)
  echo "Cloudflare quick tunnels unavailable; using localhost.run instead..."
  stop_tunnel
  nohup ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -R 80:localhost:7860 nokey@localhost.run > .cache/deploy/tunnel.log 2>&1 &
  echo $! > .cache/deploy/tunnel.pid
  for _ in $(seq 1 30); do
    URL=$(grep -oE "https://[a-z0-9.-]+\.lhr\.life" .cache/deploy/tunnel.log | head -1 || true)
    [ -n "$URL" ] && break; sleep 2
  done
fi
[ -n "$URL" ] || { echo "no tunnel could start; see .cache/deploy/tunnel.log"; exit 1; }
HOST=${URL#https://}

# 2) the app (image is built once, then reused)
docker image inspect gigbid-space >/dev/null 2>&1 || docker build -f infra/hf/Dockerfile -t gigbid-space .
docker rm -f gigbid-live >/dev/null 2>&1 || true
docker run -d --name gigbid-live --restart unless-stopped --env-file .cache/deploy/live.env \
  -e MODEL_PROFILE=open -e SPACE_HOST="$HOST" -p 127.0.0.1:7860:7860 gigbid-space >/dev/null
echo "starting GigBid (first start builds the portfolio index, about 1-3 minutes)..."
for _ in $(seq 1 200); do docker logs gigbid-live 2>&1 | grep -q "services up" && break; sleep 3; done
docker logs gigbid-live 2>&1 | grep -A5 "services up" || true

# 3) keep the Mac awake while the demo is live
pkill -f "caffeinate -dims" 2>/dev/null || true
nohup caffeinate -dims >/dev/null 2>&1 &
echo "$URL" > .cache/deploy/url.txt
echo
echo "LIVE: $URL"
echo "Sign in with REVIEWER_EMAIL / REVIEWER_PASSWORD from your .env."
