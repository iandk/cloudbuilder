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
        # Create a separate progress instance with its own console 
        # to prevent conflicts with logging outputs
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=50, complete_style="green"),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            expand=False,
            transient=True,  # Make progress bars disappear when done
            refresh_per_second=10,  # Lower refresh rate to reduce flickering
            disable=False
        )
        # Find and validate storage
        self._find_and_validate_storage()
        
    def _find_and_validate_storage(self) -> None:
        """Find a suitable storage if none provided, or validate the specified one."""
        try:
            # Get hostname first
            hostname_result = subprocess.run(
                ["hostname", "--short"],
                capture_output=True,
                text=True,
                check=True
            )
            hostname = hostname_result.stdout.strip()
            
            # Get available storage
            result = subprocess.run(
                ["pvesh", "get", f"/nodes/{hostname}/storage", "--output-format", "json"],
                capture_output=True,
                text=True,
                check=True
            )
            
            try:
                storages = json.loads(result.stdout)
                available_storages = [storage["storage"] for storage in storages]
                
                # Find storages that support VM images
                vm_compatible_storages = []
                for storage in storages:
                    content = storage.get("content", "").split(",")
                    if any(c.strip() in ["images", "rootdir"] for c in content):
                        vm_compatible_storages.append(storage["storage"])
                
                # If no storage was specified, automatically select the first compatible one
                if self.storage is None:
                    if vm_compatible_storages:
                        self.storage = vm_compatible_storages[0]
                        self.logger.info(f"Automatically selected storage: '{self.storage}'")
                    else:
                        self.logger.error("No VM-compatible storage found in Proxmox")
                        raise ValueError("No VM-compatible storage found in Proxmox. Please configure a storage that supports VM images.")
                # Otherwise validate the specified storage
                elif self.storage not in available_storages:
                    self.logger.error(f"Storage '{self.storage}' does not exist in Proxmox")
                    
                    if vm_compatible_storages:
                        self.logger.info(f"Available storages for VM templates: {', '.join(vm_compatible_storages)}")
                    else:
                        self.logger.info(f"Available storages (none support VM templates): {', '.join(available_storages)}")
                    
                    raise ValueError(f"Storage '{self.storage}' does not exist in Proxmox. "
                                   f"Please use one of these VM-compatible storages: {', '.join(vm_compatible_storages) if vm_compatible_storages else 'None available'}")
                
                # Check if the selected storage supports VM images
                storage_info = next((s for s in storages if s["storage"] == self.storage), None)
                if storage_info:
                    content = storage_info.get("content", "").split(",")
                    if not any(c.strip() in ["images", "rootdir"] for c in content):
                        self.logger.warning(f"Storage '{self.storage}' may not support VM templates (missing 'images' or 'rootdir' in content types)")
                        self.logger.info(f"VM-compatible storages: {', '.join(vm_compatible_storages) if vm_compatible_storages else 'None available'}")
                
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
            # Get hostname first
            hostname_result = subprocess.run(
                ["hostname", "--short"],
                capture_output=True,
                text=True,
                check=True
            )
            hostname = hostname_result.stdout.strip()
            
            # Use hostname in the pvesh command
            result = subprocess.run(
                ["pvesh", "get", f"/nodes/{hostname}/qemu", "--output-format", "json"],
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

    def remove_template(self, template: Template) -> None:
        """Remove a template from Proxmox."""
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
        except subprocess.CalledProcessError as e:
            if "does not exist" in str(e.stderr):
                self.logger.warning(f"Template {template.name} (VMID: {template.vmid}) not found in Proxmox")
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
        """Import template into Proxmox."""
        self.logger.info(f"Importing template: {template.name}")
        
        try:
            # Get a new VMID if needed
            if not template.vmid:
                vmid = self._get_next_vmid()
                template.vmid = vmid
            else:
                vmid = template.vmid
                
            self.logger.debug(f"Using VMID {vmid} for template {template.name}")
            
            # Verify image exists before proceeding
            if not image_path.exists():
                raise FileNotFoundError(f"Template image not found: {image_path}")
            
            # Check if VM already exists
            try:
                check_result = subprocess.run(
                    ["qm", "status", str(vmid)],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if check_result.returncode == 0:
                    # VM exists, destroy it first
                    self.logger.info(f"VM {vmid} already exists, removing it first")
                    self.remove_template(template)
            except Exception as e:
                self.logger.debug(f"Error checking VM status: {e}")
            
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