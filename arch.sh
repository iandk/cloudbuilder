#!/bin/bash

IMAGE_URL="https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2"
IMAGE_NAME="arch"
DISK_IMAGE="Arch-Linux-x86_64-cloudimg.qcow2"
TEMPLATE_ID=9004
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