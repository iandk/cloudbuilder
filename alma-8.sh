#!/bin/bash

IMAGE_URL="https://repo.almalinux.org/almalinux/8.7/cloud/x86_64/images/AlmaLinux-8-GenericCloud-8.7-20221111.x86_64.qcow2"
IMAGE_NAME="alma-8"
DISK_IMAGE="AlmaLinux-8-GenericCloud-8.7-20221111.x86_64.qcow2"
TEMPLATE_ID=9012
STORAGE_NAME="local-zfs"


[ -e $DISK_IMAGE ] && rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL


#########################################################
# Image specific 

virt-customize -a $DISK_IMAGE --install qemu-guest-agent --update --run-command 'sudo sed -i 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config'



#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME