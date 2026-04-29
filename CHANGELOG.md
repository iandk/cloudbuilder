# Changelog

All notable changes to cloudbuilder will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Template name validation against Proxmox naming rules (alphanumeric, hyphen, underscore, period; max 63 chars)
- Alpine: BBR congestion control (`net.core.default_qdisc=fq`, `net.ipv4.tcp_congestion_control=bbr`)
- Alpine: Extracted DNS resolver script to `files/alpine/resolv-conf` for maintainability

### Changed
- Increased `CUSTOMIZE_TIMEOUT` from 10 to 30 minutes to handle large package updates
- Improved timeout error messages to include template name and workload context
- EPEL component: Better error handling with stderr warnings, skips dependent installs on failure
- SSH/dnf-automatic service enablement: Now warns to stderr instead of silent failure

### Fixed
- PAM MOTD configuration now idempotent (checks before appending)
- Crontab entries for qemu-agent watchdog now idempotent (both systemd and OpenRC variants)
- Standardized error handling patterns across all bash commands
- **install.sh: Remove `passt`, replace with `isc-dhcp-client`** — On Debian 13/Proxmox VE 8 hosts, libguestfs auto-prefers `passt` over `libslirp` whenever `passt` is installed. But `passt` has no built-in DHCP server, while the libguestfs supermin appliance's `/init` unconditionally calls `dhclient eth0` to bring up networking. With passt, the DHCPDISCOVER goes unanswered, eth0 stays unconfigured, and every `virt-customize --install` step fails with `Temporary failure resolving deb.debian.org` (or `archive.ubuntu.com`). install.sh now (a) does NOT install `passt`, (b) removes it if present, (c) installs `isc-dhcp-client` so `dhclient` is available, and (d) wipes the cached supermin appliance so the next run rebuilds without passt-specific qemu args. The previous commit `867ca90` (which added `passt` and `dhcpcd-base` "for libguestfs networking") was the cause of this regression — it should have left libguestfs alone with libslirp, which works out of the box.
