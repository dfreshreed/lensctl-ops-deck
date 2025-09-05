import json
import requests
import pandas as pd
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import JsonLexer
from rich.text import Text
from utils.env_helper import logger, console_log, pretty_node_deets, console, bool_text
import utils.auth as auth
from utils.site_ops import resolve_site, SiteIdNotFoundError

# lens api query to lookup room data
EXPORT_ROOMS = """
query getRoomData($params: RoomConnectionParams) {
  tenants {
    roomData(params: $params) {
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        node {
          name
          id
          site {
            name
            id
          }
          capacity
          size
          floor
        }
      }
    }
  }
}
"""

# lens api mutation to update room metadata
UPDATE_ROOMS = """
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


def export_rooms():
    logger.info("Starting room export to csv")
    all_rooms = []
    total_rooms_exported = 0
    all_errors = []
    total_errors = 0
    cursor = None

    while True:
        payload = {
            "query": EXPORT_ROOMS,
            "variables": {
                "params": {
                    "cursor": cursor,
                    "paging": "NEXT_PAGE",
                    "limit": 50,
                    "sort": [{"field": "ROOM_NAME", "direction": "ASC"}],
                }
            },
        }
        try:
            response = requests.post(
                auth.GRAPHQL_URL, json=payload, headers=auth.get_headers()
            )
            response.raise_for_status()
        except requests.RequestException as err:
            logger.error(f"Export request failed: {err}")
            all_errors.append(f"Request error: {err}")
            total_errors += 1
            break
        data = response.json()
        if data.get("errors"):
            logger.error(f"GraphQL error:\n{json.dumps(data['errors'], indent=2)}")
            all_errors.append(json.dumps(data["errors"], indent=2))
            total_errors += 1
            break

        tenants = data.get("data", {}).get("tenants", [])
        if not tenants:
            logger.error("No tenants returned in GraphQL response")
            all_errors.append("No tenants returned in GQL response")
            total_errors += 1
            break
        room_data = tenants[0].get("roomData", {})
        edges = room_data.get("edges", [])
        page_info = room_data.get("pageInfo", {})

        for edge in edges:
            node = edge["node"]
            pretty_node_deets(node, pad_braces=True)
            total_rooms_exported += 1
            all_rooms.append(
                {
                    "name": node.get("name"),
                    "id": node.get("id"),
                    "capacity": node.get("capacity"),
                    "size": node.get("size"),
                    "floor": node.get("floor"),
                    "siteName": (node.get("site") or {}).get("name"),
                    "siteId": (node.get("site") or {}).get("id"),
                }
            )

        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        message = Text.assemble(("Pagination: ", "white"), ("hasNextPage=", "yellow"))
        message.append_text(bool_text(has_next))
        message.append(" endCursor=", "yellow")
        message.append(str(cursor), "magenta")
        console_log(message)

        if has_next and cursor:
            continue
        else:
            break

    if all_rooms:
        dataframe = pd.DataFrame(
            all_rooms,
            columns=["name", "id", "capacity", "size", "floor", "siteName", "siteId"],
        )
        dataframe.to_csv("room_data.csv", index=False)
        console_log(
            "[blue]All Room Data exported to[/blue] [magenta]room_data.csv[/magenta]"
        )
        console_log(
            "🏁 [magenta]export_rooms()[/magenta] [blue]completed with no errors[/blue]"
        )
    else:
        message = Text.assemble(
            ("export_rooms()", "magenta"),
            ("failed with", "red"),
            (str(total_errors), "yellow"),
            ("errors", "red"),
        )
        console_log(message)
        # console_log(all_errors)
        console_log("[red]Details on all errors:[/red] \n" + "\n".join(all_errors))
    message = Text.assemble(
        ("Total Rooms Exported: ", "blue"), (str(total_rooms_exported), "yellow")
    )
    console_log(message)
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return


# GRAPHQL Mutation: Update Rooms
# for each row in the csv, map the data to the expected graphql argument field name, and send the request
def update_rooms():
    total_rooms_imported = 0
    total_errors = 0
    all_errors = []
    site_name_to_id = {}
    site_id_to_name = {}

    # read the csv
    try:
        dataframe = pd.read_csv("./room_data.csv")
    # handle any errors
    except Exception as ex:
        logger.error(f"Failed to read csv: {ex}")
        console.input("[dim]Press Enter to return to main menu[/dim]")
        return
    if dataframe.empty:
        console_log(
            "[yellow]'room_data.csv' is empty → There's nothing to import [/yellow]"
        )
        console.input("[dim]Press Enter to return to main menu[/dim]")
        return

    # loop through each csv row
    for index, row in dataframe.iterrows():
        row_dict = row.to_dict()
        # row_dict = {key: (None if pd.isna(value) else value) for key, value in row_dict}
        # log row for debugging
        pretty_node_deets(row_dict, label=f"CSV row {index}", pad_braces=True)

        # Pull each value once for finalizing types
        raw_id = row.get("id")
        raw_name = row.get("name")
        raw_capacity = row.get("capacity")
        raw_size = row.get("size")
        raw_floor = row.get("floor")
        raw_site = row.get("siteId")
        raw_site_name = row.get("siteName")

        message = Text.assemble(
            ("🔍 Resolving site for ", "white"),
            (repr(raw_site_name), "yellow"),
            (":", "grey58"),
            (repr(raw_site), "blue"),
            ("...", "white"),
        )
        console_log(message)

        try:
            site_id_value = resolve_site(
                raw_site, raw_site_name, site_name_to_id, site_id_to_name
            )
        except SiteIdNotFoundError as error:
            logger.error(f"Caught SiteIdNotFoundError in row {index}: {error}")
            all_errors.append(f"Row {index}: {error}")
            total_errors += 1
            continue
        except requests.RequestException as http_error:
            logger.error(
                f"Row {index}: HTTP error during site resolution: {http_error}"
            )
            if http_error.response is not None:
                logger.debug(f"Response body:\n{http_error.response.text}")
            all_errors.append(f"Row {index}: {http_error}")
            total_errors += 1
            continue
        except Exception as err:
            logger.error(f"Row {index}: site resolution failed: {err}")
            all_errors.append(f"Row {index}: {err}")

            total_errors += 1
            continue

        room_id_value = None if pd.isna(raw_id) else str(raw_id)

        # if capacity is missing set it to None. otherwise, validate integer and convert to null (none) with warning on failure
        capacity_series = pd.to_numeric(pd.Series([raw_capacity]), errors="coerce")
        capacity_number = capacity_series.iloc[0]
        capacity_value = None if pd.isna(capacity_number) else int(capacity_number)

        if (
            pd.isna(capacity_number)
            and not pd.isna(raw_capacity)
            and str(raw_capacity).strip()
        ):
            console_log(
                f"[yellow]Warning:[/yellow] row {index} had [green]'capacity'[/green]: "
                f"[red]'{raw_capacity}'[/red], which isn't a number. "
                "It's been set to [blue]null[/blue] (None). "
                "See README › CSV Format: https://github.com/dfreshreed/lens-room-trooper "
                "for expected types. "
                "Fix value in [green]room_data.csv[/green] and run the import again.",
                style="bold",
            )
        # validate enum sizes as safety net for bad input
        DEFAULT_SIZE = "NONE"
        VALID_SIZES = {"NONE", "FOCUS", "HUDDLE", "SMALL", "MEDIUM", "LARGE"}
        # if no csv value use enum defined value
        raw_size = raw_size.upper() if pd.notna(raw_size) else DEFAULT_SIZE
        size_value = raw_size if raw_size in VALID_SIZES else DEFAULT_SIZE

        # if floor is missing -> None, otherwise ensure string if floors are numbered
        floor_value = None if pd.isna(raw_floor) else str(raw_floor).strip()

        # build room fields dictionary for payload
        room_fields = {
            "tenantId": auth.TENANT_ID,
            "id": room_id_value,
            "capacity": capacity_value,
            "size": size_value,
            "floor": floor_value,
            "siteId": site_id_value,
        }
        # ---trim name whitespace and ensure no empty string---
        if pd.notna(raw_name) and str(raw_name).strip():
            room_fields["name"] = str(raw_name).strip()
        # ---build the update room payload structure---

        pretty_node_deets(
            room_fields, label=f"Sending row {index} to Lens API", pad_braces=True
        )
        payload = {"query": UPDATE_ROOMS, "variables": {"fields": room_fields}}

        try:
            # ---fire off the request and assign the response to a variable for error handling---
            response = requests.post(
                auth.GRAPHQL_URL, json=payload, headers=auth.get_headers()
            )
            response.raise_for_status()
            data = response.json()
            highlighted = highlight(
                json.dumps(data, indent=2), JsonLexer(), TerminalFormatter()
            )
            if "errors" in data:
                # ---log GQL errors---
                gql_error = f"GraphQL error at row {index}: \n{highlighted}"
                logger.error(gql_error)
                all_errors.append(gql_error)
                total_errors += 1
            else:
                # ---log successful GQL response---
                logger.info(f"Row {index} updated. API response: \n{highlighted}")
                total_rooms_imported += 1
        # ---log network or HTTP errors---
        except requests.RequestException as err:
            http_err = f"Request error at row {index}: {err}"
            logger.error(http_err)
            all_errors.append(http_err)
            total_errors += 1
    if not total_errors:
        console_log(
            "[magenta]update_rooms()[/magenta] [blue]completed with no errors.[/blue]"
        )
        message = Text.assemble(
            ("Total Rooms Imported: ", "blue"), (str(total_rooms_imported), "yellow")
        )
        console_log(message)
    else:
        message = Text.assemble(
            ("update_rooms() ", "magenta"),
            ("failed with ", "red"),
            (str(total_errors), "yellow"),
            (" error(s)", "red"),
        )
        console_log(message)

        console_log("[red]Details on all errors:[/red] \n" + "\n".join(all_errors))
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return
