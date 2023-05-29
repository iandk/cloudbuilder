#!/bin/bash

IMAGE_URL="https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2"
IMAGE_NAME="arch"
DISK_IMAGE="Arch-Linux-x86_64-cloudimg.qcow2"
TEMPLATE_ID=$(pvesh get /cluster/resources --type vm --output-format json | jq -r '.[].vmid' | awk '$0 >= 9000 && $0 < 10000 {a[$0]} END {for (i=9000; i<10000; i++) if (!(i in a)) {print i; exit}}')
STORAGE_NAME="local-zfs"


[ -e $DISK_IMAGE ] && rm $DISK_IMAGE
qm destroy $TEMPLATE_ID

wget $IMAGE_URL


#########################################################
# Image specific 

# Customize image and install qemu-guest-agent


virt-customize -a $DISK_IMAGE --run-command "pacman-key --init" --install archlinux-keyring --install qemu-guest-agent --install resolvconf --update



#########################################################





# General setup
bash base.sh $IMAGE_NAME $DISK_IMAGE $TEMPLATE_ID $STORAGE_NAME