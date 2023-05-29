#!/bin/bash

IMAGE_URL="http://cloud-images.ubuntu.com/lunar/current/lunar-server-cloudimg-amd64.img"
IMAGE_NAME="ubuntu-23-04"
DISK_IMAGE="lunar-server-cloudimg-amd64.img"
TEMPLATE_ID=$(pvesh get /cluster/resources --type vm --output-format json | jq -r '.[].vmid' | awk '$0 >= 9000 && $0 < 10000 {a[$0]} END {for (i=9000; i<10000; i++) if (!(i in a)) {print i; exit}}')
STORAGE_NAME="local-zfs"


[ -e $DISK_IMAGE ] && rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL

#########################################################
# Image specific 

virt-customize -a $DISK_IMAGE --install qemu-guest-agent --install resolvconf --update --run-command 'systemctl enable qemu-guest-agent' --run-command 'systemctl stop qemu-guest-agent' --run-command 'systemctl start qemu-guest-agent' --run-command 'rm -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf' --run-command '(crontab -l ; echo "*/1 * * * * pgrep -x 'qemu-guest-agent' > /dev/null || systemctl start qemu-guest-agent # Restart if failed") | crontab -'




#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME

