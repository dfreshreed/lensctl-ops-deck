import csv
from typing import List, Dict, Any
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import print as pr
from rich.columns import Columns
import re
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import auth
from utils.env_helper import console_log, console
from utils.input_helpers import menu_return, ask_int, ask_str

from utils.device_ops import (
    fetch_devices_by_model,
    fetch_multiple_latest_versions,
    fetch_device_policy_stack,
)

PLATFORM_CATALOG_MAP = {
    "Lens Desktop Mac": "lens-desktop-mac",
    "Lens Desktop Windows": "lens-desktop-windows",
}

# ---------------------------------
# internal private helpers
# no touchy
# ---------------------------------


def _normalize_platform(hardware_product: str) -> str:
    if not hardware_product:
        return "Unknown"
    # Case-insensitive matching for Mac/macOS and Windows
    hardware_lower = hardware_product.lower()
    if "mac" in hardware_lower:
        return "Lens Desktop Mac"
    elif "windows" in hardware_lower:
        return "Lens Desktop Windows"
    else:
        return hardware_product


def _get_catalog_id(hardware_product: str | None) -> str | None:
    if not hardware_product:
        return None
    platform = _normalize_platform(hardware_product)
    return PLATFORM_CATALOG_MAP.get(platform)


def _normalize_version(version: str | None) -> str:
    if not version or version == "Unknown":
        return "Unknown"
    parts = version.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else version


# ---------------------------------
# LD Specific
# ---------------------------------


