#!/usr/bin/env python3
"""Hand out Google Cloud projects that their members can't overspend.

A sandbox is a Google Cloud project for someone you don't trust with your bill, such
as a student, a contractor, a CI pipeline or an AI agent. Its members get broad access
(roles/owner by default) to that project and nothing else. A monthly budget that they
can't edit makes Condom disable the project's billing when it runs out. A deny policy
stops them from raising quotas, changing the billing link or buying commitments.

    ./sandbox.py bootstrap                                   # once: admin project and Condom
    ./sandbox.py add NAME --member=user:alice@example.com --budget=50EUR

Rerun add at any time to repair drift. Every command shells out to gcloud and prints it first.
"""
import argparse
import json
import os
import re
import tempfile

import condom

DENY_POLICY = "sandbox-spend-guard"

# Permissions nobody but the admins and Condom may use in a sandbox. All of them are on
# https://cloud.google.com/iam/docs/deny-permissions-support. Deny policies themselves
# need no rule: roles/owner lacks iam.denypolicies.create/update/delete, custom roles
# can't contain them, and Deny Admin can only be granted on an organization.
DENIED_PERMISSIONS = [
    # Quota increases, through Service Usage overrides or Cloud Quotas
    "serviceusage.googleapis.com/quotas.update",
    "cloudquotas.googleapis.com/quotas.update",
    # Linking the project to a billing account, or unlinking it
    "cloudresourcemanager.googleapis.com/projects.createBillingAssignment",
    "cloudresourcemanager.googleapis.com/projects.deleteBillingAssignment",
    # Moving the project out of the folder where Condom is allowed to look it up
    "cloudresourcemanager.googleapis.com/projects.move",
    # Purchases that keep billing after Condom disables billing on the project
    "compute.googleapis.com/commitments.create",
    "compute.googleapis.com/commitments.update",
    "bigquery.googleapis.com/capacityCommitments.create",
    "bigquery.googleapis.com/capacityCommitments.update",
    "bigqueryreservation.googleapis.com/capacityCommitments.create",
    "bigqueryreservation.googleapis.com/capacityCommitments.update",
    "domains.googleapis.com/registrations.create",
]
SA_KEY_PERMISSION = "iam.googleapis.com/serviceAccountKeys.create"

NAME = re.compile(r"[a-z][a-z0-9-]{4,49}[a-z0-9]")  # fits in a budget's 60-character display name
PARENT = re.compile(r"(folders|organizations)/[0-9]+")


def principal(member):
    """IAM v2 principal identifier for an allow-policy style member."""
    if member.startswith(("principal://", "principalSet://")):
        return member
    kind, _, email = member.partition(":")
    formats = {
        "user": "principal://goog/subject/{}",
        "group": "principalSet://goog/group/{}",
        "serviceAccount": "principal://iam.googleapis.com/projects/-/serviceAccounts/{}",
    }
    if kind not in formats or not email:
        raise SystemExit(f"Use user:EMAIL, group:EMAIL or serviceAccount:EMAIL, not {member!r}")
    return formats[kind].format(email)


def deny_policy(exception_principals, deny_sa_keys=True):
    return {
        "displayName": "Sandbox members can't raise spending",
        "rules": [{
            "description": "Only admins and Condom change quotas, billing links and commitments.",
            "denyRule": {
                "deniedPrincipals": ["principalSet://goog/public:all"],
                "exceptionPrincipals": sorted(set(exception_principals)),
                "deniedPermissions": DENIED_PERMISSIONS + ([SA_KEY_PERMISSION] if deny_sa_keys else []),
            },
        }],
    }


def budget_name(name):
    return f"sandbox {name}"


def default_project_id(name):
    return name[:30].rstrip("-")  # project IDs have at most 30 characters


# Each step checks before it changes anything.

def project_number(project_id):
    return condom.gcloud("projects", "describe", project_id, fmt="value(projectNumber)")


