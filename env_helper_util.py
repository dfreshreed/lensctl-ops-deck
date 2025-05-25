import os
import sys
import logging
import coloredlogs
from dotenv import load_dotenv
from rich.console import Console

# ------------------
# load environment variables
load_dotenv()

# ------------------
# configure global logging with color-coded output
logger = logging.getLogger("lens_api")
coloredlogs.install(
    level="DEBUG",
    logger=logger,
    fmt="%(asctime)s | [%(levelname)s] | %(message)s",
)


# ------------------
# validate .env variables loaded correctly
def get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if value is None or value.strip() == "":
        logger.error(f"❌ Missing required environment variable: {var_name}")
        sys.exit(1)
    return value


# ------------------
# helper functions for CLI tool formatting
INDENT = "  "

console = Console()


def print_indented(text: str, style: str = "") -> None:
    for line in text.splitlines():
        console.print(f"{INDENT}{line}", style=style)


def prompt_with_indent(prompt: str) -> str:
    return input(f"{INDENT}{prompt}")