def parse_policy_attribution(policy_stack: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse device policy stack to determine:
    1. Effective policy (top-level capabilities)
    2. Controlling layer (which source is "winning")
    3. All applicable layers
    4. Account model baseline for comparison

    Returns:
        {
            "effective": {"version": "2.2.0", "use_latest": False},
            "controlling_layer": {
                "type": "device",
                "name": "Lens Desktop Device(...) Update Policy",
                "priority": 0,
                "id": "720c05f4-4ab5-4d87-90cd-277ac51f655e"
            },
            "all_layers": [
                {"type": "device", "priority": 0, "name": "...", "has_settings": True},
                {"type": "user_group", "priority": 0.3, "name": "...", "has_settings": False},
                {"type": "site", "priority": 1, "name": "...", "has_settings": False},
                {"type": "model", "priority": 3, "name": "...", "has_settings": False}
            ],
            "account_policy": {"version": None, "use_latest": False}  # From model layer
        }
    """
    # Get effective policy from capabilities
    capabilities = policy_stack.get("capabilities") or {}
    sw_update = capabilities.get("com", {}).get("poly", {}).get("software_update", {})
    policy = sw_update.get("policy")

    version_obj = policy.get("version") or {}
    effective_version = version_obj.get("value")

    use_latest_obj = policy.get("use_latest") or {}
    effective_use_latest = use_latest_obj.get("value")

    effective = {"version": effective_version, "use_latest": effective_use_latest}

    # parse sources to find contolling policy layer
    sources = policy_stack.get("sources", [])

    # sort by priority - lower number = higher priority
    sorted_sources = sorted(sources, key=lambda s: float(s.get("priority", 999)))

    controlling_layer = None
    account_policy = None
    all_layers = []

    for source in sorted_sources:
        source_type = source.get("type")
        source_priority = float(source.get("priority", 999))
        source_name = source.get("name", "Unknown")
        source_id = source.get("id")

        # console_log(
        #     f"[dim]Processing source: type={source_type}, priority={source_priority}, name={source_name[:50]}...[/dim]"
        # )

        # check if this source has configured settings
        source_caps = source.get("capabilities") or {}
        source_sw = (
            source_caps.get("com", {}).get("poly", {}).get("software_update", {})
        )
        source_policy = source_sw.get("policy")
        policy_variations = source_sw.get("policy_variations") or {}

        policy_has_values = False
        if source_policy:
            version = source_policy.get("version", {})
            use_latest = source_policy.get("use_latest", {})
            policy_has_values = (version and version.get("value") is not None) or (
                use_latest and use_latest.get("value") is not None
            )

        # has settings if either policy has values or policy_variations exists
        has_settings = policy_has_values or len(policy_variations) > 0

        # console_log(
        #     f"[dim]  policy_has_values={policy_has_values}, policy_variations len={len(policy_variations)}, has_settings={has_settings}[/dim]"
        # )

        layer_info = {
            "type": source_type,
            "priority": source_priority,
            "name": source_name,
            "id": source_id,
            "has_settings": has_settings,
            "settings": None,
        }

        # if settings, extract em
        if has_settings:
            if len(policy_variations) > 0:
                # store platform specific variations
                layer_info["settings"] = {
                    "has_variations": True,
                    "variations": policy_variations,
                    "version": None,
                    "use_latest": None,
                }
            elif source_policy:
                # simple policy (device)
                version_obj = source_policy.get("version") or {}
                use_latest_obj = source_policy.get("use_latest") or {}
                layer_info["settings"] = {
                    "has_variations": False,
                    "variations": None,
                    "version": version_obj.get("value"),
                    "use_latest": use_latest_obj.get("value"),
                }
        all_layers.append(layer_info)
        # console_log(
        #     f"[dim]  Added to all_layers. Total layers now: {len(all_layers)}[/dim]"
        # )

        # first source w/ settings is controlling (applied) policy
        if has_settings and not controlling_layer:
            controlling_layer = layer_info

        # track account model policy for baseline comparison
        if source_type == "model":
            account_policy = (
                layer_info["settings"]
                if has_settings
                else {"version": None, "use_latest": False}
            )

    # 🔍 DEBUG: Log if no controlling layer was found (after processing all sources)
    if not controlling_layer:
        console_log(f"[red]⚠️  No controlling layer found in policy stack[/red]")
        console_log(f"  Sources count: {len(sorted_sources)}")
        console_log(f"  All layers: {all_layers}")
        for layer in all_layers:
            console_log(f"    - {layer['type']}: has_settings={layer['has_settings']}")

    return {
        "effective": effective,
        "controlling_layer": controlling_layer,
        "all_layers": all_layers,
        "account_policy": account_policy or {"version": None, "use_latest": False},
    }


def extract_unique_policies(devices: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Parse all device policy stacks to find unique policies by layer.

    Returns:
        {
            "model": [{"id": "f82eb...", "name": "Lens Desktop Model...", "priority": 3}],
            "site": [{"id": "97dbece...", "name": "Site(US-GVL-DRHO)", "priority": 1}],
            "user_group": [{"id": "f510d6...", "name": "Team Test", "priority": 0.3}]
        }
    """
    policies_by_type = {"model": {}, "site": {}, "user_group": {}, "device": {}}

    for device in devices:
        attribution = device.get("policy_attribution", {})
        all_layers = attribution.get("all_layers", [])

        for layer in all_layers:
            policy_type = layer.get("type")
            policy_id = layer.get("id")
            has_settings = layer.get("has_settings", False)

            if (
                policy_type in policies_by_type
                and policy_id not in policies_by_type[policy_type]
            ):
                policies_by_type[policy_type][policy_id] = {
                    "id": policy_id,
                    "name": layer.get("name"),
                    "priority": float(layer.get("priority", 999)),
                    "type": policy_type,
                    "has_settings": has_settings,
                    "settings": layer.get("settings", {}),
                }

    return {
        layer: list(policies.values()) for layer, policies in policies_by_type.items()
    }


def prompt_compliance_target(
    unique_policies: Dict[str, List[Dict]],
) -> Dict[str, Any] | None:
    """
    prompt user for which policy layer they're measuring compliance against
    only show policies that have explicit settings configured
    """

    console.print()
    console.print(
        "[bold cyan]Select Policy Compliance Measurement Baseline[/bold cyan]"
    )
    console.print("[dim]─[/dim]" * 100)
    console.print()
    console.print(
        "[white]Choose which policy layer to measure compliance against:[/white]\n"
        "  [dim]• Each device will be compared to the software version specified in your selected baseline.[/dim]\n"
        "  [dim]• Results show which devices match ([green]compliant[/green]) or differ ([yellow]non-compliant[/yellow]) from that baseline.[/dim]\n"
        "  [dim]• Compliance summary displays below. Full per-device details export to [cyan]lens-desktop-compliance.csv[/cyan][/dim]\n"
        "\n"
        "  [dim]• Example: If you're using Account Model Policy to specify a version and want to know how many devices are compliant, select option 1.[/dim]"
    )
    console.print("[dim]─[/dim]" * 100)
    console.print()

    options = []

    # option 1: account model
    model_policies_with_settings = [
        p for p in unique_policies["model"] if p["has_settings"]
    ]
    if model_policies_with_settings:
        model_policy = model_policies_with_settings[0]
        options.append(
            {
                "key": str(len(options) + 1),
                "display": f"Account Model Policy: {model_policy['name']}",
                "policy": model_policy,
                "layer": "model",
            }
        )

    # option 2: specific site
    site_policies_with_settings = [
        p for p in unique_policies["site"] if p["has_settings"]
    ]
    if site_policies_with_settings:
        options.append(
            {
                "key": str(len(options) + 1),
                "display": f"Site Policy: ({len(site_policies_with_settings)} available)",
                "layer": "site",
                "submenu": True,
                "policies": site_policies_with_settings,
            }
        )

    # option 3: User Group
    group_policies_with_settings = [
        p for p in unique_policies["user_group"] if p["has_settings"]
    ]
    if group_policies_with_settings:
        options.append(
            {
                "key": str(len(options) + 1),
                "display": f"Group Policy: ({len(group_policies_with_settings)} available)",
                "layer": "user_group",
                "submenu": True,
                "policies": group_policies_with_settings,
            }
        )

    # display menu
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan", width=4)
    table.add_column("Option", style="white")

    for opt in options:
        table.add_row(opt["key"], opt["display"])

    # add exit option
    table.add_row("0", "[dim]Exit to task list[/dim]")

    console.print(table)
    console.print()

    # get user choice
    choice = ask_int("Select option", default=1, min_value=0)

    # handle exit
    if choice == 0:
        return None

    selected = next((opt for opt in options if int(opt["key"]) == choice), None)

    if not selected:
        console_log("[red]Invalid selection[/red]")
        return None

    if selected.get("submenu"):
        return _select_from_submenu(selected["policies"], selected["layer"])

    return selected


def _select_from_submenu(
    policies: List[Dict], layer_type: str
) -> Dict[str, Any] | None:
    """
    show submunue for selecting specific site/group/device policy.
    accepts pre-filtered policies list
    """

    console.print()
    console_log(f"[bold]Select {layer_type.replace('_', '').title()}[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=4, justify="right")
    table.add_column("Name", style="yellow", width=50, no_wrap=False)
    table.add_column("Priority", style="white", justify="right")

    layer_name = (
        "Sites"
        if layer_type == "site"
        else "Groups" if layer_type == "user_group" else layer_type
    )
    table.add_row(
        "0",
        f"[bold]All {layer_name} (each compared to its own {layer_type} policy)[/bold]",
        "",
    )

    for index, policy in enumerate(policies, 1):
        table.add_row(str(index), policy["name"], str(policy["priority"]))

    console.print(table)
    console.print()

    choice = ask_int("Select Policy Number", default=0, min_value=0)

    if choice == 0:
        return {
            "layer": layer_type,
            "all_policies": True,
            "policies": policies,
            "display": f"All {layer_name}",
        }

    if 1 <= choice <= len(policies):
        selected_policy = policies[choice - 1]
        return {
            "layer": layer_type,
            "policy": selected_policy,
            "all_policies": False,
            "display": selected_policy["name"],
        }
    return None


def _get_baseline_version_for_device(
    device: Dict[str, Any],
    compliance_baseline: Dict[str, Any],
    latest_versions: Dict[str, str | None],
) -> str:
    """
    Docstring for _get_baseline_version_for_device

    :param device: Description
    :type device: Dict[str, Any]
    :param compliance_baseline: Description
    :type compliance_baseline: Dict[str, Any]
    :param latest_versions: Description
    :type latest_versions: Dict[str, str | None]
    :return: Description
    :rtype: str

    returns normalized version string or "N/A" if baseline doesn't apply
    """

    baseline_layer = compliance_baseline.get("layer")

    if compliance_baseline.get("all_policies"):
        attribution = device.get("policy_attribution", {})
        all_layers = attribution.get("all_layers", [])

        matching_layer = None
        for layer in all_layers:
            if layer.get("type") == baseline_layer:
                matching_layer = layer
                break
        if not matching_layer:
            return "N/A"

        settings = matching_layer.get("settings", {})

    # specific policy layer
    baseline_policy = compliance_baseline.get("policy", {})
    baseline_policy_id = baseline_policy.get("id")

    # find this policy in the device's stack
    attribution = device.get("policy_attribution", {})
    all_layers = attribution.get("all_layers", [])

    matching_layer = None
    for layer in all_layers:
        if layer.get("id") == baseline_policy_id:
            matching_layer = layer
            break
    if not matching_layer:
        # device doesn't have this policy applied
        return "N/A"

    # extract version from this layer's settings
    settings = matching_layer.get("settings", {})

    # handle platform specific variations
    if settings.get("has_variations"):
        variations = settings.get("variations", [])
        catalog_id = _get_catalog_id(device.get("hardwareProduct"))

        for var in variations:
            if (var.get("property_value") or {}).get("value") == catalog_id:
                if (var.get("use_latest") or {}).get("value"):
                    raw_version = latest_versions.get(catalog_id) if catalog_id else ""
                    return _normalize_version(raw_version) if raw_version else "N/A"
                else:
                    version = (var.get("version") or {}).get("value")
                    return _normalize_version(version) if version else "N/A"
        return "N/A"

    # device level policy
    if settings.get("use_latest"):
        catalog_id = _get_catalog_id(device.get("hardwareProduct"))
        raw_version = latest_versions.get(catalog_id) if catalog_id else ""
        return _normalize_version(raw_version) if raw_version else "N/A"
    else:
        version = settings.get("version")
        return _normalize_version(version) if version else "N/A"


# ---------------------------------
# Filtering Funcs
# ---------------------------------


def filter_devices_by_baseline(
    devices: List[Dict[str, Any]],
    compliance_baseline: Dict[str, Any],
    silent: bool = False,
) -> List[Dict[str, Any]]:
    """
    Filter devices based on baseline selection.
    - If baseline is site or user_group: only include devices that are members
    - If baseline is model: include all devices
    - slient: if True, suppress console logging
    """

    baseline_layer = compliance_baseline.get("layer")

    # no filtering needed for account model policy
    if baseline_layer == "model":
        return devices

    # for site or user_group, filter to members only
    if baseline_layer in ["site", "user_group"]:
        if compliance_baseline.get("all_policies"):
            if not silent:
                console_log(
                    f"[bold]Filtering devices with any {baseline_layer} policy [bold]"
                )
            filtered_devices = []

            for device in devices:
                attribution = device.get("policy_attribution") or {}
                all_layers = attribution.get("all_layers", [])

                is_member = any(
                    layer.get("type") == baseline_layer for layer in all_layers
                )

                if is_member:
                    filtered_devices.append(device)
            if not silent:
                console_log(
                    f"  [bold]Found [green]{len(filtered_devices)}[/green] devices with {baseline_layer} policies [/bold]"
                )
            return filtered_devices

        # single policy
        baseline_policy = compliance_baseline.get("policy")
        if not baseline_policy:
            if not silent:
                console_log(
                    "[yellow]Warning: No policy info in baseline, returning all devices[/yellow]"
                )
            return devices

        baseline_policy_id = baseline_policy.get("id")
        if not baseline_policy_id:
            if not silent:
                console_log(
                    "[yellow]Warning: No policy ID in baseline, returning all devices[/yellow]"
                )
            return devices

        if not silent:
            console_log(
                f"[cyan]Filtering devices to members of {baseline_layer} policy: {baseline_policy.get('name')}[/cyan]"
            )

        filtered_devices = []
        for device in devices:
            attribution = device.get("policy_attribution") or {}
            all_layers = attribution.get("all_layers", [])

            # check if this device has the selected site/group policy in their stack
            is_member = any(
                layer.get("id") == baseline_policy_id for layer in all_layers
            )

            if is_member:
                filtered_devices.append(device)

        if not silent:
            console_log(
                f"[green]Found {len(filtered_devices)} devices in {baseline_layer}[/green]"
            )
        return filtered_devices

    # fallback
    return devices


# ---------------------------------
# Analysis Funcs
# ---------------------------------


def analyze_and_group_devices(
    devices: List[Dict[str, Any]],
    latest_versions: Dict[str, str | None],
    compliance_baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Args:
        compliance_baseline: {
            "layer": "model" | "site" | "user_group",
            "policy": {...}, #if specific policy selected
            "display": "Policy Name"
        }
    """

    # group device by: controlling_layer, platform & device version
    groups = {}
    platform_totals = {}  # track total devices per platform for % calc

    for device in devices:
        platform = _normalize_platform(device.get("hardwareProduct", "Unknown"))
        software_version = _normalize_version(device.get("softwareVersion", "Unknown"))

        # track platform totals
        if platform not in platform_totals:
            platform_totals[platform] = 0
        platform_totals[platform] += 1

        # get controlling policy
        attribution = device.get("policy_attribution") or {}
        controlling = attribution.get("controlling_layer") or {}
        effective = attribution.get("effective") or {}

        controlling_type = controlling.get("type", "unknown")
        controlling_name = controlling.get("name", "Unknown")
        controlling_id = controlling.get("id", "unknown")

        # controlling policy expected version
        catalog_id = _get_catalog_id(device.get("hardwareProduct"))
        if effective.get("use_latest"):
            raw_version = latest_versions.get(catalog_id) if catalog_id else ""
            expected_version = (
                _normalize_version(raw_version) if raw_version else "Unknown"
            )
        else:
            expected_version = _normalize_version(effective.get("version") or "")

        if compliance_baseline.get("all_policies"):
            baseline_layer = compliance_baseline.get("layer")  # site or user_group
            # find baseline policy layer in this device's policy stack
            all_layers = attribution.get("all_layers", [])

            baseline_policy_for_device = None

            for layer in all_layers:
                if layer.get("type") == baseline_layer:
                    baseline_policy_for_device = layer
                    break

            if baseline_policy_for_device:
                # use baseline layer policy for grouping
                grouping_type = baseline_policy_for_device.get("type", "unknown")
                grouping_name = baseline_policy_for_device.get("name", "Unknown")
                grouping_id = baseline_policy_for_device.get("id", "unknown")

                # get expected version from baseline layer policy settings
                baseline_settings = baseline_policy_for_device.get("settings", {})

                # Check if this policy has platform-specific variations
                if baseline_settings.get("has_variations"):
                    # Find the variation matching this device's catalog_id
                    variations = baseline_settings.get("variations", [])
                    matching_variation = None

                    for variation in variations:
                        prop_value = variation.get("property_value", {}).get("value")
                        if prop_value == catalog_id:
                            matching_variation = variation
                            break

                    if matching_variation:
                        # Extract version from the matching variation
                        use_latest_obj = matching_variation.get("use_latest") or {}
                        if use_latest_obj.get("value"):
                            raw_version = (
                                latest_versions.get(catalog_id) if catalog_id else ""
                            )
                            baseline_expected_version = (
                                _normalize_version(raw_version)
                                if raw_version
                                else "Unknown"
                            )
                        else:
                            version_obj = matching_variation.get("version") or {}
                            baseline_expected_version = _normalize_version(
                                version_obj.get("value") or ""
                            )
                    else:
                        # No matching variation found
                        baseline_expected_version = "Not Configured"
                else:
                    # Simple policy (no variations)
                    if baseline_settings.get("use_latest"):
                        raw_version = (
                            latest_versions.get(catalog_id) if catalog_id else ""
                        )
                        baseline_expected_version = (
                            _normalize_version(raw_version)
                            if raw_version
                            else "Unknown"
                        )
                    else:
                        baseline_expected_version = _normalize_version(
                            baseline_settings.get("version") or ""
                        )
            else:
                # device not member of any site/group → skip it
                # should've been filtered already but catch in case
                continue
        else:
            # single policy specified. use controlling policy for grouping
            grouping_type = controlling.get("type", "unknown")
            grouping_name = controlling.get("name", "Unknown")
            grouping_id = controlling.get("id", "unknown")

            # get baseline expected version
            baseline_expected_version = _get_baseline_version_for_device(
                device, compliance_baseline, latest_versions
            )

        is_compliant_with_controlling = (
            software_version == expected_version if expected_version else False
        )

        is_compliant_with_baseline = (
            software_version == baseline_expected_version
            if baseline_expected_version and baseline_expected_version != "N/A"
            else False
        )

        # create group key
        group_key = (
            grouping_type,
            grouping_name,
            grouping_id,
            platform,
            software_version,
            expected_version,  # controlling policy sw version value
            baseline_expected_version,  # baseline policy sw version value
        )

        if group_key not in groups:
            groups[group_key] = {
                "grouping_type": grouping_type,
                "grouping_name": grouping_name,
                "grouping_id": grouping_id,
                "controlling_type": controlling_type,
                "controlling_name": controlling_name,
                "platform": platform,
                "device_version": software_version,
                "controlling_expected_version": expected_version,
                "baseline_expected_version": baseline_expected_version,
                "count": 0,
                "compliant_with_controlling_count": 0,
                "compliant_with_baseline_count": 0,
                "devices": [],  # device list for csv export
            }

        groups[group_key]["count"] += 1
        if is_compliant_with_controlling:
            groups[group_key]["compliant_with_controlling_count"] += 1
        if is_compliant_with_baseline:
            groups[group_key]["compliant_with_baseline_count"] += 1
        groups[group_key]["devices"].append(device)

        # calc %s
    for group in groups.values():
        platform = group["platform"]
        total_for_platform = platform_totals.get(platform, 1)
        group["pct_of_platform"] = group["count"] / total_for_platform * 100

    # calc overall baseline compliance
    total_compliant_with_baseline = sum(
        g["compliant_with_baseline_count"] for g in groups.values()
    )
    return {
        "groups": list(groups.values()),
        "platform_totals": platform_totals,
        "total_devices": len(devices),
        "total_compliant_with_baseline": total_compliant_with_baseline,
        "compliance_baseline": compliance_baseline,
    }


# ---------------------------------
# Display Funcs
# ---------------------------------


def display_aggregated_compliance_report(
    analysis: Dict[str, Any], compliance_baseline: Dict[str, Any]
):
    """
    display aggregated compliance report grouped by controlling policy
    compact view for large device counts
    """

    # console.print()

    groups = analysis["groups"]
    platform_totals = analysis["platform_totals"]
    total_devices = analysis["total_devices"]

    # console.print()

    # summary panel
    total_compliant = analysis.get("total_compliant_with_baseline", 0)
    compliance_pct = (total_compliant / total_devices * 100) if total_devices > 0 else 0

    summary = Text()
    summary.append("Total Devices: ", style="bold cyan")
    summary.append(f"{total_devices:,}\n", style="bold white")

    summary.append("Baseline Compliance: ", style="bold cyan")
    compliance_color = (
        "green" if compliance_pct >= 90 else "yellow" if compliance_pct >= 75 else "red"
    )
    summary.append(
        f"{compliance_pct:.1f}% ({total_compliant:,}/{total_devices:,})",
        style=f"bold {compliance_color}",
    )

    baseline_layer = compliance_baseline.get("layer")
    if baseline_layer in ["site", "user_group"]:
        # check all policies
        if compliance_baseline.get("all_policies"):
            clean_name = compliance_baseline.get("display", "Unknown")
        else:
            baseline_policy = compliance_baseline.get("policy", {})
            policy_name = baseline_policy.get("name", "Unknown")
            if baseline_layer == "site":
                match = re.search(r"\(([^)]+)\)", policy_name)
                clean_name = match.group(1) if match else policy_name
            else:
                match = re.search(r"Group\(([^)]+)\)", policy_name)
                clean_name = match.group(1) if match else policy_name

        title = f"[bold]Lens Desktop Compliance Summary - {clean_name}[/bold]"
    else:
        title = f"[bold]Lens Desktop Compliance Summary[/bold]"

    summary_panel = Panel(
        summary,
        title=title,
        border_style="cyan",
    )

    # platform breakdown summary

    platform_summary = Table(show_header=True, header_style="bold magenta")
    platform_summary.add_column("Platform", style="cyan", width=20)
    platform_summary.add_column("Total Devices", style="white", justify="right")

    for platform, count in sorted(platform_totals.items()):
        platform_summary.add_row(platform, f"{count:,}")

    platform_panel = Panel(
        Align.center(platform_summary),
        title="Platform Distribution",
        border_style="cyan",
        padding=(0, 1),
    )
    console.print(Columns([summary_panel, platform_panel], expand=True))
    console.print()

    # sort groups by: controlling type priority, then controlling name/id, then platform, then count desc
    type_priority = {"device": 0, "user_group": 1, "site": 2, "model": 3}
    sorted_groups = sorted(
        groups,
        key=lambda g: (
            type_priority.get(g["grouping_type"], 99),
            g["grouping_id"],  # group by specific policy
            g["platform"],
            -g["count"],  # desc
        ),
    )

    # group by policy for section-based display
    if compliance_baseline.get("all_policies"):
        baseline_layer = compliance_baseline.get("layer")
        if baseline_layer == "site":
            grouping_label = "Devices Grouped by Site Policy"
        elif baseline_layer == "user_group":
            grouping_label = "Devices Grouped by Device User Group Policy"
        else:
            grouping_label = "Devices Grouped by Policy Layer"
    else:
        grouping_label = "Devices Grouped by Controlling Policy Layer"

    console_log(f"[bold]{grouping_label}[/bold]")
    console.print()

    current_policy_id = None
    current_table = None
    current_platform = None
    header_text = ""

    for group in sorted_groups:
        grouping_type = group["grouping_type"]
        grouping_name = group["grouping_name"]
        grouping_id = group["grouping_id"]
        controlling_type = group["controlling_type"]
        controlling_name = group["controlling_name"]
        platform = group["platform"]
        device_version = group["device_version"]
        controlling_expected = group["controlling_expected_version"]
        baseline_expected = group["baseline_expected_version"]
        count = group["count"]
        pct_platform = group["pct_of_platform"]
        compliant_with_baseline = group["compliant_with_baseline_count"]

        # extract policy display name
        if grouping_type == "device":
            match = re.search(r"\(([a-f0-9-]+)\)", grouping_name)
            policy_display = match.group(1)[:12] + "..." if match else "Unknown"
        elif grouping_type == "site":
            match = re.search(r"\(([^)]+)\)", grouping_name)
            policy_display = match.group(1) if match else "Unknown"
        elif grouping_type == "user_group":
            match = re.search(r"Group\(([^)]+)\)", grouping_name)
            policy_display = match.group(1) if match else "Unknown"
        else:
            match = re.search(r"^(.*?)\s+Update\s+Policy", grouping_name)
            policy_display = match.group(1) if match else "Unknown"

        # when we hit a new policy, print the previous table and create a new section
        if current_policy_id != grouping_id:
            # print previous table if it exists
            if current_table is not None:
                policy_panel = Panel(
                    Align.center(current_table),
                    title=header_text if header_text else "",
                    border_style="magenta",
                    padding=(0, 1),
                )
                console.print(policy_panel)
                console.print()

            # create section header with policy type and name
            type_headers = {
                "device": "▶ DEVICE POLICY",
                "user_group": "▶ DEVICE USER GROUP POLICY",
                "site": "▶ SITE POLICY",
                "model": "▶ ACCOUNT POLICY",
            }
            header_prefix = type_headers.get(
                grouping_type, f"▶ {grouping_type.upper()}"
            )

            # header text with policy name (version shown in table column)
            header_text = f"[cyan]{header_prefix}:[/cyan] [bold]{policy_display}[bold]"

            # create new table for this policy
            current_table = Table(
                show_header=True, header_style="bold magenta", padding=(0, 0)
            )
            current_table.add_column(
                "Platform", style="white", width=22, justify="center", no_wrap=True
            )
            current_table.add_column(
                "Device Count", style="white", justify="center", width=16
            )
            current_table.add_column(
                "Device SW Ver.", style="cyan", justify="center", width=16
            )
            current_table.add_column(
                f"{policy_display} Policy SW Ver.",
                style="magenta",
                width=16,
                justify="center",
            )
            current_table.add_column(
                "Controlling Policy", style="dim", justify="center", width=24
            )
            current_table.add_column(
                "% Platform", style="white", justify="center", width=16
            )
            current_table.add_column("Status", style="white", justify="center", width=8)

            current_policy_id = grouping_id
            current_platform = None

            # add platform header row to distinguish grouping
        if current_platform != platform and current_table is not None:
            platform_short = platform.replace("Lens Desktop", "")

            # platform header row - name in col 1 rest empty
            current_table.add_row(
                f"[bold blue]{platform_short}[/bold blue]",
                "",
                "",
                "",
                "",
                "",
                "",
            )
            current_platform = platform

        # add row to current table
        device_matches_controlling = device_version == controlling_expected
        controlling_display = controlling_expected if controlling_expected else "N/A"
        if device_matches_controlling and controlling_expected:
            controlling_display += " ✓"

        is_group_compliant_with_baseline = compliant_with_baseline == count
        status_display = (
            "[green]✓[/green]" if is_group_compliant_with_baseline else "[red]x[/red]"
        )

        # color-code device version based on baseline compliance
        device_version_display = (
            f"[green]{device_version}[/green]"
            if is_group_compliant_with_baseline
            else f"[yellow]{device_version}[/yellow]"
        )

        if controlling_type == grouping_type:
            controlling_display_text = f"{grouping_type.title()} Policy"
        else:
            controlling_display_text = f"{controlling_type.title()} Policy (override)"

        # Add simplified platform name for data row
        platform_short = platform.replace("Lens Desktop ", "")

        if current_table is not None:
            current_table.add_row(
                "",
                f"{count:,}",
                device_version_display,
                baseline_expected,
                controlling_display_text,
                f"{pct_platform:.1f}%",
                status_display,
            )

    # print final table
    if current_table is not None:
        policy_panel = Panel(
            Align.center(current_table),
            title=header_text,
            border_style="magenta",
            padding=(0, 1),
        )
        console.print(policy_panel)
        console.print()
    console.print(
        "[dim]═══════════════════════════════════════════════════════════════[/dim]"
    )
    console.print(
        "[dim]Policy Interitance Priority: Device (highest) → User Group → Site → Account (lowest)[/dim]"
    )
    console.print(
        "[dim]═══════════════════════════════════════════════════════════════[/dim]"
    )
    console.print()
    console.print(
        "[dim]Note: Aggregated view showing device distribution. Full details exported to CSV.[/dim]"
    )
    console.print()


# ---------------------------------
# Csv Export Funcs
# ---------------------------------


def export_compliance_csv_full_details(
    devices: List[Dict[str, Any]],
    latest_versions: Dict[str, str | None],
    compliance_baseline: Dict[str, Any],
    filename: str = "lens-desktop-compliance-full.csv",
):
    """
    export complete device inventory with policy attribution
    includes all devices with full policy stack details
    """
    console_log(f"[cyan]Exporting full device inventory to CSV: {filename}[/cyan]")

    row_count = 0
    writer = None

    with open(filename, "w", newline="", encoding="utf-8") as f:
        for device in devices:
            device_id = device.get("id", "")
            device_name = device.get("name", "")
            platform = _normalize_platform(device.get("hardwareProduct", "Unknown"))
            software_version = device.get("softwareVersion") or ""
            software_version_normalized = _normalize_version(software_version)
            user_email = device.get("user_email") or ""

            # attribution info (from check_compliance)
            attribution = device.get("policy_attribution") or {}
            controlling = attribution.get("controlling_layer") or {}
            effective = attribution.get("effective") or {}
            account_policy = attribution.get("account_policy") or {}
            all_layers = attribution.get("all_layers") or {}

            controlling_type = controlling.get("type", "unknown")
            controlling_name = controlling.get("name", "Unknown")
            controlling_priority = controlling.get("priority", "")
            controlling_id = controlling.get("id", "unknown")

            catalog_id = _get_catalog_id(device.get("hardwareProduct"))
            effective_policy_setting = None

            if effective.get("use_latest"):
                raw_version = latest_versions.get(catalog_id) if catalog_id else ""
                expected_version = (
                    _normalize_version(raw_version) if raw_version else ""
                )
                effective_policy_setting = "use_latest"
            else:
                expected_version = _normalize_version(effective.get("version") or "")
                effective_policy_setting = expected_version

            # calc baseline version for device
            baseline_version = _get_baseline_version_for_device(
                device, compliance_baseline, latest_versions
            )
            baseline_version_normalized = _normalize_version(baseline_version)

            # calc compliance for device
            is_compliant_with_controlling = (
                software_version_normalized == expected_version
                if expected_version
                else False
            )
            is_compliant_with_baseline = (
                software_version_normalized == baseline_version_normalized
                if baseline_version_normalized and baseline_version_normalized != "N/A"
                else False
            )
            baseline_display = compliance_baseline.get("display", "Unknown")

            policy_stack_summary = []
            for layer in all_layers:
                layer_type = layer.get("type") or ""
                layer_name = layer.get("name", "Unknown")
                is_controlling = layer.get("is_controlling", False)
                has_settings = layer.get("has_settings", False)

                # Extract clean policy name
                if layer_type == "device":
                    match = re.search(r"\(([a-f0-9-]+)\)", layer_name)
                    clean_name = match.group(1)[:8] + "..." if match else "Device"
                    display = f"Device ({clean_name})"
                elif layer_type == "site":
                    match = re.search(r"\(([^)]+)\)", layer_name)
                    clean_name = match.group(1) if match else "Site"
                    display = f"Site ({clean_name})"
                elif layer_type == "user_group":
                    match = re.search(r"Group\(([^)]+)\)", layer_name)
                    clean_name = match.group(1) if match else "User Group"
                    display = f"User Group ({clean_name})"
                elif layer_type == "model":
                    display = "Account"
                else:
                    display = layer_type.title()

                # Mark controlling layer with asterisk
                if is_controlling:
                    display += "*"

                policy_stack_summary.append(display)
            policy_stack_str = " -> ".join(policy_stack_summary)

            row = {
                "Device ID": device_id,
                "Device Name": device_name,
                "Device User": user_email,
                "Platform": platform,
                "Device SW Version": software_version_normalized,
                "Controlling Policy Layer": controlling_type,
                "Controlling Policy Name": controlling_name,
                "Controlling Policy ID": controlling_id,
                "Controlling Policy Setting": effective_policy_setting,
                "Controlling Policy Version": expected_version,
                "Compliant with Controlling": (
                    "Yes" if is_compliant_with_controlling else "No"
                ),
                "Baseline Policy": baseline_display,
                "Baseline Expected Version": baseline_version_normalized,
                "Latest GA Version": (
                    latest_versions.get(
                        catalog_id,
                    )
                    if catalog_id
                    else ""
                ),
                "Compliant with Baseline": (
                    "Yes" if is_compliant_with_baseline else "No"
                ),
                "Policy Stack": policy_stack_str,
            }

            if writer is None:
                # init once we know columns
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                writer.writeheader()

            writer.writerow(row)
            row_count += 1

    console_log(
        f"[bold]Exported [blue]{row_count:,}[/blue] devices to [green]{filename}[/green][/bold]"
    )
    console_log(
        "[dim]CSV includes: Device details, policy attribution, compliance status, full policy stack [/dim]"
    )


# ---------------------------------
# called from cli.py
# ---------------------------------


def fetch_policy_attributions_concurrent(
    devices: List[Dict[str, Any]], max_workers: int = 10
) -> tuple[int, int]:
    """Fetch policy attribution for all devices using concurrent requests.

    This dramatically speeds up processing by making multiple API calls in parallel
    instead of waiting for each one sequentially.

    Args:
        devices: List of device dicts to enrich with policy_attribution
        max_workers: Number of concurrent threads (default: 10)
                    Start conservative, increase if no rate limiting

    Returns:
        (successful_count, failed_count)

    Performance:
        Sequential: 70k devices × 200ms = ~3.9 hours
        Concurrent (10 workers): 70k devices = ~23 minutes
        Concurrent (20 workers): 70k devices = ~12 minutes"""

    total = len(devices)
    completed = 0
    failed = 0

    console_log(
        f"[bold]Fetching policy attribution for {total:,} devices "
        f"(using {max_workers} concurrent workers)...[/bold]"
    )
    start_time = time.time()
    # ThreadPoolExectuor manages a pool of worker threads
    # context manager ensure cleanup, w/ or w/o errors

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # submit all tasks at once. they'll be queued and processed as workers become avail
        # creates a mapping: future → devices so we know which result belongs to which device

        future_to_device = {
            executor.submit(fetch_device_policy_stack, device["id"]): device
            for device in devices
        }

        # as_completed() populates futures as they finish (not in submission order)
        # results avail as soon as ready instead of waiting for all

        for future in as_completed(future_to_device):
            device = future_to_device[future]
            device_name = device.get("name", device.get("id", "Unknown"))

            try:
                policy_stack = future.result(timeout=30)
                attribution = parse_policy_attribution(policy_stack)
                device["policy_attribution"] = attribution
                completed += 1

            except TimeoutError:
                console_log(
                    f"[red]Timeout (30s) fetching policy for {device_name}[/red]"
                )
                device["policy_attribution"] = None
                failed += 1

            except Exception as exc:
                console_log(
                    f"[red]Error fetching policy for {device_name}: {exc}[/red]"
                )
                device["policy_attribution"] = None
                failed += 1

            processed = completed + failed
            if processed % 1000 == 0 or processed == total:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                remaining_secs = (total - processed) / rate if rate > 0 else 0

                console_log(
                    f"Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | "
                    f"✓ {completed:,} | ✗ {failed} | "
                    f"Rate: {rate:.1f}/sec | "
                    f"ETA: {remaining_secs/60:.1f} min"
                )
    elapsed = time.time() - start_time
    console_log(
        f"[green]Completed in {elapsed/60:.1f} minutes ({elapsed:.1f} seconds) [/green]"
    )
    console_log(
        f"  [green]Successful: {completed:,}[/green] | [red]Failed: {failed:,}[/red]"
    )

    if failed > 0:
        console_log(
            f"[yellow]{failed} devices failed to fetch policies (marked as None)[/yellow]"
        )

    return completed, failed


def check_compliance():
    console_log("[bold]Starting Lens Desktop Compliance Check[/bold]")
    console.print()

    # get tenantID from .env
    tenant_id = auth.TENANT_ID
    if not tenant_id:
        console_log("[red]Error: TENANT_ID not found in .env [/red]")
        menu_return()
        return

    console_log(f"Tenant ID: [bold]{tenant_id}[/bold]")
    console.print()

    # step 1: fetch latest CDN versions for both platforms
    catalog_ids = list(PLATFORM_CATALOG_MAP.values())
    labels = {value: key for key, value in PLATFORM_CATALOG_MAP.items()}
    latest_versions = fetch_multiple_latest_versions(catalog_ids, labels)
    console.print()

    # step 2: fetch devices
    devices = fetch_devices_by_model(
        tenant_id, "Lens Desktop", log_prefix="Lens Desktop devices"
    )
    if not devices:
        console_log("[yellow]No Lens Desktop devices found [/yellow]")
        menu_return()
        return
    console.print()

    # step 3: fetch policy attribution for each device
    # devices = devices[:100]

    _, failed = fetch_policy_attributions_concurrent(devices, max_workers=5)

    if failed > len(devices) * 0.5:
        console_log(
            f"[red]Too many failures. Check API connectivity and rate limits[/red]"
        )
        menu_return()
        return
    console.print()

    # extract unique policies and prompt for baseline
    console_log("[bold]Analyzing policy landscape...[/bold]")
    unique_policies = extract_unique_policies(devices)

    total_policies = sum(len(policies) for policies in unique_policies.values())
    if total_policies == 0:
        console_log(
            "[yellow]No Lens Desktop policies found in this tenant [/yellow]"
            "[yellow]Devices are unmanaged → no compliance baseline available [/yellow]"
        )
        menu_return()
        return

    # loop to allow user to change baseline selection
    while True:
        compliance_baseline = prompt_compliance_target(unique_policies)

        if not compliance_baseline:
            console_log("[yellow]No compliance baseline selected[/yellow]")
            menu_return()
            return
        console.print()

        # preivew filtering to show accurate device count
        preview_devices = filter_devices_by_baseline(
            devices, compliance_baseline, silent=True
        )
        baseline_layer = compliance_baseline.get("layer")

        # conf step
        baseline_display = compliance_baseline.get("display", "Unknown")
        device_count = len(preview_devices)
        total_count = len(devices)

        # diff messages for filtered vs unfiltered
        if baseline_layer in ["site", "user_group"] and device_count < total_count:
            device_msg = f"[cyan]Devices in {baseline_layer}s:[/cyan] [bold]{device_count:,}[/bold] of {total_count:,} total"
        else:
            device_msg = (
                f"[cyan]Devices to Analyze:[/cyan] [bold]{device_count:,}[/bold]"
            )

        console.print(
            Panel(
                Text.from_markup(
                    f"[cyan]Compliance Baseline: [/cyan] [bold]{baseline_display}[/bold]\n"
                    f"{device_msg}"
                ),
                title="[yellow]Confirm Analysis[/yellow]",
                border_style="yellow",
            )
        )
        console.print()

        confirm = ask_str(
            "Proceed with analysis? (y=yes, n=change baseline, q=cancel)",
            default="y",
        ).lower()

        if confirm in ["y", "yes", ""]:
            console.print()
            break
        elif confirm in ["n", "no"]:
            console.print()
            continue
        elif confirm in ["q", "quit"]:
            console_log("[yellow]Compliance check cancelled[/yellow]")
            menu_return()
            return
        else:
            console_log("[red]Invalid choice. Please enter y, n, or q[/red]")
            console.print()
            continue

    # step 4: Filter devices based on baseline selection
    filtered_devices = filter_devices_by_baseline(devices, compliance_baseline)

    if not filtered_devices:
        console_log(
            "[yellow]No devices found for selected baseline. This may indicate:[/yellow]"
        )
        console_log("[yellow]  • No devices are members of this site/group[/yellow]")
        console_log("[yellow]  • All devices were filtered out[/yellow]")
        menu_return()
        return

    console.print()

    # step 5: Analyze and group devices
    analysis = analyze_and_group_devices(
        filtered_devices, latest_versions, compliance_baseline=compliance_baseline
    )
    console.print()

    # step 6: display aggregated report
    display_aggregated_compliance_report(analysis, compliance_baseline)

    # step 7: export full CSV
    export_compliance_csv_full_details(
        filtered_devices, latest_versions, compliance_baseline
    )
    console.print()

    console_log("[bold]Compliance check complete[/bold]")
    menu_return()
