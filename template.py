# template.py
#!/usr/bin/env python3

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TaskProgressColumn,
    TimeRemainingColumn
)

console = Console()

# Constants
DOWNLOAD_TIMEOUT = 600  # 10 minutes timeout for downloads
CUSTOMIZE_TIMEOUT = 600  # 10 minutes timeout for customization

@dataclass
class Template:
    """Template data model."""
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

class TemplateManager:
    """Manages template loading, building, and metadata."""
    
    def __init__(self, config_path: str, template_dir: Path, temp_dir: Path, storage: Optional[str] = None):
        self.config_path = config_path
        self.template_dir = template_dir
        self.temp_dir = temp_dir
        self.storage = storage  # This might be None initially and set later
        self.templates: Dict[str, Template] = {}
        self.logger = logging.getLogger("cloudbuilder")
        self.metadata_file = template_dir / "metadata.json"
        
        # Create template directory if it doesn't exist
        self.template_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize progress bar
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

    def load_templates(self) -> None:
        """Load templates from configuration file and metadata."""
        try:
            with open(self.config_path) as f:
                config = json.load(f)
            
            # Load existing metadata if available
            metadata = {}
            if self.metadata_file.exists():
                try:
                    with open(self.metadata_file) as f:
                        metadata = json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning(f"Metadata file corrupt, ignoring: {self.metadata_file}")
            
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
                
            self.logger.info(f"Loaded {len(self.templates)} templates from {self.config_path}")
            
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"Failed to load templates: {e}")
            raise

    def save_metadata(self) -> None:
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
        
        self.logger.debug(f"Saved metadata to {self.metadata_file}")

    def get_template_path(self, template: Template) -> Path:
        """Get the path where the template should be stored."""
        return self.template_dir / f"{template.name}.qcow2"

    def template_exists_locally(self, template: Template) -> bool:
        """Check if template exists locally."""
        template_path = self.get_template_path(template)
        return template_path.exists() and template.build_date is not None

    def download_image(self, template: Template, use_existing: bool = False) -> Path:
        """Download template image to temporary directory."""
        temp_file = self.temp_dir / f"{template.name}.qcow2"
        template_path = self.get_template_path(template)
        
        # If template exists locally and use_existing is True, use existing file
        if use_existing and template_path.exists():
            self.logger.info(f"Using existing template file for {template.name}")
            shutil.copy2(template_path, temp_file)
            return temp_file
        
        # Otherwise download new image
        self.logger.info(f"Downloading image for {template.name}")
        try:
            # First check if the URL is accessible
            head_response = requests.head(template.image_url, timeout=30)
            head_response.raise_for_status()
            
            response = requests.get(template.image_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            with console.status(f"Downloading {template.name}", spinner="dots") as status:
                start_time = time.time()
                downloaded = 0
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if time.time() - start_time > DOWNLOAD_TIMEOUT:
                            raise TimeoutError(f"Download timeout after {DOWNLOAD_TIMEOUT} seconds")
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                
                return temp_file
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to download image for {template.name} from {template.image_url}: {e}")
            if temp_file.exists():
                temp_file.unlink()
                
            # If download fails but we have a local template, use it as fallback
            if template_path.exists():
                self.logger.warning(f"Download failed, using existing local template as fallback for {template.name}")
                shutil.copy2(template_path, temp_file)
                return temp_file
            raise
        except Exception as e:
            self.logger.error(f"Failed to download image for {template.name}: {e}")
            if temp_file.exists():
                temp_file.unlink()
            raise
    
    def customize_image(self, template: Template, image_path: Path, update_mode: bool = False) -> None:
        """Customize the image using virt-customize with a simple status indicator."""
        self.logger.info(f"Customizing image for {template.name}")
        
        commands = []
        if template.update_packages or update_mode:
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
            self.logger.debug(f"Running virt-customize on {image_path}")
            
            # Use console.status instead of progress bar
            with console.status(f"Customizing {template.name}", spinner="dots") as status:
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
                    time.sleep(1)
                
                stdout, stderr = process.communicate()
                
                if process.returncode != 0:
                    error_msg = f"virt-customize failed with code {process.returncode}: {stderr}"
                    self.logger.error(error_msg)
                    raise RuntimeError(error_msg)
            
            # Update build information after successful customization
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if update_mode and template.build_date:
                template.last_update = current_time
            else:
                template.build_date = current_time
            
        except Exception as e:
            self.logger.error(f"Failed to customize image for {template.name}: {str(e)}")
            if process and process.poll() is None:
                process.kill()
            raise

    def build_template(self, template: Template, update: bool = False, force: bool = False) -> Path:
        """Build template and return the path to the built image."""
        use_existing = not force and self.template_exists_locally(template)
        image_path = self.download_image(template, use_existing=use_existing)
        self.customize_image(template, image_path, update_mode=update)
        
        # Copy finished image to template directory
        template_path = self.get_template_path(template)
        shutil.copy2(image_path, template_path)
        
        # Save metadata after successful build
        self.save_metadata()
        
        return template_path

    def sync_metadata_with_proxmox(self, proxmox_templates: Dict[str, int]) -> None:
        """
        Synchronize template metadata with actual Proxmox state.
        
        Args:
            proxmox_templates: Dictionary mapping template names to VMIDs
        """
        self.logger.info("Synchronizing metadata with Proxmox state")
        
        # Track which VMIDs are assigned to which templates in Proxmox
        vmid_to_template = {}
        for name, vmid in proxmox_templates.items():
            vmid_to_template[vmid] = name
        
        # Check for templates with incorrect VMIDs and fix them
        for name, template in self.templates.items():
            # If template exists in Proxmox, make sure VMID matches
            if name in proxmox_templates:
                actual_vmid = proxmox_templates[name]
                if template.vmid != actual_vmid:
                    self.logger.warning(
                        f"Template {name} has incorrect VMID in metadata: {template.vmid} vs actual {actual_vmid}"
                    )
                    template.vmid = actual_vmid
            # If template doesn't exist in Proxmox but has a VMID
            elif template.vmid is not None:
                # Check if this VMID is used by a different template in Proxmox
                if template.vmid in vmid_to_template:
                    other_template = vmid_to_template[template.vmid]
                    self.logger.warning(
                        f"Template {name} claims VMID {template.vmid} but that VMID belongs to {other_template}"
                    )
                    # Clear the VMID since this template doesn't exist in Proxmox
                    template.vmid = None
        
        # Save the synchronized metadata
        self.save_metadata()
        self.logger.info("Metadata synchronized successfully")