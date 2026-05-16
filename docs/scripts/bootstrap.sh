#!/bin/bash
set -euo pipefail

# 1. Backup sshd_config (defensive — sed -i bez backup ryzykowne)
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

# 2. Create deploy user
useradd -m -s /bin/bash -G sudo deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# 3. Sudo bez hasła (single operator + key-only SSH = OK; M-future ograniczyć do docker)
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy

# 4. SSH hardening
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd

# 5. UFW (layer 2 ponad Hetzner Cloud Firewall — defense-in-depth)
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
# 8000/3001 NIE allow w UFW — dostęp przez SSH tunnel
ufw --force enable

# 6. Docker install (official script — convenience > apt-get docker.io which lags versions)
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
systemctl enable --now docker

# 7. apt updates baseline
apt-get update
apt-get upgrade -y
apt-get autoremove -y

echo "Bootstrap complete. SSH as deploy@<ip> from now on."
echo "Verify: ssh deploy@<ip>, then 'docker ps' should work."
