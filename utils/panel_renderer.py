import sys
import time
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.console import Console
from rich.live import Live
from rich.align import Align
from utils.ascii import LIGHT_ASCII, DARK_ASCII

# Global Feature Flags
SECRET_CODE = "66"
DARK_MODE = False
BANNER_SHOWN = False


console = Console()

ASCII_HEIGHT = len(LIGHT_ASCII.splitlines())
PANEL_HEIGHT = ASCII_HEIGHT + 6
PANEL_WIDTH = console.size.width - 2

def get_mode():
    if DARK_MODE:
        return {
            "primary": "bold red",
            "secondary": "dim white",
            "prompt_prefix": "[bold red][EMPIRE][/bold red]"
        }
    else:
        return {
            "primary": "bold cyan",
            "secondary": "dim",
            "prompt_prefix": "[bold cyan][DROID][/bold cyan]"
        }

def render_panel(body: str, title: str, subtitle: str = "", border_style: str = "bright_black"):
  styles = get_mode()
  panel = Panel(
    Align.center(Text(body, style=styles["primary"])),
    title=title,
    subtitle=subtitle,
    border_style=border_style,
    padding=(1,3),
    width=PANEL_WIDTH,
    height=PANEL_HEIGHT,
  )
  console.clear()
  console.print(panel)

def show_menu():
    styles = get_mode()
    render_panel(
        DARK_ASCII if DARK_MODE else LIGHT_ASCII,
        title=f"[{styles['primary']}] ROOM TROOPER :: {'EMPIRE' if DARK_MODE else 'LENS'} ROOMS CONFIG TERMINAL [/{styles['primary']}]",
        subtitle=f"[{styles['secondary']}] Clone it. Update it. Move along.[/{styles['secondary']}]",
        border_style="red" if DARK_MODE else "bright_black",
        )

def show_banner():
    banner_text = Text()
    banner_text.append("\nYou have summoned the ", style="white")
    banner_text.append("Dark Side", style="bold red")
    banner_text.append("\n\n", style="bold white")
    panel = Panel(
        Align.center(banner_text),
        border_style="red",
        title="[bold red] EMPEROR'S COMMAND [/bold red]",
        padding=(1,2)
    )
    console.clear()
    console.print(panel)
    time.sleep(1.5)
    console.clear()
