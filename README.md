# CloudBuilder

CloudBuilder is a tool for managing VM templates in Proxmox. It automates downloading cloud OS images, customizing them, and importing them as Proxmox VM templates.

## Features

- **Template Management**: Download, customize, and import VM templates
- **Import Pre-built Images**: Import existing qcow2/img files from local paths or URLs
- **Minimal Downtime**: Updates templates with minimal unavailability in Proxmox
- **Template Filtering**: Process only specific templates with `--only` and `--except`
- **Status Reporting**: Show template status without making changes
- **Metadata Tracking**: Track build dates, update dates, and VMIDs
- **Automatic Storage Detection**: Automatically selects compatible Proxmox storage
- **Shell Completions**: Tab completion for bash and zsh
- **Self-Update**: Update cloudbuilder directly from git

## Requirements

- Python 3.6+
- Proxmox VE 6.0+
- libguestfs-tools (for virt-customize)
- Proxmox CLI tools (qm, pvesh)

## Installation

```bash
# Clone the repository
cd /opt && git clone https://github.com/iandk/cloudbuilder.git
cd cloudbuilder

# Install dependencies
pip install -r requirements.txt

# Make script executable
chmod +x cloudbuilder.py

# Create symlink
ln -s /opt/cloudbuilder/cloudbuilder.py /usr/local/bin/cloudbuilder
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
        "update_packages": false,
        "run_commands": [
            "apt-get update && apt-get -y dist-upgrade",
            "systemctl enable qemu-guest-agent",
            "rm -f /etc/ssh/ssh_host_*",
            "systemctl enable ssh",
            "rm -rf /var/lib/cloud/instance /var/lib/cloud/data",
            "truncate -s 0 /etc/machine-id"
        ],
        "ssh_password_auth": false,
        "ssh_root_login": false
    }
}
```

### Template Configuration Options

| Option | Description |
|--------|-------------|
| `image_url` | URL to download the cloud image |
| `install_packages` | List of packages to install |
| `update_packages` | Whether to update packages via virt-customize (recommend `false`, do manual upgrade in run_commands instead) |
| `run_commands` | Custom commands to run during customization |
| `ssh_password_auth` | Enable password authentication for SSH |
| `ssh_root_login` | Allow root login via SSH |

**Note**: For reliable builds, set `update_packages: false` and add the upgrade command as the first entry in `run_commands`:
- Debian/Ubuntu: `apt-get update && apt-get -y dist-upgrade`
- RHEL/Fedora: `sudo dnf -y upgrade`

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

# Update cloudbuilder itself
./cloudbuilder.py --self-update

# Set up shell tab completions
./cloudbuilder.py --setup-completions
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

### Importing Pre-built Images

Import templates from pre-built qcow2/img files without going through the customization process:

```bash
# Import templates from a local manifest file
./cloudbuilder.py --import-manifest imports.json

# Import templates from a remote manifest (URL)
./cloudbuilder.py --import-manifest http://example.com/imports.json

# Import only specific templates from manifest
./cloudbuilder.py --import-manifest imports.json --only rocky-9,centos-stream

# Force re-import templates that already exist (replaces them)
./cloudbuilder.py --import-manifest imports.json --force
```

**Manifest file format (`imports.json`):**

```json
{
  "rocky-9": {
    "source": "rocky-9.qcow2"
  },
  "centos-stream": {
    "source": "centos-stream.qcow2",
    "vmid": 9050
  },
  "custom-debian": {
    "source": "custom-debian.qcow2",
    "vmid": 9060,
    "customize": true
  }
}
```

**Manifest fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `source` | Yes | Filename, relative path, or full URL to the qcow2/img file. Relative sources are resolved against the manifest URL when importing from HTTP. |
| `vmid` | No | Specific VMID to assign (auto-assigns if omitted) |
| `customize` | No | Run virt-customize using config from templates.json (default: false) |

**Generating a manifest from a directory:**

```bash
# Generate manifest (writes to imports.json by default)
./cloudbuilder.py --generate-manifest /var/lib/cloudbuilder/templates/

# Specify output file
./cloudbuilder.py --generate-manifest /var/lib/cloudbuilder/templates/ -o my-manifest.json

# Output to stdout (for piping)
./cloudbuilder.py --generate-manifest /var/lib/cloudbuilder/templates/ -o -

# Serve the directory with a simple HTTP server
cd /var/lib/cloudbuilder/templates && python3 -m http.server 8080

# Then import on another host - sources are resolved relative to manifest URL
./cloudbuilder.py --import-manifest http://myserver:8080/imports.json
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
| `--self-update` | Update cloudbuilder from git repository |
| `--setup-completions` | Set up shell autocompletions (bash/zsh) |
| `--import-manifest FILE/URL` | Import pre-built images from a manifest file or URL (JSON) |
| `--generate-manifest DIR` | Generate manifest JSON from a directory of qcow2/img files |
| `--base-url URL` | Optional: prefix sources with full URL in generated manifest (by default, outputs just filenames which are resolved relative to manifest URL on import) |
| `-o, --output FILE` | Output file for generated manifest (default: imports.json, use '-' for stdout) |
| `--force` | Force import even if template exists in Proxmox (removes and re-imports) |
| `--only LIST` | Process only specific templates (comma-separated) |
| `--except LIST` | Process all templates except specified ones (comma-separated) |
| `--config PATH` | Path to templates configuration file (default: templates.json) |
| `--storage NAME` | Storage location in Proxmox (if not specified, will auto-detect) |
| `--template-dir PATH` | Directory for storing templates (default: /var/lib/cloudbuilder/templates) |
| `--temp-dir PATH` | Base directory for temporary files (default: /var/lib/cloudbuilder/tmp) |
| `--log-dir PATH` | Directory for log files (default: /var/log/cloudbuilder) |
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

## Template Preparation

Templates are prepared for cloning with these critical steps (handled in `run_commands`):

1. **SSH Host Keys**: Deleted during build, regenerated on first VM boot
2. **Machine ID**: Truncated (not deleted) so each VM gets a unique ID
3. **Cloud-init State**: Cleared so cloud-init runs fresh on new VMs

See `CLAUDE.md` for detailed implementation notes.

## Logging

Logs are written to both the console and `cloudbuilder.log` in the log directory.
