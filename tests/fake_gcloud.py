"""An in-memory model of the gcloud commands condom.py, sandbox.py and amp_orbs.py use."""
import json

import condom

ADMIN, ACCOUNT, PARENT = "sandbox-admin", "0X0X0X-0X0X0X-0X0X0X", "folders/9"
CONDOM = "condom@sandbox-admin.iam.gserviceaccount.com"
NOT_FOUND = "ERROR: (gcloud) NOT_FOUND: Requested entity was not found."
COMMON_FLAGS = [f"--admin-project={ADMIN}", f"--billing-account={ACCOUNT}", f"--parent={PARENT}"]


class FakeGcloud:
    def __init__(self):
        self.projects = {ADMIN: {"number": "100", "billing": ACCOUNT}}
        self.budgets, self.deny, self.bindings, self.calls = [], {}, set(), []
        self.provider = None
        self.billing_accounts, self.folder_bindings, self.function = [ACCOUNT, "OTHER-ACCOUNT"], set(), None

    def __call__(self, *args, fmt="json"):
        self.calls.append(args)
        flags = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
        match tuple(a for a in args if not a.startswith("--")):
            case ("config", "get-value", "account"):
                return "admin@example.com"
            case ("functions", "describe", _):
                return CONDOM
            case ("projects", "list") if "filter" not in flags:
                return " ".join(self.projects)
            case ("projects", "list"):
                pid = flags["filter"].removeprefix("projectId=")
                return [{"projectId": pid, "parent": {"type": "folder", "id": "9"}}] if pid in self.projects else []
            case ("projects", "create", pid):
                self.projects[pid] = {"number": str(100 + len(self.projects)), "billing": None}
            case ("projects", "describe", key):
                pid = next(p for p, v in self.projects.items() if key in (p, v["number"]))
                return self.projects[pid]["number"] if fmt == "value(projectNumber)" else pid
            case ("billing", "projects", "describe", pid):
                account = self.projects[pid]["billing"]
                return {"billingEnabled": bool(account), "billingAccountName": f"billingAccounts/{account}" if account else ""}
            case ("billing", "projects", "link", pid):
                self.projects[pid]["billing"] = flags["billing-account"]
            case ("billing", "budgets", "list"):
                return self.budgets
            case ("billing", "budgets", "create"):
                self.budgets.append({"name": f"billingAccounts/{ACCOUNT}/budgets/{len(self.budgets)}",
                                     "displayName": flags["display-name"], "flags": flags,
                                     "budgetFilter": {"projects": [flags["filter-projects"]]}})
            case ("billing", "budgets", "update", name):
                next(b for b in self.budgets if b["name"] == name)["flags"].update(flags)
            case ("iam", "policies", "get", _):
                if flags["attachment-point"] not in self.deny:
                    raise condom.GcloudError(list(args), NOT_FOUND)
                return {"etag": "e1"}
            case ("iam", "policies", "create" | "update", _):
                with open(flags["policy-file"]) as f:
                    self.deny[flags["attachment-point"]] = json.load(f)
            case ("projects", "add-iam-policy-binding", pid):
                self.bindings.add((pid, flags["member"], flags["role"]))
            case ("iam", "workload-identity-pools", "providers", "describe", _):
                if self.provider is None:
                    raise condom.GcloudError(list(args), NOT_FOUND)
                return self.provider
            case ("iam", "workload-identity-pools", "providers", "update-oidc", _):
                mapping = flags["attribute-mapping"].removeprefix("^;^")
                self.provider = {"attributeCondition": flags["attribute-condition"],
                                 "attributeMapping": dict(kv.split("=", 1) for kv in mapping.split(";")),
                                 "oidc": {"issuerUri": flags["issuer-uri"], "allowedAudiences": [flags["allowed-audiences"]]}}
            case ("services", "enable", *_):
                pass
            case ("functions", "deploy", _):
                self.function = flags
            case ("billing", "accounts", "list"):
                return "\n".join(self.billing_accounts)
            case ("billing", "accounts", "add-iam-policy-binding", account):
                self.bindings.add((account, flags["member"], flags["role"]))
            case ("resource-manager", "folders", "add-iam-policy-binding", folder):
                self.folder_bindings.add((folder, flags["member"], flags["role"]))
            case ("iam", "workload-identity-pools", "describe", _):
                return {"name": "pool"}
            case _:
                raise AssertionError(f"unexpected gcloud call {args}")

    def changes(self):
        return [c for c in self.calls if {"create", "link", "update", "update-oidc", "add-iam-policy-binding"} & set(c[:4])]
