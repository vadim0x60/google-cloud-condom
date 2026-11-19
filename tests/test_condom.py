"""Runs condom.py deploy and sandbox.py bootstrap against an in-memory model of gcloud."""
import pytest

import condom
import sandbox
from fake_gcloud import ACCOUNT, ADMIN, COMMON_FLAGS, CONDOM, FakeGcloud


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeGcloud()
    monkeypatch.setattr(condom, "gcloud", fake)
    return fake


def test_deploy_arms_condom_on_every_account_and_project(cloud, capsys):
    cloud.projects["other-project"] = {"number": "200", "billing": ACCOUNT}
    condom.main(["deploy", ADMIN])
    assert capsys.readouterr().out.strip() == CONDOM
    assert cloud.function["trigger-topic"] == "budgetreached"
    assert cloud.function["set-env-vars"] == f"GOOGLE_CLOUD_PROJECT={ADMIN},DRY_RUN=0"
    assert cloud.function["source"] == str(condom.SOURCE)
    member = f"serviceAccount:{CONDOM}"
    assert cloud.bindings == {
        (ACCOUNT, member, "roles/billing.admin"), ("OTHER-ACCOUNT", member, "roles/billing.admin"),
        (ADMIN, member, "roles/browser"), ("other-project", member, "roles/browser"),
    }


def test_dry_run_deploys_a_harmless_condom(cloud):
    condom.main(["deploy", ADMIN, "--dry-run"])
    assert cloud.function["set-env-vars"].endswith("DRY_RUN=1")


def test_sandbox_bootstrap_lets_condom_read_the_whole_folder(cloud):
    sandbox.main(["bootstrap", *COMMON_FLAGS, "--dry-run"])
    assert cloud.function["set-env-vars"].endswith("DRY_RUN=1")
    assert cloud.folder_bindings == {("9", f"serviceAccount:{CONDOM}", "roles/browser")}
