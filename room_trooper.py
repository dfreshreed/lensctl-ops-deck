import sys
import time
from utils.env_helper import print_indented
import utils.panel_renderer as panels
from update_room_data import export_rooms, update_rooms
from rich.text import Text
from rich.panel import Panel
from rich.console import Console
from rich.live import Live
from rich.align import Align
from utils.ascii import JARJAR_ASCII

# Global Feature Flags
INITIAL_LOOP = True

# CLI Menu
console = Console()

def bootup():
    global INITIAL_LOOP
    styles = panels.get_mode()
    panel_border = "red" if panels.DARK_MODE else "bright_black"
    steps = [
        "[red][SYS][/red] Activating core processors...",
        "[red][I/O][/red] Scanning data ports...",
        "[red][NET][/red] Establishing uplink to Poly Lens Cloud...",
        "[red][AUTH][/red] Verifying API Creds...",
        "[red][ROOM][/red] Initializing Room Metadata Cache...",
        "[red][OK][/red] RT-L-T fully operational...",
    ] if panels.DARK_MODE else [
        "[bold cyan][SYS][/bold cyan] Activating core processors...",
        "[bold cyan][I/O][/bold cyan] Scanning data ports...",
        "[bold cyan][NET][/bold cyan] Establishing uplink to Poly Lens Cloud...",
        "[bold cyan][AUTH][/bold cyan] Verifying API Creds...",
        "[bold cyan][ROOM][/bold cyan] Initializing Room Metadata Cache...",
        "[bold cyan][OK][/bold cyan] RT-L-T fully operational...",
    ]

    with Live(
        console=console,
        refresh_per_second=4,
        screen=True
    ) as live:
        for i, step in enumerate(steps, 1):
            panel = Panel(
                Align.center(Text.from_markup(step, style=styles["primary"])),
                title=f"[{styles['primary']}] ROOM TROOPER :: {'EMPIRE' if panels.DARK_MODE else 'LENS'} INIT [{i}/{len(steps)}] [/{styles['primary']}]",
                border_style=panel_border,
                padding=(1, 3),
                # expand=True,
            )
            live.update(panel)
            time.sleep(0.4)

    panels.render_panel(
        panels.DARK_ASCII if panels.DARK_MODE else panels.LIGHT_ASCII,
        title=f"[{styles['primary']}] ROOM TROOPER :: {'EMPIRE' if panels.DARK_MODE else 'LENS'} ROOMS CONFIG TERMINAL [/{styles['primary']}]",
        subtitle=f"[{styles['secondary']}] Clone it. Update it. Move along.[/{styles['secondary']}]",
        border_style="red" if panels.DARK_MODE else "bright_black"
    )
    time.sleep(0.7)

def toggle_dark_mode():
    panels.DARK_MODE = not panels.DARK_MODE
    # INITIAL_LOOP = True
    if panels.DARK_MODE and not panels.BANNER_SHOWN:
        panels.show_banner()
        panels.BANNER_SHOWN = True
        panels.show_menu()
        console.print("[red]The galaxy obeys your command…[/red]")
    else:
        panels.show_menu()
        console.print("[cyan]The rebellion cowers before you no more…[/cyan]")

def print_goodbye():
    console.clear()
    console.print(
        Panel(
            Align.center(Text.from_markup(JARJAR_ASCII)),
            border_style="bright_black",
            title="[bold cyan]ROOM TROOPER :: EXITING SEQUENCE COMPLETE [/bold cyan]",
            padding=(1,3),
            expand=True
        )
    )


def droid_prompt(
    question: str = "Select Task"
) -> str:

    styles = panels.get_mode()
    console.print(" " * console.width, end="\r")
    console.print(f"[{styles['secondary']}]{styles['prompt_prefix']} {question}[/{styles['secondary']}]", end=" ", highlight=False)
    answer = input().strip().upper()
    return answer


def main():
    bootup()
    while True:
        panels.show_menu()
        choice = droid_prompt("Enter task selection [0,1,2] >").strip()
        if choice == panels.SECRET_CODE:
            toggle_dark_mode()
            continue
        if choice == "1":
            console.print("[green] Exporting Rooms...[/green]")
            export_rooms()
        elif choice == "2":
            console.print("[green] Updating Room Metadata...[/green]")
            update_rooms()
        elif choice == "0":
            print_goodbye()
            sys.exit(1)
        else:
            print_indented("❌ Invalid choice. Please try again.", style="red bold")


if __name__ == "__main__":
    main()
