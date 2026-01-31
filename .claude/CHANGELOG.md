# Cloudbuilder Changelog

> LLM-maintained changelog for tracking all modifications to this project.

---

## 2025-01-31

### New Feature: `grow_partition` for min_size images

**Added automatic partition growth when disk is resized**

- New `grow_partition` field in templates.json specifies which partition to grow (e.g., "3" for /dev/sda3)
- When `min_size` triggers a disk resize, `grow_partition` runs growpart + filesystem resize BEFORE package installation
- Solves the issue where minimal images (like openSUSE Leap) run out of space during package installation
- Uses virt-customize to run growpart and xfs_growfs/resize2fs inside the image

**Removed `bpytop` from Fedora and openSUSE templates** - package no longer available in repos

Files affected: `template.py`, `templates.json`

---

### New Templates: Rocky Linux, CentOS Stream, openSUSE Leap

**Added three new distribution templates**

- **rocky-10**: Rocky Linux 10 (RHEL-compatible, drop-in AlmaLinux alternative)
- **centos-stream-10**: CentOS Stream 10 (RHEL upstream)
- **opensuse-leap-16**: openSUSE Leap 16.0 (first SUSE-family template)

**New components for openSUSE support**

- `qemu-agent-suse`: QEMU guest agent with cronie for cron watchdog
- `system-suse`: System hardening + common packages using zypper
- `opensuse-base`: openSUSE packages (vim, chrony, mtr, bind-utils, growpart, htop, bpytop)

Rocky and CentOS Stream use existing RHEL components (`rhel-base`, `epel`, `dnf-automatic`).

Files affected: `templates.json`

---

### Documentation: Local Template Testing

**Added QEMU testing instructions to README.md**

- New "Testing Templates Locally" section with examples for testing built images
- Shows how to boot templates with cloud-init for quick verification
- Includes SSH port forwarding example for remote testing
- Lists required packages (qemu-system-x86, genisoimage)
- Files affected: `README.md`

---

### Metadata Sync Improvement

**Suppressed misleading VMID warning on first run**

- Warning "incorrect VMID in metadata: None vs actual X" no longer shown when VMID is simply unset
- Warning still appears when metadata has a wrong (non-None) VMID value
- Affected file: `template.py` (sync_metadata_with_proxmox method)

---

## 2025-01-31

### Component Consolidation & Expansion

**Merged distro-specific components into unified cross-platform components**

- `motd-rhel`, `motd-debian`, `motd-ubuntu` → single `motd` component
- `finalize-rhel`, `finalize-debian` → single `finalize` component
- MOTD script content extracted to `files/cloudbuilder-motd` (imported via `copy_files`)
- `motd` component auto-detects OS (update-motd.d vs profile.d) and applies correct setup
- `finalize` component uses fallback commands (`systemctl enable sshd || ssh`)

**Extracted common patterns into new components**

- `timezone` - timezone setup (used by all 7 templates)
- `rhel-base` - RHEL packages + SELinux/chrony/qemu-ga setup
- `debian-base` - Debian/Ubuntu packages + unattended-upgrades setup
- `locale` - en_US.UTF-8 locale setup (Debian only, Ubuntu has it pre-configured)
- Final component count: 9 (system, shell, qemu-agent, timezone, rhel-base, debian-base, locale, motd, finalize)

**Moved packages to components**

- `system`: curl, git, wget, ca-certificates, traceroute, tcpdump, python3, jq, bash-completion
- `rhel-base`: vim-minimal, chrony, mtr, bind-utils, cloud-utils-growpart
- `debian-base`: cron, vim-tiny, mtr-tiny, dnsutils, cloud-guest-utils, unattended-upgrades, htop, bpytop
- Templates now only specify distro-specific extras (dnf-automatic, resolvconf, etc.)

**Moved common run_commands to components**

- `rhel-base`: `dnf -y upgrade`, SELinux disable, chrony enable, qemu-ga filter config
- `debian-base`: `apt-get update && apt-get -y dist-upgrade`, timesyncd enable, unattended-upgrades config
- Templates now only have distro-specific commands (EPEL, locale-gen, cloudimg cleanup)

**Fixed motd file staging**

- Changed from `/tmp/` to `/etc/` for cleaner file staging
- Files affected: `templates.json`, `files/cloudbuilder-motd` (new)

---

### Component System for templates.json

**Added support for reusable components to reduce template duplication**

- New `_resolve_template()` method in TemplateManager handles component resolution
- Templates can now reference components via a `uses` array
- Components can define `install_packages`, `run_commands`, and `copy_files`
- Merge strategy: components applied in order, then template's own values appended
- Backward compatible: legacy flat format (without components) still works
- Files affected: `template.py`

**New templates.json format:**

```json
{
  "components": {
    "base-hardening": {
      "description": "Sysctl security hardening",
      "run_commands": [
        "printf '%s\\n' 'net.ipv4.tcp_syncookies=1' ... > /etc/sysctl.d/99-cloudbuilder.conf"
      ]
    }
  },
  "templates": {
    "debian-12": {
      "image_url": "...",
      "uses": ["base-hardening", "motd-debian"],
      "install_packages": ["curl", "git"]
    }
  }
}
```

---

### File Import Feature (`copy_files`)

**Added support for copying files from host into template images**

- New `copy_files` field in templates.json allows specifying files to copy into the image
- Uses `virt-customize --copy-in` under the hood
- Files are copied after `install_packages` but before `run_commands`
- Paths are resolved relative to the cloudbuilder directory (where templates.json is)
- Validates that source files exist before starting customization
- Validates that destination paths end with `/` (must be directories, not file paths)
- Files affected: `template.py`, `README.md`, `CLAUDE.md`

### Documentation Cleanup

**Reduced redundancy between README.md and CLAUDE.md**

- README.md: User-facing documentation (usage, configuration, examples)
- CLAUDE.md: Implementation details for AI assistants (distro quirks, troubleshooting)
- Removed duplicate template structure examples and copy_files docs from CLAUDE.md
- CLAUDE.md now references README.md for configuration details

---

### XZ Compressed Image Support

**Added automatic decompression of XZ-compressed cloud images**

- Download function now detects URLs ending with `.xz` extension
- Automatically decompresses XZ files after download using Python's `lzma` module
- Fixes FreeBSD template import which provides qcow2 images as `.qcow2.xz` archives
- Compressed file is removed after decompression to save space
- Error handling updated to clean up both compressed and decompressed files on failure
- Files affected: `template.py`

**Example:**

```
# FreeBSD image URL ends with .qcow2.xz
"image_url": "https://download.freebsd.org/.../FreeBSD-14.3-RELEASE-amd64-BASIC-CLOUDINIT-ufs.qcow2.xz"

# Now automatically:
# 1. Downloads to freebsd-14.qcow2.xz
# 2. Decompresses to freebsd-14.qcow2
# 3. Removes the .xz file
```

---

## 2025-01-29

### Standalone Mode Support

**Added support for running cloudbuilder on non-Proxmox systems**

- Cloudbuilder now automatically detects if Proxmox VE is available
- When Proxmox is not detected, runs in standalone mode (builds images locally only)
- New `--build-only` flag to explicitly skip Proxmox import even on Proxmox systems
- Status table adapts to show only relevant columns in standalone mode (no Proxmox/VMID columns)
- All build operations (download, customize) work without Proxmox dependencies
- Files affected: `cloudbuilder.py`, `utils.py`

**New utility function:**

- Added `is_proxmox_available()` in `utils.py` - checks for `pvesh` command availability

**Example usage:**

```bash
# On a standalone system (auto-detected)
cloudbuilder --status
# WARNING  Proxmox VE not detected - running in standalone mode

# Explicitly build locally on a Proxmox system
cloudbuilder --build-only --only debian-12
# INFO     Standalone mode enabled - skipping Proxmox import
```

---

### Self-Update Local Changes Handling

**Enhanced `--self-update` to handle local modifications gracefully**

- Previously, `--self-update` would fail with cryptic git error if local changes existed
- Now detects local changes before attempting update using `git status --porcelain`
- Without `--force`: Shows clear error with options (use force, or manually stash)
- With `--force`: Uses `git reset --hard` to discard local changes and sync with remote
- Extended `--force` flag to work with `--self-update` (previously only worked with imports)
- Files affected: `utils.py`, `cloudbuilder.py`

**Example usage:**

```bash
# If local changes exist, this now shows helpful options instead of git error
cloudbuilder --self-update

# Force update, discarding any local changes
cloudbuilder --self-update --force
```

---

### Manifest Import/Export Improvements

**Relative URL Resolution for Remote Manifests**

- `--generate-manifest` now outputs just filenames by default (not absolute paths)
- `--import-manifest` now resolves relative sources against the manifest URL when fetching from HTTP
- This allows portable manifests: generate once, import from any host via URL
- Example workflow:
  - On template server: `cloudbuilder --generate-manifest .` creates `imports.json` with `{"source": "debian-12.qcow2"}`
  - On importing host: `cloudbuilder --import-manifest http://server:8080/imports.json` resolves to `http://server:8080/debian-12.qcow2`
- `--base-url` flag is now optional (only needed if you want explicit full URLs in manifest)
- Files affected: `cloudbuilder.py`, `README.md`

### Templates.json Improvements

**Crontab Syntax Standardization**

- Changed all QEMU guest agent cron entries to use consistent, robust syntax
- Added `2>/dev/null` to suppress "no crontab for user" errors on first run
- Standardized spacing: `>/dev/null` (no space)
- Affected: All 7 templates

**Package Update Strategy Change**

- Changed `update_packages` from `true` to `false` for all templates
- Added manual upgrade commands at the start of `run_commands`:
  - RHEL-based (Alma, Fedora): `sudo dnf -y upgrade`
  - Debian/Ubuntu: `apt-get update && apt-get -y dist-upgrade`
- Reason: `update_packages: true` caused slow/unreliable builds
- Affected: alma-9, alma-10, debian-12, debian-13, ubuntu-24-04, ubuntu-25-04

**SSH Host Key Regeneration**

- Added SSH host key deletion and regeneration enablement to ALL templates
- Ensures each cloned VM gets unique SSH host keys
- RHEL-based pattern:
  ```bash
  rm -f /etc/ssh/ssh_host_*
  systemctl enable sshd-keygen.target
  systemctl enable sshd
  ```
- Debian/Ubuntu pattern:
  ```bash
  rm -f /etc/ssh/ssh_host_*
  systemctl enable ssh
  ```
- Previously only alma-10 had this; now consistent across all templates

---

## Previous Changes (Pre-Changelog)

### 2025-01 (January)

- Added alma-10, debian-13, ubuntu-25-04, fedora-42 templates
- Fixed EPEL package installation order issue (htop/bpytop moved to run_commands)
- Added machine-id truncation for proper cloning
- Integrated colors.sh functionality into templates (MOTD, colors, prompt)
- Added TCP keepalive tuning, journald limits, bash-completion

### 2024-01 (January)

- Initial template setup for alma-9, debian-12, ubuntu-24-04
