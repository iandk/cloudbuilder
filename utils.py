#!/usr/bin/env python3

import logging
from pathlib import Path
from typing import List

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