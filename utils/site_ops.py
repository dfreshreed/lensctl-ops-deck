import json
import requests
import pandas as pd
from utils.env_helper import logger
import utils.auth as auth


class SiteIdNotFoundError(Exception):
    """Raised when a siteId lookup fails because the site doesn't exist."""


QUERY_SITE_ID = """
    query getSiteById($id: String!) {
        site(id: $id) {
            id
            name
        }
    }
"""

QUERY_SITE_NAME = """
    query getSiteByName($tenantId: String!, $params: SiteConnectionParams) {
        siteData(tenantId: $tenantId, params: $params) {
            edges {
                node{
                    id
                    name
                }
            }
        }
    }
"""

CREATE_OR_UPDATE_SITE = """
    mutation upsertSite($fields: UpsertSiteRequest!) {
        upsertSite(fields: $fields) {
            id
            name
        }
    }
"""


def cache_set(
    site_id: str,
    name: str,
    site_id_to_name: dict[str, str],
    site_name_to_id: dict[str, str],
) -> None:
    # remove stale mapping
    previous = site_id_to_name.get(site_id)
    if previous and previous != name and site_name_to_id.get(previous) == site_id:
        del site_name_to_id[previous]
    # set both directions
    site_id_to_name[site_id] = name

    other = site_name_to_id.get(name)
    if other and other != site_id:
        logger.warning(
            "name '%s' was mapped to %s, overwriting with %s", name, other, site_id
        )

    site_name_to_id[name] = site_id


