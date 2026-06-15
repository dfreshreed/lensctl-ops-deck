import json
import time
import requests
import pandas as pd
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import JsonLexer
from rich.text import Text
from utils.env_helper import logger, console_log, pretty_node_deets, console, bool_text
import utils.auth as auth
from utils.site_ops import resolve_site, SiteIdNotFoundError

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
    all_rooms = []
    total_rooms_exported = 0
    all_errors = []
    total_errors = 0
    cursor = None

    while True:
        try:
            data = auth.execute_gql(
                EXPORT_ROOMS,
                {
                    "params": {
                        "cursor": cursor,
                        "paging": "NEXT_PAGE",
                        "limit": 50,
                        "sort": [{"field": "ROOM_NAME", "direction": "ASC"}],
                    }
                },
            )
        except requests.RequestException as err:
            logger.error(f"Export request failed: {err}")
            break

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
            console_log(f"[muted]Exported:[/muted] {node.get('name')}")
            time.sleep(0.1)
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
        message.append(str(cursor), "blue")
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
        console_log("All Room Data exported to [dim]room_data.csv[/dim]")
        console_log(
            "🏁 [magenta]export_rooms()[/magenta] [green]completed with no errors[/green]"
        )
    else:
        message = Text.assemble(
            ("export_rooms()", "magenta"),
            ("failed with", "red"),
            (str(total_errors), "yellow"),
            ("errors", "red"),
        )
        console_log(message)
        console_log("[red]Details on all errors:[/red] \n" + "\n".join(all_errors))
    message = Text.assemble(
        ("Total Rooms Exported: "), (str(total_rooms_exported), "yellow")
    )
    console_log(message)
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return


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
            "There's nothing to import! [yellow]'room_data.csv' is empty...[/yellow]"
        )
        console.input("[dim]Press Enter to return to main menu[/dim]")
        return

    # loop through each csv row
    for index, row in dataframe.iterrows():
        time.sleep(0.3)
        console.print()
        row_dict = {}
        for key, value in row.to_dict().items():
            if pd.isna(value):
                row_dict[key] = None
            else:
                row_dict[key] = value

        pretty_node_deets(
            row_dict, label=f"CSV row {index}", pad_braces=True, label_style="yellow"
        )

        raw_id = row.get("id")
        raw_name = row.get("name")
        raw_capacity = row.get("capacity")
        raw_size = row.get("size")
        raw_floor = row.get("floor")
        raw_site = str(row.get("siteId")) if pd.notna(row.get("siteId")) else None
        raw_site_name = (
            str(row.get("siteName")) if pd.notna(row.get("siteName")) else None
        )

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
                "See README › CSV Format: https://github.com/dfreshreed/lensctl-ops-deck "
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

        # if floor missing -> None. numbered floors are strings
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
        # trim whitespace; validate no empty string
        if pd.notna(raw_name) and str(raw_name).strip():
            room_fields["name"] = str(raw_name).strip()

        # build update room payload structure
        pretty_node_deets(
            room_fields,
            label=f"Sending row {index}",
            pad_braces=True,
            label_style="muted",
        )

        try:
            data = auth.execute_gql(UPDATE_ROOMS, {"fields": room_fields})
            highlighted = highlight(
                json.dumps(data, indent=2), JsonLexer(), TerminalFormatter()
            )
            if "errors" in data:
                gql_error = f"GraphQL error at row {index}: \n{highlighted}"
                logger.error(gql_error)
                all_errors.append(gql_error)
                total_errors += 1
            else:
                console_log(
                    f"[ok]Row {index} synced.[/ok] Updated room record (in tenant): "
                )
                print(highlighted, end="")
                total_rooms_imported += 1
        # log network or HTTP errors
        except requests.RequestException as err:
            http_err = f"Request error at row {index}: {err}"
            logger.error(http_err)
            all_errors.append(http_err)
            total_errors += 1
    if not total_errors:
        console_log(
            "[magenta]update_rooms()[/magenta] [ok]completed with no errors.[/ok]"
        )
        message = Text.assemble(
            ("Total Rooms Imported: "), (str(total_rooms_imported), "yellow")
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
