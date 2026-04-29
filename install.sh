#!/bin/bash

# Install dependencies
# NOTE: We deliberately do NOT install `passt`. If `passt` is present, libguestfs
# prefers it over libslirp, but passt has no built-in DHCP server. The supermin
# appliance's /init unconditionally calls `dhclient eth0`, gets no DHCPOFFER,
# and the appliance ends up with only `lo` — every `apt-get update` then fails
# with "Temporary failure resolving deb.debian.org". libslirp/SLIRP DOES have
# DHCP, so falling back to it makes the appliance get an IP automatically.
# isc-dhcp-client provides /sbin/dhclient that the appliance init expects.
apt update && apt install -y python3 python3-pip python3-rich libguestfs-tools wget jq unzip curl git ovmf isc-dhcp-client

# Remove passt if it slipped in (e.g., older install.sh or a co-installed package
# that pulled it). libguestfs auto-prefers passt and breaks if present.
apt remove -y passt 2>/dev/null || true

# Wipe the cached supermin appliance so the next virt-customize rebuilds it
# without passt-specific qemu args baked in.
rm -rf /var/tmp/.guestfs-* 2>/dev/null || true

# Installation directories
INSTALL_DIR="/opt/cloudbuilder"
DATA_DIR="/var/lib/cloudbuilder"
LOG_DIR="/var/log/cloudbuilder"

# Create directories
mkdir -p "$DATA_DIR/templates"
mkdir -p "$DATA_DIR/tmp"
mkdir -p "$LOG_DIR"

# Set permissions
chown -R root:root "$DATA_DIR" "$LOG_DIR"
chmod -R 755 "$DATA_DIR" "$LOG_DIR"

# Install cloudbuilder
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing cloudbuilder installation..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "Installing cloudbuilder..."
    git clone https://github.com/iandk/cloudbuilder.git "$INSTALL_DIR"
fi

# Create symlink to make cloudbuilder executable
ln -sf "$INSTALL_DIR/cloudbuilder.py" /usr/local/bin/cloudbuilder
chmod +x "$INSTALL_DIR/cloudbuilder.py"

# Set up shell completions
echo "Setting up shell completions..."
cloudbuilder --setup-completions

# Set up automatic nightly self-update timer
echo "Setting up automatic self-update timer..."
cp "$INSTALL_DIR/cloudbuilder-update.service" /etc/systemd/system/
cp "$INSTALL_DIR/cloudbuilder-update.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cloudbuilder-update.timer

echo ""
echo "Cloudbuilder installed successfully."
echo "Configuration file: $INSTALL_DIR/templates.json"
echo "Template directory: $DATA_DIR/templates"
echo "Log directory: $LOG_DIR"
echo ""
echo "Automatic updates: Enabled (runs nightly at 3am)"
echo "  Check timer:  systemctl status cloudbuilder-update.timer"
echo "  Check logs:   journalctl -u cloudbuilder-update"
echo "  Disable:      systemctl disable cloudbuilder-update.timer"
