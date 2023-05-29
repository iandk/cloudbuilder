#!/bin/bash

IMAGE_URL="http://dl.rockylinux.org/vault/rocky/9.0/images/x86_64/Rocky-9-GenericCloud.latest.x86_64.qcow2"
IMAGE_NAME="rocky-9"
DISK_IMAGE="Rocky-9-GenericCloud.latest.x86_64.qcow2"
TEMPLATE_ID=$(pvesh get /cluster/resources --type vm --output-format json | jq -r '.[].vmid' | awk '$0 >= 9000 && $0 < 10000 {a[$0]} END {for (i=9000; i<10000; i++) if (!(i in a)) {print i; exit}}')
STORAGE_NAME="local-zfs"


[ -e $DISK_IMAGE ] && rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL


#########################################################
# Image specific 

virt-customize -a $DISK_IMAGE --install qemu-guest-agent --update



#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME
