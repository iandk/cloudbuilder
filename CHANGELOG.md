# Changelog

All notable changes to cloudbuilder will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Template name validation against Proxmox naming rules (alphanumeric, hyphen, underscore, period; max 63 chars)
- Ubuntu 26.04 LTS template using Canonical's released `resolute` cloud image, so Cloudbuilder targets the actual 26.04 release instead of the older daily build.
- Alpine: BBR congestion control (`net.core.default_qdisc=fq`, `net.ipv4.tcp_congestion_control=bbr`)
- Alpine: Extracted DNS resolver script to `files/alpine/resolv-conf` for maintainability
- **Image trim + sparsify pass at build end.** The `finalize` component now also cleans the apt/dnf/zypper caches, vacuums the systemd journal, drops `/var/log/*.log`, wipes `/tmp` and `/var/tmp`, and runs `fstrim -av` (all guarded with `|| true` so distro-specific tools that aren't present don't break the build). On top of that, `template.py:build_template` now calls a new `sparsify_image()` step that runs `virt-sparsify --in-place` on the qcow2 after customize and logs the before/after size. Motivation: ubuntu-26-04 ships a 5G virtual disk (vs 3.5G for ubuntu-24-04), and on rproxy.fra2 pve1 we measured DeployNode jobs going from ~10s historical to 29–36s on the new template — the qmclone task time was only +3s but the cumulative virt-customize package-install bloat plus the larger virtual extent meant each clone copies more allocated blocks. Sparsify reclaims those zeroed regions in the qcow2 file itself rather than relying on Proxmox to skip them at clone time. Sparsify failure is non-fatal — logged as a warning, build proceeds.

### Changed

- Increased `CUSTOMIZE_TIMEOUT` from 10 to 30 minutes to handle large package updates
- Improved timeout error messages to include template name and workload context
- EPEL component: Better error handling with stderr warnings, skips dependent installs on failure
- SSH/dnf-automatic service enablement: Now warns to stderr instead of silent failure

### Changed

- `--self-update` now re-runs `install.sh` automatically when it detects `install.sh` changed between commits, so dependency updates propagate to existing hosts via the nightly auto-update timer. Previously the timer only did `git pull`, meaning any change to apt packages required a manual re-run of `install.sh` on every host — which is exactly how three hosts ended up with stale `passt` after the libguestfs networking fix shipped.
- virt-customize failure output is now readable. Previously a failure printed the full multi-hundred-line virt-customize stderr **three times** on the console (once at the inner ERROR, once when the customize wrapper re-raised, once when the outer build loop caught it with `exc_info=True`). Now: the full output is written to `/var/log/cloudbuilder/failures/{template}-{timestamp}.log` for forensics, the rolling `cloudbuilder.log` gets it at DEBUG level, and the console shows just a one-line summary with exit code and dump path, plus the last 20 lines of stderr (where the actual error almost always lives) so the operator can see what broke without opening the dump file.

### Fixed

- PAM MOTD configuration now idempotent (checks before appending)
- Crontab entries for qemu-agent watchdog now idempotent (both systemd and OpenRC variants)
- Standardized error handling patterns across all bash commands
- **install.sh: Remove `passt`, replace with `isc-dhcp-client`** — On Debian 13/Proxmox VE 8 hosts, libguestfs auto-prefers `passt` over `libslirp` whenever `passt` is installed. But `passt` has no built-in DHCP server, while the libguestfs supermin appliance's `/init` unconditionally calls `dhclient eth0` to bring up networking. With passt, the DHCPDISCOVER goes unanswered, eth0 stays unconfigured, and every `virt-customize --install` step fails with `Temporary failure resolving deb.debian.org` (or `archive.ubuntu.com`). install.sh now (a) does NOT install `passt`, (b) removes it if present, (c) installs `isc-dhcp-client` so `dhclient` is available, and (d) wipes the cached supermin appliance so the next run rebuilds without passt-specific qemu args. The previous commit `867ca90` (which added `passt` and `dhcpcd-base` "for libguestfs networking") was the cause of this regression — it should have left libguestfs alone with libslirp, which works out of the box.
