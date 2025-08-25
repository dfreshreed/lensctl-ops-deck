import sys
import time
import utils.panel_renderer as panels
from update_room_data import export_rooms, update_rooms
from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
from utils.env_helper import print_indented
from utils.ascii import LATER_DUDE
from utils.auth import get_client_details, CLIENT_ID

# -----------GLOBALS-----------
INITIAL_LOOP = True
IDENTITY = None
# -----------CLI MENU-----------
console = panels._console()


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
    global console
    panels.DARK_MODE = not panels.DARK_MODE
    # INITIAL_LOOP = True
    if panels.DARK_MODE and not panels.BANNER_SHOWN:
        panels.show_banner()
        panels.BANNER_SHOWN = True
        message = "[accent]The galaxy obeys your command…[/accent]"
    else:
        message = "[accent]The rebellion cowers before you no more…[/accent]"

    console = panels._console()
    console.clear()
    console.print(panels.render_screen(selected=None, identity=IDENTITY))
    console.print(Text.from_markup(message))


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


def input_prompt(question: str = "Select Task") -> str:
    styles = panels.get_mode()
    return (
        console.input(f"[{styles['secondary']}]{styles['prompt_prefix']} {question}[/]")
        .strip()
        .upper()
    )


def main():
    bootup()
    while True:
        console.clear()
        console.print(panels.render_screen(selected=None, identity=IDENTITY))
        # panels.show_menu()
        choice = input_prompt("Enter task selection [0,1,2] >")
        if choice == panels.SECRET_CODE:
            toggle_dark_mode()
            continue
        if choice == "1":
            console.print("[ok] Exporting Rooms...[/ok]")
            export_rooms()
        elif choice == "2":
            console.print("[ok] Updating Room Metadata...[/ok]")
            update_rooms()
        elif choice == "0":
            print_goodbye()
            sys.exit(1)
        else:
            print_indented("❌ Invalid choice. Please try again.", style="red bold")


if __name__ == "__main__":
    main()
