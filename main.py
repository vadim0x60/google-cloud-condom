import base64
import functions_framework
import requests
from google.cloud import resourcemanager_v3, billing_v1
import json

project_id_endpoint = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
this_project_name = "projects/{}".format(requests.get(project_id_endpoint, headers={"Metadata-Flavor": "Google"}))

projects_client = resourcemanager_v3.ProjectsClient()
billing_client = billing_v1.CloudBillingClient()

def list_associated_projects(billing_account_name):
    request = resourcemanager_v3.SearchProjectsRequest(
        query="state:ACTIVE"
    )
    page_result = projects_client.search_projects(request=request)

    for project in page_result:
        req = billing_v1.GetProjectBillingInfoRequest(name=project.name)
        billing_info = billing_client.get_project_billing_info(request=req)
        if billing_info.billing_account_name == billing_account_name:
            yield project

def disable_billing_for_project(project_name):
    print("Disabling billing for project: {}".format(project_name))
    req = billing_v1.UpdateProjectBillingInfoRequest(
        name=project_name,
        project_billing_info=billing_v1.ProjectBillingInfo(
            billing_account_name=""
        )
    )
    billing_client.update_project_billing_info(
        request=req
    )

def defuse_billing_account(billing_account_name):
    for project in list_associated_projects(billing_account_name):
        if project.name == this_project_name:
          # Suicide is always counterproductive
          continue

        disable_billing_for_project(project.name)

@functions_framework.cloud_event
def on_budget_reached(cloud_event):
    attrs = cloud_event.data["message"]["attributes"]
    data = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))
    print(data)
    
    billing_account_id = attrs["billingAccountId"]
    billing_account_name = f"billingAccounts/{billing_account_id}"
    spent = float(data["costAmount"])
    limit = float(data["budgetAmount"])

    if spent >= limit:
      defuse_billing_account(billing_account_name)
