import time
from typing import Literal
from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from utils.ascii import LIGHT_ASCII, DARK_ASCII
from utils.env_helper import get_required_env

# -----------GLOBAL FEATURE FLAGS-----------
SECRET_CODE = "66"
DARK_MODE = False
BANNER_SHOWN = False

# -----------THEMES-----------
LIGHT = Theme(
    {
        "accent": "bold #89B4FA",  # blue
        "muted": "#6C7086",
        "ok": "bold #A6E3A1",
        "warn": "bold #FAB387",
        "err": "bold #F38BA8",
        "border": "#8C8FA1",
        "title": "bold #89B4FA",
        "link": "underline #89B4FA",
    }
)

DARK = Theme(
    {
        "accent": "bold #F38BA8",  # pink/red
        "muted": "#A6ADC8",
        "ok": "bold #A6E3A1",
        "warn": "bold #FAB387",
        "err": "bold #F38BA8",
        "border": "#585B70",
        "title": "bold #F38BA8",
        "link": "underline #F38BA8",
    }
)


def _console() -> Console:
    return Console(theme=(DARK if DARK_MODE else LIGHT))


def get_mode():
    if DARK_MODE:
        return {
            "primary": "accent",
            "secondary": "muted",
            "prompt_prefix": "[accent][EMPIRE][/accent]",
        }
    else:
        return {
            "primary": "accent",
            "secondary": "muted",
            "prompt_prefix": "[accent][INPUT][/accent]",
        }


# -----------PRIVATE BUILDERS-----------


def _status_badges(status_text="ONLINE", api_text="", identity: dict | None = None):
    api_text = get_required_env("LENS_EP")
    console_value = Text.assemble((" ●", "ok"), (" ", ""), (status_text, "accent"))
    t = Table.grid(padding=(0, 1))
    t.add_column(no_wrap=True)  # icons
    t.add_column()  # text
    t.add_row(
        _key_value_line(
            "Console",
            console_value,
        ),
    )
    t.add_row(
        _key_value_line(
            "Lens API EP",
            f" {api_text}",
        ),
    )
    if identity:
        name = identity.get("name", "")
        role = identity.get("role") or "No role"
        t.add_row(
            _key_value_line(
                "API Creds Name",
                f" {name}",
            ),
        )
        t.add_row(
            _key_value_line(
                "API Creds Role" + "",
                f" {role}",
            ),
        )
    return t


def _tasks(selected: int | None = None):
    rows = [
        "Exit",
        "Export Lens Rooms → CSV",
        "Update Lens Rooms ← CSV",
        "Create Rooms (bulk)",
    ]
    tb = Table.grid(padding=(0, 1))
    tb.add_column(justify="right", style="muted", no_wrap=True)
    tb.add_column()
    for i, label in enumerate(rows):
        index = f"{i}"
        if selected == i:
            tb.add_row(index, Text(f" {label} ", style="reverse"))
        else:
            tb.add_row(index, label)
    return Panel(
        tb,
        title="[accent] TASKS [/accent]",
        border_style="border",
        box=box.ROUNDED,
        expand=True,
    )


def _header(ascii_art: str):
    # ASCII as decoration
    art = Align.center(Text(ascii_art, no_wrap=True, style="accent"))
    return Panel(
        art,
        border_style="border",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _key_value_line(
    label: str,
    value: RenderableType,
    *,
    label_width: int = 18,
    label_style: str = "muted",
    value_style: str = "accent",
):
    grid = Table.grid(padding=(0), collapse_padding=True)
    grid.add_column(
        no_wrap=True,
        justify="left",
        min_width=label_width,
        max_width=label_width,
        style=label_style,
    )
    grid.add_column(style=value_style)
    value = (
        Text(value, style=value_style, overflow="fold")
        if isinstance(value, str)
        else value
    )
    grid.add_row(f"{label}:", value)

    return grid


# -----------PUBLIC RENDERERS-----------


def toggle_theme() -> None:
    global DARK_MODE
    DARK_MODE = not DARK_MODE
    show_banner("dark" if DARK_MODE else "light")


def render_screen(
    *,
    selected: int | None = None,
    status_text="ONLINE",
    api_text="LENS API GRAPHQL ENDPOINT",
    identity: dict | None = None,
    flash: RenderableType | None = None,
):
    outer_title = (
        "LENSCTL :: " + ("EMPIRE" if DARK_MODE else "OPS DECK") + " CONFIG TERMINAL"
    )
    outer_subtitle = "Query it. Update it. Move along."
    ascii_art = DARK_ASCII if DARK_MODE else LIGHT_ASCII
    header = _header(ascii_art)
    status = Panel(
        _status_badges(status_text, api_text, identity),
        title="[accent]STATUS[/accent]",
        border_style="border",
        box=box.ROUNDED,
        padding=(0, 1),
        expand=True,
    )
    tasks = _tasks(selected)
    tasks.expand = True
    vrule = ""

    body = Table.grid(expand=True, padding=(0, 1))
    body.add_column(ratio=1, min_width=28)  # STATUS
    body.add_column(min_width=1, ratio=0)  # SPACER
    body.add_column(ratio=1)  # TASKS
    body.add_row(status, vrule, tasks)

    pieces = [header, body]
    if flash:
        pieces.append(
            Align.center(Text.from_markup(flash) if isinstance(flash, str) else flash)
        )
    return Panel(
        Group(*pieces),
        title=f"[title]{outer_title}[/title]",
        subtitle=f"[muted]{outer_subtitle}[/muted]",
        title_align="center",
        subtitle_align="center",
        border_style="border",
        box=box.SQUARE,
        padding=(1, 1),
    )


def show_banner(kind: Literal["dark", "light"] = "dark", duration: float = 1.1) -> None:
    console = _console()

    if kind == "dark":
        title = "[title] EMPEROR'S COMMAND [/title]"
        body = Text.assemble(
            "\nYou have summoned the ", ("Dark Side", "accent"), "\n\n"
        )
    else:
        title = "[title] REBEL TRANSMISSION [/title]"
        body = Text.assemble(
            "\n", ("The Rebellion cowers before you no more!", "accent"), "\n\n"
        )

    panel = Panel(
        Align.center(body),
        border_style="border",
        title=title,
        padding=(1, 2),
        box=box.ROUNDED,
    )
    console.clear()
    console.print(panel)
    time.sleep(duration)
    console.clear()