def ensure_project(project_id, parent):
    found = condom.gcloud("projects", "list", f"--filter=projectId={project_id}")
    if not found:
        kind, number = parent.split("/")
        condom.gcloud("projects", "create", project_id, f"--{kind.removesuffix('s')}={number}", fmt="none")
        return
    actual = f"{found[0]['parent']['type']}s/{found[0]['parent']['id']}"
    if actual != parent:
        raise SystemExit(f"{project_id} is in {actual}, not {parent}. Move it or pass the right --parent.")


def ensure_billing(project_id, billing_account, may_enable):
    info = condom.gcloud("billing", "projects", "describe", project_id)
    if info.get("billingEnabled") and info.get("billingAccountName") == f"billingAccounts/{billing_account}":
        return
    if not info.get("billingEnabled") and not may_enable:
        raise SystemExit(
            f"Billing is disabled on {project_id}, probably by Condom because its budget ran out. "
            "Rerun with a higher --budget and --relink-billing to turn it back on."
        )
    condom.gcloud("billing", "projects", "link", project_id, f"--billing-account={billing_account}", fmt="none")


def current_account():
    account = condom.gcloud("config", "get-value", "account", fmt=None)
    if not account:
        raise SystemExit("Sign in with gcloud auth login, or pass --admin.")
    return f"{'serviceAccount' if account.endswith('.gserviceaccount.com') else 'user'}:{account}"


def bootstrap(args):
    """Admin project that runs Condom for every sandbox."""
    ensure_project(args.admin_project, args.parent)
    ensure_billing(args.admin_project, args.billing_account, may_enable=True)
    condom_account = condom.deploy(args.admin_project, args.region, args.dry_run)
    # Condom needs to read sandboxes to map a budget's project numbers to project IDs.
    # Granted on the parent so that sandbox members, who own their projects, can't revoke it.
    kind, number = args.parent.split("/")
    condom.gcloud(*(["organizations"] if kind == "organizations" else ["resource-manager", "folders"]),
                  "add-iam-policy-binding", number, f"--member=serviceAccount:{condom_account}",
                  "--role=roles/browser", "--condition=None", fmt="none")


def add(args, name, members):
    """Create or repair the sandbox NAME for MEMBERS, and return its project ID."""
    if not NAME.fullmatch(name):
        raise SystemExit(f"{name!r} isn't a sandbox name: use 6 to 51 lowercase letters, digits and hyphens")

    # The budget, which members can't edit, records which project belongs to the sandbox.
    budgets = condom.gcloud("billing", "budgets", "list", f"--billing-account={args.billing_account}") or []
    budget = next((b for b in budgets if b.get("displayName") == budget_name(name)), None)
    project_id = args.project_id or default_project_id(name)
    if budget:
        budgeted = condom.gcloud("projects", "describe", budget["budgetFilter"]["projects"][0].removeprefix("projects/"),
                          fmt="value(projectId)")
        if args.project_id and args.project_id != budgeted:
            raise SystemExit(f"Sandbox {name} already has project {budgeted}.")
        project_id = budgeted
    elif not args.budget:
        raise SystemExit("Pass --budget, such as --budget=50EUR, the first time you add a sandbox.")
    if project_id == args.admin_project:
        raise SystemExit("The admin project can't be a sandbox.")

    ensure_project(project_id, args.parent)
    # Without a budget, setup never finished and Condom can't have disabled billing yet.
    ensure_billing(project_id, args.billing_account, may_enable=budget is None or args.relink_billing)
    number = project_number(project_id)

    budget_args = [f"--filter-projects=projects/{number}", "--ownership-scope=billing-account",
                   f"--notifications-rule-pubsub-topic=projects/{args.admin_project}/topics/{condom.TOPIC}"]
    if args.budget:
        budget_args.append(f"--budget-amount={args.budget}")
    if budget:
        condom.gcloud("billing", "budgets", "update", budget["name"], *budget_args, fmt="none")
    else:
        condom.gcloud("billing", "budgets", "create", f"--billing-account={args.billing_account}",
               f"--display-name={budget_name(name)}", "--calendar-period=month",
               "--threshold-rule=percent=0.5", "--threshold-rule=percent=0.9", "--threshold-rule=percent=1.0",
               *budget_args, fmt="none")

    # The guard goes on before the members get any access.
    exceptions = [principal(m) for m in args.admin or [current_account()]]
    exceptions.append(principal(f"serviceAccount:{condom.service_account(args.admin_project, args.region)}"))
    attachment = f"--attachment-point=cloudresourcemanager.googleapis.com/projects/{project_id}"
    existing = condom.describe("iam", "policies", "get", DENY_POLICY, attachment, "--kind=denypolicies")
    with tempfile.NamedTemporaryFile("w", suffix=".json") as policy_file:
        json.dump(deny_policy(exceptions, not args.allow_sa_keys), policy_file)
        policy_file.flush()
        if existing:
            condom.gcloud("iam", "policies", "update", DENY_POLICY, attachment, "--kind=denypolicies",
                   f"--policy-file={policy_file.name}", f"--etag={existing['etag']}", fmt="none")
        else:
            condom.gcloud("iam", "policies", "create", DENY_POLICY, attachment, "--kind=denypolicies",
                   f"--policy-file={policy_file.name}", fmt="none")

    for member in members:
        condom.gcloud("projects", "add-iam-policy-binding", project_id, f"--member={member}", f"--role={args.role}",
               "--condition=None", fmt="none")
    return project_id


