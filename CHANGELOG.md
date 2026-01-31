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
