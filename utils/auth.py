import requests
import os
from rich.traceback import install
from utils.env_helper import get_required_env, logger
from typing import Optional, Dict, Any

install()  # colorize uncaught exceptions and tracebacks
# -------------------------
# config constants
# -------------------------

# lens GQL and Auth endpoints
TOKEN_URL = get_required_env("AUTH_URL")
GRAPHQL_URL = get_required_env("LENS_EP")

# tenant identifiers
TENANT_ID = get_required_env("TENANT_ID")
SITE_ID = os.getenv("SITE_ID")

# lens "api connection" creds
CLIENT_ID = get_required_env("CLIENT_ID")
CLIENT_SECRET = get_required_env("CLIENT_SECRET")

GET_CLIENT_DETAILS = """
query ClientCredential($clientCredentialId: String!) {
  clientCredential(id: $clientCredentialId) {
    name
    accessor {
      grants {
        roles {
          name
        }
      }
    }
  }
}
"""

# ---------------------------------
# internal private module helpers
# no touchy
# ---------------------------------

_token_cache: Optional[str] = None
_headers: Dict[str, str] = {"content-type": "application/json"}


def _token_request() -> str:
    global _token_cache
    if _token_cache:
        return _token_cache

    auth_payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
    }
    auth_response = requests.post(TOKEN_URL, headers=_headers, json=auth_payload)
    try:
        auth_response.raise_for_status()
    except requests.HTTPError as exception:
        logger.error(
            f"The Auth token request failed: {exception}\n {auth_response.text}"
        )
        raise
    data = auth_response.json()
    token = data.get("access_token")
    if not token:
        logger.error(f"The Auth response doesn't contain a token: {data}")
        raise RuntimeError("Auth Token Fetch Failed")
    _token_cache = token
    return token


# ---------------------------------
# public functions used in project
# ---------------------------------


def get_headers() -> Dict[str, Any]:
    token = _token_request()
    return {**_headers, "authorization": f"Bearer {token}"}


def execute_gql(
    query: str, variables: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    response = requests.post(GRAPHQL_URL, headers=get_headers(), json=payload)
    try:
        response.raise_for_status()
    except requests.HTTPError as exception:
        logger.error(f"GraphQL request failed...whomp: {exception}{response.text}")
        raise
    return response.json()


def get_client_details(client_id: str, *, timeout: int = 10) -> Dict[str, Any]:
    cid = client_id or CLIENT_ID
    if not cid:
        raise RuntimeError("CLIENT_ID is not set in .env file")
    payload = {
        "query": GET_CLIENT_DETAILS,
        "variables": {"clientCredentialId": cid},
    }
    response = requests.post(
        GRAPHQL_URL, headers=get_headers(), json=payload, timeout=timeout
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))
    creds = data["data"]["clientCredential"]
    name = creds["name"]
    role = ""
    for grant in creds.get("accessor", {}).get("grants", []):
        for role_obj in grant.get("roles") or []:
            if role_obj and role_obj.get("name"):
                role = role_obj["name"]
                break
            if role:
                break
    return {"name": name, "role": role}
