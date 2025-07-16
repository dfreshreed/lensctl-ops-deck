import json
import requests
import pandas as pd
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import JsonLexer
from utils.env_helper import logger, console_log, pretty_node_deets, console
import utils.auth as auth
from utils.obi_site_kenobi import resolve_site

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
    cursor = None

    while True:
        payload = {
            "query": EXPORT_ROOMS,
            "variables": {"params": {"cursor": cursor, "paging": "NEXT_PAGE"}},
        }
        try:
            response = requests.post(auth.GRAPHQL_URL, json=payload, headers=auth.get_headers())
            response.raise_for_status()
        except requests.RequestException as err:
            logger.error(f"Export request failed: {err}")
            break
        data = response.json()
        if data.get("errors"):
            logger.error(f"GraphQL error:\n{json.dumps(data['errors'], indent=2)}")
            break

        tenants = data.get("data", {}).get("tenants", [])
        room_data = tenants[0].get("roomData", {})
        edges = room_data.get("edges", [])
        page_info = room_data.get("pageInfo", {})

        for edge in edges:
            node = edge["node"]
            pretty_node_deets(node)
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

        console_log(f"Pagination: hasNextPage={has_next}, endCursor={cursor}")

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
    else:
        logger.warning("No room data found RUH ROH!")
    console_log(
        "🏁 [magenta]export_rooms()[/magenta] [blue]completed successfully with no errors[/blue]"
    )
    console_log(
        f"[blue]Total Rooms Exported:[/blue] [yellow]{total_rooms_exported}[/yellow]"
    )
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return


# GRAPHQL Mutation: Update Rooms
# for each row in the csv, map the data to the expected graphql argument field name, and send the request
def update_rooms():
    total_rooms_imported = 0
    total_errors = 0
    all_errors = []

    # read the csv
    try:
        dataframe = pd.read_csv("./room_data.csv")
        site_name_to_id = {}
        site_id_to_name = {}
    # handle any errors
    except Exception as ex:
        logger.error(f"Failed to read csv: {ex}")
        console.input("[dim]Press Enter to return to main menu[/dim]")
        return

    errors_occurred = False

    # loop through each csv row
    for index, row in dataframe.iterrows():
        # log row for debugging
        console_log(f"Row read from CSV {index}: {row.to_dict()}", style="dim")

        # Pull each value once for finalizing types
        raw_id = row.get("id")
        raw_name = row.get("name")
        raw_capacity = row.get("capacity")
        raw_size = row.get("size")
        raw_floor = row.get("floor")
        raw_site = row.get("siteId")
        raw_site_name = row.get("siteName")

        console_log(f"🔍 Resolving site for '{raw_site_name}':'{raw_site}'…", style="dim")

        try:
            site_id_value = resolve_site(raw_site, raw_site_name, site_name_to_id, site_id_to_name)
        except requests.RequestException as http_error:
            logger.error(f"Row {index}: HTTP error during site resolution: {http_error}")
            if http_error.response is not None:
                logger.debug(f"Reponse body:\n{http_error.response.text}")
            all_errors.append(f"row {index}: {http_error}")
            total_errors +=1
            continue
        except Exception as err:
            logger.error(f"Row {index}: site resolution failed: {err}")
            all_errors.append(f"row {index}: {err}")
            total_errors += 1
            continue

        room_id_value = None if pd.isna(raw_id) else str(raw_id)

        # if capacity is missing set it to None. otherwise, validate integer and convert to null (none) with warning on failure
        capacity_series = pd.to_numeric(pd.Series([raw_capacity]), errors="coerce")
        capacity_number = capacity_series.iloc[0]
        capacity_value = None if pd.isna(capacity_number) else int(capacity_number)

        if (
            pd.isna(capacity_number) and not pd.isna(raw_capacity) and str(raw_capacity).strip()
        ):
            console_log(
                f"[yellow]Warning:[/yellow] row {index} had [green]'capacity'[/green]:"
                f"[red]'{raw_capacity}'[/red], which isn't a number. "
                "It's been set to [blue]null[/blue] (None). "
                "See README › CSV Format: https://github.com/dfreshreed/lens-room-trooper "
                "for expected types. "
                "Fix value in [green]room_data.csv[/green] and run the import again.",
                style="bold",
            )

        # if no csv value use enum defined value
        size_value = raw_size if pd.notna(raw_size) else "NONE"

        # if floor is missing -> None, otherwise ensure string if floors are numbered
        floor_value = None if pd.isna(raw_floor) else str(int(raw_floor))

        #build room fields dictionary for payload
        room_fields = {
            "tenantId": auth.TENANT_ID,
            "id": room_id_value,
            "capacity": capacity_value,
            "size": size_value,
            "floor": floor_value,
            "siteId": site_id_value,
        }
        #trim name whitespace and ensure no empty string
        if pd.notna(raw_name) and str(raw_name).strip():
            room_fields["name"] = str(raw_name).strip()
        # build the update room payload structure
        console_log(f"Sending row {index}: {room_fields}", style="dim")
        payload = {"query": UPDATE_ROOMS, "variables": {"fields": room_fields}}

        try:
            # fire off the request and assign the response to a variable for error handling
            response = requests.post(auth.GRAPHQL_URL, json=payload, headers=auth.get_headers())
            response.raise_for_status()
            data = response.json()
            highlighted = highlight(json.dumps(data, indent=2), JsonLexer(), TerminalFormatter())
            if "errors" in data:
                # log GQL errors
                gql_error = f"GraphQL error at row {index}: \n{highlighted}"
                logger.error(gql_error)
                all_errors.append(gql_error)
                errors_occurred = True
                total_errors += 1
            else:
                # log successful GQL response
                logger.info(f"Row {index} updated: \n{highlighted}")
                total_rooms_imported += 1
        # log network or HTTP errors
        except requests.RequestException as err:
            http_err = f"Request error at row {index}: {err}"
            logger.error(http_err)
            all_errors.append(http_err)
            errors_occurred = True
            total_errors += 1
    if not errors_occurred:
        console_log(
            "🏁 [magenta]update_rooms()[/magenta] [blue]completed successfully with no errors.[/blue]"
        )
        console_log(
            f"[blue]Total Rooms Imported:[/blue] [yellow] {total_rooms_imported} [/yellow]"
        )
    else:
        console_log(
            f"⚠️ update_rooms() [red]failed with[/red] [yellow]{total_errors}[/yellow] [red]error(s).[/red]"
        )
        logger.error("Details on all errors: \n" + "\n".join(all_errors))
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return
