from google.cloud import resourcemanager_v3, billing_v1
from logwrap import logwrap

projects_client = resourcemanager_v3.ProjectsClient()
billing_client = billing_v1.CloudBillingClient()

@logwrap
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

@logwrap
def disable_billing_for_project(project_name):
    req = billing_v1.UpdateProjectBillingInfoRequest(
        name=project_name,
        project_billing_info=billing_v1.ProjectBillingInfo(
            billing_account_name=""
        )
    )
    billing_client.update_project_billing_info(
        request=req
    )

@logwrap
def defuse_billing_account(billing_account_name, protected_projects=[]):
    for project in list_associated_projects(billing_account_name):
        if project.name in protected_projects:
          continue

        disable_billing_for_project(project.name)

@logwrap
def on_budget_reached(event, protected_projects=[]):
    billing_account_id = event["billingAccountId"]
    billing_account_name = f"billingAccounts/{billing_account_id}"
    spent = float(event["costAmount"])
    limit = float(event["budgetAmount"])

    if spent >= limit:
      defuse_billing_account(billing_account_name, protected_projects)