from utils.env_helper import print_indented, console
import utils.panel_renderer as panels


def input_prompt(question: str = "", *, uppercase: bool = True) -> str:
    console = panels._console()
    styles = panels.get_mode()
    s = console.input(
        f"[{styles['secondary']}]{styles['prompt_prefix']} {question}[/]"
    ).strip()
    return s.upper() if uppercase else s


def ask_int(
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
        raw = input_prompt(f"{label} [[muted]{hint}[/muted]] > ", uppercase=False)
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


def ask_str(
    label: str,
    default: str = "",
    *,
    allow_empty: bool = True,
    explain: str = "defaults to",
) -> str:
    if explain == "defaults to":
        hint = f"{explain} {default}" if default else "optional"
    else:
        hint = explain
    raw = input_prompt(f"{label} [[muted]{hint}[/muted]] > ", uppercase=False)
    if raw == "":
        return default if allow_empty else ""
    return raw


def menu_return():
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return
