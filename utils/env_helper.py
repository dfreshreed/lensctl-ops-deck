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
# ------------------
load_dotenv()

# ------------------
# configure global logging with color-coded output
# ------------------
logger = logging.getLogger("lens_api")
coloredlogs.install(
    level="DEBUG",
    logger=logger,
    fmt="%(asctime)s | [%(levelname)s] | %(message)s",
)


# ------------------
# validate .env variables loaded correctly
# ------------------
def get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if value is None or value.strip() == "":
        logger.error(f"❌ Missing required environment variable: {var_name}")
        sys.exit(1)
    return value


# ------------------
# helper functions for CLI tool formatting
# ------------------
INDENT = "  "
TS_STYLE = "dim grey70"
console = Console()


def ts() -> Text:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return Text(now, style=TS_STYLE)


def bool_text(val: bool) -> Text:
    if val is True:
        return Text("True", "bold green")
    if val is False:
        return Text("False", "bold red")
    return Text("None", style="dim")


def print_indented(text: str, style: str = "") -> None:
    for line in text.splitlines():
        console.print(f"{INDENT}{line}", style=style)


def prompt_with_indent(prompt: str) -> str:
    return input(f"{INDENT}{prompt}")


def console_log(
    msg: Union[str, Text], *, style: str | None = None, parse_markup: bool = True
) -> None:
    if isinstance(msg, Text):
        body = msg
    else:
        body = Text.from_markup(msg) if parse_markup else Text(str(msg))
        if style:
            body.stylize(style)
    line = Text.assemble(("[", TS_STYLE), ts(), ("] ", TS_STYLE))
    line.append_text(body)
    console.print(line)


def _render_value(value) -> Text:
    t = Text()
    if isinstance(value, bool):
        t.append("True" if value else "False", "green" if value else "red")
    elif value is None:
        t.append("None", "dim")
    elif isinstance(value, (int, float)):
        t.append(str(value), "cyan")
    elif isinstance(value, dict):
        t.append("{", "grey58")
        first = True
        for key, valtwo in value.items():
            if not first:
                t.append(", ", "grey58")
            first = False
            t.append(str(key), "yellow")
            t.append(": ", "grey58")
            t.append_text(_render_value(valtwo))
        t.append("}", "grey58")
    elif isinstance(value, (list, tuple, set)):
        open_bracket, close_bracket = (
            ("[", "]")
            if isinstance(value, list)
            else ("(", ")") if isinstance(value, tuple) else ("{", "}")
        )
        t.append(open_bracket, "grey58")
        for i, item in enumerate(value):
            if i:
                t.append(", ", "grey58")
            t.append_text(_render_value(item))
        t.append(close_bracket, "grey58")
    else:
        t.append(repr(value), "blue")
    return t


def _render_dict(d: dict, pad_braces: bool = False) -> Text:
    brace_style = "grey58"
    open_bracket = "{ " if pad_braces and d else "{"
    close_bracket = " }" if pad_braces and d else "}"
    t = Text(open_bracket, style=brace_style)
    for i, (key, value) in enumerate(d.items()):
        if i:
            t.append(", ", style=brace_style)
        t.append(str(key), style="yellow")
        t.append(": ", style=brace_style)
        t.append_text(_render_value(value))
    t.append(close_bracket, style=brace_style)
    return t


def pretty_node_deets(
    node: dict, label: str = "Node", pad_braces: bool = False
) -> None:
    line = Text.assemble((label + " ", "green"), ("→ ", "white"))
    line.append_text(_render_dict(node, pad_braces=pad_braces))
    console_log(line)
