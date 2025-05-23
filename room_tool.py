import sys
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import TerminalFormatter
from rich.traceback import install
from env_helper_util import get_required_env, print_indented, logger, prompt_with_indent
from update_room_data import export_rooms, update_rooms

# CLI Menu


def main():
    print_indented("🛠️  Lens Room Tool")
    print_indented("────────────────────────────")
    print_indented("1️⃣  Export your Lens Room data to CSV")
    print_indented("2️⃣  Update your Lens Room data from CSV")
    print_indented("0️⃣  Exit")
    print_indented("────────────────────────────")
    choice = prompt_with_indent("👉🏻 Choose an option [0/1/2]: ").strip()

    if choice == "1":
        export_rooms()
    elif choice == "2":
        update_rooms()
    elif choice == "0":
        print_indented(
            r"""
            o_o
           / ^ \
          /(<->)\
         // \ / \\
        //  ) (  \\
        ` _/   \_ '

👋🏼 Okie-day, see yousa later!
            """
        )
        sys.exit(1)
    else:
        logger.error("❌ Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
