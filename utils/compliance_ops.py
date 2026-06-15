import csv
from datetime import datetime
from typing import List, Dict, Any
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
import re

from utils import auth
from utils.env_helper import console_log, console
from utils.input_helpers import menu_return, ask_int, ask_str

from utils.compliance_analysis import (
    PLATFORM_CATALOG_MAP,
    _normalize_platform,
    _normalize_version,
    _get_catalog_id,
    extract_unique_policies,
    analyze_and_group_devices,
    _get_baseline_version_for_device,
)
from utils.device_ops import (
    fetch_devices_by_model,
    fetch_multiple_latest_versions,
    fetch_policy_attributions_concurrent,
)


def prompt_compliance_target(
    unique_policies: Dict[str, List[Dict]],
) -> Dict[str, Any] | None:

    console.print()
    console.print("[dim]─[/dim]" * 100)
    console.print(
        "[bold cyan]Select Policy Compliance Measurement Baseline[/bold cyan]"
    )
    console.print()
    console.print(
        "[bold]What's Measured:[/bold]\n"
        "  Compliance » correct version AND controlled by the baseline policy you select\n"
        "\n"
        "[bold]Status Indicators:[/bold]\n"
        "  [green]✓ Compliant[/green] » version matches baseline and baseline policy controls the device\n"
        "  [yellow]⚠ Policy Override[/yellow] » version matches baseline [bold]BUT[/bold] a different policy controls the device \n"
        "  [red]✗ Non-Compliant[/red] » device version doesn't match baseline \n"
        "\n"
        "[bold]CLI Report Includes:[/bold]\n"
        "  Summary: Overall Compliance % and device breakdown by controlling policy\n"
        "  Tables: Devices grouped by controlling policy\n"
        "  CSV Export: Full per-device details » [cyan]desktop-app-compliance-full.csv[/cyan]\n"
        "  CSV Export: Aggregated Summary » [cyan]desktop-app-compliance-summary.csv[/cyan]\n"
        "\n"
        "[blue]Example:[/blue]\n"
        "  - Baseline = Account Model Policy (expects 2.3.0)\n"
        "  - Device on 2.3.0 controlled by Account Model » [green]✓ Compliant[/green] [dim](correct version and policy controlling)[/dim]\n"
        "  - Device on 2.3.0 controlled by Site Policy » [yellow]⚠ Policy Override[/yellow] [dim](correct version but wrong policy controlling)[/dim]\n"
        "  - Device on 2.2.0 controlled by Account Model » [red]✗ Non-Compliant[/red] [dim](wrong version but correct policy controlling)[/dim]\n"
        "  - Device on 2.2.0 controlled by Site Policy » [red]✗ Non-Compliant[/red] [dim](wrong version and wrong policy controlling)[/dim]\n"
    )
    console.print()
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

    # option 3: device user group
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


# ----------filtering funcs----------


def filter_devices_by_baseline(
    devices: List[Dict[str, Any]],
    compliance_baseline: Dict[str, Any],
    silent: bool = False,
) -> List[Dict[str, Any]]:

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


# ----------display funcs----------


