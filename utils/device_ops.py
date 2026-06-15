from typing import List, Dict, Any, Optional
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
import threading

from utils import auth
from utils.env_helper import console_log, pretty_node_deets
from utils.compliance_analysis import parse_policy_attribution

Devices = Dict[str, Any]

DEVICE_LIST = """
  query deviceList($params: DeviceFindArgs, $tenantId: ID!) {
    calculateQueryCost {
      queryCost
      costUsed
      costRemaining
      secondsToReset
    }
    tenant(id: $tenantId) {
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
            releaseChannel
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
        id
        name
        priority
        type
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
                }
              }
            }
          }
        }
      }
    }
  }
"""

# Fragment for reusable policy structure
POLICY_CAPABILITIES_FRAGMENT = """
  capabilities {
    com {
      poly {
        software_update {
          policy {
            version { value }
            use_latest { value }
          }
        }
      }
    }
  }
  sources {
    id
    name
    priority
    type
    capabilities {
      com {
        poly {
          software_update {
            policy {
              version { value }
              use_latest { value }
            }
            policy_variations {
              version { value }
              use_latest { value }
              property_value { value }
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
    total_count: Optional[int] = None
    start = time.monotonic()
    last_progress = start
    next_token = None
    page_count = 0
    retry_count = 0
    MAX_RETRIES = 5

    while True:
        page_count += 1

        params = {
            "filter": {"contains": hardware_model_filter, "field": "hardwareModel"},
            "pageSize": 700,
        }

        if next_token:
            params["nextToken"] = next_token

        variables = {"tenantId": tenant_id, "params": params}

        try:
            data = auth.execute_gql(DEVICE_LIST, variables)
            retry_count = 0  # reset after each successful request

            if "errors" in data:
                console_log(
                    f"[red]GraphQL errors on page {page_count}:[/red] {data['errors']}"
                )
                break

            # check query cost and proactively wait if approaching rate limit
            cost_info = data.get("data", {}).get("calculateQueryCost", {})
            cost_remaining = cost_info.get("costRemaining")
            query_cost = cost_info.get("queryCost")
            cost_used = cost_info.get("costUsed")
            seconds_to_reset = cost_info.get("secondsToReset")

            if cost_remaining and query_cost:
                # if next page would likely exceed limit, wait for reset
                # use 1.2x buffer to account for cost variations
                if cost_remaining < query_cost * 1.2:
                    wait_time = (seconds_to_reset or 60) + 2  # +2s buffer
                    console_log(
                        f"[yellow]Rate limit approaching:[/yellow] "
                        f"{cost_remaining:,} points left, query costs {query_cost:,}. "
                        f"Waiting {wait_time}s for reset..."
                    )
                    time.sleep(wait_time)
                elif page_count == 1:
                    # log cost info on first page for visibility
                    console_log(
                        f"[dim]Query cost: {query_cost:,} | Used: {cost_used:,} | Remaining: {cost_remaining:,}[/dim]"
                    )

            tenant = data.get("data", {}).get("tenant", {})
            if not tenant:
                console_log(f"[yellow]No devices returned in GraphQL response")
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
                            f"  Fetched: [blue]{processed:,}/{total_count:,} ({pct:.1f}%) [/blue] | "
                            f"Pages: [blue]{page_count}[/blue] | {rate:,.0f}/s",
                        )
                    else:
                        console_log(
                            f"  Fetched {processed:,} | Pages [blue]{page_count}[/blue] | {rate:,.0f}/s"
                        )
                    last_progress = now

            if not (has_next_page and next_token):
                break

        except requests.RequestException as err:
            retryable = (
                isinstance(err, requests.HTTPError)
                and err.response is not None
                and err.response.status_code in (429, 502, 503, 504)
            )
            if retryable and retry_count < MAX_RETRIES:
                retry_count += 1
                backoff = min(5 * (2 ** (retry_count - 1)), 120)
                console_log(
                    f"[yellow]Error while fetching page {page_count} "
                    f"(attempt {retry_count}/{MAX_RETRIES}), retrying in {backoff}s...[/yellow] {err}"
                )
                page_count -= 1  # will be re-incremented at top of loop
                time.sleep(backoff)
            else:
                console_log(
                    f"[red]Error fetching devices on page {page_count}:[/red] {err}"
                )
                break

    return all_devices


def fetch_latest_software_version(
    catalog_id: str,
) -> tuple[Optional[str], Optional[str]]:

    variables = {
        "hardwareProductId": catalog_id,
        "params": {"sort": [{"field": "version", "direction": "DESC"}], "limit": 10},
    }
    try:
        data = auth.execute_gql(HARDWARE_PRODUCT, variables)

        if "errors" in data:
            reason = "GraphQL error"
            console_log(
                f"[red]GraphQL errors fetching latest GA software version for {catalog_id}:[/red] {data['errors']}"
            )
            return None, reason

        hardware_product = data.get("data", {}).get("hardwareProduct", {})
        edges = hardware_product.get("softwareReleases", {}).get("edges", [])

        if not edges:
            reason = "No releases found"
            console_log(f"[yellow]No software release found for {catalog_id}[/yellow]")
            return None, reason

        for edge in edges:
            node = edge.get("node", {})
            version = node.get("version")
            channel = node.get("releaseChannel")

            if channel not in ["preview", "beta", "marketing"]:
                if channel is not None:
                    console_log(
                        f"[yellow]Warning: Unknown release channel '{channel}' for version {version}. Treating as GA. [/yellow]"
                    )
                return version, None

        reason = "Only preview/beta releases available"
        console_log(
            f"[yellow]No GA release found for {catalog_id} (all are preview/beta)[/yellow]"
        )
        return None, reason

    except requests.RequestException as err:
        reason = f"Network error: {type(err).__name__}"
        console_log(
            f"[red]Error fetching latest GA software version for {catalog_id}:[/red] {err}"
        )
        return None, reason


def fetch_multiple_latest_versions(
    catalog_ids: List[str], labels: Dict[str, str] | None = None
) -> Dict[str, Optional[str]]:
    console_log("[bold]Fetching latest GA software versions...[/bold]")

    labels = labels or {}
    latest_versions = {}

    for catalog_id in catalog_ids:
        version, error_reason = fetch_latest_software_version(catalog_id)
        latest_versions[catalog_id] = version

        label = labels.get(catalog_id, catalog_id)

        if version:
            console_log(f"  [cyan]{label}:[/cyan] v{version}")
        else:
            console_log(f"  [yellow]{label}: Unable to fetch ({error_reason})[/yellow]")

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


def build_batch_policy_query(device_ids: List[str]) -> str:
    query_parts = [
        "query BatchDevicePolicies {",
        "  calculateQueryCost {",
        "    queryCost",
        "    costUsed",
        "    costRemaining",
        "    secondsToReset",
        "  }",
    ]

    for i, device_id in enumerate(device_ids):
        # sanitize device ID for GraphQL (escape quotes)
        safe_id = device_id.replace('"', '\\"')
        query_parts.append(
            f'  dev{i}: devicePolicyCapabilities(deviceId: "{safe_id}") {{'
        )
        query_parts.append(f"    {POLICY_CAPABILITIES_FRAGMENT}")
        query_parts.append("  }")

    query_parts.append("}")
    return "\n".join(query_parts)


def fetch_device_policy_batch(
    device_ids: List[str],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    query = build_batch_policy_query(device_ids)

    try:
        data = auth.execute_gql(query, {})

        if "errors" in data:
            console_log(
                f"[red]Error fetching policy batch ({len(device_ids)} devices): {data['errors']}[/red]"
            )
            return {}, {}

        result_data = data.get("data", {})
        cost_info = result_data.get("calculateQueryCost", {})

        # extract policy data from aliased responses
        policies = {}
        for i, device_id in enumerate(device_ids):
            alias = f"dev{i}"
            policy_stack = result_data.get(alias)
            if policy_stack:
                policies[device_id] = policy_stack

        return policies, cost_info

    except requests.RequestException as err:
        console_log(f"[red]Network error fetching policy batch: {err}[/red]")
        return {}, {}


def fetch_policy_attributions_concurrent(
    devices: List[Dict[str, Any]],
    max_workers: int = 2,
    batch_size: int = 25,
) -> tuple[int, int]:

    total = len(devices)
    completed = 0
    failed = 0
    failed_devices = []

    # split devices into batches
    device_batches = []
    for i in range(0, total, batch_size):
        batch = devices[i : i + batch_size]
        device_batches.append(batch)

    total_batches = len(device_batches)

    console_log(
        f"[bold]Fetching policy attribution for [blue]{total:,}[/blue] devices[/bold]"
    )
    console_log(
        f"  [dim]Using [blue]{total_batches:,}[/blue] batches of [blue]{batch_size}[/blue] with [blue]{max_workers}[/blue] workers[/dim]"
    )

    start_time = time.time()
    last_wait_log = 0

    # create device ID to device object mapping for quick lookup
    device_map = {device["id"]: device for device in devices}

    # track rate limit state
    last_cost_info = {}
    submission_lock = threading.Lock()
    retry_counts = {}  # track retry attempts per batch

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # don't submit all batches at once - submit gradually to control rate
        pending_batches = list(device_batches)
        active_futures = {}

        # submit initial wave of batches
        for _ in range(min(max_workers, len(pending_batches))):
            batch = pending_batches.pop(0)
            future = executor.submit(
                fetch_device_policy_batch, [d["id"] for d in batch]
            )
            active_futures[future] = batch

        try:
            while active_futures:
                # wait for at least one to complete
                done_futures, _ = wait(active_futures, return_when=FIRST_COMPLETED)

                for future in done_futures:
                    batch = active_futures.pop(future)

                    # initialize to prevent NoneType errors if exception occurs
                    cost_info = None
                    policies_dict = {}
                    needs_429_retry = False  # track if this batch needs retry

                    try:
                        policies_dict, cost_info = future.result(timeout=60)
                        last_cost_info = cost_info if cost_info else last_cost_info

                        # process each device in the batch
                        for device in batch:
                            device_id = device["id"]
                            policy_stack = policies_dict.get(device_id)

                            if policy_stack:
                                attribution = parse_policy_attribution(policy_stack)
                                device["policy_attribution"] = attribution
                                completed += 1
                            else:
                                device["policy_attribution"] = None
                                failed_devices.append(device)
                                failed += 1

                    except TimeoutError:
                        console_log(
                            f"[red]Timeout (60s) fetching batch of {len(batch)} devices[/red]"
                        )
                        for device in batch:
                            device["policy_attribution"] = None
                            failed_devices.append(device)
                            failed += 1

                    except Exception as exc:
                        error_msg = str(exc)
                        # check if it's a 429 rate limit error
                        if "429" in error_msg or "Too Many Requests" in error_msg:
                            # get batch ID for retry tracking
                            batch_id = id(batch)
                            retry_count = retry_counts.get(batch_id, 0)

                            if retry_count < 3:  # max 3 retries per batch
                                retry_counts[batch_id] = retry_count + 1
                                console_log(
                                    f"[yellow]429 Rate limit error - will retry batch "
                                    f"(attempt {retry_count + 1}/3, {len(batch)} devices)[/yellow]"
                                )
                                needs_429_retry = (
                                    True  # =flag for retry in lock section
                                )
                            else:
                                console_log(
                                    f"[red]429 Rate limit error - max retries exceeded for batch "
                                    f"of {len(batch)} devices, marking as failed[/red]"
                                )
                                for device in batch:
                                    device["policy_attribution"] = None
                                    failed_devices.append(device)
                                    failed += 1
                        else:
                            console_log(f"[red]Error fetching batch: {exc}[/red]")
                            for device in batch:
                                device["policy_attribution"] = None
                                failed_devices.append(device)
                                failed += 1

                    # progress reporting (outside lock to avoid blocking other workers)
                    processed = completed + failed
                    if processed % 1000 == 0 or processed == total:
                        elapsed = time.time() - start_time
                        rate = processed / elapsed if elapsed > 0 else 0
                        remaining_secs = (total - processed) / rate if rate > 0 else 0

                        console_log(
                            f"Progress: [blue]{processed:,}/{total:,} ({processed/total*100:.1f}%)[/blue] | "
                            f"[green]✓[/green] {completed:,} | [red]✗[/red] {failed} | "
                            f"Rate: [magenta]{rate:.1f}/sec[/magenta] | "
                            f"ETA: [bold]{remaining_secs/60:.1f} min[/bold]"
                        )

                    # CRITICAL SECTION: only one worker can check rate limits and submit at a time
                    with submission_lock:
                        # handle 429 retry → requeue batch if flagged for retry
                        if needs_429_retry:
                            # put failed batch back at front of queue (protected by lock)
                            pending_batches.insert(0, batch)
                            # force wait after 429 before processing more
                            console_log("[yellow]Waiting 10s before retry...[/yellow]")
                            time.sleep(10)

                        # check rate limits and wait if needed BEFORE submitting next batch
                        # use cost_info from this batch, or fall back to last known cost info
                        current_cost_info = cost_info or last_cost_info

                        if current_cost_info:
                            cost_remaining = current_cost_info.get("costRemaining")
                            query_cost = current_cost_info.get("queryCost")
                            seconds_to_reset = current_cost_info.get("secondsToReset")

                            if cost_remaining and query_cost:
                                # if next batch would exceed limit, wait (using 2.0x buffer for safety)
                                if cost_remaining < query_cost * 2.0:
                                    wait_time = (seconds_to_reset or 60) + 2
                                    current_time = time.time()

                                    # only log wait message once per minute
                                    if current_time - last_wait_log > 60:
                                        console_log(
                                            f"[yellow]Rate limit approaching:[/yellow] "
                                            f"{cost_remaining:,} points left. Waiting {wait_time}s..."
                                        )
                                        last_wait_log = current_time

                                    time.sleep(wait_time)

                        # submit next batch if available (AFTER rate limit check)
                        if pending_batches:
                            next_batch = pending_batches.pop(0)
                            next_future = executor.submit(
                                fetch_device_policy_batch, [d["id"] for d in next_batch]
                            )
                            active_futures[next_future] = next_batch

        except KeyboardInterrupt:
            console_log(
                "[yellow]Interrupted - cancelling remaining batches...[/yellow]"
            )
            for future in active_futures:
                future.cancel()
            raise

    console_log(
        f"  [green]Successful: {completed:,}[/green] | [red]Failed: {failed:,}[/red]"
    )

    if failed_devices and failed > 0:
        console_log(
            f"\n[yellow]Retrying {len(failed_devices):,} failed devices individually...[/yellow]"
        )

        retry_completed = 0
        retry_failed = 0

        # retry one at a time instead of batch
        with ThreadPoolExecutor(max_workers=2) as retry_executor:
            retry_futures = {
                retry_executor.submit(fetch_device_policy_stack, device["id"]): device
                for device in failed_devices
            }

            for future in as_completed(retry_futures):
                device = retry_futures[future]

                try:
                    policy_stack = future.result(timeout=30)
                    if policy_stack:
                        device["policy_attribution"] = parse_policy_attribution(
                            policy_stack
                        )
                        retry_completed += 1
                        completed += 1
                        failed -= 1
                    else:
                        retry_failed += 1

                except Exception:
                    retry_failed += 1

        console_log(
            f" Retry results: [green] ✓ {retry_completed}[/green] | [red]✗ {retry_failed}[/red]"
        )

    console_log(f"[green]Final: {completed:,} successful | {failed:,} failed[/green]")
    return completed, failed
