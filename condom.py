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
def defuse_billing_account(billing_account_name, except_project=None):
    for project in list_associated_projects(billing_account_name):
        if except_project and project.name == except_project:
          # Suicide is always counterproductive
          continue

        disable_billing_for_project(project.name)