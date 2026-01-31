# v6Node Cloud Image Builder

> Project-specific context for AI assistants working on the cloudbuilder project.

---

## IMPORTANT: Documentation Requirements

**After making ANY changes to this project, you MUST update documentation.**

See `.claude/INSTRUCTIONS.md` for full requirements. At minimum:
1. **Always update** `.claude/CHANGELOG.md` with what changed and why
2. **Update this file** if template structure/behavior changes
3. **Update README.md** if user-facing behavior changes

---

## Project Overview

**Purpose**: Build customized VM templates for v6Node cloud hosting using Proxmox VE and `virt-customize` from libguestfs.

**Key Files**:
- `templates.json` - Main configuration defining all OS templates
- `cloudbuilder.py` - Build script that reads templates.json and runs virt-customize
- `colors.sh` - Reference script (functionality integrated into templates.json)

---

## Build Pipeline

```
Download → install_packages → copy_files → run_commands → SSH settings → Upload to Proxmox
```

### Critical: Execution Order

`install_packages` runs via `virt-customize --install` in a **chroot environment BEFORE** `run_commands`. This has important implications:

- You **cannot** enable EPEL in install_packages and expect EPEL packages to install
- EPEL packages (htop, bpytop on RHEL) must be installed via `run_commands` AFTER enabling EPEL
- Any repository configuration must happen in `run_commands` before dependent packages

### File Copying (`copy_files`)

Uses `virt-customize --copy-in`. Paths are resolved relative to the cloudbuilder directory. See README for usage examples.

---

## Current Templates

| Template     | Base Image      | Package Manager | MOTD Mechanism |
| ------------ | --------------- | --------------- | -------------- |
| alma-9       | AlmaLinux 9     | dnf             | profile.d      |
| alma-10      | AlmaLinux 10    | dnf             | profile.d      |
| debian-12    | Debian Bookworm | apt             | update-motd.d  |
| debian-13    | Debian Trixie   | apt             | update-motd.d  |
| ubuntu-24-04 | Ubuntu Noble    | apt             | update-motd.d  |
| ubuntu-25-04 | Ubuntu Plucky   | apt             | update-motd.d  |
| fedora-42    | Fedora 42       | dnf             | profile.d      |

---

## Template Structure

See README.md for configuration options and examples. Key implementation notes:

- `update_packages`: Set to `false`; manual upgrade in `run_commands` is more reliable
- `copy_files`: Dict mapping local paths to guest directories (uses `--copy-in`)
- `run_commands`: Must end with machine-id truncation and cloud-init cleanup

---

## Distro-Specific Package Mapping

| Function        | Debian/Ubuntu         | RHEL/Fedora            |
| --------------- | --------------------- | ---------------------- |
| DNS tools       | `dnsutils`            | `bind-utils`           |
| MTR             | `mtr-tiny`            | `mtr`                  |
| Vim             | `vim-tiny`            | `vim-minimal`          |
| Auto updates    | `unattended-upgrades` | `dnf-automatic`        |
| Disk grow       | `cloud-guest-utils`   | `cloud-utils-growpart` |
| Time sync       | `systemd-timesyncd`   | `chrony`               |
| Bash completion | `bash-completion`     | `bash-completion`      |

---

## EPEL Handling (RHEL-based only)

**htop and bpytop are NOT in base RHEL repos.** Must enable EPEL first in `run_commands`:

### AlmaLinux 9
```bash
sudo dnf install -y epel-release || sudo dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm
sudo dnf install -y htop bpytop || echo 'htop/bpytop installation skipped'
```

### AlmaLinux 10 (requires CRB + EPEL)
```bash
command -v crb >/dev/null 2>&1 && sudo crb enable || (sudo dnf -y install dnf-plugins-core && sudo dnf config-manager --set-enabled crb)
rpm -q epel-release >/dev/null 2>&1 || sudo dnf install -y epel-release || sudo dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-10.noarch.rpm
sudo dnf -y makecache
sudo dnf install -y htop bpytop || echo 'htop/bpytop installation skipped'
```

### Fedora
htop/bpytop are in base repos - **no EPEL needed**.

---

## MOTD Implementation

### Debian/Ubuntu (`/etc/update-motd.d/`)

