# Deploy GigBid on Oracle Cloud (Always Free)

Everything here is free: an Oracle **Always Free** VM, free **sslip.io** DNS, free **Let's Encrypt**
HTTPS (automatic through Caddy) and the free **Groq** tier for open models. About 45 minutes.

> The "Always Free" ARM shape (VM.Standard.A1.Flex) does not charge as long as you stay within the
> free limits below. Oracle asks for a card at sign-up for identity verification. If that's a
> problem, see **Alternative hosts** at the end.

## 1. Create the VM (about 15 minutes)

1. Sign up at https://signup.cloud.oracle.com and choose a **Home Region** near you. It can't be
   changed later, and free ARM capacity varies by region.
2. In the console, open **☰ Menu → Compute → Instances → Create instance**.
3. **Name:** `gigbid`.
4. **Image and shape → Edit:**
   - **Image:** Canonical **Ubuntu 24.04** (or 22.04).
   - **Shape:** **Ampere → VM.Standard.A1.Flex**, with **4 OCPUs and 24 GB memory**. That's the
     whole Always Free allowance, so it costs nothing.
   - If you get "Out of capacity", try another availability domain, or 2 OCPU / 12 GB (still
     enough).
5. **Networking:** keep "Create new virtual cloud network" and **Assign a public IPv4 address**.
6. **Add SSH keys:** choose **Generate a key pair for me** and click **Save private key**. You'll
   get a `ssh-key-*.key` file; keep it safe.
7. **Boot volume:** the default 47 GB is fine. Up to 200 GB is free.
8. Click **Create** and wait for the state to show **Running**. Copy the **Public IP address**.

## 2. Open ports 80 and 443 (about 5 minutes)

1. On the instance page, click the **Subnet** link, then the **Default Security List**.
2. Click **Add Ingress Rules** twice:
   - Source CIDR `0.0.0.0/0`, protocol TCP, destination port **80**.
   - Source CIDR `0.0.0.0/0`, protocol TCP, destination port **443**.
3. Port 22 (SSH) is already open by default.

## 3. Connect and install (about 10 minutes)

On your Mac, replace `<IP>` with your public IP and the key path with your downloaded key.
Run each block one at a time:

```bash
chmod 600 ~/Downloads/ssh-key-*.key
```
```bash
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<IP>
```

Now you're on the VM. The repo must be reachable from the VM: either make it public, or use a
read-only deploy key. The simplest way is to make the GitHub repo public before this step, which
the assignment requires at submission anyway.

```bash
curl -fsSL https://raw.githubusercontent.com/<your-github-user>/gigbid/main/scripts/deploy/setup_vm.sh -o setup_vm.sh && bash setup_vm.sh https://github.com/<your-github-user>/gigbid.git
```

The script installs Docker, opens the VM's own firewall for 80/443, clones the repo and prints a
suggested `DOMAIN`, such as `129-146-10-20.sslip.io`.

## 4. Configure secrets on the VM (about 5 minutes)

```bash
cd ~/gigbid && nano .env
```

Fill in the same values as your local `.env`: Groq, Langfuse, GitHub token, and the generated
secrets. Then set:
- `DOMAIN=<the value the script printed>`
- `APP_ENV=production`
- `PUBLIC_WEB_URL=https://<DOMAIN>`
- `UPWORK_OAUTH_REDIRECT_URI=https://<DOMAIN>/api/auth/upwork/callback`
- `REVIEWER_PASSWORD=<a new strong password>`. You'll give this to the grader **privately** in
  the Google Classroom comment.

Save with Ctrl+O, Enter, then Ctrl+X.

## 5. Start everything (about 10 minutes for the first build)

```bash
sudo docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --env-file .env up -d --build
```

Check it:
```bash
sudo docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml ps
```

Open `https://<DOMAIN>` and sign in with `REVIEWER_EMAIL` and `REVIEWER_PASSWORD`. Caddy gets the
HTTPS certificate automatically within about 1 minute of the first visit.

## 6. Keep it live until grades are released
- **Restarts:** every service has `restart: unless-stopped`, so it survives VM reboots.
- **Updating after a new commit:**
  ```bash
  cd ~/gigbid && git pull && sudo docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --env-file .env up -d --build
  ```
- **Logs:**
  ```bash
  sudo docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml logs -f api worker
  ```
- **Backup** of the database:
  ```bash
  sudo docker compose -f infra/docker-compose.yml exec -T postgres pg_dump -U gigbid gigbid | gzip > backup.sql.gz
  ```

## Alternative hosts (if Oracle isn't possible)
The same compose file runs on any Docker host with at least 4 GB of RAM.

Free options to check, since limits change:
- a **GitHub Codespaces** port forward, for short demos only;
- **Google Cloud e2-micro** (Always Free, 1 GB RAM: too small for the full stack);
- the **local laptop with a Cloudflare Tunnel** (`cloudflared tunnel --url http://localhost:3000`).
  This gives a free public URL while your Mac is on.

Any of these is fine for the demo video. The graded live link has to stay up until grades are
released, so the Oracle VM is the recommended choice.
