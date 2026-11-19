# Google Cloud Condom

The cost of raising a child ranges from $233,610 to $284,570 for middle-income families in the United States. And [you get a child!](https://www.goodreads.com/book/show/10266902-selfish-reasons-to-have-more-kids). The same amount of money I would spend if I accidentally left my [innocent-seeming experiment](https://www.reddit.com/r/googlecloud/comments/14a3epc/post_mortem_how_i_was_charged_4000_eur_for/) with Google Cloud running for 2-3 weeks. [And what are the universities thinking? They go out of their way to ensure their students are well supplied with contraceptives, and yet they're hosting cloud tutorials and giving out student cloud credits left and right.](https://youtu.be/ii1jcLg-eIQ?t=988)

I am here with a solution. Google Cloud Condom is a Google Cloud Function that will automatically shut down your project(s) when you reach your budget limit and prevent further spending. 

*Warning 1*. Condom shuts down your projects by disabling their billing. This can and almost certainly *will lead to irreversible data loss*. Condom is meant for people who prefer irreversible data loss to irreversible financial loss. Condom only gets activated when 100% of your budget is reached and it is possible to set up budget alerts for 50%, 75% or any other percentage of the budget. It is recommended that you set up an alert for 30% or even lower so that you can get an alert and pull out gracefully.

*Warning 2* Google's budget alerts can arrive with a delay. Condom caps your spending at 100% of the budget + spending that occured during the alert delay. No protection is perfect.

*Warning 3* If a budget is limited to specific projects, Condom only shuts down those projects. A budget that covers the whole billing account, or one Condom can't resolve to a list of projects (for example a budget limited to folders or organizations), shuts down every project on the billing account. Condom never shuts down the project it runs in.

*Warning 4* Google can't unlink a project whose [billing link is locked](https://cloud.google.com/billing/docs/how-to/secure-project-billing-account-link), so Condom can't shut such projects down. It keeps retrying and logs an error for them.

## Condom

`condom.py` deploys the Cloud Function. You need the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) and Python 3.

```
./condom.py deploy PROJECT_ID              # arm it
./condom.py deploy PROJECT_ID --dry-run    # only log what it would shut down
```

