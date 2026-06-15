from typing import List, Dict, Any

PLATFORM_CATALOG_MAP = {
    "Desktop App MacOS": "lens-desktop-mac",
    "Desktop App Windows x64": "lens-desktop-windows",
    "Desktop App Windows ARM": "lens-desktop-windows-arm",
}

# -- PRIVATE HELPERS » NO TOUCHY!


def _normalize_platform(hardware_product: str) -> str:
    if not hardware_product:
        return "Unknown"
    # case-insensitive matching for Mac/macOS and Windows
    hardware_lower = hardware_product.lower()
    if "mac" in hardware_lower:
        return "Desktop App MacOS"
    elif "windows" in hardware_lower:
        if "arm" in hardware_lower:
            return "Desktop App Windows ARM"
        else:
            return "Desktop App Windows x64"
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


# -- DESKTOP APP SPECIFIC


def parse_policy_attribution(policy_stack: Dict[str, Any]) -> Dict[str, Any]:
    # get effective policy from capabilities
    capabilities = policy_stack.get("capabilities") or {}
    sw_update = capabilities.get("com", {}).get("poly", {}).get("software_update", {})
    policy = sw_update.get("policy") or {}

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

    return {
        "effective": effective,
        "controlling_layer": controlling_layer,
        "all_layers": all_layers,
        "account_policy": account_policy or {"version": None, "use_latest": False},
    }


def extract_unique_policies(devices: List[Dict]) -> Dict[str, List[Dict]]:
    policies_by_type = {"model": {}, "site": {}, "user_group": {}, "device": {}}

    for device in devices:
        attribution = device.get("policy_attribution")
        if not attribution:
            continue
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


def _get_baseline_version_for_device(
    device: Dict[str, Any],
    compliance_baseline: Dict[str, Any],
    latest_versions: Dict[str, str | None],
) -> str:

    baseline_layer = compliance_baseline.get("layer")

    if compliance_baseline.get("all_policies"):
        attribution = device.get("policy_attribution") or {}
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
    attribution = device.get("policy_attribution") or {}
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


# -- ANALYSIS FUNCS


def analyze_and_group_devices(
    devices: List[Dict[str, Any]],
    latest_versions: Dict[str, str | None],
    compliance_baseline: Dict[str, Any],
) -> Dict[str, Any]:

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

        # Compliance requires BOTH version match AND correct policy source
        is_compliant_with_baseline = False
        if baseline_expected_version and baseline_expected_version != "N/A":
            version_matches = software_version == baseline_expected_version

            # Check if version is coming from the correct policy layer
            baseline_layer = compliance_baseline.get("layer")
            policy_source_matches = controlling_type == baseline_layer

            # Both must be true for compliance
            is_compliant_with_baseline = version_matches and policy_source_matches

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

    compliance_by_layer = {
        "device": {"total": 0, "compliant": 0, "version_match": 0},
        "user_group": {"total": 0, "compliant": 0, "version_match": 0},
        "site": {"total": 0, "compliant": 0, "version_match": 0},
        "model": {"total": 0, "compliant": 0, "version_match": 0},
    }

    for group in groups.values():
        layer_type = group["controlling_type"]
        count = group["count"]
        compliant_count = group["compliant_with_baseline_count"]

        baseline_expected = group["baseline_expected_version"]
        device_version = group["device_version"]
        version_matches = (
            device_version == baseline_expected
        ) and baseline_expected != "N/A"
        version_match_count = count if version_matches else 0

        if layer_type in compliance_by_layer:
            compliance_by_layer[layer_type]["total"] += count
            compliance_by_layer[layer_type]["compliant"] += compliant_count
            compliance_by_layer[layer_type]["version_match"] += version_match_count

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
        "compliance_by_layer": compliance_by_layer,
    }
