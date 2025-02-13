#!/bin/bash

# templates.sh
# Script to build cloud templates for Proxmox VE based on templates defined in templates.json

set -e

# Required packages
REQUIRED_PACKAGES=("jq" "libguestfs-tools" "wget" "unzip" "curl")

# Function to check and install missing packages
function check_and_install_packages() {
    MISSING_PACKAGES=()
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            MISSING_PACKAGES+=("$pkg")
        fi
    done

    if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
        echo "Installing missing packages: ${MISSING_PACKAGES[*]}"
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PACKAGES[@]}"
    fi
}

# Default storage name
STORAGE_NAME="local"

# Define cloudbuilder temp directory
CLOUDBUILDER_TMP="/tmp/cloudbuilder"

# Function to setup and clean temporary directory
function setup_temp_directory() {
    echo "Setting up temporary directory..."
    # Remove directory if it exists
    if [ -d "$CLOUDBUILDER_TMP" ]; then
        echo "Cleaning up existing temporary directory..."
        rm -rf "$CLOUDBUILDER_TMP"
    fi
    # Create fresh directory
    echo "Creating temporary directory: $CLOUDBUILDER_TMP"
    mkdir -p "$CLOUDBUILDER_TMP"
}

# Function to display usage
function usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --template TEMPLATE      Specify a template to build (can be used multiple times)"
    echo "  --storage STORAGE_NAME   Specify the storage name (default: local)"
    echo "  --list-available         List available templates defined in templates.json"
    echo "  --list-existing          List existing templates in Proxmox VE"
    echo "  --help                   Display this help message"
    exit 1
}

# Parse command-line arguments
TEMPLATES_TO_BUILD=()
while [[ $# -gt 0 ]]; do
    case "$1" in
    --template)
        if [ -n "$2" ]; then
            TEMPLATES_TO_BUILD+=("$2")
            shift 2
        else
            echo "Error: --template requires an argument."
            usage
        fi
        ;;
    --storage)
        if [ -n "$2" ]; then
            STORAGE_NAME="$2"
            shift 2
        else
            echo "Error: --storage requires an argument."
            usage
        fi
        ;;
    --list-available)
        LIST_AVAILABLE=true
        shift
        ;;
    --list-existing)
        LIST_EXISTING=true
        shift
        ;;
    --help)
        usage
        ;;
    *)
        echo "Unknown option: $1"
        usage
        ;;
    esac
done

# Check and install required packages
check_and_install_packages

# Verify that the specified storage exists
function verify_storage() {
    if ! pvesm status | awk 'NR>1 {print $1}' | grep -Fxq "$STORAGE_NAME"; then
        echo "Error: Storage '$STORAGE_NAME' does not exist."
        echo "Available storages:"
        pvesm status | awk 'NR>1 {print "  - "$1}'
        exit 1
    fi
}

verify_storage

function get_existing_templates() {
    pvesh get "/nodes/$(hostname --short)/qemu" --output-format json | \
        jq -r '.[] | select(.template==1) | "\(.vmid): \(.name)"' | \
        sort -n
}

function get_existing_template_names() {
    pvesh get "/nodes/$(hostname --short)/qemu" --output-format json | \
        jq -r '.[] | select(.template==1) | .name'
}

# Read templates from templates.json
TEMPLATES_JSON="templates.json"
if [ ! -f "$TEMPLATES_JSON" ]; then
    echo "Error: templates.json file not found."
    exit 1
fi

# Validate templates.json
if ! jq empty "$TEMPLATES_JSON" >/dev/null 2>&1; then
    echo "Error: templates.json is not valid JSON."
    exit 1
fi

# Get list of available templates
AVAILABLE_TEMPLATES=($(jq -r 'keys[]' "$TEMPLATES_JSON"))

if [ "$LIST_AVAILABLE" = true ]; then
    echo "Available templates:"
    for tmpl in "${AVAILABLE_TEMPLATES[@]}"; do
        echo "  - $tmpl"
    done
    exit 0
fi

if [ "$LIST_EXISTING" = true ]; then
    echo "Existing templates in Proxmox VE:"
    get_existing_templates
    exit 0
fi

