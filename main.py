import functions_framework
from logwrap import logwrap
import base64
import requests
import json
import logging
from condom import defuse_billing_account

logging.basicConfig(level=logging.DEBUG)

project_id_endpoint = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
this_project_name = "projects/{}".format(requests.get(project_id_endpoint, headers={"Metadata-Flavor": "Google"}))

@functions_framework.cloud_event
@logwrap
def on_budget_reached(cloud_event):
    attrs = cloud_event.data["message"]["attributes"]
    data = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))
    
    billing_account_id = attrs["billingAccountId"]
    billing_account_name = f"billingAccounts/{billing_account_id}"
    spent = float(data["costAmount"])
    limit = float(data["budgetAmount"])

    if spent >= limit:
      defuse_billing_account(billing_account_name, 
                             except_project=this_project_name)