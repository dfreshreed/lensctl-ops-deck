import pandas as pd
import requests
import os
import json
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import TerminalFormatter
from rich.traceback import install
from rich.console import Console
from env_helper_util import get_required_env, logger, console_log, pretty_node_deets

install()  # colorize uncaught exceptions and tracebacks
console = Console()

headers = {"content-type": "application/json"}

# Lens GraphQL and Auth endpoints
token_url = get_required_env("AUTH_URL")
graphQL_url = get_required_env("LENS_EP")

# tenant identifiers
tenant_id = get_required_env("TENANT_ID")
site_id = os.getenv("SITE_ID")

# OAuth Creds
client_id = get_required_env("CLIENT_ID")
client_secret = get_required_env("CLIENT_SECRET")

# exchange lens api creds for access_token
request_token = requests.post(
    token_url,
    headers=headers,
    json={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    },
)

# store token in headers variable
headers["authorization"] = f"Bearer {request_token.json()['access_token']}"


def export_rooms():
    logger.info("Starting room export to csv")
    all_rooms = []
    total_rooms_exported = 0
    cursor = None

    export_query = """
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

    while True:
        payload = {
            "query": export_query,
            "variables": {"params": {"cursor": cursor, "paging": "NEXT_PAGE"}},
        }
        response = requests.post(graphQL_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
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
    # handle any errors
    except Exception as ex:
        logger.error(f"Failed to read csv: {ex}")
        console.input("[dim]Press Enter to return to main menu[/dim]")
        return

    # the lens api mutation to update room metadata
    graphql_mutation = """
    mutation updateRoomData($fields: UpsertRoomRequest!) {
      upsertRoom(fields: $fields) {
        name
        id
        capacity
        size
        updatedAt
        floor
        }
      }
    """

    errors_occurred = False

    # loop through each csv row
    for index, row in dataframe.iterrows():
        # log row for debugging
        console_log(f"Sending row {index}: {row.to_dict()}", style="dim")

        # Pull each value once for finalizing types
        raw_id = row.get("id")
        raw_capacity = row.get("capacity")
        raw_size = row.get("size")
        raw_floor = row.get("floor")
        raw_site = row.get("siteId")

        # if in .env use it, otherwise use the csv and convert to string or set to None
        site_id_value = (
            site_id if site_id else (str(raw_site) if pd.notna(raw_site) else None)
        )
        # if capacity is missing -> None, otherwise validate integer and convert to null (none) with warning
        capacity_series = pd.to_numeric(pd.Series([raw_capacity]), errors="coerce")
        capacity_number = capacity_series.iloc[0]
        capacity_value = None if pd.isna(capacity_number) else int(capacity_number)

        if (
            pd.isna(capacity_number)
            and not pd.isna(raw_capacity)
            and str(raw_capacity).strip()
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
        size_value = raw_size or "NONE"

        # if floor is missing -> None, otherwise ensure string if floors are numbered
        floor_value = None if pd.isna(raw_floor) else str(int(raw_floor))

        fields = {
            "tenantId": tenant_id,
            "siteId": site_id_value,
            "id": raw_id,
            "capacity": capacity_value,
            "size": size_value,
            "floor": floor_value,
        }

        total_rooms_imported += 1

        # build the payload structure
        payload = {"query": graphql_mutation, "variables": {"fields": fields}}

        try:
            # fire off the request and assign the response to a variable for error handling
            response = requests.post(graphQL_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            json_str = json.dumps(data, indent=2)
            highlighted = highlight(json_str, JsonLexer(), TerminalFormatter())
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
    console.input("[dim]Press Enter to return to main menu[/dim]")
    return
