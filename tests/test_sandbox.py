"""Runs sandbox.py against an in-memory model of gcloud."""
import pytest

import condom
import sandbox
from fake_gcloud import ACCOUNT, ADMIN, COMMON_FLAGS, CONDOM, FakeGcloud


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeGcloud()
    monkeypatch.setattr(condom, "gcloud", fake)
    return fake


def add(*args):
    sandbox.main(["add", *args, *COMMON_FLAGS])


def test_add_sets_up_a_guarded_project(cloud, capsys):
    add("alice-experiments", "--member=user:alice@example.com", "--budget=50EUR")
    pid = "alice-experiments"
    assert capsys.readouterr().out.strip() == pid
    assert cloud.projects[pid]["billing"] == ACCOUNT

    [budget] = cloud.budgets
    assert budget["flags"]["filter-projects"] == f"projects/{cloud.projects[pid]['number']}"
    assert budget["flags"]["ownership-scope"] == "billing-account"  # read-only for the project's owners
    assert budget["flags"]["notifications-rule-pubsub-topic"] == f"projects/{ADMIN}/topics/budgetreached"

    rule = cloud.deny[f"cloudresourcemanager.googleapis.com/projects/{pid}"]["rules"][0]["denyRule"]
    assert rule["deniedPrincipals"] == ["principalSet://goog/public:all"]
    assert set(rule["exceptionPrincipals"]) == {"principal://goog/subject/admin@example.com",
                                                f"principal://iam.googleapis.com/projects/-/serviceAccounts/{CONDOM}"}
    assert "cloudquotas.googleapis.com/quotas.update" in rule["deniedPermissions"]
    assert sandbox.SA_KEY_PERMISSION in rule["deniedPermissions"]

    assert cloud.bindings == {(pid, "user:alice@example.com", "roles/owner")}
    steps = [c[:3] for c in cloud.changes()]
    assert steps.index(("iam", "policies", "create")) < steps.index(("projects", "add-iam-policy-binding", pid))


def test_rerun_finds_the_project_through_its_budget_and_changes_nothing_new(cloud):
    add("alice-experiments", "--member=user:alice@example.com", "--budget=50", "--project-id=alice-gcp")
    before = len(cloud.changes())
    add("alice-experiments", "--member=user:alice@example.com")
    rerun = cloud.changes()[before:]
    assert not [c for c in rerun if "create" in c[:3] or "link" in c[:3]]
    assert ("billing", "budgets", "update") in [c[:3] for c in rerun]
    assert {p for p, _, _ in cloud.bindings} == {"alice-gcp"}
    with pytest.raises(SystemExit):
        add("alice-experiments", "--member=user:alice@example.com", "--project-id=another-project")


def test_rerun_does_not_undo_the_kill_switch(cloud):
    add("alice-experiments", "--member=user:alice@example.com", "--budget=50")
    cloud.projects["alice-experiments"]["billing"] = None  # Condom fired
    with pytest.raises(SystemExit, match="relink-billing"):
        add("alice-experiments", "--member=user:alice@example.com")
    assert cloud.projects["alice-experiments"]["billing"] is None
    add("alice-experiments", "--member=user:alice@example.com", "--budget=100", "--relink-billing")
    assert cloud.projects["alice-experiments"]["billing"] == ACCOUNT


def test_the_admin_project_is_never_a_sandbox(cloud):
    with pytest.raises(SystemExit):
        add("alice-experiments", "--member=user:alice@example.com", "--budget=50", f"--project-id={ADMIN}")
    assert not cloud.bindings
