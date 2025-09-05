import sys
import time

import requests
import utils.panel_renderer as panels
from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
from utils.ascii import LATER_DUDE
from utils.auth import get_client_details, CLIENT_ID
from utils.env_helper import print_indented
from utils.room_ops import export_rooms, update_rooms
from utils.bulk_create import create_rooms
from utils.site_ops import create_site_if_not_exists

# -----------GLOBALS-----------

INITIAL_LOOP = True
IDENTITY = None
FLASH = ""
# -----------CLI MENU-----------

console = panels._console()

# -----------PRIVATE BUILDERS-----------


def _ask_int(
    label: str,
    default: int,
    *,
    min_value: int | None = None,
    explain: str = "defaults to",
) -> int:

    hint = f"{explain} {default}" + (
        f" · min {min_value}" if min_value is not None else ""
    )

    while True:
        raw = input_prompt(f"{label} [muted]{hint}[/muted] > ", uppercase=False)
        if raw == "":
            return default
        try:
            val = int(raw)
        except ValueError:
            print_indented("Please enter a whole number", style="red")
            continue

        if min_value is not None and val < min_value:
            print_indented(f"Must be >= {min_value}", style="red")
            continue
        return val


def _ask_str(
    label: str,
    default: str = "",
    *,
    allow_empty: bool = True,
    explain: str = "defaults to",
) -> str:
    hint = f"{explain} {default}" if default else "optional"
    raw = input_prompt(f"{label} [muted]{hint}[/muted] > ", uppercase=False)
    if raw == "":
        return default if allow_empty else ""
    return raw


# -----------PUBLIC RENDERERS-----------


def bootup():
    global INITIAL_LOOP
    global IDENTITY
    steps = (
        [
            "[red][SYS][/red] Activating core processors...",
            "[red][I/O][/red] Scanning data ports...",
            "[red][NET][/red] Establishing uplink to Poly Lens Cloud...",
            "[red][AUTH][/red] Verifying API Creds...",
            "[red][ROOM][/red] Initializing Room Metadata Cache...",
            "[red][OK][/red] LENSCTL OPS DECK fully operational...",
        ]
        if panels.DARK_MODE
        else [
            "[bold cyan][SYS][/bold cyan] Activating core processors...",
            "[bold cyan][I/O][/bold cyan] Scanning data ports...",
            "[bold cyan][NET][/bold cyan] Establishing uplink to Poly Lens Cloud...",
            "[bold cyan][AUTH][/bold cyan] Verifying API Creds...",
            "[bold cyan][ROOM][/bold cyan] Initializing Room Metadata Cache...",
            "[bold cyan][OK][/bold cyan] LENSCTL OPS DECK fully operational...",
        ]
    )

    try:
        IDENTITY = get_client_details(CLIENT_ID)
    except Exception as exc:
        IDENTITY = {"name": "Unknown credential", "role": "", "error": str(exc)}

    with Live(console=console, refresh_per_second=4, screen=True) as live:
        for i, step in enumerate(steps, 1):
            panel = Panel(
                Align.center(Text.from_markup(step)),
                title=f"[title]LENSCTL :: {'EMPIRE' if panels.DARK_MODE else 'OPS DECK'} INIT [{i}/{len(steps)}] [/title]",
                border_style="border",
                padding=(1, 3),
            )
            live.update(panel)
            time.sleep(0.4)

    console.clear()
    console.print(panels.render_screen(selected=None, identity=IDENTITY))
    time.sleep(0.7)


def toggle_dark_mode():
    global console, FLASH
    FLASH = panels.toggle_theme()
    console = panels._console()


def print_goodbye():
    console = panels._console()
    console.clear()
    console.print(
        Panel(
            Align.center(Text.from_markup(LATER_DUDE)),
            border_style="border",
            title="[title]LENSCTL OPS DECK :: EXITING SEQUENCE COMPLETE [/title]",
            padding=(1, 3),
            expand=True,
        )
    )


def input_prompt(question: str = "", *, uppercase: bool = True) -> str:
    styles = panels.get_mode()
    s = console.input(
        f"[{styles['secondary']}]{styles['prompt_prefix']} {question}[/]"
    ).strip()
    return s.upper() if uppercase else s


def prompt_create_rooms() -> dict:
    count = _ask_int("Number of rooms →", 10, min_value=1)
    base = _ask_str("Base name →", "Room")
    start = _ask_int("Starting Number →", 0)
    site = _ask_str("Site Name (Optional)", "", allow_empty=True).strip()
    return {
        "count": count,
        "base_name": base,
        "start": start,
        "site_name": site,
    }


def main():
    bootup()
    while True:
        console.clear()
        console.print(
            panels.render_screen(selected=None, identity=IDENTITY, flash=FLASH)
        )

        choice = input_prompt("Enter task selection [0,1,2,3] > ")
        if choice == panels.SECRET_CODE:
            toggle_dark_mode()
            continue
        if choice == "1":
            console.print("[ok] Exporting Rooms...[/ok]")
            export_rooms()
        elif choice == "2":
            console.print("[ok] Updating Room Metadata...[/ok]")
            update_rooms()
        elif choice == "3":
            params = prompt_create_rooms()
            if not params:
                time.sleep(0.5)
                continue
            site_id = None
            site_name = params.pop("site_name", "").strip()
            if site_name:
                try:
                    site_id = create_site_if_not_exists(site_name)
                except requests.RequestException as exc:
                    print_indented(
                        f"Site lookup/create failed (network): {exc}", style="red bold"
                    )
                    time.sleep(0.8)
                    continue
                except Exception as exc:
                    print_indented(
                        f"Site lookup/create failed: {exc}", style="red bold"
                    )
                    time.sleep(0.8)
                    continue
            console.print("[ok] Creating Rooms...[/ok]")
            create_rooms(**params, siteId=site_id)
            time.sleep(0.8)
        elif choice == "0":
            print_goodbye()
            sys.exit(0)
        else:
            print_indented("❌ Invalid choice. Please try again.", style="red bold")


if __name__ == "__main__":
    main()