# Command-line flags, shared with adapters such as amp_orbs.py

def common_arguments():
    parser = argparse.ArgumentParser(add_help=False, parents=[condom.region_argument()])
    for flag, var, text in [
        ("--admin-project", "SANDBOX_ADMIN_PROJECT", "project that runs Condom; no sandbox member gets access to it"),
        ("--billing-account", "SANDBOX_BILLING_ACCOUNT", "billing account ID, such as 0X0X0X-0X0X0X-0X0X0X"),
        ("--parent", "SANDBOX_PARENT", "folders/N or organizations/N to create projects in; deny policies need one"),
    ]:
        parser.add_argument(flag, default=os.environ.get(var), required=var not in os.environ, help=f"{text} [${var}]")
    return parser


def bootstrap_arguments():
    parser = argparse.ArgumentParser(add_help=False, parents=[common_arguments()])
    parser.add_argument("--dry-run", action="store_true", help="deploy Condom so that it only logs what it would shut down")
    return parser


def sandbox_arguments():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--budget", help="monthly budget, such as 50 or 50EUR in the billing account's currency; "
                        "required the first time, kept when omitted")
    parser.add_argument("--project-id", help="ID for a new project (default: the sandbox name, cut to 30 characters)")
    parser.add_argument("--role", default="roles/owner", help="role the members get on the project")
    parser.add_argument("--admin", action="append", help="user:, group: or serviceAccount: exempt from the deny "
                        "policy; repeatable (default: the current gcloud account)")
    parser.add_argument("--allow-sa-keys", action="store_true", help="let members create service account keys")
    parser.add_argument("--relink-billing", action="store_true", help="turn billing back on after Condom disabled it")
    return parser


def run(parser, args):
    if not PARENT.fullmatch(args.parent):
        parser.error(f"--parent must be folders/N or organizations/N, not {args.parent!r}")
    condom.run(args)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(required=True)
    boot = commands.add_parser("bootstrap", parents=[bootstrap_arguments()], help=bootstrap.__doc__)
    boot.set_defaults(run=bootstrap)
    new = commands.add_parser("add", parents=[common_arguments(), sandbox_arguments()], help=add.__doc__)
    new.add_argument("name", help="sandbox name, such as alice-experiments")
    new.add_argument("--member", action="append", required=True,
                     help="IAM member to grant --role, such as user:alice@example.com; repeatable")
    new.set_defaults(run=lambda args: print(add(args, args.name, args.member)))
    run(parser, parser.parse_args(argv))


if __name__ == "__main__":
    main()