def _get_expected_versions_display(
    groups: List[Dict[str, Any]],
    grouping_id: str,
    latest_versions: Dict[str, str | None],
) -> str:
    """
    get display string showing expected versions for THIS policy. i.e., "Expected: Mac 2.3.1 | Win 2.1.1"
    shows ALL platforms THIS policy defines, even if no devices exist on that platform.

    args:
        groups: List of group dicts from analysis
        grouping_id: The policy ID to get versions for
        latest_versions: Dict mapping catalog_ids to latest GA versions
    """
    matching_groups = [g for g in groups if g["grouping_id"] == grouping_id]

    if not matching_groups:
        return "Expected: Unknown"

    # find a device with valid policy attribution to read policy settings from
    # search through all groups since some groups may have devices with failed policy fetches
    reference_device = None
    grouping_type = matching_groups[0]["grouping_type"]

    for group in matching_groups:
        for device in group.get("devices", []):
            attribution = device.get("policy_attribution")
            if attribution:
                # check if this device has the policy layer we need
                all_layers = attribution.get("all_layers", [])
                for layer in all_layers:
                    if (
                        layer.get("id") == grouping_id
                        and layer.get("type") == grouping_type
                    ):
                        reference_device = device
                        break
                if reference_device:
                    break
        if reference_device:
            break

    # ff no device has valid attribution, fallback to group-level data
    if not reference_device:
        all_platform_versions = {}
        for group in matching_groups:
            platform_short = group["platform"].replace("Desktop App ", "")
            expected = group["controlling_expected_version"]
            if expected and expected != "N/A" and expected != "Unknown":
                all_platform_versions[platform_short] = expected

        if all_platform_versions:
            parts = [
                f"{platform} {version}"
                for platform, version in sorted(all_platform_versions.items())
            ]
            return "Expected: " + " | ".join(parts)
        return "Expected: N/A"

    # access the policy settings from the reference device's attribution
    attribution = reference_device.get("policy_attribution") or {}
    all_layers = attribution.get("all_layers", [])

    # find the specific layer for this grouping_id
    matching_layer = None
    for layer in all_layers:
        if layer.get("id") == grouping_id and layer.get("type") == grouping_type:
            matching_layer = layer
            break

    if not matching_layer:
        return "Expected: Unknown"

    settings = matching_layer.get("settings")
    if not settings:
        return "Expected: Unknown"

    all_platform_versions = {}

    # check if policy has platform-specific variations
    if settings.get("has_variations"):
        variations = settings.get("variations", [])

        for variation in variations:
            # Get catalog_id from property_value
            catalog_id = variation.get("property_value", {}).get("value")

            # Determine platform name from catalog_id
            if catalog_id == "lens-desktop-mac":
                platform_short = "Mac"
            elif catalog_id == "lens-desktop-windows":
                platform_short = "Windows x64"
            elif catalog_id == "lens-desktop-windows-arm":
                platform_short = "Windows ARM"
            else:
                continue

            # check if use_latest or specific version
            use_latest_obj = variation.get("use_latest")
            if use_latest_obj and use_latest_obj.get("value"):
                version = latest_versions.get(catalog_id, "Unknown")
            else:
                version_obj = variation.get("version")
                version = (
                    version_obj.get("value", "Unknown") if version_obj else "Unknown"
                )

            all_platform_versions[platform_short] = _normalize_version(version)
    else:
        # simple policy without variations - applies same version to all platforms
        use_latest = settings.get("use_latest")
        if use_latest:
            # apply to both platforms
            for catalog_id, platform_name in [
                ("lens-desktop-mac", "Mac"),
                ("lens-desktop-windows", "Windows x64"),
                ("lens-desktop-windows-arm", "Windows ARM"),
            ]:
                version = latest_versions.get(catalog_id, "Unknown")
                all_platform_versions[platform_name] = _normalize_version(version)
        else:
            version = settings.get("version", "Unknown")
            # single version applies to all platforms
            for platform_name in ["Mac", "Windows x64", "Windows ARM"]:
                all_platform_versions[platform_name] = _normalize_version(version)

    if not all_platform_versions:
        return "Expected: N/A"

    # always show versions by platform
    parts = [
        f"{platform} {version}"
        for platform, version in sorted(all_platform_versions.items())
    ]
    return "Expected: " + " | ".join(parts)


