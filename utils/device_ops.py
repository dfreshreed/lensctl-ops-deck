from typing import List, Dict, Any, Optional
import requests
import time

from utils import auth
from utils.env_helper import console_log, pretty_node_deets

Devices = Dict[str, Any]

DEVICE_LIST = """
  query deviceList($params: DeviceFindArgs, $tenantId: ID!) {
    tenant(id: $tenantId) {
      id
      name
      region {
        id
      }
      inventory {
        deviceSearch(params: $params) {
          edges {
            node {
              id
              name
              hardwareModel
              hardwareProduct
              softwareVersion
              user {
                email
              }
            }
          }
          pageInfo {
            hasNextPage
            nextToken
            totalCount
          }
        }
        deviceCount
      }
    }
  }
"""

HARDWARE_PRODUCT = """
  query HardwareProduct($hardwareProductId: ID!, $params: SoftwareConnectionParams) {
    hardwareProduct(id: $hardwareProductId) {
      name
      softwareReleases(params: $params) {
        edges {
          node {
            version
            publishDate
          }
        }
      }
    }
  }
"""

DEVICE_POLICY_CAPABILITIES = """
  query DevicePolicyCapabilities($deviceId: String!) {
    devicePolicyCapabilities(deviceId: $deviceId) {
      capabilities {
        com {
          poly {
            software_update {
              policy {
                version {
                  value
                }
                use_latest {
                  value
                }
              }
            }
          }
        }
      }
      sources {
        collectionId
        id
        name
        priority
        settingsCount
        type
        collectionRule {
          type
          value
        }
        capabilities {
          com {
            poly {
              software_update {
                policy {
                  version {
                    value
                  }
                  use_latest {
                    value
                  }
                  property_value {
                    value
                  }
                }
                policy_variations {
                  version {
                    value
                  }
                  use_latest {
                    value
                  }
                  property_value {
                    value
                  }
                  property_path {
                    value
                  }
                }
              }
            }
          }
        }
      }
    }
  }
"""


def fetch_devices_by_model(
    tenant_id: str,
    hardware_model_filter: str,
    log_prefix: str = "devices",
    *,
    debug_nodes: bool = False,
    sample_nodes: int = 0,
    progress: bool = True,
    progress_interval_s: float = 1.0,
) -> List[Devices]:

    console_log(f"[bold]Fetching {log_prefix}...[/bold]")

    all_devices: List[Devices] = []
    all_errors = []
    total_count: Optional[int] = None
    start = time.monotonic()
    last_progress = start
    total_errors = 0
    next_token = None
    page_count = 0

    while True:
        page_count += 1

        params = {
            "filter": {"contains": hardware_model_filter, "field": "hardwareModel"},
            "pageSize": 500,
        }

        if next_token:
            params["nextToken"] = next_token

        variables = {"tenantId": tenant_id, "params": params}

        try:
            data = auth.execute_gql(DEVICE_LIST, variables)

            if "errors" in data:
                console_log(
                    f"[red]GraphQL errors on page {page_count}:[/red] {data['errors']}"
                )
                break

            tenant = data.get("data", {}).get("tenant", {})
            if not tenant:
                console_log(f"[yellow]No devices returned in GraphQL response")
                all_errors.append(
                    f"No {hardware_model_filter} models returned in GQL response"
                )
                total_errors += 1
                break
            inventory = tenant.get("inventory", {})
            device_search = inventory.get("deviceSearch", {})

            edges = device_search.get("edges", [])
            page_info = device_search.get("pageInfo", {})  # or {}

            if total_count is None:
                total_count = page_info.get("totalCount")

            for edge in edges:
                node = edge.get("node", {})
                if debug_nodes or (sample_nodes and len(all_devices) < sample_nodes):
                    pretty_node_deets(node, pad_braces=True)
                device = {
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "hardwareModel": node.get("hardwareModel"),
                    "hardwareProduct": node.get("hardwareProduct"),
                    "softwareVersion": node.get("softwareVersion"),
                    "user_email": (
                        node.get("user", {}).get("email") if node.get("user") else None
                    ),
                }
                all_devices.append(device)

            has_next_page = page_info.get("hasNextPage", False)
            next_token = page_info.get("nextToken")

            if progress:
                now = time.monotonic()
                done = not (has_next_page and next_token)
                if done or (now - last_progress) >= progress_interval_s:
                    processed = len(all_devices)
                    elapsed = max(now - start, 0.001)
                    rate = processed / elapsed

                    if total_count:
                        pct = processed / total_count * 100
                        console_log(
                            f"  Fetched [blue]{processed:,}/{total_count:,} ({pct:.1f}%) [/blue] | "
                            f"pages {page_count} | {rate:,.0f}/s",
                        )
                    else:
                        console_log(
                            f"  Fetched {processed:,} | pages {page_count} | {rate:,.0f}/s"
                        )
                    last_progress = now

            if not (has_next_page and next_token):
                break

        except requests.RequestException as err:
            console_log(
                f"[red]Error fetching devices on page {page_count}:[/red] {err}"
            )
            break

    return all_devices


def fetch_latest_software_version(catalog_id: str) -> Optional[str]:
    variables = {
        "hardwareProductId": catalog_id,
        "params": {"sort": [{"field": "version", "direction": "DESC"}], "limit": 1},
    }
    try:
        data = auth.execute_gql(HARDWARE_PRODUCT, variables)

        if "errors" in data:
            console_log(
                f"[red]GraphQL errors fetching latest GA software version for {catalog_id}:[/red] {data['errors']}"
            )

        hardware_product = data.get("data", {}).get("hardwareProduct", {})
        edges = hardware_product.get("softwareReleases", {}).get("edges", [])

        if not edges:
            console_log(f"[yellow]No software release found for {catalog_id}[/yellow]")
            return None

        latest_version = edges[0].get("node", {}).get("version")
        return latest_version

    except requests.RequestException as err:
        console_log(
            f"[red]Error fetching latest GA software version for {catalog_id}:[/red] {err}"
        )
        return None


def fetch_multiple_latest_versions(
    catalog_ids: List[str], labels: Dict[str, str] | None = None
) -> Dict[str, Optional[str]]:
    console_log("[bold]Fetching latest GA software versions...[/bold]")

    labels = labels or {}
    latest_versions = {}

    for catalog_id in catalog_ids:
        version = fetch_latest_software_version(catalog_id)
        latest_versions[catalog_id] = version

        label = labels.get(catalog_id, catalog_id)

        if version:
            console_log(f"  [cyan]{label}:[/cyan] v{version}")
        else:
            console_log(f"  [yellow]{label}: Unable to fetch[/yellow]")

    return latest_versions


def fetch_device_policy_stack(device_id: str) -> Dict[str, Any]:
    # fetch policy stack for each device

    variables = {"deviceId": device_id}

    try:
        data = auth.execute_gql(DEVICE_POLICY_CAPABILITIES, variables)

        if "errors" in data:
            console_log(
                f"Error fetching policy details for device {device_id}: {data['errors']}"
            )
            return {}

        return data.get("data", {}).get("devicePolicyCapabilities", {})

    except requests.RequestException as err:
        console_log(f"Error fetching device policy: {err}")
        return {}
