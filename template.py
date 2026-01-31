# template.py
#!/usr/bin/env python3

import json
import logging
import lzma
import os
import re
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
DOWNLOAD_TIMEOUT = 600   # 10 minutes timeout for downloads
CUSTOMIZE_TIMEOUT = 1800  # 30 minutes timeout for customization (includes package updates + installs)

# Proxmox VM naming rules
PROXMOX_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')
PROXMOX_NAME_MAX_LENGTH = 63


def validate_template_name(name: str) -> None:
    """
    Validate template name against Proxmox VM naming rules.

    Proxmox requires:
    - Alphanumeric characters, hyphens, underscores, and periods only
    - Cannot start with a hyphen
    - Maximum 63 characters

    Raises:
        ValueError: If the name is invalid
    """
    if not name:
        raise ValueError("Template name cannot be empty")

    if len(name) > PROXMOX_NAME_MAX_LENGTH:
        raise ValueError(
            f"Template name '{name}' is too long ({len(name)} chars). "
            f"Maximum is {PROXMOX_NAME_MAX_LENGTH} characters."
        )

    if not PROXMOX_NAME_PATTERN.match(name):
        raise ValueError(
            f"Template name '{name}' contains invalid characters. "
            f"Only alphanumeric, hyphen, underscore, and period are allowed. "
            f"Name cannot start with a hyphen."
        )


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
    min_size: Optional[str] = None  # Minimum disk size (e.g., "1G", "500M")
    copy_files: Optional[Dict[str, str]] = None  # Local path -> destination path mapping
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

    def _resolve_template(self, name: str, template_config: dict, components: dict) -> dict:
        """
        Resolve component references and merge into final template config.

        Components are applied in order, then template's own values are appended.
        - install_packages: concatenated in order
        - run_commands: concatenated in order
        - copy_files: merged (later values override earlier)
        """
        resolved = {
            "install_packages": [],
            "run_commands": [],
            "copy_files": {}
        }

        # Apply components in order
        for comp_name in template_config.get("uses", []):
            if comp_name not in components:
                raise ValueError(f"Template '{name}' references unknown component '{comp_name}'")
            comp = components[comp_name]
            resolved["install_packages"].extend(comp.get("install_packages", []))
            resolved["run_commands"].extend(comp.get("run_commands", []))
            if comp.get("copy_files"):
                resolved["copy_files"].update(comp["copy_files"])

        # Apply template's own values (appended after components)
        resolved["install_packages"].extend(template_config.get("install_packages", []))
        resolved["run_commands"].extend(template_config.get("run_commands", []))
        if template_config.get("copy_files"):
            resolved["copy_files"].update(template_config["copy_files"])

        # Copy non-mergeable fields directly from template
        for key in ["image_url", "update_packages", "ssh_password_auth", "ssh_root_login", "min_size"]:
            if key in template_config:
                resolved[key] = template_config[key]

        return resolved

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

            # Detect config format: new (with components/templates) or legacy (flat)
            if "components" in config and "templates" in config:
                # New format with components
                components = config["components"]
                templates_config = config["templates"]
                self.logger.debug(f"Using component-based config with {len(components)} components")
            else:
                # Legacy flat format - no components to resolve
                components = {}
                templates_config = config

            self.templates = {}
            for name, t in templates_config.items():
                # Validate template name against Proxmox naming rules
                validate_template_name(name)

                # Resolve component references if using new format
                if components or t.get("uses"):
                    t = self._resolve_template(name, t, components)

                template = Template(
                    name=name,
                    image_url=t["image_url"],
                    install_packages=t.get("install_packages", []),
                    update_packages=t.get("update_packages", False),
                    run_commands=t.get("run_commands", []),
                    ssh_password_auth=t.get("ssh_password_auth", False),
                    ssh_root_login=t.get("ssh_root_login", False),
                    min_size=t.get("min_size"),
                    copy_files=t.get("copy_files") if t.get("copy_files") else None
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

        # Check if URL points to a compressed file
        is_xz_compressed = template.image_url.endswith('.xz')
        download_file = self.temp_dir / f"{template.name}.qcow2.xz" if is_xz_compressed else temp_file

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

                with open(download_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if time.time() - start_time > DOWNLOAD_TIMEOUT:
                            raise TimeoutError(f"Download timeout after {DOWNLOAD_TIMEOUT} seconds")

                        f.write(chunk)
                        downloaded += len(chunk)

            # Decompress XZ file if needed
            if is_xz_compressed:
                self.logger.info(f"Decompressing XZ archive for {template.name}")
                with console.status(f"Decompressing {template.name}", spinner="dots"):
                    with lzma.open(download_file, 'rb') as xz_file:
                        with open(temp_file, 'wb') as out_file:
                            shutil.copyfileobj(xz_file, out_file)
                    # Remove the compressed file
                    download_file.unlink()

            return temp_file
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to download image for {template.name} from {template.image_url}: {e}")
            for f in [temp_file, download_file]:
                if f.exists():
                    f.unlink()

            # If download fails but we have a local template, use it as fallback
            if template_path.exists():
                self.logger.warning(f"Download failed, using existing local template as fallback for {template.name}")
                shutil.copy2(template_path, temp_file)
                return temp_file
            raise
        except Exception as e:
            self.logger.error(f"Failed to download image for {template.name}: {e}")
            for f in [temp_file, download_file]:
                if f.exists():
                    f.unlink()
            raise

    def resize_image_if_needed(self, template: Template, image_path: Path) -> None:
        """Resize the qcow2 image if it's smaller than the template's min_size."""
        if not template.min_size:
            return

        self.logger.info(f"Checking if {template.name} needs resizing to {template.min_size}")

        try:
            # Get current image size using qemu-img info
            result = subprocess.run(
                ["qemu-img", "info", "--output=json", str(image_path)],
                capture_output=True,
                text=True,
                check=True
            )
            info = json.loads(result.stdout)
            current_size = info.get("virtual-size", 0)

            # Parse min_size (e.g., "1G", "500M", "2048M")
            min_size_str = template.min_size.upper().strip()
            if min_size_str.endswith("G"):
                min_size_bytes = int(float(min_size_str[:-1]) * 1024 * 1024 * 1024)
            elif min_size_str.endswith("M"):
                min_size_bytes = int(float(min_size_str[:-1]) * 1024 * 1024)
            elif min_size_str.endswith("K"):
                min_size_bytes = int(float(min_size_str[:-1]) * 1024)
            else:
                # Assume bytes if no suffix
                min_size_bytes = int(min_size_str)

            if current_size < min_size_bytes:
                self.logger.info(
                    f"Resizing {template.name} from {current_size / (1024*1024*1024):.2f}G to {template.min_size}"
                )
                subprocess.run(
                    ["qemu-img", "resize", str(image_path), template.min_size],
                    capture_output=True,
                    text=True,
                    check=True
                )
                self.logger.info(f"Successfully resized {template.name} to {template.min_size}")
            else:
                self.logger.debug(
                    f"{template.name} already meets min_size ({current_size / (1024*1024*1024):.2f}G >= {template.min_size})"
                )
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to resize image for {template.name}: {e.stderr}")
            raise RuntimeError(f"Failed to resize image: {e.stderr}")
        except Exception as e:
            self.logger.error(f"Failed to resize image for {template.name}: {e}")
            raise

    def customize_image(self, template: Template, image_path: Path, update_mode: bool = False) -> None:
        """Customize the image using virt-customize with a simple status indicator."""

        # Check if there's anything to customize
        has_work = (
            template.update_packages or
            update_mode or
            template.install_packages or
            template.run_commands or
            template.copy_files or
            template.ssh_password_auth or
            template.ssh_root_login
        )

        if not has_work:
            self.logger.info(f"Skipping customization for {template.name} (no packages/commands defined)")
            # Still update build info
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            template.build_date = current_time
            template.last_update = None
            return

        self.logger.info(f"Customizing image for {template.name}")

        commands = []
        if template.update_packages or update_mode:
            commands.extend(["--update"])

        if template.install_packages:
            commands.extend(["--install", ",".join(template.install_packages)])

        # Copy files into the image (before run_commands so copied files are available)
        if template.copy_files:
            config_dir = Path(self.config_path).parent
            for local_path, dest_path in template.copy_files.items():
                # Resolve relative paths against the config directory
                source_path = Path(local_path)
                if not source_path.is_absolute():
                    source_path = config_dir / source_path
                source_path = source_path.resolve()

                if not source_path.exists():
                    raise FileNotFoundError(f"Copy source file not found: {source_path}")

                # Validate destination is a directory path (must end with /)
                if not dest_path.endswith('/'):
                    raise ValueError(
                        f"copy_files destination must be a directory (end with '/'): "
                        f"'{dest_path}' should be '{dest_path}/' or a directory like '/etc/'"
                    )

                # virt-customize --copy-in format: local_path:remote_dir
                commands.extend(["--copy-in", f"{source_path}:{dest_path}"])
                self.logger.debug(f"Will copy {source_path} to {dest_path} in image")

        for cmd in template.run_commands:
            commands.extend(["--run-command", cmd])

        # Preserve SSH host keys across cloud-init instance-id changes (e.g., Proxmox config regeneration)
        commands.extend([
            "--run-command",
            "mkdir -p /etc/cloud/cloud.cfg.d && echo 'ssh_deletekeys: false' > /etc/cloud/cloud.cfg.d/99-preserve-ssh-keys.cfg"
        ])

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
                        pkg_count = len(template.install_packages)
                        cmd_count = len(template.run_commands)
                        raise TimeoutError(
                            f"Customization of '{template.name}' timed out after {CUSTOMIZE_TIMEOUT // 60} minutes "
                            f"({pkg_count} packages, {cmd_count} commands). "
                            f"Consider increasing CUSTOMIZE_TIMEOUT or reducing package list."
                        )
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
                template.last_update = None  # Clear stale last_update on fresh build
            
        except Exception as e:
            self.logger.error(f"Failed to customize image for {template.name}: {str(e)}")
            if process and process.poll() is None:
                process.kill()
            raise

    def build_template(self, template: Template, update: bool = False, force: bool = False) -> Path:
        """Build template and return the path to the built image."""
        use_existing = not force and self.template_exists_locally(template)
        image_path = self.download_image(template, use_existing=use_existing)
        self.resize_image_if_needed(template, image_path)
        self.customize_image(template, image_path, update_mode=update)
        
        # Copy finished image to template directory
        template_path = self.get_template_path(template)
        shutil.copy2(image_path, template_path)
        
        # Save metadata after successful build
        self.save_metadata()
        
        return template_path

    def import_from_source(self, name: str, source: str, vmid: Optional[int] = None) -> 'Template':
        """
        Import a pre-built image from a local path or URL without customization.

        Args:
            name: Name for the template
            source: Local file path or HTTP(S) URL to the qcow2/img file
            vmid: Optional specific VMID to assign

        Returns:
            Template object with metadata populated
        """
        self.logger.info(f"Importing template '{name}' from {source}")

        template_path = self.template_dir / f"{name}.qcow2"
        is_url = source.startswith('http://') or source.startswith('https://')

        if is_url:
            # Download from URL
            self.logger.info(f"Downloading image for {name} from URL")
            try:
                head_response = requests.head(source, timeout=30, allow_redirects=True)
                head_response.raise_for_status()

                response = requests.get(source, stream=True, timeout=30)
                response.raise_for_status()

                with console.status(f"Downloading {name}", spinner="dots") as status:
                    start_time = time.time()
                    downloaded = 0

                    with open(template_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if time.time() - start_time > DOWNLOAD_TIMEOUT:
                                raise TimeoutError(f"Download timeout after {DOWNLOAD_TIMEOUT} seconds")
                            f.write(chunk)
                            downloaded += len(chunk)

                self.logger.info(f"Downloaded {downloaded} bytes for {name}")

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to download image for {name} from {source}: {e}")
                if template_path.exists():
                    template_path.unlink()
                raise
        else:
            # Copy from local path
            source_path = Path(source)
            if not source_path.exists():
                raise FileNotFoundError(f"Source file not found: {source}")

            if not source_path.is_file():
                raise ValueError(f"Source is not a file: {source}")

            self.logger.info(f"Copying local image for {name}")
            with console.status(f"Copying {name}", spinner="dots"):
                shutil.copy2(source_path, template_path)

        # Create template object with metadata
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        template = Template(
            name=name,
            image_url=source,  # Store original source for reference
            install_packages=[],
            update_packages=False,
            run_commands=[],
            ssh_password_auth=False,
            ssh_root_login=False,
            build_date=current_time,
            vmid=vmid
        )

        # Add to templates dict and save metadata
        self.templates[name] = template
        self.save_metadata()

        self.logger.info(f"Successfully imported template '{name}'")
        return template

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
                    if template.vmid is not None:
                        self.logger.warning(
                            f"Template {name} has incorrect VMID in metadata: {template.vmid} vs actual {actual_vmid}"
                        )
                    template.vmid = actual_vmid
            # If template doesn't exist in Proxmox but has a VMID in metadata
            elif template.vmid is not None:
                # Check if this VMID is used by a different template in Proxmox
                if template.vmid in vmid_to_template:
                    other_template = vmid_to_template[template.vmid]
                    self.logger.warning(
                        f"Template {name} claims VMID {template.vmid} but that VMID belongs to {other_template} - clearing stale VMID"
                    )
                else:
                    self.logger.warning(
                        f"Template {name} has VMID {template.vmid} in metadata but doesn't exist in Proxmox - clearing stale VMID"
                    )
                # Always clear the VMID since this template doesn't exist in Proxmox
                template.vmid = None
        
        # Save the synchronized metadata
        self.save_metadata()
        self.logger.info("Metadata synchronized successfully")
