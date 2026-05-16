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
3. Run bootstrap:
   ```bash
   bash /tmp/bootstrap.sh
   # Check output ends with "Bootstrap complete. SSH as deploy@<ip>..."
   ```
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

Next: §4 First deploy (covered in M9.5-D47).