def display_aggregated_compliance_report(
    analysis: Dict[str, Any],
    compliance_baseline: Dict[str, Any],
    latest_versions: Dict[str, str | None],
):

    groups: List[Dict[str, Any]] = analysis.get("groups", [])
    platform_totals = analysis["platform_totals"]
    total_devices = analysis["total_devices"]

    # summary panel
    total_compliant = analysis.get("total_compliant_with_baseline", 0)
    compliance_pct = (total_compliant / total_devices * 100) if total_devices > 0 else 0

    summary = Text()
    summary.append("Total Devices: ", style="cyan")
    summary.append(f"{total_devices:,}\n", style="bold white")

    summary.append("Baseline: ", style="cyan")
    summary.append(f"{compliance_baseline.get('display', 'Unknown')}\n", style="white")

    summary.append("Overall Compliance: ", style="cyan")
    summary.append(
        f"{compliance_pct:.1f}% ({total_compliant:,}/{total_devices:,})\n\n",
        style="bold white",
    )

    summary.append("Devices by Controlling Policy Layer:\n", style="cyan")

    compliance_by_layer = analysis.get("compliance_by_layer", {})
    baseline_layer = compliance_baseline.get("layer")

    baseline_expected_version = "Unknown"
    for group in analysis["groups"]:
        if group["grouping_type"] == baseline_layer:
            baseline_expected_version = group["baseline_expected_version"]
            break

    layer_order = ["device", "user_group", "site", "model"]
    layer_labels = {
        "device": "Device Policy",
        "user_group": "User Group Policy",
        "site": "Site Policy",
        "model": "Account Model",
    }

    for layer in layer_order:
        layer_data = compliance_by_layer.get(layer, {"total": 0, "compliant": 0})
        total = layer_data["total"]
        compliant = layer_data["compliant"]
        version_match = layer_data["version_match"]

        if total == 0:
            continue

        is_baseline = layer == baseline_layer
        label = layer_labels.get(layer, layer.title())

        # icon and style based on baseline vs override
        if is_baseline:
            non_compliant = total - compliant
            summary.append(f" ", style="")
            summary.append(f"{compliant:,}", style="green")
            summary.append(" ✓", style="bold green")
            summary.append(" / ", style="white")
            summary.append(f"{non_compliant:,}", style="red")
            summary.append(" ✗", style="bold red")
            summary.append(f" ({total:,} {label})", style="white")
            summary.append(" [Baseline]\n", style="dim")
        else:
            non_version_match = total - version_match
            summary.append(f" ", style="")
            summary.append(f"{version_match:,}", style="yellow")
            summary.append(" ⚠", style="bold yellow")
            summary.append(" / ", style="white")
            summary.append(f"{non_version_match:,}", style="red")
            summary.append(" ✗", style="bold red")
            summary.append(f" ({total:,} {label})", style="white")
            summary.append(" [Override]\n", style="dim")

    platform_table = Table(
        show_header=True, header_style="dim", box=None, padding=(0, 1)
    )
    platform_table.add_column("Platform", style="white", no_wrap=True, justify="left")
    platform_table.add_column("Devices", style="cyan", justify="right")

    for platform, count in sorted(platform_totals.items()):
        platform_short = platform.replace("Desktop App ", "")
        platform_table.add_row(platform_short, f"{count:,}")

    color_key = Text()
    color_key.append("Status Legend:\n", style="bold cyan")

    color_key.append(" ✓", style="bold green")
    color_key.append(" Compliant\n", style="white")
    color_key.append(" Correct version from baseline\n", style="dim")
    # color_key.append(" from baseline\n\n", style="dim")

    color_key.append(" ⚠", style="bold yellow")
    color_key.append(" Policy Override\n", style="white")
    color_key.append(
        " Correct version BUT controlled by override policy\n", style="dim"
    )
    # color_key.append(" wrong source\n\n", style="dim")

    color_key.append(" ✗", style="bold red")
    color_key.append(" Non-Compliant\n", style="white")
    color_key.append(" Wrong version", style="dim")

    # use Table.grid for better column spacing control
    summary_grid = Table.grid(expand=True, padding=(0, 3))
    summary_grid.add_column(ratio=3)  # left: Summary stats
    summary_grid.add_column(ratio=2)  # middle: Platform distribution
    summary_grid.add_column(ratio=2)  # right: Color legend
    summary_grid.add_row(summary, color_key, Align.center(platform_table))

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

        title = f"Desktop App Compliance Summary - [bold]{clean_name}[/bold]"
    else:
        title = f"Desktop App Compliance Summary"

    summary_panel = Panel(
        summary_grid, title=title, border_style="cyan", padding=(1, 2)
    )

    console.print(summary_panel)
    console.print()

    baseline_layer = compliance_baseline.get("layer")

    def sort_key(g):
        grouping_type = g["grouping_type"]
        is_baseline = grouping_type == baseline_layer

        # priority → baseline first then by policy priority
        type_priority = {"device": 0, "user_group": 1, "site": 2, "model": 3}

        return (
            0 if is_baseline else 1,
            type_priority.get(grouping_type, 99),
            g["grouping_id"],
            g["platform"],
            -g["count"],
        )

    sorted_groups = sorted(groups, key=sort_key)

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
    show_controlling_column = False

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
                    border_style="dim",
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

            # Get expected versions for this policy
            expected_versions_text = _get_expected_versions_display(
                groups, grouping_id, latest_versions
            )

            # header text with policy name and expected versions
            header_text = f"[cyan]{header_prefix}:[/cyan] [bold]{policy_display}[/bold] [dim]|[/dim] [magenta]{expected_versions_text}[/magenta]"

            # create new table for this policy
            current_table = Table(show_header=True, header_style="bold", padding=(0, 0))
            current_table.add_column(
                "Platform", style="white", width=30, justify="center", no_wrap=True
            )
            current_table.add_column(
                "Device Count", style="white", justify="center", width=16
            )
            current_table.add_column(
                "Device SW Ver.", style="cyan", justify="center", width=16
            )
            current_table.add_column(
                "% Platform", style="white", justify="center", width=12
            )

            # only show controlling policy column when:
            # 1. baseline is site or user_group
            # 2. at least one device in this policy section has a policy override
            show_controlling_column = False
            if baseline_layer in ["site", "user_group"]:
                # look ahead to see if any devices in this policy section have overrides
                for g in sorted_groups:
                    if g["grouping_id"] == grouping_id:
                        if g["controlling_type"] != baseline_layer:
                            show_controlling_column = True
                            break

            if show_controlling_column:
                current_table.add_column(
                    "Controlling Policy", style="dim", justify="center", width=60
                )

            current_policy_id = grouping_id
            current_platform = None

            # add platform header row to distinguish grouping
        if current_platform != platform and current_table is not None:
            platform_short = platform.replace("Desktop App ", "")

            # platform header row - name in col 1 rest empty
            if show_controlling_column:
                current_table.add_row(
                    f"[reverse bold blue]{platform_short }[/reverse bold blue]",
                    "",
                    "",
                    "",
                    "",
                )
            else:
                current_table.add_row(
                    f"[reverse bold blue]{platform_short }[/reverse bold blue]",
                    "",
                    "",
                    "",
                )
            current_platform = platform

        # add row to current table
        baseline_layer = compliance_baseline.get("layer")
        is_group_compliant_with_baseline = compliant_with_baseline == count

        version_matches = device_version == baseline_expected
        policy_source_matches = controlling_type == baseline_layer

        if is_group_compliant_with_baseline:
            # Green: compliant
            device_version_display = f"[green]{device_version}[/green]"
        elif version_matches and not policy_source_matches:
            # Yellow: correct version but override policy
            device_version_display = f"[yellow]{device_version}[/yellow]"
        else:
            # Red: wrong version
            device_version_display = f"[red]{device_version}[/red]"

        if current_table is not None:
            if show_controlling_column:
                current_table.add_row(
                    "",
                    f"{count:,}",
                    device_version_display,
                    f"{pct_platform:.1f}%",
                    f"[dim]{controlling_name}[/dim]",
                )
            else:
                current_table.add_row(
                    "",
                    f"{count:,}",
                    device_version_display,
                    f"{pct_platform:.1f}%",
                )

    # print final table
    if current_table is not None:
        policy_panel = Panel(
            Align.center(current_table),
            title=header_text,
            border_style="dim",
            padding=(0, 1),
        )
        console.print(policy_panel)
        console.print()
    console.print(
        "[dim]═══════════════════════════════════════════════════════════════[/dim]"
    )
    console.print()
    console.print(
        "[dim yellow]Note:[/dim yellow][dim] Aggregated view showing device distribution. Full details exported to CSV.[/dim]"
    )
    console.print()


