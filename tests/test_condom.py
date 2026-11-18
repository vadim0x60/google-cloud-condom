"""Runs the Cloud Function against an in-memory model of Cloud Billing.

Billing account A pays for the project Condom runs in and two other projects;
billing account B pays for one more project.
"""
import base64
import json

import pytest
from cloudevents.http import CloudEvent
from google.api_core import exceptions
from google.cloud import billing_v1, resourcemanager_v3
from google.cloud.billing import budgets_v1

import condom
import main

HOST = "condom-host"
PROJECTS = {  # project ID: (project number, billing account)
    HOST: ("111", "billingAccounts/A"),
    "victim-1": ("222", "billingAccounts/A"),
    "victim-2": ("333", "billingAccounts/A"),
    "other-account": ("444", "billingAccounts/B"),
}


class FakeGoogleCloud:
    def __init__(self):
        self.billing = {pid: account for pid, (_, account) in PROJECTS.items()}
        self.budgets = {}
        self.failing = set()

    # Cloud Billing
    def list_project_billing_info(self, name):
        return [
            billing_v1.ProjectBillingInfo(
                name=f"projects/{pid}/billingInfo", project_id=pid,
                billing_account_name=account, billing_enabled=True,
            )
            for pid, account in self.billing.items() if account == name
        ]

    def update_project_billing_info(self, name, project_billing_info):
        pid = name.removeprefix("projects/")
        if pid in self.failing:
            raise exceptions.PermissionDenied(f"cannot unlink {pid}")
        self.billing[pid] = project_billing_info.billing_account_name

    # Budgets
    def get_budget(self, name):
        if name not in self.budgets:
            raise exceptions.NotFound(name)
        return self.budgets[name]

    # Resource Manager
    def get_project(self, name):
        number = name.removeprefix("projects/")
        pid = next(pid for pid, (num, _) in PROJECTS.items() if num == number)
        return resourcemanager_v3.Project(name=name, project_id=pid)

    def add_budget(self, budget_id, **budget_filter):
        self.budgets[f"billingAccounts/A/budgets/{budget_id}"] = budgets_v1.Budget(
            budget_filter=budgets_v1.Filter(**budget_filter)
        )

    def unbilled(self):
        return {pid for pid, account in self.billing.items() if not account}


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeGoogleCloud()
    for client in ("billing_client", "budget_client", "projects_client"):
        monkeypatch.setattr(condom, client, fake)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", HOST)
    monkeypatch.delenv("DRY_RUN", raising=False)
    main.this_project_id.cache_clear()
    return fake


def notify(cost, budget, budget_id="whole-account"):
    """Deliver a budget notification the way Pub/Sub and Eventarc do."""
    data = {"budgetDisplayName": "test", "costAmount": cost, "budgetAmount": budget,
            "currencyCode": "EUR", "costIntervalStart": "2026-11-01T00:00:00Z"}
    message = {
        "attributes": {"billingAccountId": "A", "budgetId": budget_id, "schemaVersion": "1.0"},
        "data": base64.b64encode(json.dumps(data).encode()).decode(),
    }
    event = CloudEvent({"type": "google.cloud.pubsub.topic.v1.messagePublished", "source": "test"},
                       {"message": message})
    main.on_budget_reached(event)


def test_under_budget_changes_nothing(cloud):
    notify(99.99, 100.0)
    assert cloud.unbilled() == set()


def test_reached_budget_shuts_down_the_account_but_not_condom(cloud):
    notify(100.0, 100.0)
    assert cloud.unbilled() == {"victim-1", "victim-2"}


def test_one_failure_does_not_stop_the_other_shutdowns(cloud):
    cloud.failing = {"victim-1"}
    with pytest.raises(ExceptionGroup) as raised:
        notify(150.0, 100.0)
    assert cloud.unbilled() == {"victim-2"}
    assert "victim-1" in str(raised.value.exceptions[0])


def test_redelivery_after_a_failure_finishes_the_job(cloud):
    cloud.failing = {"victim-1"}
    with pytest.raises(ExceptionGroup):
        notify(150.0, 100.0)
    cloud.failing = set()
    notify(150.0, 100.0)
    assert cloud.unbilled() == {"victim-1", "victim-2"}


@pytest.mark.parametrize("scoped_to", [["projects/222"], ["projects/victim-1"]])
def test_project_budget_shuts_down_only_its_projects(cloud, scoped_to):
    cloud.add_budget("b-1", projects=scoped_to)
    notify(150.0, 100.0, budget_id="b-1")
    assert cloud.unbilled() == {"victim-1"}


def test_project_budget_never_shuts_down_condom(cloud):
    cloud.add_budget("b-1", projects=["projects/111", "projects/333"])
    notify(150.0, 100.0, budget_id="b-1")
    assert cloud.unbilled() == {"victim-2"}


@pytest.mark.parametrize("budget_filter", [{"resource_ancestors": ["folders/9"]}, None])
def test_unknown_scope_falls_back_to_the_whole_account(cloud, budget_filter):
    if budget_filter is not None:
        cloud.add_budget("b-1", **budget_filter)
    notify(150.0, 100.0, budget_id="b-1")  # without a filter, the budget isn't found
    assert cloud.unbilled() == {"victim-1", "victim-2"}


def test_dry_run_disables_nothing(cloud, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    notify(150.0, 100.0)
    assert cloud.unbilled() == set()
