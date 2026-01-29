#!/bin/bash

# Install dependencies
apt update && apt install -y python3 python3-pip python3-rich libguestfs-tools wget jq unzip curl git

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
