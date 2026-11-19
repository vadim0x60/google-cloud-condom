#!/usr/bin/env python3
"""Amp adapter for sandbox.py: one sandbox per Amp project, signed in to from Amp orbs.

An identity pool in the sandbox admin project trusts Amp's ID tokens (Workload
Identity Federation), and each Amp project's principal set is the only member of
its sandbox. See https://ampcode.com/docs/orbs/handling-secrets#google-cloud.

    ./amp_orbs.py bootstrap --user-id=USER   # once: sandbox bootstrap, identity pool and provider
    ./amp_orbs.py add UUID --budget=50EUR    # per Amp project; prints its .agents/setup

Rerun add at any time to repair drift. Every command shells out to gcloud and prints it first.
"""
import argparse
import json
import re

import condom
import sandbox

POOL = "amp-orbs"
PROVIDER = "amp"
ISSUER = "https://ampcode.com/api/workload-identity"
MAX_CONDITION_LENGTH = 4096  # Google's limit on a provider's attribute condition

# Setup-time tokens have no thread_id; their project-scoped sub is short enough for
# google.subject (127 bytes), unlike the sub of a thread-scoped token.
SUBJECT_MAPPING = "has(assertion.thread_id) ? assertion.thread_id : assertion.sub"
ATTRIBUTE_MAPPING = {"google.subject": SUBJECT_MAPPING, "attribute.project_id": "assertion.project_id"}

AMP_PROJECT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
AMP_USER = re.compile(r"user_[0-9A-Za-z]+")


# The provider's attribute condition doubles as the list of Amp projects.

def cel_list(values):
    return "[" + ", ".join(f"'{v}'" for v in values) + "]"


def attribute_condition(user_ids, amp_projects):
    """Accept exchanged tokens from these Amp users, or from these Amp projects.

    Setup-time tokens have no user_id, so they only pass on their project_id.
    """
    allowed = []
    if user_ids:
        allowed.append(f"(has(assertion.user_id) && assertion.user_id in {cel_list(sorted(user_ids))})")
    if amp_projects:
        allowed.append(f"(has(assertion.project_id) && assertion.project_id in {cel_list(sorted(amp_projects))})")
    return f"assertion.token_use == 'exchanged' && ({' || '.join(allowed) or 'false'})"


def parse_condition(condition):
    """The (user IDs, Amp project IDs) of a condition attribute_condition wrote."""
    def listed(claim):
        match = re.search(rf"assertion\.{claim} in \[([^\]]*)\]", condition)
        return re.findall(r"'([^']*)'", match.group(1)) if match else []

    user_ids, amp_projects = listed("user_id"), listed("project_id")
    if attribute_condition(user_ids, amp_projects) != condition:
        raise SystemExit(
            f"The attribute condition of provider {PROVIDER} wasn't written by this tool:\n  {condition}\n"
            "Rerun bootstrap with --replace-condition and the --user-id flags you want; "
            "then rerun add for every Amp project that should keep access."
        )
    return user_ids, amp_projects


def pool_name(pool_project_number):
    return f"projects/{pool_project_number}/locations/global/workloadIdentityPools/{POOL}"


def audience(pool_project_number):
    return f"https://iam.googleapis.com/{pool_name(pool_project_number)}/providers/{PROVIDER}"


def principal_set(pool_project_number, amp_project):
    return f"principalSet://iam.googleapis.com/{pool_name(pool_project_number)}/attribute.project_id/{amp_project}"


def sandbox_name(amp_project):
    return f"amp-{amp_project}"


def describe_provider(admin_project):
    return condom.describe("iam", "workload-identity-pools", "providers", "describe", PROVIDER,
                            f"--workload-identity-pool={POOL}", "--location=global", f"--project={admin_project}")


def write_provider(admin_project, pool_project_number, provider, user_ids, amp_projects):
    condition = attribute_condition(user_ids, amp_projects)
    if len(condition) > MAX_CONDITION_LENGTH:
        raise SystemExit(f"The attribute condition would exceed {MAX_CONDITION_LENGTH} characters. "
                         "Create a second provider or pool for more Amp projects.")
    if (provider and provider.get("attributeCondition") == condition
            and provider.get("attributeMapping") == ATTRIBUTE_MAPPING
            and provider.get("oidc", {}).get("issuerUri") == ISSUER
            and provider.get("oidc", {}).get("allowedAudiences") == [audience(pool_project_number)]):
        return
    mapping = ";".join(f"{k}={v}" for k, v in ATTRIBUTE_MAPPING.items())
    condom.gcloud("iam", "workload-identity-pools", "providers", "update-oidc" if provider else "create-oidc",
                   PROVIDER, f"--workload-identity-pool={POOL}", "--location=global", f"--project={admin_project}",
                   f"--issuer-uri={ISSUER}", f"--allowed-audiences={audience(pool_project_number)}",
                   f"--attribute-mapping=^;^{mapping}", f"--attribute-condition={condition}", fmt="none")