if [ ${#TEMPLATES_TO_BUILD[@]} -eq 0 ]; then
    echo "Error: No templates specified. Use --template TEMPLATE."
    usage
fi

# Validate templates
for TEMPLATE in "${TEMPLATES_TO_BUILD[@]}"; do
    if [[ ! " ${AVAILABLE_TEMPLATES[@]} " =~ " ${TEMPLATE} " ]]; then
        echo "Error: Template '${TEMPLATE}' is not defined in templates.json."
        exit 1
    fi
done

# Check for existing templates in Proxmox VE
EXISTING_TEMPLATE_NAMES=($(get_existing_template_names))

# Add after argument parsing and before starting the main process
setup_temp_directory

for TEMPLATE in "${TEMPLATES_TO_BUILD[@]}"; do
    if [[ " ${EXISTING_TEMPLATE_NAMES[@]} " =~ " ${TEMPLATE} " ]]; then
        echo "Warning: Template '${TEMPLATE}' already exists in Proxmox VE. Skipping..."
        continue
    fi

    echo "Building template: $TEMPLATE"

    # Extract data from JSON
    IMAGE_URL=$(jq -r --arg tmpl "$TEMPLATE" '.[$tmpl].image_url' "$TEMPLATES_JSON")
    INSTALL_PACKAGES=$(jq -r --arg tmpl "$TEMPLATE" '.[$tmpl].install_packages // empty | join(",")' "$TEMPLATES_JSON")
    UPDATE_PACKAGES=$(jq -r --arg tmpl "$TEMPLATE" '.[$tmpl].update_packages' "$TEMPLATES_JSON")
    RUN_COMMANDS=$(jq -c --arg tmpl "$TEMPLATE" '.[$tmpl].run_commands // empty' "$TEMPLATES_JSON")
    SSH_PASSWORD_AUTH=$(jq -r --arg tmpl "$TEMPLATE" '.[$tmpl].ssh_password_auth // empty' "$TEMPLATES_JSON")
    SSH_ROOT_LOGIN=$(jq -r --arg tmpl "$TEMPLATE" '.[$tmpl].ssh_root_login // empty' "$TEMPLATES_JSON")

    # Default SSH options to false if not set
    SSH_PASSWORD_AUTH=${SSH_PASSWORD_AUTH:-false}
    SSH_ROOT_LOGIN=${SSH_ROOT_LOGIN:-false}

    DISK_IMAGE=$(basename "$IMAGE_URL")
    IMAGE_PATH="$CLOUDBUILDER_TMP/$DISK_IMAGE"

    # Generate TEMPLATE_ID
    TEMPLATE_ID=$(pvesh get /cluster/resources --type vm --output-format json | jq -r '.[].vmid' | awk '
        $0 >= 9000 && $0 < 10000 {a[$0]}
        END {for (i=9000; i<10000; i++) if (!(i in a)) {print i; exit}}
    ')

    # Destroy existing VM with TEMPLATE_ID if exists
    if qm status "$TEMPLATE_ID" >/dev/null 2>&1; then
        echo "Destroying existing VM with ID $TEMPLATE_ID"
        qm destroy "$TEMPLATE_ID" --purge
    fi

    # Download the image if not already downloaded
    if [ ! -f "$IMAGE_PATH" ]; then
        echo "Downloading image: $IMAGE_URL"
        wget -O "$IMAGE_PATH" "$IMAGE_URL"
    else
        echo "Using cached image: $IMAGE_PATH"
    fi

    # Verify that the image file is valid
    if ! qemu-img info "$IMAGE_PATH" >/dev/null 2>&1; then
        echo "Error: $IMAGE_PATH is not a valid image file."
        exit 1
    fi

    # Apply customizations using virt-customize
    echo "Customizing image: $DISK_IMAGE"
    CUSTOMIZE_ARGS=()

    if [ "$UPDATE_PACKAGES" = "true" ]; then
        CUSTOMIZE_ARGS+=("--update")
    fi

    if [ -n "$INSTALL_PACKAGES" ]; then
        CUSTOMIZE_ARGS+=("--install" "$INSTALL_PACKAGES")
    fi

    if [ -n "$RUN_COMMANDS" ] && [ "$RUN_COMMANDS" != "null" ]; then
        # Read commands as an array
        mapfile -t COMMANDS < <(echo "$RUN_COMMANDS" | jq -r '.[]')
        for cmd in "${COMMANDS[@]}"; do
            CUSTOMIZE_ARGS+=("--run-command" "$cmd")
        done
    fi

    if [ ${#CUSTOMIZE_ARGS[@]} -gt 0 ]; then
        virt-customize -a "$IMAGE_PATH" "${CUSTOMIZE_ARGS[@]}"
    fi

    # General setup
    IMAGE_NAME="$TEMPLATE"
    NODE_NAME=$(hostname --short)

    # Conditionally allow root login and plaintext auth
    if [[ "$SSH_PASSWORD_AUTH" == "true" ]]; then
        virt-edit -a "$IMAGE_PATH" /etc/cloud/cloud.cfg -e 's/ssh_pwauth:.*[Ff]alse/ssh_pwauth: True/' || true
        virt-edit -a "$IMAGE_PATH" /etc/cloud/cloud.cfg -e 's/ssh_pwauth:.*0/ssh_pwauth: 1/' || true
        virt-edit -a "$IMAGE_PATH" /etc/ssh/sshd_config -e 's/^#*PasswordAuthentication .*/PasswordAuthentication yes/' || true
    fi

    if [[ "$SSH_ROOT_LOGIN" == "true" ]]; then
        virt-edit -a "$IMAGE_PATH" /etc/cloud/cloud.cfg -e 's/disable_root:.*[Tt]rue/disable_root: False/' || true
        virt-edit -a "$IMAGE_PATH" /etc/cloud/cloud.cfg -e 's/disable_root:.*1/disable_root: 0/' || true
        virt-edit -a "$IMAGE_PATH" /etc/cloud/cloud.cfg -e 's/lock_passwd:.*[Tt]rue/lock_passwd: False/' || true
        virt-edit -a "$IMAGE_PATH" /etc/cloud/cloud.cfg -e 's/lock_passwd:.*1/lock_passwd: 0/' || true
        virt-edit -a "$IMAGE_PATH" /etc/ssh/sshd_config -e 's/^#*PermitRootLogin .*/PermitRootLogin yes/' || true
    fi

    # Create VM
    echo "Creating VM with ID $TEMPLATE_ID and name $IMAGE_NAME"
    qm create "$TEMPLATE_ID" --memory 1024 --net0 virtio,bridge=vmbr0 --name "$IMAGE_NAME" --agent enabled=1

    # Import disk
    echo "Importing disk..."
    qm importdisk "$TEMPLATE_ID" "$IMAGE_PATH" "$STORAGE_NAME"

    # Get the volume name from the VM configuration
    VOLUME_NAME=$(qm config "$TEMPLATE_ID" | grep "^unused0:" | awk '{print $2}')

    if [ -z "$VOLUME_NAME" ]; then
        echo "Error: Unable to find the imported disk in VM configuration."
        exit 1
    fi

    # Assign the imported disk to scsi0
    echo "Assigning the imported disk ($VOLUME_NAME) to scsi0"
    qm set "$TEMPLATE_ID" --scsihw virtio-scsi-pci --scsi0 "$VOLUME_NAME,discard=on"

    # Continue with VM configuration
    qm set "$TEMPLATE_ID" --ide2 "$STORAGE_NAME:cloudinit"
    qm set "$TEMPLATE_ID" --boot c --bootdisk scsi0
    qm set "$TEMPLATE_ID" --serial0 socket --vga serial0
    qm set "$TEMPLATE_ID" --cpu host
    qm set "$TEMPLATE_ID" --ciuser root

    # Enable Firewall and IP Filter
    echo "Enabling firewall and IP filter for VM $TEMPLATE_ID"
    pvesh set "/nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options" -enable true
    pvesh set "/nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options" -ipfilter true
    pvesh set "/nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options" -policy_in ACCEPT
    pvesh set "/nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options" -policy_out ACCEPT

    # Convert VM to template
    echo "Converting VM $TEMPLATE_ID to template"
    qm template "$TEMPLATE_ID"

    # Clean up image file
    if [ -f "$IMAGE_PATH" ]; then
        echo "Removing image file: $IMAGE_PATH"
        rm -f "$IMAGE_PATH"
    fi

    echo "Template $TEMPLATE built successfully."
done

# At the very end of the script, add cleanup
echo "Cleaning up temporary directory..."
rm -rf "$CLOUDBUILDER_TMP"

echo "All specified templates have been processed."
