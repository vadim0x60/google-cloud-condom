import base64
import functools
import json
import logging
import os

import functions_framework
import requests

import condom

logging.basicConfig(level=logging.INFO)


@functools.cache
def this_project_id():
    if project_id := os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return project_id
    r = requests.get(
        "http://metadata.google.internal/computeMetadata/v1/project/project-id",
        headers={"Metadata-Flavor": "Google"},
        timeout=5,
    )
    r.raise_for_status()
    return r.text


@functions_framework.cloud_event
def on_budget_reached(cloud_event):
    attrs = cloud_event.data["message"]["attributes"]
    data = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))

    # Suicide is always counterproductive
    protected_projects = {this_project_id()}
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

    condom.on_budget_reached({**attrs, **data}, protected_projects, dry_run)