def fetch_site_name_by_id(csv_site_id: str) -> str:
    """use the provided .csv site id to query site name"""
    response = requests.post(
        auth.GRAPHQL_URL,
        json={"query": QUERY_SITE_ID, "variables": {"id": csv_site_id}},
        headers=auth.get_headers(),
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as http_err:
        # got a non-2xx error
        if http_err.response is not None:
            try:
                error_data = http_err.response.json().get("errors", [])
            except ValueError as parse_error:
                # couldn't parse json - likely 500
                logger.warning("Raising SiteIdNotFoundError ONE")
                logger.warning(f"Couldn't parse GraphQL error: {parse_error!r}")
                logger.debug(f"Rawr response: `{http_err.response.text!r}`")
            else:
                for err in error_data:
                    message = err.get("message", "").lower()
                    if (
                        "resource mapping failed" in message
                        or "internal server error" in message
                    ):
                        logger.warning("Known bad site found in room_data.csv")
                        logger.warning(
                            f"SiteIdNotFound error thrown for siteId → '{csv_site_id}' GraphQL lookup failed with: {message}"
                        )
                        raise SiteIdNotFoundError(
                            f"siteId '{csv_site_id}' doesn't exist in Lens. Failed GQL lookup: {message} Check your csv or add a siteName while leaving siteId blank to create a new site."
                        )
        # fallback re-raise
        raise
    # got a 200 so parse json and check for GQL errors
    data = response.json()
    if data.get("errors"):
        for err in data["errors"]:
            message = err.get("message", "").lower()
            if (
                "resource mapping failed" in message
                or "internal server error" in message
            ):
                logger.warning("Raising SiteIdNotFoundError in 200-OK payload")
                raise SiteIdNotFoundError(
                    f"GQL query error for siteId '{csv_site_id}': {message} doesn't exist in Lens. Check your csv or add a siteName while leaving siteId blank to create a new site."
                )
        raise RuntimeError(f"GraphQL getSiteById failed: {data['errors']}")

    site = (data.get("data") or {}).get("site")
    if not site:
        raise SiteIdNotFoundError(f"siteId '{csv_site_id}' not found")

    name = site.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError(
            f"GraphQL getSiteById returned a site without a name for siteId '{csv_site_id}'"
        )
    return name


def fetch_site_id_by_name(csv_site_name: str) -> str | None:
    lookup_payload = {
        "query": QUERY_SITE_NAME,
        "variables": {
            "tenantId": auth.TENANT_ID,
            "params": {
                "filter": [
                    {
                        "field": "NAME",
                        "comparisonOperator": "EQUALS",
                        "value": csv_site_name,
                    }
                ],
                "limit": 1,
            },
        },
    }
    response = requests.post(
        auth.GRAPHQL_URL, json=lookup_payload, headers=auth.get_headers()
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(f"GraphQL error getting Site by Name: {data['errors']}")

    edges = data["data"]["siteData"]["edges"]

    if edges:
        return edges[0]["node"]["id"]

    return None


def rename_site(csv_site_id: str, csv_site_name: str) -> str:
    """rename an existing site to name provided in .csv"""
    rename_site_payload = {
        "query": CREATE_OR_UPDATE_SITE,
        "variables": {
            "fields": {
                "tenantId": auth.TENANT_ID,
                "id": csv_site_id,
                "name": csv_site_name,
            }
        },
    }
    rename_response = requests.post(
        auth.GRAPHQL_URL, json=rename_site_payload, headers=auth.get_headers()
    )
    try:
        rename_response.raise_for_status()
    except requests.HTTPError as http_err:
        logger.error(f"rename_site HTTP {rename_response.status_code}: {http_err}")
        logger.debug(f"payload:\n{json.dumps(rename_site_payload, indent=2)}")
        logger.debug(f"response body: \n{rename_response.text}")
        raise
    data = rename_response.json()
    if data.get("errors"):
        raise RuntimeError(f"GraphQL error while renaming the site: {data['errors']}")
    return data["data"]["upsertSite"]["name"]


def create_site_if_not_exists(csv_site_name: str) -> str:
    existing = fetch_site_id_by_name(csv_site_name)
    if existing:
        return existing

    create_site_payload = {
        "query": CREATE_OR_UPDATE_SITE,
        "variables": {"fields": {"tenantId": auth.TENANT_ID, "name": csv_site_name}},
    }

    create_response = requests.post(
        auth.GRAPHQL_URL,
        json=create_site_payload,
        headers=auth.get_headers(),
    )
    create_response.raise_for_status()
    data = create_response.json()
    if data.get("errors"):
        raise RuntimeError(f"Error creating site: {data['errors']}")
    return data["data"]["upsertSite"]["id"]


def resolve_site(
    csv_site_id: str | None,
    csv_site_name: str | None,
    site_name_to_id: dict[str, str],
    site_id_to_name: dict[str, str],
):
    """
    resolve a siteId by: [1] Env override, [2] .csv provided Id, [3] querying by .csv name
    if query doesn't find by name, it creates the site, and the room will be assigned to it
    """
    csv_site_id = (
        auth.SITE_ID
        if auth.SITE_ID
        else (str(csv_site_id) if pd.notna(csv_site_id) else None)
    )
    raw = str(csv_site_name) if pd.notna(csv_site_name) else None
    csv_site_name = raw.strip() if raw and raw.strip() else None

    if csv_site_id:
        # check if .csv siteName matches cache or Lens site record.
        current_name = site_id_to_name.get(csv_site_id)
        if current_name is None:
            try:
                fetched = fetch_site_name_by_id(csv_site_id)
            except SiteIdNotFoundError as known:
                # logger.debug(f"Known bad siteId found in room_data.csv, re-reraising: {known}")
                raise
            except Exception as exc:
                logger.error(
                    f"Unexpected error fetching site name for siteId {csv_site_id}: {exc}"
                )
                raise
            current_name = fetched
        # cache it
        cache_set(
            csv_site_id,
            current_name,
            site_id_to_name,
            site_name_to_id,
        )

        # guard: if target name already exists, use that site (id) instead of renaming
        if csv_site_name and csv_site_name != current_name:
            target_id = site_name_to_id.get(csv_site_name) or fetch_site_id_by_name(
                csv_site_name
            )
            # name already belongs to a site, don't rename
            if target_id and target_id != csv_site_id:
                cache_set(target_id, csv_site_name, site_id_to_name, site_name_to_id)
                return target_id

            # if .csv site name differs from queried or cached, rename the site
            new_name = rename_site(csv_site_id, csv_site_name)

            # update cache with new site name
            cache_set(csv_site_id, new_name, site_id_to_name, site_name_to_id)

        return csv_site_id
    # if no siteId in .csv, resolve the site by name
    if csv_site_name is not None and csv_site_name.strip():
        name = csv_site_name.strip()
        cached_id = site_name_to_id.get(name)

        if cached_id is not None:
            return cached_id

        new_site_id = create_site_if_not_exists(name)
        # update cache with new site name
        cache_set(new_site_id, name, site_id_to_name, site_name_to_id)

        return new_site_id
    return None
