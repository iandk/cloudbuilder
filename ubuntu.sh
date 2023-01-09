#!/bin/bash

IMAGE_URL="https://cloud-images.ubuntu.com/kinetic/current/kinetic-server-cloudimg-amd64.img"
IMAGE_NAME="ubuntu-22-10"
DISK_IMAGE="kinetic-server-cloudimg-amd64.img"
TEMPLATE_ID=9008 
STORAGE_NAME="local-zfs"


rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL

#########################################################
# Image specific 

#virt-customize -a $DISK_IMAGE --install qemu-guest-agent --install resolvconf --update


#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME

