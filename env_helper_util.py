import os
import sys
import logging
import coloredlogs
from dotenv import load_dotenv
from rich.text import Text
from rich.console import Console
from typing import Union
from datetime import datetime


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


def console_log(msg: Union[str, Text], style: str = "white"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    console.print(f"[green]{timestamp}[/green]", msg)


def pretty_node_deets(node: dict):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = Text(f"[{timestamp}] Node -> ", style="green")

    for key, value in node.items():
        if isinstance(value, dict):
            line.append("site: { ", style="pale_violet_red1")
            for sub_key, sub_value in value.items():
                line.append(f"{sub_key}: ", style="yellow")
                line.append(f"{sub_value} ", style="blue")
            line.append("} ", style="pale_violet_red1")
        else:
            line.append(f"{key}: ", style="yellow")
            line.append(f"{value} ", style="blue")
    console.print(line)
