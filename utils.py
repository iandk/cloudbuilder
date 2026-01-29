# utils.py
#!/usr/bin/env python3

import logging
from logging.handlers import RotatingFileHandler
import subprocess
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

    # Create rotating file handler (10MB max, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)

    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_formatter)

    # Configure a consistent display format for the console logger
    # Using a more minimal format without timestamps to avoid clutter
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=False,  # Tracebacks go to log file only, not console
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

    # Debug output to help diagnose path issues (only if logger is configured)
    logger = logging.getLogger("cloudbuilder")
    if logger.handlers or logging.root.handlers:
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


def self_update(install_dir: Path, logger: logging.Logger) -> bool:
    """
    Update cloudbuilder from git repository if installed from git.

    Args:
        install_dir: The installation directory of cloudbuilder
        logger: Logger instance

    Returns:
        True if update was successful or not a git repo, False on error
    """
    git_dir = install_dir / ".git"

    if not git_dir.exists():
        logger.warning(f"Not a git repository: {install_dir}")
        logger.info("Self-update is only available when cloudbuilder is installed from git")
        return False

    logger.info(f"Updating cloudbuilder from git repository in {install_dir}")

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = result.stdout.strip()
        logger.info(f"Current branch: {current_branch}")

        # Get current commit before update
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )
        old_commit = result.stdout.strip()

        # Fetch from remote
        logger.info("Fetching updates from remote...")
        subprocess.run(
            ["git", "fetch"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )

        # Check if there are updates available
        result = subprocess.run(
            ["git", "rev-list", f"HEAD..origin/{current_branch}", "--count"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )
        updates_available = int(result.stdout.strip())

        if updates_available == 0:
            logger.info("Already up to date")
            return True

        logger.info(f"{updates_available} update(s) available, pulling changes...")

        # Pull changes
        result = subprocess.run(
            ["git", "pull"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )

        # Get new commit
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )
        new_commit = result.stdout.strip()

        logger.info(f"Successfully updated from {old_commit} to {new_commit}")

        # Show recent commits
        result = subprocess.run(
            ["git", "log", f"{old_commit}..{new_commit}", "--oneline"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout.strip():
            logger.info("Changes:")
            for line in result.stdout.strip().split('\n'):
                logger.info(f"  {line}")

        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Git command failed: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        logger.error(f"Failed to update: {e}")
        return False


def setup_shell_completions(logger: logging.Logger) -> bool:
    """
    Set up shell autocompletions for cloudbuilder.

    This function:
    1. Checks if argcomplete is installed (installs it if not)
    2. Registers cloudbuilder for global completion

    Args:
        logger: Logger instance

    Returns:
        True if setup was successful, False otherwise
    """
    # Check if argcomplete is installed
    try:
        import argcomplete
        logger.info("argcomplete is already installed")
    except ImportError:
        logger.info("argcomplete not found, attempting to install...")

        # Check if we're on a Debian-based system with externally-managed Python
        externally_managed = Path("/usr/lib/python3.13/EXTERNALLY-MANAGED").exists() or \
                            Path("/usr/lib/python3.12/EXTERNALLY-MANAGED").exists() or \
                            Path("/usr/lib/python3.11/EXTERNALLY-MANAGED").exists()

        installed = False

        if externally_managed:
            # Try apt first on Debian-based systems
            logger.info("Detected externally-managed Python environment, using apt...")
            try:
                subprocess.run(
                    ["apt-get", "install", "-y", "python3-argcomplete"],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info("python3-argcomplete installed via apt")
                installed = True
            except subprocess.CalledProcessError as e:
                logger.warning(f"apt install failed: {e.stderr if e.stderr else e}")
            except FileNotFoundError:
                logger.warning("apt-get not found")

        if not installed:
            # Try pip with --break-system-packages as fallback
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--break-system-packages", "argcomplete"],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info("argcomplete installed via pip")
                installed = True
            except subprocess.CalledProcessError as e:
                # Try without --break-system-packages for non-externally-managed environments
                try:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", "argcomplete"],
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    logger.info("argcomplete installed via pip")
                    installed = True
                except subprocess.CalledProcessError as e2:
                    logger.error(f"Failed to install argcomplete: {e2.stderr if e2.stderr else e2}")

        if not installed:
            logger.error("Could not install argcomplete. Please install manually:")
            logger.error("  Debian/Ubuntu: apt install python3-argcomplete")
            logger.error("  Other: pip install argcomplete")
            return False

    # Find the cloudbuilder script path
    paths = get_installation_paths()
    cloudbuilder_script = paths['install_dir'] / "cloudbuilder.py"

    if not cloudbuilder_script.exists():
        logger.error(f"cloudbuilder.py not found at {cloudbuilder_script}")
        return False

    # Detect shell
    shell = Path(subprocess.run(
        ["echo", "$SHELL"],
        shell=True,
        capture_output=True,
        text=True
    ).stdout.strip() or "/bin/bash").name

    logger.info(f"Detected shell: {shell}")

    # For bash, we need to write a completion script that sources properly
    if shell == "bash":
        completion_dir = Path("/etc/bash_completion.d")
        if not completion_dir.exists() or not completion_dir.is_dir():
            completion_dir = Path.home() / ".bash_completion.d"
            completion_dir.mkdir(parents=True, exist_ok=True)
        completion_file = completion_dir / "cloudbuilder"

        # Write a bash completion script that uses argcomplete
        # This script will be sourced by bash on startup
        completion_script = '''# Bash completion for cloudbuilder
# Generated by cloudbuilder --setup-completions

_cloudbuilder_completion() {
    local IFS=$'\\013'
    local SUPPRESS_SPACE=0
    if compopt +o nospace 2> /dev/null; then
        SUPPRESS_SPACE=1
    fi

    COMPREPLY=( $(IFS="$IFS" \\
                  COMP_LINE="$COMP_LINE" \\
                  COMP_POINT="$COMP_POINT" \\
                  COMP_TYPE="$COMP_TYPE" \\
                  _ARGCOMPLETE_COMP_WORDBREAKS="$COMP_WORDBREAKS" \\
                  _ARGCOMPLETE=1 \\
                  _ARGCOMPLETE_SUPPRESS_SPACE=$SUPPRESS_SPACE \\
                  cloudbuilder 8>&1 9>&2 > /dev/null 2>&1) )
    if [[ $? != 0 ]]; then
        unset COMPREPLY
    elif [[ $SUPPRESS_SPACE == 1 ]] && [[ "${COMPREPLY-}" =~ [=/:]$ ]]; then
        compopt -o nospace
    fi
}

complete -o bashdefault -o default -o nosort -F _cloudbuilder_completion cloudbuilder
'''
        try:
            with open(completion_file, "w") as f:
                f.write(completion_script)
            logger.info(f"Bash completions written to {completion_file}")
            logger.info("Restart your shell or run: source " + str(completion_file))
            return True
        except PermissionError:
            # Try user's home directory
            completion_dir = Path.home() / ".bash_completion.d"
            completion_dir.mkdir(parents=True, exist_ok=True)
            completion_file = completion_dir / "cloudbuilder"
            with open(completion_file, "w") as f:
                f.write(completion_script)

            # Also add sourcing to .bashrc if not already there
            bashrc = Path.home() / ".bashrc"
            source_line = f'[ -f {completion_file} ] && source {completion_file}'
            if bashrc.exists():
                content = bashrc.read_text()
                if str(completion_file) not in content:
                    with open(bashrc, "a") as f:
                        f.write(f"\n# Cloudbuilder autocompletion\n{source_line}\n")
                    logger.info(f"Added completion source to {bashrc}")
            logger.info(f"Bash completions written to {completion_file}")
            logger.info("Restart your shell or run: source ~/.bashrc")
            return True

    elif shell == "zsh":
        # For zsh, we add to .zshrc
        zshrc = Path.home() / ".zshrc"
        completion_line = 'eval "$(register-python-argcomplete cloudbuilder)"'

        if zshrc.exists():
            content = zshrc.read_text()
            if completion_line not in content:
                with open(zshrc, "a") as f:
                    f.write(f"\n# Cloudbuilder autocompletion\n{completion_line}\n")
                logger.info(f"Added completion to {zshrc}")
            else:
                logger.info("Completion already configured in .zshrc")
        else:
            with open(zshrc, "w") as f:
                f.write(f"# Cloudbuilder autocompletion\n{completion_line}\n")
            logger.info(f"Created {zshrc} with completion")

        logger.info("Restart your shell or run: source ~/.zshrc")
        return True

    elif shell == "fish":
        fish_dir = Path.home() / ".config" / "fish" / "completions"
        fish_dir.mkdir(parents=True, exist_ok=True)
        completion_file = fish_dir / "cloudbuilder.fish"

        try:
            result = subprocess.run(
                ["register-python-argcomplete", "--shell", "fish", "cloudbuilder"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                with open(completion_file, "w") as f:
                    f.write(result.stdout)
                logger.info(f"Fish completions written to {completion_file}")
                return True
        except FileNotFoundError:
            pass

        # Fallback: write a basic fish completion
        logger.warning("Could not generate fish completions via register-python-argcomplete")
        logger.info("You may need to manually configure fish completions")
        return False

    else:
        logger.warning(f"Unsupported shell: {shell}")
        logger.info("You can manually add to your shell config:")
        logger.info('  eval "$(register-python-argcomplete cloudbuilder)"')
        return False
