"""Checks the Amp adapter: its provider condition, its sandboxes and its setup script."""
import json
import subprocess

import celpy
import pytest

import amp_orbs
import condom
import sandbox
from fake_gcloud import COMMON_FLAGS, FakeGcloud

ME = "user_01K9X5152M9X3RVA3NAPHXARZD"
P1 = "01a1f071-f1b8-7239-823c-b0e022e23d1b"
P2 = "9f3e0000-0000-4000-8000-000000000002"


def evaluate(expression, assertion):
    env = celpy.Environment()
    return env.program(env.compile(expression)).evaluate({"assertion": celpy.json_to_cel(assertion)})


def token(**claims):
    return {"iss": amp_orbs.ISSUER, "token_use": "exchanged", "sub": "s", **claims}


SETUP = dict(sub=f"workspace:w:project:{P1}", project_id=P1, workspace_id="w")  # no user_id or thread_id
RUNTIME = dict(project_id=P1, user_id="user_SOMEONEELSE", thread_id="T-1", workspace_id="w")


@pytest.mark.parametrize("claims, allowed", [
    (SETUP, True),
    (RUNTIME, True),
    ({**RUNTIME, "project_id": P2}, False),  # another Amp project
    ({**RUNTIME, "project_id": P2, "user_id": ME}, True),  # the listed user, from any project
    ({"user_id": ME, "thread_id": "T-2"}, True),  # the listed user, in a thread without a project
    ({"user_id": "user_SOMEONEELSE", "thread_id": "T-2"}, False),
    ({**SETUP, "token_use": "something-else"}, False),
])
def test_condition_admits_listed_projects_and_users_only(claims, allowed):
    assert bool(evaluate(amp_orbs.attribute_condition([ME], [P1]), token(**claims))) is allowed


def test_condition_without_users_rejects_tokens_without_projects():
    assert not evaluate(amp_orbs.attribute_condition([], [P1]), token(user_id=ME, thread_id="T-2"))


def test_subject_is_the_thread_at_runtime_and_the_project_during_setup():
    assert evaluate(amp_orbs.SUBJECT_MAPPING, token(**RUNTIME)) == "T-1"
    assert evaluate(amp_orbs.SUBJECT_MAPPING, token(**SETUP)) == f"workspace:w:project:{P1}"


def test_condition_round_trips_and_refuses_foreign_conditions():
    assert amp_orbs.parse_condition(amp_orbs.attribute_condition([ME], [P2, P1])) == ([ME], [P1, P2])
    with pytest.raises(SystemExit):
        amp_orbs.parse_condition(f"assertion.workspace_id == 'w' && assertion.project_id == '{P1}'")


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeGcloud()
    fake.provider = {"attributeCondition": amp_orbs.attribute_condition([ME], [])}
    monkeypatch.setattr(condom, "gcloud", fake)
    return fake


def add(*args):
    amp_orbs.main(["add", *args, *COMMON_FLAGS])


def test_each_amp_project_owns_only_its_own_sandbox(cloud, capsys):
    add(P1, "--budget=50EUR")
    add(P2, "--budget=20")
    assert amp_orbs.parse_condition(cloud.provider["attributeCondition"]) == ([ME], [P1, P2])
    pool = "principalSet://iam.googleapis.com/projects/100/locations/global/workloadIdentityPools/amp-orbs"
    assert cloud.bindings == {
        (sandbox.default_project_id(f"amp-{P1}"), f"{pool}/attribute.project_id/{P1}", "roles/owner"),
        (sandbox.default_project_id(f"amp-{P2}"), f"{pool}/attribute.project_id/{P2}", "roles/owner"),
    }
    assert f"{pool}/attribute.project_id/{P2}" in capsys.readouterr().out


def test_setup_instructions_write_working_credentials(tmp_path):
    fake_amp = tmp_path / "bin" / "amp"
    fake_amp.parent.mkdir()
    # A token whose payload is {"exp": 1700000000}; the helper must pass the audience it was given.
    fake_amp.write_text('#!/bin/sh\necho "$@" > "$HOME/amp-args"\necho "x.eyJleHAiOjE3MDAwMDAwMDB9.y"\n')
    fake_amp.chmod(0o755)
    script = amp_orbs.setup_instructions(P1, "my-amp-project", "100")
    env = {"HOME": str(tmp_path), "PATH": f"{fake_amp.parent}:/usr/bin:/bin"}
    subprocess.run(["bash", "-euc", script], env=env, check=True)

    credentials = json.loads((tmp_path / ".config/gcloud/amp-external-account.json").read_text())
    helper = credentials["credential_source"]["executable"]["command"]
    assert helper == f"{tmp_path}/.local/bin/amp-gcp-identity"
    assert credentials["audience"] == "//iam.googleapis.com/projects/100/locations/global/workloadIdentityPools/amp-orbs/providers/amp"
    output = json.loads(subprocess.run([helper], env=env, check=True, capture_output=True, text=True).stdout)
    assert output["expiration_time"] == 1700000000 and output["id_token"].startswith("x.")
    assert (tmp_path / "amp-args").read_text().split() == [
        "orb", "id-token", "--audience", amp_orbs.audience("100"), "--subject-scope", "project"]
