# CloudBuilder

CloudBuilder is a tool for managing VM templates in Proxmox. It automates downloading cloud OS images, customizing them, and importing them as Proxmox VM templates.

## Features

- **Template Management**: Download, customize, and import VM templates
- **Minimal Downtime**: Updates templates with minimal unavailability in Proxmox
- **Template Filtering**: Process only specific templates with `--only` and `--except`
- **Status Reporting**: Show template status without making changes
- **Metadata Tracking**: Track build dates, update dates, and VMIDs
- **Automatic Storage Detection**: Automatically selects compatible Proxmox storage

## Requirements

- Python 3.6+
- Proxmox VE 6.0+
- libguestfs-tools (for virt-customize)
- Proxmox CLI tools (qm, pvesh)

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/cloudbuilder.git
cd cloudbuilder

# Install dependencies
pip install -r requirements.txt

# Make script executable
chmod +x cloudbuilder.py
```

## Configuration

Create a `templates.json` file in the current directory:

```json
{
    "debian-12": {
        "image_url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2",
        "install_packages": [
            "qemu-guest-agent",
            "curl",
            "git"
        ],
        "update_packages": true,
        "run_commands": [
            "systemctl enable qemu-guest-agent"
        ],
        "ssh_password_auth": true,
        "ssh_root_login": true
    }
}
```

### Template Configuration Options

| Option | Description |
|--------|-------------|
| `image_url` | URL to download the cloud image |
| `install_packages` | List of packages to install |
| `update_packages` | Whether to update all packages |
| `run_commands` | Custom commands to run during customization |
| `ssh_password_auth` | Enable password authentication for SSH |
| `ssh_root_login` | Allow root login via SSH |

## Usage

### Basic Operations

```bash
# Check and build missing templates
./cloudbuilder.py

# Show status without making changes
./cloudbuilder.py --status

# Update existing templates
./cloudbuilder.py --update

# Rebuild templates from scratch
./cloudbuilder.py --rebuild
```

### Template Selection

```bash
# Process only specific templates
./cloudbuilder.py --only debian-12,ubuntu-24-04

# Process all templates except specified ones
./cloudbuilder.py --except fedora-40,fedora-41

# Combine with other flags
./cloudbuilder.py --update --only debian-12
```

### Advanced Options

```bash
# Specify custom paths
./cloudbuilder.py --config /path/to/templates.json --template-dir /path/to/templates --temp-dir /path/to/tmp

# Specify Proxmox storage (overrides automatic detection)
./cloudbuilder.py --storage local-zfs

# Set minimum VMID
./cloudbuilder.py --min-vmid 9000
```

### Command-line Options

| Option | Description |
|--------|-------------|
| `--status` | Show template status without making changes |
| `--update` | Update existing templates |
| `--rebuild` | Rebuild templates from scratch |
| `--only LIST` | Process only specific templates (comma-separated) |
| `--except LIST` | Process all templates except specified ones (comma-separated) |
| `--config PATH` | Path to templates configuration file (default: templates.json) |
| `--storage NAME` | Storage location in Proxmox (if not specified, will auto-detect) |
| `--template-dir PATH` | Directory for storing templates (default: /root/cloudbuilder/templates) |
| `--temp-dir PATH` | Base directory for temporary files (default: /root/cloudbuilder/tmp) |
| `--log-dir PATH` | Directory for log files (default: /root/cloudbuilder) |
| `--min-vmid NUM` | Minimum VMID for templates (default: 9000) |

## Storage Detection

CloudBuilder automatically detects and selects a compatible Proxmox storage for VM templates. It:

1. Scans available storages in your Proxmox environment
2. Identifies storages that support VM images (content types "images" or "rootdir")
3. Selects the first compatible storage found
4. Logs which storage was selected

You can override automatic detection by specifying a storage with `--storage`.

## Metadata

CloudBuilder maintains metadata about templates in two places:

1. `metadata.json` in the template directory
2. Template notes in Proxmox (accessible via the web UI)

Example metadata.json:
```json
{
  "debian-12": {
    "build_date": "2025-02-24 16:31:08",
    "last_update": "2025-02-24 16:52:59",
    "vmid": 9000
  }
}
```

## Project Structure

- `cloudbuilder.py`: Main entry point and orchestration
- `template.py`: Template models and management
- `proxmox.py`: Proxmox integration
- `utils.py`: Utilities and helpers

## Behavior Details

- **Default mode**: Ensures templates exist locally and in Proxmox
- **Update mode**: Updates existing templates while maintaining VMIDs
- **Rebuild mode**: Rebuilds templates from scratch while preserving VMIDs
- **Minimal downtime**: Templates are built locally first, then replaced in Proxmox one by one

## Logging

Logs are written to both the console and `cloudbuilder.log` in the log directory.