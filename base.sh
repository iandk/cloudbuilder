


IMAGE_NAME=$1
DISK_IMAGE=$2
TEMPLATE_ID=$3
STORAGE_NAME=$4
NODE_NAME=$(hostname)


# Allow root login and plaintext auth
virt-edit -a $DISK_IMAGE /etc/cloud/cloud.cfg -e 's/disable_root: [Tt]rue/disable_root: False/'
virt-edit -a $DISK_IMAGE /etc/cloud/cloud.cfg -e 's/disable_root: 1/disable_root: 0/' 
virt-edit -a $DISK_IMAGE /etc/cloud/cloud.cfg -e 's/lock_passwd: [Tt]rue/lock_passwd: False/'
virt-edit -a $DISK_IMAGE /etc/cloud/cloud.cfg -e 's/lock_passwd: 1/lock_passwd: 0/' 
virt-edit -a $DISK_IMAGE /etc/cloud/cloud.cfg -e 's/ssh_pwauth:   0/ssh_pwauth:   1/'
virt-edit -a $DISK_IMAGE /etc/ssh/sshd_config -e 's/PasswordAuthentication no/PasswordAuthentication yes/'
virt-edit -a $DISK_IMAGE /etc/ssh/sshd_config -e 's/PermitRootLogin [Nn]o/PermitRootLogin yes/'
virt-edit -a $DISK_IMAGE /etc/ssh/sshd_config -e 's/#PermitRootLogin [Yy]es/PermitRootLogin yes/'
virt-edit -a $DISK_IMAGE /etc/ssh/sshd_config -e 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/'


qm create $TEMPLATE_ID --memory 1024 --net0 virtio,bridge=vmbr0 --name $IMAGE_NAME
qm importdisk $TEMPLATE_ID $DISK_IMAGE $STORAGE_NAME

# Base configuration 
qm set $TEMPLATE_ID --scsihw virtio-scsi-pci --scsi0 $STORAGE_NAME:vm-$TEMPLATE_ID-disk-0,discard=on
qm set $TEMPLATE_ID --ide2 $STORAGE_NAME:cloudinit
qm set $TEMPLATE_ID --boot c --bootdisk scsi0
qm set $TEMPLATE_ID --serial0 socket --vga serial0
qm set $TEMPLATE_ID --agent 1
qm set $TEMPLATE_ID --cpu cputype=host
qm set $TEMPLATE_ID --ciuser root

# Enable Firewall and IP Filter
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -enable true
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -ipfilter true
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -policy_in ACCEPT
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -policy_out ACCEPT


qm template $TEMPLATE_ID

[ -e $DISK_IMAGE ] && rm $DISK_IMAGE