def bootstrap(args):
    """Sandbox admin project, plus an identity pool and provider that trust Amp."""
    sandbox.bootstrap(args)
    condom.gcloud("services", "enable", "iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com",
                   f"--project={args.admin_project}", fmt="none")
    if not condom.describe("iam", "workload-identity-pools", "describe", POOL, "--location=global",
                            f"--project={args.admin_project}"):
        condom.gcloud("iam", "workload-identity-pools", "create", POOL, "--location=global",
                       "--display-name=Amp orbs", f"--project={args.admin_project}", fmt="none")
    provider = describe_provider(args.admin_project)
    user_ids, amp_projects = [], []
    if provider and not args.replace_condition:
        user_ids, amp_projects = parse_condition(provider.get("attributeCondition", ""))
    pool_project_number = sandbox.project_number(args.admin_project)
    write_provider(args.admin_project, pool_project_number, provider, args.user_id or user_ids, amp_projects)
    print(f"Provider {pool_name(pool_project_number)}/providers/{PROVIDER} trusts Amp users "
          f"{args.user_id or user_ids} and {len(amp_projects)} Amp project(s). Next: ./amp_orbs.py add AMP_PROJECT_UUID")


def add(args):
    """Sandbox for one Amp project, created or repaired."""
    if not AMP_PROJECT.fullmatch(args.amp_project):
        raise SystemExit(f"{args.amp_project!r} isn't an Amp project UUID")
    provider = describe_provider(args.admin_project)
    if not provider:
        raise SystemExit("Run ./amp_orbs.py bootstrap first.")
    user_ids, amp_projects = parse_condition(provider.get("attributeCondition", ""))
    pool_project_number = sandbox.project_number(args.admin_project)
    project_id = sandbox.add(args, sandbox_name(args.amp_project), [principal_set(pool_project_number, args.amp_project)])
    write_provider(args.admin_project, pool_project_number, provider, user_ids, set(amp_projects) | {args.amp_project})
    print(setup_instructions(args.amp_project, project_id, pool_project_number))


HELPER = """#!/usr/bin/env bash
# Prints an Amp ID token in the format Google's executable-sourced credentials expect.
set -euo pipefail
token="$(amp orb id-token --audience '{audience}' --subject-scope project)"
AMP_ID_TOKEN="$token" python3 - <<'PY'
import base64, json, os
token = os.environ['AMP_ID_TOKEN']
payload = token.split('.')[1]
payload += '=' * (-len(payload) % 4)
print(json.dumps({{
    'version': 1,
    'success': True,
    'token_type': 'urn:ietf:params:oauth:token-type:id_token',
    'id_token': token,
    'expiration_time': json.loads(base64.urlsafe_b64decode(payload))['exp'],
}}))
PY
"""


def setup_instructions(amp_project, project_id, pool_project_number):
    provider = f"//iam.googleapis.com/{pool_name(pool_project_number)}/providers/{PROVIDER}"
    credentials = {
        "universe_domain": "googleapis.com",
        "type": "external_account",
        "audience": provider,
        "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
        "token_url": "https://sts.googleapis.com/v1/token",
        "credential_source": {"executable": {"command": "$HOME/.local/bin/amp-gcp-identity", "timeout_millis": 30000}},
    }
    env = {
        "GOOGLE_CLOUD_PROJECT": project_id,
        "CLOUDSDK_CORE_PROJECT": project_id,
        "GOOGLE_CLOUD_QUOTA_PROJECT": project_id,
        "CLOUDSDK_BILLING_QUOTA_PROJECT": project_id,
        "GOOGLE_APPLICATION_CREDENTIALS": "$HOME/.config/gcloud/amp-external-account.json",
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE": "$HOME/.config/gcloud/amp-external-account.json",
        "GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES": "1",
    }
    return f"""\
# Amp project {amp_project} -> Google Cloud project {project_id}
#   principal set: {principal_set(pool_project_number, amp_project)}
#   provider:      {provider}
#   audience:      {audience(pool_project_number)}
#
# Add this to the Amp project's .agents/setup. Also set the exports below as the Amp
# project's environment variables, with $HOME expanded, so agent shells get them.
mkdir -p "$HOME/.local/bin" "$HOME/.config/gcloud"
cat > "$HOME/.local/bin/amp-gcp-identity" <<'HELPER'
{HELPER.format(audience=audience(pool_project_number))}HELPER
chmod +x "$HOME/.local/bin/amp-gcp-identity"
cat > "$HOME/.config/gcloud/amp-external-account.json" <<JSON
{json.dumps(credentials, indent=2)}
JSON
""" + "".join(f'export {k}="{v}"\n' for k, v in env.items())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(required=True)
    boot = commands.add_parser("bootstrap", parents=[sandbox.bootstrap_arguments()], help=bootstrap.__doc__)
    boot.add_argument("--user-id", action="append", help="Amp user whose threads may sign in to the pool from any "
                      "project, such as user_01K9X5152M9X3RVA3NAPHXARZD; repeatable. Default: keep the current ones")
    boot.add_argument("--replace-condition", action="store_true", help="overwrite a provider condition this tool didn't write")
    boot.set_defaults(run=bootstrap)
    new = commands.add_parser("add", parents=[sandbox.common_arguments(), sandbox.sandbox_arguments()], help=add.__doc__)
    new.add_argument("amp_project", help="Amp project UUID")
    new.set_defaults(run=add)

    args = parser.parse_args(argv)
    for user_id in getattr(args, "user_id", None) or []:
        if not AMP_USER.fullmatch(user_id):
            parser.error(f"{user_id!r} isn't an Amp user ID")
    sandbox.run(parser, args)


if __name__ == "__main__":
    main()
