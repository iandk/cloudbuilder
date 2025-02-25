# utils.py
#!/usr/bin/env python3

import logging
from pathlib import Path
from typing import List, Dict, Any
import sys

from rich.console import Console
from rich.logging import RichHandler

console = Console()

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
    
    # Configure a consistent display format for the console logger
    # Using a more minimal format without timestamps to avoid clutter
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_time=False,
        level=logging.INFO,
        markup=True,  # Enable rich markup in log messages
        show_path=False  # Hide the file path to make output cleaner
    )
    
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(message)s",  # Keep console format minimal
        handlers=[
            rich_handler,
            file_handler
        ]
    )
    
    logger = logging.getLogger("cloudbuilder")
    logger.info("Logging initialized")
    return logger

def parse_template_list(template_list: str) -> List[str]:
    """Parse a comma-separated list of templates."""
    if not template_list:
        return []
        
    return [t.strip() for t in template_list.split(",") if t.strip()]

def get_installation_paths():
    """Get standard paths for cloudbuilder installation."""
    # Resolve the real path of the script, following symlinks
    script_path = Path(__file__).resolve()
    install_dir = script_path.parent
    
    paths = {
        'install_dir': install_dir,
        'config_dir': install_dir,
        'template_dir': Path('/var/lib/cloudbuilder/templates'),
        'temp_dir': Path('/var/lib/cloudbuilder/tmp'),
        'log_dir': Path('/var/log/cloudbuilder'),
        'config_file': install_dir / 'templates.json',
    }
    
    # Create directories if they don't exist
    for dir_path in [paths['template_dir'], paths['temp_dir'], paths['log_dir']]:
        dir_path.mkdir(parents=True, exist_ok=True)
    
    # Debug output to help diagnose path issues
    logger = logging.getLogger("cloudbuilder")
    logger.debug(f"Script path: {script_path}")
    logger.debug(f"Install directory: {install_dir}")
    logger.debug(f"Config file path: {paths['config_file']}")
    
    return paths

def validate_template_selection(
    logger: logging.Logger, 
    available_templates: Dict[str, Any], 
    include_templates: List[str] = None, 
    exclude_templates: List[str] = None
) -> None:
    """
    Validate that all specified templates exist in the available templates.
    
    Args:
        logger: Logger instance
        available_templates: Dictionary of available templates
        include_templates: List of templates to include (--only)
        exclude_templates: List of templates to exclude (--except)
        
    Raises:
        SystemExit: If any specified templates don't exist
    """
    all_template_names = set(available_templates.keys())
    
    if include_templates:
        missing_templates = [t for t in include_templates if t not in all_template_names]
        if missing_templates:
            logger.error(f"Error: The following specified templates do not exist: {', '.join(missing_templates)}")
            logger.info(f"Available templates: {', '.join(sorted(all_template_names))}")
            sys.exit(1)
    
    if exclude_templates:
        missing_templates = [t for t in exclude_templates if t not in all_template_names]
        if missing_templates:
            logger.error(f"Error: The following excluded templates do not exist: {', '.join(missing_templates)}")
            logger.info(f"Available templates: {', '.join(sorted(all_template_names))}")
            sys.exit(1)