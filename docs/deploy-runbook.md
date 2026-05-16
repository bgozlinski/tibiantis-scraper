# Tibiantis Monitor — Deploy runbook

This runbook walks operator through first deploy of Tibiantis Monitor
on Hetzner VM. Estimated time: ~1h end-to-end for someone with SSH + Docker
familiarity. Updated after each milestone change.

## §1 Prerequisites

Before starting:
- [ ] Hetzner Cloud account (https://console.hetzner.cloud) z payment method
- [ ] Local SSH key pair: `~/.ssh/id_ed25519` (existing) or `ssh-keygen -t ed25519 -C "tibiantis-deploy"`
- [ ] Discord bot token (Developer Portal, M7 setup) — paste later na VM
- [ ] (Optional) Docker Hub account dla pull rate limit bypass z `docker login`

Estimated cost: **~6€/mc** (Hetzner CX22 + free Docker Hub public + free GHA public)

## §2 Provision VM

1. Cloud Console → Projects → "Add Project" → `tibiantis-monitor`
2. Sidebar → "Security" → "SSH Keys" → Add → paste `~/.ssh/id_ed25519.pub`
3. Sidebar → "Servers" → "Add Server"
   - Location: **Falkenstein DE-FSN** (~30ms z PL)
   - Image: **Ubuntu 24.04**
   - Type: **CX22** (~6€/mc, 2 vCPU shared, 4GB RAM, 40GB SSD)
   - Networking: Public IPv4 + IPv6 (default)
   - SSH Keys: select your uploaded key
   - Firewall: leave empty for now (Firewall added next step)
   - Cloud Config: none
   - Volumes: none
   - Backups: disabled
   - Labels: `env=prod`, `project=tibiantis`
   - Create & start server, **capture public IPv4 address**.
4. Sidebar → "Firewalls" → "Create Firewall" → `tibiantis-firewall`
   - Inbound rules:
     - Allow TCP 22 from `<your-IPv4>/32` (check via `curl ipify.org`)
     - Allow ICMP from `0.0.0.0/0` (ping/traceroute debug)
   - Outbound rules: allow all (default)
   - Apply to: server created step 3

## §3 First SSH + bootstrap

1. From laptop:
   ```bash
   scp docs/scripts/bootstrap.sh root@<hetzner-ip>:/tmp/
   ```
2. SSH as root:
   ```bash
   ssh root@<hetzner-ip>
   # Confirm SSH key auth works (no password prompt)
   ```
3. Run bootstrap (~3-5 min on CX22; prints `[1/8]`..`[8/8]` step markers):
   ```bash
   bash /tmp/bootstrap.sh
   # Check output ends with "Bootstrap complete. SSH as deploy@<ip>..."
   ```
   The script replaces the snap-installed Docker (pre-shipped on Hetzner Ubuntu 24.04
   minimal — strict confinement + auto-refresh are production hazards) with docker-ce
   via the official `get.docker.com` script, then asserts UFW + deploy + docker
   state before declaring success.
4. Verify hardening (from laptop, new terminal):
   ```bash
   ssh deploy@<hetzner-ip>           # should work
   ssh -o PreferredAuthentications=password root@<hetzner-ip>   # "Permission denied"
   ```
5. On VM as deploy:
   ```bash
   docker ps                          # empty list, no errors (Docker accessible via group membership)
   sudo ufw status verbose            # 22/tcp ALLOW, default deny incoming
   ```

## §4 First deploy

### 4.1 Prepare deploy directory

```bash
ssh deploy@<hetzner-ip>
sudo mkdir -p /opt/tibiantis
sudo chown deploy:deploy /opt/tibiantis
cd /opt/tibiantis
```

### 4.2 Download compose + env template

```bash
curl -fsSL https://raw.githubusercontent.com/bgozlinski/tibiantis-scraper/master/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/bgozlinski/tibiantis-scraper/master/.env.example -o .env.example
cp .env.example .env
chmod 600 .env
```

### 4.3 Fill secrets

Generate `DJANGO_SECRET_KEY` (alphanumeric only — Compose v2 `$VAR` interpolation gotcha):

```bash
python3 -c "import string, secrets; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50)))"
```

Edit `.env`:
- `DJANGO_SECRET_KEY=<generated 50-char alphanumeric>`
- `POSTGRES_PASSWORD=<32-char alphanumeric>` (regenerate with the snippet above — alphanumeric avoids both compose `$VAR` interpolation AND URL-encoding inside `DATABASE_URL`)
- **`DATABASE_URL=postgres://tibiantis:<same-as-POSTGRES_PASSWORD>@postgres:5432/tibiantis`** — the password appears twice; both must match exactly, or migrate exits 1 with `password authentication failed for user "tibiantis"`. Tech debt: should be DRY-constructed in `config/settings/prod.py` from individual `POSTGRES_*` vars (follow-up issue).
- `DISCORD_BOT_TOKEN=<real token from Discord Developer Portal>`
- `DJANGO_ALLOWED_HOSTS=<hetzner-ipv4>,localhost,web` — `web` is required so Uptime Kuma's internal-DNS monitor (`http://web:8000/health/`) doesn't get rejected by Django with `DisallowedHost`.

### 4.4 Pull + up

```bash
docker compose pull
docker compose up -d
```

Wait ~90 seconds for full stack health (postgres + redis + mongo first, then `migrate` one-shot completes, then web/celery_worker/celery_beat/discord_bot/uptime-kuma).

### 4.5 Verify deploy

```bash
docker compose ps
# Expected: 8 long-running services Up (postgres, redis, mongo, web, celery_worker,
# celery_beat, discord_bot, uptime-kuma). migrate hidden by default (Exited 0).

docker compose ps -a
# Shows migrate Exited (0).

docker compose logs migrate
# Expected: "Apply all migrations" + "Running migrations" + exit 0

docker compose exec web curl -fsS http://localhost:8000/health/
# Expected: HTTP 200 + {"db":"ok","redis":"ok"}
```

## §5 Smoke verification

From laptop, SSH tunnel with 2 forwarded ports:

```bash
ssh -L 8000:localhost:8000 -L 3001:localhost:3001 deploy@<hetzner-ip>
```

In another terminal on laptop:

```bash
curl -fsS http://localhost:8000/health/   # 200 + JSON
```

In browser: http://localhost:3001 → Uptime Kuma setup wizard.

### 5.1 Kuma initial setup

- Create admin account (save credentials in password manager).
- Add 4 monitors:
  1. **web /health/** — Type HTTP(s), URL `http://web:8000/health/`, interval 60s, expect 200
  2. **postgres** — Type TCP Port, Hostname `postgres`, Port `5432`, interval 60s
  3. **redis** — Type TCP Port, Hostname `redis`, Port `6379`, interval 60s
  4. **mongo** — Type TCP Port, Hostname `mongo`, Port `27017`, interval 60s
- Wait 2 min → all four monitors green on dashboard.

> Kuma resolves service names via the Docker default network (`tibiantis_default`) because it shares the network with the other compose services. Using `http://localhost:8000/health/` inside Kuma would resolve to Kuma itself — see Pułapka B.

## §6 Discord bot live test

- In dev guild: `/bedmage add yhral`
- Bot responds with an ephemeral success message (per M7-D33 contract).
- Verify the DB row was actually created:

  ```bash
  docker compose exec web python manage.py shell -c \
    "from apps.bedmages.models import BedmageWatch; \
     print(BedmageWatch.objects.filter(character__name='yhral').exists())"
  # → True
  ```

## §7 Rolling update

After CI pushes to master (new `:master` tag in Docker Hub):

```bash
ssh deploy@<hetzner-ip>
cd /opt/tibiantis
docker compose pull
docker compose up -d
```

Compose recreates containers with the new image. Healthchecks settle within ~30s. Migrations apply automatically because the `migrate` one-shot re-runs on every `up`.

Sanity:

```bash
docker compose images   # shows :master tag created datetime
docker compose ps       # all healthy
```

## §8 Rollback

Option A — pin compose file to a specific commit SHA tag:

```bash
cd /opt/tibiantis
sed -i 's|bgozl/tibiantis-scraper:master|bgozl/tibiantis-scraper:sha-<old-commit>|g' docker-compose.yml
docker compose pull
docker compose up -d
```

Option B — retag a local image as `:master`:

```bash
docker pull bgozl/tibiantis-scraper:sha-<old-commit>
docker tag bgozl/tibiantis-scraper:sha-<old-commit> bgozl/tibiantis-scraper:master
docker compose up -d
```

Option A leaves the rollback visible in the compose file (good for incident timeline). Option B is faster but invisible to `docker compose images`.

## §9 Troubleshooting

### 9.1 SECRET_KEY containing `$`

**Symptom:** `The "<varname>" variable is not set. Defaulting to a blank string.` warnings on every `docker compose` command; web container starts with a partial SECRET_KEY.
**Fix:** regenerate alphanumeric-only key (§4.3 generator), update `.env`, `docker compose up -d`.

### 9.2 `.env` world-readable

**Symptom:** `ls -la .env` shows `-rw-r--r--`.
**Fix:** `chmod 600 .env`.

### 9.3 Discord bot restart loop

**Symptom:** `docker compose logs discord_bot` shows "Improper token has been passed" + container restarting every ~30s.
**Fix:** regenerate token in Discord Developer Portal, edit `.env`, `docker compose up -d --no-deps discord_bot`.

### 9.4 `migrate` exit code 1

**Symptom:** `docker compose ps -a` shows migrate Exited (1); web doesn't start because `depends_on: service_completed_successfully` is unmet.
**Fix:** `docker compose logs migrate` → read the migration error. Common cause: postgres not actually ready despite healthcheck — wait, then `docker compose up -d migrate` to retry only the migrate service.

### 9.5 Port 8000 already in use

**Symptom:** `docker compose up -d` fails with `Bind for 0.0.0.0:8000 failed: port is already allocated`.
**Fix:** `sudo lsof -i :8000` → identify process → stop it, or change the host-side port in compose.

### 9.6 UFW lockout

**Symptom:** SSH disconnected mid-session, cannot reconnect.
**Fix:** Hetzner Cloud Console → server → Console (web TTY) → `ufw allow 22/tcp && ufw reload`.

### 9.7 Container DNS resolution failing

**Symptom:** container can't pull images, can't connect to Discord/Postgres by service name.
**Fix:** `docker network inspect tibiantis_default` → check internal DNS state. Fallback: `sudo systemctl restart docker` (will recreate networks; brief downtime).

### 9.8 Disk full (40GB CX22 SSD)

**Symptom:** `docker compose up` fails with `no space left on device`.
**Fix:** `docker system prune -af && docker volume prune` (careful — drops unused volumes). M-future: attach Hetzner Volume for `/var/lib/docker`.

### 9.9 Docker Hub anonymous rate limit (100 pulls / 6h)

**Symptom:** `docker compose pull` fails with `toomanyrequests: Too Many Requests`.
**Fix:** `docker login -u bgozl` with a Personal Access Token (200 pulls / 6h authenticated).

### 9.10 Hetzner Cloud Firewall vs UFW desynced

**Symptom:** SSH works on VM console but external SSH connections fail.
**Fix:** Cloud Console → Firewall → check inbound TCP 22 rule against your current ISP IP (`curl ipify.org`). Update CIDR if it changed.

### 9.11 Kuma `web /health/` monitor red while curl from host works

**Symptom:** All TCP monitors (postgres/redis/mongo) green, but the HTTP monitor `http://web:8000/health/` stays red.
**Cause:** Django's `ALLOWED_HOSTS` rejects requests with `Host: web:8000` because `web` is the docker service name, not a host Django recognizes — Django returns HTTP 400 `DisallowedHost`, Kuma sees not-200.
**Fix:** add `web` to `DJANGO_ALLOWED_HOSTS` in `.env`, then `docker compose up -d --force-recreate web`. The monitor recovers on the next 60s interval — no need to recreate it.

### 9.12 migrate exit 1: password authentication failed

**Symptom:** `docker compose logs migrate` ends with `psycopg.OperationalError: ... password authentication failed for user "tibiantis"`. Web/celery/bot stay in `Created` state.
**Cause:** `POSTGRES_PASSWORD` and the password embedded inside `DATABASE_URL` in `.env` don't match. Postgres initialized its data volume with the value of `POSTGRES_PASSWORD` on first boot; Django connects using `DATABASE_URL`.
**Fix:**
```bash
docker compose down
docker volume rm tibiantis_postgres_data    # ONLY safe before any real data exists
# Edit .env: make sure POSTGRES_PASSWORD and the password inside DATABASE_URL match exactly
docker compose up -d
```
If postgres has real data, do NOT drop the volume — instead, edit `DATABASE_URL` in `.env` to match the password postgres was initialized with, and `docker compose up -d --force-recreate web migrate celery_worker celery_beat discord_bot`.

## §10 Cost tally

| Component | Cost |
|---|---|
| Hetzner CX22 VM | ~5.83€/mc |
| Docker Hub public repo | 0€ (free tier) |
| GitHub Actions on public repo | 0€ (unlimited) |
| Discord bot | 0€ |
| **Total** | **~6€/mc** |

Optional add-ons (M-future):

- Hetzner backups: +20% of server cost (~1.20€/mc)
- Static IPv4 reservation: ~1€/mc
- Off-site backup storage (Backblaze B2): ~$0.005/GB/mc
