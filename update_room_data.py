import pandas as pd
import requests
import coloredlogs
import logging
import sys
import json
import os
from dotenv import load_dotenv
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import TerminalFormatter

load_dotenv() #load environment variables

headers = {'content-type': 'application/json'}
token_url = 'https://login.lens.poly.com/oauth/token'
graphQL_url = 'https://api.silica-prod01.io.lens.poly.com/graphql/'
tenant_id = os.getenv("TENANT_ID")
site_id = os.gentenv("SITE_ID")
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")

#configure logging
logger=logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger)

# exchange lens api creds for access_token
request_token = requests.post(token_url, headers=headers, json= {
  "client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"})

# store token in headers variable
headers['authorization'] = f"Bearer {request_token.json()['access_token']}"

# for each row in the csv, map the data to the expected graphql argument field name, and send the request
def update_rooms():
  # read the csv
    try: dataframe = pd.read_csv('./room_data.csv')
  # handle any errors
    except Exception as e:
        logging.error(f"Failed to read csv: {e}")
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
        }
      }
    """
  #loop through each csv row
    for index, row in dataframe.iterrows():
        fields = {
          "tenantId": tenant_id,
          "siteId": site_id,
          "id": row.get("id"),
          "capacity": row.get("capacity"),
          "size": row.get("size"),
          "floor": str(row.get("floor")) if not pd.isna(row.get("floor")) else None #convert number to string
        }

      # build the payload structure
        payload = {
          "query": graphql_mutation,
          "variables": {
            "fields": fields
          }
        }

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
            else:
                # log the success if no error
                logger.info(f"Row {index} updated: \n{highlighted}")
        except requests.RequestException as er:
            logger.error(f"Request error at row {index}: {er}")

update_rooms()