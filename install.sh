#!/bin/bash

# Install dependencies
apt update && apt install -y python3 python3-rich libguestfs-tools wget jq unzip curl git

# Install cloudbuilder
git clone https://github.com/iandk/cloudbuilder.git /opt/cloudbuilder
ln -s /opt/cloudbuilder/cloudbuilder.py /usr/local/bin/cloudbuilder

echo "Cloudbuilder installed successfully. You can now use the 'cloudbuilder' command to build templates."