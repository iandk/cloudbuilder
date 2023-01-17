#!/bin/bash

echo "This script will build Proxmox VE OS templates for Debian, Ubuntu and Alma"
read -p "Press Enter to continue, or Ctrl+C to cancel."

apt update && apt install -y libguestfs-tools


# bash debian.sh

bash ubuntu.sh

# bash alma.sh

