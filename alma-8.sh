#!/bin/bash

IMAGE_URL="https://repo.almalinux.org/almalinux/8/cloud/x86_64/images/AlmaLinux-8-GenericCloud-latest.x86_64.qcow2"
IMAGE_NAME="alma-8"
DISK_IMAGE="AlmaLinux-8-GenericCloud-latest.x86_64.qcow2"
TEMPLATE_ID=$(pvesh get /cluster/resources --type vm --output-format json | jq -r '.[].vmid' | awk '$0 >= 9000 && $0 < 10000 {a[$0]} END {for (i=9000; i<10000; i++) if (!(i in a)) {print i; exit}}')
STORAGE_NAME="local-zfs"


[ -e $DISK_IMAGE ] && rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL


#########################################################
# Image specific 

virt-customize -a $DISK_IMAGE --install qemu-guest-agent --update --run-command 'sudo sed -i 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config' --run-command '(crontab -l ; echo "*/1 * * * * pgrep -f 'qemu-ga' > /dev/null || systemctl start qemu-guest-agent # Restart if failed") | crontab -'



#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME
