#!/usr/bin/env python3
"""Deploy Condom, a Cloud Function that disables billing on projects whose budget runs out.

Condom listens on the Pub/Sub topic budgetreached in the project it runs in. Connect
any budget to that topic, and when the budget is reached Condom disables billing on
the projects it covers. It never disables billing on the project it runs in.

    ./condom.py deploy PROJECT_ID              # arm it
    ./condom.py deploy PROJECT_ID --dry-run    # only log what it would shut down

Rerun deploy at any time to update Condom. Every command shells out to gcloud and prints it first.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

TOPIC = "budgetreached"
FUNCTION = "capBudget"
SOURCE = Path(__file__).resolve().parent / "function"
APIS = [
    # The APIs Condom calls
    "cloudbilling.googleapis.com", "billingbudgets.googleapis.com", "cloudresourcemanager.googleapis.com",
    # The ones 2nd gen Cloud Functions are built on
    "cloudfunctions.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
    "run.googleapis.com", "eventarc.googleapis.com", "pubsub.googleapis.com",
]


class GcloudError(Exception):
    def __init__(self, cmd, stderr):
        super().__init__(f"{shlex.join(cmd)} failed:\n{stderr.strip()}")
        self.stderr = stderr


def gcloud(*args, fmt="json"):
    cmd = ["gcloud", *args, "--quiet"] + ([f"--format={fmt}"] if fmt else [])
    print("+", shlex.join(cmd), file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise GcloudError(cmd, result.stderr)
    if fmt == "json":
        return json.loads(result.stdout) if result.stdout.strip() else None
    return result.stdout.strip()


def describe(*args):
    """gcloud's JSON output, or None if the resource doesn't exist."""
    try:
        return gcloud(*args)
    except GcloudError as e:
        if "NOT_FOUND" in e.stderr or "not found" in e.stderr.lower():
            return None
        raise


def service_account(project, region):
    return gcloud("functions", "describe", FUNCTION, "--gen2", f"--region={region}", f"--project={project}",
                  fmt="value(serviceConfig.serviceAccountEmail)")


def deploy(project, region, dry_run=False):
    """Deploy Condom to PROJECT and let it shut down every project you can see, and return its service account."""
    gcloud("services", "enable", *APIS, f"--project={project}", fmt="none")
    # --retry makes Pub/Sub redeliver the notification if a shutdown fails.
    gcloud("functions", "deploy", FUNCTION, "--gen2", "--entry-point=on_budget_reached", "--runtime=python311",
           f"--source={SOURCE}", f"--region={region}", f"--project={project}", f"--trigger-topic={TOPIC}", "--retry",
           f"--set-env-vars=GOOGLE_CLOUD_PROJECT={project},DRY_RUN={int(dry_run)}", fmt="none")
    member = f"--member=serviceAccount:{service_account(project, region)}"

    # Billing Account Administrator lets Condom list and unlink every project on the account,
    # including projects created after this deployment.
    for account in gcloud("billing", "accounts", "list", "--filter=open=true", fmt="value(name.basename())").split():
        gcloud("billing", "accounts", "add-iam-policy-binding", account, member, "--role=roles/billing.admin", fmt="none")

    # Browser lets Condom translate the project numbers in project-scoped budgets into project IDs.
    # Projects created later lack it; a project-scoped budget covering them shuts down the whole account.
    # sandbox.py avoids this by granting Browser on the folder its projects live in.
    for project_id in gcloud("projects", "list", fmt="value(projectId)").split():
        gcloud("projects", "add-iam-policy-binding", project_id, member, "--role=roles/browser", "--condition=None",
               fmt="none")
    return member.removeprefix("--member=serviceAccount:")


def region_argument():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--region", default=os.environ.get("REGION", "us-central1"), help="Condom's region [$REGION]")
    return parser


def run(args):
    try:
        args.run(args)
    except GcloudError as e:
        raise SystemExit(str(e))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(required=True)
    command = commands.add_parser("deploy", parents=[region_argument()], help=deploy.__doc__)
    command.add_argument("project", help="project to run Condom in")
    command.add_argument("--dry-run", action="store_true", help="only log what Condom would shut down")
    command.set_defaults(run=lambda args: print(deploy(args.project, args.region, args.dry_run)))
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
