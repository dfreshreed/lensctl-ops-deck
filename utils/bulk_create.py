import json
import time
import requests
from rich.text import Text
from typing import Optional
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import JsonLexer

from utils.env_helper import logger, console_log, console
import utils.auth as auth

# -----------GLOBALS-----------
DEFAULT_ROOM = {
    "capacity": None,
    "size": "NONE",
    "floor": "",
    "tenantId": auth.TENANT_ID,
    "siteId": None,
}

BULK_CREATE_ROOMS = """
mutation updateRoomData($fields: UpsertRoomRequest!) {
  upsertRoom(fields: $fields) {
    name
    id
    capacity
    size
    updatedAt
    floor
    site {
      id
      name
    }
  }
}
"""


# -----------PRIVATE BUILDERS-----------
def _make_room_name(base: str | None, n: int, sep: str = " ") -> str:
    base = (base or "").strip()
    return f"{base}{sep}{n}" if base else str(n)


# -----------PUBLIC RENDERERS-----------
def create_rooms(
    count: int,
    base_name: str = "None",
    start: int = 0,
    delay: float = 0.5,
    siteId: Optional[str] = None,
    *,
    interactive_pause: bool = False,
):
    total_rooms_created = 0
    total_errors = 0
    all_errors = []
    counter = start

    for _ in range(count):
        fields = DEFAULT_ROOM.copy()
        fields["name"] = _make_room_name(base_name, counter)
        if siteId is not None:
            fields["siteId"] = siteId
        counter += 1
        time.sleep(delay)

        # build the payload structure
        payload = {"query": BULK_CREATE_ROOMS, "variables": {"fields": fields}}

        try:
            response = requests.post(
                auth.GRAPHQL_URL, json=payload, headers=auth.get_headers()
            )
            response.raise_for_status()
            data = response.json()

            highlighted = highlight(
                json.dumps(data, indent=2), JsonLexer(), TerminalFormatter()
            )

            if "errors" in data:
                # log GQL errors
                gql_error = f"GraphQL error creating: \n{highlighted}"
                logger.error(gql_error)
                all_errors.append(gql_error)
                total_errors += 1
            else:
                # log successful GQL response
                logger.info(f"Room created: \n{highlighted}")
                total_rooms_created += 1

        # log network or HTTP errors
        except requests.RequestException as err:
            http_err = f"Request error for {err}"
            logger.error(http_err)
            all_errors.append(http_err)

            total_errors += 1

    if not total_errors:
        console_log(
            "[magenta]create_rooms()[/magenta] [blue]completed successfully with no errors.[/blue]"
        )
        message = Text.assemble(
            ("Total rooms created: ", "magenta"),
            (str(total_rooms_created), "yellow"),
        )
        console_log(message)
    else:
        message = Text.assemble(
            ("create rooms() ", "magenta"),
            ("failed with ", "red"),
            (str(total_errors), "yellow"),
            (" errors", "red"),
        )
        console_log(message)
        message = Text.assemble(
            ("Total rooms created: ", "magenta"),
            (str(total_rooms_created), "yellow"),
        )
        console_log(message)

    console.input("[dim]Press Enter to return to main menu [/dim]")
