import sys
import time
from env_helper_util import print_indented
from update_room_data import export_rooms, update_rooms
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.console import Console
from rich.live import Live
from rich.align import Align
from typing import List, Optional
import itertools

# Global Feature Flags
DARK_MODE = False
INITIAL_LOOP = True

# CLI Menu
console = Console()


def bootup():
    droid_ascii = f"""
        ____                                              [--------------- TASK LIST ---------------]
       / () \\                                             [ 0. Exit the script                      ]
     _|______|_      [ UNIT: RT-L-T ]                     [ 1. Export your Lens Rooms data to CSV   ]
    | | ==== | |     [ STATUS: ONLINE ]                   [ 2. Update your Lens Rooms data from CSV ]
    | |   o  | |     [ LINK: /dev/roomsbus ]              [-----------------------------------------]
"""
    steps = [
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
    ) as live:
        for i, step in enumerate(steps, 1):
            panel = Panel(
                Align.center(Text.from_markup(step, style="bold white")),
                title=f"[cyan] ROOM TROOPER :: LENS ROOMS CONFIG TERMINAL INIT [{i}/{len(steps)}] [/cyan]",
                border_style="bright_black",
                padding=(1, 3),
                expand=True,
            )
            live.update(panel)
            time.sleep(0.4)
    console.clear()
    console.print(
        Panel(
            Align.center(Text(droid_ascii, style="cyan")),
            border_style="bright_black",
            title="[bold cyan] ROOM TROOPER :: LENS ROOMS CONFIG TERMINAL [/bold cyan]",
            subtitle="[dim] Clone it. Update it. Move along.",
            padding=(1, 3),
        )
    )
    time.sleep(0.7)


def show_menu():
    droid_ascii = f"""
        ____                                              [--------------- TASK LIST ---------------]
       / () \\                                             [ 0. Exit the script                      ]
     _|______|_      [ UNIT: RT-L-T ]                     [ 1. Export your Lens Rooms data to CSV   ]
    | | ==== | |     [ STATUS: ONLINE ]                   [ 2. Update your Lens Rooms data from CSV ]
    | |   o  | |     [ LINK: /dev/roomsbus ]              [-----------------------------------------]
"""
    console.clear()
    console.print(
        Panel(
            Align.center(Text(droid_ascii, style="cyan")),
            border_style="bright_black",
            title="[bold cyan] ROOM TROOPER :: LENS ROOMS CONFIG TERMINAL [/bold cyan]",
            subtitle="[dim] Clone it. Update it. Move along.",
            padding=(1, 3),
        )
    )


def print_goodbye():
    jarjar_ascii = Text()
    jarjar_ascii.append("    o_o\n", style="bold yellow")
    jarjar_ascii.append("   / ^ \\\n", style="bold orange3")
    jarjar_ascii.append("  /(<->)\\\n", style="bold orange3")
    jarjar_ascii.append(" // \\ / \\\\\n", style="bold orange3")
    jarjar_ascii.append("//  ) (  \\\\\n", style="bold orange3")
    jarjar_ascii.append("` _/   \\_ '\n", style="bold orange3")

    goodbye_text = [
        "",
        "",
        "Okie-day!",
        "\nSee yousa later! 👋🏼",
        "",
        "",
    ]
    goodbye_block = "\n".join(goodbye_text)
    table = Table.grid(padding=(0, 6))
    table.add_row(jarjar_ascii, goodbye_block)

    console.print(
        Panel(
            Align.center(table, style="white"),
            border_style="bright_black",
            padding=(1, 3),
            title="[bold cyan]ROOM TROOPER :: EXITING SEQUENCE COMPLETE [/bold cyan]",
            expand=True,
        )
    )


def droid_prompt(
    question: str = "Select Task",
    delay: float = 0.4,
    cursor_duration: float = 1.0,
) -> str:
    global DARK_MODE
    global INITIAL_LOOP

    prompt_prefix = (
        "[bold red][TROOPER][/bold red]"
        if DARK_MODE
        else "[bold cyan][DROID][/bold cyan]"
    )

    cursor_color = "red" if DARK_MODE else "white"
    cursor_cycle = itertools.cycle(["▌", " "])

    if INITIAL_LOOP:
        with Live(refresh_per_second=4) as live:
            start_time = time.time()
            while time.time() - start_time < cursor_duration:
                cursor = next(cursor_cycle)
                live.update(
                    Text.from_markup(
                        f"[dim]{prompt_prefix} Initializing input...[/dim]",
                        style=cursor_color,
                    )
                )
                time.sleep(0.2)
        time.sleep(delay)
        INITIAL_LOOP = False
    console.print(" " * console.width, end="\r")

    console.print(f"{prompt_prefix} {question}", end=" ", highlight=False)
    answer = input()
    return answer.strip()


def main():
    bootup()
    while True:
        choice = droid_prompt("Enter task selection [0,1,2] >")
        choice = choice.strip()
        if choice == "1":
            console.print("[green] Exporting Rooms...[/green]")
            export_rooms()
            console.input("[dim]Press Enter to return to main menu[/dim]")
            show_menu()
        elif choice == "2":
            console.print("[green] Updating Room Metadata...[/green]")
            update_rooms()
            console.input("[dim]Press Enter to return to main menu[/dim]")
            show_menu()
        elif choice == "0":
            print_goodbye()
            sys.exit(1)
        else:
            print_indented("❌ Invalid choice. Please try again.", style="red bold")


if __name__ == "__main__":
    main()
