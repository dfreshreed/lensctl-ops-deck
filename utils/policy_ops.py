from typing import Optional, List, Dict, Any
import requests

from rich.table import Table


from utils.auth import execute_gql
import utils.auth as auth
from utils.env_helper import console_log, console
from utils.input_helpers import ask_int

"""
  Policy helpers for policy management operations.
  Currently unused by compliance checks (which use device_ops instead),
  but kept for future policy editing/management features.
"""

LIST_POLICIES = """
  query PoliciesCapabilities($rules: Rule!) {
    policiesCapabilities(rules: $rules) {
      collectionId
      settingsCount
      name
      priority
      type
      id
    }
  }
  """

POLICY_CAPABILITIES_DETAIL = """
  query LdModelSwPolicy($rules: Rule, $policyCapabilitiesId: String) {
    policyCapabilities(rules: $rules, id: $policyCapabilitiesId) {
      sources {
        id
        collectionRule {
          id
          value
        }
        name
        updatedAt
        priority
        type
        capabilities {
          com {
            poly {
              software_update {
                policy {
                  url_source {
                    value
                    constraints {
                      options
                    }
                  }
                  postponed_update_hours {
                    value
                    constraints {
                      options
                    }
                  }
                  allow_update_postpone_times {
                    value
                    constraints {
                      options
                    }
                  }
                  version {
                    value
                    constraints {
                      options
                    }
                  }
                  use_latest {
                    value
                    constraints {
                      options
                    }
                  }
                }
                policy_variations {
                  property_value {
                    value
                    constraints {
                      options
                    }
                  }
                  property_path {
                    value
                    constraints {
                      options
                    }
                  }
                  use_latest {
                    value
                    constraints {
                      options
                    }
                  }
                  version {
                    value
                    constraints {
                      options
                    }
                  }
                }
              }
            }
          }
        }
        settingsCount
        collectionId
      }
      deviceIds
    }
  }
  """

Policy = Dict[str, Any]


def fetch_account_model_policies(tenant_id: str) -> List[Policy]:
    console_log("Fetching Account → Model policies")

    variables = {
        "rules": {
            "and": [
                {"equal": {"key": "tenantId", "value": tenant_id}},
                {"equal": {"key": "type", "value": "model"}},
            ]
        }
    }

    try:
        data = execute_gql(LIST_POLICIES, variables)

        if "errors" in data:
            console_log(f"[red] GraphQL errors: {data['errors']} [/red]")
            return []
        policies = data.get("data", {}).get("policiesCapabilities", [])
        console_log(f"[green] Found {len(policies)} Account → Model policies [/green]")

        return policies

    except requests.RequestException as error:
        console_log(f"[red]Error fetching policies: {error}[/red]")
        return []


def select_policy(policies: List[Policy], search_term: str = "") -> Optional[str]:
    if not policies:
        console_log("[red]No policies available to select[/red]")
        return None

    # filter by search term if provided
    if search_term:
        matching_policies = [
            p for p in policies if search_term.lower() in p.get("name", "").lower()
        ]
    else:
        matching_policies = policies

    # exactly one match -> auto-select
    if len(matching_policies) == 1:
        policy = matching_policies[0]
        console_log(
            f"[green]Auto-selected policy:[/green] [bold]{policy['name']}[/bold] (ID: {policy['id']})"
        )
        return policy["id"]

    # multiple matches -> let user choose from list
    if len(matching_policies) > 1 and search_term:
        console_log(
            f"[yellow]Found {len(matching_policies)} policies matching '{search_term}'[/yellow]"
        )
        console.print()
        policies_to_show = matching_policies

    # no matches or search term -> display all polices
    else:
        if search_term:
            console_log(f"[yellow]No policies found matching '{search_term}'[/yellow]")
        console_log("[cyan]Showing all available model policies:[/cyan]")
        console.print()
        policies_to_show = policies

    # show policies in a table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=4, justify="right")
    table.add_column("Policy Name", style="yellow")
    table.add_column("ID", style="dim")
    table.add_column("Priority", justify="right", style="white")
    table.add_column("Settings", justify="right", style="green")

    for idx, policy in enumerate(policies_to_show, start=1):
        table.add_row(
            str(idx),
            policy.get("name", "Unknown"),
            policy.get("id", ""),
            str(policy.get("priority", 0)),
            str(policy.get("settingsCount", 0)),
        )
    console.print(table)
    console.print()
    console_log("[dim]Enter 0 to cancel[/dim]")

    # prompt user to select
    while True:
        choice = ask_int("Select policy number", default=0, min_value=0)

        if choice == 0:
            console_log("[yellow]Canceled policy selection[/yellow]")
            return None
        if 1 <= choice <= len(policies_to_show):
            selected_policy = policies_to_show[choice - 1]
            console_log(f"[green]Selected: [bold]{selected_policy['name']}[/bold]")
            return selected_policy["id"]

        console_log(
            f"[red]Invalid choice. Please enter 1-{len(policies_to_show)} or 0 to abort[/red]"
        )


def fetch_policy_detail(tenant_id: str, policy_id: str) -> Dict[str, Any]:

    console_log(f"Fetching policy details for ID: {policy_id}")

    variables = {
        "policyCapabilitiesId": policy_id,
        "rules": {"equal": {"key": "tenantId", "value": tenant_id}},
    }

    try:
        data = auth.execute_gql(POLICY_CAPABILITIES_DETAIL, variables)

        if "errors" in data:
            console_log(f"[red]GraphQL errors: {data['errors']}[/red]")
            return {}

        policy_data = data.get("data", {}).get("policyCapabilities", {})

        if not policy_data:
            console_log(f"[red]No policy data found for this policy ID[/red]")
            return {}

        console_log(f"Fetched policy details")
        return policy_data

    except requests.RequestException as err:
        console_log(f"[red]Error fetching policy details: {err}[/red]")
        return {}


def extract_software_policy_variations(policy_data: Dict[str, Any]) -> List[Policy]:
    sources = policy_data.get("sources", [])

    if not sources:
        return []

    # get highest priority source
    highest_priority_source = max(sources, key=lambda s: s.get("priority", 0))

    console_log(
        f"[green]Using policy source: [bold]{highest_priority_source.get('name')}[/bold] (priority: {highest_priority_source.get('priority')})"
    )

    # extract policy variations from capabilities
    capabilities = highest_priority_source.get("capabilities", {})
    sw_update = capabilities.get("com", {}).get("poly", {}).get("software_update", {})
    policy_variations = sw_update.get("policy_variations", {})

    return policy_variations