- Scripts executed by PAM on login
- Output goes to `/run/motd.dynamic`
- Must disable default scripts: `chmod -x /etc/update-motd.d/*`
- Ubuntu: disable motd-news services: `systemctl disable motd-news.timer`

### RHEL/Fedora (`/etc/profile.d/`)

- No update-motd.d mechanism available
- Script runs on every interactive shell
- **Must guard against multiple displays**:
```bash
[ -n "$V6NODE_MOTD_SHOWN" ] && return
export V6NODE_MOTD_SHOWN=1
```
- Check for interactive shell: `[ -z "$PS1" ] && return`

---

## Security Hardening Applied

### Sysctl (`/etc/sysctl.d/99-v6node.conf`)

```
net.ipv4.tcp_syncookies=1              # SYN flood protection
net.ipv4.conf.all.accept_redirects=0   # Ignore ICMP redirects
net.ipv4.conf.all.send_redirects=0     # Don't send redirects
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.all.log_martians=1       # Log suspicious packets
net.ipv6.conf.all.accept_redirects=0
net.core.rmem_max=16777216             # TCP buffer tuning
net.core.wmem_max=16777216
net.core.netdev_max_backlog=30000
net.core.somaxconn=65535
vm.swappiness=10                       # Reduce swap usage
net.ipv4.tcp_keepalive_time=600        # Faster dead connection detection
net.ipv4.tcp_keepalive_intvl=60
net.ipv4.tcp_keepalive_probes=5
```

### SELinux (RHEL-based)

Disabled via: `sed -i 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config`

### Auto Updates

- **Debian/Ubuntu**: `unattended-upgrades` with auto-reboot disabled
- **RHEL/Fedora**: `dnf-automatic` with security-only upgrades

---

## Template Preparation for Cloning

### Machine ID (CRITICAL)

**Must truncate (not delete)** `/etc/machine-id`:

```bash
truncate -s 0 /etc/machine-id
```

If deleted instead of truncated, systemd may fail to boot properly.

### Cloud-init State

Clean state so cloud-init runs fresh on new VMs:

```bash
rm -rf /var/lib/cloud/instance /var/lib/cloud/data
```

### SSH Host Keys

**All templates now explicitly handle SSH key regeneration** to ensure unique keys per VM:

**RHEL/Fedora** (near end of run_commands):
```bash
sudo rm -f /etc/ssh/ssh_host_*
sudo systemctl enable sshd-keygen.target
sudo systemctl enable sshd
```

**Debian/Ubuntu** (near end of run_commands):
```bash
rm -f /etc/ssh/ssh_host_*
systemctl enable ssh
```

Keys are deleted during build, then regenerated on first boot by systemd.

---

## QEMU Guest Agent

Required for Proxmox VM management (shutdown, IP reporting):

```bash
# Install (same package name all distros)
qemu-guest-agent

# Enable
systemctl enable qemu-guest-agent

# Cron fallback (agent can crash) - USE THIS EXACT SYNTAX:
(crontab -l 2>/dev/null; echo '*/1 * * * * pgrep -f qemu-ga >/dev/null || systemctl start qemu-guest-agent') | crontab -

# Enable guest-exec for Proxmox (RHEL-based)
sed -i 's/\(FILTER_RPC_ARGS="--allow-rpcs=.*\)"/\1,guest-exec,guest-exec-status"/' /etc/sysconfig/qemu-ga
```

**Note**: The `2>/dev/null` after `crontab -l` suppresses "no crontab for user" errors on first run.

---

## Profile Scripts Created

| Script                              | Purpose                                        |
| ----------------------------------- | ---------------------------------------------- |
| `/etc/profile.d/colors.sh`          | Color aliases for ls, grep, diff, ip; man pages |
| `/etc/profile.d/prompt.sh`          | Cyan prompt (root), Green prompt (users)       |
| `/etc/profile.d/motd.sh`            | Dynamic MOTD (RHEL/Fedora only)                |
| `/etc/profile.d/history-timestamps.sh` | Bash history with timestamps                |
| `/etc/update-motd.d/00-v6node`      | Dynamic MOTD (Debian/Ubuntu only)              |

---

## SSH Configuration

| Setting                 | Debian/Ubuntu             | RHEL/Fedora               |
| ----------------------- | ------------------------- | ------------------------- |
| Main config             | `/etc/ssh/sshd_config`    | `/etc/ssh/sshd_config`    |
| Drop-in dir             | `/etc/ssh/sshd_config.d/` | `/etc/ssh/sshd_config.d/` |
| Service name            | `ssh` or `sshd`           | `sshd`                    |

