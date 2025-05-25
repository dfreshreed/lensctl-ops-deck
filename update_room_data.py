import pandas as pd
import requests
import sys
import json
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import TerminalFormatter
from rich.traceback import install
from env_helper_util import get_required_env, logger

install()  # colorize uncaught exceptions and tracebacks

headers = {"content-type": "application/json"}

# Lens GraphQL and Auth endpoints
token_url = get_required_env("AUTH_URL")
graphQL_url = get_required_env("LENS_EP")

# tenant identifiers
tenant_id = get_required_env("TENANT_ID")
site_id = get_required_env("SITE_ID")

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
        # logger.debug(data)
        if "errors" in data:
            logger.error(f"GraphQL error:\n{json.dumps(data['errors'], indent=2)}")
            break

        tenants = data.get("data", {}).get("tenants", [])
        room_data = tenants[0].get("roomData", {})
        edges = room_data.get("edges", [])
        page_info = room_data.get("pageInfo", {})

        for edge in edges:
            node = edge["node"]
            logger.info(f"Node: {node}")
            total_rooms_exported += 1
            all_rooms.append(
                {
                    "name": node.get("name"),
                    "id": node.get("id"),
                    "capacity": node.get("capacity"),
                    "size": node.get("size"),
                    "floor": node.get("floor"),
                    "siteName": node.get("site", {}).get("name"),
                    "siteId": node.get("site", {}).get("id"),
                }
            )

        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

        logger.info(f"Pagination: hasNextPage={has_next}, endCursor={cursor}")

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
        logger.info("Room Data exported to room_data.csv")
    else:
        logger.warning("No room data found RUH ROH!")
    logger.info("🏁 export_rooms() completed successfully.")
    logger.info(f"Total Rooms Exported: {total_rooms_exported}")


# GRAPHQL Mutation: Update Rooms
# for each row in the csv, map the data to the expected graphql argument field name, and send the request
def update_rooms():
    # read the csv
    try:
        dataframe = pd.read_csv("./room_data.csv")
    # handle any errors
    except Exception as ex:
        logger.error(f"Failed to read csv: {ex}")
        sys.exit(1)

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
        fields = {
            "tenantId": tenant_id,
            "siteId": row.get("siteId") or site_id,
            "id": row.get("id"),
            "capacity": row.get("capacity"),
            "size": row.get("size"),
            # convert number to string to avoid NaN GQL errors
            "floor": str(row.get("floor")) if not pd.isna(row.get("floor")) else None,
        }

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
                # log the error if present
                logger.error(f"GraphQL error at row {index}: \n{highlighted}")
                errors_occurred = True
            else:
                # log the success if no error
                logger.info(f"Row {index} updated: \n{highlighted}")
        except requests.RequestException as err:
            logger.error(f"Request error at row {index}: {err}")
            errors_occurred = True

    if not errors_occurred:
        logger.info("🏁 update_rooms() completed successfully with no errors.")
    else:
        logger.warning("⚠️ update_rooms() completed with one or more errors.")
