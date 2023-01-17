


IMAGE_NAME=$1
DISK_IMAGE=$2
TEMPLATE_ID=$3
STORAGE_NAME=$4
NODE_NAME=$(hostname)


qm create $TEMPLATE_ID --memory 1024 --net0 virtio,bridge=vmbr0 --name $IMAGE_NAME
qm importdisk $TEMPLATE_ID $DISK_IMAGE $STORAGE_NAME

qm set $TEMPLATE_ID --scsihw virtio-scsi-pci --scsi0 $STORAGE_NAME:vm-$TEMPLATE_ID-disk-0,discard=on
qm set $TEMPLATE_ID --ide2 $STORAGE_NAME:cloudinit
qm set $TEMPLATE_ID --boot c --bootdisk scsi0
qm set $TEMPLATE_ID --serial0 socket --vga serial0
qm set $TEMPLATE_ID --agent 1
qm set $TEMPLATE_ID --cpu cputype=host
qm set $TEMPLATE_ID --ciuser root

pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -enable true
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -ipfilter true
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -policy_in ACCEPT
pvesh set /nodes/$NODE_NAME/qemu/$TEMPLATE_ID/firewall/options -policy_out ACCEPT

qm template $TEMPLATE_ID

[ -e $DISK_IMAGE ] && rm $DISK_IMAGE