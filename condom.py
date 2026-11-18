import logging

from google.cloud import billing_v1, resourcemanager_v3
from google.cloud.billing import budgets_v1

log = logging.getLogger(__name__)

billing_client = billing_v1.CloudBillingClient()
budget_client = budgets_v1.BudgetServiceClient()
projects_client = resourcemanager_v3.ProjectsClient()


def list_billed_projects(billing_account_name):
    """IDs of the projects whose billing is enabled on this billing account."""
    for info in billing_client.list_project_billing_info(name=billing_account_name):
        if info.billing_enabled:
            yield info.project_id


def budget_scope(billing_account_name, budget_id):
    """IDs of the projects a budget is limited to, or None if it covers the whole account.

    Falls back to the whole account whenever the scope can't be pinned down to a
    list of projects: Condom prefers shutting down too much to shutting down too little.
    """
    try:
        budget = budget_client.get_budget(name=f"{billing_account_name}/budgets/{budget_id}")
        if budget.budget_filter.resource_ancestors or not budget.budget_filter.projects:
            return None
        scope = set()
        for name in budget.budget_filter.projects:
            key = name.removeprefix("projects/")
            if key.isdigit():  # Budgets usually store project numbers
                key = projects_client.get_project(name=name).project_id
            scope.add(key)
        return scope
    except Exception:
        log.exception("Could not read the scope of budget %s, treating it as the whole billing account", budget_id)
        return None


def disable_billing_for_project(project_id):
    billing_client.update_project_billing_info(
        name=f"projects/{project_id}",
        project_billing_info=billing_v1.ProjectBillingInfo(billing_account_name=""),
    )


def on_budget_reached(event, protected_projects=(), dry_run=False):
    """Disable billing on every project the budget in `event` covers.

    `event` is a budget notification: its Pub/Sub attributes merged with its data.
    Raises if billing could not be disabled on some project, after trying all of them.
    """
    spent = float(event["costAmount"])
    limit = float(event["budgetAmount"])
    if spent < limit:
        log.info("Budget %s: spent %s of %s, no action", event.get("budgetId"), spent, limit)
        return

    billing_account_name = f"billingAccounts/{event['billingAccountId']}"
    scope = budget_scope(billing_account_name, event["budgetId"])
    errors = []
    for project_id in list_billed_projects(billing_account_name):
        if project_id in protected_projects or (scope is not None and project_id not in scope):
            log.info("Skipping %s", project_id)
            continue
        if dry_run:
            log.warning("DRY RUN: would disable billing for %s", project_id)
            continue
        try:
            disable_billing_for_project(project_id)
            log.warning("Disabled billing for %s", project_id)
        except Exception as e:
            log.exception("Failed to disable billing for %s", project_id)
            errors.append(e)

    if errors:
        raise ExceptionGroup(f"Failed to disable billing on {len(errors)} project(s)", errors)
