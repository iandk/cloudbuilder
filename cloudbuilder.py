#!/usr/bin/env python3

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TaskProgressColumn,
    TimeRemainingColumn
)

# Configure console for output
console = Console()

# Constants
DOWNLOAD_TIMEOUT = 600  # 10 minutes timeout for downloads
CUSTOMIZE_TIMEOUT = 600  # 10 minutes timeout for customization


def setup_logging(log_dir: Path) -> logging.Logger:
    """Setup logging to both file and console with a single continuous log file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "cloudbuilder.log"  # Single continuous log file
    
    # Create file handler and set its level
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    
    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_formatter)
    
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[
            RichHandler(console=console, rich_tracebacks=True, show_time=False, level=logging.INFO),
            file_handler
        ]
    )
    return logging.getLogger("cloudbuilder")

@dataclass
class Template:
    name: str
    image_url: str
    install_packages: List[str]
    update_packages: bool
    run_commands: List[str]
    ssh_password_auth: bool
    ssh_root_login: bool
    build_date: Optional[str] = None
    last_update: Optional[str] = None
    vmid: Optional[int] = None

class TempDirManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.temp_dirs: List[Path] = []
        
        # Register cleanup handlers
        signal.signal(signal.SIGINT, self.cleanup_handler)
        signal.signal(signal.SIGTERM, self.cleanup_handler)
    
    def create_temp_dir(self) -> Path:
        """Create a new temporary directory and track it for cleanup."""
        temp_dir = Path(tempfile.mkdtemp(dir=self.base_dir))
        self.temp_dirs.append(temp_dir)
        return temp_dir
    
    def cleanup_handler(self, signum, frame):
        """Handle cleanup on process termination."""
        self.cleanup()
        sys.exit(1)
    
    def cleanup(self):
        """Clean up all temporary directories."""
        for temp_dir in self.temp_dirs:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        self.temp_dirs.clear()

class TemplateBuilder:
    def __init__(self, config_path: str, template_dir: Path, temp_manager: TempDirManager, storage: str = "local"):
        self.config_path = config_path
        self.template_dir = template_dir
        self.temp_manager = temp_manager
        self.storage = storage
        self.templates: Dict[str, Template] = {}
        self.logger = logging.getLogger("cloudbuilder")
        self.metadata_file = template_dir / "metadata.json"
        
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(complete_style="green"),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            expand=True,
            transient=False
        )
        
        # Create template directory if it doesn't exist
        self.template_dir.mkdir(parents=True, exist_ok=True)

    def load_templates(self) -> None:
        """Load templates from configuration file and metadata."""
        try:
            with open(self.config_path) as f:
                config = json.load(f)
            
            # Load existing metadata if available
            metadata = {}
            if self.metadata_file.exists():
                with open(self.metadata_file) as f:
                    metadata = json.load(f)
            
            self.templates = {}
            for name, t in config.items():
                template = Template(
                    name=name,
                    image_url=t["image_url"],
                    install_packages=t.get("install_packages", []),
                    update_packages=t.get("update_packages", False),
                    run_commands=t.get("run_commands", []),
                    ssh_password_auth=t.get("ssh_password_auth", False),
                    ssh_root_login=t.get("ssh_root_login", False)
                )
                
                # Load metadata if available
                if name in metadata:
                    template.build_date = metadata[name].get("build_date")
                    template.last_update = metadata[name].get("last_update")
                    template.vmid = metadata[name].get("vmid")
                
                self.templates[name] = template
                
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"Failed to load templates: {e}")
            sys.exit(1)

    def save_metadata(self):
        """Save template metadata to file."""
        metadata = {
            name: {
                "build_date": template.build_date,
                "last_update": template.last_update,
                "vmid": template.vmid
            }
            for name, template in self.templates.items()
        }
        
        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    def get_template_path(self, template: Template) -> Path:
        """Get the path where the template should be stored."""
        return self.template_dir / f"{template.name}.qcow2"

    def download_image(self, template: Template, build_dir: Path) -> Path:
        """Download or copy template image."""
        image_path = build_dir / f"{template.name}.qcow2"
        template_path = self.get_template_path(template)
        
        # If template exists locally and we're updating, use existing file
        if template_path.exists() and template.image_url:
            self.logger.info(f"Using existing template file for {template.name}")
            shutil.copy2(template_path, image_path)
            return image_path
        
        # Otherwise download new image
        if template.image_url:
            self.logger.info(f"Downloading image for {template.name}")
            try:
                response = requests.get(template.image_url, stream=True, timeout=30)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                
                with self.progress as progress:
                    task_id = progress.add_task(
                        f"Downloading {template.name}",
                        total=max(total_size, DOWNLOAD_TIMEOUT) if total_size else DOWNLOAD_TIMEOUT
                    )
                    
                    start_time = time.time()
                    downloaded = 0
                    
                    with open(image_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if time.time() - start_time > DOWNLOAD_TIMEOUT:
                                raise TimeoutError(f"Download timeout after {DOWNLOAD_TIMEOUT} seconds")
                            
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size:
                                progress.update(task_id, completed=downloaded)
                            else:
                                elapsed = int(time.time() - start_time)
                                progress.update(task_id, completed=min(elapsed, DOWNLOAD_TIMEOUT))
                    
                    progress.remove_task(task_id)
                    return image_path
                    
            except Exception as e:
                self.logger.error(f"Failed to download image for {template.name}: {e}")
                if image_path.exists():
                    image_path.unlink()
                raise
        else:
            # Copy existing template to working directory
            shutil.copy2(template_path, image_path)
            return image_path

    def customize_image(self, template: Template, image_path: Path) -> None:
        """Customize the image using virt-customize with timeout and progress indication."""
        self.logger.info(f"Customizing image for {template.name}")
        
        with self.progress as progress:
            task_id = progress.add_task(f"Customizing {template.name}", total=CUSTOMIZE_TIMEOUT)
            
            commands = []
            if template.update_packages:
                commands.extend(["--update"])
            
            if template.install_packages:
                commands.extend(["--install", ",".join(template.install_packages)])
            
            for cmd in template.run_commands:
                commands.extend(["--run-command", cmd])

            if template.ssh_password_auth:
                commands.extend([
                    "--run-command", 
                    "sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config"
                ])

            if template.ssh_root_login:
                commands.extend([
                    "--run-command",
                    "sed -i 's/^#*PermitRootLogin .*/PermitRootLogin yes/' /etc/ssh/sshd_config"
                ])

            process = None
            try:
                # Start the customization process
                process = subprocess.Popen(
                    ["virt-customize", "-a", str(image_path)] + commands,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                start_time = time.time()
                while process.poll() is None:
                    elapsed = int(time.time() - start_time)
                    if elapsed >= CUSTOMIZE_TIMEOUT:
                        process.kill()
                        raise TimeoutError(f"Customization timeout after {CUSTOMIZE_TIMEOUT} seconds")
                    
                    progress.update(task_id, completed=min(elapsed, CUSTOMIZE_TIMEOUT))
                    time.sleep(1)
                
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(
                        process.returncode,
                        ["virt-customize"],
                        output=process.stdout.read() if process.stdout else None,
                        stderr=process.stderr.read() if process.stderr else None
                    )
                
                # Complete the progress bar
                progress.update(task_id, completed=CUSTOMIZE_TIMEOUT)
                
                # Update build information after successful customization
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if template.build_date:
                    template.last_update = current_time
                else:
                    template.build_date = current_time

                self.save_metadata()  # Save after each successful template build
                
            except Exception as e:
                self.logger.error(f"Failed to customize image for {template.name}: {str(e)}")
                if process and process.poll() is None:
                    process.kill()
                raise
            finally:
                progress.remove_task(task_id)

class ProxmoxManager:
    def __init__(self, storage: str = "local", min_vmid: int = 9000):
        self.storage = storage
        self.min_vmid = min_vmid
        self.logger = logging.getLogger("cloudbuilder")
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(complete_style="green"),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            expand=True,
            transient=False
        )
        
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
            for vm in json.loads(result.stdout):
                if vm.get("template") == 1:
                    templates[vm["name"]] = vm["vmid"]
            return templates
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get existing templates: {e.stderr if e.stderr else e}")
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Proxmox response: {e}")
            return {}

    def add_template_note(self, vmid: int, template: Template, is_update: bool = False) -> None:
        """Add or update template description with build information."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if is_update:
            template.last_update = current_time
            note = (f"Template built: {template.build_date}\n"
                   f"Last updated: {current_time}")
        else:
            template.build_date = current_time
            note = f"Template built: {current_time}"
        
        try:
            subprocess.run([
                "qm", "set", str(vmid),
                "--description", note
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to set template note: {e.stderr}")

    def import_template(self, template: Template, image_path: Path, is_update: bool = False) -> None:
        """Import template into Proxmox."""
        self.logger.info(f"Importing template: {template.name}")
        
        with self.progress as progress:
            task_id = progress.add_task(f"Importing {template.name}")
            
            try:
                # Verify existing VMID if we have one
                vmid = template.vmid
                if vmid:
                    try:
                        # Check if VM exists and belongs to this template
                        result = subprocess.run(
                            ["qm", "status", str(vmid)],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        
                        # Also verify the VM name matches our template
                        vm_info = subprocess.run(
                            ["qm", "config", str(vmid)],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        if template.name not in vm_info.stdout:
                            self.logger.warning(f"VMID {vmid} exists but belongs to different template, will assign new ID")
                            vmid = None
                            template.vmid = None
                    except subprocess.CalledProcessError:
                        self.logger.warning(f"Template {template.name} with VMID {vmid} not found, will assign new ID")
                        vmid = None
                        template.vmid = None
                
                # Get new VMID if needed
                if not vmid:
                    vmid = self._get_next_vmid()
                    template.vmid = vmid
                    
                self.logger.debug(f"Using VMID {vmid} for template {template.name}")
                
                # Create VM
                subprocess.run([
                    "qm", "create", str(vmid),
                    "--memory", "1024",
                    "--net0", "virtio,bridge=vmbr0",
                    "--name", template.name,
                    "--agent", "enabled=1"
                ], check=True, capture_output=True)

                # Import disk
                subprocess.run([
                    "qm", "importdisk", str(vmid), str(image_path), self.storage
                ], check=True, capture_output=True)

                # Configure VM
                subprocess.run([
                    "qm", "set", str(vmid),
                    "--scsihw", "virtio-scsi-pci",
                    "--scsi0", f"{self.storage}:vm-{vmid}-disk-0,discard=on",
                    "--ide2", f"{self.storage}:cloudinit",
                    "--boot", "c",
                    "--bootdisk", "scsi0",
                    "--serial0", "socket",
                    "--vga", "serial0",
                    "--cpu", "host"
                ], check=True, capture_output=True)

                # Add build/update information
                self.add_template_note(vmid, template, is_update)

                # Convert to template
                subprocess.run(
                    ["qm", "template", str(vmid)], 
                    check=True, 
                    capture_output=True
                )
                
                progress.remove_task(task_id)
                
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to import template {template.name}: {e.stderr}")
                # Only cleanup if we created the VM and it failed
                if "already exists" not in str(e.stderr):
                    try:
                        subprocess.run(["qm", "destroy", str(vmid)], check=True)
                    except subprocess.CalledProcessError:
                        pass  # Ignore cleanup errors
                raise

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
        
    
def main():
    console.print("[bold blue]Proxmox Template Builder[/bold blue]")
    parser = argparse.ArgumentParser(description="Proxmox template builder")
    parser.add_argument("--config", default="templates.json", help="Path to templates configuration file")
    parser.add_argument("--storage", default="local-zfs", help="Storage location in Proxmox")
    parser.add_argument("--template-dir", default="/root/cloudbuilder/templates", help="Directory for storing templates")
    parser.add_argument("--temp-dir", default="/root/cloudbuilder/tmp", help="Base directory for temporary files")
    parser.add_argument("--log-dir", default="/root/cloudbuilder", help="Directory for log files")
    parser.add_argument("--import", action="store_true", dest="import_templates", help="Import built templates to Proxmox")
    parser.add_argument("--update", action="store_true", help="Update existing templates")
    parser.add_argument("--replace", action="store_true", help="Replace existing templates")
    parser.add_argument("--min-vmid", type=int, default=9000, help="Minimum VMID for templates")
    args = parser.parse_args()

    # Setup logging
    log_dir = Path(args.log_dir)
    logger = setup_logging(log_dir)

    # Initialize directories
    template_dir = Path(args.template_dir)
    temp_base = Path(args.temp_dir)
    temp_base.mkdir(parents=True, exist_ok=True)
    
    # Initialize temp directory manager
    temp_manager = TempDirManager(temp_base)

    try:
        console.print(f"[green]Loading configuration from: {args.config}[/green]")
        builder = TemplateBuilder(args.config, template_dir, temp_manager, args.storage)
        builder.load_templates()
        console.print(f"[green]Found {len(builder.templates)} templates in configuration[/green]")
        
        proxmox = ProxmoxManager(args.storage, args.min_vmid)
        existing_proxmox_templates = proxmox.get_existing_templates()

        # Create temporary build directory
        build_dir = temp_manager.create_temp_dir()

        for name, template in builder.templates.items():
            try:
                template_path = builder.get_template_path(template)
                template_exists_locally = template_path.exists() and template.build_date is not None
                template_exists_in_proxmox = name in existing_proxmox_templates
                
                if template_exists_in_proxmox:
                    template.vmid = existing_proxmox_templates[name]
                
                # Standard build mode (no --import)
                if not args.import_templates:
                    if template_exists_locally and not args.update and not args.replace:
                        logger.info(f"Skipping existing template: {name}")
                        continue
                    
                    if args.replace:
                        logger.info(f"Replacing template: {name}")
                    elif args.update:
                        logger.info(f"Updating template: {name}")
                    else:
                        logger.info(f"Building new template: {name}")
                
                # Import mode
                else:
                    if template_exists_locally and template_exists_in_proxmox and not args.update and not args.replace:
                        logger.info(f"Skipping existing template in Proxmox and local storage: {name}")
                        continue
                    
                    if not template_exists_locally:
                        logger.info(f"Template {name} missing locally, building first")
                    elif not template_exists_in_proxmox:
                        logger.info(f"Template {name} missing in Proxmox, importing")
                    elif args.update:
                        logger.info(f"Updating template: {name}")
                    elif args.replace:
                        logger.info(f"Replacing template: {name}")
                
                # Build/update template in temporary directory
                image_path = builder.download_image(template, build_dir)
                builder.customize_image(template, image_path)
                
                # Import to Proxmox if requested
                if args.import_templates:
                    if template_exists_in_proxmox and (args.update or args.replace):
                        try:
                            subprocess.run(
                                ["qm", "destroy", str(template.vmid)], 
                                check=True,
                                capture_output=True
                            )
                        except subprocess.CalledProcessError as e:
                            if "does not exist" not in str(e.stderr):
                                raise
                            logger.warning(f"Template {name} with VMID {template.vmid} not found, will create new one")
                            template.vmid = None
                    
                    proxmox.import_template(template, image_path, is_update=args.update)
                
                # If build successful and not in replace mode, copy to template directory
                if not args.replace:
                    shutil.copy2(image_path, template_path)
                    builder.save_metadata()  # Save metadata after successful copy
                
                logger.info(f"Successfully processed template: {name}")

            except Exception as e:
                logger.error(f"Failed to process template {name}: {e}")
                continue

        # Final metadata save after processing
        builder.save_metadata()
        logger.info("Template processing completed")

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        sys.exit(1)
    finally:
        # Cleanup temporary directories
        temp_manager.cleanup()

if __name__ == "__main__":
    main()