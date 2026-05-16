#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

APT_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

# 1. apt update + upgrade FIRST — before sshd_config edits, so openssh-server
#    upgrade can't trigger a dpkg merge prompt that silently aborts the script.
echo "[1/8] apt update + upgrade"
apt-get update -qq
apt-get "${APT_OPTS[@]}" -y upgrade
apt-get "${APT_OPTS[@]}" -y autoremove

# 2. Backup sshd_config (defensive — sed -i bez backup ryzykowne)
echo "[2/8] backup sshd_config"
cp -f /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

# 3. Create deploy user (idempotent — re-run safe)
echo "[3/8] create deploy user"
id -u deploy >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo deploy
mkdir -p /home/deploy/.ssh
cp -f /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# 4. Sudo bez hasła (single operator + key-only SSH = OK; M-future ograniczyć do docker)
echo "[4/8] sudo NOPASSWD for deploy"
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy

# 5. SSH hardening
echo "[5/8] SSH hardening"
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
# Ubuntu/Debian: ssh.service. RHEL/CentOS: sshd.service. Try both for portability.
systemctl reload ssh.service 2>/dev/null \
    || systemctl reload sshd.service 2>/dev/null \
    || { echo "ERROR: cannot reload SSH (tried ssh.service + sshd.service)"; exit 1; }

# 6. UFW (layer 2 ponad Hetzner Cloud Firewall — defense-in-depth)
#    `ufw allow 22/tcp` MUSI być przed `ufw --force enable` — preventowanie SSH lockout.
echo "[6/8] UFW"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
# 8000/3001 NIE allow w UFW — dostęp przez SSH tunnel
ufw --force enable

# 7. Docker — Hetzner Ubuntu 24.04 minimal pre-installs Docker via snap.
#    Snap docker has strict confinement (breaks bind mounts) and auto-refresh
#    (restarts dockerd unannounced) — both production hazards. Replace with docker-ce.
echo "[7/8] Docker (remove snap docker if present, install docker-ce)"
if snap list docker >/dev/null 2>&1; then
    echo "  detected snap docker, removing..."
    snap remove docker
fi
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
systemctl enable --now docker

# 8. Final verification — assert critical post-conditions. If any fails, exit
#    non-zero so the operator sees the failure instead of a fake "complete" line.
echo "[8/8] verify"
ufw status verbose | grep -q "Status: active" \
    || { echo "ERROR: UFW not active"; exit 1; }
ufw status | grep -qE "^22/tcp\s+ALLOW" \
    || { echo "ERROR: UFW 22/tcp ALLOW missing"; exit 1; }
id deploy | grep -qE '\bdocker\b' \
    || { echo "ERROR: deploy not in docker group"; exit 1; }
systemctl is-active --quiet docker \
    || { echo "ERROR: docker.service not running"; exit 1; }
grep -qE '^PasswordAuthentication no' /etc/ssh/sshd_config \
    || { echo "ERROR: sshd PasswordAuthentication not disabled"; exit 1; }

echo "Bootstrap complete. SSH as deploy@<ip> from now on."
echo "Verify: ssh deploy@<ip>, then 'docker ps' should work."
