# proxmox.py
#!/usr/bin/env python3

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TaskProgressColumn,
    TimeRemainingColumn
)

from template import Template

console = Console()


class ProxmoxManager:
    """Manages Proxmox integration for templates."""

    def __init__(self, storage: Optional[str] = None, min_vmid: int = 9000):
        self.storage = storage
        self.min_vmid = min_vmid
        self.logger = logging.getLogger("cloudbuilder")
        self.node = self._get_hostname()  # Store hostname
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=50, complete_style="green"),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            expand=False,
            transient=True,  
            refresh_per_second=10,  
            disable=False
        )
        # Find and validate storage
        self._find_and_validate_storage()

    def _get_hostname(self) -> str:
        """Gets the local hostname for Proxmox API calls."""
        try:
            hostname_result = subprocess.run(
                ["hostname", "--short"],
                capture_output=True,
                text=True,
                check=True
            )
            hostname = hostname_result.stdout.strip()
            if not hostname:
                self.logger.error("Failed to determine hostname: output was empty.")
                raise ValueError("Hostname cannot be empty.")
            return hostname
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get hostname: {e.stderr if e.stderr else e}")
            raise
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while getting hostname: {e}")
            raise

    def _find_and_validate_storage(self) -> None:
        """Find a suitable storage if none provided, or validate the specified one."""
        try:
            # Get available storage using self.node
            result = subprocess.run(
                ["pvesh", "get", f"/nodes/{self.node}/storage", "--output-format", "json"],
                capture_output=True,
                text=True,
                check=True
            )

            try:
                storages = json.loads(result.stdout)
                all_storage_names = [s["storage"] for s in storages]

                # Find active, enabled, and VM-compatible storages
                vm_compatible_storages = []
                for storage in storages:
                    is_active = storage.get("active", 0) == 1
                    is_enabled = storage.get("enabled", 0) == 1
                    content = storage.get("content", "").split(",")
                    is_compatible = any(c.strip() in ["images", "rootdir"] for c in content)

                    if is_active and is_enabled and is_compatible:
                        vm_compatible_storages.append(storage["storage"])

                # If no storage was specified, automatically select the first compatible one
                if self.storage is None:
                    if vm_compatible_storages:
                        self.storage = vm_compatible_storages[0]
                        self.logger.info(f"Automatically selected storage: '{self.storage}'")
                    else:
                        self.logger.error("No active, enabled, and VM-compatible storage found in Proxmox.")
                        raise ValueError("No active and compatible storage found. Please configure a storage that supports VM images.")
                
                # If storage was specified, validate it
                elif self.storage not in all_storage_names:
                    self.logger.error(f"Storage '{self.storage}' does not exist in Proxmox.")
                    if vm_compatible_storages:
                         self.logger.info(f"Available storages for VM templates: {', '.join(vm_compatible_storages)}")
                    raise ValueError(f"Specified storage '{self.storage}' does not exist.")

                elif self.storage not in vm_compatible_storages:
                    self.logger.error(f"Specified storage '{self.storage}' is not active, enabled, or compatible for VM images.")
                    if vm_compatible_storages:
                         self.logger.info(f"Available storages for VM templates: {', '.join(vm_compatible_storages)}")
                    raise ValueError(f"Specified storage '{self.storage}' is not suitable for VM templates.")
                
                self.logger.debug(f"Using storage '{self.storage}' for templates")

            except json.JSONDecodeError:
                self.logger.error("Failed to parse Proxmox storage list")
                raise

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get storage list: {e.stderr if e.stderr else e}")
            raise

    def get_existing_templates(self) -> Dict[str, int]:
        """Get existing templates from Proxmox."""
        try:
            # Use self.node
            result = subprocess.run(
                ["pvesh", "get", f"/nodes/{self.node}/qemu", "--output-format", "json"],
                capture_output=True,
                text=True,
                check=True
            )

            templates = {}
            try:
                vms = json.loads(result.stdout)
                for vm in vms:
                    if vm.get("template") == 1:
                        templates[vm["name"]] = vm["vmid"]
                        self.logger.debug(f"Found existing template in Proxmox: {vm['name']} (VMID: {vm['vmid']})")
            except json.JSONDecodeError:
                self.logger.error("Failed to parse Proxmox API response")

            self.logger.info(f"Found {len(templates)} existing templates in Proxmox")
            return templates

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get existing templates: {e.stderr if e.stderr else e}")
            return {}

    def get_storage_content(self) -> list:
        """
        Retrieves and parses the content of the configured Proxmox storage.
        Returns a list of storage items, or an empty list on error.
        """
        if not self.node or not self.storage:
            self.logger.error("Node or storage not initialized for get_storage_content.")
            return []

        command_parts = ["get", f"/nodes/{self.node}/storage/{self.storage}/content", "--output-format", "json"]
        try:
            cmd = ["pvesh"] + command_parts
            self.logger.debug(f"Executing PVE API command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout while trying to get storage content from '{self.storage}' on node '{self.node}'.")
            return []
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get storage content from '{self.storage}' on node '{self.node}': {e.stderr or e.stdout}")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON from storage content for '{self.storage}': {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error getting storage content for '{self.storage}': {e}")
            return []

    def check_for_linked_clones(self, vmid: int) -> bool:
        """
        Checks if a given template VMID has linked clones on self.storage.
        A base disk for a template (e.g., vmid 9005) often has a 'name' like 'base-9005-disk-0'.
        Linked clones refer to this via a 'parent' field like 'base-9005-disk-0@__base__'.
        """
        base_disk_name_pattern = f"base-{vmid}-disk-0"  # This pattern seems to be Proxmox's default
        # Sometimes the disk might just be vm-<vmid>-disk-0 if not specifically made a base image by other tools.
        # However, for templates that ARE base images, 'base-{vmid}-disk-0' is common.
        # Let's also consider vm-{vmid}-disk-0 as a potential base name if the 'base-' prefix isn't used.

        # The crucial part is how linked clones refer to the parent, typically with @__base__
        # Proxmox template disks are often named like 'vm-<vmid>-disk-<index>' or 'base-<vmid>-disk-<index>'
        # We need to find the actual base disk name for the template VMID.
        # Let's assume the primary disk for a template VMID `vmid` is `vm-<vmid>-disk-0` or `base-<vmid>-disk-0`
        # This logic might need refinement based on actual disk naming conventions from `qm config <vmid>`

        storage_contents = self.get_storage_content()
        if not storage_contents:
            self.logger.warning(f"Could not retrieve or parse storage content for '{self.storage}' when checking "
                                f"linked clones for VMID {vmid}. Assuming no linked clones if content is unavailable/empty.")
            return False

        # Identify the actual base disk(s) for the given template VMID
        template_base_disk_volids = []
        for item in storage_contents:
            if item.get("vmid") == vmid and item.get("format") and ("content" in item and item["content"] == "images"):
                # Check if it's a base disk (parent is null or doesn't end with @__base__)
                if not item.get("parent") or not item.get("parent", "").endswith("@__base__"):
                    volid_name_part = item.get("volid", "").split(':')[-1]  # e.g., base-9005-disk-0 or vm-9005-disk-0
                    if volid_name_part:
                        template_base_disk_volids.append(volid_name_part)

        if not template_base_disk_volids:
            self.logger.debug(f"No primary disk volumes found for template VMID {vmid} on storage '{self.storage}'. Cannot check for linked clones.")
            return False

        self.logger.debug(f"Identified potential base disk names for template VMID {vmid}: {template_base_disk_volids}. "
                          f"Checking for clones linked to these (e.g., parent like 'disk_name@__base__').")

        for item in storage_contents:
            item_parent = item.get("parent")
            if item_parent:  # If a volume has a parent
                # A parent reference looks like 'local-zfs:base-9005-disk-0@__base__' or 'base-9005-disk-0@__base__'
                # We need to match the part before '@__base__' with our template_base_disk_volids
                parent_disk_name = item_parent.split('@__base__')[0]
                if parent_disk_name.endswith(tuple(template_base_disk_volids)):  # match if 'local-zfs:vol_id' or just 'vol_id'
                    for base_disk_name in template_base_disk_volids:
                        if parent_disk_name.endswith(base_disk_name):  # Ensure we are matching the correct base disk
                            clone_vmid = item.get("vmid", "N/A")
                            clone_volid = item.get("volid", "N/A")
                            self.logger.warning(
                                f"Template VMID {vmid} (base disk: {base_disk_name}) has a linked clone."
                                f"VMID {clone_vmid}, Volume {clone_volid} (parent: '{item_parent}'). "
                                f"Update/removal of template {vmid} will be skipped."
                            )
                            return True

        self.logger.debug(f"No linked clones found for VMID {vmid} referencing base disks {template_base_disk_volids} on storage '{self.storage}'.")
        return False

    def remove_template(self, template: Template) -> None:
        """
        Remove a template from Proxmox.
        Does not clear the VMID as we want to preserve it for rebuilding.
        """
        if not template.vmid:
            self.logger.warning(f"Cannot remove template {template.name} - no VMID assigned")
            return

        try:
            self.logger.info(f"Removing template {template.name} (VMID: {template.vmid})")
            result = subprocess.run(
                ["qm", "destroy", str(template.vmid)],
                capture_output=True,
                text=True,
                check=True
            )
            self.logger.debug(f"Template removal result: {result.stdout}")
            # We intentionally DO NOT clear the VMID here to preserve it for rebuilding

        except subprocess.CalledProcessError as e:
            if "does not exist" in str(e.stderr):
                self.logger.warning(f"Template {template.name} (VMID: {template.vmid}) not found in Proxmox")
                # We still don't clear the VMID as we want to preserve it for rebuilding
            else:
                self.logger.error(f"Failed to remove template {template.name}: {e.stderr}")
                raise

    def add_template_metadata(self, vmid: int, template: Template, is_update: bool = False) -> None:
        """Add template metadata as note in Proxmox."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if is_update:
            template.last_update = current_time
            metadata = {
                "name": template.name,
                "build_date": template.build_date,
                "last_update": current_time
            }
        else:
            template.build_date = current_time
            metadata = {
                "name": template.name,
                "build_date": current_time
            }

        note = json.dumps(metadata, indent=2)

        try:
            subprocess.run([
                "qm", "set", str(vmid),
                "--description", note
            ], check=True, capture_output=True)

            self.logger.debug(f"Added metadata to template {template.name} (VMID: {vmid})")

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to set template metadata: {e.stderr}")

    def _get_next_vmid(self) -> int:
        """Get next available VMID by finding the first unused ID starting from min_vmid."""
        try:
            # Get all existing VMs in the cluster
            result = subprocess.run(
                ["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"],
                capture_output=True,
                text=True,
                check=True
            )

            # Get all existing VMIDs and their names for better logging
            existing_vmids = {}  # vmid -> name mapping
            cluster_vms = json.loads(result.stdout)

            for vm in cluster_vms:
                if 'vmid' in vm:
                    vmid = vm['vmid']
                    name = vm.get('name', 'unknown')
                    node = vm.get('node', 'unknown')
                    existing_vmids[vmid] = (name, node)
                    self.logger.debug(f"Found existing VM: ID {vmid}, name '{name}' on node '{node}'")

            # Find first available ID starting from min_vmid
            current_id = self.min_vmid
            while current_id in existing_vmids:
                name, node = existing_vmids[current_id]
                self.logger.debug(f"VMID {current_id} is in use by '{name}' on node '{node}'")
                current_id += 1

            self.logger.info(f"Selected new VMID: {current_id}")
            return current_id

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get cluster resources: {e.stderr if e.stderr else e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Proxmox response: {e}")
            raise

    def import_template(self, template: Template, image_path: Path, is_update: bool = False) -> None:
        """Import template into Proxmox, preserving the VMID if it already exists.
        Assumes linked clone checks and necessary removals have been done by the caller if is_update is True."""
        self.logger.info(f"Importing template: {template.name}")

        vmid = template.vmid
        try:
            if not vmid:
                vmid = self._get_next_vmid()
                template.vmid = vmid
                self.logger.info(f"Assigned new VMID {vmid} for template {template.name}")
            else:
                self.logger.info(f"Using VMID {vmid} for template {template.name} (intended action: {'update' if is_update else 'create new'})")

            if not image_path.exists():
                self.logger.error(f"Template image not found: {image_path}")
                raise FileNotFoundError(f"Template image not found: {image_path}")

            # If the VMID (new or existing) is already in use, qm create will fail.
            # The caller (cloudbuilder.py) is responsible for clearing the VMID slot if this is an update operation.
            # No removal logic here within import_template for the is_update case.

            # Now show progress and do the actual import
            with console.status(f"Importing {template.name}", spinner="dots") as status:
                # Create VM
                self.logger.debug(f"Creating VM {template.name} with VMID {vmid}")
                subprocess.run([
                    "qm", "create", str(vmid),
                    "--memory", "1024",
                    "--net0", "virtio,bridge=vmbr0",
                    "--name", template.name,
                    "--agent", "enabled=1",
                    "--scsihw", "virtio-scsi-pci",
                    "--serial0", "socket",
                    "--vga", "serial0",
                    "--cpu", "host"
                ], check=True, capture_output=True)

                # Import disk directly with attachment (modern approach)
                self.logger.debug(f"Importing and attaching disk from {image_path} to storage {self.storage}")
                import_result = subprocess.run([
                    "qm", "set", str(vmid),
                    "--scsi0", f"{self.storage}:0,import-from={image_path},discard=on"
                ], check=True, capture_output=True, text=True)

                # Configure boot options
                self.logger.debug(f"Configuring boot options for VM {vmid}")
                subprocess.run([
                    "qm", "set", str(vmid),
                    "--boot", "c",
                    "--bootdisk", "scsi0"
                ], check=True, capture_output=True)

                # Add CloudInit drive
                self.logger.debug(f"Adding CloudInit drive to VM {vmid}")
                try:
                    subprocess.run([
                        "qm", "set", str(vmid),
                        "--ide2", f"{self.storage}:cloudinit"
                    ], check=True, capture_output=True)
                except subprocess.CalledProcessError as e:
                    self.logger.warning(f"Failed to add CloudInit drive: {e.stderr}. This may be normal if the storage doesn't support CloudInit.")

                # Add build/update information
                self.add_template_metadata(vmid, template, is_update)

                # Convert to template
                self.logger.debug(f"Converting VM {vmid} to template")
                template_result = subprocess.run(
                    ["qm", "template", str(vmid)],
                    check=True,
                    capture_output=True,
                    text=True
                )

            # Log success after the progress indicator is done
            self.logger.info(f"Successfully imported template {template.name} with VMID {vmid}")

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if hasattr(e.stderr, 'decode') else str(e.stderr)
            self.logger.error(f"Failed to import template {template.name}: {error_msg}")

            # Only cleanup if we created the VM and it failed
            if 'vmid' in locals() and "already exists" not in str(e.stderr):
                try:
                    self.logger.warning(f"Cleaning up failed template import: destroying VMID {vmid}")
                    subprocess.run(["qm", "destroy", str(vmid)], check=True, capture_output=True)
                except subprocess.CalledProcessError as cleanup_error:
                    self.logger.warning(f"Failed to clean up VM {vmid}: {cleanup_error}")
            raise
