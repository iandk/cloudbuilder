#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
# cloudbuilder.py
from rich.table import Table
import argparse
import json
import logging
import sys
from pathlib import Path

try:
    import argcomplete
    ARGCOMPLETE_AVAILABLE = True
except ImportError:
    ARGCOMPLETE_AVAILABLE = False

from rich.console import Console
from rich.logging import RichHandler

from template import TemplateManager
from proxmox import ProxmoxManager
from utils import setup_logging, parse_template_list, get_installation_paths, validate_template_selection, self_update, setup_shell_completions

console = Console()


def main():
    """Main entry point for the cloudbuilder application."""
    # Get standard paths
    paths = get_installation_paths()

    parser = argparse.ArgumentParser(description="Proxmox Template Builder")

    # Core behavior arguments
    parser.add_argument("--update", action="store_true", help="Update existing templates")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild templates from scratch")
    parser.add_argument("--status", action="store_true", help="Show template status without making changes")
    parser.add_argument("--self-update", action="store_true", help="Update cloudbuilder from git repository")
    parser.add_argument("--setup-completions", action="store_true", help="Set up shell autocompletions")
    parser.add_argument("--import-manifest", dest="import_manifest", metavar="FILE",
                        help="Import pre-built images from a manifest file (JSON with source paths/URLs)")
    parser.add_argument("--generate-manifest", dest="generate_manifest", metavar="DIR",
                        help="Generate a manifest JSON from a directory of qcow2/img files")
    parser.add_argument("--base-url", dest="base_url", metavar="URL",
                        help="Base URL to prefix sources in generated manifest (use with --generate-manifest)")
    parser.add_argument("-o", "--output", dest="output_file", metavar="FILE",
                        help="Output file for generated manifest (default: imports.json, use '-' for stdout)")
    parser.add_argument("--force", action="store_true",
                        help="Force import even if template already exists in Proxmox (removes and re-imports)")

    # Template selection arguments
    parser.add_argument("--only", help="Process only specified templates (comma-separated list)")
    parser.add_argument("--except", dest="exclude", help="Process all templates except those specified (comma-separated list)")

    # Configuration arguments
    parser.add_argument("--config", default=str(paths['config_file']), help="Path to templates configuration file")
    parser.add_argument("--storage", default=None, help="Storage location in Proxmox (if not specified, will auto-detect)")
    parser.add_argument("--template-dir", default=str(paths['template_dir']), help="Directory for storing templates")
    parser.add_argument("--temp-dir", default=str(paths['temp_dir']), help="Base directory for temporary files")
    parser.add_argument("--log-dir", default=str(paths['log_dir']), help="Directory for log files")
    parser.add_argument("--min-vmid", type=int, default=9000, help="Minimum VMID for templates")

    # Enable shell autocompletion if argcomplete is available
    if ARGCOMPLETE_AVAILABLE:
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    # Handle generate manifest early (before logging setup)
    if args.generate_manifest:
        source_dir = Path(args.generate_manifest)
        if not source_dir.exists():
            print(f"Error: Directory not found: {source_dir}", file=sys.stderr)
            sys.exit(1)
        if not source_dir.is_dir():
            print(f"Error: Not a directory: {source_dir}", file=sys.stderr)
            sys.exit(1)

        # Find all qcow2 and img files
        image_files = list(source_dir.glob("*.qcow2")) + list(source_dir.glob("*.img"))
        if not image_files:
            print(f"Error: No .qcow2 or .img files found in {source_dir}", file=sys.stderr)
            sys.exit(1)

        # Build manifest
        manifest = {}
        base_url = args.base_url.rstrip('/') if args.base_url else None

        for image_path in sorted(image_files):
            # Use filename without extension as template name
            name = image_path.stem

            if base_url:
                source = f"{base_url}/{image_path.name}"
            else:
                source = str(image_path.absolute())

            manifest[name] = {"source": source}

        # Output JSON
        json_output = json.dumps(manifest, indent=2)

        # Default output file is imports.json in the source directory
        if args.output_file:
            output_file = args.output_file
        else:
            output_file = str(source_dir / "imports.json")

        if output_file == "-":
            # Output to stdout
            print(json_output)
        else:
            # Write to file
            with open(output_file, 'w') as f:
                f.write(json_output + '\n')
            print(f"Generated manifest with {len(manifest)} templates: {output_file}", file=sys.stderr)

        sys.exit(0)

    # Setup logging
    logger = setup_logging(Path(args.log_dir))

    # Log the main header rather than using console.print
    logger.info("Proxmox Template Builder")

    # Handle self-update early and exit
    if args.self_update:
        success = self_update(paths['install_dir'], logger)
        sys.exit(0 if success else 1)

    # Handle shell completions setup and exit
    if args.setup_completions:
        success = setup_shell_completions(logger)
        sys.exit(0 if success else 1)

    # Handle import manifest
    if args.import_manifest:
        manifest_source = args.import_manifest
        is_url = manifest_source.startswith('http://') or manifest_source.startswith('https://')

        if is_url:
            # Fetch manifest from URL
            import requests
            try:
                logger.info(f"Fetching manifest from {manifest_source}")
                response = requests.get(manifest_source, timeout=30)
                response.raise_for_status()
                manifest = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch manifest from URL: {e}")
                sys.exit(1)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in manifest: {e}")
                sys.exit(1)
        else:
            # Load from local file
            manifest_path = Path(manifest_source)
            if not manifest_path.exists():
                logger.error(f"Manifest file not found: {manifest_path}")
                sys.exit(1)
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in manifest file: {e}")
                sys.exit(1)

        if not manifest:
            logger.warning("Manifest file is empty")
            sys.exit(0)

        # Parse template filtering for imports
        import_include = parse_template_list(args.only) if args.only else None
        import_exclude = parse_template_list(args.exclude) if args.exclude else []

        # Filter manifest entries
        filtered_manifest = {}
        for name, config in manifest.items():
            if import_include is not None and name not in import_include:
                continue
            if name in import_exclude:
                continue
            filtered_manifest[name] = config

        if not filtered_manifest:
            logger.warning("No templates selected for import after filtering")
            sys.exit(0)

        logger.info(f"Importing {len(filtered_manifest)} template(s) from manifest")

        # Initialize directories and managers
        template_dir = Path(args.template_dir)
        temp_dir = Path(args.temp_dir)
        template_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        template_manager = TemplateManager(
            config_path=args.config,
            template_dir=template_dir,
            temp_dir=temp_dir,
            storage=args.storage
        )

        proxmox_manager = ProxmoxManager(
            storage=args.storage,
            min_vmid=args.min_vmid
        )

        # Load existing templates for customization support
        try:
            template_manager.load_templates()
        except Exception:
            pass  # Config might not exist, that's okay for imports

        proxmox_templates = proxmox_manager.get_existing_templates()

        # Process each import
        success_count = 0
        for name, config in filtered_manifest.items():
            try:
                source = config.get("source")
                if not source:
                    logger.error(f"Template '{name}' missing required 'source' field")
                    continue

                vmid = config.get("vmid")
                customize = config.get("customize", False)

                # Check if template already exists in Proxmox
                existing_vmid = proxmox_templates.get(name)
                if existing_vmid:
                    if not args.force:
                        logger.warning(f"Template '{name}' already exists in Proxmox (VMID: {existing_vmid}), skipping (use --force to overwrite)")
                        continue

                    # Force mode: check for linked clones before removing
                    logger.info(f"Template '{name}' exists (VMID: {existing_vmid}), force mode enabled - will replace")
                    if proxmox_manager.check_for_linked_clones(existing_vmid):
                        logger.error(f"Cannot force import '{name}': template has linked clones. Remove linked VMs first.")
                        continue

                    # Create a temporary template object with the existing VMID for removal
                    from template import Template
                    existing_template = Template(
                        name=name,
                        image_url="",
                        install_packages=[],
                        update_packages=False,
                        run_commands=[],
                        ssh_password_auth=False,
                        ssh_root_login=False,
                        vmid=existing_vmid
                    )
                    logger.info(f"Removing existing template '{name}' (VMID: {existing_vmid})")
                    proxmox_manager.remove_template(existing_template)

                    # Reuse the existing VMID if not explicitly specified in manifest
                    if vmid is None:
                        vmid = existing_vmid
                        logger.info(f"Reusing VMID {vmid} for '{name}'")

                # Import the template from source
                template = template_manager.import_from_source(name, source, vmid)

                # Optionally customize if requested and config exists
                if customize and name in template_manager.templates:
                    config_template = template_manager.templates[name]
                    if config_template.install_packages or config_template.run_commands:
                        logger.info(f"Customizing imported template '{name}'")
                        image_path = template_manager.get_template_path(template)
                        template_manager.customize_image(config_template, image_path)
                        # Update the template object with customization settings
                        template.install_packages = config_template.install_packages
                        template.run_commands = config_template.run_commands
                        template_manager.save_metadata()

                # Import to Proxmox
                image_path = template_manager.get_template_path(template)
                proxmox_manager.import_template(template, image_path, is_update=False)

                # Update metadata with assigned VMID
                template_manager.templates[name] = template
                template_manager.save_metadata()

                logger.info(f"Successfully imported template '{name}' (VMID: {template.vmid})")
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to import template '{name}': {e}", exc_info=True)
                continue

        logger.info(f"Import complete: {success_count}/{len(filtered_manifest)} templates imported successfully")
        sys.exit(0 if success_count == len(filtered_manifest) else 1)

    # Parse template selection
    process_all = True
    include_templates = []
    exclude_templates = []

    if args.only:
        process_all = False
        include_templates = parse_template_list(args.only)
        logger.info(f"Processing only templates: {', '.join(include_templates)}")

    if args.exclude:
        exclude_templates = parse_template_list(args.exclude)
        logger.info(f"Excluding templates: {', '.join(exclude_templates)}")

    # Initialize directories
    template_dir = Path(args.template_dir)
    temp_dir = Path(args.temp_dir)
    template_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Initialize managers
        template_manager = TemplateManager(
            config_path=args.config,
            template_dir=template_dir,
            temp_dir=temp_dir,
            storage=args.storage
        )

        proxmox_manager = ProxmoxManager(
            storage=args.storage,
            min_vmid=args.min_vmid
        )

        # Load templates and get Proxmox status
        template_manager.load_templates()
        proxmox_templates = proxmox_manager.get_existing_templates()

        # Validate template selection first
        if args.only or args.exclude:
            # Verify that all specified templates exist
            validate_template_selection(
                logger=logger,
                available_templates=template_manager.templates,
                include_templates=include_templates if args.only else None,
                exclude_templates=exclude_templates if args.exclude else None
            )

        # Synchronize metadata with Proxmox state
        template_manager.sync_metadata_with_proxmox(proxmox_templates)

        # Then apply template filtering
        filtered_templates = {}
        for name, template in template_manager.templates.items():
            if (process_all or name in include_templates) and name not in exclude_templates:
                filtered_templates[name] = template

                # Update VMID if template exists in Proxmox (already done by sync_metadata_with_proxmox)
                # if name in proxmox_templates:
                #     template.vmid = proxmox_templates[name]

        if not filtered_templates:
            logger.warning("No templates selected for processing!")
            return

        if not args.status:  # Don't do this check if only showing status
            templates_with_clones = []
            for name, template in filtered_templates.items():
                is_candidate_for_update_rebuild = (args.update or args.rebuild) and name in proxmox_templates
                if is_candidate_for_update_rebuild and template.vmid:
                    logger.debug(f"Pre-checking template {name} (VMID: {template.vmid}) for linked clones.")
                    if proxmox_manager.check_for_linked_clones(template.vmid):
                        templates_with_clones.append(name)

            if templates_with_clones:
                logger.error("Aborting operation. The following templates scheduled for update/rebuild have linked clones:")
                for cloned_name in templates_with_clones:
                    logger.error(f"  - {cloned_name} (VMID: {template_manager.templates[cloned_name].vmid})")
                logger.error("Please resolve this by detaching or removing the linked VMs before proceeding.")
                sys.exit(1)
            else:
                logger.info("Linked clone pre-check passed for all selected templates requiring update/rebuild.")

        # Status only mode
        if args.status:
            logger.info("Template Status")

            status_table = Table(show_header=True, header_style="bold", box=None)
            status_table.add_column("Template", style="cyan")
            status_table.add_column("Local")
            status_table.add_column("Proxmox")
            status_table.add_column("VMID")
            status_table.add_column("Build Date")
            status_table.add_column("Last Update")

            for name, template in filtered_templates.items():
                local_status = "[green]✓[/green]" if template_manager.template_exists_locally(template) else "[red]✗[/red]"
                proxmox_status = "[green]✓[/green]" if name in proxmox_templates else "[red]✗[/red]"
                vmid = str(template.vmid) if template.vmid else "—"
                build_date = template.build_date if template.build_date else "—"
                last_update = template.last_update if template.last_update else "—"

                status_table.add_row(
                    name, local_status, proxmox_status, vmid,
                    build_date, last_update
                )

            # Print table with console to keep formatting
            console.print(status_table)
            return

        # First, build all templates locally
        built_templates = {}

        for name, template in filtered_templates.items():
            try:
                exists_locally = template_manager.template_exists_locally(template)
                exists_in_proxmox = name in proxmox_templates

                # Determine build action based on flags
                if args.rebuild:
                    logger.info(f"Building new version of template: {name}")
                    image_path = template_manager.build_template(template, force=True)
                    built_templates[name] = (template, image_path, exists_in_proxmox)

                elif args.update:
                    if exists_locally or exists_in_proxmox:
                        logger.info(f"Building updated version of template: {name}")
                        image_path = template_manager.build_template(template, update=True)
                        built_templates[name] = (template, image_path, exists_in_proxmox)
                    else:
                        logger.info(f"Template {name} doesn't exist yet, creating it")
                        image_path = template_manager.build_template(template)
                        built_templates[name] = (template, image_path, False)

                else:
                    # Default behavior: ensure templates exist both locally and in Proxmox
                    if not exists_locally:
                        logger.info(f"Template {name} missing locally, building it")
                        image_path = template_manager.build_template(template)
                        built_templates[name] = (template, image_path, exists_in_proxmox)
                    else:
                        logger.info(f"Template {name} exists locally")
                        image_path = template_manager.get_template_path(template)

                        if not exists_in_proxmox:
                            logger.info(f"Template {name} exists locally but missing in Proxmox")
                            built_templates[name] = (template, image_path, False)
                        else:
                            logger.info(f"Template {name} exists in Proxmox (VMID: {template.vmid})")
                            # Ensure firewall settings are correct for existing templates
                            proxmox_manager.ensure_firewall_settings(template.vmid, name)

                template_manager.save_metadata()

            except Exception as e:
                logger.error(f"Failed to build template {name}: {e}", exc_info=True)
                continue

        # Then, import/update templates in Proxmox one by one
        for name, (template, image_path, exists_in_proxmox) in built_templates.items():
            try:
                # If a template is being imported and already exists in Proxmox, it's an overwrite.
                is_overwrite_operation = exists_in_proxmox

                if is_overwrite_operation:
                    logger.info(f"Preparing to overwrite existing template {name} (VMID: {template.vmid}) in Proxmox.")
                    # Upfront check should have caught linked clones. Now safe to remove.
                    logger.info(f"Removing existing template {name} (VMID: {template.vmid}) from Proxmox before import.")
                    proxmox_manager.remove_template(template)

                # The is_update flag for import_template now primarily informs metadata handling within add_template_metadata
                # True if args.update was passed, False otherwise (e.g. for rebuilds or new installs)
                metadata_update_flag = args.update

                logger.info(f"Importing template {name} to Proxmox (Metadata Update: {metadata_update_flag})")
                proxmox_manager.import_template(template, image_path, is_update=metadata_update_flag)

                # Make sure the template in the template_manager is updated with the VMID
                template_manager.templates[name].vmid = template.vmid
                template_manager.save_metadata()

                logger.info(f"Successfully processed template: {name}")

            except Exception as e:
                logger.error(f"Failed to import template {name} to Proxmox: {e}", exc_info=True)
                continue

        logger.info("Template processing completed")

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