# -- Csv Export Funcs


def export_compliance_csv_full_details(
    devices: List[Dict[str, Any]],
    latest_versions: Dict[str, str | None],
    compliance_baseline: Dict[str, Any],
    filename: str = "desktop-app-compliance-full.csv",
):
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

            # Compliance requires BOTH version match AND correct policy source
            is_compliant_with_baseline = False
            if baseline_version_normalized and baseline_version_normalized != "N/A":
                version_matches = (
                    software_version_normalized == baseline_version_normalized
                )

                # Check if version is coming from the correct policy layer
                baseline_layer = compliance_baseline.get("layer")
                policy_source_matches = controlling_type == baseline_layer

                # Both must be true for compliance
                is_compliant_with_baseline = version_matches and policy_source_matches

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
                    display = "Account model"
                else:
                    display = layer_type.title()

                # Mark controlling layer with asterisk
                if is_controlling:
                    display += "*"

                policy_stack_summary.append(display)
            policy_stack_str = " >> ".join(policy_stack_summary)

            row = {
                "Device ID": device_id,
                "Device Name": device_name,
                "Device User": user_email,
                "Platform": platform,
                "Device SW Version": software_version_normalized,
                "Compliant with Baseline": (
                    "Yes" if is_compliant_with_baseline else "No"
                ),
                "Policy Layers (Highest >> Lowest Priority)": f"{policy_stack_str}",
                "Winning Policy Layer": controlling_type,
                "Winning Policy Name": controlling_name,
                "Winning Policy Setting": effective_policy_setting,
                "Winning Policy Version": expected_version,
            }

            if writer is None:
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