**Ubuntu-specific**: Remove `/etc/ssh/sshd_config.d/60-cloudimg-settings.conf` to allow custom SSH settings.

To suppress duplicate "Last login" messages:
```bash
sed -i 's/^#*PrintLastLog.*/PrintLastLog no/' /etc/ssh/sshd_config
```

---

## Common Issues & Solutions

### "No match for argument: htop bpytop" on AlmaLinux

**Cause**: EPEL not enabled before package installation
**Solution**: Move htop/bpytop install to `run_commands` after EPEL enablement

### Identical machine-id across cloned VMs

**Cause**: machine-id not cleared before template creation
**Solution**: `truncate -s 0 /etc/machine-id` (must truncate, NOT delete)

### MOTD shows multiple times in same session

**Cause**: profile.d script runs on every shell spawn
**Solution**: Guard with environment variable (see MOTD section above)

### Ubuntu default MOTD still appearing

**Cause**: Ubuntu has multiple MOTD sources
**Solution**: Disable all of them:
```bash
chmod -x /etc/update-motd.d/*
systemctl disable motd-news.timer motd-news.service
rm -f /etc/update-motd.d/{10-help-text,50-motd-news,90-updates-available,91-release-upgrade,95-hwe-eol}
```

---

## JSON Escaping Reference

When editing templates.json:

| Character    | In Shell       | In JSON          |
| ------------ | -------------- | ---------------- |
| Newline      | `\n`           | `\n`             |
| Backslash    | `\`            | `\\`             |
| Double quote | `"`            | `\"`             |
| ANSI escape  | `\e` or `\033` | `\\e` or `\\033` |
| Dollar sign  | `$`            | `$` (no escape)  |
| Single quote | `'`            | `'` (no escape)  |

---

## Testing Checklist

After building a template and creating a VM:

1. SSH Access - Can connect via SSH
2. Machine ID - `cat /etc/machine-id` - should be unique per VM
3. SSH Host Keys - Should differ between VMs
4. MOTD Display - v6Node branded MOTD with system info
5. Colors - `ls --color=auto` works, man pages colored
6. Prompt - Colored prompt displays correctly
7. Guest Agent - `systemctl status qemu-guest-agent` - running
8. Auto Updates - Service enabled
9. Sysctl - `sysctl net.ipv4.tcp_syncookies` returns 1
10. No Duplicate Login - Only one "Last login" message

---

## File Locations Summary

| Purpose               | Path                                           |
| --------------------- | ---------------------------------------------- |
| Color aliases         | `/etc/profile.d/colors.sh`                     |
| Colored prompt        | `/etc/profile.d/prompt.sh`                     |
| Dynamic MOTD (RHEL)   | `/etc/profile.d/motd.sh`                       |
| Dynamic MOTD (Debian) | `/etc/update-motd.d/00-v6node`                 |
| History timestamps    | `/etc/profile.d/history-timestamps.sh`         |
| Sysctl hardening      | `/etc/sysctl.d/99-v6node.conf`                 |
| Journald limits       | `/etc/systemd/journald.conf.d/size-limit.conf` |
| I/O scheduler         | `/etc/udev/rules.d/60-virtio-scheduler.rules`  |

---

## Version History

> **Note**: Detailed changelog now maintained in `.claude/CHANGELOG.md`

- **2024-01**: Initial template setup for alma-9, debian-12, ubuntu-24-04
- **2025-01**: Added alma-10, debian-13, ubuntu-25-04, fedora-42
- **2025-01**: Fixed EPEL package installation order issue
- **2025-01**: Added machine-id truncation for proper cloning
- **2025-01**: Integrated colors.sh functionality (MOTD, colors, prompt)
- **2025-01**: Added TCP keepalive tuning, journald limits, bash-completion
- **2025-01-29**: Standardized crontab syntax across all templates
- **2025-01-29**: Changed to manual package upgrades (update_packages: false)
- **2025-01-29**: Added SSH key regeneration to ALL templates
- **2025-01-29**: Created `.claude/` documentation structure
- **2025-01-31**: Added `copy_files` feature for importing files into templates
