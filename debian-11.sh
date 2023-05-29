#!/bin/bash

IMAGE_URL="https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-genericcloud-amd64.qcow2"
IMAGE_NAME="debian-11"
DISK_IMAGE="debian-11-genericcloud-amd64.qcow2"
TEMPLATE_ID=$(pvesh get /cluster/resources --type vm --output-format json | jq -r '.[].vmid' | awk '$0 >= 9000 && $0 < 10000 {a[$0]} END {for (i=9000; i<10000; i++) if (!(i in a)) {print i; exit}}')
STORAGE_NAME="local-zfs"


[ -e $DISK_IMAGE ] && rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL


#########################################################
# Image specific 

# Customize image and install qemu-guest-agent
# Debian does not entirely rely on cloud-init for network configuration, it will generate
# a dhcp config for the primary interface as this is commonly used with cloud providers
# We dont want that behaviour so we have to manually create the file which will mask the autogenerated
# /run/network/interfaces.d/ens18 file


virt-customize -a $DISK_IMAGE --install qemu-guest-agent --install resolvconf --update --run-command 'echo "auto ens18" >> /etc/network/interfaces.d/ens18' --run-command 'echo "iface ens18 inet manual" >> /etc/network/interfaces.d/ens18' --run-command '(crontab -l ; echo "*/1 * * * * pgrep -x 'qemu-guest-agent' > /dev/null || systemctl start qemu-guest-agent # Restart if failed") | crontab -'



#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME