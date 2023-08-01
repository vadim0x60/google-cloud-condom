import functions_framework
import base64
import requests
import json
import logging
import condom

logging.basicConfig(level=logging.DEBUG)

project_id_endpoint = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
r = requests.get(project_id_endpoint, headers={"Metadata-Flavor": "Google"})
this_project_name = "projects/{}".format(r.text)

@functions_framework.cloud_event
def on_budget_reached(cloud_event):
    attrs = cloud_event.data["message"]["attributes"]
    data = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))
    
    # Suicide is always counterproductive
    protected_projects = [this_project_name]

    return condom.on_budget_reached({**attrs, **data}, protected_projects)