def export_compliance_csv_summary(
    analysis: Dict[str, Any],
    compliance_baseline: Dict[str, Any],
    filename: str = "desktop-app-compliance-summary.csv",
):
    run_date = datetime.now().strftime("%d-%m-%Y %H:%M")
    baseline_display = compliance_baseline.get("display", "Unknown")
    baseline_layer = compliance_baseline.get("layer")

    total_devices = analysis.get("total_devices", 0)
    total_compliant = analysis.get("total_compliant_with_baseline", 0)
    overall_pct = (
        f"{(total_compliant / total_devices * 100):.1f}%"
        if total_devices > 0
        else "N/A"
    )

    layer_labels = {
        "device": "Device Policy",
        "user_group": "User Group Policy",
        "site": "Site Policy",
        "model": "Account Model ",
    }

    def _clean_policy_name(name, policy_type):
        if policy_type == "device":
            match = re.search(r"\(([a-f0-9-]+)\)", name)
            return match.group(1)[:12] + "..." if match else name
        elif policy_type == "site":
            match = re.search(r"\(([^)]+)\)", name)
            return match.group(1) if match else name
        elif policy_type == "user_group":
            match = re.search(r"Group\(([^)]+)\)", name)
            return match.group(1) if match else name
        else:
            match = re.search(r"^(.*?)\s+Update\s+Policy", name)
            return match.group(1) if match else name

    def sort_key(g):
        type_priority = {"device": 0, "user_group": 1, "site": 2, "model": 3}
        return (
            0 if g["grouping_type"] == baseline_layer else 1,
            type_priority.get(g["grouping_type"], 99),
            g["grouping_id"],
            g["platform"],
            -g["count"],
        )

    sorted_groups = sorted(analysis.get("groups", []), key=sort_key)

    console_log(f"[cyan]Exporting compliance summary to CSV: {filename}[/cyan]")

    type_headers = {
        "device": "DEVICE POLICY",
        "user_group": "USER GROUP POLICY",
        "site": "SITE POLICY",
        "model": "ACCOUNT MODEL",
    }

    col_headers = [
        "Platform",
        "Device Count",
        "Device SW Ver.",
        "% Platform",
        "Compliance Status",
    ]

    row_count = 0
    with open(filename, "w", newline="", encoding="utf-8") as f:
        just = csv.writer(f)
        just.writerow([f"Run Date: {run_date}"])
        just.writerow([f"Baseline >> {baseline_display}"])
        just.writerow([f"Overall Compliance: {overall_pct}"])
        just.writerow([])

        current_policy_id = None
        current_platform = None
        first_section = True

        for group in sorted_groups:
            grouping_type = group["grouping_type"]
            grouping_name = group["grouping_name"]
            grouping_id = group["grouping_id"]
            controlling_type = group["controlling_type"]
            platform = group["platform"]
            device_version = group["device_version"]
            baseline_expected = group["baseline_expected_version"]
            count = group["count"]
            pct_platform = group["pct_of_platform"]
            compliant = group["compliant_with_baseline_count"]

            if current_policy_id != grouping_id:
                if not first_section:
                    just.writerow([])
                first_section = False

                policy_display = _clean_policy_name(grouping_name, grouping_type)
                header_prefix = type_headers.get(grouping_type, grouping_type.upper())

                policy_groups = [
                    group
                    for group in sorted_groups
                    if group["grouping_id"] == grouping_id
                ]
                platform_versions = {}
                for pg in policy_groups:
                    platform_short = pg["platform"].replace("Desktop App ", "")
                    if platform_short not in platform_versions:
                        platform_versions[platform_short] = pg[
                            "baseline_expected_version"
                        ]
                expected_parts = [
                    f"{p} {v}" for p, v in sorted(platform_versions.items())
                ]
                expected_text = (
                    "Expected: " + " | ".join(expected_parts)
                    if expected_parts
                    else "Expected: N/A"
                )

                just.writerow(
                    [f">> {header_prefix}: {policy_display} | {expected_text}"]
                )
                just.writerow(col_headers)

                current_policy_id = grouping_id
                current_platform = None

            if current_platform != platform:
                platform_short = platform.replace("Desktop App ", "")
                just.writerow([f"[ {platform_short} ]"])
                current_platform = platform

            is_group_compliant = compliant == count
            version_matches = device_version == baseline_expected
            policy_source_matches = controlling_type == baseline_layer

            if is_group_compliant:
                status = "Compliant"
            elif version_matches and not policy_source_matches:
                status = "Policy Override"
            else:
                status = "Non-Compliant"

            just.writerow(
                ["", f"{count:,}", device_version, f"{pct_platform:.1f}%", status]
            )
            row_count += 1

    console_log(
        f"[bold]Exported [blue]{row_count:,}[/blue] rows to [green]{filename}[/green][/bold]"
    )
    console_log(
        "[dim]CSV includes: aggregated compliance by policy, platform, and version[/dim]"
    )


