# Cloudbuilder Tasks

See [CHANGELOG.md](CHANGELOG.md) for completed work.

## Backlog

| # | Issue | Description |
|---|-------|-------------|
| 7 | Image Checksums | Add SHA256 verification for downloaded images |
| 9 | Hardcoded URLs | Add mirrors/fallbacks, consider version pinning |
| 12 | Magic Strings | Make VMID range, memory, bridge configurable per-template |

## Ideas

- Image caching with versioning for reproducible builds
- Dry-run mode to preview changes
- Template inheritance (e.g., `ubuntu-24-04-docker` extends `ubuntu-24-04`)
- Health checks to validate built images boot correctly
- Parallel builds for multiple templates
- Webhook notifications on build success/failure
