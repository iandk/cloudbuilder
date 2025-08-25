#!/usr/bin/env python3
# cloudbuilder.py
from rich.table import Table
import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from template import TemplateManager
from proxmox import ProxmoxManager
from utils import setup_logging, parse_template_list, get_installation_paths, validate_template_selection

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

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(Path(args.log_dir))

    # Log the main header rather than using console.print
    logger.info("Proxmox Template Builder")

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