# -- called from cli.py


def check_compliance():
    console_log("[bold]Starting Desktop App Compliance Check[/bold]")
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
        tenant_id, "Desktop App", log_prefix="Desktop App devices"
    )
    if not devices:
        console_log("[yellow]No Desktop App devices found [/yellow]")
        menu_return()
        return
    console.print()

    # step 3: fetch policy attribution for each device
    # Uses batching (25 devices per query) + concurrent workers to optimize performance

    _, failed = fetch_policy_attributions_concurrent(devices)

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
            "[yellow]No Desktop App policies found in this tenant [/yellow]"
            "[yellow]Devices are unmanaged → no compliance baseline available [/yellow]"
        )
        menu_return()
        return

    # loop to allow user to change baseline selection
    while True:
        compliance_baseline = prompt_compliance_target(unique_policies)
        console.print()

        if not compliance_baseline:
            console_log("[yellow]Returning to main menu[/yellow]\n")
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
                    f"[cyan]Compliance Baseline:[/cyan][bold] {baseline_display}[/bold]\n"
                    f"{device_msg}"
                ),
                title="[yellow]Confirm Analysis[/yellow]",
                border_style="yellow",
            )
        )
        console.print()

        confirm = ask_str(
            "Proceed with analysis?",
            default="y",
            explain="y=yes, n=change baseline, q=cancel & exit",
        ).lower()
        console.print()

        if confirm in ["y", "yes", ""]:
            break
        elif confirm in ["n", "no"]:
            continue
        elif confirm in ["q", "quit"]:
            console_log("[yellow]Compliance check cancelled[/yellow]")
            return
        else:
            console.print()
            console_log(
                "[red]Invalid choice.[bold] Please enter y, n, or q[/bold][/red]"
            )
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
    display_aggregated_compliance_report(analysis, compliance_baseline, latest_versions)

    # step 7: export full .csv
    export_compliance_csv_full_details(
        filtered_devices, latest_versions, compliance_baseline
    )
    console.print()

    # step 8: export summary .csv
    export_compliance_csv_summary(analysis, compliance_baseline)
    console.print()

    console_log("[bold]Compliance check complete[/bold]")
    menu_return()