1. Create a Google Cloud project for Condom to run in. Note its `PROJECT_ID`.
2. Clone this repository and run `./condom.py deploy PROJECT_ID`. Rerun it at any time to update Condom. Pass `--region` (or set `REGION`) to deploy outside `us-central1`.
3. [Create a budget](https://cloud.google.com/billing/docs/how-to/budgets) in your [Google Cloud Billing Account](https://console.cloud.google.com/billing). Tick "Connect a Pub/Sub topic to this budget" and choose `projects/PROJECT_ID/topics/budgetreached`. The budget can cover any projects and billing accounts; they don't have to be related to `PROJECT_ID`.
4. Enjoy your time with Google Cloud.

Condom doesn't manage your budgets: when one is reached, it shuts down the projects that budget covers. `deploy` gives Condom Billing Account Administrator on every open billing account you can see, so it can unlink any of their projects, and Browser on every project you can see, so it can resolve the project numbers in budgets. Projects created later lack Browser (see Warning 3); `sandbox.py` avoids that by granting it on a folder.

*Note* It is allowed and intended to have many budgets connected to the same topic. When a budget is reached, a message is published on the topic with all the details of that budget. Condom will evaluate the blast radius of projects linked to that particular budget and shut them down. You only need to do one deployment per topic and the intended use case is having one Condom for all of you billing accounts.

## Sandboxes

This repository has three tools, each built on the one before:

* **`condom.py`** deploys the kill switch described above. Its Cloud Function lives in `function/`.
* **`sandbox.py`**, which hands out Google Cloud projects that their members can't overspend. Use it for anyone you don't trust with your bill, such as students, contractors, CI pipelines or AI agents.
* **`amp_orbs.py`**, an adapter that gives each [Amp](https://ampcode.com) project a sandbox. See [Amp orbs](#amp-orbs).

A sandbox's members get `roles/owner` (or `--role`) on its project and nothing else. A monthly budget that they can't edit makes Condom disable the project's billing when it runs out. A deny policy stops them from raising their own limits. Run `sandbox.py` as a Google Cloud admin, locally or in Cloud Shell. It needs only `gcloud` and Python 3, and it prints every `gcloud` command before running it. Every step checks before it changes anything, so rerunning a command after a failure picks up where it stopped.

*Status*: `sandbox.py` and `amp_orbs.py` haven't run against Google Cloud yet; their tests use a model of `gcloud`. Try them in a test folder first, and run `bootstrap` with `--dry-run` so Condom only logs what it would shut down. [First run](#first-run) lists what may need adjusting.

You need an organization: deny policies can't be used without one. Create a folder for the sandboxes. You need these roles:

* Project Creator and Folder IAM Admin on the folder
* Deny Admin (`roles/iam.denyAdmin`) on the organization, the only place it can be granted
* Billing Account Administrator

Everything `sandbox.py` creates is inside the folder, apart from budgets on the billing account and the roles `condom.py deploy` gives Condom (see [Condom](#condom)). Then:

```
export SANDBOX_ADMIN_PROJECT=sandbox-admin SANDBOX_BILLING_ACCOUNT=0X0X0X-0X0X0X-0X0X0X SANDBOX_PARENT=folders/123456789
./sandbox.py bootstrap --dry-run    # rerun without --dry-run to arm Condom
./sandbox.py add alice-experiments --member=user:alice@example.com --budget=50EUR
```

`bootstrap` runs once. It creates the admin project, deploys Condom there with `condom.py deploy`, and lets Condom look up every project in the folder. Sandbox members get no access to the admin project.

`add` creates or repairs one sandbox, in this order:

1. It creates the project in the folder and links billing.
2. It creates a monthly budget scoped to the project and connected to Condom's topic. The budget is read-only for project owners, who could otherwise edit it.
3. It applies a deny policy to the project.
4. It grants the members the role on the project, and on that project only.

It prints the project ID. Rerun `add` at any time to repair drift. The budget records which project belongs to which sandbox, and members can't edit it. After Condom has disabled billing, rerunning won't turn billing back on unless you pass `--relink-billing`.

The deny policy applies to everyone except the admins (`--admin`, by default you) and Condom. Members are included, and so are service accounts they create. It blocks:

* quota increases (`serviceusage` and `cloudquotas` `quotas.update`)
* linking or unlinking billing (`projects.createBillingAssignment`, `projects.deleteBillingAssignment`)
* moving the project out of the folder (`projects.move`)
* purchases that keep costing money after billing is disabled: Compute Engine and BigQuery commitments, and domain registrations
* creating service account keys (`--allow-sa-keys` turns this off)

Editing deny policies isn't one of the [permissions a deny policy can block](https://cloud.google.com/iam/docs/deny-permissions-support), and it doesn't need to be: `roles/owner` lacks `iam.denypolicies.create`, `update` and `delete`, custom roles can't contain them, and Deny Admin can't be granted on a project. Members get no billing account roles.

Google Cloud now has native [spend caps](https://cloud.google.com/billing/docs/how-to/budgets-spend-caps), which pause a service without deleting anything. They cover only a few services, such as Gemini and Cloud Run, and project owners can lift them, so they don't replace Condom. You can add them as a faster first line of defense.

## Amp orbs

`amp_orbs.py` gives each Amp project a sandbox that its orbs sign in to with [Workload Identity Federation](https://ampcode.com/docs/orbs/handling-secrets#google-cloud), with no service account keys. It takes the same flags and environment variables as `sandbox.py`:

```
./amp_orbs.py bootstrap --user-id=user_01K9X5152M9X3RVA3NAPHXARZD
./amp_orbs.py add 01a1f071-f1b8-7239-823c-b0e022e23d1b --budget=50EUR > amp-setup.sh
```

`bootstrap` runs `sandbox.py bootstrap`, then creates the `amp-orbs` identity pool and its `amp` provider in the admin project. The provider accepts tokens where `token_use == 'exchanged'` that come from a listed Amp user or a listed Amp project. Setup-time tokens have no `user_id`, so they get in through their project.

`add` creates the sandbox `amp-UUID`, whose only member is the Amp project's principal set. It then adds the Amp project to the provider's condition. It prints what the Amp project's `.agents/setup` needs: the Google Cloud project ID, the audience, a credential helper, the credential file and the environment variables.

## First run

Things to watch for:

* Google may refuse to grant `roles/owner` to an Amp principal set. If it does, pass `--role=roles/editor`.
* The Amp provider's subject mapping uses `has(...) ? ... : ...`. If Google rejects it, map `google.subject` to `assertion.sub`. Have the credential helper keep `--subject-scope project` so the subject stays under 127 bytes.
* The Amp provider's condition holds about 90 Amp projects before it reaches Google's 4,096-character limit.

## Development

```
pip install -r requirements-dev.txt
pytest
```

The tests run the Cloud Function against an in-memory model of Cloud Billing, and the three tools against an in-memory model of `gcloud`, so they need no Google Cloud account.
